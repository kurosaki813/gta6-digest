"""Small HTTP client built on the standard library: User-Agent, timeouts, retries."""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional

log = logging.getLogger(__name__)

RETRY_STATUSES = (429, 500, 502, 503, 504)


class HttpError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


@dataclass
class Response:
    status: int
    headers: Dict[str, str]   # lower-cased header names
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def request(method: str, url: str, user_agent: str, headers: Optional[Dict[str, str]] = None,
            data: Optional[bytes] = None, timeout: int = 20, retries: int = 3) -> Response:
    """Send a request with a bounded retry policy.

    RATE LIMITS: at most `retries` attempts with an increasing pause, honouring
    Retry-After on 429. After that we give up until the next polling cycle.
    """
    delay = 5
    all_headers = {"User-Agent": user_agent}
    all_headers.update(headers or {})
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return Response(resp.status, hdrs, resp.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < retries:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("HTTP %s from %s, waiting %ss (attempt %s/%s)",
                            e.code, _safe(url), wait, attempt, retries)
                time.sleep(wait)
                delay *= 2
                continue
            raise HttpError(e.code, _safe(url)) from e
        except urllib.error.URLError as e:
            if attempt < retries:
                log.warning("Network error for %s (%s), retrying in %ss", _safe(url), e.reason, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def get(url: str, user_agent: str, timeout: int = 20, retries: int = 3) -> bytes:
    return request("GET", url, user_agent, timeout=timeout, retries=retries).body


def post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HttpError(e.code, f"{_safe(url)} — {body}") from e


def get_json(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def domain_of(url: Optional[str]) -> str:
    if not url:
        return ""
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _safe(url: str) -> str:
    """Hide the Telegram bot token if it ever ends up in a log line."""
    if "api.telegram.org/bot" in url:
        return "https://api.telegram.org/bot<token>/..."
    return url
