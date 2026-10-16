#!/usr/bin/env python
"""Kick module — public streamer channel (v2 public API, no login).

Collector: socmint_tools/kick_osint.py (SOCMIntelligence).  Kick sits behind
Cloudflare; a block is reported as a Warning, not a failure.
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


@module_task(module_name="kick", dev_mode_sleep=2)
def p_kick(param):
    """Task of Celery that reads a public Kick channel."""
    target = param.split("@")[0] if "@" in param else param
    d = run_tool("kick_osint.py", [target], timeout=60)
    handle = d.get("slug") or target
    declared = d.get("declared_socials") or {}
    socials = list(d.get("socials") or [])
    for plat, value in declared.items():
        value = str(value).strip().rstrip("/").split("/")[-1].lstrip("@")
        if value and not any(s.get("platform") == plat for s in socials):
            socials.append({"platform": plat, "handle": value, "url": None})
    stream = d.get("stream") or {}
    bio = d.get("bio") or ""
    return assemble_account(
        module="kick",
        param=param,
        platform="kick",
        handle=handle,
        url=d.get("url"),
        name=d.get("username"),
        bio=bio,
        avatar=d.get("profile_pic"),
        emails=d.get("emails") or [],
        socials=socials,
        facts=[
            ("Followers", d.get("followers"), "fas fa-users"),
            ("Verified", "Yes" if d.get("verified") else None, "fas fa-check-circle"),
            ("Banned", "Yes" if d.get("is_banned") else None, "fas fa-ban"),
            (
                "Live now",
                stream.get("title") if d.get("live") else None,
                "fas fa-broadcast-tower",
            ),
            (
                "Categories",
                ", ".join((d.get("recent_categories") or [])[:5]),
                "fas fa-gamepad",
            ),
        ],
        presence=[{"name": "followers", "value": d.get("followers") or 0}],
        raw=d,
        text_for_selectors=bio,
    )


t_kick = p_kick

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    print(json.dumps(t_kick(ap.parse_args().username, dev_mode=False), indent=2))
