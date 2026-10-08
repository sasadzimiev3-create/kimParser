import json
import re
from pathlib import Path


CONNECTED = "Вы подключены!"
ASK_PASSWORD = "Введите пароль"
BAD_PASSWORD = "Неверный пароль"
ASK_START = "Нажмите /start"


def command_name(text):
    raw = (text or "").strip()
    if not raw:
        return ""
    first = raw.split(maxsplit=1)[0]
    return first.split("@", 1)[0].lower()


def is_start(text):
    return command_name(text) == "/start"


def is_menu(text):
    return command_name(text) == "/menu"


_TAG = re.compile(r"^kp:(-?\d+):(\d+)$")


def delivery_tag(text):
    match = _TAG.match((text or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def delivery_tag_text(peer_id, msg_id):
    return "kp:{}:{}".format(peer_id, msg_id)


def is_listener_alert(sender_id, listener_id, forwarded, text):
    if sender_id != listener_id:
        return False
    if forwarded:
        return True
    if delivery_tag(text):
        return True
    return "\n\nhttps://t.me/" in (text or "")


def handle_private(text, status, password):
    raw = (text or "").strip()
    if is_start(raw):
        if status == "connected":
            return "connected", CONNECTED
        return "awaiting", ASK_PASSWORD
    if is_menu(raw) and status != "connected":
        if status == "awaiting":
            return "awaiting", ASK_PASSWORD
        return None, ASK_START
    if status == "connected":
        return "connected", None
    if status == "awaiting" and raw == password:
        return "connected", CONNECTED
    if status == "awaiting":
        return "awaiting", BAD_PASSWORD
    return None, ASK_START


class SubscriberList:
    def __init__(self, path):
        self.path = Path(path)
        self.connected = set()
        self.awaiting = set()
        if self.path.exists():
            self.connected = {int(item) for item in json.loads(self.path.read_text())}

    def status(self, chat_id):
        if chat_id in self.connected:
            return "connected"
        if chat_id in self.awaiting:
            return "awaiting"
        return None

    def ids(self):
        return list(self.connected)

    def apply(self, chat_id, status):
        if status == "connected":
            self.awaiting.discard(chat_id)
            if chat_id not in self.connected:
                self.connected.add(chat_id)
                self._save()
            return
        if status == "awaiting":
            self.awaiting.add(chat_id)
            return
        self.awaiting.discard(chat_id)

    def discard(self, chat_id):
        self.awaiting.discard(chat_id)
        if chat_id in self.connected:
            self.connected.remove(chat_id)
            self._save()

    def _save(self):
        self.path.write_text(json.dumps(sorted(self.connected)))
        self.path.chmod(0o600)
