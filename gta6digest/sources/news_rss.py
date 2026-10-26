"""News sites via RSS. Only articles about GTA 6 are kept."""
from __future__ import annotations

import re
from typing import List

from .. import http
from ..feeds import html_to_text, parse_feed
from ..models import Post
from .base import Source


class NewsRssSource(Source):
    def __init__(self, name: str, url: str, user_agent: str, keywords: List[str]):
        self.name = f"news:{name}"
        self.url = url
        self.user_agent = user_agent
        self._kw = re.compile("|".join(re.escape(k) for k in keywords), re.I) if keywords else None

    def fetch(self) -> List[Post]:
        data = http.get(self.url, self.user_agent)
        posts = []
        for e in parse_feed(data):
            text = html_to_text(e.content_html)
            if self._kw and not self._kw.search(e.title + " " + text):
                continue
            posts.append(Post(
                source=self.name,
                external_id=e.id,
                title=e.title,
                url=e.link,
                published=e.published,
                text=text[:4000],
                link_url=e.link,
            ))
        return posts
