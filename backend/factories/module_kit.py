"""One builder for every "account on platform X" module.

Turns a normalised account description into Veiled Eye's positional output with the
same conventions everywhere:

* ``graphic[0] = {module: gather}``  — root node + one node per fact
* ``profile``                        — name / username / bio / location /
  email / phone / photos / social / wallet entries (feeds the Profile view
  and ``crossref``)
* ``timeline``                       — dated events
* ``tasks``                          — pivots to other Veiled Eye modules
"""

from __future__ import annotations

from typing import Any

from factories.identity import (
    find_phones,
    find_wallets,
    icon_for,
    socials_to_profile,
    socials_to_tasks,
)
from factories.output_builder import build_total


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def assemble_account(
    *,
    module: str,
    param: str,
    platform: str,
    handle: str,
    url: str | None = None,
    name: str | None = None,
    bio: str | None = None,
    location: str | None = None,
    avatar: str | None = None,
    created: str | None = None,
    emails: list[str] | None = None,
    socials: list[dict] | None = None,
    facts: list[tuple[str, Any, str]] | None = None,
    extra_nodes: list[dict] | None = None,
    extra_graphic: list[dict] | None = None,
    timeline: list[dict] | None = None,
    presence: list[dict] | None = None,
    raw: Any = None,
    validation: str = "hard",
    text_for_selectors: str = "",
) -> list[dict]:
    """Build the Veiled Eye result for one platform account.

    ``facts`` are ``(title, value, icon)`` rows shown as graph nodes.
    ``text_for_selectors`` (bio, descriptions...) is mined for crypto wallets
    and international phone numbers, which become profile entries + pivots.
    """
    icon = icon_for(platform)
    link = module.title()
    gather: list[dict] = [
        {
            "name-node": link,
            "title": name or handle,
            "subtitle": f"@{handle}" if handle else "",
            "icon": icon,
            "link": link,
            "help": url or "",
        }
    ]
    for idx, (title, value, ficon) in enumerate(facts or []):
        value = _clean(value)
        if value in (None, "", [], {}):
            continue
        gather.append(
            {
                "name-node": f"{link}-f{idx}",
                "title": title,
                "subtitle": str(value)[:300],
                "icon": ficon,
                "link": link,
            }
        )
    for node in extra_nodes or []:
        gather.append({"link": link, **node})

    profile: list[dict] = []
    social_entry = {
        "name": platform.title(),
        "url": url or "",
        "icon": icon,
        "source": module,
        "username": handle,
    }
    socials_profile = [social_entry, *socials_to_profile(socials or [], module)]
    profile.append({"social": socials_profile})
    if handle:
        profile.append({"username": handle})
    if name and name != handle:
        profile.append({"name": _clean(name)})
    if bio:
        profile.append({"bio": _clean(bio)[:1000]})
    if location:
        profile.append({"location": _clean(location)})
    if avatar and str(avatar).startswith("http"):
        profile.append({"photos": [{"picture": avatar, "title": platform}]})
    if url:
        profile.append({"url": url})
    for email in emails or []:
        profile.append({"email": email})

    wallets = find_wallets(text_for_selectors)
    phones = find_phones(text_for_selectors)
    if wallets:
        profile.append(
            {
                "wallet": [
                    {"currency": w["chain"], "address": w["address"]} for w in wallets
                ]
            }
        )
    for phone in phones:
        profile.append({"phone": phone})
    if presence:
        profile.append({"presence": [{"name": module, "children": presence}]})

    events = list(timeline or [])
    if created:
        events.insert(
            0,
            {
                "date": str(created),
                "action": f"{platform.title()} : account created",
                "icon": icon,
            },
        )

    tasks = socials_to_tasks(socials or [], skip=module)
    if wallets:
        tasks.append(
            {"module": "crypto", "param": ",".join(w["address"] for w in wallets)}
        )
    if phones:
        tasks.append({"module": "phone", "param": ",".join(phones)})
    for email in emails or []:
        for target in ("gravatar", "pgp"):
            tasks.append({"module": target, "param": email})

    graphic = [{module: gather}, *(extra_graphic or [])]
    return build_total(
        module=module,
        param=param,
        validation=validation,
        raw=raw,
        graphic=graphic,
        profile=profile,
        timeline=events,
        tasks=tasks,
    )
