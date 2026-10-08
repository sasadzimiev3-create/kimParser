import json
import urllib.error
import urllib.request
from html import escape

from src.targets import KEYWORDS, TOPICS

BUTTONS = (
    ("Чаты", b"menu:chats"),
    ("Ключ слова", b"menu:keywords"),
)
STUB_TEXT = "Пока недоступно"
MEDALS = ("🥇", "🥈", "🥉")


def catalog_counts():
    return len(TOPICS), len(KEYWORDS)


def menu_text(chat_count, word_count, top):
    lines = [
        "<b>⚙️ Меню:</b>",
        "💬Чатов: {}".format(chat_count),
        "🔑 слов: {}".format(word_count),
        "",
        "<u>📊Статистика за неделю:</u>",
    ]
    rows = list(top)[: len(MEDALS)]
    if not rows:
        lines.append("Пока нет совпадений")
    else:
        for medal, row in zip(MEDALS, rows):
            keyword, count = row
            lines.append("{} {} - {}".format(medal, escape(keyword), count))
    return "\n".join(lines)


def install_menu_button(token):
    steps = (
        (
            "setMyCommands",
            {"commands": [{"command": "menu", "description": "Меню"}]},
        ),
        (
            "setChatMenuButton",
            {"menu_button": {"type": "commands"}},
        ),
    )
    problems = []
    for method, payload in steps:
        try:
            _call(token, method, payload)
        except RuntimeError as error:
            problems.append(str(error))
    if problems:
        raise RuntimeError("; ".join(problems))


def _call(token, method, payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        "https://api.telegram.org/bot{}/{}".format(token, method),
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError("{} HTTP {}".format(method, error.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise RuntimeError("{} недоступен".format(method)) from None
    if not data.get("ok"):
        description = data.get("description", "ошибка")
        raise RuntimeError("{}: {}".format(method, description))
