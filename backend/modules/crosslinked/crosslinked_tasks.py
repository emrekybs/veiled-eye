#!/usr/bin/env python
"""CrossLinked module — LinkedIn employee enumeration for an organisation.

Wraps m8sec/CrossLinked (GPLv3) through its ``CrossLinked`` search class:
search-engine dorks (``site:linkedin.com/in "<company>"``) return the names
and job titles of the people who list that organisation.

Input: a company name (``Acme Corp``) **or** a domain (``acme.com``).  With a
domain the module also derives the likely corporate e-mail address of every
employee, using the common formats (first.last, flast, first) — handy for
the ``crossref`` / leak modules.

Tunables (env):
  VEILED_CROSSLINKED_ENGINES  comma list, default "bing,google"
  VEILED_CROSSLINKED_TIMEOUT  seconds per engine (default 25)
  VEILED_CROSSLINKED_PROXY    optional proxy (ip:port) for the engine requests
"""

from __future__ import annotations

import argparse
import json
import os
import re

from celery.utils.log import get_task_logger
from factories.chain import company_from_domain
from factories.output_builder import build_total, root_node
from factories.quiet import silenced
from factories.task_wrapper import module_task
from unidecode import unidecode

logger = get_task_logger(__name__)

LINK = "CrossLinked"
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$", re.I)
EMAIL_FORMATS = ("{first}.{last}", "{f}{last}", "{first}{last}", "{first}")


def _target(param: str) -> tuple[str, str | None]:
    """Return (company_query, domain_or_None)."""
    value = param.strip()
    if "@" in value:
        value = value.split("@")[-1]
    if _DOMAIN_RE.match(value):
        company = company_from_domain(value) or value.split(".")[0]
        return company, value.lower()
    return value, None


_TITLE_SPLIT = re.compile(r"\s+[-\u2013\u2014|]\s+")
_LI_PROFILE = re.compile(
    r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/in/[^/?#]+", re.I
)


def parse_result(title: str, url: str, snippet: str, company: str) -> dict | None:
    """``Jane Doe - Security Engineer - Acme | LinkedIn`` -> person.

    Only profile URLs (/in/...) count, and the company must appear in the
    title or snippet: a name match alone is how false positives creep in.
    """
    if not _LI_PROFILE.match(str(url or "")):
        return None
    text = f"{title} {snippet}".lower()
    words = [w for w in re.split(r"\W+", company.lower()) if len(w) > 1]
    if words and not all(w in text for w in words):
        return None
    clean = re.sub(r"\s*\|\s*LinkedIn.*$", "", str(title or ""), flags=re.I).strip()
    parts = [x.strip() for x in _TITLE_SPLIT.split(clean) if x.strip()]
    if not parts:
        return None
    name = unidecode(parts[0])
    if (
        not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{2,60}", name)
        or "linkedin" in name.lower()
    ):
        return None
    job = parts[1] if len(parts) > 1 else "N/A"
    return {"name": name, "title": job, "url": _LI_PROFILE.match(url).group(0)}


def _providers() -> list:
    """Every engine that works without being blocked, best first."""
    from factories.configuration import api_keys_search
    from factories.search_providers import (
        BraveSearchProvider,
        DuckDuckGoProvider,
        GoogleCSEProvider,
    )

    out = []
    brave = api_keys_search("brave_key")
    if brave:
        out.append(BraveSearchProvider(brave))
    cse_key, cse_cx = api_keys_search("cse_api_key"), api_keys_search("cse_cx")
    if cse_key and cse_cx:
        out.append(GoogleCSEProvider(cse_key, cse_cx))
    out.append(DuckDuckGoProvider())  # ddgs: keyless metasearch, rotates engines
    return out


def _search(company: str) -> list[dict]:
    queries = [
        f'site:linkedin.com/in "{company}"',
        f'site:linkedin.com/in "at {company}"',
        f'"{company}" linkedin profile',
    ]
    limit = int(os.environ.get("VEILED_CROSSLINKED_MAX", "60"))
    results: list[dict] = []
    seen: set[str] = set()
    for provider in _providers():
        for q in queries:
            try:
                hits = provider.search(q, max_results=30)
            except Exception as exc:
                logger.warning(f"CrossLinked {provider.name} failed: {exc}")
                continue
            for h in hits:
                person = parse_result(h.title, h.url, h.description, company)
                if person and person["url"] not in seen:
                    seen.add(person["url"])
                    person["engine"] = provider.name
                    results.append(person)
            if len(results) >= limit:
                return results
    if not results:
        results = _legacy_search(company)
    return results


def _legacy_search(company: str) -> list[dict]:
    """The original CrossLinked scraper (Bing HTML), last resort."""
    try:
        from crosslinked.search import CrossLinked
    except ImportError:
        return []
    timeout = float(os.environ.get("VEILED_CROSSLINKED_TIMEOUT", "20"))
    out: list[dict] = []
    with silenced():
        try:
            for item in CrossLinked("bing", company, timeout, 5, [], 1).search():
                item = dict(item)
                item["engine"] = "bing"
                out.append(item)
        except Exception as exc:
            logger.warning(f"CrossLinked bing failed: {exc}")
    return out


def _split_name(name: str) -> tuple[str, str] | None:
    parts = [
        p for p in re.split(r"\s+", unidecode(name).lower().strip()) if p.isalpha()
    ]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def _emails(name: str, domain: str) -> list[str]:
    split = _split_name(name)
    if not split:
        return []
    first, last = split
    out = []
    for fmt in EMAIL_FORMATS:
        local = fmt.format(first=first, last=last, f=first[0], l=last[0])
        out.append(f"{local}@{domain}")
    return out


@module_task(module_name="crosslinked", dev_mode_sleep=5)
def p_crosslinked(param):
    """Task of Celery that enumerates an organisation's LinkedIn employees."""
    company, domain = _target(param)
    found = _search(company)

    # dedupe by profile URL / name
    people: dict[str, dict] = {}
    for item in found:
        key = (item.get("url") or item.get("name") or "").lower()
        if key and key not in people and item.get("name"):
            people[key] = item
    if not people:
        raise Exception(
            f"warn: No LinkedIn profiles found for '{company}'. Search engines may be "
            "rate limiting; a Brave Search or Google CSE key (API keys page) helps."
        )

    gather = [root_node(LINK, company, "fab fa-linkedin", f"{len(people)} employees")]
    lists, social, profile = [], [], []
    titles: dict[str, int] = {}

    for idx, person in enumerate(people.values()):
        name = str(person.get("name", "")).strip()
        title = str(person.get("title", "N/A")).strip()
        url = person.get("url", "")
        emails = _emails(name, domain) if domain else []
        titles[title] = titles.get(title, 0) + 1
        gather.append(
            {
                "name-node": f"CL-{idx}",
                "title": name,
                "subtitle": title,
                "icon": "fas fa-user-tie",
                "link": LINK,
                "help": url,
            }
        )
        lists.append(
            {
                "title": name,
                "subtitle": title,
                "url": url,
                "engine": person.get("engine", ""),
                "emails": emails,
            }
        )
        social.append(
            {
                "name": f"LinkedIn - {name}",
                "url": url,
                "icon": "fab fa-linkedin",
                "source": "crosslinked",
                "username": name,
            }
        )

    profile.append({"social": social})
    profile.append({"organization": company})
    profile.append(
        {
            "presence": [
                {
                    "name": "crosslinked",
                    "children": [{"name": "employees", "value": len(people)}],
                }
            ]
        }
    )

    graphic = [
        {"crosslinked": gather},
        {"lists": lists},
        {"titles": titles},
        {"email_formats": [f + "@" + domain for f in EMAIL_FORMATS] if domain else []},
    ]

    return build_total(
        module="crosslinked",
        param=param,
        validation="soft",
        raw={"company": company, "domain": domain, "employees": list(people.values())},
        graphic=graphic,
        profile=profile,
        timeline=[],
    )


t_crosslinked = p_crosslinked


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CrossLinked employee enumeration (Veiled Eye module)"
    )
    parser.add_argument("company", help="company name or domain")
    print(
        json.dumps(t_crosslinked(parser.parse_args().company, dev_mode=False), indent=2)
    )
