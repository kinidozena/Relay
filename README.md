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

## Groq API Configuration

The bot uses Groq for LLM triage. It provides a free tier that requires no credit card.

1. Go to [console.groq.com](https://console.groq.com) and log in or create an account.
2. Navigate to **API Keys** in the left sidebar.
3. Click **Create API Key**, name it, and generate it.
4. Copy the key (starts with `gsk_...`) and save it as `GROQ_API_KEY` in your `.env` file.

Note: The default model is `openai/gpt-oss-120b`. If you see a model-not-found error, check the Groq models documentation (https://console.groq.com/docs/models) and update the `LOCBOT_MODEL` variable in your `.env`.

## Slack App Configuration

Before running the bot, you must configure a Slack App to generate the required tokens and permissions.

1. **Create the App**
   - Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** -> **From scratch**.
   - Name it (e.g., Relay) and select your workspace.

2. **Enable Socket Mode**
   - Go to **Socket Mode** in the left sidebar and toggle it **On**.
   - Create an App-Level Token (name it anything, e.g., `socket`).
   - Copy the token (starts with `xapp-...`) and save it as `SLACK_APP_TOKEN`.

3. **Configure Permissions**
   - Go to **OAuth & Permissions**.
   - Under **Bot Token Scopes**, add the following scopes:
     - `app_mentions:read`
     - `chat:write`
     - `im:history`
     - `im:read`
     - `im:write`
     - `commands`

4. **Enable Event Subscriptions**
   - Go to **Event Subscriptions** and toggle it **On**.
   - Under **Subscribe to bot events**, add:
     - `app_mention`
     - `message.im`
   - *Note: If you add scopes or events after installing the app, you must reinstall it for changes to take effect.*

5. **Enable Interactivity**
   - Go to **Interactivity & Shortcuts** and toggle it **On**. (No Request URL is needed when using Socket Mode).

6. **Create Slash Commands**
   - Go to **Slash Commands** and create the following commands:
     - `/loc-queue`
     - `/loc-close`
     - `/loc-reopen`
     - `/loc-clear`

7. **Install and Retrieve Bot Token**
   - Go to **Install App** in the left sidebar and click **Install to Workspace**.
   - Copy the **Bot User OAuth Token** (starts with `xoxb-...`) and save it as `SLACK_BOT_TOKEN`.

8. **Configure the Team Channel**
   - Create a channel in Slack for the localization team (e.g., `#loc-team`).
   - Invite the bot to this channel (e.g., `/invite @Relay`).
   - Right-click the channel name in Slack, scroll to the bottom, and copy the **Channel ID** (starts with `C0...`).
   - Save this ID as `LOC_TEAM_CHANNEL`.

## Bot Setup
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
