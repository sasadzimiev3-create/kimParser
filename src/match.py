from src.targets import KEYWORDS


def normalize(text):
    return text.casefold().replace("ё", "е")


def matching_keyword(text):
    if not text:
        return None
    haystack = normalize(text)
    for keyword in sorted(KEYWORDS, key=len, reverse=True):
        if normalize(keyword) in haystack:
            return keyword
    return None


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
