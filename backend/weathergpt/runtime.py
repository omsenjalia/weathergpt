"""Process-wide runtime state: uptime, a ring buffer of recent events, and a TTL cache."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Generic, Optional, TypeVar

START_TIME = time.time()
START_DATETIME = datetime.now(timezone.utc).isoformat()
RECENT_LOGS: deque[dict] = deque(maxlen=100)


def log_event(level: str, message: str, details: Optional[dict] = None) -> None:
    RECENT_LOGS.appendleft({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "details": details or {},
    })


def uptime_seconds() -> float:
    return round(time.time() - START_TIME, 2)


T = TypeVar("T")


class TTLCache(Generic[T]):
    """Small thread-safe LRU cache with per-entry expiry.

    Serverless instances are short-lived, so this only has to absorb bursts
    (the home screen, chat and advisory asking about the same place at once).
    """

    def __init__(self, name: str, max_entries: int = 512):
        self.name = name
        self.max_entries = max_entries
        self._data: "OrderedDict[str, tuple[float, T]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[T]:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None or item[0] < now:
                if item is not None:
                    del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return item[1]

    def set(self, key: str, value: T, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_seconds, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def get_or_set(self, key: str, ttl_seconds: float, factory: Callable[[], T]) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value, ttl_seconds)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"name": self.name, "entries": len(self._data), "hits": self.hits, "misses": self.misses}


_caches: list[TTLCache] = []


def make_cache(name: str, max_entries: int = 512) -> TTLCache:
    cache: TTLCache = TTLCache(name, max_entries)
    _caches.append(cache)
    return cache


def cache_stats() -> list[dict]:
    return [c.stats() for c in _caches]


def clear_all_caches() -> None:
    for cache in _caches:
        cache.clear()
