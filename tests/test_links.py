import unittest

from src.links import parse_link, peer_id_from_channel, private_message_link, trailing_telegram_link


class LinkTests(unittest.TestCase):
    def test_public_and_topic(self):
        link = parse_link("смотрите https://t.me/WorkProKino/196.")
        self.assertEqual(link.kind, "public")
        self.assertEqual(link.username, "workprokino")
        self.assertEqual(link.ref_id, 196)
        self.assertEqual(link.link, "https://t.me/workprokino/196")

    def test_mention_and_invite(self):
        mention = parse_link("@Jetlagchat")
        self.assertEqual(mention.username, "jetlagchat")
        self.assertIsNone(mention.ref_id)
        invite = parse_link("https://t.me/joinchat/AbC_def")
        self.assertEqual(invite.kind, "invite")
        self.assertEqual(invite.invite, "AbC_def")
        self.assertEqual(invite.link, "https://t.me/+AbC_def")

    def test_private_roundtrip(self):
        peer = -1001391677315
        link = private_message_link(peer, 243544)
        parsed = parse_link(link)
        self.assertEqual(parsed.kind, "private")
        self.assertEqual(peer_id_from_channel(parsed.internal_id), peer)
        self.assertEqual(parsed.ref_id, 243544)

    def test_email_is_not_a_chat(self):
        self.assertIsNone(parse_link("пишите user@mail.ru"))

    def test_trailing_link_is_the_last_one(self):
        text = "внутри https://t.me/other/1\n\nhttps://t.me/jetlagchat/50"
        self.assertEqual(trailing_telegram_link(text), "https://t.me/jetlagchat/50")
