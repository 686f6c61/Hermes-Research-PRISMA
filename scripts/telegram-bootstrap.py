#!/usr/bin/env python3
"""Validate a Telegram bot and discover its private-chat owner safely.

The token is read from the process environment so it never appears in a shell
command or URL copied by the user. Output is deliberately limited to bot and
user identifiers needed by the local setup assistant.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

TOKEN_PATTERN = re.compile(r"^[0-9]+:[A-Za-z0-9_-]{20,}$")


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def telegram_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not TOKEN_PATTERN.fullmatch(token):
        fail("Telegram token is missing or has an invalid format")
    return token


def api_call(method: str, params: dict[str, str] | None = None) -> dict:
    token = telegram_token()
    endpoint = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode("utf-8") if params else None
    request = urllib.request.Request(endpoint, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        fail(f"Telegram rejected {method} (HTTP {exc.code})")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        fail(f"Telegram did not return a valid response for {method}")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        fail(f"Telegram reported that {method} failed")
    return payload


def bot_identity() -> None:
    result = api_call("getMe").get("result", {})
    username = str(result.get("username", "")).strip()
    bot_id = str(result.get("id", "")).strip()
    if not username or not bot_id:
        fail("Telegram returned an incomplete bot identity")
    print(f"@{username} ({bot_id})")


def private_users() -> None:
    updates = api_call("getUpdates", {"timeout": "0", "limit": "100"}).get("result", [])
    candidates: dict[str, tuple[str, str]] = {}
    for update in updates if isinstance(updates, list) else []:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or chat.get("type") != "private" or not isinstance(sender, dict):
            continue
        user_id = str(sender.get("id", "")).strip()
        if not user_id.isdigit():
            continue
        username = str(sender.get("username", "")).strip()
        full_name = " ".join(
            part
            for part in (
                str(sender.get("first_name", "")).strip(),
                str(sender.get("last_name", "")).strip(),
            )
            if part
        )
        candidates[user_id] = (username, full_name)
    for user_id, (username, full_name) in sorted(candidates.items()):
        label = f"@{username}" if username else full_name or "usuario privado"
        print(f"{user_id}\t{label}")


def check_chat(chat_id: str) -> None:
    if not re.fullmatch(r"-?[1-9][0-9]*", chat_id):
        fail("Telegram chat ID must be a non-zero integer")
    api_call("getChat", {"chat_id": chat_id})


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("identity")
    subparsers.add_parser("discover-users")
    check = subparsers.add_parser("check-chat")
    check.add_argument("chat_id")
    args = parser.parse_args()

    if args.command == "identity":
        bot_identity()
    elif args.command == "discover-users":
        private_users()
    else:
        check_chat(args.chat_id)


if __name__ == "__main__":
    main()
