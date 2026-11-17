"""Private Telegram conversation state shared by polling and webhook intake."""

import json
import re

MENU = (
    ("📝 Yeni müraciət", "📋 Müraciətlərim"),
    ("🔎 Müraciəti yoxla", "ℹ️ Kömək"),
)
CATEGORIES = ("🌐 İnternet", "⚡ Elektrik", "🔧 Texniki problem", "📦 Digər")
LOCATIONS = ("📍 Bakı", "📍 Sumqayıt", "📍 Gəncə", "📍 Digər")
PHOTO_LIMIT = 5 * 1024 * 1024
CONFIRM = "✅ Təsdiqlə"
EDIT = "✏️ Düzəliş et"
CANCEL = "❌ Ləğv et"
LABELS = {"New": "Yeni", "Assigned": "Təyin edilib",
          "In Progress": "İcradadır", "Resolved": "Həll edilib"}


def install_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_drafts (
        chat_id INTEGER PRIMARY KEY, state TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_flow_updates (
        id INTEGER PRIMARY KEY
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_ticket_details (
        ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
        category TEXT NOT NULL, location TEXT NOT NULL
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS telegram_conversation (
        id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
        direction TEXT NOT NULL, text TEXT NOT NULL, delivery TEXT NOT NULL,
        recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS telegram_conversation_queue
        ON telegram_conversation(delivery, id)""")
    db.execute("""CREATE INDEX IF NOT EXISTS telegram_conversation_ticket
        ON telegram_conversation(ticket_id, id)""")
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_ratings (
        ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
        score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS telegram_photos (
        id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
        update_id INTEGER NOT NULL UNIQUE, file_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")


def receive_photo(db, update_id, chat_id, photos):
    if db.execute("SELECT 1 FROM telegram_photos WHERE update_id=?", (update_id,)).fetchone():
        return {}
    row = db.execute("SELECT state FROM telegram_drafts WHERE chat_id=?", (chat_id,)).fetchone()
    draft = json.loads(row["state"]) if row else {}
    text = "Əvvəl /reply <nömrə> ilə müraciəti seçin, sonra şəkli göndərin."
    if draft.get("step") == "conversation":
        photo = next((item for item in reversed(photos) if isinstance(item, dict)
                      and type(item.get("file_size")) is int
                      and 0 < item["file_size"] <= PHOTO_LIMIT
                      and isinstance(item.get("file_id"), str)
                      and 1 <= len(item["file_id"]) <= 512), None)
        text = "5 MB-a qədər Telegram fotosu göndərin."
        if photo:
            inserted = db.execute("""INSERT INTO telegram_photos(ticket_id,update_id,file_id)
                SELECT ticket_id,?,? FROM telegram_ticket_chats WHERE ticket_id=? AND chat_id=?""",
                (update_id, photo["file_id"], draft["ticket_id"], chat_id)).rowcount
            if inserted:
                db.execute("DELETE FROM telegram_drafts WHERE chat_id=?", (chat_id,))
                text = "Foto müraciətə əlavə edildi."
    return {"chat_id": chat_id, "text": text}


def queue_status(db, ticket_id, status):
    text = f"🔔 Müraciət #{ticket_id} · {LABELS[status]}"
    if status == "Resolved":
        text += f"\nXidməti qiymətləndirmək üçün /rate {ticket_id} 5 yazın (1–5)."
    db.execute("""INSERT INTO telegram_conversation(ticket_id,direction,text,delivery)
        SELECT ticket_id,'system',?,'pending' FROM telegram_ticket_chats WHERE ticket_id=?""",
        (text, ticket_id))


def handle_private_text(db, update_id, chat_id, text, create_ticket):
    """Return a reply payload, or None to let ordinary text use existing intake."""
    text = text.strip()
    if db.execute("SELECT 1 FROM telegram_flow_updates WHERE id = ?", (update_id,)).fetchone():
        return {}
    row = db.execute("SELECT state FROM telegram_drafts WHERE chat_id = ?", (chat_id,)).fetchone()
    draft = json.loads(row["state"]) if row else {}
    step = draft.get("step")

    def reply(message, keyboard=MENU):
        db.execute("INSERT INTO telegram_flow_updates VALUES (?)", (update_id,))
        if draft:
            db.execute("""INSERT INTO telegram_drafts VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET state = excluded.state""",
                (chat_id, json.dumps(draft)))
        else:
            db.execute("DELETE FROM telegram_drafts WHERE chat_id = ?", (chat_id,))
        return {"chat_id": chat_id, "text": message, "reply_markup": {
            "keyboard": [[{"text": label} for label in line] for line in keyboard],
            "resize_keyboard": True,
        }}

    if text in ("/start", "/menu"):
        draft.clear()
        return reply("👋 Dəstək Mərkəzinə xoş gəlmisiniz!\n\nSizə necə kömək edə bilərik?")
    if text in ("/help", MENU[1][1]):
        return reply("Yeni müraciət düyməsini seçin və ya probleminizi birbaşa yazın. "
                     "Müraciətləri /tickets, vəziyyəti /status 123 ilə yoxlayın.")
    if text in ("/cancel", CANCEL):
        draft.clear()
        return reply("Əməliyyat ləğv edildi.")
    if text in ("/new", MENU[0][0]):
        draft.clear()
        draft["step"] = "category"
        return reply("Xidmət kateqoriyasını seçin.", (CATEGORIES[:2], CATEGORIES[2:], (CANCEL,)))

    if text in ("/tickets", MENU[0][1], "Müraciətlərim", MENU[1][0]):
        draft.clear()
        tickets = db.execute("""SELECT t.id, t.status FROM tickets t
            JOIN telegram_ticket_chats c ON c.ticket_id = t.id
            WHERE c.chat_id = ? ORDER BY t.id DESC LIMIT 5""", (chat_id,)).fetchall()
        if not tickets:
            return reply("Müraciət tapılmadı.")
        lines = [f"#{t['id']} · {LABELS[t['status']]}" for t in tickets]
        return reply("\n".join(["Son müraciətləriniz", *lines]),
                     tuple((f"/status {t['id']}", f"/reply {t['id']}") for t in tickets) + MENU)
    if text.split()[:1] == ["/status"]:
        match = re.fullmatch(r"/status\s+#?([1-9][0-9]{0,17})", text)
        if not match:
            return reply("Nümunə: /status 123")
        ticket = db.execute("""SELECT t.id, t.status, t.agent, d.category, d.location,
            (SELECT recorded_at FROM ticket_events WHERE ticket_id=t.id AND kind='received'
             ORDER BY id LIMIT 1) AS received_at
            FROM tickets t JOIN telegram_ticket_chats c ON c.ticket_id=t.id
            LEFT JOIN telegram_ticket_details d ON d.ticket_id=t.id
            WHERE t.id=? AND c.chat_id=?""", (int(match[1]), chat_id)).fetchone()
        if not ticket:
            return reply("Müraciət tapılmadı.")
        lines = [f"🎫 #{ticket['id']} · {LABELS[ticket['status']]}"]
        for field, label in (("category", "Kateqoriya"), ("location", "Məkan"),
                             ("agent", "Təyinat"), ("received_at", "Qəbul vaxtı (UTC)")):
            if ticket[field]:
                lines.append(f"{label}: {ticket[field]}")
        latest = db.execute("""SELECT text FROM telegram_conversation
            WHERE ticket_id=? AND direction IN ('operator','system') AND delivery='sent'
            ORDER BY id DESC LIMIT 1""", (ticket["id"],)).fetchone()
        if latest:
            lines.append("Son yenilik: " + latest["text"][:1000])
        return reply("\n".join(lines))
    command = text.strip("⭐ ").split()
    if command and command[0] in ("/reply", "/rate"):
        rate = command[0] == "/rate"
        if len(command) != (3 if rate else 2) or not re.fullmatch(r"[1-9][0-9]{0,17}", command[1]):
            return reply("Nümunə: /reply 123 və ya /rate 123 5")
        ticket_id = int(command[1])
        ticket = db.execute("""SELECT t.status FROM tickets t
            JOIN telegram_ticket_chats c ON c.ticket_id=t.id
            WHERE t.id=? AND c.chat_id=?""", (ticket_id, chat_id)).fetchone()
        if not ticket:
            return reply("Müraciət tapılmadı.")
        if rate:
            if ticket["status"] != "Resolved" or command[2] not in ("1", "2", "3", "4", "5"):
                return reply("Həll edilmiş müraciəti 1–5 arası qiymətləndirin.")
            inserted = db.execute("INSERT OR IGNORE INTO telegram_ratings VALUES (?, ?)",
                                  (ticket_id, int(command[2]))).rowcount
            return reply("Qiymətiniz qeydə alındı." if inserted else "Bu müraciəti artıq qiymətləndirmisiniz.")
        draft.clear()
        draft.update(step="conversation", ticket_id=ticket_id)
        return reply(f"#{ticket_id} üçün mesajınızı yazın.", ((CANCEL,),))
    if step == "conversation" and not text.startswith("/"):
        if not 1 <= len(text) <= 2000:
            return reply("Mesaj 1–2000 simvol olmalıdır.", ((CANCEL,),))
        ticket_id = draft["ticket_id"]
        inserted = db.execute("""INSERT INTO telegram_conversation(ticket_id,direction,text,delivery)
            SELECT ticket_id,'customer',?,'received' FROM telegram_ticket_chats
            WHERE ticket_id=? AND chat_id=?""", (text, ticket_id, chat_id)).rowcount
        draft.clear()
        return reply("Mesaj operatora çatdı." if inserted else "Müraciət tapılmadı.")
    if re.match(r"/[A-Za-z]", text):
        return reply("Bu əmr tanınmadı. Mövcud seçimlər üçün /menu yazın.")

    if step == "category":
        if text not in CATEGORIES:
            return reply("Kateqoriyanı düymələrdən seçin.", (CATEGORIES[:2], CATEGORIES[2:], (CANCEL,)))
        draft.update(step="location", category=text.split(" ", 1)[1])
        return reply("Məkanı seçin və ya şəhərin adını yazın.", (LOCATIONS[:2], LOCATIONS[2:], (CANCEL,)))
    if step == "location":
        if text == LOCATIONS[-1]:
            return reply("Şəhərin adını yazın.", ((CANCEL,),))
        if not 1 <= len(text) <= 100:
            return reply("Məkan 1–100 simvol olmalıdır.", ((CANCEL,),))
        draft.update(step="description", location=text.removeprefix("📍 "))
        return reply("Problemi təsvir edin (ən çox 2000 simvol).", ((CANCEL,),))
    if step == "description":
        if not 1 <= len(text) <= 2000:
            return reply("Təsvir 1–2000 simvol olmalıdır.", ((CANCEL,),))
        draft.update(step="confirm", description=text)
        return reply(f"Kateqoriya: {draft['category']}\nMəkan: {draft['location']}\n"
                     f"Təsvir: {text}", ((CONFIRM, EDIT), (CANCEL,)))
    if step == "confirm":
        if text == EDIT:
            draft.clear()
            draft["step"] = "category"
            return reply("Kateqoriyanı yenidən seçin.", (CATEGORIES[:2], CATEGORIES[2:], (CANCEL,)))
        if text != CONFIRM:
            return reply("Müraciəti təsdiqləyin və ya düzəliş edin.", ((CONFIRM, EDIT), (CANCEL,)))
        category, location = draft["category"], draft["location"]
        body = f"{category} · {location}\n{draft['description']}"
        ticket = create_ticket(db, "telegram", update_id, body, chat_id)[0]
        db.execute("INSERT OR IGNORE INTO telegram_ticket_details VALUES (?, ?, ?)",
                   (ticket["id"], category, location))
        draft.clear()
        return reply(f"Müraciətiniz qəbul edildi. Müraciət nömrəsi: #{ticket['id']}\n"
                     f"Vəziyyət: {LABELS[ticket['status']]}")
    if text in (*CATEGORIES, *LOCATIONS, CONFIRM, EDIT):
        return reply("Başlamaq üçün Yeni müraciət düyməsini seçin.")
    return None
