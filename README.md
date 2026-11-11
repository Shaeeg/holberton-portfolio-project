# Multichannel Support Center and Field Services Integrator
*(Çoxkanallı Dəstək Mərkəzi və Sahə Xidmətləri İnteqratoru)*

## 1. Project Overview

**Mission:** To build a centralized communication hub designed for small businesses that aggregates customer requests from multiple channels (WhatsApp, Telegram, Email) into a unified, Kanban-style dashboard for support agents and field service management.

**The Differentiator:** An automated ticket routing system that parses incoming messages for specific keywords or location data and automatically assigns the ticket to the most appropriate field agent.

## 2. Core Functionalities

*   **Omnichannel Aggregator:** Webhook endpoints designed to receive, normalize, and store incoming messages from:
    *   WhatsApp (via Twilio or Meta API)
    *   Telegram (via Telegram Bot API)
    *   Email (via IMAP or SendGrid/Mailgun inbound parse)
*   **Kanban Dashboard:** A real-time, interactive UI where agents can drag and drop tickets across stages (e.g., New, Assigned, In Progress, Resolved).
*   **Automated Routing Engine:** A background service that analyzes text (keywords) and extracts location metadata to auto-assign tickets to specific agents.
*   **Real-time Synchronization:** WebSockets or Server-Sent Events (SSE) to ensure the Kanban board updates instantly without refreshing when new requests arrive.

## 3. Technical Stack (Proposed)

*   **Backend:** Python (Flask/FastAPI) or Node.js (Express/NestJS) - Ideal for handling robust REST APIs and asynchronous webhooks.
*   **Frontend:** React.js or Vue.js - Excellent for building interactive, state-driven drag-and-drop Kanban boards.
*   **Database:** PostgreSQL (Relational data for users/tickets) or MongoDB (Flexible schema for varied message payloads). Redis for task queuing (e.g., Celery/Bull) if needed.
*   **Infrastructure:** Docker, Nginx, Linux (Ubuntu).

## 4. Workflow and Project Lifecycle

The team will follow this strict chronological workflow:

### Phase 1: Inception (Weeks 1-2)
*   **Team Formation:** Establish roles and communication channels.
*   **Idea Creation & Presentation:** Finalize the "Multichannel Support Center" concept and present it for approval.

### Phase 2: Planning and Documentation (Weeks 2-3)
*   **Kanban Board Setup:** Initialize project management tools (Trello, Jira, or GitHub Kanban).
*   **Documentation (Docs):** Write API specifications, database schemas, and this core planning document.
*   **Functionality & Tech Stack:** Lock in the chosen programming languages, frameworks, and MVP features.
*   **Responsibilities:** Assign specific modules (e.g., User A handles Webhooks, User B handles Frontend UI).

### Phase 3: Iterative Development
The development phase will be heavily focused on stability and continuous integration:
*   **Test Environment (Config):** Set up isolated staging environments to prevent third-party API changes from breaking production.
*   **Deploy from Start:** Implement CI/CD pipelines immediately. A basic "Hello World" application will be deployed on Day 1, and every subsequent feature will be deployed iteratively.
*   **Logger:** Implement robust logging mechanisms to track webhook payloads, routing decisions, and system errors.
*   **Tests:** Enforce Test-Driven Development (TDD). Unit tests and integration tests are mandatory, especially to ensure external API failures are handled gracefully.

### Phase 4: Demo Day
*   Final system freeze.
*   Live demonstration of a message coming in via Telegram/WhatsApp and automatically routing to an agent's Kanban board.

## 5. Potential Challenges & Risk Mitigation

*   **Risk:** Third-party API rate limits or downtime.
    *   **Mitigation:** Implement a retry mechanism with exponential backoff and store raw webhook payloads in a dead-letter queue if processing fails.
*   **Risk:** Webhook format changes breaking the system.
    *   **Mitigation:** Comprehensive unit testing on the parsing logic and maintaining clear versioning in API endpoints.

## 6. MVP — Local setup

Run from the repository root in PowerShell with Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v
$env:INBOUND_SECRET = "local-demo"
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 --call app:create_app
```

Open http://127.0.0.1:8000. Send a sample ticket from a second terminal:

```powershell
$payload = @{ id = "demo-1"; text = "Bakıda internet problemi" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/webhooks/whatsapp -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{ 'X-Webhook-Secret' = 'local-demo' } -Body $payload
```

The board refreshes every two seconds. Drag a card or use its status selector to move it. Location rules take precedence over service keywords. The current routing labels are demo assignments.

- Telegram accepts text updates at `POST /webhooks/telegram`. Register the public HTTPS webhook URL with Telegram using the same secret token as `TELEGRAM_SECRET`.
- WhatsApp and email endpoints accept normalized JSON with `id` and `text`, authenticated by the `X-Webhook-Secret` header. A provider adapter must validate its provider's requests and forward this format.
- `GET /api/tickets` lists tickets and `PATCH /api/tickets/<id>` changes their status. The board and these endpoints currently assume a trusted local environment.
- CI runs the test suite and builds and starts the Docker image. For a persistent container, mount a writable volume at `/data`. Hosting, agent authentication, provider adapters, and push updates remain future work.

## 7. Live Telegram demo

1. Create a dedicated demo bot with [BotFather](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).
2. From the repository root, run `.\.venv\Scripts\python.exe demo.py --telegram` and paste the token into the hidden prompt.
3. Open the new bot in Telegram and tap **Start**. Send **Bakıda internet problemi**. The board should show the ticket in **Təyin edilib** with the **Bakı** routing label.
4. Move it to **İcradadır**, then **Həll edilib**. Send **Kömək lazımdır** to demonstrate the **Yeni** column when no routing rule matches.

The demo uses Telegram long polling and a localhost dashboard. Use a dedicated bot without an active Telegram webhook or another polling process. Press Ctrl+C to stop. For a demo without Telegram, run `demo.py` without the flag and use the sample webhook request above.

On Windows, the first successful Telegram setup saves the token in Windows Credential Manager. Subsequent runs reuse it. To enter a new token, run `demo.py --telegram --replace-token`.

## 8. Operator workflow

Use **Yeni müraciət yarat** for requests received by phone or in person. Manual tickets use the same routing rules as webhook tickets. Change the agent on a card, move the card through the workflow, and open **Tarixçə** to inspect recorded changes. History starts with events recorded after this update. **CSV yüklə** exports the current filter results.

The live Telegram demo replies to a newly recorded message with its ticket number. Repeat deliveries reuse the existing ticket and do not send another confirmation.

## 9. Configure automatic routing

Set `ROUTING_RULES` before starting the server to replace the default city and service rules. Rules are evaluated in order and the first matching keyword determines the assignment. Put city rules before broad service rules if city coverage takes precedence.

```powershell
$env:ROUTING_RULES = '[["Gəncə","Aysel"],["Bakı","Nicat"],["internet","Şəbəkə"]]'
.\.venv\Scripts\python.exe demo.py --telegram
```

Use `[]` to disable automatic routing, or remove the environment variable to use the built-in defaults.
