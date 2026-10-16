#!/usr/bin/env python
"""Wayback Machine module — archived copies of a person's profiles.

Collector: socmint_tools/wayback_osint.py (SOCMIntelligence: CDX API +
content of the first / last archived copies).

* **username** -> the profile URL of the handle on the big platforms is
  looked up in the archive; old page titles / descriptions reveal former
  display names and bios, old links reveal accounts that were later removed.
* **domain / URL** -> archived history of that page or site.
* **e-mail** -> treated as its local-part (username).

``VEILED_WAYBACK_PLATFORMS`` restricts the platform list (comma separated).
"""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from factories.identity import socials_to_profile, socials_to_tasks
from factories.output_builder import build_total, root_node
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task

PROFILE_URLS = {
    "twitter": "twitter.com/{u}",
    "instagram": "instagram.com/{u}",
    "tiktok": "tiktok.com/@{u}",
    "github": "github.com/{u}",
    "reddit": "reddit.com/user/{u}",
    "telegram": "t.me/{u}",
    "facebook": "facebook.com/{u}",
    "youtube": "youtube.com/@{u}",
    "linkedin": "linkedin.com/in/{u}",
    "medium": "medium.com/@{u}",
}


def targets_for(param: str) -> list[tuple[str, str]]:
    value = param.strip()
    if "@" in value and "/" not in value:
        value = value.split("@")[0]
    bare = re.sub(r"^https?://", "", value, flags=re.I)
    if "." in bare and re.match(r"^[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/.*)?$", bare):
        return [("site", bare)]
    wanted = [
        p.strip()
        for p in os.environ.get(
            "VEILED_WAYBACK_PLATFORMS", ",".join(PROFILE_URLS)
        ).split(",")
        if p.strip() in PROFILE_URLS
    ]
    return [(p, PROFILE_URLS[p].format(u=value.lstrip("@"))) for p in wanted]


_GENERIC_TITLE = re.compile(
    r"log ?in|sign ?up|not found|page|error|blocked|just a moment|attention required|"
    r"twitter|instagram|facebook|linkedin|tiktok|reddit|github|youtube|telegram|medium|^x$",
    re.I,
)


def _name_from_title(title: str, platform: str) -> str | None:
    """'John Doe (@jdoe) / Twitter' -> 'John Doe' (None for login walls etc.)."""
    if platform == "site":
        return None
    name = re.split(r"\s+[(@|\u2022\u00b7\-\u2013]|\s+on\s+", title)[0].strip(" -|·")
    if not name or len(name) > 60 or _GENERIC_TITLE.search(name):
        return None
    return name


def _lookup(item: tuple[str, str]) -> tuple[str, str, dict | None, str | None]:
    platform, url = item
    try:
        return (
            platform,
            url,
            run_tool("wayback_osint.py", [url, "--snapshots", "2"], timeout=150),
            None,
        )
    except Exception as exc:  # not archived / rate limited
        return platform, url, None, str(exc).replace("warn: ", "")


@module_task(module_name="wayback", dev_mode_sleep=3)
def p_wayback(param):
    """Task of Celery that mines archived profile pages."""
    items = targets_for(param)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_lookup, items))
    found = [(p, u, d) for p, u, d, _ in results if d]
    if not found:
        errors = {e for *_, e in results if e}
        if any("rate" in (e or "").lower() or "429" in (e or "") for e in errors):
            raise Exception("warn: Wayback Machine rate limited, try again later")
        raise Exception("warn: No archived copies found")

    gather = [
        root_node("Wayback", param, "fas fa-history", f"{len(found)} archived pages")
    ]
    profile, timeline, socials, lists = [], [], [], []
    for platform, url, d in found:
        gather.append(
            {
                "name-node": f"WB-{platform}",
                "title": platform.title() if platform != "site" else d.get("target"),
                "subtitle": f"{d.get('total_captures')} captures · {d.get('first_capture')} → {d.get('last_capture')}",
                "icon": "fas fa-archive",
                "link": "Wayback",
                "help": d.get("last_capture_url") or "",
            }
        )
        lists.append(
            {
                "platform": platform,
                "url": url,
                "captures": d.get("total_captures"),
                "first": d.get("first_capture"),
                "last": d.get("last_capture"),
                "first_url": d.get("first_capture_url"),
                "last_url": d.get("last_capture_url"),
                "snapshots": d.get("snapshots") or [],
            }
        )
        if d.get("first_capture"):
            timeline.append(
                {
                    "date": d["first_capture"],
                    "action": f"Wayback : first archived copy of {url}",
                    "icon": "fas fa-history",
                }
            )
        for snap in d.get("snapshots") or []:
            title = (snap.get("title") or "").strip()
            if title:
                timeline.append(
                    {
                        "date": snap.get("date"),
                        "action": f"Wayback : '{title[:120]}'",
                        "icon": "fas fa-archive",
                        "desc": (snap.get("description") or "")[:200],
                    }
                )
                name = _name_from_title(title, platform)
                if name:
                    profile.append({"name": name})
            if snap.get("description") and platform != "site":
                profile.append({"bio": snap["description"][:500]})
        for email in d.get("emails") or []:
            profile.append({"email": email})
        socials.extend(d.get("socials") or [])

    profile.insert(0, {"social": socials_to_profile(socials, "wayback")})
    graphic = [{"wayback": gather}, {"lists": lists}]
    return build_total(
        module="wayback",
        param=param,
        validation="soft",
        raw={"targets": [u for _, u in items], "found": [u for _, u, _ in found]},
        graphic=graphic,
        profile=profile,
        timeline=timeline,
        tasks=socials_to_tasks(socials),
    )


t_wayback = p_wayback

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    print(json.dumps(t_wayback(ap.parse_args().target, dev_mode=False), indent=2))
