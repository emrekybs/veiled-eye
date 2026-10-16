#!/usr/bin/env python
"""Gravatar module — profile behind an e-mail hash (or Gravatar username).

Collector: socmint_tools/gravatar_osint.py (SOCMIntelligence).  Gravatar
profiles often expose verified accounts, links, crypto wallets and phones.
"""

import argparse
import json

from factories.module_kit import assemble_account
from factories.socmint_runner import run_tool
from factories.task_wrapper import module_task


@module_task(module_name="gravatar", dev_mode_sleep=2)
def p_gravatar(param):
    """Task of Celery that resolves a Gravatar profile."""
    d = run_tool("gravatar_osint.py", [param.strip()], timeout=60)
    handle = d.get("username") or (param.split("@")[0] if "@" in param else param)

    socials = list(d.get("socials") or [])
    extra_nodes = []
    for acc in d.get("accounts") or []:
        plat = str(acc.get("type") or acc.get("service") or "").lower()
        if acc.get("username") and plat:
            socials.append(
                {"platform": plat, "handle": acc["username"], "url": acc.get("url")}
            )
        extra_nodes.append(
            {
                "name-node": f"GR-acc-{plat}-{acc.get('username') or acc.get('url')}",
                "title": plat.title() or "Account",
                "subtitle": acc.get("username") or acc.get("url") or "",
                "icon": "fas fa-check-circle" if acc.get("verified") else "fas fa-link",
                "help": acc.get("url") or "",
            }
        )
    for link in d.get("links") or []:
        if link.get("url"):
            extra_nodes.append(
                {
                    "name-node": f"GR-link-{link['url']}",
                    "title": link.get("title") or "Link",
                    "subtitle": link["url"],
                    "icon": "fas fa-globe",
                }
            )

    out = assemble_account(
        module="gravatar",
        param=param,
        platform="gravatar",
        handle=handle,
        url=d.get("profile_url"),
        name=d.get("display_name") or d.get("name"),
        bio=d.get("about"),
        location=d.get("location"),
        avatar=d.get("avatar_url") if d.get("has_avatar") else None,
        created=d.get("registration_date"),
        emails=[e for e in (d.get("emails") or []) if e != d.get("email")],
        socials=socials,
        facts=[
            ("Avatar", "custom" if d.get("has_avatar") else None, "fas fa-image"),
            (
                "Job",
                " @ ".join(x for x in (d.get("job_title"), d.get("company")) if x),
                "fas fa-briefcase",
            ),
            ("Pronouns", d.get("pronouns"), "fas fa-user"),
            ("Timezone", d.get("timezone"), "fas fa-clock"),
            ("MD5", d.get("md5"), "fas fa-hashtag"),
        ],
        extra_nodes=extra_nodes,
        raw=d,
        text_for_selectors=" ".join(
            [d.get("about") or ""]
            + [c.get("address") or "" for c in d.get("crypto") or []]
            + list(d.get("phones") or [])
        ),
    )
    # Gravatar lists organisation + phones explicitly
    profile = next(item["profile"] for item in out if "profile" in item)
    if d.get("company"):
        profile.append({"organization": d["company"]})
    return out


t_gravatar = p_gravatar

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    print(json.dumps(t_gravatar(ap.parse_args().target, dev_mode=False), indent=2))
