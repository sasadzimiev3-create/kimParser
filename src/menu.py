import json
import urllib.error
import urllib.request
from html import escape

HOME_ROWS = ((("Чаты", b"menu:chats"), ("Ключ слова", b"menu:keywords")),)
CHAT_ROWS = (
    (("Добавить чат", b"menu:add_chat"), ("Удалить чат", b"menu:del_chat")),
    (("◀️ Назад", b"menu:home"),),
)
WORD_ROWS = (
    (("Добавить слово", b"menu:add_word"), ("Удалить слово", b"menu:del_word")),
    (("◀️ Назад", b"menu:home"),),
)
BACK_CHAT_ROWS = ((("◀️ Назад", b"menu:chats"),),)
BACK_WORD_ROWS = ((("◀️ Назад", b"menu:keywords"),),)
ADD_CHAT_TEXT = "\n".join(
    (
        "<b>⚙️ Меню:</b> → чаты",
        "",
        "Отправьте ссылку на чат.",
        "Для отдельной темы подойдёт ссылка вида https://t.me/chat/123.",
    )
)
ADD_WORD_TEXT = "\n".join(
    (
        "<b>⚙️ Меню:</b> → ключ слова",
        "",
        "Отправьте ключевое слово или фразу.",
    )
)
DELETE_CHAT_INTRO = "Отправьте номер чата, который нужно удалить."
DELETE_WORD_INTRO = "Отправьте номер слова, которое нужно удалить."
MEDALS = ("🥇", "🥈", "🥉")


def menu_text(chat_count, word_count, top):
    lines = [
        "<b>⚙️ Меню:</b>",
        "",
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


def chat_label(title, topic_title, topic_id, status):
    name = title or "Чат"
    if topic_title:
        name = "{} - {}".format(name, topic_title)
    elif topic_id:
        name = "{} - тема {}".format(name, topic_id)
    if status == "requested":
        name = "{} (заявка отправлена)".format(name)
    elif status == "pending":
        name = "{} (подключаю)".format(name)
    elif status == "failed":
        name = "{} (не удалось войти)".format(name)
    return name


def chat_menu_line(title, topic_title, topic_id, status, link):
    label = chat_label(title, topic_title, topic_id, status).replace("—", "-").replace("–", "-")
    url = (link or "").strip()
    if not url or url in label:
        return label
    return "{}\n{}".format(label, url)


def hit_note(keyword, chat_name, chat_link):
    word = (keyword or "").strip() or "—"
    name = (chat_name or "").strip() or "—"
    url = (chat_link or "").strip()
    note = "[ Ключ слово: {}\nЧат: {}]".format(word, name)
    if url:
        return "{}\n{}".format(note, url)
    return note


def message_with_note(text, note):
    body = (text or "").rstrip()
    extra = (note or "").strip()
    if body and extra:
        return "{}\n{}".format(body, extra)
    return body or extra


def section_text(screen, heading, labels, intro=None):
    lines = ["<b>⚙️ Меню:</b> → {}".format(screen), ""]
    if intro:
        lines.append(intro)
        lines.append("")
    lines.append(heading)
    if not labels:
        lines.append("Пока пусто")
    else:
        for index, label in enumerate(labels, 1):
            lines.append("{}. {}".format(index, escape(label)))
    return "\n".join(lines)


def chats_text(labels):
    return section_text("чаты", "Ваши чаты:", labels)


def words_text(labels):
    return section_text("ключ слова", "Ваши ключ слова:", labels)


def choice_message(text, count, noun):
    raw = (text or "").strip()
    if not raw.isdigit():
        return None, "Нужен номер из списка."
    number = int(raw)
    if number < 1 or number > count:
        return None, "Нет {} с таким номером.".format(noun)
    return number, None


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
