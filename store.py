"""SQLite ticket store. No Slack, no LLM. Pure data layer."""
import sqlite3
import json
import time
from pathlib import Path

DB = Path(__file__).parent / "locbot.db"

# Columns that hold lists; stored as JSON text.
_LIST_FIELDS = {"languages", "links", "missing_info"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL,
    requester TEXT,
    channel TEXT,
    raw_text TEXT,
    type TEXT,
    summary TEXT,
    languages TEXT,
    deadline TEXT,
    priority TEXT,
    links TEXT,
    needs_human INTEGER,
    needs_human_reason TEXT,
    suggested_role TEXT,
    missing_info TEXT,
    status TEXT,
    assignee TEXT,
    thread_ts TEXT
);
"""

def _conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.execute(_SCHEMA)

def _encode(d: dict) -> dict:
    out = dict(d)
    for f in _LIST_FIELDS:
        if f in out and not isinstance(out[f], str):
            out[f] = json.dumps(out[f] or [])
    if "needs_human" in out:
        out["needs_human"] = 1 if out["needs_human"] else 0
    return out

def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in _LIST_FIELDS:
        try:
            d[f] = json.loads(d[f]) if d.get(f) else []
        except (json.JSONDecodeError, TypeError):
            d[f] = []
    d["needs_human"] = bool(d.get("needs_human"))
    return d

def create_ticket(fields: dict) -> int:
    fields = _encode(fields)
    fields.setdefault("created_at", time.time())
    fields.setdefault("status", "new")
    cols = ", ".join(fields)
    qs = ", ".join("?" for _ in fields)
    with _conn() as c:
        cur = c.execute(f"INSERT INTO tickets ({cols}) VALUES ({qs})", list(fields.values()))
        return cur.lastrowid

def get_ticket(tid: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
        return _decode(row) if row else None

def get_by_thread(thread_ts: str, status: str | None = None) -> dict | None:
    """Find a ticket by its Slack thread_ts."""
    with _conn() as c:
        if status:
            row = c.execute("SELECT * FROM tickets WHERE thread_ts = ? AND status = ?", (thread_ts, status)).fetchone()
        else:
            row = c.execute("SELECT * FROM tickets WHERE thread_ts = ?", (thread_ts,)).fetchone()
    return _decode(row) if row else None

def list_tickets(status=None):
    q = "SELECT * FROM tickets"
    args = ()
    if status:
        q += " WHERE status = ?"
        args = (status,)
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
        return [_decode(r) for r in rows]

def find_by_requester(requester: str):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM tickets WHERE requester = ? ORDER BY created_at DESC",
            (requester,),
        ).fetchall()
        return [_decode(r) for r in rows]

def update_ticket(tid: int, **fields):
    if not fields:
        return
    fields = _encode(fields)
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE tickets SET {sets} WHERE id = ?", list(fields.values()) + [tid])

def open_counts() -> dict:
    """Status -> count, excluding done. For management summary."""
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) n FROM tickets WHERE status != 'done' GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}