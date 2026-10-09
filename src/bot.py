import logging

from telethon import Button, events, utils

from src.access import subscribe_link, unsubscribe_chat
from src.gate import (
    ASK_PASSWORD,
    ASK_START,
    delivery_target,
    handle_private,
    is_listener_alert,
    is_menu,
    is_start,
)
from src.links import parse_link, peer_id_from_channel, posted_message_id, trailing_telegram_link
from src.trace import trace
from src.menu import (
    ADD_CHAT_TEXT,
    ADD_WORD_TEXT,
    BACK_CHAT_ROWS,
    BACK_WORD_ROWS,
    CHAT_ROWS,
    DELETE_CHAT_INTRO,
    DELETE_WORD_INTRO,
    HOME_ROWS,
    WORD_ROWS,
    chat_menu_line,
    chats_text,
    choice_message,
    hit_note,
    menu_text,
    message_with_note,
    section_text,
    words_text,
)

log = logging.getLogger("kimparser")


def markup(rows):
    return [[Button.inline(text, data) for text, data in row] for row in rows]


def callback_name(data):
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeError:
            return ""
    return str(data or "")


def forward_source(fwd):
    if fwd is None or not getattr(fwd, "from_id", None):
        return None
    msg_id = getattr(fwd, "channel_post", None) or getattr(fwd, "saved_from_msg_id", None)
    if not msg_id:
        return None
    return utils.get_peer_id(fwd.from_id), msg_id


def delivery_source(event, db):
    found = forward_source(event.message.fwd_from)
    if found:
        return found
    link = trailing_telegram_link(event.raw_text or "")
    parsed = parse_link(link) if link else None
    posted = posted_message_id(parsed)
    if parsed is None or not posted:
        return None
    if parsed.internal_id:
        return peer_id_from_channel(parsed.internal_id), posted
    if parsed.username:
        peer = db.peer_by_username(parsed.username)
        if peer:
            return peer, posted
    return None


async def present(event, text, rows, prefer_edit):
    buttons = markup(rows)
    if prefer_edit:
        try:
            await event.edit(text, parse_mode="html", buttons=buttons)
            return
        except Exception:
            log.exception("Не изменил сообщение меню")
    await event.respond(text, parse_mode="html", buttons=buttons)


async def relay_targets(event, targets, subscribers, skip_id, db, peer_id, msg_id, origin=None):
    text = (origin.raw_text if origin is not None else event.raw_text) or ""
    connected = set(subscribers.ids())
    for user_id, keyword, chat_name, chat_link in targets:
        if user_id == skip_id or user_id not in connected:
            if user_id != skip_id:
                # #region agent log
                trace("D", "bot.py:relay_targets", "Пропуск", {"user": user_id, "peer": peer_id, "msg": msg_id})
                # #endregion
            db.finish_delivery(peer_id, msg_id, user_id)
            continue
        note = hit_note(keyword, chat_name, chat_link)
        delivered = await _send_one(event, user_id, text, subscribers, note, origin)
        if delivered:
            # #region agent log
            trace(
                "D",
                "bot.py:relay_targets",
                "Ушло подписчику",
                {"user": user_id, "peer": peer_id, "msg": msg_id, "word": keyword},
            )
            # #endregion
            db.finish_delivery(peer_id, msg_id, user_id)
            try:
                db.record_hit(user_id, keyword)
            except Exception:
                log.exception("Статистика не записалась")
        elif delivered is None:
            db.finish_delivery(peer_id, msg_id, user_id)
        else:
            db.release_delivery(peer_id, msg_id, user_id)


async def _send_one(event, user_id, text, subscribers, note, origin=None):
    try:
        if origin is None:
            await event.forward_to(user_id)
        else:
            await event.client.forward_messages(user_id, origin)
    except Exception as error:
        name = type(error).__name__
        if any(part in name for part in ("Forbidden", "Blocked", "Deactivated")):
            subscribers.discard(user_id)
            log.info("Отписал %s: %s", user_id, name)
            return None
        log.exception("Пересылка подписчику %s не прошла", user_id)
    else:
        await _send_note(event.client, user_id, note)
        return True
    if not (text or "").strip():
        return False
    body = message_with_note(text, note)
    if not body:
        return False
    try:
        await event.client.send_message(user_id, body, link_preview=False, parse_mode="html")
    except Exception:
        log.exception("Текст подписчику %s не ушёл", user_id)
        return False
    return True


async def _send_note(client, user_id, note):
    if not note:
        return
    try:
        await client.send_message(user_id, note, link_preview=False, parse_mode="html")
    except Exception:
        log.exception("Подпись к совпадению не ушла %s", user_id)


def register_bot(bot_client, subscribers, password, listener_id, db, listener):
    async def show_home(event, prefer_edit):
        user_id = event.sender_id
        db.prepare_user(user_id)
        db.clear_wizard(user_id)
        chats, words = db.counts(user_id)
        text = menu_text(chats, words, db.top_keywords(user_id))
        await present(event, text, HOME_ROWS, prefer_edit)

    async def show_chats(event, prefer_edit):
        user_id = event.sender_id
        db.prepare_user(user_id)
        db.clear_wizard(user_id)
        labels = [_label(row) for row in db.list_chats(user_id)]
        await present(event, chats_text(labels), CHAT_ROWS, prefer_edit)

    async def show_words(event, prefer_edit):
        user_id = event.sender_id
        db.prepare_user(user_id)
        db.clear_wizard(user_id)
        labels = [row["keyword"] for row in db.list_keywords(user_id)]
        await present(event, words_text(labels), WORD_ROWS, prefer_edit)

    async def on_private(event):
        if not event.is_private:
            return
        if is_listener_alert(
            event.sender_id,
            listener_id,
            bool(event.message.fwd_from),
            event.raw_text,
        ):
            await _deliver_alert(event)
            return
        user_id = event.sender_id
        if subscribers.status(user_id) != "connected":
            await _gate(event)
            return
        if is_menu(event.raw_text) or is_start(event.raw_text):
            db.clear_wizard(user_id)
            if is_menu(event.raw_text):
                try:
                    await show_home(event, False)
                except Exception:
                    log.exception("Меню не отправилось %s", user_id)
                return
        mode, ids = db.wizard(user_id)
        if mode:
            try:
                await _wizard(event, mode, ids)
            except Exception:
                log.exception("Шаг меню не выполнился %s", user_id)
            return
        await _gate(event)

    async def _deliver_alert(event):
        if not event.message.fwd_from:
            found = delivery_target(event.raw_text, db.peer_by_username)
            if found:
                await _deliver_tagged(event, found)
                return
        source = delivery_source(event, db)
        if source is None:
            if event.message.fwd_from:
                return
            log.error("Не понял, откуда пересылка")
            return
        peer_id, msg_id = source
        targets = db.claim_delivery(peer_id, msg_id)
        if not targets:
            log.error("Нет плана доставки peer=%s msg=%s", peer_id, msg_id)
            return
        await relay_targets(event, targets, subscribers, listener_id, db, peer_id, msg_id)

    async def _deliver_tagged(event, tagged):
        peer_id, msg_id = tagged
        targets = db.claim_delivery(peer_id, msg_id)
        # #region agent log
        trace(
            "C",
            "bot.py:_deliver_tagged",
            "Метка принята",
            {"peer": peer_id, "msg": msg_id, "plan": len(targets)},
        )
        # #endregion
        if not targets:
            return
        origin = await event.get_reply_message()
        if origin is None:
            # #region agent log
            trace("C", "bot.py:_deliver_tagged", "Метка без оригинала", {"peer": peer_id, "msg": msg_id})
            # #endregion
            for user_id, _keyword, _chat_name, _chat_link in targets:
                db.release_delivery(peer_id, msg_id, user_id)
            return
        await relay_targets(
            event,
            targets,
            subscribers,
            listener_id,
            db,
            peer_id,
            msg_id,
            origin,
        )

    async def _gate(event):
        previous = subscribers.status(event.sender_id)
        status, reply = handle_private(event.raw_text, previous, password)
        subscribers.apply(event.sender_id, status)
        if previous != "connected" and status == "connected":
            db.prepare_user(event.sender_id)
            log.info("Подключен %s", event.sender_id)
        if reply:
            await event.respond(reply)

    async def _wizard(event, mode, ids):
        user_id = event.sender_id
        if mode == "add_chat":
            await _add_chat(event, user_id)
            return
        if mode == "add_word":
            await _add_word(event, user_id)
            return
        if mode == "del_chat":
            await _delete_by_number(event, user_id, ids, "чата", _drop_chat)
            return
        if mode == "del_word":
            await _delete_by_number(event, user_id, ids, "слова", _drop_word)

    async def _add_chat(event, user_id):
        parsed = parse_link(event.raw_text)
        if parsed is None:
            await event.respond(
                "Не понял ссылку. Пришлите её в виде https://t.me/chat или https://t.me/chat/123."
            )
            return
        if db.same_link(user_id, parsed.link):
            await event.respond("Этот чат уже есть в списке.")
            return
        await event.respond("Вхожу в чат…")
        message = await subscribe_link(listener, db, user_id, event.raw_text)
        if message:
            await event.respond(message)
            return
        await show_chats(event, False)

    async def _add_word(event, user_id):
        message = db.add_keyword(user_id, event.raw_text)
        if message:
            await event.respond(message)
            return
        log.info("Слово добавлено user=%s", user_id)
        await show_words(event, False)

    async def _delete_by_number(event, user_id, ids, noun, drop):
        number, error = choice_message(event.raw_text, len(ids), noun)
        if error:
            await event.respond(error)
            return
        removed = await drop(user_id, ids[number - 1])
        if not removed:
            await event.respond("Этой строки уже нет.")
        if noun == "чата":
            await show_chats(event, False)
        else:
            await show_words(event, False)

    async def _drop_chat(user_id, chat_id):
        return await unsubscribe_chat(listener, db, user_id, chat_id)

    async def _drop_word(user_id, keyword_id):
        removed = db.delete_keyword(user_id, keyword_id)
        if removed:
            log.info("Слово удалено user=%s id=%s", user_id, keyword_id)
        return removed

    async def on_button(event):
        try:
            status = subscribers.status(event.sender_id)
            if status != "connected":
                text = ASK_PASSWORD if status == "awaiting" else ASK_START
                await event.answer(text, alert=True)
                return
            user_id = event.sender_id
            db.prepare_user(user_id)
            name = callback_name(event.data)
            if name == "menu:del_chat" and not db.list_chats(user_id):
                await event.answer("Пока нечего удалять.", alert=True)
                return
            if name == "menu:del_word" and not db.list_keywords(user_id):
                await event.answer("Пока нечего удалять.", alert=True)
                return
            await event.answer()
            if name == "menu:home":
                await show_home(event, True)
            elif name == "menu:chats":
                await show_chats(event, True)
            elif name == "menu:keywords":
                await show_words(event, True)
            elif name == "menu:add_chat":
                db.set_wizard(user_id, "add_chat", [])
                await present(event, ADD_CHAT_TEXT, BACK_CHAT_ROWS, True)
            elif name == "menu:add_word":
                db.set_wizard(user_id, "add_word", [])
                await present(event, ADD_WORD_TEXT, BACK_WORD_ROWS, True)
            elif name == "menu:del_chat":
                rows = db.list_chats(user_id)
                db.set_wizard(user_id, "del_chat", [row["id"] for row in rows])
                labels = [_label(row) for row in rows]
                text = section_text("чаты", "Ваши чаты:", labels, DELETE_CHAT_INTRO)
                await present(event, text, BACK_CHAT_ROWS, True)
            elif name == "menu:del_word":
                rows = db.list_keywords(user_id)
                db.set_wizard(user_id, "del_word", [row["id"] for row in rows])
                labels = [row["keyword"] for row in rows]
                text = section_text("ключ слова", "Ваши ключ слова:", labels, DELETE_WORD_INTRO)
                await present(event, text, BACK_WORD_ROWS, True)
        except Exception:
            log.exception("Кнопка меню не ответила")

    bot_client.add_event_handler(on_private, events.NewMessage(incoming=True))
    bot_client.add_event_handler(on_button, events.CallbackQuery())


def _label(row):
    return chat_menu_line(
        row["title"],
        row["topic_title"],
        row["topic_id"],
        row["status"],
        row["link"],
    )
