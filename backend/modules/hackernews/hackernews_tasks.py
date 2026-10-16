#!/usr/bin/env python
"""Hacker News module — profile, about links, activity, interaction graph.

Collector: socmint_tools/hackernews_osint.py (SOCMIntelligence).
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


@module_task(module_name="hackernews", dev_mode_sleep=3)
def p_hackernews(param):
    """Task of Celery that reads a Hacker News user."""
    target = param.split("@")[0] if "@" in param else param
    d = run_tool("hackernews_osint.py", [target, "--items", "300"], timeout=150)
    handle = d.get("username") or target
    activity = d.get("activity") or {}
    extra_nodes = [
        {
            "name-node": f"HN-rep-{u}",
            "title": u,
            "subtitle": f"replied to {c}x",
            "icon": "fas fa-reply",
        }
        for u, c in list((d.get("replied_to") or {}).items())[:10]
    ]
    extra_nodes += [
        {
            "name-node": f"HN-dom-{dom}",
            "title": dom,
            "subtitle": f"submitted {c}x",
            "icon": "fas fa-globe",
        }
        for dom, c in list((d.get("top_domains") or {}).items())[:6]
    ]
    timeline = [
        {
            "date": s["date"],
            "action": f"Hacker News : story '{s.get('title')}'",
            "icon": "fab fa-hacker-news",
        }
        for s in (d.get("stories") or [])[:15]
        if s.get("date")
    ]
    about = d.get("about") or ""
    return assemble_account(
        module="hackernews",
        param=param,
        platform="hackernews",
        handle=handle,
        url=d.get("profile_url"),
        bio=about,
        created=d.get("created"),
        emails=d.get("about_emails") or [],
        socials=d.get("about_socials") or [],
        facts=[
            ("Karma", d.get("karma"), "fas fa-star"),
            ("Submissions", d.get("submitted_total"), "fas fa-stream"),
            (
                "Active",
                " → ".join(
                    x for x in (activity.get("first"), activity.get("last")) if x
                ),
                "fas fa-calendar",
            ),
            (
                "Links in about",
                ", ".join((d.get("about_links") or [])[:4]),
                "fas fa-link",
            ),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[
            {"activity": activity},
            {"replied_to": d.get("replied_to") or {}},
        ],
        timeline=timeline,
        presence=[{"name": "karma", "value": d.get("karma") or 0}],
        raw={k: v for k, v in d.items() if k != "recent_comments"},
        text_for_selectors=about + " " + " ".join(d.get("about_links") or []),
    )


t_hackernews = p_hackernews

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    print(json.dumps(t_hackernews(ap.parse_args().username, dev_mode=False), indent=2))
