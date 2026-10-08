import unittest
from types import SimpleNamespace

from src.match import in_topic, matched_chat, matching_keyword, recipients, topic_id_from_reply


def reply(**kwargs):
    defaults = {"forum_topic": False, "reply_to_top_id": None, "reply_to_msg_id": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class MatchTests(unittest.TestCase):
    def test_operator_forms(self):
        self.assertEqual(matching_keyword("Нужен оператор на завтра"), "оператор")
        self.assertEqual(matching_keyword("ищем оператора"), "оператора")
        self.assertEqual(matching_keyword("ВИДЕООПЕРАТОР"), "видеооператор")
        self.assertEqual(matching_keyword("видеооператора в смену"), "видеооператора")

    def test_yo_and_phrase(self):
        self.assertEqual(matching_keyword("есть съемка в пятницу"), "съёмка")
        self.assertEqual(matching_keyword("съёмочный день 12 часов"), "съёмочный день")
        self.assertEqual(matching_keyword("надо отснять интервью"), "отснять")
        self.assertEqual(matching_keyword("можно снять ролик"), "снять")

    def test_case_and_punctuation(self):
        self.assertEqual(matching_keyword("Оператор"), "оператор")
        self.assertEqual(matching_keyword("ОПЕРАТОР"), "оператор")
        self.assertEqual(matching_keyword("Оператор,"), "оператор")
        self.assertEqual(matching_keyword("Оператор."), "оператор")
        self.assertEqual(matching_keyword("нужен оператор, на завтра"), "оператор")
        self.assertEqual(matching_keyword("Съёмка."), "съёмка")
        self.assertEqual(matching_keyword("СЪЁМОЧНЫЙ ДЕНЬ."), "съёмочный день")
        self.assertEqual(matching_keyword("«видеограф»"), "видеограф")
        self.assertEqual(matching_keyword("смена!"), "смена")

    def test_no_match(self):
        self.assertIsNone(matching_keyword("ищем монтажёра"))
        self.assertIsNone(matching_keyword(""))

    def test_custom_list_picks_the_longest_word(self):
        words = ["оператор", "видеооператор"]
        self.assertEqual(matching_keyword("нужен видеооператор", words), "видеооператор")
        self.assertEqual(matching_keyword("нужен оператор", ["смена"]), None)

    def test_recipients_stay_inside_their_topic_and_words(self):
        rows = [
            {"user_id": 1, "topic_id": 10, "keyword": "оператор"},
            {"user_id": 1, "topic_id": 10, "keyword": "видеооператор"},
            {"user_id": 2, "topic_id": None, "keyword": "смена"},
            {"user_id": 3, "topic_id": 11, "keyword": "оператор"},
        ]
        topic = reply(forum_topic=True, reply_to_top_id=10)
        found = recipients("нужен видеооператор, смена завтра", rows, 900, topic)
        self.assertEqual(found, [(1, "видеооператор"), (2, "смена")])
        rows[0]["title"] = "Jetlag"
        rows[0]["link"] = "https://t.me/jetlagchat/10"
        rows[1]["link"] = "https://t.me/jetlagchat/10"
        rows[2]["title"] = "Весь чат"
        rows[2]["link"] = "https://t.me/whole"
        self.assertEqual(matched_chat(rows, 1, 900, topic)["link"], "https://t.me/jetlagchat/10")
        self.assertEqual(matched_chat(rows, 3, 900, topic), None)
        both = [
            {"user_id": 1, "topic_id": None, "title": "Весь", "link": "https://t.me/whole"},
            {"user_id": 1, "topic_id": 10, "title": "Тема", "link": "https://t.me/jetlagchat/10"},
        ]
        self.assertEqual(matched_chat(both, 1, 900, topic)["title"], "Тема")

    def test_topic(self):
        allowed = {44320, 44329}
        header = reply(forum_topic=True, reply_to_top_id=44320, reply_to_msg_id=500)
        self.assertTrue(in_topic(900, header, allowed))
        self.assertFalse(in_topic(900, reply(forum_topic=True, reply_to_top_id=1), allowed))
        self.assertFalse(in_topic(900, None, allowed))
        self.assertTrue(in_topic(44329, None, allowed))
        self.assertEqual(
            topic_id_from_reply(reply(forum_topic=True, reply_to_msg_id=196)),
            196,
        )


if __name__ == "__main__":
    unittest.main()
