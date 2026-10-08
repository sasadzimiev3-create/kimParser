import asyncio
import logging

from telethon import utils
from telethon.errors import (
    ChannelPrivateError,
    ChannelsTooMuchError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    InviteRequestSentError,
    UserAlreadyParticipantError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    GetForumTopicsByIDRequest,
    ImportChatInviteRequest,
)
from telethon.tl.types import Channel, Chat, ChatInviteAlready, User

from src.links import parse_link, peer_id_from_channel

log = logging.getLogger("kimparser")

_FULL = "Аккаунт уже вступил в слишком много чатов."
_FAIL = "Не получилось войти в чат."
_CLOSED = "Чат закрыт, нужна ссылка-приглашение."
_MISSING = "Не нашёл такой чат."
_NOT_CHAT = "Это не чат."
_PERSON = "Это профиль человека, а не чат."
_NEED_INVITE = "Аккаунт не состоит в этом чате. Нужна публичная ссылка или приглашение."
_BAD_INVITE = "Ссылка-приглашение не работает."
_OLD_INVITE = "Ссылка-приглашение устарела."
_NO_TOPIC = "Не нашёл такую тему в этом чате."
_BAD_LINK = "Не понял ссылку. Пришлите её в виде https://t.me/chat или https://t.me/chat/123."


def _blank(**extra):
    data = {
        "ok": False,
        "status": "failed",
        "message": None,
        "peer_id": None,
        "username": None,
        "title": None,
        "topic_id": None,
        "topic_title": None,
        "invite_hash": None,
        "entity": None,
        "forum": False,
    }
    data.update(extra)
    return data


async def subscribe_link(client, db, user_id, text):
    parsed = parse_link(text)
    if parsed is None:
        return _BAD_LINK
    if db.same_link(user_id, parsed.link):
        return "Этот чат уже есть в списке."
    try:
        outcome = await open_parsed(client, parsed, may_join=True, wait_limit=45, strict_topic=True)
    except Exception:
        log.exception("Вход по ссылке не удался")
        return _FAIL
    if not outcome["ok"]:
        if outcome["peer_id"] and not db.peer_in_use(outcome["peer_id"]):
            await leave_peer(client, outcome["peer_id"])
        return outcome["message"] or _FAIL
    if outcome["peer_id"] is not None and db.same_chat(user_id, outcome["peer_id"], outcome["topic_id"]):
        return "Этот чат уже есть в списке."
    if outcome["invite_hash"] and db.same_invite(user_id, outcome["invite_hash"]):
        return "Этот чат уже есть в списке."
    db.add_chat(
        user_id,
        link=parsed.link,
        title=outcome["title"] or parsed.link,
        status=outcome["status"],
        username=outcome["username"],
        peer_id=outcome["peer_id"],
        topic_id=outcome["topic_id"],
        topic_title=outcome["topic_title"],
        invite_hash=outcome["invite_hash"],
    )
    log.info(
        "Чат добавлен user=%s peer=%s topic=%s status=%s",
        user_id,
        outcome["peer_id"],
        outcome["topic_id"],
        outcome["status"],
    )
    return None


async def unsubscribe_chat(client, db, user_id, chat_id):
    row = db.delete_chat(user_id, chat_id)
    if row is None:
        return False
    peer_id = row["peer_id"]
    if peer_id and not db.peer_in_use(peer_id):
        await leave_peer(client, peer_id)
    log.info("Чат удалён user=%s id=%s", user_id, chat_id)
    return True


async def refresh_access(client, db, pending_only=False):
    groups = {}
    order = []
    for row in db.all_chats():
        key = _group_key(row)
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(row)
    for key in order:
        group = groups[key]
        if pending_only and not any(row["status"] in ("pending", "requested") for row in group):
            continue
        try:
            await _refresh_group(client, db, group)
        except Exception:
            log.exception("Чат не обновился")


async def open_parsed(client, parsed, may_join, wait_limit, strict_topic):
    if parsed.kind == "invite":
        return await acquire_invite(client, parsed.invite, may_join, wait_limit)
    if parsed.kind == "private":
        return await acquire_peer(
            client,
            peer_id_from_channel(parsed.internal_id),
            may_join,
            wait_limit,
            parsed.ref_id,
            strict_topic,
        )
    return await acquire_public(
        client,
        parsed.username,
        may_join,
        wait_limit,
        parsed.ref_id,
        strict_topic,
    )


async def acquire_public(client, username, may_join, wait_limit, ref_id=None, strict_topic=False):
    label = "@" + username
    try:
        entity = await client.get_entity(username)
    except FloodWaitError as error:
        if error.seconds <= wait_limit:
            await asyncio.sleep(error.seconds)
            return await acquire_public(client, username, may_join, 0, ref_id, strict_topic)
        log.info("Вход в %s отложен на %s с", label, error.seconds)
        return _blank(ok=True, status="pending", title=label, username=username.lower())
    except (UsernameInvalidError, UsernameNotOccupiedError):
        return _blank(message=_MISSING)
    except ChannelPrivateError:
        return _blank(message=_CLOSED)
    except Exception:
        log.exception("Чат %s не найден", label)
        return _blank(message=_MISSING)
    if isinstance(entity, User):
        return _blank(message=_PERSON)
    if not isinstance(entity, (Channel, Chat)):
        return _blank(message=_NOT_CHAT)
    membership = await ensure_member(client, entity, label, may_join, wait_limit)
    title = getattr(entity, "title", None) or label
    stopped = _from_membership(membership, title, username.lower())
    if stopped is not None:
        if ref_id and getattr(entity, "forum", False):
            stopped["topic_id"] = ref_id
        return stopped
    try:
        entity = await client.get_entity(username)
    except Exception:
        log.exception("Чат %s не перечитался", label)
    return await _describe(client, entity, username, ref_id, strict_topic)


async def acquire_invite(client, invite_hash, may_join, wait_limit):
    try:
        checked = await client(CheckChatInviteRequest(invite_hash))
    except InviteHashExpiredError:
        return _blank(message=_OLD_INVITE, invite_hash=invite_hash)
    except InviteHashInvalidError:
        return _blank(message=_BAD_INVITE, invite_hash=invite_hash)
    except FloodWaitError as error:
        if error.seconds <= wait_limit:
            await asyncio.sleep(error.seconds)
            return await acquire_invite(client, invite_hash, may_join, 0)
        return _blank(ok=True, status="pending", title="Чат", invite_hash=invite_hash)
    except Exception:
        log.exception("Приглашение не прочиталось")
        return _blank(message=_BAD_INVITE, invite_hash=invite_hash)
    if isinstance(checked, ChatInviteAlready):
        return await _describe(
            client,
            checked.chat,
            getattr(checked.chat, "username", None),
            None,
            False,
            invite_hash,
        )
    title = getattr(checked, "title", None) or "Чат"
    if not may_join:
        return _blank(ok=True, status="requested", title=title, invite_hash=invite_hash)
    try:
        updates = await client(ImportChatInviteRequest(invite_hash))
    except InviteRequestSentError:
        log.info("Заявка по приглашению отправлена")
        return _blank(ok=True, status="requested", title=title, invite_hash=invite_hash)
    except UserAlreadyParticipantError:
        return _blank(ok=True, status="pending", title=title, invite_hash=invite_hash)
    except FloodWaitError as error:
        if error.seconds <= wait_limit:
            await asyncio.sleep(error.seconds)
            return await acquire_invite(client, invite_hash, may_join, 0)
        return _blank(ok=True, status="pending", title=title, invite_hash=invite_hash)
    except ChannelsTooMuchError:
        return _blank(message=_FULL, invite_hash=invite_hash)
    except Exception:
        log.exception("Вход по приглашению не удался")
        return _blank(message=_FAIL, invite_hash=invite_hash)
    chats = getattr(updates, "chats", None) or []
    if not chats:
        return _blank(ok=True, status="pending", title=title, invite_hash=invite_hash)
    entity = chats[0]
    return await _describe(client, entity, getattr(entity, "username", None), None, False, invite_hash)


async def acquire_peer(client, peer_id, may_join, wait_limit, ref_id=None, strict_topic=False):
    try:
        entity = await client.get_entity(peer_id)
    except Exception:
        log.exception("Чат %s недоступен", peer_id)
        return _blank(message=_NEED_INVITE)
    if isinstance(entity, User) or not isinstance(entity, (Channel, Chat)):
        return _blank(message=_NOT_CHAT)
    username = getattr(entity, "username", None)
    label = "@{}".format(username) if username else str(peer_id)
    membership = await ensure_member(client, entity, label, may_join, wait_limit)
    title = getattr(entity, "title", None) or label
    stopped = _from_membership(membership, title, username.lower() if username else None)
    if stopped is not None:
        stopped["peer_id"] = peer_id
        if ref_id and getattr(entity, "forum", False):
            stopped["topic_id"] = ref_id
        return stopped
    return await _describe(client, entity, username, ref_id, strict_topic)


async def ensure_member(client, entity, label, may_join, wait_limit):
    if getattr(entity, "left", True) is False:
        return "ok"
    if not may_join:
        return "requested"
    try:
        await client(JoinChannelRequest(entity))
    except UserAlreadyParticipantError:
        return "ok"
    except InviteRequestSentError:
        log.info("Заявка в %s отправлена", label)
        return "requested"
    except FloodWaitError as error:
        if error.seconds <= wait_limit:
            await asyncio.sleep(error.seconds)
            return await ensure_member(client, entity, label, may_join, 0)
        log.info("Вход в %s отложен на %s с", label, error.seconds)
        return "pending"
    except ChannelsTooMuchError:
        return "full"
    except Exception:
        log.exception("Не удалось войти в %s", label)
        return "fail"
    log.info("Вступил в %s", label)
    return "ok"


async def read_topic(client, entity, topic_id):
    try:
        result = await client(GetForumTopicsByIDRequest(peer=entity, topics=[topic_id]))
    except Exception:
        log.exception("Тема %s не прочиталась", topic_id)
        return ""
    topics = getattr(result, "topics", None) or []
    if not topics:
        return None
    return getattr(topics[0], "title", None) or ""


async def leave_peer(client, peer_id):
    try:
        entity = await client.get_entity(peer_id)
        await client(LeaveChannelRequest(entity))
        log.info("Вышел из чата %s", peer_id)
    except Exception:
        log.exception("Не вышел из чата %s", peer_id)


async def _describe(client, entity, username, ref_id, strict_topic, invite_hash=None):
    peer_id = utils.get_peer_id(entity)
    title = getattr(entity, "title", None) or ("@{}".format(username) if username else "Чат")
    stored = getattr(entity, "username", None) or username
    if stored:
        stored = stored.lower()
    forum = bool(getattr(entity, "forum", False))
    topic_id = None
    topic_title = None
    if ref_id and forum:
        topic_name = await read_topic(client, entity, ref_id)
        if topic_name is None and strict_topic:
            return _blank(
                message=_NO_TOPIC,
                title=title,
                username=stored,
                peer_id=peer_id,
                forum=forum,
                entity=entity,
            )
        if topic_name is not None:
            topic_id = ref_id
            topic_title = topic_name or None
    return _blank(
        ok=True,
        status="active",
        peer_id=peer_id,
        username=stored,
        title=title,
        topic_id=topic_id,
        topic_title=topic_title,
        invite_hash=invite_hash,
        entity=entity,
        forum=forum,
    )


def _from_membership(membership, title, username):
    if membership == "ok":
        return None
    if membership in ("requested", "pending"):
        return _blank(ok=True, status=membership, title=title, username=username)
    message = _FULL if membership == "full" else _FAIL
    return _blank(message=message, title=title, username=username)


def _group_key(row):
    if row["username"]:
        return ("user", row["username"].lower())
    if row["invite_hash"]:
        return ("invite", row["invite_hash"])
    if row["peer_id"]:
        return ("peer", row["peer_id"])
    return ("id", row["id"])


async def _refresh_group(client, db, group):
    sample = group[0]
    may_join = not any(row["status"] == "requested" for row in group)
    if sample["username"]:
        base = await acquire_public(client, sample["username"], may_join, 0)
    elif sample["invite_hash"]:
        base = await acquire_invite(client, sample["invite_hash"], may_join, 0)
    elif sample["peer_id"]:
        base = await acquire_peer(client, sample["peer_id"], may_join, 0)
    else:
        return
    if base["status"] != "active":
        for row in group:
            if row["status"] == "active" and row["peer_id"]:
                continue
            fields = {"status": base["status"] if base["ok"] else "failed"}
            if base["title"]:
                fields["title"] = base["title"]
            if base["username"]:
                fields["username"] = base["username"]
            if base["peer_id"]:
                fields["peer_id"] = base["peer_id"]
            if base["invite_hash"]:
                fields["invite_hash"] = base["invite_hash"]
            db.update_chat(row["id"], **fields)
        return
    for row in group:
        await _apply_row(client, db, row, base)


async def _apply_row(client, db, row, base):
    topic_id = row["topic_id"]
    topic_title = row["topic_title"]
    if topic_id and base["entity"] is not None:
        title = await read_topic(client, base["entity"], topic_id)
        if title:
            topic_title = title
        elif title is None:
            log.warning("Тема %s не найдена, оставляю id", topic_id)
    db.update_chat(
        row["id"],
        status="active",
        peer_id=base["peer_id"],
        username=base["username"] or row["username"],
        title=base["title"] or row["title"],
        topic_title=topic_title,
        invite_hash=base["invite_hash"] or row["invite_hash"],
    )
    log.info(
        "Чат подключён peer=%s topic=%s title=%s",
        base["peer_id"],
        topic_id,
        base["title"],
    )
