#!/usr/bin/env python
"""WhatsMyName module — community-maintained username enumeration.

Uses the WhatsMyName dataset (WebBreacher/WhatsMyName, CC BY-SA 4.0,
(c) Micah Hoffman) — ~700 sites, each with an explicit "exists" and "missing"
signature, so hits are far less noisy than status-code-only checkers.

The dataset ships with Veiled Eye (``wmn-data.json``) and is refreshed from GitHub
at runtime when reachable (``VEILED_WMN_REMOTE=0`` to disable).

Tunables (env):
  VEILED_WMN_CONCURRENCY  parallel requests (default 40)
  VEILED_WMN_TIMEOUT      per-site timeout seconds (default 12)
  VEILED_WMN_NSFW         "1" includes the NSFW category (default off)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from factories.output_builder import build_total, root_node, site_icon
from factories.task_wrapper import module_task

DATA_FILE = Path(__file__).resolve().parent / "wmn-data.json"
REMOTE_URL = (
    "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_cache: dict | None = None


def load_sites() -> list[dict]:
    """Remote dataset when reachable, bundled copy otherwise."""
    global _cache
    if _cache is None:
        data = None
        if os.environ.get("VEILED_WMN_REMOTE", "1") != "0":
            try:
                import requests

                resp = requests.get(REMOTE_URL, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
            except Exception:
                data = None
        if not data or not isinstance(data.get("sites"), list):
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        _cache = data
    nsfw = os.environ.get("VEILED_WMN_NSFW", "0") == "1"
    return [
        s
        for s in _cache["sites"]
        if s.get("valid", True) is not False
        and (nsfw or "nsfw" not in str(s.get("cat", "")).lower())
    ]


def classify(site: dict, status: int, text: str) -> str:
    """found | missing | unknown — WhatsMyName detection semantics."""
    if status == site.get("e_code") and site.get("e_string", "") in text:
        return "found"
    if status == site.get("m_code") and site.get("m_string", "") in text:
        return "missing"
    return "missing" if status == site.get("m_code") else "unknown"


def _account(site: dict, username: str) -> str:
    acc = username
    for ch in str(site.get("strip_bad_char") or ""):
        acc = acc.replace(ch, "")
    return acc


async def _check(client, sem, site: dict, username: str) -> dict:
    acc = _account(site, username)
    url = site["uri_check"].replace("{account}", acc)
    pretty = (site.get("uri_pretty") or site["uri_check"]).replace("{account}", acc)
    headers = {"User-Agent": UA, **(site.get("headers") or {})}
    async with sem:
        try:
            if site.get("post_body"):
                body = site["post_body"].replace("{account}", acc)
                resp = await client.post(url, content=body, headers=headers)
            else:
                resp = await client.get(url, headers=headers)
            state = classify(site, resp.status_code, resp.text)
            code = resp.status_code
        except Exception as exc:
            state, code = "error", type(exc).__name__
    return {
        "name": site["name"],
        "cat": site.get("cat", "misc"),
        "url": pretty,
        "state": state,
        "status": code,
    }


async def _run(username: str, sites: list[dict]) -> list[dict]:
    import httpx

    sem = asyncio.Semaphore(int(os.environ.get("VEILED_WMN_CONCURRENCY", "40")))
    timeout = httpx.Timeout(float(os.environ.get("VEILED_WMN_TIMEOUT", "12")))
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, verify=False
    ) as client:
        return await asyncio.gather(*(_check(client, sem, s, username) for s in sites))


@module_task(module_name="whatsmyname", dev_mode_sleep=5)
def p_whatsmyname(param):
    """Task of Celery that enumerates a username with WhatsMyName."""
    username = (param.split("@")[0] if "@" in param else param).strip().lstrip("@")
    sites = load_sites()
    results = asyncio.run(_run(username, sites))
    found = [r for r in results if r["state"] == "found"]
    if not found:
        raise Exception(f"warn: Username not found on {len(sites)} WhatsMyName sites")

    gather = [
        root_node(
            "WhatsMyName",
            username,
            "fas fa-search",
            f"{len(found)} / {len(sites)} sites",
        )
    ]
    social, categories = [], {}
    for r in sorted(found, key=lambda x: (x["cat"], x["name"])):
        categories[r["cat"]] = categories.get(r["cat"], 0) + 1
        icon = site_icon(r["name"])
        gather.append(
            {
                "name-node": f"WMN-{r['name']}",
                "title": r["name"],
                "subtitle": r["cat"],
                "icon": icon,
                "link": "WhatsMyName",
                "help": r["url"],
            }
        )
        social.append(
            {
                "name": r["name"],
                "url": r["url"],
                "icon": icon,
                "source": "whatsmyname",
                "username": username,
                "category": r["cat"],
            }
        )
    stats = {
        state: sum(1 for r in results if r["state"] == state)
        for state in ("found", "missing", "unknown", "error")
    }
    profile = [
        {"social": social},
        {"username": username},
        {
            "presence": [
                {
                    "name": "whatsmyname",
                    "children": [
                        {"name": c, "value": n} for c, n in sorted(categories.items())
                    ],
                }
            ]
        },
    ]
    graphic = [
        {"whatsmyname": gather},
        {"lists": found},
        {"categories": categories},
        {"stats": stats},
    ]
    return build_total(
        module="whatsmyname",
        param=param,
        validation="soft",
        raw={
            "username": username,
            "checked": len(sites),
            "stats": stats,
            "found": found,
        },
        graphic=graphic,
        profile=profile,
        timeline=[],
    )


t_whatsmyname = p_whatsmyname

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    print(json.dumps(t_whatsmyname(ap.parse_args().username, dev_mode=False), indent=2))
