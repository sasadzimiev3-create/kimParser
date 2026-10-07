import asyncio
import json
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from src.settings import require_settings

STATE = Path("login_state.json")


async def run():
    settings = require_settings()
    client = TelegramClient(
        settings["session_path"],
        settings["api_id"],
        settings["api_hash"],
    )
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print("AUTHORIZED {} {}".format(me.id, me.username or ""))
        await client.disconnect()
        return

    import os

    code = os.environ.get("LOGIN_CODE", "").strip()
    if not code:
        sent = await client.send_code_request(settings["phone"])
        STATE.write_text(json.dumps({"phone_code_hash": sent.phone_code_hash}))
        STATE.chmod(0o600)
        print("CODE_SENT")
        await client.disconnect()
        return

    state = json.loads(STATE.read_text())
    try:
        await client.sign_in(
            settings["phone"],
            code,
            phone_code_hash=state["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        password = os.environ.get("LOGIN_PASSWORD", "").strip()
        if not password:
            print("NEED_PASSWORD")
            await client.disconnect()
            return
        await client.sign_in(password=password)
    me = await client.get_me()
    print("AUTHORIZED {} {}".format(me.id, me.username or ""))
    await client.disconnect()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
