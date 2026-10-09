import unittest
from pathlib import Path

from src.menu import (
    CHAT_ROWS,
    HOME_ROWS,
    WORD_ROWS,
    chat_label,
    chat_menu_line,
    chats_text,
    choice_message,
    hit_note,
    menu_text,
    message_with_note,
    words_text,
)


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
                    "",
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

    def test_buttons(self):
        self.assertEqual([label for label, _ in HOME_ROWS[0]], ["Чаты", "Ключ слова"])
        self.assertEqual(
            [label for label, _ in CHAT_ROWS[0]],
            ["Добавить чат", "Удалить чат"],
        )
        self.assertEqual(CHAT_ROWS[1][0][0], "◀️ Назад")
        self.assertEqual(
            [label for label, _ in WORD_ROWS[0]],
            ["Добавить слово", "Удалить слово"],
        )

    def test_chat_screen(self):
        label = chat_label("@jetlagchat", None, 44320, "pending")
        line = chat_menu_line(
            "@jetlagchat",
            None,
            44320,
            "pending",
            "https://t.me/jetlagchat/44320",
        )
        text = chats_text([line, "Work"])
        self.assertEqual(
            text,
            "\n".join(
                [
                    "<b>⚙️ Меню:</b> → чаты",
                    "",
                    "Ваши чаты:",
                    "1. @jetlagchat - тема 44320 (подключаю)",
                    "https://t.me/jetlagchat/44320",
                    "2. Work",
                ]
            ),
        )
        self.assertEqual(label + "\nhttps://t.me/jetlagchat/44320", line)
        self.assertEqual(
            chat_menu_line("JETLAG CHAT", "вакансии", None, "active", "https://t.me/jetlagchat/44320"),
            "JETLAG CHAT - вакансии\nhttps://t.me/jetlagchat/44320",
        )
        self.assertEqual(chat_menu_line("Work", None, None, "active", ""), "Work")
        self.assertIn("Пока пусто", chats_text([]))
        self.assertIn("Ваши ключ слова:", words_text(["оператор"]))
        self.assertIn("&lt;b&gt;", chats_text(["<b>\nhttps://t.me/chat"]))

    def test_hit_note_sits_under_the_message(self):
        note = hit_note("оператор", "@jetlagchat — тема 44320", "https://t.me/jetlagchat/50")
        self.assertEqual(
            note,
            "[ Ключ слово: оператор\nЧат: @jetlagchat — тема 44320]\nhttps://t.me/jetlagchat/50",
        )
        self.assertEqual(
            message_with_note("нужен оператор", note),
            "нужен оператор\n" + note,
        )
        self.assertEqual(hit_note("", "", ""), "[ Ключ слово: —\nЧат: —]")

    def test_choice(self):
        self.assertEqual(choice_message("2", 3, "чата"), (2, None))
        self.assertEqual(choice_message("слово", 3, "чата")[1], "Нужен номер из списка.")
        self.assertEqual(choice_message("9", 3, "слова")[1], "Нет слова с таким номером.")


class DeployKeepFilesTests(unittest.TestCase):
    def test_deploy_keeps_subscriber_and_stats_files(self):
        script = Path(__file__).resolve().parents[1].joinpath("deploy", "deploy.sh").read_text()
        self.assertIn("--exclude 'subscribers.json'", script)
        self.assertIn("--exclude 'keyword_stats.json'", script)
        self.assertIn("--exclude 'keyword_stats.json.tmp'", script)
        self.assertIn("--exclude 'kimparser.db'", script)
        self.assertIn("--exclude 'kimparser.db-wal'", script)
        self.assertIn("--exclude 'kimparser.db-shm'", script)
