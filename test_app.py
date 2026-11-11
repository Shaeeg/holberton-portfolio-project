import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, load_routing_rules
from demo import forward_updates


class SupportTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        app = create_app(Path(directory.name) / "test.sqlite3")
        app.config.update(TESTING=True, TELEGRAM_SECRET="test-token", INBOUND_SECRET="test-inbound")
        self.client = app.test_client()

    def telegram(self, payload):
        return self.client.post(
            "/webhooks/telegram",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-token"},
        )

    def test_telegram_routes_and_deduplicates(self):
        payload = {"update_id": 10, "message": {"text": "Bakıda internet problemi"}}
        created = self.telegram(payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["agent"], "Bakı")
        self.assertEqual(created.json["status"], "Assigned")
        self.assertEqual(self.telegram(payload).status_code, 200)
        self.assertEqual(len(self.client.get("/api/tickets").json), 1)

    def test_polling_forwards_text_and_skips_non_text(self):
        updates = [
            {"update_id": 40, "message": {"text": "Elektrik problemi"}},
            {"update_id": 41, "message": {"photo": []}},
        ]
        self.assertEqual(forward_updates(self.client, "test-token", updates, None), 42)
        self.assertEqual(forward_updates(self.client, "test-token", updates, None), 42)
        tickets = self.client.get("/api/tickets").json
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["agent"], "Elektrik")


    def test_inbound_channels_and_board_update(self):
        for channel in ("email", "whatsapp"):
            with self.subTest(channel=channel):
                response = self.client.post(
                    f"/webhooks/{channel}",
                    json={"id": "same-id", "text": "Kömək lazımdır"},
                    headers={"X-Webhook-Secret": "test-inbound"},
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json["status"], "New")
        ticket_id = response.json["id"]
        self.assertEqual(self.client.patch(f"/api/tickets/{ticket_id}", json={"status": "Resolved"}).status_code, 200)
        self.assertEqual(self.client.get("/api/tickets").json[0]["status"], "Resolved")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_manual_assignment_moves_new_ticket_and_can_be_cleared(self):
        ticket = self.telegram({"update_id": 55, "message": {"text": "Kömək"}}).json
        url = f"/api/tickets/{ticket['id']}/assignment"
        assigned = self.client.put(url, json={"agent": " Aysel "}).json
        self.assertEqual((assigned["agent"], assigned["status"]), ("Aysel", "Assigned"))
        cleared = self.client.put(url, json={"agent": ""}).json
        self.assertEqual((cleared["agent"], cleared["status"]), (None, "New"))
        self.assertEqual(self.client.put(url, json={"agent": []}).status_code, 400)

    def test_history_records_changes_once(self):
        payload = {"update_id": 71, "message": {"text": "Bakıda internet problemi"}}
        ticket = self.telegram(payload).json
        self.telegram(payload)
        path = f"/api/tickets/{ticket['id']}"
        for _ in range(2):
            self.client.patch(path, json={"status": "In Progress"})
        events = self.client.get(path + "/events").json
        self.assertEqual([(event["kind"], event["detail"]) for event in events], [
            ("status", "In Progress"), ("assignment", "Bakı"), ("received", "telegram"),
        ])
        self.assertEqual(self.client.get("/api/tickets/999/events").status_code, 404)

    def test_manual_ticket_uses_shared_routing(self):
        response = self.client.post("/api/tickets", json={"text": "İnternet kəsilib"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json["channel"], response.json["agent"]), ("manual", "Şəbəkə"))
        self.assertEqual(self.client.post("/api/tickets", json={"text": " "}).status_code, 400)

    def test_urgent_ticket_is_listed_first_and_logged_once(self):
        first = self.client.post("/api/tickets", json={"text": "Birinci"}).json
        self.client.post("/api/tickets", json={"text": "İkinci"})
        path = f"/api/tickets/{first['id']}"
        self.assertEqual(first["priority"], "normal")
        for _ in range(2):
            self.assertEqual(self.client.put(path + "/priority", json={"priority": "urgent"}).status_code, 200)
        self.assertEqual(self.client.get("/api/tickets").json[0]["id"], first["id"])
        events = self.client.get(path + "/events").json
        self.assertEqual([event["detail"] for event in events if event["kind"] == "priority"], ["urgent"])
        self.assertEqual(self.client.put(path + "/priority", json={"priority": "invalid"}).status_code, 400)

    def test_telegram_confirmation_is_sent_once(self):
        updates = [{"update_id": 90, "message": {"chat": {"id": 42}, "text": "Kömək"}}]
        with patch("demo.telegram_call") as telegram:
            self.assertEqual(forward_updates(self.client, "test-token", updates, None, "test"), 91)
            self.assertEqual(forward_updates(self.client, "test-token", updates, None, "test"), 91)
        ticket_id = self.client.get("/api/tickets").json[0]["id"]
        telegram.assert_called_once_with("test", "sendMessage", {
            "chat_id": 42,
            "text": f"Müraciətiniz qəbul edildi. Müraciət nömrəsi: #{ticket_id}",
        })

    def test_telegram_status_only_available_to_originating_chat(self):
        chat = {"id": 42, "type": "private"}
        ticket = self.telegram({"update_id": 99, "message": {"chat": chat, "text": "Kömək"}}).json
        lookup = self.client.application.extensions["telegram_status"]
        self.assertNotIn("chat_id", ticket)
        with patch("demo.telegram_call") as telegram:
            for update_id, chat_id in ((100, 42), (101, 43)):
                update = {"update_id": update_id, "message": {
                    "chat": {**chat, "id": chat_id}, "text": f"/status {ticket['id']}",
                }}
                self.assertEqual(
                    forward_updates(self.client, "test-token", [update], None, "test", lookup),
                    update_id + 1,
                )
        replies = [call.args[2]["text"] for call in telegram.call_args_list]
        self.assertEqual(replies, [f"Müraciət #{ticket['id']} · Yeni", "Müraciət tapılmadı."])
        self.assertEqual(len(self.client.get("/api/tickets").json), 1)

    def test_telegram_ticket_list_is_private_and_limited(self):
        chat = {"id": 42, "type": "private"}
        for update_id in range(1, 8):
            self.telegram({"update_id": update_id, "message": {"chat": chat, "text": "Kömək"}})
        lookup = self.client.application.extensions["telegram_tickets"]
        self.assertEqual([ticket["id"] for ticket in lookup(42)], [7, 6, 5, 4, 3])
        self.assertEqual(lookup(43), [])
        with patch("demo.telegram_call") as telegram:
            update = {"update_id": 8, "message": {"chat": chat, "text": "/tickets"}}
            self.assertEqual(
                forward_updates(self.client, "test-token", [update], None, "test", list_tickets=lookup),
                9,
            )
        reply = telegram.call_args.args[2]["text"]
        self.assertIn("#7 · Yeni", reply)
        self.assertNotIn("#2 ·", reply)
        self.assertEqual(len(self.client.get("/api/tickets").json), 7)

    def test_telegram_menu_button_and_unknown_commands_do_not_create_tickets(self):
        chat = {"id": 42, "type": "private"}
        updates = [
            {"update_id": update_id, "message": {"chat": chat, "text": text}}
            for update_id, text in enumerate(("/help", "Müraciətlərim", "/typo"), 1)
        ]
        with patch("demo.telegram_call") as telegram:
            self.assertEqual(forward_updates(
                self.client, "test-token", updates, None, "test",
                list_tickets=self.client.application.extensions["telegram_tickets"],
            ), 4)
        replies = [call.args[2] for call in telegram.call_args_list]
        self.assertIn({"text": "Müraciətlərim"}, replies[0]["reply_markup"]["keyboard"][1])
        self.assertEqual(replies[1]["text"], "Müraciət tapılmadı.")
        self.assertIn("/menu", replies[2]["text"])
        self.assertEqual(self.client.get("/api/tickets").json, [])

    def test_internal_note_is_persisted_in_history(self):
        ticket = self.client.post("/api/tickets", json={"text": "Kömək"}).json
        path = f"/api/tickets/{ticket['id']}"
        self.assertEqual(self.client.post(path + "/notes", json={"text": "  Müştəriyə zəng edildi. "}).status_code, 201)
        event = self.client.get(path + "/events").json[0]
        self.assertEqual((event["kind"], event["detail"]), ("note", "Müştəriyə zəng edildi."))
        self.assertEqual(self.client.post(path + "/notes", json={"text": " "}).status_code, 400)
        self.assertEqual(self.client.post("/api/tickets/999/notes", json={"text": "Qeyd"}).status_code, 404)

    def test_board_revalidation_only_downloads_changed_ticket_lists(self):
        initial = self.client.get("/api/tickets")
        headers = {"If-None-Match": initial.headers["ETag"]}
        unchanged = self.client.get("/api/tickets", headers=headers)
        self.assertEqual((unchanged.status_code, unchanged.data), (304, b""))
        ticket = self.client.post("/api/tickets", json={"text": "Kömək"}).json
        changed = self.client.get("/api/tickets", headers=headers)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json[0]["id"], ticket["id"])
        self.assertEqual(changed.json[0]["received_at"], self.client.get(
            f"/api/tickets/{ticket['id']}/events"
        ).json[0]["recorded_at"])
        self.assertNotEqual(changed.headers["ETag"], initial.headers["ETag"])

    def test_resolution_timestamp_follows_current_status(self):
        ticket = self.client.post("/api/tickets", json={"text": "Kömək"}).json
        path = f"/api/tickets/{ticket['id']}"
        self.assertIsNone(self.client.get("/api/tickets").json[0]["resolved_at"])
        self.client.patch(path, json={"status": "Resolved"})
        resolved = self.client.get("/api/tickets").json[0]
        self.assertEqual(resolved["resolved_at"], self.client.get(path + "/events").json[0]["recorded_at"])
        self.client.patch(path, json={"status": "In Progress"})
        self.assertIsNone(self.client.get("/api/tickets").json[0]["resolved_at"])

    def test_configured_routing_uses_first_matching_rule(self):
        app = self.client.application
        app.config["ROUTING_RULES"] = load_routing_rules(
            '[["Gəncə", "Aysel"], ["internet", "Nicat"]]'
        )
        ticket = self.client.post("/api/tickets", json={"text": "GƏNCƏ internet"}).json
        self.assertEqual((ticket["agent"], ticket["status"]), ("Aysel", "Assigned"))
        app.config["ROUTING_RULES"] = load_routing_rules("[]")
        self.assertEqual(
            self.client.post("/api/tickets", json={"text": "Gəncə internet"}).json["status"],
            "New",
        )
        for invalid in ("{", "{}", '[["", "Aysel"]]'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                load_routing_rules(invalid)

    def test_rejects_untrusted_or_invalid_input(self):
        self.assertEqual(self.client.post("/webhooks/telegram", json={}).status_code, 401)
        self.assertEqual(self.telegram({"update_id": []}).status_code, 400)
        self.assertEqual(self.telegram({"update_id": 1, "message": {"photo": []}}).status_code, 204)
        self.assertEqual(self.client.patch("/api/tickets/1", json={"status": []}).status_code, 400)
        self.assertEqual(self.client.patch("/api/tickets/1", json={"status": "New"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
