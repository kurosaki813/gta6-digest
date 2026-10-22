"""Главная логика: цикл сбора, дайджест, уведомления."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .classifier import Classifier
from .config import Config
from .digest import build_alert, build_digest, digest_header, html_to_console
from .sources import NewsRssSource, RedditRssSource, Source
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
                log.warning("Telegram включён, но нет token или chat_id — отправка отключена")
            else:
                self.telegram = Telegram(cfg.telegram_token, cfg.telegram_chat_id)

    def _build_sources(self) -> List[Source]:
        srcs: List[Source] = []
        if self.cfg.reddit_enabled:
            srcs.append(RedditRssSource(self.cfg.subreddit, self.cfg.user_agent,
                                        self.cfg.reddit_listings))
        for name, url in self.cfg.news_feeds:
            srcs.append(NewsRssSource(name, url, self.cfg.user_agent, self.cfg.news_keywords))
        return srcs

    # ---------- один цикл ----------
    def collect(self) -> dict:
        stats = {"new": 0, "updated": 0, "errors": 0}
        for src in self.sources:
            try:
                posts = src.fetch()
            except Exception as e:  # один сломанный источник не должен валить остальные
                stats["errors"] += 1
                log.error("Источник %s: ошибка %s", src.name, e)
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
            log.info("Источник %s: получено %s, новых %s", src.name, len(posts), new_here)

        purged = self.storage.purge_older_than(self.cfg.retention_days)
        if purged:
            log.info("Удалено старых постов: %s", purged)
        return stats

    def send_alerts(self) -> int:
        stories = self.storage.stories_to_alert()
        if not stories:
            return 0
        sent = 0
        for s in stories:
            text = build_alert(s)
            if self.telegram and self.cfg.instant_alerts:
                try:
                    self.telegram.send(text)
                except Exception as e:
                    log.error("Не удалось отправить уведомление: %s", e)
                    break
            else:
                log.info("Уведомление: %s", html_to_console(text).replace("\n", " | "))
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

    # ---------- бесконечный цикл ----------
    def _digest_due(self) -> bool:
        now = datetime.now()  # локальное время машины
        hh, mm = (int(x) for x in self.cfg.digest_time.split(":"))
        today = now.strftime("%Y-%m-%d")
        if self.storage.get_kv("last_digest_date") == today:
            return False
        return (now.hour, now.minute) >= (hh, mm)

    def run_forever(self) -> None:
        # При самом первом запуске база пустая и всё "новое" — не спамим
        # уведомлениями про старые посты.
        first_run = self.storage.get_kv("initialized") is None
        log.info("Старт. Источников: %s, опрос каждые %s мин., дайджест в %s",
                 len(self.sources), self.cfg.poll_minutes, self.cfg.digest_time)
        while True:
            started = time.monotonic()
            try:
                stats = self.collect()
                log.info("Цикл: новых %s, обновлено %s, ошибок источников %s",
                         stats["new"], stats["updated"], stats["errors"])
                if first_run:
                    self.storage.mark_all_alerted()
                    self.storage.set_kv("initialized", "1")
                    first_run = False
                else:
                    n = self.send_alerts()
                    if n:
                        log.info("Отправлено уведомлений: %s", n)
                if self._digest_due():
                    self.send_digest()
                    self.storage.set_kv("last_digest_date", datetime.now().strftime("%Y-%m-%d"))
                    log.info("Дайджест отправлен")
            except Exception:
                log.exception("Ошибка в цикле, продолжаю работу")
            elapsed = time.monotonic() - started
            time.sleep(max(60.0, self.cfg.poll_minutes * 60 - elapsed))
