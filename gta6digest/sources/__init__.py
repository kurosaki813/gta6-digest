"""Источники данных. Каждый реализует интерфейс Source из base.py."""
from .base import Source
from .news_rss import NewsRssSource
from .reddit_rss import RedditRssSource

__all__ = ["Source", "NewsRssSource", "RedditRssSource"]
