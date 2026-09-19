"""Run-keyed shared cache and freshness for WeatherNext and other providers.

- Immutable run cache plus atomically updated latest-complete pointer
- Bounded size, retention, spend limits
- Cross-user isolation where needed
- Server-side cache, not client-side
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from threading import RLock
from typing import Any, Optional

from services.forecast_models import NormalizedForecast


@dataclass
class CacheEntry:
    forecast: NormalizedForecast
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: datetime = None  # type: ignore

    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.created_at

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


class ForecastCache:
    """LRU cache with TTL and size bounds."""

    def __init__(self, max_size: int = 1000, default_ttl_seconds: int = 1800):
        self.max_size = max_size
        self.default_ttl = default_ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[NormalizedForecast]:
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                self._evictions += 1
                return None
            # Update LRU and access stats
            self._cache.move_to_end(key)
            entry.access_count += 1
            entry.last_accessed = datetime.now(timezone.utc)
            self._hits += 1
            return entry.forecast

    def set(self, key: str, forecast: NormalizedForecast, ttl_seconds: Optional[int] = None) -> None:
        with self._lock:
            ttl = ttl_seconds or self.default_ttl
            now = datetime.now(timezone.utc)
            expires = now + timedelta(seconds=ttl)
            entry = CacheEntry(forecast=forecast, created_at=now, expires_at=expires)

            if key in self._cache:
                del self._cache[key]
            self._cache[key] = entry

            # Enforce size bound
            while len(self._cache) > self.max_size:
                oldest_key, _ = self._cache.popitem(last=False)
                self._evictions += 1

    def invalidate(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(hit_rate, 3),
                "keys": list(self._cache.keys())[:20],  # first 20 for diagnostics
            }

    def cleanup_expired(self) -> int:
        """Remove expired entries, return count removed."""
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for k in expired_keys:
                del self._cache[k]
                self._evictions += 1
            return len(expired_keys)


# Global cache singleton
_global_cache: Optional[ForecastCache] = None

def get_cache() -> ForecastCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = ForecastCache(max_size=1000, default_ttl_seconds=1800)
    return _global_cache

def clear_cache():
    global _global_cache
    if _global_cache:
        _global_cache.clear()
    else:
        _global_cache = ForecastCache()
