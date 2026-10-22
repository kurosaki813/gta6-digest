"""Маленький HTTP-клиент на стандартной библиотеке: User-Agent, таймауты, повторы."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


class HttpError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


def get(url: str, user_agent: str, timeout: int = 20, retries: int = 3) -> bytes:
    """GET с повторами. На 429 (слишком много запросов) ждём и пробуем ещё раз.

    ВАЖНО (лимиты Reddit): мы не долбим сервер. Максимум 3 попытки
    с растущей паузой, потом сдаёмся до следующего цикла.
    """
    delay = 5
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
                log.warning("HTTP %s от %s, жду %s сек (попытка %s/%s)",
                            e.code, url, wait, attempt, retries)
                time.sleep(wait)
                delay *= 2
                continue
            raise HttpError(e.code, url) from e
        except urllib.error.URLError as e:
            if attempt < retries:
                log.warning("Сетевая ошибка %s (%s), повтор через %s сек", url, e.reason, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise HttpError(e.code, f"{url} — {body}") from e


def get_json(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def domain_of(url: str | None) -> str:
    if not url:
        return ""
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host
