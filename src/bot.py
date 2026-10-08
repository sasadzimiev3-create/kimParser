import logging

from telethon import Button, events

from src.gate import ASK_PASSWORD, ASK_START, handle_private, is_listener_alert, is_menu
from src.menu import BUTTONS, STUB_TEXT, catalog_counts, menu_text

log = logging.getLogger("kimparser")


async def relay(event, subscribers, skip_id):
    text = event.raw_text or ""
    for chat_id in subscribers.ids():
        if chat_id == skip_id:
            continue
        try:
            await event.forward_to(chat_id)
            continue
        except Exception as error:
            name = type(error).__name__
            if any(part in name for part in ("Forbidden", "Blocked", "Deactivated")):
                subscribers.discard(chat_id)
                log.info("Отписал %s: %s", chat_id, name)
                continue
            log.exception("Пересылка подписчику %s не прошла", chat_id)
        if not text:
            continue
        try:
            await event.client.send_message(chat_id, text)
        except Exception:
            log.exception("Текст подписчику %s не ушёл", chat_id)


def menu_markup():
    return [[Button.inline(text, data) for text, data in BUTTONS]]


def register_bot(bot_client, subscribers, password, listener_id, stats):
    known = {data for _, data in BUTTONS}

    async def on_private(event):
        if not event.is_private:
            return
        if is_listener_alert(
            event.sender_id,
            listener_id,
            bool(event.message.fwd_from),
            event.raw_text,
        ):
            await relay(event, subscribers, listener_id)
            return
        if is_menu(event.raw_text) and subscribers.status(event.sender_id) == "connected":
            chats, words = catalog_counts()
            try:
                await event.respond(
                    menu_text(chats, words, stats.top()),
                    parse_mode="html",
                    buttons=menu_markup(),
                )
            except Exception:
                log.exception("Меню не отправилось %s", event.sender_id)
            return
        previous = subscribers.status(event.sender_id)
        status, reply = handle_private(event.raw_text, previous, password)
        subscribers.apply(event.sender_id, status)
        if previous != "connected" and status == "connected":
            log.info("Подключен %s", event.sender_id)
        if reply:
            await event.respond(reply)

    async def on_button(event):
        try:
            status = subscribers.status(event.sender_id)
            if status != "connected":
                text = ASK_PASSWORD if status == "awaiting" else ASK_START
                await event.answer(text, alert=True)
                return
            if event.data not in known:
                await event.answer()
                return
            await event.answer(STUB_TEXT, alert=True)
        except Exception:
            log.exception("Кнопка меню не ответила")

    bot_client.add_event_handler(on_private, events.NewMessage(incoming=True))
    bot_client.add_event_handler(on_button, events.CallbackQuery())
