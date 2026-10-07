import logging

from telethon import events

from src.gate import handle_private, is_listener_alert

log = logging.getLogger("kimparser")

# region agent log
def _dbg(hyp, loc, msg, data):
    import json, time
    with open("/var/log/kimparser-debug-820a6e.log", "a") as f:
        f.write(json.dumps({"sessionId": "820a6e", "runId": "pre-fix", "hypothesisId": hyp, "location": loc, "message": msg, "data": data, "timestamp": int(time.time() * 1000)}, ensure_ascii=False) + "\n")
# endregion


async def relay(event, subscribers, skip_id):
    text = event.raw_text or ""
    for chat_id in subscribers.ids():
        if chat_id == skip_id:
            continue
        try:
            await event.forward_to(chat_id)
            # region agent log
            _dbg("E", "bot.py:relay", "forwarded to subscriber", {"to": chat_id})
            # endregion
            continue
        except Exception as error:
            name = type(error).__name__
            # region agent log
            _dbg("E", "bot.py:relay", "forward to subscriber failed", {"to": chat_id, "error": name})
            # endregion
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


def register_bot(bot_client, subscribers, password, listener_id):
    async def on_private(event):
        if not event.is_private:
            return
        # region agent log
        _dbg("D", "bot.py:on_private", "bot got private message", {"sender": event.sender_id, "listener": listener_id, "forwarded": bool(event.message.fwd_from), "is_alert": is_listener_alert(event.sender_id, listener_id, bool(event.message.fwd_from), event.raw_text), "is_start": (event.raw_text or "").strip().startswith("/start"), "status_before": subscribers.status(event.sender_id), "subscribers": len(subscribers.ids())})
        # endregion
        if is_listener_alert(
            event.sender_id,
            listener_id,
            bool(event.message.fwd_from),
            event.raw_text,
        ):
            await relay(event, subscribers, listener_id)
            return
        previous = subscribers.status(event.sender_id)
        status, reply = handle_private(event.raw_text, previous, password)
        subscribers.apply(event.sender_id, status)
        if previous != "connected" and status == "connected":
            log.info("Подключен %s", event.sender_id)
        if reply:
            await event.respond(reply)

    bot_client.add_event_handler(on_private, events.NewMessage(incoming=True))
