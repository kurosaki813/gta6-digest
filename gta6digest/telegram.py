"""Sending to Telegram via the Bot API (no third-party libraries).

The digest goes to a single private chat (your own), it is not published.
"""
from __future__ import annotations

import time
from typing import List

from . import http

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4000  # Telegram allows 4096 characters per message; keep a margin


def split_message(text: str, limit: int = LIMIT) -> List[str]:
    """Split a long digest on line boundaries so HTML tags are never cut in half."""
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit and current:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str) -> None:
        for chunk in split_message(text):
            http.post_json(API.format(token=self.token, method="sendMessage"), {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            time.sleep(0.5)  # stay well under Telegram's limits

    @staticmethod
    def find_chat_ids(token: str) -> List[str]:
        """List chats that recently messaged the bot — used to find your chat_id."""
        data = http.get_json(API.format(token=token, method="getUpdates"))
        found = []
        for upd in data.get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat", {})
            if chat:
                label = chat.get("username") or chat.get("title") or chat.get("first_name", "")
                found.append(f"{chat['id']}  ({label})")
        return list(dict.fromkeys(found))
