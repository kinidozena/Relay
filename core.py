"""Orchestration layer. Ties triage + store and decides what happens.
Slack-independent on purpose: the CLI and the Slack bot both call handle_message().
"""
import store
import triage

# Action values the caller (CLI / Slack) acts on:
# "status"    -> reply only (answered a status query)
# "ask_info"  -> reply with clarifying questions (ticket is needs_info)
# "escalate"  -> reply to requester AND post `escalation` to the loc-team channel
# "ack"       -> reply only (routine, auto-routed, no active ping)
# "help"      -> reply only (greeting/help)

_URGENT = {"high", "urgent"}

def _fmt_ticket_line(t: dict) -> str:
    langs = "/ ".join(t["languages"]).upper() if t["languages"] else "—"
    due = t["deadline"] or "no deadline"
    status = t["status"].replace("_", " ")
    summary = t["summary"] or t["raw_text"][:60]
    return (f"#{t['id']} {t['type'] or 'request'} · {langs} · due: {due} · `{status}`"
            f"\n        {summary}")

def queue_summary() -> str:
    """For management: open work grouped by status."""
    counts = store.open_counts()
    if not counts:
        return "No open requests."
    status_line = " · ".join(f"{n} {s.replace('_',' ')}" for s, n in counts.items())
    attention = [t for t in store.list_tickets()
                 if t["status"] != "done" and (t["needs_human"] or t["priority"] in _URGENT)]
    lines = [f":bar_chart: Open requests — {status_line}"]
    if attention:
        lines.append("\nNeeds a team member:")
        lines += [_fmt_ticket_line(t) for t in attention]
    remaining = [t for t in store.list_tickets()
                 if t["status"] != "done" and t not in attention]
    if remaining:
        lines.append("\nOther open tickets:")
        lines += [_fmt_ticket_line(t) for t in remaining]
    return "\n".join(lines)

def _handle_status_query(requester: str) -> dict:
    mine = [t for t in store.find_by_requester(requester) if t["status"] != "done"]
    if not mine:
        reply = (":white_check_mark: No open requests on your end.\n"
                 "Send me a request in plain language anytime to get started.")
    else:
        lines = [f":clipboard: Your open requests ({len(mine)}):", ""]
        lines += [_fmt_ticket_line(t) for t in mine]
        reply = "\n".join(lines)
    return {"intent": "status_query", "ticket": None, "action": "status",
            "reply": reply, "escalation": None}

def _handle_new_request(text: str, requester: str, channel: str, t: dict, 
                        existing_tid: int | None = None, thread_ts: str | None = None) -> dict:
    if existing_tid:
        tid = existing_tid
        store.update_ticket(tid,
            type=t["type"], summary=t["summary"], languages=t["languages"],
            deadline=t["deadline"], priority=t["priority"], links=t["links"],
            needs_human=t["needs_human"], needs_human_reason=t["needs_human_reason"],
            suggested_role=t["suggested_role"], missing_info=t["missing_info"],
            status="new"
        )
    else:
        tid = store.create_ticket({
            "requester": requester, "channel": channel, "raw_text": text, "thread_ts": thread_ts,
            "type": t["type"], "summary": t["summary"], "languages": t["languages"],
            "deadline": t["deadline"], "priority": t["priority"], "links": t["links"],
            "needs_human": t["needs_human"], "needs_human_reason": t["needs_human_reason"],
            "suggested_role": t["suggested_role"], "missing_info": t["missing_info"],
            "status": "new",
        })

    # 1) Needs human judgment or urgent -> loop in a team member NOW.
    if t["needs_human"] or t["priority"] in _URGENT:
        store.update_ticket(tid, status="routed")
        reason = t["needs_human_reason"] or f"priority: {t['priority']}"
        open_qs = "\n".join(f"• {q}" for q in t["missing_info"])

        reply_lines = [
            f":rotating_light: *Request logged — #{tid}*",
            f"_{t['summary']}_", " ",
            f"*Status:* Escalated to the loc team",
            f"*Reason:* {reason}",
            f"*Assigned to:* {t['suggested_role'] or 'loc team'}",
        ]
        if t["deadline"]:
            reply_lines.append(f"*Deadline:* {t['deadline']}")
        if open_qs:
            reply_lines += [" ", "*To speed things up, have these ready:*", open_qs]
        reply_lines += [" ", "_The team will follow up here._"]
        reply = "\n".join(reply_lines)

        esc_lines = [
            f":rotating_light: *#{tid} needs attention* — {reason}",
            f"*{t['summary']}*",
            f"Type: {t['type'] or '—'} · "
            f"Languages: {'/'.join(t['languages']).upper() if t['languages'] else '—'} · "
            f"Priority: {t['priority']} · "
            f"Deadline: {t['deadline'] or '—'}",
            f"Requested by: <@{requester}> · Suggested owner: {t['suggested_role'] or 'unassigned'}",
        ]
        if open_qs:
            esc_lines += [" ", "*Open questions for requester:*", open_qs]
        escalation = "\n".join(esc_lines)

        return {"intent": "new_request", "ticket": store.get_ticket(tid),
                "action": "escalate", "reply": reply, "escalation": escalation}

    # 2) Routine but missing required info -> the bot asks the requester.
    if t["missing_info"]:
        store.update_ticket(tid, status="needs_info")
        qs = "\n".join(f"• {q}" for q in t["missing_info"])
        reply = "\n".join([
            f":pencil: *Request received — #{tid}*",
            f"_{t['summary']}_", " ",
            "*A few details needed before I can route this:*",
            qs, " ",
            "_Reply with the details and I'll move it forward._",
        ])
        return {"intent": "new_request", "ticket": store.get_ticket(tid),
                "action": "ask_info", "reply": reply, "escalation": None}

    # 3) Routine + complete -> auto-route, no active ping.
    store.update_ticket(tid, status="routed", assignee=t["suggested_role"])
    langs = "/ ".join(t["languages"]).upper() if t["languages"] else "—"
    reply = "\n".join([
        f":white_check_mark: *Request logged — #{tid}*",
        f"_{t['summary']}_", " ",
        f"*Type:* {t['type'] or '—'}",
        f"*Languages:* {langs}",
        f"*Deadline:* {t['deadline'] or '—'}",
        f"*Assigned to:* {t['suggested_role'] or 'the team'}", " ",
        "_Ask me for a status update anytime._",
    ])
    return {"intent": "new_request", "ticket": store.get_ticket(tid),
            "action": "ack", "reply": reply, "escalation": None}

_HELP = "\n".join([
    ":wave: Welcome to Relay — your localization request bot.", " ",
    "Send me a request in plain language and I'll log, classify, and route it.",
    "Examples:",
    "• Translate the attached release notes to FR and DE by Friday <link>",
    "• We need a new MT post-editing workflow for 6 languages",
    "• URGENT: certified ES translation of this contract today <link>", " ",
    "Ask \"what's the status of my requests?\" anytime to check your open tickets.",
])

def handle_message(text: str, requester: str, channel: str, thread_ts: str | None = None) -> dict:
    existing_tid = None
    
    # Check for follow-up in an existing needs_info thread
    if thread_ts:
        existing = store.get_by_thread(thread_ts, status="needs_info")
        if existing:
            existing_tid = existing["id"]
            text = existing["raw_text"] + "\n\n[User follow-up]: " + text

    t = triage.triage(text)
    
    if t["intent"] == "status_query":
        return _handle_status_query(requester)
    if t["intent"] == "new_request":
        return _handle_new_request(text, requester, channel, t, existing_tid, thread_ts)
        
    return {"intent": "other", "ticket": None, "action": "help",
            "reply": _HELP, "escalation": None}