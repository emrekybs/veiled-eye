#!/usr/bin/env python
"""Telegram module — public t.me card + channel preview (no API key).

Collector: socmint_tools/telegram_osint.py (SOCMIntelligence).
"""

import argparse
import json
import os

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task

KIND = {"channel": "Channel", "group": "Group", "user": "User", "bot": "Bot"}


def _handle(param: str) -> str:
    return (
        param.split("@")[0]
        if "@" in param and not param.startswith("@")
        else param.lstrip("@")
    )


@module_task(module_name="telegram", dev_mode_sleep=3)
def p_telegram(param):
    """Task of Celery that reads a public Telegram profile / channel."""
    pages = os.environ.get("VEILED_TELEGRAM_PAGES", "3")
    d = run_tool("telegram_osint.py", [_handle(param), "--pages", pages], timeout=120)
    a = d.get("analysis") or {}
    handle = d.get("username") or _handle(param)

    extra_nodes = []
    for src, cnt in list((a.get("top_forward_sources") or {}).items())[:10]:
        if src and src != "?":
            extra_nodes.append(
                {
                    "name-node": f"TG-fwd-{src}",
                    "title": f"@{src}",
                    "subtitle": f"forwarded {cnt}x",
                    "icon": "fas fa-share",
                }
            )
    for mention in (d.get("description_mentions") or [])[:10]:
        extra_nodes.append(
            {
                "name-node": f"TG-men-{mention}",
                "title": f"@{mention}",
                "subtitle": "mentioned in bio",
                "icon": "fas fa-at",
            }
        )

    timeline = []
    for post in (d.get("posts") or [])[:15]:
        if post.get("date"):
            timeline.append(
                {
                    "date": str(post["date"]),
                    "action": f"Telegram : post in @{handle}",
                    "icon": "fab fa-telegram",
                    "desc": str(post.get("text") or "")[:160],
                }
            )

    desc = d.get("description") or ""
    return assemble_account(
        module="telegram",
        param=param,
        platform="telegram",
        handle=handle,
        url=d.get("url"),
        name=d.get("title"),
        bio=desc,
        avatar=d.get("photo"),
        emails=d.get("description_emails") or [],
        socials=d.get("description_socials") or [],
        facts=[
            ("Type", KIND.get(d.get("kind"), d.get("kind")), "fab fa-telegram"),
            ("Subscribers", d.get("subscribers"), "fas fa-users"),
            ("Verified", "Yes" if d.get("verified") else None, "fas fa-check-circle"),
            ("Posts analysed", a.get("posts_analyzed") or None, "fas fa-stream"),
            ("First post", a.get("first_post"), "fas fa-calendar"),
            ("Last post", a.get("last_post"), "fas fa-calendar-check"),
            (
                "Top domains",
                ", ".join(list((a.get("top_domains") or {}).keys())[:5]),
                "fas fa-globe",
            ),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[{"analysis": a}],
        timeline=timeline,
        presence=[{"name": "subscribers", "value": d.get("subscribers") or 0}],
        raw={k: v for k, v in d.items() if k != "posts"},
        text_for_selectors=desc + " " + " ".join(d.get("description_links") or []),
    )


t_telegram = p_telegram

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    print(json.dumps(t_telegram(ap.parse_args().username, dev_mode=False), indent=2))
