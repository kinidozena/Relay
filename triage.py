"""LLM triage on Groq's free tier. Free-text request -> structured fields + routing.

Only THIS file talks to a model. store.py / core.py / cli.py are provider-agnostic,
so swapping the model provider is a single-file change.
"""
import os
import json
import re
from groq import Groq

# openai/gpt-oss-120b: current Groq model, strong at structured (JSON) output.
# Lighter/faster alternative: openai/gpt-oss-20b. Override with env LOCBOT_MODEL.
# NOTE: Groq deprecates model IDs periodically. If a call fails with a
# model-not-found error, check current IDs at console.groq.com/docs/models.
MODEL = os.environ.get("LOCBOT_MODEL", "openai/gpt-oss-120b")

_client = Groq()  # reads GROQ_API_KEY from the environment

SYSTEM = """You are the triage engine for a localization (loc) team's request system.
A "loc team" handles translation and the engineering around it.

Read one inbound message and return ONE JSON object, nothing else. No prose, no code fences.

Fields:
- intent: one of "new_request", "status_query", "other".
    "new_request" = asking the loc team to do work.
    "status_query" = asking about existing/their requests ("what's the status", "any update", "how many open").
    "other" = greeting, help question, anything else.
- type: short free-text label for the work, e.g. "file translation", "MT engine setup",
    "QA/linguistic check", "new workflow design", "string extraction", "vendor coordination".
    Invent a fitting label; do not force into a fixed list. null if not a new_request.
- summary: one short line describing the ask. null if not a new_request.
- languages: list of language codes/names mentioned, e.g. ["fr","de"]. [] if none/unknown.
- deadline: deadline as written (e.g. "Friday", "2026-07-01") or null.
- priority: one of "low","normal","high","urgent". Infer from wording; default "normal".
- links: list of URLs in the message. [].
- needs_human: true ONLY when the WORK ITSELF requires a loc engineer's or PM's judgment,
    independent of whether details are missing.
    TRUE for: standing up new or undefined workflows, MT/tooling setup, cross-tool checks,
    integration work, or genuinely ambiguous scope on a non-trivial task.
    FALSE for: ordinary translation or QA tasks, even if under-specified. A vague or empty
    request like "please translate this" is NOT needs_human — it only has missing_info.
    Do NOT set needs_human just because information is missing; missing details belong in
    missing_info, not here.
- needs_human_reason: one short line. "" if needs_human is false.
- suggested_role: who should own it, e.g. "translator","localization engineer","loc PM". null if not new_request.
- missing_info: list of short clarifying questions if required info is absent (target languages,
    deadline, source files/links, scope). [] if the request is complete enough to act on.

Be decisive. Prefer asking missing_info over guessing scope. Return only the JSON object."""


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(text[start : end + 1])


_DEFAULTS = {
    "intent": "other",
    "type": None,
    "summary": None,
    "languages": [],
    "deadline": None,
    "priority": "normal",
    "links": [],
    "needs_human": False,
    "needs_human_reason": "",
    "suggested_role": None,
    "missing_info": [],
}


def triage(text: str) -> dict:
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": text},
        ],
        temperature=0,
        # Forces valid JSON. Requires the word "json" in the prompt (it's there).
        # If a chosen model rejects this param, delete this line; _extract_json still copes.
        response_format={"type": "json_object"},
        # Optional speed/cost knobs for gpt-oss models (omitted for max first-run compatibility):
        #   reasoning_effort="low", max_completion_tokens=600,
    )
    raw = resp.choices[0].message.content or ""
    data = _extract_json(raw)
    # Fill anything the model omitted so downstream code never KeyErrors.
    out = dict(_DEFAULTS)
    out.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return out
