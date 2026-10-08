import json
import tempfile
import unittest
from pathlib import Path

from src.db import WEEK_SECONDS, Database
from src.targets import KEYWORDS, TOPICS


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "kimparser.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.conn.close()
        self._tmp.cleanup()

    def test_seed_once_and_reload(self):
        self.assertTrue(self.db.prepare_user(7))
        chats, words = self.db.counts(7)
        self.assertEqual(chats, sum(len(ids) for ids in TOPICS.values()))
        self.assertEqual(words, len(KEYWORDS))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        first = self.db.list_chats(7)[0]["id"]
        self.db.delete_chat(7, first)
        self.assertFalse(self.db.prepare_user(7))
        self.assertEqual(self.db.counts(7)[0], chats - 1)
        other = Database(self.path)
        try:
            self.assertEqual(other.counts(7), (chats - 1, words))
        finally:
            other.conn.close()

    def test_users_do_not_share_chats_or_words(self):
        self.db.prepare_user(1)
        self.db.prepare_user(2)
        self.db.add_chat(
            1,
            link="https://t.me/extra",
            title="Extra",
            status="active",
            username="extra",
            peer_id=-1005,
        )
        self.assertIsNone(self.db.add_keyword(1, "уникальное"))
        self.assertEqual(self.db.add_keyword(1, " оператор "), "Такое слово уже есть.")
        self.assertEqual(self.db.add_keyword(1, "я"), "Слишком короткое слово.")
        self.assertIsNone(self.db.peer_by_username("missing"))
        self.assertEqual(self.db.peer_by_username("Extra"), -1005)
        self.assertTrue(self.db.peer_in_use(-1005))
        own = [row for row in self.db.list_chats(1) if row["peer_id"] == -1005][0]
        self.db.delete_chat(2, own["id"])
        self.assertTrue(self.db.peer_in_use(-1005))
        self.db.delete_chat(1, own["id"])
        self.assertFalse(self.db.peer_in_use(-1005))
        self.assertEqual(self.db.top_keywords(2, now=10), [])
        self.db.record_hit(1, "уникальное", now=10)
        self.assertEqual(self.db.top_keywords(1, now=10), [("уникальное", 1)])
        self.assertEqual(self.db.top_keywords(2, now=10), [])

    def test_week_and_delivery_plan(self):
        self.db.record_hit(1, "старое", now=-1)
        self.db.record_hit(1, "оператор", now=WEEK_SECONDS)
        self.db.record_hit(1, "оператор", now=WEEK_SECONDS)
        self.db.record_hit(1, "съёмка", now=WEEK_SECONDS)
        self.assertEqual(
            self.db.top_keywords(1, now=WEEK_SECONDS),
            [("оператор", 2), ("съёмка", 1)],
        )
        self.assertEqual(self.db.top_keywords(1, now=WEEK_SECONDS + WEEK_SECONDS + 1), [])
        self.db.plan_delivery(
            -1001,
            9,
            [(1, "оператор", "Jetlag", "https://t.me/jetlagchat/44320"), (2, "смена")],
            now=WEEK_SECONDS,
        )
        self.assertEqual(
            sorted(self.db.claim_delivery(-1001, 9)),
            [
                (1, "оператор", "Jetlag", "https://t.me/jetlagchat/44320"),
                (2, "смена", "", ""),
            ],
        )
        self.assertEqual(self.db.claim_delivery(-1001, 9), [])
        self.db.release_delivery(-1001, 9, 1)
        self.assertEqual(
            self.db.claim_delivery(-1001, 9),
            [(1, "оператор", "Jetlag", "https://t.me/jetlagchat/44320")],
        )

    def test_legacy_stats_import_once(self):
        self.db.prepare_user(1, now=1)
        self.db.prepare_user(2, now=1)
        legacy = self.path.parent / "keyword_stats.json"
        legacy.write_text(json.dumps([[10, "оператор"], [10, "оператор"]]))
        self.db.import_legacy_file(legacy)
        self.assertEqual(self.db.top_keywords(1, now=10), [("оператор", 2)])
        self.assertEqual(self.db.top_keywords(2, now=10), [("оператор", 2)])
        self.db.import_legacy_file(legacy)
        self.assertEqual(self.db.top_keywords(1, now=10), [("оператор", 2)])
        broken = self.path.parent / "broken.json"
        broken.write_text("nope")
        fresh = Database(self.path.parent / "other.db")
        try:
            fresh.prepare_user(3, now=1)
            fresh.import_legacy_file(broken)
            self.assertEqual(fresh.top_keywords(3, now=1), [])
            fresh.record_hit(3, "смена", now=1)
            self.assertEqual(fresh.top_keywords(3, now=1), [("смена", 1)])
        finally:
            fresh.conn.close()

    def test_wizard_roundtrip(self):
        self.db.prepare_user(4)
        self.db.set_wizard(4, "del_chat", [8, 3])
        self.assertEqual(self.db.wizard(4), ("del_chat", [8, 3]))
        self.db.clear_wizard(4)
        self.assertEqual(self.db.wizard(4), (None, []))
        self.assertTrue(self.db.same_link(4, "https://t.me/JETLAGCHAT/44320"))

    def test_old_deliveries_gain_chat_columns(self):
        self.db.conn.execute("DROP TABLE deliveries")
        self.db.conn.execute(
            """CREATE TABLE deliveries (
                peer_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (peer_id, msg_id, user_id)
            )"""
        )
        self.db._add_column("deliveries", "chat_name", "TEXT NOT NULL DEFAULT ''")
        self.db._add_column("deliveries", "chat_link", "TEXT NOT NULL DEFAULT ''")
        self.db.plan_delivery(
            5,
            6,
            [(7, "смена", "Work", "https://t.me/WorkProKino/196")],
            now=1,
        )
        self.assertEqual(
            self.db.claim_delivery(5, 6),
            [(7, "смена", "Work", "https://t.me/WorkProKino/196")],
        )
