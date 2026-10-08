import asyncio
import json
import logging
import urllib.error
import urllib.request

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaWebPage

from src.access import refresh_access
from src.bot import register_bot
from src.db import Database
from src.gate import SubscriberList, delivery_tag_text
from src.links import private_message_link
from src.match import matched_chat, recipients
from src.menu import chat_label, install_menu_button
from src.settings import require_settings

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


async def mark_forward(client, bot, sent, peer_id, msg_id):
    message = sent[0] if isinstance(sent, (list, tuple)) else sent
    reply_to = getattr(message, "id", None)
    await client.send_message(bot, delivery_tag_text(peer_id, msg_id), reply_to=reply_to)


async def deliver(client, bot, event):
    message = event.message
    try:
        sent = await client.forward_messages(bot, message)
        await mark_forward(client, bot, sent, event.chat_id, message.id)
        return "forward"
    except Exception as error:
        name = type(error).__name__
        if name == "FloodWaitError":
            seconds = getattr(error, "seconds", 1)
            log.warning("Flood wait %s с", seconds)
            await asyncio.sleep(seconds)
            try:
                sent = await client.forward_messages(bot, message)
                await mark_forward(client, bot, sent, event.chat_id, message.id)
                return "forward"
            except Exception:
                log.exception("Оригинал не переслался после ожидания")
        else:
            log.exception("Оригинал не переслался, отправляю текст")

    chat = await event.get_chat()
    username = getattr(chat, "username", None)
    if username:
        link = "https://t.me/{}/{}".format(username, message.id)
    else:
        link = private_message_link(event.chat_id, message.id)
    body = message.raw_text or ""
    if link:
        body = "{}\n\n{}".format(body, link)
    await client.send_message(bot, body)
    return "copy"


def build_handler(client, bot, db):
    async def on_message(event):
        try:
            await _handle(event)
        except Exception:
            log.exception("Сообщение не обработалось")

    async def _handle(event):
        rows = db.matching_rows(event.chat_id)
        if not rows:
            return
        text = message_text(event.message)
        if text is None:
            return
        found = recipients(text, rows, event.message.id, event.message.reply_to)
        if not found:
            return
        planned = []
        for user_id, keyword in found:
            chat = matched_chat(rows, user_id, event.message.id, event.message.reply_to)
            name = ""
            link = ""
            if chat:
                name = chat_label(
                    chat.get("title"),
                    chat.get("topic_title"),
                    chat.get("topic_id"),
                    chat.get("status"),
                )
                link = chat.get("link") or ""
            planned.append((user_id, keyword, name, link))
        db.plan_delivery(event.chat_id, event.message.id, planned)
        try:
            kind = await deliver(client, bot, event)
        except Exception:
            log.exception("Доставка боту не удалась")
            return
        log.info(
            "Совпадение chat=%s msg=%s users=%s keywords=%s via=%s",
            event.chat_id,
            event.message.id,
            len(found),
            ",".join(sorted({keyword for _, keyword in found})),
            kind,
        )

    return on_message


async def retry_access(client, db):
    while True:
        await asyncio.sleep(7200)
        try:
            await refresh_access(client, db, pending_only=True)
        except Exception:
            log.exception("Повтор входа в чаты не удался")


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
    db = Database(settings["db_path"])
    for user_id in subscribers.ids():
        db.prepare_user(user_id)
    db.import_legacy_file(settings["stats_path"])
    register_bot(bot_client, subscribers, settings["bot_password"], me.id, db, client)
    try:
        install_menu_button(settings["bot_token"])
        log.info("Кнопка меню включена")
    except RuntimeError as error:
        log.error("Кнопка меню не включилась: %s", error)
    except Exception:
        log.error("Кнопка меню не включилась")
    bot = await client.get_entity(username)
    try:
        await refresh_access(client, db)
    except Exception:
        log.exception("Чаты не обновились")
    client.add_event_handler(
        build_handler(client, bot, db),
        events.NewMessage(incoming=True),
    )
    asyncio.create_task(retry_access(client, db))
    if not db.active_peer_count():
        log.warning("Нет подключённых чатов, меню бота работает")
    log.info(
        "Слушаю %s чатов, бот @%s, подписчиков %s",
        db.active_peer_count(),
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
