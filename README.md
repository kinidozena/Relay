# Relay
Relay is a localization request bot designed for Slack. It turns plain-language Slack messages into tracked, routed localization requests — instantly.

## Architecture
Slack event (mention / DM)
        |
    app.py          <- Slack layer only. Socket Mode.
        |
    core.py         <- Orchestration. Calls triage, writes to store.
       / \
triage.py  store.py <- LLM call (Groq)   SQLite (locbot.db)

## Key Design Decisions
- **LLM Triage:** Free text in, structured ticket out. Supports new request types automatically without code changes.
- **Provider Isolation:** Only `triage.py` touches the LLM provider. Swapping models is a one-file change.
- **Routing Precedence:** Urgent or complex requests escalate immediately, even if details are missing. Routine requests ask for missing info.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
2. Copy .env.example to .env and add your Groq and Slack API keys.
3. Run the bot:
   ```bash
   python app.py

## CLI Fallback
Run the terminal interface without Slack:
```bash
python cli.py --seed
```
