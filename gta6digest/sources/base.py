"""Source interface.

A new source (Reddit API, a news site, YouTube...) is a class with a name and
a fetch() method returning a list of Post objects. The rest of the pipeline
does not know or care where posts come from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Post


class Source(ABC):
    name: str = "base"
    # True if the source can tell us which stored posts were deleted/removed
    supports_deletion_sync: bool = False

    @abstractmethod
    def fetch(self) -> List[Post]:
        """Return fresh posts. Network errors may propagate: the main loop
        logs them and moves on to the next source."""

    def find_removed(self, external_ids: List[str]) -> List[str]:
        """Return the IDs (from external_ids) that no longer exist at the source."""
        return []
