"""Интерфейс источника.

Любой новый источник (Reddit API, YouTube, сайт) — это класс с двумя вещами:
имя и метод fetch(), который возвращает список Post. Остальной код
не знает и не должен знать, откуда пришли посты.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Post


class Source(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self) -> List[Post]:
        """Вернуть свежие посты. Ошибки сети пусть летят наружу —
        главный цикл их залогирует и пойдёт к следующему источнику."""
