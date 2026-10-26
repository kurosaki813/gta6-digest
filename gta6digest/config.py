"""Loading config.ini."""
from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

log = logging.getLogger(__name__)

MAX_RETENTION_DAYS = 30   # stated in the Reddit API access request
MIN_POLL_MINUTES = 15


def _list(value: str) -> List[str]:
    return [v.strip() for v in value.replace("\n", ",").split(",") if v.strip()]


@dataclass
class Config:
    base_dir: Path
    db_path: Path
    log_path: Path
    poll_minutes: int
    retention_days: int
    digest_time: str
    user_agent: str
    telegram_enabled: bool
    telegram_token: str
    telegram_chat_id: str
    instant_alerts: bool
    reddit_enabled: bool
    reddit_mode: str
    subreddit: str
    reddit_listings: List[str]
    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str
    reddit_password: str
    deletion_sync_hours: int
    news_keywords: List[str]
    news_feeds: List[Tuple[str, str]] = field(default_factory=list)
    max_per_category: int = 5
    show_memes: bool = False
    official_domains: List[str] = field(default_factory=list)
    insiders: List[str] = field(default_factory=list)


def load(path: str) -> Config:
    p = Path(path).resolve()
    if not p.exists():
        raise SystemExit(f"Config file {p} not found. Copy config.example.ini to config.ini.")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(p, encoding="utf-8")
    base = p.parent

    feeds = []
    for section in cp.sections():
        if section.startswith("news:") and cp.getboolean(section, "enabled", fallback=True):
            feeds.append((section[5:].strip(), cp.get(section, "url")))

    g, t, r, d, c = cp["general"], cp["telegram"], cp["reddit"], cp["digest"], cp["classifier"]

    retention = g.getint("retention_days", 14)
    if retention > MAX_RETENTION_DAYS:
        log.warning("retention_days=%s is above %s; using %s", retention,
                    MAX_RETENTION_DAYS, MAX_RETENTION_DAYS)
        retention = MAX_RETENTION_DAYS
    poll = max(MIN_POLL_MINUTES, g.getint("poll_minutes", 20))

    mode = r.get("mode", "rss").strip().lower()
    if mode not in ("rss", "api"):
        raise SystemExit("[reddit] mode must be 'rss' or 'api'")

    return Config(
        base_dir=base,
        db_path=base / g.get("db_path", "data/gta6.db"),
        log_path=base / g.get("log_path", "data/parser.log"),
        poll_minutes=poll,
        retention_days=retention,
        digest_time=g.get("digest_time", "10:00"),
        user_agent=g.get("user_agent", "gta6-digest/0.2 (personal project)"),
        telegram_enabled=t.getboolean("enabled", False),
        telegram_token=t.get("token", "").strip(),
        telegram_chat_id=t.get("chat_id", "").strip(),
        instant_alerts=t.getboolean("instant_alerts", True),
        reddit_enabled=r.getboolean("enabled", True),
        reddit_mode=mode,
        subreddit=r.get("subreddit", "GTA6"),
        reddit_listings=_list(r.get("listings", "new, hot")),
        reddit_client_id=r.get("client_id", "").strip(),
        reddit_client_secret=r.get("client_secret", "").strip(),
        reddit_username=r.get("username", "").strip(),
        reddit_password=r.get("password", "").strip(),
        deletion_sync_hours=max(1, r.getint("deletion_sync_hours", 6)),
        news_keywords=_list(cp.get("news", "keywords", fallback="gta 6, gta vi")),
        news_feeds=feeds,
        max_per_category=d.getint("max_per_category", 5),
        show_memes=d.getboolean("show_memes", False),
        official_domains=_list(c.get("official_domains", "rockstargames.com")),
        insiders=_list(c.get("insiders", "")),
    )
