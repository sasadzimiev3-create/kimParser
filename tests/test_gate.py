import unittest

from src.gate import (
    ASK_PASSWORD,
    ASK_START,
    BAD_PASSWORD,
    CONNECTED,
    handle_private,
    is_listener_alert,
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
        self.assertFalse(is_listener_alert(9, 5, True, "Оператор"))


if __name__ == "__main__":
    unittest.main()
