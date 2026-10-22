"""Классификатор на правилах: тема + статус достоверности + флаг спойлера.

Никаких внешних сервисов (обещание в заявке): всё считается локально
по ключевым словам, доменам ссылок и (позже, с API) флейрам.

Как подкрутить: добавляй слова в KEYWORDS. Совпадение в заголовке
весит 2 очка, в тексте — 1. Побеждает тема с наибольшим счётом.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from .http import domain_of
from .models import Classification, Post

# Порядок = порядок разделов в дайджесте
CATEGORIES: Dict[str, str] = {
    "official":   "📢 Официальные анонсы",
    "story":      "🎭 Сюжет и персонажи",
    "map":        "🗺 Карта и локации",
    "gameplay":   "🎮 Геймплей и механики",
    "finds":      "🔍 Находки игроков",
    "technical":  "⚙️ Техническое",
    "online":     "🌐 Онлайн",
    "reviews":    "⭐ Отзывы и впечатления",
    "business":   "💼 Бизнес и продажи",
    "discussion": "💬 Обсуждения",
    "memes":      "😂 Мемы",
}

STATUSES: Dict[str, str] = {
    "official": "✅ официально",
    "confirmed": "✅ слух подтвердился",
    "debunked": "❌ опровергнуто",
    "insider":  "🕵️ инсайдер",
    "rumor":    "❓ слух",
    "theory":   "💭 теория",
    "none":     "",
}

# Приоритет статусов: если в одну историю попали пост-слух и
# официальный пост, у истории остаётся более "сильный" статус.
STATUS_PRIORITY = ["none", "theory", "rumor", "insider", "debunked", "official", "confirmed"]

KEYWORDS: Dict[str, List[str]] = {
    "official": [
        "official trailer", "trailer 3", "trailer 4", "newswire", "rockstar confirms",
        "rockstar announced", "rockstar announces", "officially", "release date",
        "pre-order", "preorder", "pre order", "price", "edition", "rockstar games tweet",
        "rockstar update", "official screenshot", "official artwork",
    ],
    "story": [
        "lucia", "jason", "story", "plot", "character", "protagonist", "ending",
        "mission", "cutscene", "voice actor", "dialogue", "narrative", "villain",
    ],
    "map": [
        "map", "leonida", "vice city", "location", "miami", "florida", "keys",
        "everglades", "grassrivers", "port gellhorn", "ambrosia", "mount kalaga",
        "interior", "city size", "map size", "landmark",
    ],
    "gameplay": [
        "gameplay", "mechanic", "weapon", "vehicle", "car", "driving", "shooting",
        "wanted level", "police", "heist", "robbery", "customization", "physics",
        "npc", "ai behavior", "combat", "stealth", "swimming", "boat", "aircraft",
    ],
    "finds": [
        "easter egg", "noticed", "detail", "found", "discovered", "hidden", "secret",
        "frame by frame", "zoom in", "in the background", "glitch", "bug", "exploit",
        "comparison", "side by side", "analysis", "breakdown",
    ],
    "technical": [
        "pc port", "pc version", "fps", "frame rate", "framerate", "30fps", "60fps",
        "resolution", "4k", "ps5 pro", "ps5", "xbox series", "performance", "graphics",
        "ray tracing", "file size", "download size", "gb", "patch", "crash", "loading",
    ],
    "online": [
        "gta online", "online mode", "multiplayer", "roleplay", " rp ", "servers",
        "shark card", "online 2", "co-op",
    ],
    "reviews": [
        "review", "reviews", "metacritic", "opencritic", "score", "impressions",
        "hands-on", "hands on", "verdict", "rated", "/10", "masterpiece",
        "disappointed", "overrated", "underrated", "my thoughts", "first hours",
    ],
    "business": [
        "take-two", "take two", "take2", "earnings", "sales", "sold", "revenue",
        "investor", "stock", "strauss zelnick", "zelnick", "delay", "delayed",
        "budget", "copies", "fiscal",
    ],
    "memes": [
        "meme", "lol", "lmao", "shitpost", "copium", "hopium", "me waiting",
        "day 1 of", "day one of", "pov:", "be like", "😂", "🤣",
    ],
}

RUMOR_WORDS = ["leak", "leaked", "leaks", "rumor", "rumour", "rumored", "allegedly",
               "reportedly", "unconfirmed", "apparently", "source claims", "sources say"]
DEBUNK_WORDS = ["fake", "debunked", "not real", "hoax", "false", "misinformation",
                "photoshopped", "edited image", "is not true"]
THEORY_WORDS = ["theory", "theories", "speculation", "speculate", "what if",
                "could this be", "prediction", "predictions", "i think", "my guess"]
OFFICIAL_WORDS = ["rockstar confirms", "officially", "official trailer", "newswire",
                  "rockstar announced", "rockstar announces", "confirmed by rockstar"]
SPOILER_WORDS = ["spoiler", "spoilers", "ending", "final mission", "plot twist",
                 "dies", "death of", "last mission", "post-credits"]


def _compile(words: Iterable[str]) -> re.Pattern:
    parts = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        esc = re.escape(w)
        # Границы слов ставим только там, где края — буквы/цифры
        left = r"\b" if w[0].isalnum() else ""
        right = r"\b" if w[-1].isalnum() else ""
        parts.append(f"{left}{esc}{right}")
    return re.compile("|".join(parts) or r"(?!x)x", re.I)


class Classifier:
    def __init__(self, official_domains: List[str], insiders: Optional[List[str]] = None):
        self.official_domains = [d.lower().strip() for d in official_domains if d.strip()]
        self._cat = {c: _compile(ws) for c, ws in KEYWORDS.items()}
        self._rumor = _compile(RUMOR_WORDS)
        self._debunk = _compile(DEBUNK_WORDS)
        self._theory = _compile(THEORY_WORDS)
        self._official = _compile(OFFICIAL_WORDS)
        self._spoiler = _compile(SPOILER_WORDS)
        self._insider = _compile(insiders or [])

    def _is_official_domain(self, url: Optional[str]) -> bool:
        d = domain_of(url)
        return bool(d) and any(d == od or d.endswith("." + od) for od in self.official_domains)

    def classify(self, post: Post) -> Classification:
        title = post.title or ""
        text = post.text or ""
        both = f"{title}\n{text}"
        official_link = self._is_official_domain(post.link_url)

        # --- тема ---
        scores: Dict[str, int] = {}
        for cat, rx in self._cat.items():
            s = 2 * len(rx.findall(title)) + len(rx.findall(text))
            if s:
                scores[cat] = s
        if official_link:
            scores["official"] = scores.get("official", 0) + 10
        if post.flair:  # заработает с Reddit API
            f = post.flair.lower()
            if "meme" in f or "humor" in f:
                scores["memes"] = scores.get("memes", 0) + 5
            elif "news" in f:
                scores["official"] = scores.get("official", 0) + 3
            elif "leak" in f or "rumor" in f:
                pass  # тема определяется содержанием, флейр влияет на статус ниже
        # --- статус достоверности ---
        if official_link or self._official.search(title):
            status = "official"
        elif self._debunk.search(title):
            status = "debunked"
        elif self._insider.search(both):
            status = "insider"
        elif self._rumor.search(title) or (post.flair and "leak" in post.flair.lower()):
            status = "rumor"
        elif self._theory.search(title):
            status = "theory"
        else:
            status = "none"

        # Тема "Официальные анонсы" только для официальной информации:
        # слух про дату релиза — это не анонс.
        if status != "official":
            scores.pop("official", None)
        category = max(scores, key=lambda c: (scores[c], -list(CATEGORIES).index(c))) \
            if scores else "discussion"

        # Официальный статус без официальной темы — обычно новость про дату/трейлер
        if status == "official" and category in ("discussion", "memes"):
            category = "official"

        spoiler = bool(self._spoiler.search(title)) or \
            bool(post.flair and "spoiler" in post.flair.lower())
        return Classification(category=category, status=status, spoiler=spoiler)


def stronger_status(a: str, b: str) -> str:
    """Какой статус оставить у истории, когда в неё добавился новый пост."""
    if a in ("rumor", "insider") and b == "official":
        return "confirmed"  # слух подтвердился официально
    ia = STATUS_PRIORITY.index(a) if a in STATUS_PRIORITY else 0
    ib = STATUS_PRIORITY.index(b) if b in STATUS_PRIORITY else 0
    return a if ia >= ib else b
