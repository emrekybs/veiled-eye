#!/usr/bin/env python
"""Ahmia module — .onion search-engine index (filtered, abuse-free index).

Complements the existing ``darkweb`` module (Tor66 + OnionLand over Tor):
Ahmia is queried on its clearnet front-end first (no Tor needed) and, when
that is blocked and ``TOR_PROXY_URL`` is reachable, on its own .onion
address.  Ahmia requires a per-session hidden form token, which is read from
the home page before searching.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

CLEARNET = "https://ahmia.fi"
ONION = "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
UA = "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
ONION_RE = re.compile(r"[a-z2-7]{56}\.onion", re.I)


def _session(tor: bool) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    if tor:
        proxy = os.environ.get("TOR_PROXY_URL", "socks5h://127.0.0.1:9050")
        s.proxies = {"http": proxy, "https": proxy}
    return s


def form_token(html: str) -> dict:
    """Hidden inputs of the search form (Ahmia's anti-bot token)."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="searchForm") or soup.find(
        "form", action=re.compile("search")
    )
    if not form:
        return {}
    return {
        i["name"]: i.get("value", "")
        for i in form.find_all("input", attrs={"type": "hidden"})
        if i.get("name")
    }


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for li in soup.select("li.result"):
        a = li.select_one("h4 a") or li.find("a")
        href = a.get("href", "") if a else ""
        target = parse_qs(urlparse(href).query).get("redirect_url", [href])[0]
        cite = li.find("cite")
        onion_match = ONION_RE.search(target) or ONION_RE.search(
            cite.get_text() if cite else ""
        )
        if not onion_match:
            continue
        url = target if ".onion" in target else f"http://{onion_match.group(0)}"
        if url in seen:
            continue
        seen.add(url)
        last = li.select_one("span.lastSeen")
        ts = last.get("data-timestamp") if last else None
        try:
            last_seen = (
                datetime.fromtimestamp(float(ts), tz=UTC).date().isoformat()
                if ts
                else None
            )
        except ValueError:
            last_seen = None
        desc = li.find("p")
        out.append(
            {
                "title": a.get_text(" ", strip=True) if a else onion_match.group(0),
                "url": url,
                "onion": onion_match.group(0).lower(),
                "description": desc.get_text(" ", strip=True)[:300] if desc else "",
                "last_seen": last_seen,
            }
        )
    return out


def search(query: str, tor: bool = False) -> list[dict]:
    base = ONION if tor else CLEARNET
    s = _session(tor)
    home = s.get(base + "/", timeout=60 if tor else 20)
    home.raise_for_status()
    params = {"q": query, **form_token(home.text)}
    resp = s.get(base + "/search/", params=params, timeout=90 if tor else 30)
    if resp.status_code == 429:
        raise Exception("warn: Ahmia rate limited")
    resp.raise_for_status()
    return parse_results(resp.text)


def _tor_available() -> bool:
    import socket

    proxy = urlparse(os.environ.get("TOR_PROXY_URL", "socks5h://127.0.0.1:9050"))
    try:
        with socket.create_connection(
            (proxy.hostname or "127.0.0.1", proxy.port or 9050), timeout=2
        ):
            return True
    except OSError:
        return False


@module_task(module_name="ahmia", dev_mode_sleep=3)
def p_ahmia(param):
    """Task of Celery that searches the Ahmia .onion index."""
    query = param.strip()
    via = "clearnet"
    try:
        hits = search(query)
    except Exception as exc:
        if not _tor_available():
            raise Exception(
                f"warn: Ahmia clearnet blocked and Tor not reachable ({exc})"
            ) from exc
        via = "tor"
        hits = search(query, tor=True)
    if not hits:
        raise Exception("warn: No Ahmia results")

    gather = [
        root_node("Ahmia", query, "fas fa-user-secret", f"{len(hits)} onion results")
    ]
    timeline = []
    for idx, hit in enumerate(hits[:25]):
        gather.append(
            {
                "name-node": f"AH-{idx}",
                "title": hit["title"][:80] or hit["onion"],
                "subtitle": hit["onion"],
                "icon": "fas fa-user-secret",
                "link": "Ahmia",
                "help": hit["description"],
            }
        )
        if hit["last_seen"]:
            timeline.append(
                {
                    "date": hit["last_seen"],
                    "action": f"Ahmia : '{query}' on {hit['onion'][:16]}…",
                    "icon": "fas fa-user-secret",
                }
            )
    profile = [
        {
            "presence": [
                {
                    "name": "ahmia",
                    "children": [{"name": "onion results", "value": len(hits)}],
                }
            ]
        }
    ]
    return build_total(
        module="ahmia",
        param=param,
        validation="soft",
        raw={"query": query, "via": via, "results": hits},
        graphic=[{"ahmia": gather}, {"lists": hits}],
        profile=profile,
        timeline=timeline,
    )


t_ahmia = p_ahmia

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    print(json.dumps(t_ahmia(ap.parse_args().query, dev_mode=False), indent=2))
