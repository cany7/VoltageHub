from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from threading import RLock
from typing import Any, TypeVar

from cachetools import TTLCache

from app.config.settings import AppSettings, get_settings

T = TypeVar("T")


class QueryCache:
    """Small in-memory TTL cache for serving-layer hot aggregate reads."""

    def __init__(self, *, ttl_seconds: int, maxsize: int = 256) -> None:
        # Assumption: the spec requires TTL behavior but does not prescribe a
        # cache-size limit, so a 256-entry cap is used as a small default bound.
        self._cache: TTLCache[tuple[Any, ...], Any] = TTLCache(
            maxsize=maxsize,
            ttl=ttl_seconds,
        )
        self._lock = RLock()

    def get_or_set(self, key: tuple[Any, ...], loader: Callable[[], T]) -> T:
        with self._lock:
            cached_value = self._cache.get(key)
            if cached_value is not None:
                return cached_value

        computed_value = loader()
        with self._lock:
            self._cache[key] = computed_value
        return computed_value


@lru_cache(maxsize=1)
def get_query_cache() -> QueryCache:
    settings: AppSettings = get_settings()
    return QueryCache(ttl_seconds=settings.cache_ttl_seconds)
