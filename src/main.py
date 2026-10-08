import asyncio
import json
import logging
import urllib.error
import urllib.request

from telethon import TelegramClient, events, utils
from telethon.errors import (
    FloodWaitError,
    InviteRequestSentError,
    UserAlreadyParticipantError,
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import MessageMediaWebPage

from src.bot import register_bot
from src.gate import SubscriberList
from src.match import in_topic, matching_keyword, topic_id_from_reply
from src.settings import require_settings
from src.targets import TOPICS

log = logging.getLogger("kimparser")

# region agent log
def _dbg(hyp, loc, msg, data):
    import time
    with open("/var/log/kimparser-debug-820a6e.log", "a") as f:
        f.write(json.dumps({"sessionId": "820a6e", "runId": "pre-fix", "hypothesisId": hyp, "location": loc, "message": msg, "data": data, "timestamp": int(time.time() * 1000)}, ensure_ascii=False) + "\n")


_DBG_SAMPLE = {}
_DBG_LIVE = {}
_DBG_SEEN = {}
_DBG_HEAD = {-1002053584336: 19665}
# endregion


def bot_identity(token):
    request = urllib.request.Request(
        "https://api.telegram.org/bot{}/getMe".format(token)
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit("Токен бота отклонён, HTTP {}".format(error.code))
    if not payload.get("ok"):
        raise SystemExit("Токен бота отклонён")
    return payload["result"]["username"]


def message_text(message):
    if message.action or message.media and not isinstance(message.media, MessageMediaWebPage):
        return None
    text = (message.raw_text or "").strip()
    return text or None


async def ensure_joined(client, entity, username, quiet, may_join):
    # region agent log
    _dbg("A", "main.py:ensure_joined", "before join", {"chat": username, "left": getattr(entity, "left", None), "quiet": quiet, "may_join": may_join, "runId": "post-fix"})
    # endregion
    if getattr(entity, "left", True) is False:
        if not quiet:
            log.info("Уже состоит в @%s", username)
        return "ok"
    if not may_join:
        return "requested"
    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        if not quiet:
            log.info("Уже состоит в @%s", username)
        return "ok"
    except InviteRequestSentError:
        if not quiet:
            log.info("Заявка в @%s отправлена, ждём одобрения администратора", username)
        return "requested"
    except FloodWaitError:
        if not quiet:
            log.info("Вход в @%s отложен, Telegram просит подождать", username)
        return "pending"
    except Exception:
        log.exception("Не удалось войти в @%s", username)
        return "fail"
    if not quiet:
        log.info("Вступил в @%s", username)
    return "ok"


async def attach_chat(client, allowed, username, topic_ids, quiet, may_join=True):
    try:
        entity = await client.get_entity(username)
    except Exception:
        if not quiet:
            log.exception("Чат @%s не найден", username)
        return "fail"
    status = await ensure_joined(client, entity, username, quiet, may_join)
    if status != "ok":
        return status
    entity = await client.get_entity(username)
    peer_id = utils.get_peer_id(entity)
    allowed[peer_id] = set(topic_ids)
    if quiet:
        log.info("Заявку в @%s приняли, темы подключены", username)
        return "ok"
    forum = bool(getattr(entity, "forum", False))
    log.info("@%s id=%s forum=%s topics=%s", username, peer_id, forum, topic_ids)
    for topic_id in topic_ids:
        try:
            found = await client.get_messages(entity, limit=1, reply_to=topic_id)
        except Exception:
            log.exception("Тема %s в @%s недоступна", topic_id, username)
            continue
        # region agent log
        try:
            sample = await client.get_messages(entity, limit=40, reply_to=topic_id)
            _dbg("B", "main.py:attach_chat", "topic sample", {"chat": username, "topic": topic_id, "n": len(sample), "in_topic_false": [m.id for m in sample if not in_topic(m.id, m.reply_to, set(topic_ids))], "with_text": sum(1 for m in sample if message_text(m)), "keyword_hits": sum(1 for m in sample if message_text(m) and matching_keyword(message_text(m))), "caption_hits": sum(1 for m in sample if not message_text(m) and m.media and matching_keyword(m.raw_text or "")), "service": sum(1 for m in sample if m.action)})
            hit = next((m for m in sample if message_text(m) and matching_keyword(message_text(m))), None)
            if hit is not None and "msg" not in _DBG_SAMPLE:
                _DBG_SAMPLE.update({"chat": username, "msg": hit})
        except Exception as error:
            _dbg("B", "main.py:attach_chat", "topic sample failed", {"chat": username, "topic": topic_id, "error": type(error).__name__})
        # endregion
        if found:
            log.info(
                "Тема %s в @%s читается, последнее сообщение %s",
                topic_id,
                username,
                found[0].id,
            )
        else:
            log.warning("Тема %s в @%s пустая или закрыта", topic_id, username)
    return "ok"


async def watch_map(client):
    allowed = {}
    pending = []
    for username, topic_ids in TOPICS.items():
        status = await attach_chat(client, allowed, username, topic_ids, quiet=False)
        if status in ("pending", "requested"):
            pending.append((username, topic_ids, status == "requested"))
    if not allowed and not pending:
        raise SystemExit("Нет ни одного доступного чата")
    return allowed, pending


async def retry_pending(client, allowed, pending):
    while pending:
        await asyncio.sleep(180)
        still_pending = []
        for username, topic_ids, requested in pending:
            status = await attach_chat(
                client,
                allowed,
                username,
                topic_ids,
                quiet=True,
                may_join=not requested,
            )
            if status in ("pending", "requested"):
                still_pending.append((username, topic_ids, requested or status == "requested"))
            elif status != "ok":
                log.error("Чат @%s пропущен", username)
        pending[:] = still_pending


async def deliver(client, bot, event):
    message = event.message
    try:
        await client.forward_messages(bot, message)
        return "forward"
    except FloodWaitError as error:
        log.warning("Flood wait %s с", error.seconds)
        await asyncio.sleep(error.seconds)
        try:
            await client.forward_messages(bot, message)
            return "forward"
        except Exception:
            log.exception("Оригинал не переслался после ожидания")
    except Exception:
        log.exception("Оригинал не переслался, отправляю текст")

    chat = await event.get_chat()
    username = getattr(chat, "username", None)
    link = "https://t.me/{}/{}".format(username, message.id) if username else ""
    body = message.raw_text or ""
    if link:
        body = "{}\n\n{}".format(body, link)
    await client.send_message(bot, body)
    return "copy"


def build_handler(client, bot, allowed):
    async def on_message(event):
        topics = allowed.get(event.chat_id)
        # region agent log
        if topics:
            seen = _DBG_LIVE.setdefault(event.chat_id, [0, None])
            seen[0] += 1
            seen[1] = event.message.id
            _DBG_SEEN.setdefault(event.chat_id, set()).add(event.message.id)
            r = event.message.reply_to
            _dbg("BC", "main.py:on_message", "live message in watched chat", {"chat": event.chat_id, "msg": event.message.id, "forum_topic": getattr(r, "forum_topic", None), "top_id": getattr(r, "reply_to_top_id", None), "reply_to_msg_id": getattr(r, "reply_to_msg_id", None), "in_topic": in_topic(event.message.id, r, topics), "has_text": message_text(event.message) is not None, "keyword": matching_keyword(message_text(event.message) or "")})
        # endregion
        if not topics or not in_topic(event.message.id, event.message.reply_to, topics):
            return
        text = message_text(event.message)
        if text is None:
            return
        keyword = matching_keyword(text)
        if keyword is None:
            return
        kind = await deliver(client, bot, event)
        log.info(
            "Совпадение chat=%s msg=%s keyword=%s via=%s",
            event.chat_id,
            event.message.id,
            keyword,
            kind,
        )

    return on_message


async def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = require_settings()
    username = bot_identity(settings["bot_token"])
    client = TelegramClient(
        settings["session_path"],
        settings["api_id"],
        settings["api_hash"],
    )
    bot_client = TelegramClient(
        settings["bot_session_path"],
        settings["api_id"],
        settings["api_hash"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Аккаунт не авторизован. Сначала нужен вход.")
    await bot_client.start(bot_token=settings["bot_token"])
    me = await client.get_me()
    subscribers = SubscriberList(settings["subscribers_path"])
    register_bot(bot_client, subscribers, settings["bot_password"], me.id)
    bot = await client.get_entity(username)
    allowed, pending = await watch_map(client)
    client.add_event_handler(
        build_handler(client, bot, allowed),
        events.NewMessage(incoming=True),
    )
    if pending:
        asyncio.create_task(retry_pending(client, allowed, pending))
    # region agent log
    async def _dbg_poll():
        while True:
            await asyncio.sleep(120)
            for peer_id in list(allowed):
                try:
                    last = await client.get_messages(peer_id, limit=1)
                    _dbg("C", "main.py:_dbg_poll", "chat head vs live events", {"chat": peer_id, "head_id": last[0].id if last else None, "live_count": _DBG_LIVE.get(peer_id, [0, None])[0], "last_live_id": _DBG_LIVE.get(peer_id, [0, None])[1]})
                    head = last[0].id if last else None
                    prev = _DBG_HEAD.get(peer_id)
                    _DBG_HEAD[peer_id] = head
                    missed = [i for i in range(prev + 1, head + 1) if i not in _DBG_SEEN.get(peer_id, set())][:50] if prev and head and head > prev else []
                    if missed:
                        got = await client.get_messages(peer_id, ids=missed)
                        _dbg("F", "main.py:_dbg_poll", "ids not seen live", {"chat": peer_id, "items": [{"id": i, "kind": type(m).__name__ if m else "deleted", "action": type(m.action).__name__ if m and getattr(m, "action", None) else None, "topic": topic_id_from_reply(getattr(m, "reply_to", None)) if m else None, "has_text": bool(m and message_text(m)), "keyword": matching_keyword(message_text(m) or "") if m and message_text(m) else None, "out": bool(m and m.out)} for i, m in zip(missed, got)]})
                except Exception as error:
                    _dbg("C", "main.py:_dbg_poll", "head check failed", {"chat": peer_id, "error": type(error).__name__})

    asyncio.create_task(_dbg_poll())
    # endregion
    log.info(
        "Слушаю %s чатов, бот @%s, подписчиков %s",
        len(allowed),
        username,
        len(subscribers.ids()),
    )
    await asyncio.gather(
        client.run_until_disconnected(),
        bot_client.run_until_disconnected(),
    )


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
