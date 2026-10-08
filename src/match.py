import re

from src.targets import KEYWORDS


def normalize(text):
    folded = text.casefold().replace("ё", "е")
    without_punctuation = re.sub(r"[^\w\s]+", " ", folded)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def matching_keyword(text, keywords=None):
    pool = KEYWORDS if keywords is None else keywords
    if not text or not pool:
        return None
    haystack = normalize(text)
    ranked = sorted(pool, key=lambda item: len(normalize(item)), reverse=True)
    for keyword in ranked:
        needle = normalize(keyword)
        if needle and needle in haystack:
            return keyword
    return None


def _row_visible(row, message_id, reply):
    topic_id = row["topic_id"]
    if topic_id is not None and not in_topic(message_id, reply, {topic_id}):
        return False
    return True


def recipients(text, rows, message_id, reply):
    """Кому отправить сообщение: свои слова и только свои темы."""
    chosen = {}
    for row in rows:
        if not _row_visible(row, message_id, reply):
            continue
        words = chosen.setdefault(row["user_id"], [])
        if row["keyword"] not in words:
            words.append(row["keyword"])
    found = []
    for user_id, words in chosen.items():
        keyword = matching_keyword(text, words)
        if keyword:
            found.append((user_id, keyword))
    return found


def matched_chat(rows, user_id, message_id, reply):
    """Чат, из которого пришло совпадение: тема точнее, чем весь чат."""
    found = []
    seen = set()
    for row in rows:
        if row["user_id"] != user_id or not _row_visible(row, message_id, reply):
            continue
        key = (row.get("topic_id"), row.get("link"), row.get("title"))
        if key in seen:
            continue
        seen.add(key)
        found.append(row)
    if not found:
        return None
    specific = [row for row in found if row.get("topic_id") is not None]
    return specific[0] if specific else found[0]


def topic_id_from_reply(reply):
    """Id темы форума. None, если сообщение не из темы."""
    if reply is None or not getattr(reply, "forum_topic", False):
        return None
    return getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None)


def in_topic(message_id, reply, allowed):
    if message_id in allowed:
        return True
    topic_id = topic_id_from_reply(reply)
    return topic_id in allowed
