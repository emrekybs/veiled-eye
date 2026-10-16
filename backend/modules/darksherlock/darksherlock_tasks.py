#!/usr/bin/env python
"""Dark-Sherlock module — username presence on cybercrime forums.

Port of banaxou/dark-sherlock (MIT): the tool's core is a lookup against the
threatactorusernames.com search API, which indexes handles seen on
underground / cybercrime forums.  The X and GitHub checks of the original
are intentionally left out because Veiled Eye already has dedicated modules for
both (and ``crossref`` correlates them).
"""

import argparse
import json
from urllib.parse import quote

import requests
from celery.utils.log import get_task_logger
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

logger = get_task_logger(__name__)

API_URL = "https://threatactorusernames.com/api/search?q={}"
LINK = "DarkSherlock"


def _local_part(param: str) -> str:
    return param.split("@")[0] if "@" in param else param


def _query(username: str) -> list[dict]:
    resp = requests.get(
        API_URL.format(quote(username, safe="")),
        headers={"User-Agent": "VeiledEye-OSINT"},
        timeout=20,
    )
    if resp.status_code == 429:
        raise Exception("warn: Rate limited by threatactorusernames.com")
    if resp.status_code != 200:
        raise Exception(f"warn: threatactorusernames.com error ({resp.status_code})")
    try:
        data = resp.json()
    except ValueError as exc:
        raise Exception("warn: Invalid response from threatactorusernames.com") from exc
    results = data.get("results", []) if isinstance(data, dict) else []
    return [r for r in results if isinstance(r, dict)]


def _forum(item: dict) -> str:
    return str(item.get("forum") or item.get("source") or "Unknown")


@module_task(module_name="darksherlock", dev_mode_sleep=3)
def p_darksherlock(param):
    """Task of Celery that looks a handle up on cybercrime-forum indexes."""
    username = _local_part(param)
    hits = _query(username)
    if not hits:
        raise Exception("warn: Username not seen on indexed cybercrime forums")

    gather = [root_node(LINK, username, "fas fa-user-secret", "Cybercrime forums")]
    lists, social, timeline = [], [], []
    forums: dict[str, int] = {}

    for idx, item in enumerate(hits):
        forum = _forum(item)
        forums[forum] = forums.get(forum, 0) + 1
        handle = str(item.get("username") or item.get("name") or username)
        url = item.get("url") or item.get("link") or ""
        date = item.get("date") or item.get("first_seen") or item.get("last_seen") or ""
        gather.append(
            {
                "name-node": f"DS-{idx}",
                "title": forum,
                "subtitle": handle,
                "icon": "fas fa-user-secret",
                "link": LINK,
                "help": url or f"{handle} @ {forum}",
            }
        )
        lists.append({"title": forum, "subtitle": handle, "url": url, "date": date})
        social.append(
            {
                "name": forum,
                "url": url,
                "icon": "fas fa-user-secret",
                "source": "darksherlock",
                "username": handle,
            }
        )
        if date:
            timeline.append(
                {
                    "date": str(date),
                    "action": f"DarkSherlock : {handle} seen on {forum}",
                    "icon": "fas fa-user-secret",
                }
            )

    profile = [
        {"social": social},
        {"username": username},
        {
            "presence": [
                {
                    "name": "darksherlock",
                    "children": [{"name": f, "value": c} for f, c in forums.items()],
                }
            ]
        },
    ]
    graphic = [{"darksherlock": gather}, {"lists": lists}, {"forums": forums}]

    return build_total(
        module="darksherlock",
        param=param,
        validation="soft",
        raw={"username": username, "results": hits},
        graphic=graphic,
        profile=profile,
        timeline=timeline,
    )


t_darksherlock = p_darksherlock


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dark-Sherlock lookup")
    parser.add_argument("username")
    print(
        json.dumps(
            t_darksherlock(parser.parse_args().username, dev_mode=False), indent=2
        )
    )
