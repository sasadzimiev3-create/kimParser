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

from src.match import in_topic, matching_keyword
from src.settings import require_settings
from src.targets import TOPICS

log = logging.getLogger("kimparser")


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


async def ensure_joined(client, entity, username, quiet):
    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        if not quiet:
            log.info("Уже состоит в @%s", username)
        return "ok"
    except InviteRequestSentError:
        if not quiet:
            log.info("Заявка в @%s отправлена, ждём одобрения администратора", username)
        return "pending"
    except Exception:
        log.exception("Не удалось войти в @%s", username)
        return "fail"
    if not quiet:
        log.info("Вступил в @%s", username)
    return "ok"


async def attach_chat(client, allowed, username, topic_ids, quiet):
    try:
        entity = await client.get_entity(username)
    except Exception:
        if not quiet:
            log.exception("Чат @%s не найден", username)
        return "fail"
    status = await ensure_joined(client, entity, username, quiet)
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
        if status == "pending":
            pending.append((username, topic_ids))
    if not allowed and not pending:
        raise SystemExit("Нет ни одного доступного чата")
    return allowed, pending


async def retry_pending(client, allowed, pending):
    while pending:
        await asyncio.sleep(180)
        still_pending = []
        for username, topic_ids in pending:
            status = await attach_chat(client, allowed, username, topic_ids, quiet=True)
            if status == "pending":
                still_pending.append((username, topic_ids))
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
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Аккаунт не авторизован. Сначала нужен вход.")
    bot = await client.get_entity(username)
    allowed, pending = await watch_map(client)
    client.add_event_handler(
        build_handler(client, bot, allowed),
        events.NewMessage(incoming=True),
    )
    if pending:
        asyncio.create_task(retry_pending(client, allowed, pending))
    log.info("Слушаю %s чатов, бот @%s", len(allowed), username)
    await client.run_until_disconnected()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
