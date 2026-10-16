#!/usr/bin/env python
"""E-mail registrations — holehe and user-scanner merged into one view.

For every site the address is registered on, one row:

* ``confirmed`` — both tools report the account (or user-scanner itself rates
  it confirmed and holehe agrees / was not able to check)
* ``likely``    — one tool reports it
* recovery hints holehe exposes (masked phone, masked backup e-mail)

The two scanners already run for an e-mail search; this module reuses their
cached results (waiting for them while they run) and only scans itself when
nothing is cached. Neither tool runs "loud" checks that notify the target.

Also reports what the address itself tells: free / disposable / corporate
provider and the domain.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time

from factories import categories, result_cache
from factories.output_builder import build_total, root_node, site_icon
from factories.task_wrapper import module_task

LINK = "E-mail registrations"

FREE_PROVIDERS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "ymail.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "gmx.com",
    "gmx.de",
    "gmx.net",
    "web.de",
    "mail.com",
    "yandex.com",
    "yandex.ru",
    "mail.ru",
    "inbox.ru",
    "list.ru",
    "bk.ru",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "tutanota.com",
    "tuta.io",
    "zoho.com",
    "qq.com",
    "163.com",
    "126.com",
    "hotmail.co.uk",
    "yahoo.co.uk",
    "outlook.com.tr",
    "hotmail.com.tr",
    "yandex.com.tr",
    "mynet.com",
}
PRIVACY_PROVIDERS = {
    "proton.me",
    "protonmail.com",
    "pm.me",
    "tutanota.com",
    "tuta.io",
    "duck.com",
    "simplelogin.com",
    "anonaddy.me",
    "addy.io",
    "mailfence.com",
    "cock.li",
    "riseup.net",
    "disroot.org",
}
DISPOSABLE = {
    "mailinator.com",
    "10minutemail.com",
    "guerrillamail.com",
    "temp-mail.org",
    "tempmail.com",
    "yopmail.com",
    "trashmail.com",
    "getnada.com",
    "dispostable.com",
    "sharklasers.com",
    "maildrop.cc",
    "throwawaymail.com",
    "mohmal.com",
    "emailondeck.com",
    "fakeinbox.com",
    "mintemail.com",
}


def provider_kind(domain: str) -> str:
    d = domain.lower()
    if d in DISPOSABLE:
        return "disposable"
    if d in PRIVACY_PROVIDERS:
        return "privacy-focused"
    if d in FREE_PROVIDERS:
        return "free webmail"
    return "corporate / own domain"


def site_key(name: str) -> str:
    """'Instagram', 'instagram.com', 'instagram' -> 'instagram'."""
    n = str(name or "").lower().strip()
    n = re.sub(r"^https?://(www\.)?", "", n).split("/")[0]
    n = re.sub(r"\.(com|net|org|io|co|me|tv|gg|ru|de|fr|uk|com\.tr)$", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def _section(result, key):
    for el in result or []:
        if isinstance(el, dict) and key in el:
            return el[key]
    return None


def _cached(module: str, email: str, wait: float):
    """Cached output of ``module`` (waiting while it runs), or None."""
    start = time.monotonic()
    # the scanner may still be queued: give it a moment to appear
    grace = min(15.0, wait)
    while True:
        state = result_cache.state(module, email)
        if state == "DONE":
            return result_cache.fetch(module, email)
        elapsed = time.monotonic() - start
        if elapsed >= wait or (state != "RUNNING" and elapsed >= grace):
            return None
        time.sleep(2)


def holehe_rows(email: str, wait: float) -> list[dict]:
    res = _cached("holehe", email, wait)
    if res is not None:
        raw = _section(res, "raw")
        return raw if isinstance(raw, list) and raw and "exists" in raw[0] else []
    import trio
    from modules.holehe.holehe_tasks import _holehe_query

    return trio.run(_holehe_query, email)


def userscanner_rows(email: str, wait: float) -> list[dict]:
    res = _cached("userscanner", email, wait)
    if res is not None:
        raw = _section(res, "raw")
        return (raw.get("found") or []) if isinstance(raw, dict) else []
    from modules.userscanner.userscanner_tasks import _as_dict, _scan

    first, _ = _scan(email, True)
    return [r for r in (_as_dict(x) for x in first) if r.get("found")]


def merge(holehe: list[dict], scanner: list[dict]) -> list[dict]:
    sites: dict[str, dict] = {}

    def row(key: str, name: str) -> dict:
        return sites.setdefault(
            key,
            {
                "site": name,
                "domain": "",
                "sources": [],
                "url": "",
                "category": "",
                "recovery_email": "",
                "recovery_phone": "",
                "others": None,
                "scanner_confidence": "",
                "holehe_checked": False,
            },
        )

    for h in holehe:
        key = site_key(h.get("domain") or h.get("name"))
        if not key:
            continue
        hname = str(h.get("name") or key)
        r = row(key, hname.capitalize() if hname.islower() else hname)
        r["holehe_checked"] = r["holehe_checked"] or not h.get("rateLimit")
        r["domain"] = r["domain"] or h.get("domain") or ""
        if h.get("exists") is True:
            r["sources"].append("holehe")
            r["recovery_email"] = h.get("emailrecovery") or r["recovery_email"]
            r["recovery_phone"] = h.get("phoneNumber") or r["recovery_phone"]
            if h.get("others"):
                r["others"] = h["others"]
    for s in scanner:
        name = s.get("site_name") or s.get("site") or ""
        key = site_key(name)
        if not key:
            continue
        r = row(key, name)
        if name and r["site"].lower() == name.lower():
            r["site"] = name  # user-scanner's display name ("GitHub", not "github")
        r["sources"].append("user-scanner")
        r["url"] = r["url"] or s.get("url") or ""
        r["category"] = r["category"] or s.get("category") or ""
        conf = ((s.get("extra") or {}).get("confidence")) or ""
        r["scanner_confidence"] = conf

    out = []
    for r in sites.values():
        if not r["sources"]:
            continue
        both = len(set(r["sources"])) > 1
        r["status"] = (
            "confirmed"
            if both
            or (r["scanner_confidence"] == "confirmed" and not r["holehe_checked"])
            else "likely"
        )
        r["kind"] = categories.classify(r["site"], url=r["url"] or r["domain"])
        out.append(r)
    order = {"confirmed": 0, "likely": 1}
    return sorted(out, key=lambda r: (order[r["status"]], r["site"].lower()))


@module_task(module_name="emailreg", dev_mode_sleep=5)
def p_emailreg(email):
    """Merged e-mail registration sweep (holehe + user-scanner)."""
    email = str(email).strip()
    if "@" not in email:
        raise Exception("warn: e-mail registrations need an e-mail address")
    wait = float(os.environ.get("VEILED_EMAILREG_WAIT", "120"))
    domain = email.rsplit("@", 1)[1].lower()
    rows = merge(holehe_rows(email, wait), userscanner_rows(email, wait))
    kind = provider_kind(domain)
    if not rows:
        raise Exception(f"warn: No registrations found for {email}")

    confirmed = sum(1 for r in rows if r["status"] == "confirmed")
    gather = [
        root_node(
            LINK,
            email,
            "fas fa-envelope-open-text",
            f"{len(rows)} sites · {confirmed} confirmed",
        ),
        {
            "name-node": "ER-provider",
            "title": domain,
            "subtitle": kind,
            "icon": "fas fa-server",
            "link": LINK,
        },
    ]
    social, profile = [], []
    for r in rows:
        hints = []
        if r["recovery_phone"]:
            hints.append(f"recovery phone {r['recovery_phone']}")
        if r["recovery_email"]:
            hints.append(f"recovery e-mail {r['recovery_email']}")
        sources = " + ".join(dict.fromkeys(r["sources"]))
        gather.append(
            {
                "name-node": f"ER-{site_key(r['site'])}",
                "title": r["site"],
                "subtitle": "; ".join([f"{r['status']} ({sources})", *hints]),
                "icon": site_icon(r["site"]),
                "link": LINK,
                "help": r["url"] or (f"https://{r['domain']}" if r["domain"] else ""),
                "confidence": r["status"],
            }
        )
        social.append(
            {
                "name": r["site"],
                "url": r["url"] or (f"https://{r['domain']}" if r["domain"] else ""),
                "icon": site_icon(r["site"]),
                "source": "emailreg",
                "username": email,
                "category": r["category"] or r["kind"],
            }
        )
    profile.append({"social": social})
    profile.append({"email": email})

    return build_total(
        module="emailreg",
        param=email,
        validation="hard",
        raw={"email": email, "domain": domain, "provider": kind, "sites": rows},
        graphic=[{"emailreg": gather}, {"lists": rows}],
        profile=profile,
        timeline=[],
    )


t_emailreg = p_emailreg

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("email")
    print(json.dumps(t_emailreg(ap.parse_args().email, dev_mode=False), indent=2))
