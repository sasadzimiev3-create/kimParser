import unittest
from types import SimpleNamespace

from src.match import in_topic, matching_keyword, topic_id_from_reply


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

    def test_no_match(self):
        self.assertIsNone(matching_keyword("ищем монтажёра"))
        self.assertIsNone(matching_keyword(""))

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
