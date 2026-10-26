"""Main logic: collection loop, deletion sync, digest and alerts."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .classifier import Classifier
from .config import Config
from .digest import build_alert, build_digest, digest_header, html_to_console
from .sources import NewsRssSource, RedditApiSource, RedditRssSource, Source
from .storage import Storage
from .telegram import Telegram

log = logging.getLogger("gta6digest")


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.storage = Storage(str(cfg.db_path))
        self.classifier = Classifier(cfg.official_domains, cfg.insiders)
        self.sources = self._build_sources()
        self.telegram: Optional[Telegram] = None
        if cfg.telegram_enabled:
            if not cfg.telegram_token or not cfg.telegram_chat_id:
                log.warning("Telegram is enabled but token or chat_id is missing — sending disabled")
            else:
                self.telegram = Telegram(cfg.telegram_token, cfg.telegram_chat_id)

    def _build_sources(self) -> List[Source]:
        srcs: List[Source] = []
        cfg = self.cfg
        if cfg.reddit_enabled:
            if cfg.reddit_mode == "api":
                srcs.append(RedditApiSource(
                    cfg.subreddit, cfg.user_agent, cfg.reddit_listings,
                    cfg.reddit_client_id, cfg.reddit_client_secret,
                    cfg.reddit_username, cfg.reddit_password))
            else:
                srcs.append(RedditRssSource(cfg.subreddit, cfg.user_agent, cfg.reddit_listings))
        for name, url in cfg.news_feeds:
            srcs.append(NewsRssSource(name, url, cfg.user_agent, cfg.news_keywords))
        return srcs

    # ---------- one cycle ----------
    def collect(self) -> dict:
        stats = {"new": 0, "updated": 0, "errors": 0, "deleted": 0}
        for src in self.sources:
            try:
                posts = src.fetch()
            except Exception as e:  # one broken source must not stop the others
                stats["errors"] += 1
                log.error("Source %s: error %s", src.name, e)
                continue
            new_here = 0
            for post in posts:
                cls = self.classifier.classify(post)
                is_new, _ = self.storage.save_post(post, cls)
                if is_new:
                    new_here += 1
                else:
                    stats["updated"] += 1
            stats["new"] += new_here
            log.info("Source %s: fetched %s, new %s", src.name, len(posts), new_here)

        stats["deleted"] = self.sync_deletions()
        purged = self.storage.purge_older_than(self.cfg.retention_days)
        if purged:
            log.info("Purged %s posts older than %s days", purged, self.cfg.retention_days)
        for src in self.sources:
            if hasattr(src, "requests_made"):
                log.info("Source %s: %s API requests since start", src.name, src.requests_made)
        return stats

    def sync_deletions(self, force: bool = False) -> int:
        """DELETION SYNC: drop stored posts that were deleted or removed at the source.

        Runs every `deletion_sync_hours` (default 6) to keep API usage low.
        """
        key = "last_deletion_sync"
        last = self.storage.get_kv(key)
        now = time.time()
        if not force and last and now - float(last) < self.cfg.deletion_sync_hours * 3600:
            return 0
        deleted = 0
        for src in self.sources:
            if not src.supports_deletion_sync:
                continue
            try:
                removed = src.find_removed(self.storage.ids_for_source(src.name))
            except Exception as e:
                log.error("Deletion sync for %s failed: %s", src.name, e)
                return deleted  # try again next cycle
            for ext_id in removed:
                self.storage.delete_post(src.name, ext_id)
            deleted += len(removed)
            log.info("Deletion sync for %s: removed %s posts", src.name, len(removed))
        self.storage.set_kv(key, str(now))
        return deleted

    def send_alerts(self) -> int:
        stories = self.storage.stories_to_alert()
        sent = 0
        for s in stories:
            text = build_alert(s)
            if self.telegram and self.cfg.instant_alerts:
                try:
                    self.telegram.send(text)
                except Exception as e:
                    log.error("Could not send alert: %s", e)
                    break
            else:
                log.info("Alert: %s", html_to_console(text).replace("\n", " | "))
            self.storage.mark_alerted(s["id"])
            sent += 1
        return sent

    def make_digest(self, hours: int = 24) -> str:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return build_digest(self.storage.stories_since(since), self.cfg.max_per_category,
                            self.cfg.show_memes, digest_header(datetime.now()))

    def send_digest(self, hours: int = 24) -> str:
        text = self.make_digest(hours)
        if self.telegram:
            self.telegram.send(text)
        return text

    # ---------- main loop ----------
    def _digest_due(self) -> bool:
        now = datetime.now()  # machine local time
        hh, mm = (int(x) for x in self.cfg.digest_time.split(":"))
        if self.storage.get_kv("last_digest_date") == now.strftime("%Y-%m-%d"):
            return False
        return (now.hour, now.minute) >= (hh, mm)

    def run_forever(self) -> None:
        # On the very first run everything looks "new" — don't spam alerts about old posts.
        first_run = self.storage.get_kv("initialized") is None
        log.info("Starting. Sources: %s, polling every %s min, digest at %s",
                 len(self.sources), self.cfg.poll_minutes, self.cfg.digest_time)
        while True:
            started = time.monotonic()
            try:
                stats = self.collect()
                log.info("Cycle: new %s, updated %s, deleted %s, source errors %s",
                         stats["new"], stats["updated"], stats["deleted"], stats["errors"])
                if first_run:
                    self.storage.mark_all_alerted()
                    self.storage.set_kv("initialized", "1")
                    first_run = False
                else:
                    n = self.send_alerts()
                    if n:
                        log.info("Alerts sent: %s", n)
                if self._digest_due():
                    self.send_digest()
                    self.storage.set_kv("last_digest_date", datetime.now().strftime("%Y-%m-%d"))
                    log.info("Digest sent")
            except Exception:
                log.exception("Error in cycle, continuing")
            elapsed = time.monotonic() - started
            time.sleep(max(60.0, self.cfg.poll_minutes * 60 - elapsed))
