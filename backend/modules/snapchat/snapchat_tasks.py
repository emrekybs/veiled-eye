#!/usr/bin/env python
"""Snapchat module — PUBLIC profile page (snapchat.com/add/<user>).

Collector: socmint_tools/snap_osint.py (SOCMIntelligence).  Reads only what
Snapchat publishes on the public profile page (display name, bio, website,
public stories / highlights / spotlights and their timestamps).  Private
accounts are reported as a Warning.
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_snapchat
from factories.task_wrapper import module_task


@module_task(module_name="snapchat", dev_mode_sleep=3)
def p_snapchat(param):
    """Task of Celery that reads a public Snapchat profile."""
    target = (
        param.split("@")[0] if "@" in param and not param.startswith("@") else param
    ).lstrip("@")
    d = run_snapchat(target)
    acc = d.get("account_information") or {}
    ana = d.get("account_analysis") or {}
    snaps = d.get("snap_analytics") or {}
    handle = acc.get("username") or target

    extra_nodes = []
    for rel in (d.get("related_accounts") or [])[:12]:
        name = rel.get("username") if isinstance(rel, dict) else str(rel)
        if name:
            extra_nodes.append(
                {
                    "name-node": f"SC-rel-{name}",
                    "title": f"@{name}",
                    "subtitle": "related account",
                    "icon": "fab fa-snapchat",
                }
            )
    timeline = []
    for s in ((d.get("stories") or {}).get("snaps") or [])[:20]:
        if s.get("upload_date") and s["upload_date"] != "unknown":
            timeline.append(
                {
                    "date": s["upload_date"],
                    "action": "Snapchat : public story",
                    "icon": "fab fa-snapchat",
                }
            )

    website = acc.get("website") or ""
    bio = acc.get("bio") or ""
    return assemble_account(
        module="snapchat",
        param=param,
        platform="snapchat",
        handle=handle,
        url=f"https://www.snapchat.com/add/{handle}",
        name=acc.get("display_name"),
        bio=bio,
        avatar=acc.get("profile_picture"),
        created=ana.get("created_at")
        if ana.get("created_at") not in (None, "unknown")
        else None,
        socials=[],
        facts=[
            ("Public", "Yes" if acc.get("is_public") else "No", "fas fa-eye"),
            ("Subscribers", acc.get("subscriber_count"), "fas fa-users"),
            ("Website", website, "fas fa-globe"),
            (
                "Category",
                " / ".join(
                    x for x in (acc.get("category"), acc.get("subcategory")) if x
                ),
                "fas fa-tag",
            ),
            ("Snaps", snaps.get("total_snaps"), "fas fa-images"),
            (
                "Most active",
                " ".join(
                    str(x)
                    for x in (
                        snaps.get("most_active_day"),
                        snaps.get("most_active_hour"),
                    )
                    if x
                ),
                "fas fa-clock",
            ),
            ("Last active", ana.get("last_active"), "fas fa-calendar-check"),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[
            {
                "activity": {
                    "days": snaps.get("daily_distribution"),
                    "hours": snaps.get("hourly_distribution"),
                }
            },
            {"related_accounts": d.get("related_accounts") or []},
        ],
        timeline=timeline,
        presence=[{"name": "subscribers", "value": acc.get("subscriber_count") or 0}],
        raw={k: v for k, v in d.items() if k not in ("heatmap",)},
        text_for_selectors=bio + " " + website,
    )


t_snapchat = p_snapchat

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    print(json.dumps(t_snapchat(ap.parse_args().username, dev_mode=False), indent=2))
