# Multichannel Support Center and Field Services Integrator

*Çoxkanallı Dəstək Mərkəzi və Sahə Xidmətləri İnteqratoru*

A portfolio MVP for small businesses that collects customer requests in an Azerbaijani-language Kanban board and routes them to field teams by keyword or city.

## Features

- **Live Telegram intake:** The local demo uses long polling. Customers can select a topic, receive a ticket number, and check their own tickets with `/tickets` or `/status <number>` in a private chat. A Telegram webhook endpoint is also available for HTTPS deployments.
- **WhatsApp and email intake:** Authenticated endpoints accept normalized JSON from provider adapters. Direct WhatsApp and email provider connections still require adapters.
- **Operator board:** Create tickets manually, drag cards between stages, assign an agent, set priority, and add internal notes. Each card has a ticket number and activity history.
- **Search and reporting:** Filter by channel, agent, priority, status, and waiting time. Review open and resolved counts, median resolution time, and export the current view to CSV.
- **Routing and reliability:** Configurable first-match routing, duplicate delivery handling, persisted history, and a dashboard that polls every two seconds and retries after a connection failure.

The backend uses Python 3.12, Flask, Waitress, and SQLite. The board uses server-rendered HTML and vanilla JavaScript. GitHub Actions runs the integration tests and a Docker health check.

## Local setup

Run from the repository root in PowerShell with Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v
$env:INBOUND_SECRET = "local-demo"
.\.venv\Scripts\python.exe demo.py
```

Open http://127.0.0.1:8000. Send a sample ticket from a second terminal:

```powershell
$payload = @{ id = "demo-1"; text = "Bakıda internet problemi" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/webhooks/whatsapp -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{ 'X-Webhook-Secret' = 'local-demo' } -Body $payload
```

The board refreshes every two seconds. Drag a card or use its status selector to move it. Location rules take precedence over service keywords. The current routing labels are demo assignments.

- Telegram accepts text updates at `POST /webhooks/telegram`. Register the public HTTPS webhook URL with Telegram using the same secret token as `TELEGRAM_SECRET`.
- WhatsApp and email endpoints accept normalized JSON with `id` and `text`, authenticated by the `X-Webhook-Secret` header. A provider adapter must validate its provider's requests and forward this format.
- `GET /api/tickets` lists tickets, `POST /api/tickets` creates a manual ticket, and `PATCH /api/tickets/<id>` changes its status. See Operator access below for authentication.
- CI runs the test suite and builds and starts the Docker image. For a persistent container, mount a writable volume at `/data`. Public hosting, individual operator accounts, and direct provider adapters remain future work.

## Live Telegram demo

1. Create a dedicated demo bot with [BotFather](https://core.telegram.org/bots/tutorial#obtain-your-bot-token).
2. From the repository root, run `.\.venv\Scripts\python.exe demo.py --telegram` and paste the token into the hidden prompt.
3. Open the new bot in Telegram and tap **Start**. Send **Bakıda internet problemi**. The board should show the ticket in **Təyin edilib** with the **Bakı** routing label.
4. Move it to **İcradadır**, then **Həll edilib**. Send **Kömək lazımdır** to demonstrate the **Yeni** column when no routing rule matches.

The demo uses Telegram long polling and a localhost dashboard. Use a dedicated bot without an active Telegram webhook or another polling process. Press Ctrl+C to stop. For a demo without Telegram, run `demo.py` without the flag and use the sample webhook request above.

On Windows, the first successful Telegram setup saves the token in Windows Credential Manager. Subsequent runs reuse it. To enter a new token, run `demo.py --telegram --replace-token`.

## Operator workflow

Use **Yeni müraciət** for requests received by phone or in person. Manual tickets use the same routing rules as webhook tickets. Change the agent on a card, move the card through the workflow, and open **Tarixçə** to inspect recorded changes. History starts with events recorded after this update. **CSV yüklə** exports the current filter results.

The live Telegram demo replies to a newly recorded message with its ticket number. Repeat deliveries reuse the existing ticket and do not send another confirmation.

## Configure automatic routing

Set `ROUTING_RULES` before starting the server to replace the default city and service rules. Rules are evaluated in order and the first matching keyword determines the assignment. Put city rules before broad service rules if city coverage takes precedence.

```powershell
$env:ROUTING_RULES = '[["Gəncə","Aysel"],["Bakı","Nicat"],["internet","Şəbəkə"]]'
.\.venv\Scripts\python.exe demo.py --telegram
```

Use `[]` to disable automatic routing, or remove the environment variable to use the built-in defaults.

## Architecture and operator access

- `app.py` initializes Flask and SQLite, adds missing schema elements transactionally, and implements intake, workflow, activity and reporting queries.
- `operator_access.py` applies HTTP Basic authentication and browser security headers. The dashboard and its API require an operator password by default. JSON writes reject cross-site or same-site cross-origin browser requests.
- `demo.py` serves the app on loopback and optionally polls Telegram. Telegram replies are best-effort. `templates/board.html` contains the dashboard markup, while `static/` contains the browser behavior and styles.

Set `OPERATOR_PASSWORD` to a strong secret and optionally set `OPERATOR_USERNAME` (default `operator`). Use HTTPS through a reverse proxy for any non-loopback access. This MVP uses a shared operator identity. The local-only `demo.py` launcher permits passwordless access when no operator password is configured. `/health` and the independently authenticated webhook routes work without operator credentials.

Use `DATABASE_PATH` to point at a persistent SQLite file or an isolated demo database. Docker defaults to `/data/support.sqlite3`. Back up the database before upgrading a long-lived installation.

### API reference

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Database readiness |
| GET, POST | `/api/tickets` | List tickets or create one with `text` |
| PATCH | `/api/tickets/<id>` | Update `status` |
| PUT | `/api/tickets/<id>/assignment` | Set `agent`, or clear with an empty string |
| PUT | `/api/tickets/<id>/priority` | Set `priority` to `normal`, `high`, or `urgent` |
| GET | `/api/tickets/<id>/events` | Read activity and notes |
| POST | `/api/tickets/<id>/notes` | Add an internal note with `text` |
| POST | `/webhooks/telegram` | Telegram text intake using `TELEGRAM_SECRET` |
| POST | `/webhooks/whatsapp`, `/webhooks/email` | Normalized intake using `INBOUND_SECRET` |

### Docker

Build with `docker build -t support-center .`. Set `OPERATOR_PASSWORD` in your shell before starting the container.

```powershell
docker run --rm -p 127.0.0.1:8000:8000 -e OPERATOR_PASSWORD -v support-data:/data support-center
```

For the presentation, start with an isolated database. After the Telegram intake and routing steps above, change the ticket priority, reassign it, add a note, and inspect the timeline. Check the resulting status in Telegram with `/status <id>`, then export the filtered view. Label the normalized WhatsApp example as simulated intake.

## Interactive Telegram support

1. Start `demo.py --telegram`, then send `/start` in a private chat.
2. Tap **Yeni müraciət**, select a category and city, describe the issue, and tap **Təsdiqlə**. Note the ticket number and initial status. Free-text submission remains available from the main menu.
3. Switch the matching card to **İcradadır**. Open **Telegram söhbəti** and send a customer-visible reply. Use the separate **Tarixçə** panel for internal notes.
4. In Telegram, choose a ticket through **Müraciətlərim** or use `/reply <id>` and send one text message or Telegram photo. Select the ticket again before another reply. The dashboard previews supported JPEG photos up to 5 MiB through its protected API.
5. Resolve the card, then tap a rating button or send `/rate <id> 5`. The card shows the rating. The overview shows the average once there are three ratings.

SQLite adds tables for drafts, processed guided updates, ticket details, conversations, photos and ratings at startup. Ownership uses the existing private chat association. Ticket changes and queued notifications commit together. The worker records pending, sending, sent and failed states. Telegram rate limits requeue rejected deliveries. Ambiguous failures are left visible for operator review to avoid duplicate messages. A process interrupted mid-send can leave a message in the sending state. Photos are fetched on demand from Telegram. Their provider file identifiers and bot token stay server-side.

For an HTTPS webhook deployment, configure `TELEGRAM_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_REPLIES=1`, and operator authentication. Run `python demo.py --delivery-only` alongside the web server with the same `DATABASE_PATH` to process outbound status and conversation messages. The worker and server need shared access to the SQLite file. Use either HTTPS webhook mode or long polling for a bot.
