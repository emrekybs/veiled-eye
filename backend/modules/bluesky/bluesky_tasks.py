#!/usr/bin/env python
"""Bluesky module — AT Protocol public profile + recent posts (no login).

Collector: socmint_tools/bluesky_osint.py (SOCMIntelligence).  A bare
username is tried as ``<username>.bsky.social``; custom-domain handles
(``name.dev``) and DIDs are used as given.
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


def actor_for(param: str) -> str:
    value = param.strip().lstrip("@")
    if "@" in value:  # e-mail -> local part
        value = value.split("@")[0]
    if value.startswith("did:") or "." in value:
        return value
    return f"{value}.bsky.social"


@module_task(module_name="bluesky", dev_mode_sleep=3)
def p_bluesky(param):
    """Task of Celery that reads a public Bluesky profile."""
    d = run_tool("bluesky_osint.py", [actor_for(param), "--posts", "100"], timeout=120)
    handle = d.get("handle") or actor_for(param)
    mentions = d.get("mentions") or []
    extra_nodes = []
    for m in mentions[:12]:
        h = m.get("handle") if isinstance(m, dict) else str(m)
        if h:
            extra_nodes.append(
                {
                    "name-node": f"BS-men-{h}",
                    "title": f"@{h}",
                    "subtitle": f"mentioned {m.get('count', '') if isinstance(m, dict) else ''}x",
                    "icon": "fas fa-at",
                }
            )
    for dom in (d.get("domains") or [])[:8]:
        extra_nodes.append(
            {
                "name-node": f"BS-dom-{dom['domain']}",
                "title": dom["domain"],
                "subtitle": f"linked {dom['count']}x",
                "icon": "fas fa-globe",
            }
        )
    desc = d.get("description") or ""
    return assemble_account(
        module="bluesky",
        param=param,
        platform="bluesky",
        handle=handle,
        url=d.get("url"),
        name=d.get("display_name"),
        bio=desc,
        avatar=d.get("avatar"),
        created=d.get("created_at"),
        emails=d.get("emails") or [],
        socials=[],
        facts=[
            ("DID", d.get("did"), "fas fa-fingerprint"),
            ("Followers", d.get("followers"), "fas fa-users"),
            ("Following", d.get("following"), "fas fa-user-plus"),
            ("Posts", d.get("posts_count"), "fas fa-stream"),
            ("Self-hosted PDS", d.get("pds"), "fas fa-server"),
            (
                "Languages",
                ", ".join(x["lang"] for x in (d.get("languages") or [])[:4]),
                "fas fa-language",
            ),
            (
                "Active",
                " → ".join(x for x in (d.get("first_post"), d.get("last_post")) if x),
                "fas fa-calendar",
            ),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[
            {
                "activity": {
                    "hours": d.get("hour_distribution"),
                    "days": d.get("day_distribution"),
                }
            },
            {"hashtags": d.get("hashtags") or []},
        ],
        presence=[
            {"name": "followers", "value": d.get("followers") or 0},
            {"name": "following", "value": d.get("following") or 0},
        ],
        raw={k: v for k, v in d.items() if k != "posts"},
        validation="hard" if "." in param or param.startswith("did:") else "soft",
        text_for_selectors=desc,
    )


t_bluesky = p_bluesky

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("handle")
    print(json.dumps(t_bluesky(ap.parse_args().handle, dev_mode=False), indent=2))
