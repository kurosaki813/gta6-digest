"""Data sources. Each one implements the Source interface from base.py."""
from .base import Source
from .news_rss import NewsRssSource
from .reddit_api import RedditApiSource
from .reddit_rss import RedditRssSource

__all__ = ["Source", "NewsRssSource", "RedditApiSource", "RedditRssSource"]
