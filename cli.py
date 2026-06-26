"""Run the bot's brain from the terminal. No Slack needed.
Usage:
    python cli.py                # interactive
    python cli.py --seed         # insert example tickets, print queue, exit
Type 'queue' to see the management summary, 'quit' to exit.
"""
import sys
import store
import core

REQUESTER = "U_CLI_USER"
CHANNEL = "C_CLI"

SEED = [
    "Hi, can you translate the attached release notes into French and German by Friday? https://drive/x",
    "We need to stand up a brand-new MT post-editing workflow for our docs team across 6 languages, with QA gates. Where do we start?",
    "Please translate this.",
    "URGENT: legal contract needs certified ES translation today, https://drive/contract",
]


def show(result: dict):
    print(f"\nintent={result['intent']}  action={result['action']}")
    print("reply >", result["reply"])
    if result["escalation"]:
        print("\n[posted to loc-team channel]")
        print(result["escalation"])
    print("-" * 60)


def main():
    store.init_db()
    if "--seed" in sys.argv:
        for msg in SEED:
            print(f"\n>>> {msg}")
            show(core.handle_message(msg, REQUESTER, CHANNEL))
        print("\n=== MANAGEMENT QUEUE ===")
        print(core.queue_summary())
        return

    print("Loc bot CLI. Type a request, 'queue', or 'quit'.")
    while True:
        try:
            msg = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg in ("quit", "exit"):
            break
        if msg == "queue":
            print(core.queue_summary())
            continue
        show(core.handle_message(msg, REQUESTER, CHANNEL))


if __name__ == "__main__":
    main()
