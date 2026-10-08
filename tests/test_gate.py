import json
import tempfile
import unittest
from pathlib import Path

from src.gate import (
    ASK_PASSWORD,
    ASK_START,
    BAD_PASSWORD,
    CONNECTED,
    SubscriberList,
    handle_private,
    is_listener_alert,
    is_menu,
)


class GateTests(unittest.TestCase):
    def test_start_then_password(self):
        status, reply = handle_private("/start", None, "7927")
        self.assertEqual((status, reply), ("awaiting", ASK_PASSWORD))
        status, reply = handle_private("7927", status, "7927")
        self.assertEqual((status, reply), ("connected", CONNECTED))

    def test_password_before_start(self):
        status, reply = handle_private("7927", None, "7927")
        self.assertEqual((status, reply), (None, ASK_START))

    def test_wrong_password_can_be_retried(self):
        status, reply = handle_private("0000", "awaiting", "7927")
        self.assertEqual((status, reply), ("awaiting", BAD_PASSWORD))
        status, reply = handle_private("7927", status, "7927")
        self.assertEqual(reply, CONNECTED)

    def test_already_connected(self):
        status, reply = handle_private("/start", "connected", "7927")
        self.assertEqual((status, reply), ("connected", CONNECTED))
        status, reply = handle_private("привет", "connected", "7927")
        self.assertEqual((status, reply), ("connected", None))

    def test_punctuation_is_not_the_password(self):
        status, reply = handle_private("7927.", "awaiting", "7927")
        self.assertEqual(reply, BAD_PASSWORD)
        self.assertEqual(status, "awaiting")

    def test_listener_alert(self):
        self.assertTrue(is_listener_alert(5, 5, True, "Оператор"))
        self.assertTrue(is_listener_alert(5, 5, False, "текст\n\nhttps://t.me/jetlagchat/1"))
        self.assertFalse(is_listener_alert(5, 5, False, "/start"))
        self.assertFalse(is_listener_alert(5, 5, False, "/menu"))
        self.assertFalse(is_listener_alert(9, 5, True, "Оператор"))

    def test_menu_command(self):
        self.assertTrue(is_menu("/menu"))
        self.assertTrue(is_menu("/MENU"))
        self.assertTrue(is_menu("/menu@parser4kim_bot"))
        self.assertFalse(is_menu("/start"))
        self.assertFalse(is_menu("меню"))

    def test_menu_does_not_count_as_password(self):
        status, reply = handle_private("/menu", None, "7927")
        self.assertEqual((status, reply), (None, ASK_START))
        status, reply = handle_private("/MENU", "awaiting", "7927")
        self.assertEqual((status, reply), ("awaiting", ASK_PASSWORD))
        status, reply = handle_private("/menu@parser4kim_bot", "connected", "7927")
        self.assertEqual((status, reply), ("connected", None))

    def test_subscriber_file_stays_a_list_of_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "subscribers.json"
            path.write_text("[7, 9]")
            people = SubscriberList(path)
            self.assertEqual(set(people.ids()), {7, 9})
            people.apply(4, "awaiting")
            self.assertEqual(json.loads(path.read_text()), [7, 9])
            people.apply(8, "connected")
            self.assertEqual(json.loads(path.read_text()), [7, 8, 9])
            people.discard(7)
            self.assertEqual(json.loads(path.read_text()), [8, 9])


if __name__ == "__main__":
    unittest.main()
