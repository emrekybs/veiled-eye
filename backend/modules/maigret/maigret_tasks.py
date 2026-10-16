#!/usr/bin/env python
"""Maigret module — username dossier across thousands of sites.

Wraps soxoj/maigret (MIT) through its Python API.  Besides account
existence, maigret's page parser extracts identity data (full name, bio,
location, avatar, linked usernames / links) which Veiled Eye turns into profile
entries so the Profile and Timeline views pick them up automatically.

Tunables (env):
  VEILED_MAIGRET_TOP      sites to check, ranked by popularity (default 500;
                       "all" = the whole ~3000 site database)
  VEILED_MAIGRET_TIMEOUT  per-site timeout in seconds (default 10)
  VEILED_MAIGRET_TAGS     comma separated tag whitelist (e.g. "coding,photo")
  TOR_PROXY_URL        when set, .onion sites are checked through Tor
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from celery.utils.log import get_task_logger
from factories.links import PLATFORM_MODULE, profiles_in
from factories.output_builder import build_total, root_node, site_icon
from factories.task_wrapper import module_task

logger = get_task_logger(__name__)

LINK = "Maigret"

# ids_data keys produced by maigret's parsers -> Veiled Eye profile keys
_PROFILE_MAP = {
    "fullname": "name",
    "name": "name",
    "first_name": "firstName",
    "last_name": "lastName",
    "bio": "bio",
    "description": "bio",
    "location": "location",
    "country": "location",
    "city": "location",
    "gender": "gender",
    "email": "email",
    "phone": "phone",
    "website": "url",
    "link": "url",
}
_PHOTO_KEYS = ("image", "avatar", "photo", "profile_image")
_DATE_KEYS = ("created_at", "registered", "joined", "creation_date")


def _local_part(param: str) -> str:
    return param.split("@")[0] if "@" in param else param


def _settings() -> dict:
    top_env = os.environ.get("VEILED_MAIGRET_TOP", "500").strip().lower()
    top = sys.maxsize if top_env == "all" else max(1, int(top_env))
    tags = [
        t.strip()
        for t in os.environ.get("VEILED_MAIGRET_TAGS", "").split(",")
        if t.strip()
    ]
    tor = os.environ.get("TOR_PROXY_URL") or None
    if tor and tor.startswith("socks5h://"):
        tor = "socks5://" + tor[len("socks5h://") :]
    return {
        "top": top,
        "tags": tags,
        "timeout": float(os.environ.get("VEILED_MAIGRET_TIMEOUT", "10")),
        "tor": tor,
    }


def _run_maigret(username: str) -> dict:
    """Run maigret and return its raw ``{site: results_info}`` dict."""
    import maigret
    from maigret.sites import MaigretDatabase

    cfg = _settings()
    db_path = os.path.join(os.path.dirname(maigret.__file__), "resources", "data.json")
    db = MaigretDatabase().load_from_path(db_path)
    sites = db.ranked_sites_dict(
        top=cfg["top"], tags=cfg["tags"], disabled=False, id_type="username"
    )
    mlogger = logging.getLogger("maigret")
    mlogger.setLevel(logging.ERROR)

    coro = maigret.search(
        username=username,
        site_dict=sites,
        logger=mlogger,
        timeout=cfg["timeout"],
        tor_proxy=cfg["tor"],
        is_parsing_enabled=True,
        no_progressbar=True,
        max_connections=50,
        retries=1,
    )
    return asyncio.run(coro)


def _is_claimed(info: dict) -> bool:
    status = info.get("status")
    if status is None:
        return False
    if hasattr(status, "is_found"):
        return bool(status.is_found())
    return str(getattr(status, "status", status)).lower().endswith("claimed")


def _ids(info: dict) -> dict:
    status = info.get("status")
    data = getattr(status, "ids_data", None) or {}
    return data if isinstance(data, dict) else {}


def _tags(info: dict) -> list:
    status = info.get("status")
    return list(getattr(status, "tags", None) or [])


@module_task(module_name="maigret", dev_mode_sleep=10)
def p_maigret(param):
    """Task of Celery that sweeps a username with maigret."""
    username = _local_part(param)
    raw_results = _run_maigret(username)

    found = {site: info for site, info in raw_results.items() if _is_claimed(info)}
    if not found:
        raise Exception("warn: Username not found by maigret")

    gather = [
        root_node(LINK, username, "fas fa-user-astronaut", f"{len(found)} accounts")
    ]
    lists, social, profile, timeline = [], [], [], []
    tag_count: dict[str, int] = {}
    pivots_usernames: set[str] = set()
    pivots_links: set[str] = set()
    linked: dict[tuple[str, str], dict] = {}
    raw_found = []

    for site, info in sorted(found.items(), key=lambda kv: kv[1].get("rank") or 10**9):
        url = info.get("url_user") or ""
        icon = site_icon(site)
        ids = _ids(info)
        tags = _tags(info)
        for tag in tags:
            tag_count[tag] = tag_count.get(tag, 0) + 1

        gather.append(
            {
                "name-node": f"MG-{site}",
                "title": site,
                "subtitle": ", ".join(tags[:3]),
                "icon": icon,
                "link": LINK,
                "help": url,
            }
        )
        lists.append(
            {
                "title": site,
                "subtitle": url,
                "status": info.get("http_status"),
                "rank": info.get("rank"),
                "tags": tags,
                "ids": ids,
            }
        )
        social.append(
            {
                "name": site,
                "url": url,
                "icon": icon,
                "source": "maigret",
                "username": username,
                "category": ",".join(tags),
            }
        )

        # identity data parsed from the profile page
        for key, value in ids.items():
            if value in (None, "", [], {}):
                continue
            pkey = _PROFILE_MAP.get(key)
            if pkey:
                profile.append({pkey: str(value)})
            elif key in _PHOTO_KEYS and str(value).startswith("http"):
                profile.append({"photos": [{"picture": str(value), "title": site}]})
            elif key in _DATE_KEYS:
                timeline.append(
                    {
                        "date": str(value),
                        "action": f"Maigret : account created on {site}",
                        "icon": icon,
                    }
                )
        for u in info.get("ids_usernames", {}) or {}:
            if u and u.lower() != username.lower():
                pivots_usernames.add(u)
        for link in info.get("ids_links", []) or []:
            pivots_links.add(link)
        # cross-check: profiles this page links to (bio, website field...)
        page_values = list(info.get("ids_links", []) or []) + [
            v for v in ids.values() if isinstance(v, str)
        ]
        for platform, handle in profiles_in(page_values):
            linked.setdefault(
                (platform, handle.lower()), {"handle": handle, "from": set()}
            )
            linked[(platform, handle.lower())]["from"].add(site)

        raw_found.append({"site": site, "url": url, "tags": tags, "ids": ids})

    # --- cross-check -----------------------------------------------------
    # Accounts named by the profiles maigret opened (a GitHub bio linking a
    # Twitter handle) are stronger evidence than a bare username hit.
    tasks: list[dict] = []
    cross_rows = []
    for (platform, _key), item in sorted(linked.items()):
        handle = item["handle"]
        sources = sorted(item["from"])
        same = handle.lower() == username.lower()
        social.append(
            {
                "name": platform.capitalize()
                if platform != "twitter"
                else "Twitter / X",
                "url": _profile_url(platform, handle),
                "icon": site_icon(platform),
                "source": "maigret",
                "username": handle,
                "category": "",
                "linked_from": ", ".join(sources),
            }
        )
        cross_rows.append(
            {
                "platform": platform,
                "handle": handle,
                "linked_from": sources,
                "same_handle": same,
            }
        )
        gather.append(
            {
                "name-node": f"MG-x-{platform}-{handle}",
                "title": f"{platform} @{handle}",
                "subtitle": "linked from " + ", ".join(sources[:3]),
                "icon": site_icon(platform),
                "link": LINK,
                "help": _profile_url(platform, handle),
            }
        )
        module = PLATFORM_MODULE.get(platform)
        if module:
            tasks.append({"module": module, "param": handle})
        if not same:
            pivots_usernames.add(handle)
    extra_handles = [
        h for h in sorted(pivots_usernames) if h.lower() != username.lower()
    ]
    for handle in extra_handles[: int(os.environ.get("VEILED_MAIGRET_PIVOTS", "3"))]:
        tasks.append({"module": "maigret", "param": handle})

    profile.insert(0, {"social": social})
    profile.append({"username": username})
    profile.append(
        {
            "presence": [
                {
                    "name": "maigret",
                    "children": [
                        {"name": t, "value": c} for t, c in sorted(tag_count.items())
                    ],
                }
            ]
        }
    )

    graphic = [
        {"maigret": gather},
        {"lists": lists},
        {"tags": tag_count},
        {
            "pivots": {
                "usernames": sorted(pivots_usernames),
                "links": sorted(pivots_links),
            }
        },
        {"crosscheck": cross_rows},
    ]

    return build_total(
        module="maigret",
        param=param,
        validation="soft",
        raw={
            "username": username,
            "checked": len(raw_results),
            "found": raw_found,
            "crosscheck": cross_rows,
        },
        graphic=graphic,
        profile=profile,
        timeline=timeline,
        tasks=tasks,
    )


def _profile_url(platform: str, handle: str) -> str:
    return {
        "twitter": f"https://x.com/{handle}",
        "instagram": f"https://www.instagram.com/{handle}",
        "github": f"https://github.com/{handle}",
        "gitlab": f"https://gitlab.com/{handle}",
        "reddit": f"https://www.reddit.com/user/{handle}",
        "telegram": f"https://t.me/{handle}",
        "tiktok": f"https://www.tiktok.com/@{handle}",
        "youtube": f"https://www.youtube.com/@{handle}",
        "linkedin": f"https://www.linkedin.com/in/{handle}",
        "keybase": f"https://keybase.io/{handle}",
        "bluesky": f"https://bsky.app/profile/{handle}",
        "twitch": f"https://www.twitch.tv/{handle}",
        "steam": f"https://steamcommunity.com/id/{handle}",
        "medium": f"https://medium.com/@{handle}",
    }.get(platform, "")


t_maigret = p_maigret


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="maigret sweep (Veiled Eye module)")
    parser.add_argument("username")
    print(json.dumps(t_maigret(parser.parse_args().username, dev_mode=False), indent=2))
