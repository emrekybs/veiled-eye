#!/usr/bin/env python
"""Crossref module — cross-source correlation of everything Veiled Eye collected.

Every ``@module_task`` module stores its output in the result cache
(``factories/result_cache.py``).  Crossref reads those outputs for the target
(and for the selectors discovered on the way — local-part, e-mails found by
GitSniff/GitHub, handles found by maigret...), then:

* **accounts**   — merges every platform account reported by any module
  (maigret, user-scanner, dark-sherlock, sherlock-like modules, social
  modules...) by ``(platform, handle)``, counts how many *independent* sources
  confirm it and grades it ``confirmed / likely / candidate`` (user-scanner's
  own metadata rating is honoured).
* **identity**   — names, e-mails, locations, organisations and photos voted by
  source, so the most corroborated value of each attribute surfaces first.
* **exposure**   — which discovered e-mails / handles also show up in leak,
  infostealer (Hudson Rock) or cybercrime-forum (dark-sherlock) results.
* **org match**  — when CrossLinked enumerated the target's organisation, any
  employee whose name matches the identity is flagged.

It never re-runs a module.  Modules still running are awaited up to
``VEILED_CROSSREF_WAIT`` seconds (default 60).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict

from celery.utils.log import get_task_logger
from factories import chain, insights, result_cache
from factories.avatar import match_avatars
from factories.chain import company_from_domain, is_email
from factories.identity import selector_type
from factories.output_builder import build_total, root_node, site_icon
from factories.task_wrapper import module_task

logger = get_task_logger(__name__)

LINK = "Crossref"

# Modules that only speak about e-mail addresses
EMAIL_SOURCES = (
    "userscanner",
    "holehe",
    "socialscan",
    "emailrep",
    "leaks",
    "leaklookup",
    "hudsonrock",
    "peopledatalabs",
    "gravatar",
    "pgp",
    "ahmia",
    "darkweb",
)
# Modules that take a username / handle
USERNAME_SOURCES = (
    "maigret",
    "userscanner",
    "darksherlock",
    "gitsniff",
    "github",
    "gitlab",
    "keybase",
    "reddit",
    "twitter",
    "instagram",
    "tiktok",
    "mastodon",
    "twitch",
    "spotify",
    "youtube",
    "linkedin",
    "hudsonrock",
    "venmo",
    "tinder",
    "usersearch",
    "whatsmyname",
    "telegram",
    "steam",
    "bluesky",
    "hackernews",
    "stackexchange",
    "kick",
    "snapchat",
    "wayback",
    "pgp",
    "ahmia",
    "darkweb",
    "gravatar",
)
EXPOSURE_SOURCES = {
    "leaks",
    "leaklookup",
    "hudsonrock",
    "darksherlock",
    "ahmia",
    "darkweb",
}

_GRADES = ("confirmed", "likely", "candidate")
_PLATFORM_ALIASES = {
    "x": "twitter",
    "x | twitter": "twitter",
    "twitter / x": "twitter",
    "x / twitter": "twitter",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "reddit.com": "reddit",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
}


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------
def norm_platform(name: str) -> str:
    value = re.sub(r"^linkedin - .*", "linkedin", str(name or "").strip().lower())
    value = _PLATFORM_ALIASES.get(value, value)
    value = re.sub(r"^(www\.)", "", value)
    value = re.sub(r"\.(com|net|org|io|me|tv|gg|co)$", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def norm_handle(handle: str) -> str:
    return str(handle or "").strip().lstrip("@").lower()


def section(result: list, key: str):
    if not isinstance(result, list):
        return None
    for item in result:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def is_error(result) -> bool:
    raw = section(result, "raw")
    return (
        isinstance(raw, list)
        and bool(raw)
        and isinstance(raw[0], dict)
        and raw[0].get("status") in ("Fail", "Warning")
    )


def grade(sources: set[str], hint: str | None = None) -> str:
    n = len(sources)
    if hint == "conflicting":
        return "candidate"
    if n >= 3 or (hint == "confirmed" and n >= 1):
        return "confirmed"
    if n == 2 or hint == "likely":
        return "likely"
    return "candidate"


def _userscanner_hints(result) -> dict[tuple[str, str], str]:
    """(platform, handle) -> user-scanner confidence from its lists."""
    hints = {}
    for item in section(result, "graphic") or []:
        if isinstance(item, dict) and isinstance(item.get("lists"), list):
            for row in item["lists"]:
                key = (
                    norm_platform(row.get("title")),
                    norm_handle(row.get("subtitle")),
                )
                hints[key] = str(row.get("confidence") or "")
    return hints


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _wait_and_fetch(
    pairs: list[tuple[str, str]], wait: float
) -> dict[tuple[str, str], list]:
    """Fetch cached outputs; wait for the ones still RUNNING."""
    deadline = time.monotonic() + wait
    out: dict[tuple[str, str], list] = {}
    pending = list(pairs)
    while pending:
        still = []
        for module, param in pending:
            st = result_cache.state(module, param)
            if st == "DONE":
                res = result_cache.fetch(module, param)
                if res is not None:
                    out[(module, param)] = res
            elif st == "RUNNING":
                still.append((module, param))
        if not still or time.monotonic() >= deadline:
            break
        pending = still
        time.sleep(2)
    return out


def collect(param: str, wait: float) -> dict[tuple[str, str], list]:
    """Gather sibling outputs for the target and one hop of pivots."""
    seeds = {param}
    if is_email(param):
        seeds.add(param.split("@")[0])
        domain = param.split("@")[-1].lower()
        if company_from_domain(domain):
            seeds.add(domain)

    def pairs_for(values) -> list[tuple[str, str]]:
        pairs = []
        for v in values:
            kind = selector_type(v)
            if kind == "phone":
                mods = ("phone",)
            elif kind == "wallet":
                mods = ("crypto",)
            elif kind == "domain":
                mods = ("crosslinked", "wayback", "pgp")
            elif kind == "email":
                mods = EMAIL_SOURCES
            else:
                mods = USERNAME_SOURCES
            pairs += [(m, v) for m in mods]
            if "." in v and kind == "username":
                pairs.append(("crosslinked", v))
        return pairs

    collected = _wait_and_fetch(pairs_for(seeds), wait)

    # one hop: e-mails / handles discovered by the first round
    hop: set[str] = set()
    for res in collected.values():
        for entry in section(res, "profile") or []:
            if isinstance(entry, dict):
                if entry.get("email"):
                    hop.add(str(entry["email"]).lower())
                if entry.get("username"):
                    hop.add(str(entry["username"]))
    hop -= seeds
    if hop:
        collected.update(_wait_and_fetch(pairs_for(sorted(hop)[:25]), 0))

    # pivots whose params are derived (phone / wallet lists, gitsniff,
    # crosslinked...): ask the chain rules and the results' own tasks
    for _ in range(2):
        derived = set()
        for res in list(collected.values()):
            tasks = chain.next_tasks(res)
            for item in res if isinstance(res, list) else []:
                if isinstance(item, dict) and isinstance(item.get("tasks"), list):
                    tasks += [t for t in item["tasks"] if isinstance(t, dict)]
            for t in tasks:
                key = (t.get("module"), t.get("param"))
                if key[0] and key[1] and key[0] != "crossref" and key not in collected:
                    derived.add(key)
        if not derived:
            break
        collected.update(_wait_and_fetch(sorted(derived), 0))
    return collected


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------
def correlate(param: str, collected: dict[tuple[str, str], list]) -> dict:
    accounts: dict[tuple[str, str], dict] = {}
    identity: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    photos: dict[str, set[str]] = defaultdict(set)
    photo_items: list[dict] = []
    hints: dict[tuple[str, str], str] = {}
    exposure: dict[str, set[str]] = defaultdict(set)
    sources_ok, sources_err = set(), set()
    employees: list[dict] = []

    for (module, mparam), res in collected.items():
        if is_error(res):
            sources_err.add(module)
            continue
        sources_ok.add(module)
        if module == "userscanner":
            hints.update(_userscanner_hints(res))
        if module in EXPOSURE_SOURCES:
            raw = section(res, "raw")
            empty_darkweb = module == "darkweb" and not raw  # darkweb: no hits
            if not empty_darkweb:
                exposure[module].add(str(mparam).lower())
        if module == "crosslinked":
            for item in section(res, "graphic") or []:
                if isinstance(item, dict) and isinstance(item.get("lists"), list):
                    employees.extend(item["lists"])

        for entry in section(res, "profile") or []:
            if not isinstance(entry, dict):
                continue
            for social in entry.get("social") or []:
                if not isinstance(social, dict):
                    continue
                platform = norm_platform(social.get("name") or social.get("source"))
                handle = norm_handle(social.get("username") or mparam)
                if module == "crosslinked" or not platform:
                    continue
                acc = accounts.setdefault(
                    (platform, handle),
                    {
                        "platform": social.get("name") or platform,
                        "handle": handle,
                        "urls": set(),
                        "sources": set(),
                        "icon": social.get("icon") or site_icon(platform),
                    },
                )
                acc["sources"].add(module)
                if social.get("url"):
                    acc["urls"].add(str(social["url"]))
            for wallet in (
                entry.get("wallet") or []
                if isinstance(entry.get("wallet"), list)
                else []
            ):
                if isinstance(wallet, dict) and wallet.get("address"):
                    identity["wallet"][wallet["address"]].add(module)
            for key in (
                "name",
                "email",
                "phone",
                "location",
                "organization",
                "username",
                "url",
                "bio",
            ):
                value = entry.get(key)
                if isinstance(value, str) and value.strip() and module != "crosslinked":
                    identity[key][value.strip()].add(module)
                elif key == "organization" and isinstance(value, list):
                    for org in value:
                        if isinstance(org, dict) and org.get("name"):
                            identity[key][org["name"]].add(module)
            for photo in entry.get("photos") or []:
                if isinstance(photo, dict) and photo.get("picture"):
                    photos[photo["picture"]].add(module)
                    platform = norm_platform(photo.get("title") or module)
                    photo_items.append(
                        {
                            "picture": photo["picture"],
                            "account": (platform, norm_handle(mparam)),
                            "module": module,
                        }
                    )

    # --- avatar re-use (perceptual hash) ---------------------------------
    avatar_matches: list[dict] = []
    if os.environ.get("VEILED_AVATAR_HASH", "1") != "0" and len(photo_items) > 1:
        try:
            avatar_matches = match_avatars(photo_items)
        except Exception as exc:  # never let image work break correlation
            logger.warning(f"avatar hashing failed: {exc}")
    avatar_accounts = {tuple(a) for m in avatar_matches for a in m["accounts"]}

    # --- accounts --------------------------------------------------------
    account_rows = []
    for (platform, handle), acc in accounts.items():
        avatar = (platform, handle) in avatar_accounts
        g = grade(acc["sources"], hints.get((platform, handle)))
        if avatar and g == "candidate":
            g = "likely"  # same picture as another account of the target
        account_rows.append(
            {
                "platform": acc["platform"],
                "handle": handle,
                "urls": sorted(acc["urls"]),
                "sources": sorted(acc["sources"]),
                "score": len(acc["sources"]),
                "confidence": g,
                "icon": acc["icon"],
                "underground": "darksherlock" in acc["sources"],
                "avatar_match": avatar,
            }
        )
    account_rows.sort(
        key=lambda r: (_GRADES.index(r["confidence"]), -r["score"], r["platform"])
    )

    # --- identity consensus ---------------------------------------------
    identity_rows = {
        key: sorted(
            (
                {"value": v, "sources": sorted(s), "score": len(s)}
                for v, s in values.items()
            ),
            key=lambda r: -r["score"],
        )
        for key, values in identity.items()
    }

    # --- handle reuse ------------------------------------------------------
    reuse: dict[str, set[str]] = defaultdict(set)
    for row in account_rows:
        reuse[row["handle"]].add(norm_platform(row["platform"]))
    reuse_rows = sorted(
        ({"handle": h, "platforms": len(p)} for h, p in reuse.items() if h),
        key=lambda r: -r["platforms"],
    )

    # --- exposure ------------------------------------------------------------
    exposure_rows = [
        {"source": src, "selectors": sorted(values)}
        for src, values in sorted(exposure.items())
    ]

    # --- employee match --------------------------------------------------------
    known_names = {n.lower() for n in identity.get("name", {})}
    org_matches = [
        e for e in employees if str(e.get("title", "")).lower() in known_names
    ]

    return {
        "target": param,
        "sources_ok": sorted(sources_ok),
        "sources_error": sorted(sources_err),
        "accounts": account_rows,
        "identity": identity_rows,
        "photos": [{"picture": p, "sources": sorted(s)} for p, s in photos.items()],
        "reuse": reuse_rows,
        "exposure": exposure_rows,
        "org_matches": org_matches,
        "avatar_matches": avatar_matches,
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------
@module_task(module_name="crossref", dev_mode_sleep=3)
def p_crossref(param):
    """Task of Celery that correlates every Veiled Eye result for a target."""
    wait = float(os.environ.get("VEILED_CROSSREF_WAIT", "60"))
    collected = collect(param, wait)
    if not collected:
        raise Exception("warn: Nothing to correlate yet (run other modules first)")
    report = correlate(param, collected)
    if not report["sources_ok"]:
        raise Exception("warn: No successful module output to correlate yet")
    accounts = report["accounts"]

    counts = {g: sum(1 for a in accounts if a["confidence"] == g) for g in _GRADES}
    gather = [
        root_node(
            LINK,
            param,
            "fas fa-project-diagram",
            f"{counts['confirmed']} confirmed · {counts['likely']} likely",
        )
    ]
    for idx, acc in enumerate(a for a in accounts if a["confidence"] != "candidate"):
        gather.append(
            {
                "name-node": f"CR-acc-{idx}",
                "title": acc["platform"],
                "subtitle": f"{acc['handle']} · {acc['confidence']} ({acc['score']})",
                "icon": "fas fa-user-secret" if acc["underground"] else acc["icon"],
                "link": LINK,
                "help": ", ".join(acc["urls"][:3]) or ", ".join(acc["sources"]),
            }
        )
    for key, icon in (
        ("name", "fas fa-user"),
        ("email", "fas fa-at"),
        ("location", "fas fa-map-marker-alt"),
        ("phone", "fas fa-phone"),
        ("wallet", "fas fa-wallet"),
    ):
        for idx, row in enumerate(report["identity"].get(key, [])[:5]):
            gather.append(
                {
                    "name-node": f"CR-{key}-{idx}",
                    "title": row["value"],
                    "subtitle": f"{key} · {row['score']} sources",
                    "icon": icon,
                    "link": LINK,
                    "help": ", ".join(row["sources"]),
                }
            )
    for idx, match in enumerate(report["avatar_matches"]):
        gather.append(
            {
                "name-node": f"CR-avatar-{idx}",
                "title": "Same profile picture",
                "subtitle": " = ".join(f"{p}/{h}" for p, h in match["accounts"]),
                "icon": "fas fa-portrait",
                "link": LINK,
                "help": f"perceptual hash distance {match['distance']}/64",
            }
        )
    for idx, row in enumerate(report["exposure"]):
        gather.append(
            {
                "name-node": f"CR-exp-{idx}",
                "title": row["source"],
                "subtitle": ", ".join(row["selectors"]),
                "icon": "fas fa-skull-crossbones",
                "link": LINK,
            }
        )

    # places for the map + activity hours / time zone (factories/insights.py)
    report["places"] = insights.places(collected)
    report["activity"] = insights.activity(collected)
    act = report["activity"]
    if act["estimate"]:
        gather.append(
            {
                "name-node": "CR-tz",
                "title": f"Time zone {act['estimate']}",
                "subtitle": act["basis"],
                "icon": "fas fa-clock",
                "link": LINK,
            }
        )
    for idx, place in enumerate(report["places"][:8]):
        gather.append(
            {
                "name-node": f"CR-place-{idx}",
                "title": place["name"] or f"{place['lat']:.3f}, {place['lng']:.3f}",
                "subtitle": f"{place['kind']} · {place['source']}",
                "icon": "fas fa-map-marker-alt",
                "link": LINK,
                "help": f"https://www.openstreetmap.org/?mlat={place['lat']}&mlon={place['lng']}#map=12/{place['lat']}/{place['lng']}",
            }
        )

    # pictures: one-click reverse image search (analyst opens them)
    for idx, photo in enumerate((report.get("photos") or [])[:3]):
        links = insights.reverse_image_links(photo["picture"])
        gather.append(
            {
                "name-node": f"CR-rev-{idx}",
                "title": "Reverse image search",
                "subtitle": f"profile picture from {', '.join(photo['sources'][:3])}",
                "icon": "fas fa-search",
                "link": LINK,
                "help": links["Yandex"],
                "picture": photo["picture"],
            }
        )
        photo["reverse_search"] = links
    # handle patterns for the best-supported full name (shown, not run)
    best = (report["identity"].get("name") or [None])[0]
    report["username_candidates"] = (
        insights.username_candidates(best["value"]) if best else []
    )
    if report["username_candidates"]:
        gather.append(
            {
                "name-node": "CR-handles",
                "title": "Handle patterns to try",
                "subtitle": ", ".join(report["username_candidates"][:8]),
                "icon": "fas fa-user-tag",
                "link": LINK,
                "handles": report["username_candidates"],
            }
        )

    profile = [
        {
            "presence": [
                {
                    "name": "crossref",
                    "children": [
                        {"name": "confirmed", "value": counts["confirmed"]},
                        {"name": "likely", "value": counts["likely"]},
                        {"name": "candidate", "value": counts["candidate"]},
                        {"name": "sources", "value": len(report["sources_ok"])},
                        {
                            "name": "avatar matches",
                            "value": len(report["avatar_matches"]),
                        },
                    ],
                }
            ]
        }
    ]
    for place in report["places"]:
        if place["kind"] == "stated location":  # geocoded here: new on the map
            profile.append(
                {
                    "geo": {
                        "Caption": "Cross-analysis",
                        "Accessibility": f"stated by {place['source']}",
                        "Latitude": place["lat"],
                        "Longitude": place["lng"],
                        "Name": place["name"],
                        "Time": "",
                    }
                }
            )
    top_name = (report["identity"].get("name") or [None])[0]
    if top_name and top_name["score"] >= 2:
        profile.append({"name": top_name["value"]})

    graphic = [
        {"crossref": gather},
        {"accounts": accounts},
        {"identity": report["identity"]},
        {"reuse": report["reuse"]},
        {"exposure": report["exposure"]},
        {"org_matches": report["org_matches"]},
        {"avatar_matches": report["avatar_matches"]},
        {"places": report["places"]},
        {"activity": report["activity"]},
        {"sources": {"ok": report["sources_ok"], "error": report["sources_error"]}},
    ]

    return build_total(
        module="crossref",
        param=param,
        validation="soft",
        raw=report,
        graphic=graphic,
        profile=profile,
        timeline=[],
    )


t_crossref = p_crossref


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Correlate cached Veiled Eye results")
    parser.add_argument("target")
    print(json.dumps(t_crossref(parser.parse_args().target, dev_mode=False), indent=2))
