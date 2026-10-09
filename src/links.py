import re


class Link(object):
    def __init__(self, kind, link, username=None, ref_id=None, internal_id=None, invite=None):
        self.kind = kind
        self.link = link
        self.username = username
        self.ref_id = ref_id
        self.internal_id = internal_id
        self.invite = invite


_INVITE = re.compile(
    r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_-]+)$",
    re.I,
)
_PRIVATE = re.compile(
    r"^(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)/(\d+)$",
    re.I,
)
_PUBLIC = re.compile(
    r"^(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,31})(?:/(\d+))?$",
    re.I,
)
_AT = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,31})$")
_FIND = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/\S+|(?<![\w])@[A-Za-z][A-Za-z0-9_]{3,31}\b",
    re.I,
)


def peer_id_from_channel(internal_id):
    return int("-100{}".format(internal_id))


def private_message_link(peer_id, message_id):
    text = str(peer_id)
    if not text.startswith("-100"):
        return ""
    return "https://t.me/c/{}/{}".format(text[4:], message_id)


def message_permalink(peer_id, message_id, username=None):
    name = (username or "").strip().lstrip("@").lower()
    if name:
        return "https://t.me/{}/{}".format(name, message_id)
    return private_message_link(peer_id, message_id)


def trailing_telegram_link(text):
    marker = "\n\nhttps://t.me/"
    if marker not in (text or ""):
        return None
    tail = text.rsplit(marker, 1)[1].strip().splitlines()[0].strip()
    if not tail:
        return None
    return "https://t.me/" + tail


def parse_link(text):
    found = _FIND.search(text or "")
    if not found:
        return None
    token = found.group(0).split("?")[0].split("#")[0].rstrip("/")
    token = token.rstrip(".,);]>")
    invite = _INVITE.match(token)
    if invite:
        digest = invite.group(1)
        return Link("invite", "https://t.me/+{}".format(digest), invite=digest)
    private = _PRIVATE.match(token)
    if private:
        internal_id = int(private.group(1))
        ref_id = int(private.group(2))
        return Link(
            "private",
            "https://t.me/c/{}/{}".format(internal_id, ref_id),
            ref_id=ref_id,
            internal_id=internal_id,
        )
    public = _PUBLIC.match(token)
    if public:
        username = public.group(1).lower()
        ref_id = int(public.group(2)) if public.group(2) else None
        link = "https://t.me/" + username
        if ref_id is not None:
            link = "{}/{}".format(link, ref_id)
        return Link("public", link, username=username, ref_id=ref_id)
    mention = _AT.match(token)
    if mention:
        username = mention.group(1).lower()
        return Link("public", "https://t.me/" + username, username=username)
    return None
