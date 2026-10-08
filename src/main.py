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
from src.debug_session import agent_log
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
    # #region agent log
    agent_log(
        "A",
        "main.py:mark_forward",
        "sent delivery tag",
        {"peer": peer_id, "msg": msg_id, "reply": reply_to},
        run_id="post-fix",
    )
    # #endregion


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
        reply = event.message.reply_to
        text = message_text(event.message)
        if text is None:
            raw = (event.message.raw_text or "").strip()
            # #region agent log
            if raw:
                agent_log(
                    "C",
                    "main.py:_handle",
                    "skipped non-text",
                    {
                        "chat": event.chat_id,
                        "msg": event.message.id,
                        "media": type(event.message.media).__name__ if event.message.media else "",
                        "raw_len": len(raw),
                    },
                )
            # #endregion
            return
        found = recipients(text, rows, event.message.id, reply)
        if not found:
            # #region agent log
            agent_log(
                "B",
                "main.py:_handle",
                "no recipients",
                {
                    "chat": event.chat_id,
                    "msg": event.message.id,
                    "forum": bool(getattr(reply, "forum_topic", False)) if reply else False,
                    "top": getattr(reply, "reply_to_top_id", None) if reply else None,
                    "reply_to": getattr(reply, "reply_to_msg_id", None) if reply else None,
                    "rows": len(rows),
                    "text_len": len(text),
                },
            )
            # #endregion
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
        # #region agent log
        agent_log(
            "E",
            "main.py:_handle",
            "planned",
            {
                "chat": event.chat_id,
                "msg": event.message.id,
                "keywords": sorted({keyword for _, keyword in found}),
                "users": len(found),
            },
        )
        # #endregion
        try:
            kind = await deliver(client, bot, event)
        except Exception:
            log.exception("Доставка боту не удалась")
            # #region agent log
            agent_log("E", "main.py:_handle", "deliver failed", {"chat": event.chat_id, "msg": event.message.id})
            # #endregion
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


async def debug_probe(client, bot, db):
    await asyncio.sleep(3)
    topics = (
        (-1001391677315, 44320),
        (-1001391677315, 44329),
        (-1002053584336, 196),
        (-1002053584336, 131),
        (-1001138391813, 264492),
    )
    for peer, topic in topics:
        rows = db.matching_rows(peer)
        try:
            messages = await client.get_messages(peer, limit=5, reply_to=topic)
        except Exception as error:
            # #region agent log
            agent_log(
                "D",
                "main.py:debug_probe",
                "topic read failed",
                {"peer": peer, "topic": topic, "error": type(error).__name__},
            )
            # #endregion
            continue
        for msg in messages or []:
            reply = msg.reply_to
            visible = message_text(msg)
            raw = (msg.raw_text or "").strip()
            found = recipients(raw, rows, msg.id, reply) if raw else []
            age = None
            if msg.date is not None:
                age = int(__import__("time").time() - msg.date.timestamp())
            # #region agent log
            agent_log(
                "B" if visible and not found else ("C" if raw and not visible else "D"),
                "main.py:debug_probe",
                "recent topic message",
                {
                    "peer": peer,
                    "topic": topic,
                    "msg": msg.id,
                    "age_s": age,
                    "media": type(msg.media).__name__ if msg.media else "",
                    "has_text": bool(visible),
                    "raw_len": len(raw),
                    "forum": bool(getattr(reply, "forum_topic", False)) if reply else False,
                    "top": getattr(reply, "reply_to_top_id", None) if reply else None,
                    "reply_to": getattr(reply, "reply_to_msg_id", None) if reply else None,
                    "reply_type": type(reply).__name__ if reply else "",
                    "keywords": [item[1] for item in found],
                    "rows": len(rows),
                },
            )
            # #endregion
    try:
        db.plan_delivery(
            -1001391677315,
            243544,
            [(0, "оператор", "JETLAG CHAT - вакансии", "https://t.me/jetlagchat/44320")],
        )
        sample = await client.get_messages(-1001391677315, ids=243544)
        sent = await client.forward_messages(bot, sample)
        # #region agent log
        agent_log("A", "main.py:debug_probe", "forwarded sample to bot", {"msg": 243544})
        # #endregion
        await mark_forward(client, bot, sent, -1001391677315, 243544)
    except Exception as error:
        # #region agent log
        agent_log("A", "main.py:debug_probe", "forward sample failed", {"error": type(error).__name__})
        # #endregion
    # #region agent log
    agent_log("D", "main.py:debug_probe", "probe finished", {})
    # #endregion


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
    asyncio.create_task(debug_probe(client, bot, db))
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
