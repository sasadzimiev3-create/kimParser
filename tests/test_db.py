import json
import tempfile
import unittest
from pathlib import Path

from src.db import WEEK_SECONDS, Database, moscow_day_start
from src.targets import KEYWORDS, TOPICS


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "kimparser.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.conn.close()
        self._tmp.cleanup()

    def test_new_user_starts_empty(self):
        self.assertTrue(self.db.prepare_user(7))
        self.assertEqual(self.db.counts(7), (0, 0))
        self.assertEqual(self.db.list_chats(7), [])
        self.assertEqual(self.db.list_keywords(7), [])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.db.prepare_user(7))
        self.assertEqual(self.db.counts(7), (0, 0))
        other = Database(self.path)
        try:
            self.assertEqual(other.counts(7), (0, 0))
        finally:
            other.conn.close()

    def test_stopped_user_is_left_out_of_matches(self):
        self.db.prepare_user(1)
        self.db.prepare_user(2)
        for user_id in (1, 2):
            self.db.add_chat(
                user_id,
                link="https://t.me/extra/1",
                title="Extra",
                status="active",
                peer_id=-1005,
                topic_id=1,
            )
            self.assertIsNone(self.db.add_keyword(user_id, "оператор"))
        self.assertTrue(self.db.is_running(1))
        self.assertEqual({row["user_id"] for row in self.db.matching_rows(-1005)}, {1, 2})
        self.assertFalse(self.db.set_running(1, False))
        self.assertEqual({row["user_id"] for row in self.db.matching_rows(-1005)}, {2})
        self.assertTrue(self.db.set_running(1, True))
        self.assertEqual({row["user_id"] for row in self.db.matching_rows(-1005)}, {1, 2})

    def test_admin_snapshot_counts_live_sessions(self):
        self.db.prepare_user(1)
        self.db.prepare_user(2)
        self.db.set_running(2, False)
        self.db.add_chat(
            1,
            link="https://t.me/a/1",
            title="A",
            status="active",
            peer_id=-100,
            topic_id=1,
        )
        self.db.add_chat(
            1,
            link="https://t.me/a/2",
            title="A",
            status="active",
            peer_id=-100,
            topic_id=2,
        )
        self.db.add_chat(
            1,
            link="https://t.me/d",
            title="D",
            status="requested",
        )
        self.db.add_chat(
            2,
            link="https://t.me/b/1",
            title="B",
            status="pending",
            peer_id=-200,
            topic_id=1,
        )
        self.db.add_chat(2, link="https://t.me/c", title="C", status="failed")
        self.assertIsNone(self.db.add_keyword(1, "оператор"))
        self.assertIsNone(self.db.add_keyword(2, "смена"))
        start = moscow_day_start(1_800_000_000)
        self.db.record_hit(1, "оператор", now=start)
        self.db.record_hit(1, "смена", now=start - 1)
        self.db.record_hit(2, "оператор", now=start)
        self.db.plan_delivery(-100, 9, [(1, "оператор")], now=start)
        self.db.plan_delivery(-100, 8, [(2, "смена")], now=start)
        self.db.claim_delivery(-100, 8)
        snap = self.db.admin_snapshot([1, 2, 3, 1], now=start + 5)
        self.assertEqual(snap["running"], 2)
        self.assertEqual(snap["stopped"], 1)
        self.assertEqual(snap["connected"], 3)
        self.assertEqual(snap["profiles"], 2)
        self.assertEqual(snap["peers"], 1)
        self.assertEqual(snap["subscriptions"], 5)
        self.assertEqual(snap["active"], 2)
        self.assertEqual(snap["pending"], 1)
        self.assertEqual(snap["requested"], 1)
        self.assertEqual(snap["failed"], 1)
        self.assertEqual(snap["keywords"], 2)
        self.assertEqual(snap["hits_today"], 2)
        self.assertEqual(snap["hits_week"], 3)
        self.assertEqual(snap["top"][0], ("оператор", 2))
        self.assertEqual(snap["queued"], 1)
        self.assertEqual(snap["sending"], 1)
        self.assertEqual([person["user_id"] for person in snap["people"]], [1, 2, 3])
        first = snap["people"][0]
        self.assertEqual(first["chats"], 3)
        self.assertEqual(first["live"], 2)
        self.assertEqual(first["words"], 1)
        self.assertEqual(first["hits"], 2)
        self.assertEqual(snap["people"][1]["live"], 0)
        self.assertTrue(snap["people"][2]["running"])
        self.assertEqual(snap["people"][2]["chats"], 0)
        empty = self.db.admin_snapshot([], now=start + 5)
        self.assertEqual(empty["running"], 0)
        self.assertEqual(empty["people"], [])
        self.assertEqual(empty["hits_week"], 3)

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
        self.assertIsNone(self.db.add_keyword(1, " оператор "))
        self.assertEqual(self.db.add_keyword(1, "оператор"), "Такое слово уже есть.")
        self.assertEqual(self.db.list_keywords(2), [])
        self.assertEqual(self.db.list_chats(2), [])
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
        self.db.add_chat(
            4,
            link="https://t.me/JETLAGCHAT/44320",
            title="@jetlagchat",
            status="pending",
            username="jetlagchat",
            topic_id=44320,
        )
        self.assertTrue(self.db.same_link(4, "https://t.me/jetlagchat/44320"))
        self.assertFalse(self.db.same_link(8, "https://t.me/jetlagchat/44320"))

    def test_old_users_start_running(self):
        self.db.conn.execute("PRAGMA foreign_keys=OFF")
        self.db.conn.execute("DROP TABLE users")
        self.db.conn.execute(
            """CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                seeded INTEGER NOT NULL DEFAULT 0,
                wizard TEXT,
                wizard_payload TEXT NOT NULL DEFAULT '[]'
            )"""
        )
        self.db.conn.execute(
            "INSERT INTO users(user_id, seeded, wizard, wizard_payload) VALUES(7, 1, NULL, '[]')"
        )
        self.db._add_column("users", "running", "INTEGER NOT NULL DEFAULT 1")
        self.assertTrue(self.db.is_running(7))
        self.assertFalse(self.db.set_running(7, False))
        self.assertFalse(self.db.is_running(7))

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

    def test_unused_starter_copy_is_removed_once(self):
        self._copy_starter(9, "pending")
        self._copy_starter(3, "active")
        self.db.prepare_user(4)
        self.assertIsNone(self.db.add_keyword(4, "педик"))
        self.assertEqual(self.db.drop_copied_starters(), 1)
        self.assertEqual(self.db.counts(9), (0, 0))
        self.assertEqual(self.db.counts(3), (sum(len(ids) for ids in TOPICS.values()), len(KEYWORDS)))
        self.assertEqual([row["keyword"] for row in self.db.list_keywords(4)], ["педик"])
        self._copy_starter(9, "pending")
        self.assertEqual(self.db.drop_copied_starters(), 0)
        self.assertEqual(self.db.counts(9), (sum(len(ids) for ids in TOPICS.values()), len(KEYWORDS)))

    def _copy_starter(self, user_id, status):
        self.db.prepare_user(user_id)
        for username, topic_ids in TOPICS.items():
            for topic_id in topic_ids:
                self.db.add_chat(
                    user_id,
                    link="https://t.me/{}/{}".format(username.lower(), topic_id),
                    title="@" + username,
                    status=status,
                    username=username,
                    topic_id=topic_id,
                )
        for keyword in KEYWORDS:
            self.assertIsNone(self.db.add_keyword(user_id, keyword))
