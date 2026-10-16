"""Auto-chaining rules for the extended modules.

The frontend already executes every ``{"module": ..., "param": ...}`` entry
it finds in a result's ``tasks`` element, as long as the module name is in
``/tasklist``.  This file decides which extended modules (maigret,
userscanner, darksherlock, gitsniff, crosslinked, crossref) get triggered
from which existing results, WITHOUT modifying any existing module.

``inject()`` is applied by the ``/result`` endpoint just before the result
leaves the API, and the ``veiled-eye scan`` CLI uses ``next_tasks()`` to walk the
same graph without a frontend.

Disable with ``VEILED_AUTOCHAIN=0``.
"""

from __future__ import annotations

import os
from typing import Any

# Free / consumer mail providers — never treated as a company domain.
FREE_MAIL = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.es",
    "ymail.com",
    "hotmail.com",
    "hotmail.es",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "gmx.com",
    "gmx.de",
    "gmx.net",
    "mail.com",
    "mail.ru",
    "yandex.com",
    "yandex.ru",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "tutanota.com",
    "tuta.io",
    "zoho.com",
    "qq.com",
    "163.com",
    "126.com",
    "web.de",
    "free.fr",
    "orange.fr",
    "libero.it",
    "seznam.cz",
    "wp.pl",
    "o2.pl",
    "rambler.ru",
    "bk.ru",
    "inbox.ru",
    "list.ru",
    "fastmail.com",
    "hey.com",
    "duck.com",
    "yahoo.co.uk",
    "hotmail.co.uk",
    "outlook.es",
    "outlook.fr",
}

# Modules the stock frontend fires on its own. Their results are the
# entry points ("anchors") into the extended module graph.
EMAIL_ANCHORS = {
    "emailrep",
    "leaklookup",
    "holehe",
    "peopledatalabs",
    "leaks",
    "socialscan",
    "hudsonrock",
}
USERNAME_ANCHORS = {"search", "dorks", "hudsonrock"}

# Veiled Eye modules worth confirming when maigret / crossref see an account there.
CONFIRMABLE = {"github", "gitlab", "keybase", "reddit"}

# Identity modules fired for every username / e-mail investigation
USERNAME_IDENTITY = (
    "maigret",
    "userscanner",
    "darksherlock",
    "whatsmyname",
    "telegram",
    "steam",
    "bluesky",
    "hackernews",
    "stackexchange",
    "kick",
    "snapchat",
    "instagram",
    "wayback",
    "pgp",
    "ahmia",
    "darkweb",
)
EMAIL_IDENTITY = ("userscanner", "emailreg", "gravatar", "pgp", "ahmia", "darkweb")

EXTENDED_MODULES = (
    "maigret",
    "userscanner",
    "darksherlock",
    "gitsniff",
    "crosslinked",
    "crossref",
    "telegram",
    "gravatar",
    "steam",
    "bluesky",
    "hackernews",
    "stackexchange",
    "kick",
    "snapchat",
    "wayback",
    "whatsmyname",
    "pgp",
    "phone",
    "crypto",
    "ahmia",
)


def enabled() -> bool:
    return os.environ.get("VEILED_AUTOCHAIN", "1").lower() not in ("0", "false", "no")


def is_email(value: str) -> bool:
    return isinstance(value, str) and "@" in value and "." in value.split("@")[-1]


def company_from_domain(domain: str) -> str | None:
    """``acme-corp.com.tr`` -> ``acme corp`` (None for free-mail)."""
    domain = (domain or "").lower().strip()
    if not domain or domain in FREE_MAIL:
        return None
    labels = [lb for lb in domain.split(".") if lb]
    second_level = {
        "com",
        "co",
        "org",
        "net",
        "gov",
        "edu",
        "ac",
        "gen",
        "biz",
        "bel",
        "k12",
    }
    if len(labels) >= 3 and labels[-2] in second_level and len(labels[-1]) == 2:
        base = labels[-3]  # acme.com.tr / acme.co.uk
    elif len(labels) >= 2:
        base = labels[-2]  # mail.acme.com -> acme
    else:
        base = labels[0] if labels else ""
    base = base.replace("-", " ").replace("_", " ").strip()
    return base or None


def _section(result: list, key: str) -> Any:
    for item in result:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def _graphic_nodes(result: list, graph_key: str) -> list[dict]:
    graphic = _section(result, "graphic") or []
    for item in graphic:
        if (
            isinstance(item, dict)
            and graph_key in item
            and isinstance(item[graph_key], list)
        ):
            return item[graph_key]
    return []


def _ok(result: list) -> bool:
    """False for the 4-element error shape produced by ``@module_task``."""
    raw = _section(result, "raw")
    if (
        isinstance(raw, list)
        and raw
        and isinstance(raw[0], dict)
        and raw[0].get("status")
        in (
            "Fail",
            "Warning",
        )
    ):
        return False
    return _section(result, "graphic") is not None


def next_tasks(result: Any) -> list[dict[str, str]]:
    """Return the extended-module tasks a finished result should trigger."""
    if not isinstance(result, list) or not result:
        return []
    module = _section(result, "module")
    param = _section(result, "param")
    if not module or not param:
        return []
    param = str(param)
    tasks: list[dict[str, str]] = []

    def add(mod: str, value: str | None) -> None:
        if value and {"module": mod, "param": value} not in tasks:
            tasks.append({"module": mod, "param": value})

    # --- Entry points fired by the stock frontend ---------------------------
    if module in EMAIL_ANCHORS and is_email(param):
        for target in EMAIL_IDENTITY:
            add(target, param)
        domain = param.split("@")[-1].lower()
        if company_from_domain(domain):  # corporate address -> its employees
            add("crosslinked", domain)
            add("domaininfo", domain)
    if module in USERNAME_ANCHORS and not is_email(param):
        # the username box also accepts phones and wallets (Veiled Eye UI)
        from factories.identity import selector_type

        kind = selector_type(param)
        if kind == "phone":
            add("phone", param)
        elif kind == "wallet":
            add("crypto", param)
        else:
            for target in USERNAME_IDENTITY:
                add(target, param)

    # --- Phones / wallets surfaced by ANY module -> phone / crypto --------
    if _ok(result) and module not in ("phone", "crypto"):
        phones, wallets = [], []
        for entry in _section(result, "profile") or []:
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("phone"), str) and entry["phone"] not in phones:
                phones.append(entry["phone"])
            for w in (
                entry.get("wallet") or []
                if isinstance(entry.get("wallet"), list)
                else []
            ):
                if (
                    isinstance(w, dict)
                    and w.get("address")
                    and w["address"] not in wallets
                ):
                    wallets.append(w["address"])
        if phones:
            add("phone", ",".join(phones[:5]))
        if wallets:
            add("crypto", ",".join(wallets[:10]))

    # --- GitHub -> commit-email mining + company employees -----------------
    if module == "github" and _ok(result):
        add("gitsniff", param)
        for node in _graphic_nodes(result, "github"):
            if node.get("name-node") == "GitCompany" and isinstance(
                node.get("subtitle"), str
            ):
                add("crosslinked", node["subtitle"].lstrip("@").strip())

    # --- Slow username sweeps finish -> correlate ---------------------------
    if module == "maigret":
        add("crossref", param)
        if _ok(result):
            for node in _graphic_nodes(result, "maigret"):
                site = str(node.get("title", "")).lower()
                if site in CONFIRMABLE:
                    add(site, param)
    if module == "userscanner" and is_email(param):
        add("crossref", param)

    return tasks


def inject(result: Any) -> Any:
    """Append/merge chained tasks into *result* (returns the same object).

    Every task list is then cut at the pivot depth (factories/pivots.py).
    """
    from factories import pivots

    if not enabled():
        return pivots.limit(result)
    try:
        extra = next_tasks(result)
        if not extra:
            return result
        existing = None
        for item in result:
            if isinstance(item, dict) and isinstance(item.get("tasks"), list):
                existing = item["tasks"]
                break
        if existing is None:
            result.append({"tasks": extra})
        else:
            for task in extra:
                if task not in existing:
                    existing.append(task)
    except Exception:
        pass
    return pivots.limit(result)
