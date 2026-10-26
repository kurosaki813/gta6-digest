"""RSS 2.0 and Atom parsing without third-party libraries."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"


@dataclass
class FeedEntry:
    id: str
    title: str
    link: str
    published: datetime
    content_html: str


def parse_date(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    value = value.strip()
    try:
        # ISO 8601 (Atom). Python 3.9 does not accept "Z", so replace it.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)  # RFC 822 (RSS)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_feed(data: bytes) -> List[FeedEntry]:
    root = ET.fromstring(data)
    entries: List[FeedEntry] = []

    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry"):
            link = ""
            for l in e.findall(f"{ATOM}link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            content = e.find(f"{ATOM}content")
            if content is None:
                content = e.find(f"{ATOM}summary")
            entries.append(FeedEntry(
                id=_text(e.find(f"{ATOM}id")) or link,
                title=html.unescape(_text(e.find(f"{ATOM}title"))),
                link=link,
                published=parse_date(_text(e.find(f"{ATOM}published"))
                                     or _text(e.find(f"{ATOM}updated"))),
                content_html=_text(content),
            ))
        return entries

    channel = root.find("channel")
    if channel is None:
        raise ValueError("Unknown feed format")
    for item in channel.findall("item"):
        link = _text(item.find("link"))
        content = _text(item.find(f"{CONTENT_NS}encoded")) or _text(item.find("description"))
        entries.append(FeedEntry(
            id=_text(item.find("guid")) or link,
            title=html.unescape(_text(item.find("title"))),
            link=link,
            published=parse_date(_text(item.find("pubDate"))),
            content_html=content,
        ))
    return entries


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>", "\n", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    return _WS_RE.sub(" ", s).strip()
