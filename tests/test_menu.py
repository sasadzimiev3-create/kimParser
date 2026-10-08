import json
import tempfile
import unittest
from pathlib import Path

from src.menu import BUTTONS, menu_text
from src.stats import WEEK_SECONDS, KeywordStats


class MenuTextTests(unittest.TestCase):
    def test_top_three(self):
        text = menu_text(
            3,
            11,
            [("оператор", 4), ("съёмка", 2), ("смена", 1), ("снять", 1)],
        )
        self.assertEqual(
            text,
            "\n".join(
                [
                    "<b>⚙️ Меню:</b>",
                    "💬Чатов: 3",
                    "🔑 слов: 11",
                    "",
                    "<u>📊Статистика за неделю:</u>",
                    "🥇 оператор - 4",
                    "🥈 съёмка - 2",
                    "🥉 смена - 1",
                ]
            ),
        )

    def test_empty_week(self):
        text = menu_text(3, 11, [])
        self.assertIn("<b>⚙️ Меню:</b>", text)
        self.assertIn("💬Чатов: 3", text)
        self.assertIn("🔑 слов: 11", text)
        self.assertIn("<u>📊Статистика за неделю:</u>", text)
        self.assertIn("Пока нет совпадений", text)
        self.assertNotIn("🥇", text)

    def test_keyword_is_escaped(self):
        text = menu_text(1, 1, [("<b>", 1)])
        self.assertIn("🥇 &lt;b&gt; - 1", text)

    def test_buttons_are_a_pair(self):
        self.assertEqual([label for label, _ in BUTTONS], ["Чаты", "Ключ слова"])


class KeywordStatsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "keyword_stats.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_week_window_and_reload(self):
        stats = KeywordStats(self.path)
        stats.record("старое", now=-1)
        stats.record("оператор", now=WEEK_SECONDS)
        stats.record("оператор", now=WEEK_SECONDS)
        stats.record("съёмка", now=WEEK_SECONDS)
        self.assertEqual(
            stats.top(now=WEEK_SECONDS),
            [("оператор", 2), ("съёмка", 1)],
        )
        saved = json.loads(self.path.read_text())
        self.assertEqual(
            [item[1] for item in saved],
            ["оператор", "оператор", "съёмка"],
        )
        again = KeywordStats(self.path)
        self.assertEqual(again.top(now=WEEK_SECONDS), [("оператор", 2), ("съёмка", 1)])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_edge_of_the_week_drops_off(self):
        stats = KeywordStats(self.path)
        stats.record("край", now=1000)
        moment = 1000 + WEEK_SECONDS
        self.assertEqual(stats.top(now=moment), [("край", 1)])
        self.assertEqual(stats.top(now=moment + 1), [])

    def test_only_top_three_ties_break_by_name(self):
        stats = KeywordStats(self.path)
        for _ in range(5):
            stats.record("а", now=10)
        for _ in range(2):
            stats.record("б", now=10)
        for _ in range(2):
            stats.record("в", now=10)
        stats.record("г", now=10)
        self.assertEqual(stats.top(now=10), [("а", 5), ("б", 2), ("в", 2)])

    def test_corrupt_file_does_not_block_new_stats(self):
        self.path.write_text("nope")
        stats = KeywordStats(self.path)
        self.assertEqual(stats.top(now=10), [])
        stats.record("смена", now=10)
        self.assertEqual(stats.top(now=10), [("смена", 1)])
        self.assertEqual(json.loads(self.path.read_text()), [[10, "смена"]])


class DeployKeepFilesTests(unittest.TestCase):
    def test_deploy_keeps_subscriber_and_stats_files(self):
        script = Path(__file__).resolve().parents[1].joinpath("deploy", "deploy.sh").read_text()
        self.assertIn("--exclude 'subscribers.json'", script)
        self.assertIn("--exclude 'keyword_stats.json'", script)
        self.assertIn("--exclude 'keyword_stats.json.tmp'", script)
