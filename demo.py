"""Run a local Kanban demo with an optional live Telegram bot."""

import argparse
import json
import os
import re
import secrets
import threading
import webbrowser
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from waitress import create_server

from app import create_app


def telegram_call(token, method, payload):
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        json.dumps(payload).encode(),
        {"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=40) as response:
        data = json.load(response)
    if data.get("ok") is not True:
        raise ValueError("Telegram returned an invalid response")
    return data["result"]


STATUS_LABELS = {
    "New": "Yeni", "Assigned": "Təyin edilib",
    "In Progress": "İcradadır", "Resolved": "Həll edilib",
}


def show_menu(token, chat_id):
    telegram_call(token, "sendMessage", {
        "chat_id": chat_id,
        "text": "Müraciət mövzusunu seçin və ya probleminizi yazın. Son müraciətlər üçün /tickets, ayrıca müraciət üçün /status 123 yazın.",
        "reply_markup": {
            "keyboard": [
                [{"text": "İnternet problemi"}, {"text": "Elektrik problemi"}],
                [{"text": "Digər müraciət"}, {"text": "Müraciətlərim"}],
            ],
            "resize_keyboard": True,
        },
    })


def forward_updates(client, secret, updates, offset, token=None, lookup_status=None, list_tickets=None):
    for update in updates:
        message = update.get("message", {})
        text = message.get("text") if isinstance(message, dict) else None
        command = text.strip() if isinstance(text, str) else ""
        if token and command in ("/start", "/menu", "/help"):
            show_menu(token, message["chat"]["id"])
            offset = update["update_id"] + 1
            continue
        if token and list_tickets and command in ("/tickets", "Müraciətlərim"):
            chat = message["chat"]
            if chat.get("type") != "private":
                reply = "Müraciətlərinizi botla şəxsi söhbətdə yoxlayın."
            else:
                tickets = list_tickets(chat["id"])
                lines = [f"#{ticket['id']} · {STATUS_LABELS[ticket['status']]}" for ticket in tickets]
                reply = "\n".join(["Son müraciətləriniz", *lines]) if lines else "Müraciət tapılmadı."
            telegram_call(token, "sendMessage", {"chat_id": chat["id"], "text": reply})
            offset = update["update_id"] + 1
            continue
        if token and lookup_status and command.split()[:1] == ["/status"]:
            chat = message["chat"]
            match = re.fullmatch(r"/status\s+#?([1-9][0-9]{0,17})", text.strip())
            reply = "Nümunə: /status 123"
            if chat.get("type") != "private":
                reply = "Müraciətin vəziyyətini botla şəxsi söhbətdə yoxlayın."
            elif match:
                status = lookup_status(int(match[1]), chat["id"])
                reply = f"Müraciət #{match[1]} · {STATUS_LABELS[status]}" if status else "Müraciət tapılmadı."
            telegram_call(token, "sendMessage", {"chat_id": chat["id"], "text": reply})
            offset = update["update_id"] + 1
            continue
        if token and re.match(r"/[A-Za-z][A-Za-z0-9_]*(?:@[A-Za-z0-9_]+)?(?:\s|$)", command):
            telegram_call(token, "sendMessage", {
                "chat_id": message["chat"]["id"],
                "text": "Bu əmr tanınmadı. Mövcud seçimlər üçün /menu yazın.",
            })
            offset = update["update_id"] + 1
            continue
        response = client.post(
            "/webhooks/telegram",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )
        if response.status_code >= 500:
            break
        if response.status_code not in (200, 201, 204, 400):
            raise RuntimeError(f"Unexpected local webhook status {response.status_code}")
        chat_id = message.get("chat", {}).get("id") if isinstance(message, dict) else None
        if token and chat_id is not None and response.status_code == 201:
            try:
                telegram_call(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Müraciətiniz qəbul edildi. Müraciət nömrəsi: #{response.json['id']}",
                })
            except (URLError, OSError, ValueError):
                print("Ticket saved, but Telegram confirmation could not be sent.", flush=True)
        if response.status_code == 400:
            print("Telegram update skipped because its payload was invalid.", flush=True)
        offset = update["update_id"] + 1
    return offset


def poll_telegram(token, app, stop):
    offset = None
    delay = 1
    client = app.test_client()
    while not stop.is_set():
        payload = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            updates = telegram_call(token, "getUpdates", payload)
            offset = forward_updates(
                client, app.config["TELEGRAM_SECRET"], updates, offset, token,
                app.extensions["telegram_status"], app.extensions["telegram_tickets"],
            )
        except HTTPError as error:
            print(f"Telegram HTTP {error.code}. Retrying in {delay}s.", flush=True)
            if error.code == 409:
                print("Use a new bot or stop its other polling/webhook integration.", flush=True)
        except (URLError, OSError, ValueError, RuntimeError):
            print(f"Telegram intake temporarily unavailable. Retrying in {delay}s.", flush=True)
        else:
            if not updates or offset == updates[-1]["update_id"] + 1:
                delay = 1
                continue
        stop.wait(delay)
        delay = min(delay * 2, 30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram", action="store_true", help="Connect a live Telegram bot")
    parser.add_argument("--replace-token", action="store_true", help="Replace the saved Telegram token")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    token = None
    if args.telegram:
        import keyring

        service, account = "Holberton Support Center", "Telegram Bot"
        token = None
        if not args.replace_token:
            token = os.getenv("TELEGRAM_BOT_TOKEN") or keyring.get_password(service, account)
        save_token = not token
        token = (token or getpass("Telegram bot token: ")).strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            parser.exit(1, "Invalid Telegram token format.\n")
        try:
            bot = telegram_call(token, "getMe", {})
            webhook = telegram_call(token, "getWebhookInfo", {})
        except HTTPError as error:
            parser.exit(1, f"Telegram rejected the connection (HTTP {error.code}).\n")
        except (URLError, OSError, ValueError):
            parser.exit(1, "Could not connect to Telegram.\n")
        if webhook["url"]:
            parser.exit(1, "This bot already has a webhook. Use a new demo bot.\n")
        if save_token:
            keyring.set_password(service, account, token)
        print(f"Telegram connected: @{bot['username']}", flush=True)

    app = create_app()
    if token:
        app.config["TELEGRAM_SECRET"] = secrets.token_urlsafe(32)
    server = create_server(app, host="127.0.0.1", port=8000)
    stop = threading.Event()
    if token:
        threading.Thread(target=poll_telegram, args=(token, app, stop), daemon=True).start()
    url = "http://127.0.0.1:8000"
    print(f"Kanban: {url}  |  Ctrl+C to stop", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.run()
    finally:
        stop.set()
        server.close()


if __name__ == "__main__":
    main()
