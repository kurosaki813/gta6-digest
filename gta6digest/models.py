"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Post:
    """A single post or article from any source.

    PRIVACY: there is intentionally no author field. Usernames are never
    stored or passed further down the pipeline.
    """

    source: str                 # "reddit", "news:Eurogamer", ...
    external_id: str            # ID in the source (Reddit fullname, e.g. t3_abc123)
    title: str
    url: str                    # link to the post/article itself
    published: datetime         # always timezone-aware UTC
    text: str = ""
    link_url: Optional[str] = None   # external link from the post, if any
    score: Optional[int] = None      # Reddit API only
    num_comments: Optional[int] = None
    flair: Optional[str] = None      # Reddit API only


@dataclass
class Classification:
    category: str   # key from classifier.CATEGORIES
    status: str     # key from classifier.STATUSES
    spoiler: bool
