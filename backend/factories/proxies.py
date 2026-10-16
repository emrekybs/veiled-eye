"""Proxy pool for outgoing requests (API keys page: ``proxy_list``).

``proxy_list``   proxies separated by commas, spaces or new lines:
                 ``http://user:pass@1.2.3.4:8080``, ``socks5h://host:1080``,
                 or ``tor`` (TOR_PROXY_URL, default socks5h://127.0.0.1:9050)
``proxy_hosts``  optional: only these sites go through the pool
                 (``instagram.com, linkedin.com``); empty = every site

Requests rotate round-robin over healthy proxies. A proxy that fails to
connect is benched for 5 minutes (shared by all workers) and the request is
retried once on the next one. There is no silent fallback to a direct
connection while proxies are configured.

Covers every module that uses ``requests`` (most of them, and the SOCMINT
collectors, which get the pool's first healthy proxy as HTTPS_PROXY). Tools
with their own HTTP stack (maigret, holehe, WhatsMyName, user-scanner)
follow the HTTPS_PROXY environment variable of the worker instead.
"""

from __future__ import annotations

import itertools
import os
import re
import threading
import time
from urllib.parse import urlparse

from factories import result_cache

BENCH_SECONDS = 300
_REFRESH = 30.0
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "proxies": [], "hosts": []}
_counter = itertools.count()


def parse_list(text: str) -> list[str]:
    out = []
    for item in re.split(r"[\s,;]+", str(text or "").strip()):
        if not item:
            continue
        if item.lower() == "tor":
            item = os.environ.get("TOR_PROXY_URL", "socks5h://127.0.0.1:9050")
        elif "://" not in item:
            item = "http://" + item
        if urlparse(item).hostname and item not in out:
            out.append(item)
    return out


def _load() -> tuple[list[str], list[str]]:
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < _REFRESH:
            return _cache["proxies"], _cache["hosts"]
    try:
        from factories.configuration import api_keys_search

        proxies = parse_list(
            api_keys_search("proxy_list") or os.environ.get("VEILED_PROXIES", "")
        )
        hosts = [
            h.strip().lower().lstrip(".")
            for h in re.split(r"[\s,;]+", str(api_keys_search("proxy_hosts") or ""))
            if h.strip()
        ]
    except Exception:
        proxies, hosts = [], []
    with _lock:
        _cache.update(at=now, proxies=proxies, hosts=hosts)
    return proxies, hosts


def reset_cache() -> None:
    with _lock:
        _cache.update(at=0.0, proxies=[], hosts=[])


def applies_to(url: str) -> bool:
    proxies, hosts = _load()
    if not proxies:
        return False
    if not hosts:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


def healthy() -> list[str]:
    proxies, _ = _load()
    return [p for p in proxies if not result_cache.cooling(f"proxy:{p}")]


def pick(exclude: set[str] | None = None) -> str | None:
    pool = [p for p in healthy() if p not in (exclude or set())]
    if not pool:
        return None
    return pool[next(_counter) % len(pool)]


def bench(proxy: str) -> None:
    result_cache.cooldown(f"proxy:{proxy}", BENCH_SECONDS)


def as_requests(proxy: str) -> dict:
    return {"http": proxy, "https": proxy}


def env_for_subprocess() -> dict:
    """HTTP(S)_PROXY for child processes when the pool covers every site."""
    proxies, hosts = _load()
    if not proxies or hosts:
        return {}
    p = pick()
    return (
        {"HTTP_PROXY": p, "HTTPS_PROXY": p, "http_proxy": p, "https_proxy": p}
        if p
        else {}
    )
