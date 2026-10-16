#!/usr/bin/env python
"""Phone module — offline number intelligence + account registration + web.

For each number (several may be given, comma separated):

1. **phonenumbers** (offline, libphonenumber): validity, E.164 /
   international / national formats, country, original carrier, line type
   (mobile / fixed / VoIP / toll-free...), time zones.
2. **ignorant** (megadose, GPLv3): is the number registered on Instagram,
   Snapchat, Amazon?  Non-notifying checks only.
3. **Web mentions**: the number's formats searched as exact phrases
   (keyless DuckDuckGo) — classifieds, complaint sites, business listings.

Numbers without a ``+`` prefix are parsed with ``VEILED_PHONE_REGION``
(default ``TR``).  ``VEILED_PHONE_IGNORANT=0`` / ``VEILED_PHONE_WEB=0`` disable
the online parts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from factories.identity import split_multi
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

LINE_TYPES = {
    0: "fixed line",
    1: "mobile",
    2: "fixed line or mobile",
    3: "toll free",
    4: "premium rate",
    5: "shared cost",
    6: "VoIP",
    7: "personal number",
    8: "pager",
    9: "UAN",
    10: "voicemail",
    99: "unknown",
}


def analyse(raw: str) -> dict:
    """Offline libphonenumber analysis (raises a warning when invalid)."""
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone

    region = os.environ.get("VEILED_PHONE_REGION", "TR")
    try:
        num = phonenumbers.parse(raw, None if raw.strip().startswith("+") else region)
    except phonenumbers.NumberParseException as exc:
        raise Exception(f"warn: Not a phone number: {raw}") from exc
    fmt = phonenumbers.PhoneNumberFormat
    return {
        "input": raw,
        "valid": phonenumbers.is_valid_number(num),
        "possible": phonenumbers.is_possible_number(num),
        "e164": phonenumbers.format_number(num, fmt.E164),
        "international": phonenumbers.format_number(num, fmt.INTERNATIONAL),
        "national": phonenumbers.format_number(num, fmt.NATIONAL),
        "country_code": num.country_code,
        "national_number": str(num.national_number),
        "region": phonenumbers.region_code_for_number(num),
        "country": geocoder.description_for_number(num, "en") or None,
        "carrier": carrier.name_for_number(num, "en") or None,
        "line_type": LINE_TYPES.get(phonenumbers.number_type(num), "unknown"),
        "timezones": list(timezone.time_zones_for_number(num)),
    }


async def _ignorant(info: dict) -> list[dict]:
    import httpx
    from ignorant.modules.shopping.amazon import amazon
    from ignorant.modules.social_media.instagram import instagram
    from ignorant.modules.social_media.snapchat import snapchat

    out: list[dict] = []
    cc, nn = str(info["country_code"]), info["national_number"]
    async with httpx.AsyncClient(timeout=15) as client:
        for check in (instagram, snapchat, amazon):
            try:
                await check(nn, cc, client, out)
            except Exception as exc:  # one broken site never kills the rest
                out.append(
                    {
                        "name": check.__name__,
                        "exists": False,
                        "rateLimit": True,
                        "error": str(exc),
                    }
                )
    return out


def registrations(info: dict) -> list[dict]:
    if os.environ.get("VEILED_PHONE_IGNORANT", "1") == "0":
        return []
    try:
        return asyncio.run(_ignorant(info))
    except Exception:
        return []


def web_mentions(info: dict, limit: int = 8) -> list[dict]:
    if os.environ.get("VEILED_PHONE_WEB", "1") == "0":
        return []
    try:
        from ddgs import DDGS
    except Exception:
        return []
    variants = list(
        dict.fromkeys([info["e164"], info["international"], info["national"]])
    )
    query = " OR ".join(f'"{v}"' for v in variants)
    try:
        hits = DDGS().text(query, max_results=limit) or []
    except Exception:
        return []
    return [
        {
            "title": h.get("title", ""),
            "url": h.get("href", ""),
            "snippet": h.get("body", ""),
        }
        for h in hits
    ]


@module_task(module_name="phone", dev_mode_sleep=2)
def p_phone(param):
    """Task of Celery that profiles one or more phone numbers."""
    numbers = split_multi(param)
    if not numbers:
        raise Exception("warn: Empty phone parameter")
    gather = [root_node("Phone", param, "fas fa-phone", f"{len(numbers)} number(s)")]
    profile, lists = [], []
    social, valid = [], 0
    for idx, raw in enumerate(numbers):
        info = analyse(raw)
        if not info["valid"]:
            gather.append(
                {
                    "name-node": f"PH-{idx}",
                    "title": raw,
                    "subtitle": "invalid number",
                    "icon": "fas fa-times-circle",
                    "link": "Phone",
                }
            )
            lists.append({**info, "registrations": [], "web": []})
            continue
        valid += 1
        regs = registrations(info)
        web = web_mentions(info)
        info.update({"registrations": regs, "web": web})
        lists.append(info)
        gather.append(
            {
                "name-node": f"PH-{idx}",
                "title": info["international"],
                "subtitle": " · ".join(
                    x
                    for x in (info["country"], info["carrier"], info["line_type"])
                    if x
                ),
                "icon": "fas fa-mobile-alt"
                if info["line_type"] == "mobile"
                else "fas fa-phone",
                "link": "Phone",
                "help": ", ".join(info["timezones"]),
            }
        )
        for reg in regs:
            if reg.get("exists"):
                gather.append(
                    {
                        "name-node": f"PH-{idx}-{reg['name']}",
                        "title": str(reg["name"]).title(),
                        "subtitle": f"registered with {info['e164']}",
                        "icon": f"fab fa-{reg['name']}",
                        "link": "Phone",
                    }
                )
                social.append(
                    {
                        "name": str(reg["name"]).title(),
                        "url": f"https://{reg.get('domain', '')}",
                        "icon": f"fab fa-{reg['name']}",
                        "source": "phone",
                        "username": info["e164"],
                    }
                )
        for hit_idx, hit in enumerate(web[:5]):
            gather.append(
                {
                    "name-node": f"PH-{idx}-web{hit_idx}",
                    "title": hit["title"][:80] or hit["url"],
                    "subtitle": "web mention",
                    "icon": "fas fa-globe",
                    "link": "Phone",
                    "help": hit["url"],
                }
            )
        profile.append({"phone": info["e164"]})
        if info["country"]:
            profile.append({"location": info["country"]})

    if not valid:
        raise Exception("warn: No valid phone number")
    if social:
        profile.insert(0, {"social": social})
    return build_total(
        module="phone",
        param=param,
        validation="hard",
        raw={"numbers": lists},
        graphic=[{"phone": gather}, {"lists": lists}],
        profile=profile,
        timeline=[],
    )


t_phone = p_phone

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("numbers", help="one or more numbers, comma separated")
    print(json.dumps(t_phone(ap.parse_args().numbers, dev_mode=False), indent=2))
