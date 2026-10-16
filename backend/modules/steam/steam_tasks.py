#!/usr/bin/env python
"""Steam module — public community profile (XML), aliases, groups, friends.

Collector: socmint_tools/steam_osint.py (SOCMIntelligence).  Works keyless;
``STEAM_API_KEY`` (optional) adds bans, level, games and full friend list.
Name history (``aliases``) is a strong identity pivot.
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


@module_task(module_name="steam", dev_mode_sleep=3)
def p_steam(param):
    """Task of Celery that reads a Steam community profile."""
    target = param.split("@")[0] if "@" in param else param
    d = run_tool("steam_osint.py", [target], timeout=120)
    handle = d.get("custom_url") or target

    aliases = [
        a.get("newname") or a.get("name")
        for a in d.get("aliases") or []
        if isinstance(a, dict)
    ]
    aliases = [a for a in aliases if a]
    extra_nodes = [
        {
            "name-node": f"ST-alias-{i}",
            "title": alias,
            "subtitle": "previous name",
            "icon": "fas fa-history",
        }
        for i, alias in enumerate(dict.fromkeys(aliases))
    ][:15]
    for g in (d.get("groups") or [])[:10]:
        extra_nodes.append(
            {
                "name-node": f"ST-grp-{g.get('id')}",
                "title": g.get("name") or g.get("url") or "Group",
                "subtitle": f"group · {g.get('members') or '?'} members",
                "icon": "fas fa-users",
            }
        )
    bans = d.get("bans") or {}
    out = assemble_account(
        module="steam",
        param=param,
        platform="steam",
        handle=handle,
        url=d.get("profile_url"),
        name=d.get("real_name") or d.get("persona"),
        bio=d.get("summary"),
        location=d.get("location") or d.get("country"),
        avatar=d.get("avatar"),
        created=d.get("time_created") or d.get("member_since"),
        emails=d.get("summary_emails") or [],
        socials=d.get("summary_socials") or [],
        facts=[
            ("Persona", d.get("persona"), "fab fa-steam"),
            ("SteamID64", d.get("steamid"), "fas fa-id-card"),
            ("Privacy", d.get("privacy") or d.get("visibility"), "fas fa-lock"),
            (
                "VAC banned",
                "Yes" if d.get("vac_banned") or bans.get("vac") else None,
                "fas fa-ban",
            ),
            ("Level", d.get("level"), "fas fa-level-up-alt"),
            ("Friends", len(d.get("friends") or []) or None, "fas fa-user-friends"),
            (
                "Most played",
                ", ".join(
                    g.get("name") or "" for g in (d.get("most_played") or [])[:3]
                ),
                "fas fa-gamepad",
            ),
        ],
        extra_nodes=extra_nodes,
        extra_graphic=[
            {"aliases": aliases},
            {"groups": d.get("groups") or []},
            {"friends": d.get("friends") or []},
        ],
        timeline=[
            {
                "date": str(a["changed"]),
                "action": f"Steam : name changed to '{a.get('name')}'",
                "icon": "fab fa-steam",
            }
            for a in d.get("aliases") or []
            if isinstance(a, dict) and a.get("changed")
        ],
        presence=[
            {"name": "friends", "value": len(d.get("friends") or [])},
            {"name": "groups", "value": len(d.get("groups") or [])},
        ],
        raw=d,
        text_for_selectors=(d.get("summary") or "")
        + " "
        + " ".join(d.get("summary_links") or []),
    )
    profile = next(item["profile"] for item in out if "profile" in item)
    for alias in dict.fromkeys(aliases):
        profile.append({"username": alias})
    return out


t_steam = p_steam

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    print(json.dumps(t_steam(ap.parse_args().target, dev_mode=False), indent=2))
