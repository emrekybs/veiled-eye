"""Cross-module result cache used by the ``crossref`` correlation module.

Every ``@module_task`` module stores its finished output here, keyed by
``(module, param)``.  ``crossref`` later reads the outputs of its sibling
modules to correlate them without re-running anything.

Backends
--------
* **redis** (default when the Celery broker is Redis): shared between the
  API process and every Celery worker.  Entries expire after
  ``VEILED_CACHE_TTL`` seconds (default 3600).
* **memory**: in-process dict.  Used by the ``veiled-eye scan`` CLI (no Redis
  needed) and as an automatic fallback when Redis is unreachable.

The cache is strictly best-effort: every public function swallows its own
errors so a cache problem can never break a module.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from typing import Any

_TTL = int(os.environ.get("VEILED_CACHE_TTL", "3600"))
_PREFIX = "veiled:cache:"
_RETRY_AFTER = 60.0

_memory: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
_redis_client = None
_redis_down_since: float | None = None


def _backend() -> str:
    return os.environ.get("VEILED_CACHE", "redis").lower()


def _key(module: str, param: str) -> str:
    return f"{_PREFIX}{module}:{str(param).strip().lower()}"


def _redis():
    """Return a Redis client or ``None`` (cached failure for 60s)."""
    global _redis_client, _redis_down_since
    if _backend() != "redis":
        return None
    if _redis_down_since and time.monotonic() - _redis_down_since < _RETRY_AFTER:
        return None
    if _redis_client is None:
        try:
            import redis

            url = os.environ.get(
                "VEILED_CACHE_URL",
                os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
            )
            _redis_client = redis.Redis.from_url(
                url, socket_connect_timeout=0.5, socket_timeout=1.0
            )
        except Exception:
            _redis_down_since = time.monotonic()
            return None
    return _redis_client


def _mark_redis_down() -> None:
    global _redis_client, _redis_down_since
    _redis_client = None
    _redis_down_since = time.monotonic()


def _mem_set(key: str, value: Any, ttl: int | None = None) -> None:
    with _lock:
        _memory[key] = (time.time() + (ttl or _TTL), value)


def _mem_get(key: str) -> Any:
    with _lock:
        item = _memory.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.time():
            _memory.pop(key, None)
            return None
        return value


def _set(key: str, value: Any, ttl: int | None = None) -> None:
    client = _redis()
    if client is not None:
        try:
            client.set(key, json.dumps(value, default=str), ex=ttl or _TTL)
            return
        except Exception:
            _mark_redis_down()
    _mem_set(key, value, ttl)


def _get(key: str) -> Any:
    client = _redis()
    if client is not None:
        try:
            raw = client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            _mark_redis_down()
    return _mem_get(key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mark_running(module: str, param: str) -> None:
    """Flag that *module* is currently processing *param*."""
    with contextlib.suppress(Exception):
        _set(_key(module, param) + ":state", "RUNNING")


def store(module: str, param: str, result: Any) -> None:
    """Store a finished module output and flag it DONE."""
    try:
        _set(_key(module, param), result)
        _set(_key(module, param) + ":state", "DONE")
    except Exception:
        pass


def state(module: str, param: str) -> str | None:
    """Return ``"RUNNING"``, ``"DONE"`` or ``None`` (never seen)."""
    try:
        return _get(_key(module, param) + ":state")
    except Exception:
        return None


def fetch(module: str, param: str) -> Any:
    """Return the cached output of *module* for *param*, or ``None``."""
    try:
        return _get(_key(module, param))
    except Exception:
        return None


def clear_memory() -> None:
    """Drop the in-process cache (tests / CLI)."""
    with _lock:
        _memory.clear()


# ---------------------------------------------------------------------------
# Source cool-downs: a module marks a source as rate-limited so the next
# lookups (any worker) go straight to the next method for a while.
# ---------------------------------------------------------------------------
def cooldown(source: str, seconds: int) -> None:
    _set(f"{_PREFIX}cooldown:{source}", time.time() + seconds, ttl=max(1, int(seconds)))


def cooling(source: str) -> bool:
    until = _get(f"{_PREFIX}cooldown:{source}")
    try:
        return bool(until) and float(until) > time.time()
    except (TypeError, ValueError):
        return False


def remember(key: str, value: Any, ttl: int = 6 * 3600) -> None:
    """Small shared key/value (Redis or memory) for cross-task state."""
    _set(f"{_PREFIX}kv:{key}", value, ttl=ttl)


def recall(key: str) -> Any:
    return _get(f"{_PREFIX}kv:{key}")
