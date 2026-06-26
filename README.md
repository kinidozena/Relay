# Relay
Relay is a localization request bot designed for Slack. It turns plain-language Slack messages into tracked, routed localization requests — instantly.

## Architecture

The system separates the Slack transport layer from the core routing logic. This allows the core to run via a terminal CLI without any Slack dependencies.

### Transport Layer (`app.py`)
* Connects to Slack via Socket Mode (no public webhook URL required).
* Ingests `app_mention` and `message.im` events.
* Renders Block Kit UI (escalation cards with Claim/Mark Done buttons).
* Handles interactive payloads (button clicks) and the `/loc-queue` slash command.

### Orchestration (`core.py`)
* Receives raw text from `app.py` (Slack) or `cli.py` (Terminal).
* Calls the triage module to parse the request.
* Executes routing logic: determines if the request needs human escalation, requires more info, or can be auto-acknowledged.
* Formats the final response strings.

### Integrations & Data
* **LLM Triage (`triage.py`)**: Isolates the Groq API. Converts unstructured text into structured JSON (ticket metadata, priority, routing decision).
* **Data Store (`store.py`)**: Manages the SQLite database (`locbot.db`). Tracks ticket states (`new` → `needs_info` → `routed` → `claimed` → `done`).

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
