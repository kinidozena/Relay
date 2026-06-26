"""Test runner for Relay bot.

Two modes:
  python cli_test.py           -- offline: stubs triage with expected_fields, tests routing only
  python cli_test.py --live    -- live: calls Groq, checks intent + action + key fields

Offline mode needs no API key and runs in seconds.
Live mode requires GROQ_API_KEY and bills zero (free tier).
"""
import sys
import json
import os
from pathlib import Path

# ------------------------------------------------------------------
DATA_FILE = Path(__file__).parent / "test_data.json"
REQUESTER = "U_TEST"
CHANNEL = "C_TEST"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"


def _load():
    with open(DATA_FILE) as f:
        return json.load(f)


# ------------------------------------------------------------------
# Offline mode: inject expected_fields directly into triage so we
# test routing logic without any LLM call.
# ------------------------------------------------------------------

def _run_offline(samples: list) -> tuple[int, int]:
    import store
    import triage
    import core

    store.init_db()
    _orig = triage.triage

    passed = failed = 0

    for s in samples:
        fake = {**triage._DEFAULTS, "intent": s["expected_intent"], **s["expected_fields"]}
        # summary must be non-None for new_request tickets
        if fake["intent"] == "new_request" and not fake.get("summary"):
            fake["summary"] = s["description"]

        triage.triage = lambda text, _f=fake: dict(_f)
        result = core.handle_message(s["input"], REQUESTER, CHANNEL)

        checks = []
        checks.append(("intent", s["expected_intent"], result["intent"]))
        checks.append(("action", s["expected_action"], result["action"]))

        failures = [(k, exp, got) for k, exp, got in checks if exp != got]
        ok = not failures

        tag = PASS if ok else FAIL
        passed += ok
        failed += (not ok)

        print(f"{tag}  [{s['id']}] {s['description']}")
        if not ok:
            for k, exp, got in failures:
                print(f"       {k}: expected={exp!r}  got={got!r}")
        else:
            print(f"       intent={result['intent']}  action={result['action']}")

    triage.triage = _orig
    return passed, failed


# ------------------------------------------------------------------
# Live mode: real Groq call, check intent + action + key fields.
# ------------------------------------------------------------------

def _check_fields(expected: dict, result: dict, triage_out: dict) -> list[str]:
    """Return list of failure strings, empty if all pass."""
    failures = []
    ticket = result.get("ticket") or {}

    field_map = {
        "type":        triage_out.get("type", ""),
        "languages":   triage_out.get("languages", []),
        "deadline":    triage_out.get("deadline"),
        "priority":    triage_out.get("priority", "normal"),
        "needs_human": triage_out.get("needs_human", False),
        "missing_info": triage_out.get("missing_info", []),
    }

    for key, exp_val in expected.items():
        got_val = field_map.get(key)

        if key == "languages":
            # check presence, not exact order or casing
            exp_codes = {v.lower() for v in exp_val}
            got_codes = {v.lower() for v in (got_val or [])}
            if not exp_codes.issubset(got_codes):
                failures.append(f"languages: expected {exp_val} subset of got {list(got_codes)}")

        elif key == "missing_info":
            # just check that something was asked, not exact wording
            if exp_val and not got_val:
                failures.append("missing_info: expected questions, got none")

        elif key == "type":
            # loose check: at least one word from expected type in got type
            exp_words = set(exp_val.lower().split())
            got_lower = (got_val or "").lower()
            if not any(w in got_lower for w in exp_words):
                failures.append(f"type: expected ~{exp_val!r}, got {got_val!r}")

        else:
            if got_val != exp_val:
                failures.append(f"{key}: expected={exp_val!r} got={got_val!r}")

    return failures


def _run_live(samples: list) -> tuple[int, int]:
    from dotenv import load_dotenv
    load_dotenv()

    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY not set. Cannot run live mode.")
        sys.exit(1)

    import store
    import triage
    import core

    store.init_db()
    passed = failed = 0

    for s in samples:
        print(f"\n[{s['id']}] {s['description']}")
        print(f"  Input: {s['input'][:80]}{'...' if len(s['input'])>80 else ''}")

        try:
            triage_out = triage.triage(s["input"])
            result = core.handle_message.__wrapped__(s["input"], REQUESTER, CHANNEL) \
                if hasattr(core.handle_message, "__wrapped__") \
                else _live_handle(s["input"], REQUESTER, CHANNEL, triage_out)

            intent_ok = triage_out["intent"] == s["expected_intent"]
            action_ok = result["action"] == s["expected_action"]
            field_failures = _check_fields(s["expected_fields"], result, triage_out)

            ok = intent_ok and action_ok and not field_failures
            tag = PASS if ok else FAIL
            passed += ok
            failed += (not ok)

            print(f"  {tag}  intent={triage_out['intent']}  action={result['action']}")
            print(f"       type={triage_out['type']!r}  languages={triage_out['languages']}"
                  f"  priority={triage_out['priority']}  needs_human={triage_out['needs_human']}")
            if not intent_ok:
                print(f"       intent: expected={s['expected_intent']!r}")
            if not action_ok:
                print(f"       action: expected={s['expected_action']!r}")
            for f in field_failures:
                print(f"       field: {f}")
            print(f"  reply preview: {result['reply'][:120].replace(chr(10),' | ')}...")

        except Exception as e:
            failed += 1
            print(f"  {FAIL}  exception: {e}")

    return passed, failed


def _live_handle(text, requester, channel, triage_out):
    """Call core routing with a pre-computed triage result."""
    import core, store, triage as triage_mod
    _orig = triage_mod.triage
    triage_mod.triage = lambda t: triage_out
    result = core.handle_message(text, requester, channel)
    triage_mod.triage = _orig
    return result


# ------------------------------------------------------------------

def main():
    live = "--live" in sys.argv
    samples = _load()

    print(f"\nRelay test suite — {'LIVE (Groq)' if live else 'OFFLINE (stubbed)'}")
    print(f"{len(samples)} samples  |  {DATA_FILE.name}\n")
    print("-" * 60)

    if live:
        passed, failed = _run_live(samples)
    else:
        passed, failed = _run_offline(samples)

    print("-" * 60)
    total = passed + failed
    status = PASS if failed == 0 else FAIL
    print(f"\n{status}  {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} failed)")
    else:
        print("  — all clear")


if __name__ == "__main__":
    main()
