from __future__ import annotations

import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

from app.infrastructure.config import get_settings


def telegram_call(token: str, method: str, **params: str) -> dict:
    query = urlencode(params)
    url = f"https://api.telegram.org/bot{token}/{method}"
    if query:
        url = f"{url}?{query}"
    with urlopen(url) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error for {method}: {payload}")
    return payload["result"]


def parse_chat_ids(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty.")

    chat_ids = parse_chat_ids(settings.telegram_manager_chat_ids)
    if not chat_ids:
        raise SystemExit("TELEGRAM_MANAGER_CHAT_IDS is empty.")

    me = telegram_call(settings.telegram_bot_token, "getMe")
    bot_id = str(me["id"])
    bot_username = me.get("username", "")
    print(f"Bot: @{bot_username} (id={bot_id})")

    overall_ok = True
    for chat_id in chat_ids:
        try:
            chat = telegram_call(settings.telegram_bot_token, "getChat", chat_id=chat_id)
            member = telegram_call(
                settings.telegram_bot_token,
                "getChatMember",
                chat_id=chat_id,
                user_id=bot_id,
            )
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            print(f"[ERROR] chat_id={chat_id}: {exc}")
            continue

        chat_type = chat.get("type", "unknown")
        title = chat.get("title") or chat.get("username") or chat_id
        status = member.get("status", "unknown")
        can_post = member.get("can_post_messages")

        print(f"[OK] {title} ({chat_type}) -> bot status: {status}")

        if chat_type == "channel":
            is_admin = status in {"administrator", "creator"}
            if not is_admin:
                overall_ok = False
                print(f"[WARN] {chat_id}: bot is not channel admin.")
            elif can_post is False:
                overall_ok = False
                print(f"[WARN] {chat_id}: bot admin without post permission.")

    if not overall_ok:
        raise SystemExit(1)

    print("Telegram setup check passed.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error: {exc}", file=sys.stderr)
        raise SystemExit(1)
