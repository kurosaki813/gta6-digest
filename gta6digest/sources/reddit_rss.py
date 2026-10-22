"""Reddit через RSS (без ключа). Временный источник: Reddit отключает RSS 13.11.2026.

Когда одобрят API, рядом появится reddit_api.py с тем же интерфейсом,
а этот файл можно будет удалить.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from .. import http
from ..feeds import html_to_text, parse_feed
from ..models import Post
from .base import Source

log = logging.getLogger(__name__)

_LINK_RE = re.compile(r'<a href="([^"]+)">\s*\[link\]\s*</a>', re.I)


class RedditRssSource(Source):
    def __init__(self, subreddit: str, user_agent: str, listings: List[str]):
        self.subreddit = subreddit
        self.user_agent = user_agent
        self.listings = listings  # например ["new", "hot"]
        self.name = "reddit"

    def fetch(self) -> List[Post]:
        posts: dict = {}
        for listing in self.listings:
            url = f"https://www.reddit.com/r/{self.subreddit}/{listing}/.rss?limit=100"
            try:
                data = http.get(url, self.user_agent)
            except http.HttpError as e:
                if e.status in (403, 404, 410):
                    log.error("Reddit RSS недоступен (HTTP %s). Возможно, RSS уже отключили — "
                              "пора переходить на API.", e.status)
                raise
            for p in parse_reddit_feed(data):
                posts[p.external_id] = p
        return list(posts.values())


def _strip_author_trailer(content_html: str) -> str:
    """Отрезаем хвост "submitted by /u/ник [link] [comments]".

    ВАЖНО (обещание в заявке): именно здесь из данных выкидывается никнейм автора.
    """
    idx = content_html.find("submitted by")
    if idx == -1:
        idx = content_html.find("&#32; submitted")
    return content_html[:idx] if idx != -1 else content_html


def _external_link(content_html: str) -> Optional[str]:
    m = _LINK_RE.search(content_html)
    if not m:
        return None
    url = m.group(1)
    # У текстовых постов [link] ведёт на сам Reddit — это не внешняя ссылка.
    if "reddit.com/r/" in url and "/comments/" in url:
        return None
    return url


def parse_reddit_feed(data: bytes) -> List[Post]:
    result = []
    for e in parse_feed(data):
        body_html = _strip_author_trailer(e.content_html)
        text = html_to_text(body_html)
        text = text.replace("&#32;", " ").strip()
        result.append(Post(
            source="reddit",
            external_id=e.id,
            title=e.title,
            url=e.link,
            published=e.published,
            text=text[:4000],
            link_url=_external_link(e.content_html),
        ))
    return result
