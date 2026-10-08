import os
from pathlib import Path


def load_dotenv(path=".env"):
    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def require_settings():
    load_dotenv()
    missing = [
        name
        for name in ("API_ID", "API_HASH", "PHONE", "BOT_TOKEN", "BOT_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit("В окружении нет: " + ", ".join(missing))
    return {
        "api_id": int(os.environ["API_ID"]),
        "api_hash": os.environ["API_HASH"],
        "phone": os.environ["PHONE"],
        "bot_token": os.environ["BOT_TOKEN"],
        "bot_password": os.environ["BOT_PASSWORD"],
        "session_path": os.environ.get("SESSION_PATH", "kimparser.session"),
        "bot_session_path": os.environ.get("BOT_SESSION_PATH", "bot.session"),
        "subscribers_path": os.environ.get("SUBSCRIBERS_PATH", "subscribers.json"),
        "stats_path": os.environ.get("STATS_PATH", "keyword_stats.json"),
        "db_path": os.environ.get("DB_PATH", "kimparser.db"),
    }
