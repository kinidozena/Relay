"""Slack layer (Socket Mode). Translates Slack events <-> core.handle_message.
Run: python app.py   (after filling .env: SLACK_BOT_TOKEN, SLACK_APP_TOKEN,
LOC_TEAM_CHANNEL, GROQ_API_KEY)
Needs no public URL. Requires the app to have Socket Mode and Interactivity enabled,
and the bot to be invited to LOC_TEAM_CHANNEL.
"""
import os
import re
from dotenv import load_dotenv
load_dotenv()  # must run before importing core (triage builds the Groq client at import)

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

import core
import store

LOC_TEAM_CHANNEL = os.environ.get("LOC_TEAM_CHANNEL", "")

# token_verification_enabled=False so the module imports without a network call;
# the real token is validated explicitly at startup (auth_test below).
app = App(token=os.environ.get("SLACK_BOT_TOKEN") or "xoxb-not-set",
          token_verification_enabled=False)

# --- Block Kit for escalated tickets ---------------------------------------
def _escalation_blocks(text: str, tid: int, footer: str | None = None):
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "block_id": f"ticket_{tid}", "elements": [
            {"type": "button", "action_id": "claim_ticket",
             "text": {"type": "plain_text", "text": "Claim"}, "value": str(tid)},
            {"type": "button", "action_id": "done_ticket", "style": "primary",
             "text": {"type": "plain_text", "text": "Mark done"}, "value": str(tid)},
            {"type": "button", "action_id": "needinfo_ticket",
             "text": {"type": "plain_text", "text": "Need info"}, "value": str(tid)},
        ]},
    ]
    if footer:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    return blocks

# --- Core dispatch ----------------------------------------------------------
def _process(text: str, user: str, channel: str, client, thread_ts: str | None = None):
    """Run one message through the brain and post the reply (+ escalation)."""
    result = core.handle_message(text, user, channel, thread_ts)
    
    client.chat_postMessage(channel=channel, text=result["reply"], thread_ts=thread_ts)
    
    if result["action"] == "escalate" and result["escalation"]:
        tid = result["ticket"]["id"]
        if not LOC_TEAM_CHANNEL:
            print("[escalation] LOC_TEAM_CHANNEL not set; skipping team post.")
            return
        try:
            client.chat_postMessage(
                channel=LOC_TEAM_CHANNEL,
                blocks=_escalation_blocks(result["escalation"], tid),
                text=result["escalation"],  # fallback for notifications
            )
        except SlackApiError as e:
            print(f"[escalation post failed] {e.response['error']} "
                  f"— is the bot invited to LOC_TEAM_CHANNEL?")

# --- Events -----------------------------------------------------------------
@app.event("app_mention")
def on_mention(event, client):
    text = re.sub(r"<@[^>]+>", "", event.get("text", "")).strip()  # drop the @bot token
    thread_ts = event.get("thread_ts") or event.get("ts")
    _process(text, event["user"], event["channel"], client, thread_ts=thread_ts)

@app.event("message")
def on_dm(event, client):
    # Ignore the bot's own messages and edits/joins/etc. to avoid loops.
    if event.get("bot_id") or event.get("subtype"):
        return
    thread_ts = event.get("thread_ts") or event.get("ts")
    _process(event.get("text", ""), event["user"], event["channel"], client, thread_ts=thread_ts)

# --- Button actions (human in the loop) -------------------------------------
def _update_status(body, client, status: str, verb: str):
    tid = int(body["actions"][0]["value"])
    user = body["user"]["id"]
    fields = {"status": status}
    if status == "claimed":
        fields["assignee"] = user
        
    store.update_ticket(tid, **fields)
    
    original = body["message"]["blocks"][0]["text"]["text"]
    footer = f"{verb} by <@{user}> — status: {status}"
    client.chat_update(channel=body["channel"]["id"], ts=body["message"]["ts"],
                       blocks=_escalation_blocks(original, tid, footer),
                       text="Ticket updated")

@app.action("claim_ticket")
def a_claim(ack, body, client):
    ack(); _update_status(body, client, "claimed", "Claimed")

@app.action("done_ticket")
def a_done(ack, body, client):
    ack(); _update_status(body, client, "done", "Closed")

@app.action("needinfo_ticket")
def a_needinfo(ack, body, client):
    ack(); _update_status(body, client, "needs_info", "Flagged for info")

# --- Slash commands ----------------------------------------------------------
@app.command("/loc-queue")
def cmd_queue(ack, respond):
    ack()
    respond(core.queue_summary())

@app.command("/loc-close")
def cmd_close(ack, respond, command):
    """Close a single ticket by ID. Usage: /loc-close 7"""
    ack()
    raw = (command.get("text") or "").strip()
    if not raw.isdigit():
        respond("Usage: `/loc-close` `<ticket_id>` — e.g. `/loc-close 7`")
        return
    tid = int(raw)
    ticket = store.get_ticket(tid)
    if not ticket:
        respond(f"No ticket found with ID #{tid}.")
        return
    if ticket["status"] == "done":
        respond(f"#{tid} is already closed.")
        return
    store.update_ticket(tid, status="done")
    respond(f":white_check_mark: Ticket #{tid} closed — {ticket['summary']}")

@app.command("/loc-reopen")
def cmd_reopen(ack, respond, command):
    """Reopen a closed ticket. Usage: /loc-reopen 7"""
    ack()
    raw = (command.get("text") or "").strip()
    if not raw.isdigit():
        respond("Usage: `/loc-reopen` `<ticket_id>` — e.g. `/loc-reopen 7`")
        return
    tid = int(raw)
    ticket = store.get_ticket(tid)
    if not ticket:
        respond(f"No ticket found with ID #{tid}.")
        return
    if ticket["status"] != "done":
        respond(f"#{tid} is not closed (status: `{ticket['status']}`). Nothing changed.")
        return
    store.update_ticket(tid, status="routed")
    respond(f":arrows_counterclockwise: Ticket #{tid} reopened — {ticket['summary']}")

# Pending confirmation tokens: user -> "clear" to allow /loc-clear confirm.
_clear_pending: dict[str, bool] = {}

@app.command("/loc-clear")
def cmd_clear(ack, respond, command):
    """Mark all open tickets done. Requires confirmation.
    First call: shows a warning and count.
    Second call within the same session: executes.
    Usage: /loc-clear       (first call — shows warning)
           /loc-clear confirm  (second call — executes)
    """
    ack()
    user = command["user_id"]
    arg = (command.get("text") or "").strip().lower()
    
    if arg != "confirm":
        open_tickets = [t for t in store.list_tickets() if t["status"] != "done"]
        count = len(open_tickets)
        if count == 0:
            respond("The queue is already empty.")
            _clear_pending.pop(user, None)
            return
        _clear_pending[user] = True
        respond(
            f":warning: This will close *{count} open ticket(s)* and cannot be undone.\n"
            f"Run `/loc-clear confirm` to proceed, or ignore this to cancel."
        )
        return

    if not _clear_pending.get(user):
        respond("Run `/loc-clear` first to see the warning, then `/loc-clear confirm` to proceed.")
        return

    open_tickets = [t for t in store.list_tickets() if t["status"] != "done"]
    for t in open_tickets:
        store.update_ticket(t["id"], status="done")
    _clear_pending.pop(user, None)
    respond(f":white_check_mark: Queue cleared — *{len(open_tickets)} ticket(s)* marked done.")

# --- Startup ----------------------------------------------------------------
def _check_env():
    missing = [v for v in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GROQ_API_KEY")
               if not os.environ.get(v)]
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing)
                         + ". Set them in .env or your shell.")
    if not LOC_TEAM_CHANNEL:
        print("Warning: LOC_TEAM_CHANNEL not set — escalations won't post to a channel.")

if __name__ == "__main__":
    _check_env()
    store.init_db()
    auth = app.client.auth_test()  # validates the bot token, raises if bad
    print(f"Connected as {auth['user']} to '{auth['team']}'. Listening (Ctrl+C to stop)...")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()