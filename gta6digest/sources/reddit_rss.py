"""Reddit via RSS (no API key). Temporary: Reddit retires RSS feeds on 2026-11-13.

Once Data API access is approved, switch `mode = api` in config.ini and
reddit_api.py takes over with the same interface.
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
        self.listings = listings  # e.g. ["new", "hot"]
        self.name = "reddit"

    def fetch(self) -> List[Post]:
        posts: dict = {}
        for listing in self.listings:
            url = f"https://www.reddit.com/r/{self.subreddit}/{listing}/.rss?limit=100"
            try:
                data = http.get(url, self.user_agent)
            except http.HttpError as e:
                if e.status in (403, 404, 410):
                    log.error("Reddit RSS unavailable (HTTP %s). RSS may have been retired — "
                              "switch to mode = api.", e.status)
                raise
            for p in parse_reddit_feed(data):
                posts[p.external_id] = p
        return list(posts.values())


def _strip_author_trailer(content_html: str) -> str:
    """Cut off the "submitted by /u/name [link] [comments]" trailer.

    PRIVACY: this is where the author's username is dropped from RSS data.
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
    # For text posts [link] points back to Reddit itself — not an external link.
    if "reddit.com/r/" in url and "/comments/" in url:
        return None
    return url


def parse_reddit_feed(data: bytes) -> List[Post]:
    result = []
    for e in parse_feed(data):
        body_html = _strip_author_trailer(e.content_html)
        text = html_to_text(body_html).replace("&#32;", " ").strip()
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
