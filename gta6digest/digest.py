"""Сборка дайджеста и мгновенных уведомлений (HTML для Telegram + текст для консоли)."""
from __future__ import annotations

import html
import re
import sqlite3
from datetime import datetime
from typing import Iterable, List

from .classifier import CATEGORIES, STATUSES


def _story_line(s: sqlite3.Row) -> str:
    title = html.escape(s["title"])
    if s["spoiler"]:
        title = f"<tg-spoiler>{title}</tg-spoiler>"
        prefix = "⚠️ спойлер: "
    else:
        prefix = ""
    status = STATUSES.get(s["status"], "")
    extra = []
    if status:
        extra.append(status)
    if s["mentions"] > 1:
        extra.append(f"×{s['mentions']}")
    tail = f" <i>({', '.join(extra)})</i>" if extra else ""
    return f"• {prefix}<a href=\"{html.escape(s['best_url'], quote=True)}\">{title}</a>{tail}"


def build_digest(stories: Iterable[sqlite3.Row], max_per_category: int,
                 show_memes: bool, header: str) -> str:
    by_cat: dict = {}
    for s in stories:
        by_cat.setdefault(s["category"], []).append(s)

    parts: List[str] = [f"<b>{html.escape(header)}</b>"]
    total = 0
    for key, label in CATEGORIES.items():
        if key == "memes" and not show_memes:
            continue
        items = by_cat.get(key, [])
        if not items:
            continue
        shown = items[:max_per_category]
        total += len(shown)
        lines = [f"\n<b>{label}</b>"] + [_story_line(s) for s in shown]
        if len(items) > len(shown):
            lines.append(f"<i>…и ещё {len(items) - len(shown)}</i>")
        parts.append("\n".join(lines))
    if total == 0:
        parts.append("\nЗа этот период ничего нового.")
    return "\n".join(parts)


def build_alert(s: sqlite3.Row) -> str:
    head = "🚨 <b>Слух подтвердился!</b>" if s["status"] == "confirmed" \
        else "🚨 <b>Официальная новость</b>"
    return f"{head}\n{_story_line(s)}"


def html_to_console(text: str) -> str:
    text = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"\2\n    \1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def digest_header(now: datetime) -> str:
    return f"GTA 6 — дайджест за {now.strftime('%d.%m.%Y')}"
