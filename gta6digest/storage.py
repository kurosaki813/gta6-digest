"""Хранилище на SQLite: посты, истории (кластеры дублей), служебные значения."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .classifier import stronger_status
from .clustering import is_same_story
from .models import Classification, Post

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    spoiler      INTEGER NOT NULL DEFAULT 0,
    best_url     TEXT NOT NULL,
    link_url     TEXT,
    mentions     INTEGER NOT NULL DEFAULT 1,
    sources      TEXT NOT NULL DEFAULT '',
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    alerted      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    text         TEXT,
    url          TEXT NOT NULL,
    link_url     TEXT,
    published    TEXT NOT NULL,
    fetched      TEXT NOT NULL,
    score        INTEGER,
    num_comments INTEGER,
    flair        TEXT,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    spoiler      INTEGER NOT NULL DEFAULT 0,
    story_id     INTEGER REFERENCES stories(id) ON DELETE SET NULL,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published);
CREATE INDEX IF NOT EXISTS idx_stories_last_seen ON stories(last_seen);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""
# ВАЖНО (обещание в заявке): в схеме нет колонки с автором поста.

CLUSTER_WINDOW_HOURS = 72


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------- посты ----------
    def save_post(self, post: Post, cls: Classification) -> Tuple[bool, int]:
        """Сохранить пост. Возвращает (новый ли пост, id истории).

        Если пост уже есть — обновляем изменчивые поля (рейтинг, текст после правки).
        """
        cur = self.db.execute(
            "SELECT id, story_id FROM posts WHERE source=? AND external_id=?",
            (post.source, post.external_id))
        row = cur.fetchone()
        if row:
            self.db.execute(
                "UPDATE posts SET title=?, text=?, score=COALESCE(?, score), "
                "num_comments=COALESCE(?, num_comments), flair=COALESCE(?, flair) WHERE id=?",
                (post.title, post.text, post.score, post.num_comments, post.flair, row["id"]))
            self.db.commit()
            return False, row["story_id"]

        story_id = self._attach_to_story(post, cls)
        self.db.execute(
            "INSERT INTO posts (source, external_id, title, text, url, link_url, published, "
            "fetched, score, num_comments, flair, category, status, spoiler, story_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (post.source, post.external_id, post.title, post.text, post.url, post.link_url,
             _iso(post.published), _iso(_now()), post.score, post.num_comments, post.flair,
             cls.category, cls.status, int(cls.spoiler), story_id))
        self.db.commit()
        return True, story_id

    def _attach_to_story(self, post: Post, cls: Classification) -> int:
        since = _iso(_now() - timedelta(hours=CLUSTER_WINDOW_HOURS))
        candidates = self.db.execute(
            "SELECT * FROM stories WHERE last_seen >= ? ORDER BY last_seen DESC", (since,)
        ).fetchall()
        for s in candidates:
            if is_same_story(post.title, s["title"], post.link_url, s["link_url"]):
                new_status = stronger_status(s["status"], cls.status)
                # Если история повысилась до официальной — тема тоже официальная
                category = "official" if new_status in ("official", "confirmed") \
                    and s["category"] in ("discussion", "memes") else s["category"]
                sources = set(filter(None, s["sources"].split(","))) | {post.source}
                # Ссылку на официальный источник предпочитаем ссылке на Reddit
                best_url = s["best_url"]
                if cls.status == "official" and s["status"] != "official" and post.link_url:
                    best_url = post.link_url
                self.db.execute(
                    "UPDATE stories SET mentions = mentions + 1, last_seen=?, status=?, "
                    "category=?, sources=?, best_url=?, spoiler = MAX(spoiler, ?), "
                    "alerted = CASE WHEN ? != status AND ? IN ('official','confirmed') "
                    "THEN 0 ELSE alerted END WHERE id=?",
                    (_iso(_now()), new_status, category, ",".join(sorted(sources)), best_url,
                     int(cls.spoiler), new_status, new_status, s["id"]))
                return s["id"]

        best_url = post.link_url if cls.status == "official" and post.link_url else post.url
        cur = self.db.execute(
            "INSERT INTO stories (title, category, status, spoiler, best_url, link_url, "
            "mentions, sources, first_seen, last_seen) VALUES (?,?,?,?,?,?,1,?,?,?)",
            (post.title, cls.category, cls.status, int(cls.spoiler), best_url, post.link_url,
             post.source, _iso(_now()), _iso(_now())))
        return cur.lastrowid

    # ---------- истории ----------
    def stories_since(self, since: datetime) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM stories WHERE last_seen >= ? "
            "ORDER BY mentions DESC, last_seen DESC", (_iso(since),)).fetchall()

    def stories_to_alert(self) -> List[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM stories WHERE alerted = 0 AND "
            "(status IN ('official','confirmed') OR category = 'official') "
            "ORDER BY first_seen").fetchall()

    def mark_alerted(self, story_id: int) -> None:
        self.db.execute("UPDATE stories SET alerted = 1 WHERE id = ?", (story_id,))
        self.db.commit()

    def mark_all_alerted(self) -> None:
        self.db.execute("UPDATE stories SET alerted = 1")
        self.db.commit()

    # ---------- чистка ----------
    def purge_older_than(self, days: int) -> int:
        """ВАЖНО (обещание в заявке): удаляем данные старше N дней (по умолчанию 30)."""
        cutoff = _iso(_now() - timedelta(days=days))
        n = self.db.execute("DELETE FROM posts WHERE published < ?", (cutoff,)).rowcount
        self.db.execute(
            "DELETE FROM stories WHERE last_seen < ? AND id NOT IN "
            "(SELECT DISTINCT story_id FROM posts WHERE story_id IS NOT NULL)", (cutoff,))
        self.db.commit()
        return n

    def delete_post(self, source: str, external_id: str) -> None:
        """Для синхронизации удалений (используем, когда будет Reddit API)."""
        self.db.execute("DELETE FROM posts WHERE source=? AND external_id=?",
                        (source, external_id))
        self.db.commit()

    # ---------- служебное ----------
    def get_kv(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv(key, value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def counts(self) -> dict:
        posts = self.db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        stories = self.db.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        by_cat = {r[0]: r[1] for r in self.db.execute(
            "SELECT category, COUNT(*) FROM stories GROUP BY category")}
        return {"posts": posts, "stories": stories, "by_category": by_cat}
