"""Reddit via the official Data API (OAuth, "script" app type). Read-only.

Disabled until access is approved: set `mode = api` and the credentials in
config.ini.

What this module does with Reddit data:
  * reads listings (new/hot/...) of one subreddit and /api/info for deletion checks;
  * never posts, votes, comments or sends messages;
  * never stores the author — the `author` field is only looked at to detect
    deleted posts and is then discarded;
  * respects the X-Ratelimit-* headers and keeps a minimum gap between requests.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .. import http
from ..models import Post
from .base import Source

log = logging.getLogger(__name__)

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
INFO_BATCH = 100          # /api/info accepts up to 100 fullnames per call
LOW_REMAINING = 5         # pause until reset when fewer requests than this remain


def is_removed(d: Dict) -> bool:
    """True if a post was deleted by its author or removed by moderators/admins."""
    if d.get("removed_by_category"):
        return True
    if d.get("selftext") in ("[deleted]", "[removed]"):
        return True
    # Looked at only to detect deletion; never stored.
    return d.get("author") == "[deleted]"


def parse_post(d: Dict) -> Post:
    """Convert a Reddit `t3` object into a Post. PRIVACY: `author` is not copied."""
    link = None if d.get("is_self") else (d.get("url_overridden_by_dest") or d.get("url"))
    return Post(
        source="reddit",
        external_id=d["name"],                      # fullname, e.g. t3_abc123
        title=d.get("title", ""),
        url="https://www.reddit.com" + d.get("permalink", ""),
        published=datetime.fromtimestamp(float(d.get("created_utc", 0)), tz=timezone.utc),
        text=(d.get("selftext") or "")[:4000],
        link_url=link,
        score=d.get("score"),
        num_comments=d.get("num_comments"),
        flair=d.get("link_flair_text"),
    )


def parse_listing(payload: Dict) -> List[Post]:
    posts = []
    for child in payload.get("data", {}).get("children", []):
        if child.get("kind") != "t3":
            continue
        d = child.get("data", {})
        if is_removed(d):
            continue
        posts.append(parse_post(d))
    return posts


class RedditApiSource(Source):
    supports_deletion_sync = True

    def __init__(self, subreddit: str, user_agent: str, listings: List[str],
                 client_id: str, client_secret: str, username: str, password: str,
                 min_interval: float = 1.0):
        missing = [k for k, v in {"client_id": client_id, "client_secret": client_secret,
                                  "username": username, "password": password}.items() if not v]
        if missing:
            raise ValueError(f"Reddit API mode needs these settings in config.ini: {', '.join(missing)}")
        self.name = "reddit"
        self.subreddit = subreddit
        self.user_agent = user_agent
        self.listings = listings
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self.min_interval = min_interval

        self._token: Optional[str] = None
        self._token_expires = 0.0
        self._last_request = 0.0
        self._remaining: Optional[float] = None
        self._reset_at = 0.0
        self.requests_made = 0

    # ---------- auth ----------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        data = urllib.parse.urlencode({
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
        }).encode("utf-8")
        resp = http.request("POST", TOKEN_URL, self.user_agent, data=data, headers={
            "Authorization": http.basic_auth(self._client_id, self._client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self.requests_made += 1
        payload = resp.json()
        if "access_token" not in payload:
            raise RuntimeError(f"Reddit auth failed: {payload.get('error', 'unknown error')}")
        self._token = payload["access_token"]
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    # ---------- rate limiting ----------
    def _wait_for_slot(self) -> None:
        now = time.monotonic()
        wait = self._last_request + self.min_interval - now
        if self._remaining is not None and self._remaining < LOW_REMAINING and self._reset_at > now:
            wait = max(wait, self._reset_at - now)
            log.warning("Reddit rate limit nearly used up, pausing %.0fs", wait)
        if wait > 0:
            time.sleep(wait)

    def _update_limits(self, headers: Dict[str, str]) -> None:
        try:
            if "x-ratelimit-remaining" in headers:
                self._remaining = float(headers["x-ratelimit-remaining"])
            if "x-ratelimit-reset" in headers:
                self._reset_at = time.monotonic() + float(headers["x-ratelimit-reset"])
        except ValueError:
            pass

    def _get(self, path: str, params: Dict[str, str]) -> Dict:
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
        for attempt in (1, 2):
            self._wait_for_slot()
            token = self._get_token()
            try:
                resp = http.request("GET", url, self.user_agent,
                                    headers={"Authorization": f"bearer {token}"})
            except http.HttpError as e:
                if e.status == 401 and attempt == 1:  # token expired early
                    self._token = None
                    continue
                raise
            finally:
                self._last_request = time.monotonic()
                self.requests_made += 1
            self._update_limits(resp.headers)
            return resp.json()
        raise RuntimeError("Reddit API: authorization failed twice")

    # ---------- Source interface ----------
    def fetch(self) -> List[Post]:
        posts: Dict[str, Post] = {}
        for listing in self.listings:
            payload = self._get(f"/r/{self.subreddit}/{listing}", {"limit": "100", "raw_json": "1"})
            for p in parse_listing(payload):
                posts[p.external_id] = p
        return list(posts.values())

    def find_removed(self, external_ids: List[str]) -> List[str]:
        """Check stored posts in batches of 100 and return those deleted or removed."""
        removed: List[str] = []
        ids = [i for i in external_ids if i.startswith("t3_")]
        for start in range(0, len(ids), INFO_BATCH):
            chunk = ids[start:start + INFO_BATCH]
            payload = self._get("/api/info", {"id": ",".join(chunk), "raw_json": "1"})
            present = {c["data"]["name"]: c["data"]
                       for c in payload.get("data", {}).get("children", [])}
            removed.extend(i for i in chunk if i not in present or is_removed(present[i]))
        return removed
