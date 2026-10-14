import unittest
from pathlib import Path

from src.menu import (
    ADMIN_ID,
    CHAT_ROWS,
    WORD_ROWS,
    admin_text,
    chat_label,
    chat_menu_line,
    chats_text,
    choice_message,
    hit_note,
    home_rows,
    is_admin,
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
        running = home_rows(True)
        stopped = home_rows(False)
        self.assertEqual([label for label, _ in running[0]], ["Чаты", "Ключ слова"])
        self.assertEqual(running[1], (("Остановить", b"menu:run"),))
        self.assertEqual(stopped[1], (("Запустить", b"menu:run"),))
        self.assertEqual(len(running[1]), 1)
        self.assertEqual(len(running), 2)
        admin = home_rows(True, admin=True)
        self.assertEqual(admin[2], (("Админ", b"menu:admin"),))
        self.assertTrue(is_admin(ADMIN_ID))
        self.assertTrue(is_admin(str(ADMIN_ID)))
        self.assertFalse(is_admin(1))
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
        note = hit_note("оператор", "@jetlagchat — тема 44320", "https://t.me/jetlagchat/44320/50")
        self.assertEqual(
            note,
            "Ключ: <i>оператор</i>\n"
            "Чат: @jetlagchat — тема 44320\n"
            '<a href="https://t.me/jetlagchat/44320/50">https://t.me/jetlagchat/44320/50</a>',
        )
        self.assertEqual(
            message_with_note("нужен оператор", note),
            "нужен оператор\n" + note,
        )
        self.assertEqual(hit_note("", "", ""), "Ключ: —\nЧат: —")

    def test_admin_screen(self):
        people = [
            {
                "user_id": index,
                "running": True,
                "chats": 1,
                "live": 1,
                "words": 1,
                "hits": 0,
            }
            for index in range(1, 33)
        ]
        people[0] = {
            "user_id": 7,
            "running": True,
            "chats": 0,
            "live": 0,
            "words": 0,
            "hits": 3,
        }
        text = admin_text(
            {
                "running": 2,
                "stopped": 1,
                "connected": 3,
                "profiles": 4,
                "peers": 3,
                "subscriptions": 5,
                "active": 2,
                "pending": 1,
                "requested": 1,
                "failed": 1,
                "keywords": 8,
                "queued": 0,
                "sending": 1,
                "hits_today": 4,
                "hits_week": 9,
                "top": [("<b>", 2)],
                "people": people,
            }
        )
        self.assertIn("<b>⚙️ Меню:</b> → админ", text)
        self.assertIn("▶️ Запущено сессий: 2", text)
        self.assertIn("⏸ Остановлено: 1", text)
        self.assertIn("👂 Слушаю чатов: 3", text)
        self.assertIn("активных 2, подключаю 1, заявка 1, ошибка 1", text)
        self.assertIn("сегодня 4", text)
        self.assertIn("за 7 дней 9", text)
        self.assertIn("🥇 &lt;b&gt; - 2", text)
        self.assertIn("<code>7</code> — запущена, чатов 0, слов 0, совпадений 3, нечего слать", text)
        self.assertIn("и ещё 2", text)
        self.assertNotIn("<code>32</code>", text)
        empty = admin_text(
            {
                "running": 0,
                "stopped": 0,
                "connected": 0,
                "profiles": 0,
                "peers": 0,
                "subscriptions": 0,
                "active": 0,
                "pending": 0,
                "requested": 0,
                "failed": 0,
                "keywords": 0,
                "queued": 0,
                "sending": 0,
                "hits_today": 0,
                "hits_week": 0,
                "top": [],
                "people": [],
            }
        )
        self.assertIn("Пока нет совпадений", empty)
        self.assertIn("Пока никто не подключён", empty)

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
