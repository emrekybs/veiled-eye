"""Default timeout and the proxy pool for every outgoing HTTP request.

Several upstream modules call ``requests`` without a timeout; one silent
server then blocks a worker slot until the task hard limit. ``install()``
gives every ``requests`` call (``requests.get`` included, it goes through
``Session.request``) a default ``timeout`` when the caller did not pass one.

Against blocking it also:

* replaces the default ``python-requests/x`` User-Agent (blocked on sight by
  many sites) with a current browser one, rotated per session
* retries once after HTTP 429 / 503, honouring ``Retry-After`` (capped by
  ``VEILED_HTTP_RETRY_MAX``, default 8 s) and switching proxy when a pool
  is configured
"""

from __future__ import annotations

import os
import random
import time

import requests
from factories import proxies

BROWSER_UAS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
)
_RETRY_STATUS = (429, 503)


def _retry_after(resp) -> float:
    cap = float(os.environ.get("VEILED_HTTP_RETRY_MAX", "8"))
    raw = str(resp.headers.get("Retry-After", "")).strip()
    try:
        wait = float(raw) if raw else 2.0 + random.random() * 2
    except ValueError:
        wait = 3.0
    return max(0.5, min(wait, cap))


DEFAULT_TIMEOUT = (
    float(os.environ.get("VEILED_HTTP_CONNECT_TIMEOUT", "10")),
    float(os.environ.get("VEILED_HTTP_TIMEOUT", "45")),
)
_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    original = requests.Session.request

    def request(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = DEFAULT_TIMEOUT
        ua = str(self.headers.get("User-Agent", ""))
        headers = kwargs.get("headers") or {}
        if ua.startswith("python-requests") and not any(
            k.lower() == "user-agent" for k in headers
        ):
            if not getattr(self, "_ve_ua", None):
                self._ve_ua = random.choice(BROWSER_UAS)
            self.headers["User-Agent"] = self._ve_ua
        if kwargs.get("proxies") or not proxies.applies_to(str(url)):
            resp = original(self, method, url, **kwargs)
            if (
                resp.status_code in _RETRY_STATUS
                and os.environ.get("VEILED_HTTP_RETRY", "1") != "0"
            ):
                time.sleep(_retry_after(resp))
                resp = original(self, method, url, **kwargs)
            return resp
        tried: set[str] = set()
        for _attempt in range(2):
            proxy = proxies.pick(exclude=tried)
            if proxy is None:
                raise requests.ConnectionError(
                    "every configured proxy is benched (proxy_list); try again later"
                )
            tried.add(proxy)
            try:
                resp = original(
                    self, method, url, proxies=proxies.as_requests(proxy), **kwargs
                )
                if resp.status_code in _RETRY_STATUS and _attempt == 0:
                    proxies.bench(proxy)  # this exit is rate limited: next one
                    last = requests.HTTPError(f"HTTP {resp.status_code} via proxy")
                    continue
                return resp
            except (
                requests.exceptions.ProxyError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.SSLError,
            ) as exc:
                proxies.bench(proxy)
                last = exc
        raise last

    request.__wrapped__ = original  # type: ignore[attr-defined]
    requests.Session.request = request
    _installed = True
