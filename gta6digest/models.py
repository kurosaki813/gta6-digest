"""Общие структуры данных проекта."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    """Один пост/статья из любого источника.

    ВАЖНО (обещание в заявке Reddit): здесь НЕТ поля с автором.
    Никнеймы мы не храним и не передаём дальше.
    """

    source: str                 # "reddit", "news:Eurogamer" и т.п.
    external_id: str            # ID поста в источнике (для Reddit: t3_xxxx)
    title: str
    url: str                    # ссылка на сам пост/статью
    published: datetime         # всегда в UTC (timezone-aware)
    text: str = ""
    link_url: Optional[str] = None   # внешняя ссылка из поста (если есть)
    score: Optional[int] = None      # рейтинг (появится с Reddit API)
    num_comments: Optional[int] = None
    flair: Optional[str] = None      # флейр поста (появится с Reddit API)


@dataclass
class Classification:
    category: str   # ключ темы, см. classifier.CATEGORIES
    status: str     # ключ статуса, см. classifier.STATUSES
    spoiler: bool
