"""Склейка дублей: одна новость, запощенная 20 раз, становится одной "историей"."""
from __future__ import annotations

import re
from typing import Optional, Set

_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.I)

# Слова, которые есть почти в каждом посте и ничего не говорят о сути
STOPWORDS = set("""
a an the and or but if of to in on at by for with from about as is are was were be been
it its this that these those i you he she we they my your our their me him her them
so just not no yes do does did have has had will would can could should what why how
who when where which there here than then too very really more most some any all new
gta gta6 gtavi vi 6 grand theft auto rockstar game games video trailer post thread
reddit sub subreddit guys anyone think know get got like look looks one after before
""".split())

SHORT_KEEP = {"pc", "4k", "ps"}


def _stem(w: str) -> str:
    """Очень грубое приведение к основе: leaked/leaks/leaking -> leak."""
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> Set[str]:
    out = set()
    for w in _WORD_RE.findall(text or ""):
        w = w.lower()
        if w in STOPWORDS or (len(w) < 3 and w not in SHORT_KEEP):
            continue
        out.add(_stem(w))
    return out


def similarity(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_same_story(title_a: str, title_b: str,
                  link_a: Optional[str] = None, link_b: Optional[str] = None) -> bool:
    # Одинаковая внешняя ссылка — почти наверняка одна и та же новость
    if link_a and link_b and link_a.rstrip("/") == link_b.rstrip("/"):
        return True
    ta, tb = tokens(title_a), tokens(title_b)
    shared = len(ta & tb)
    sim = similarity(ta, tb)
    return sim >= 0.5 or (shared >= 4 and sim >= 0.3)
