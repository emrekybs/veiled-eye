#!/usr/bin/env python
"""Stack Exchange module — user profile + network accounts (no key).

Collector: socmint_tools/stackexchange_osint.py (SOCMIntelligence).
A username is searched by display name; only an EXACT display-name match is
accepted (name search alone is too noisy for identity work).  ``site:id`` or a
profile URL are used directly.  ``VEILED_STACKEXCHANGE_SITE`` (default
stackoverflow) selects the site.
"""

import argparse
import json
import os
import re

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


@module_task(module_name="stackexchange", dev_mode_sleep=3)
def p_stackexchange(param):
    """Task of Celery that reads a Stack Exchange user."""
    target = param.split("@")[0] if "@" in param and "/" not in param else param
    site = os.environ.get("VEILED_STACKEXCHANGE_SITE", "stackoverflow")
    d = run_tool("stackexchange_osint.py", [target, "--site", site], timeout=120)

    by_name = not (target.isdigit() or ":" in target or "/" in target)
    if by_name and _norm(d.get("display_name")) != _norm(target):
        names = ", ".join(
            c.get("display_name") or "" for c in (d.get("candidates") or [])[:5]
        )
        raise Exception(f"warn: No exact Stack Exchange match (closest: {names})")

    handle = d.get("display_name") or target
    extra_nodes = [
        {
            "name-node": f"SE-net-{n.get('site')}",
            "title": n.get("site") or "site",
            "subtitle": f"rep {n.get('reputation')}",
            "icon": "fab fa-stack-exchange",
            "help": n.get("link") or "",
        }
        for n in (d.get("network") or [])[:15]
    ]
    tags = ", ".join(t.get("tag") or "" for t in (d.get("top_tags") or [])[:6])
    about = d.get("about") or ""
    activity = d.get("activity") or {}
    return assemble_account(
        module="stackexchange",
        param=param,
        platform="stackexchange",
        handle=handle,
        url=d.get("link"),
        name=d.get("display_name"),
        bio=about,
        location=d.get("location"),
        avatar=d.get("profile_image"),
        created=d.get("created"),
        emails=d.get("about_emails") or [],
        socials=d.get("socials") or [],
        facts=[
            ("Site", d.get("site"), "fab fa-stack-exchange"),
            ("Reputation", d.get("reputation"), "fas fa-star"),
            ("Website", d.get("website"), "fas fa-globe"),
            ("Top tags", tags, "fas fa-tags"),
            ("Last access", d.get("last_access"), "fas fa-clock"),
            ("Network accounts", len(d.get("network") or []) or None, "fas fa-sitemap"),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[{"network": d.get("network") or []}, {"activity": activity}],
        presence=[{"name": "reputation", "value": d.get("reputation") or 0}],
        raw={k: v for k, v in d.items() if k not in ("answers", "questions")},
        validation="hard" if not by_name else "soft",
        text_for_selectors=about
        + " "
        + " ".join(d.get("about_links") or [])
        + " "
        + (d.get("website") or ""),
    )


t_stackexchange = p_stackexchange

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    print(json.dumps(t_stackexchange(ap.parse_args().target, dev_mode=False), indent=2))
