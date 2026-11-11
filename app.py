import hmac
import json
import logging
import os
import sqlite3
from contextlib import closing
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request

PRIORITIES = ("normal", "high", "urgent")
STATUSES = ("New", "Assigned", "In Progress", "Resolved")


DEFAULT_ROUTING_RULES = (
    ("sumqayıt", "Sumqayıt"),
    ("bakı", "Bakı"),
    ("internet", "Şəbəkə"),
    ("elektrik", "Elektrik"),
)


def normalize_text(text):
    return text.replace("İ", "i").replace("I", "ı").casefold()


def load_routing_rules(raw):
    if raw is None:
        return DEFAULT_ROUTING_RULES
    try:
        rules = json.loads(raw)
    except ValueError as error:
        raise ValueError("ROUTING_RULES must be a JSON array of [keyword, agent] pairs") from error
    if not isinstance(rules, list):
        raise ValueError("ROUTING_RULES must be a JSON array of [keyword, agent] pairs")
    normalized = []
    for rule in rules:
        if (
            not isinstance(rule, list)
            or len(rule) != 2
            or any(not isinstance(value, str) or not value.strip() for value in rule)
            or len(rule[1].strip()) > 100
        ):
            raise ValueError("Each routing rule needs a non-empty keyword and agent (max 100 characters)")
        normalized.append((normalize_text(rule[0].strip()), rule[1].strip()))
    return tuple(normalized)


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=database or os.getenv("DATABASE_PATH", "support.sqlite3"),
        TELEGRAM_SECRET=os.getenv("TELEGRAM_SECRET", ""),
        INBOUND_SECRET=os.getenv("INBOUND_SECRET", ""),
        ROUTING_RULES=load_routing_rules(os.getenv("ROUTING_RULES")),
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    app.logger.setLevel(logging.INFO)

    def connect():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        return connection

    with closing(connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL,
                external_id TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                agent TEXT,
                UNIQUE(channel, external_id)
            )
        """)

        columns = {column["name"] for column in connection.execute("PRAGMA table_info(tickets)")}
        if "priority" not in columns:
            connection.execute("ALTER TABLE tickets ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ticket_events (
                id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id),
                kind TEXT NOT NULL,
                detail TEXT,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS ticket_events_ticket_idx
            ON ticket_events(ticket_id, id)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS telegram_ticket_chats (
                ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
                chat_id INTEGER NOT NULL
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS telegram_ticket_chats_chat_idx
            ON telegram_ticket_chats(chat_id, ticket_id)
        """)

    def telegram_tickets(chat_id):
        with closing(connect()) as connection:
            rows = connection.execute(
                """SELECT tickets.id, tickets.status FROM telegram_ticket_chats
                   JOIN tickets ON tickets.id = telegram_ticket_chats.ticket_id
                   WHERE telegram_ticket_chats.chat_id = ?
                   ORDER BY telegram_ticket_chats.ticket_id DESC LIMIT 5""",
                (chat_id,),
            )
            return [dict(row) for row in rows]

    app.extensions["telegram_tickets"] = telegram_tickets

    def telegram_status(ticket_id, chat_id):
        with closing(connect()) as connection:
            row = connection.execute(
                """SELECT tickets.status FROM tickets
                   JOIN telegram_ticket_chats ON tickets.id = telegram_ticket_chats.ticket_id
                   WHERE tickets.id = ? AND telegram_ticket_chats.chat_id = ?""",
                (ticket_id, chat_id),
            ).fetchone()
        return row["status"] if row else None

    app.extensions["telegram_status"] = telegram_status

    def record_event(connection, ticket_id, kind, detail):
        connection.execute(
            "INSERT INTO ticket_events (ticket_id, kind, detail) VALUES (?, ?, ?)",
            (ticket_id, kind, detail),
        )

    @app.get("/api/tickets/<int:ticket_id>/events")
    def ticket_events(ticket_id):
        with closing(connect()) as connection:
            if connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
                abort(404)
            events = connection.execute(
                """SELECT kind, detail, recorded_at FROM ticket_events
                   WHERE ticket_id = ? ORDER BY id DESC""",
                (ticket_id,),
            )
            return jsonify([dict(event) for event in events])

    @app.post("/api/tickets/<int:ticket_id>/notes")
    def add_note(ticket_id):
        data = request.get_json(silent=True)
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
            return {"error": "Enter a note of 1 to 1000 characters"}, 400
        with closing(connect()) as connection, connection:
            if connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
                abort(404)
            record_event(connection, ticket_id, "note", text.strip())
        return {"status": "saved"}, 201

    @app.get("/")
    def board():
        return render_template("board.html", statuses=STATUSES)

    @app.get("/health")
    def health():
        with closing(connect()) as connection:
            connection.execute("SELECT 1 FROM tickets LIMIT 1")
        return {"status": "ok"}

    @app.get("/api/tickets")
    def tickets():
        with closing(connect()) as connection:
            response = jsonify([dict(row) for row in connection.execute(
                """SELECT tickets.*, (
                       SELECT recorded_at FROM ticket_events
                       WHERE ticket_id = tickets.id AND kind = 'received'
                       ORDER BY id LIMIT 1
                   ) AS received_at, CASE WHEN tickets.status = 'Resolved' THEN (
                       SELECT recorded_at FROM ticket_events
                       WHERE ticket_id = tickets.id AND kind = 'status' AND detail = 'Resolved'
                       ORDER BY id DESC LIMIT 1
                   ) END AS resolved_at FROM tickets ORDER BY
                   CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                   id DESC"""
            )])
        response.cache_control.private = True
        response.cache_control.no_cache = True
        response.add_etag()
        return response.make_conditional(request)

    @app.patch("/api/tickets/<int:ticket_id>")
    def update_ticket(ticket_id):
        data = request.get_json(silent=True)
        status = data.get("status") if isinstance(data, dict) else None
        if status not in STATUSES:
            return {"error": "Invalid status"}, 400
        with closing(connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE tickets SET status = ? WHERE id = ? AND status <> ?",
                (status, ticket_id, status),
            )
            if cursor.rowcount:
                record_event(connection, ticket_id, "status", status)
            elif connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
                abort(404)
        return {"id": ticket_id, "status": status}

    @app.put("/api/tickets/<int:ticket_id>/priority")
    def set_priority(ticket_id):
        data = request.get_json(silent=True)
        priority = data.get("priority") if isinstance(data, dict) else None
        if priority not in PRIORITIES:
            return {"error": "Invalid priority"}, 400
        with closing(connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE tickets SET priority = ? WHERE id = ? AND priority <> ?",
                (priority, ticket_id, priority),
            )
            if cursor.rowcount:
                record_event(connection, ticket_id, "priority", priority)
            elif connection.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
                abort(404)
        return {"id": ticket_id, "priority": priority}

    @app.put("/api/tickets/<int:ticket_id>/assignment")
    def assign_ticket(ticket_id):
        data = request.get_json(silent=True)
        agent = data.get("agent") if isinstance(data, dict) else None
        if not isinstance(agent, str) or len(agent.strip()) > 100:
            return {"error": "Agent must be text up to 100 characters"}, 400
        agent = agent.strip() or None
        with closing(connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT agent, status FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
            if previous is None:
                abort(404)
            connection.execute(
                """UPDATE tickets SET agent = ?, status = CASE
                       WHEN status = 'New' AND ? IS NOT NULL THEN 'Assigned'
                       WHEN status = 'Assigned' AND ? IS NULL THEN 'New'
                       ELSE status
                   END WHERE id = ?""",
                (agent, agent, agent, ticket_id),
            )
            ticket = connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
            if previous["agent"] != ticket["agent"]:
                record_event(connection, ticket_id, "assignment", ticket["agent"])
            if previous["status"] != ticket["status"]:
                record_event(connection, ticket_id, "status", ticket["status"])
        return jsonify(dict(ticket))

    @app.post("/api/tickets")
    def create_ticket():
        data = request.get_json(silent=True)
        body = data.get("text") if isinstance(data, dict) else None
        if not isinstance(body, str) or not body.strip() or len(body.strip()) > 4000:
            return {"error": "Enter between 1 and 4000 characters"}, 400
        return store_ticket("manual", uuid4().hex, body)

    def store_ticket(channel, external_id, body, chat_id=None):
        normalized = normalize_text(body)
        agent = next(
            (team for keyword, team in app.config["ROUTING_RULES"] if keyword in normalized),
            None,
        )
        with closing(connect()) as connection, connection:
            cursor = connection.execute(
                """INSERT INTO tickets (channel, external_id, body, status, agent)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(channel, external_id) DO NOTHING""",
                (channel, str(external_id), body.strip(), "Assigned" if agent else "New", agent),
            )
            created = cursor.rowcount == 1
            ticket = connection.execute(
                "SELECT * FROM tickets WHERE channel = ? AND external_id = ?",
                (channel, str(external_id)),
            ).fetchone()
            if created and chat_id is not None:
                connection.execute(
                    "INSERT INTO telegram_ticket_chats (ticket_id, chat_id) VALUES (?, ?)",
                    (ticket["id"], chat_id),
                )
            if created:
                record_event(connection, ticket["id"], "received", channel)
                if agent:
                    record_event(connection, ticket["id"], "assignment", agent)
        if created:
            app.logger.info("Ticket %s received via %s, assigned to %s", ticket["id"], channel, agent)
        return jsonify(dict(ticket)), 201 if created else 200

    @app.post("/webhooks/<channel>")
    def webhook(channel):
        if channel not in ("telegram", "whatsapp", "email"):
            abort(404)
        secret_key, header = (
            ("TELEGRAM_SECRET", "X-Telegram-Bot-Api-Secret-Token")
            if channel == "telegram" else ("INBOUND_SECRET", "X-Webhook-Secret")
        )
        secret = app.config[secret_key]
        if not secret or not hmac.compare_digest(
            request.headers.get(header, "").encode(), secret.encode()
        ):
            abort(401)

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return {"error": "Expected a JSON object"}, 400
        chat_id = None
        if channel == "telegram":
            external_id = data.get("update_id")
            if type(external_id) is not int:
                return {"error": "Expected an integer update_id"}, 400
            message = data.get("message")
            body = message.get("text") if isinstance(message, dict) else None
            if body is None:
                return "", 204
            chat = message.get("chat")
            if isinstance(chat, dict) and type(chat.get("id")) is int and chat.get("type") == "private":
                chat_id = chat["id"]
        else:
            external_id = data.get("id")
            body = data.get("text")
        if (
            type(external_id) not in (int, str)
            or not str(external_id).strip()
            or len(str(external_id)) > 512
            or not isinstance(body, str)
            or not body.strip()
        ):
            return {"error": "Expected a valid message ID and non-empty text"}, 400

        return store_ticket(channel, external_id, body, chat_id)

    return app
