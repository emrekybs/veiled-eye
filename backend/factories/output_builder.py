"""Helpers that build the positional Veiled Eye output list.

The frontend reads results by position, so every module MUST return::

    [ {"module"}, {"param"}, {"validation"}, {"raw"},
      {"graphic"}, {"profile"}, {"timeline"}, ({"tasks"}) ]

``build_total`` enforces that order for the extended modules.
"""

from __future__ import annotations

from typing import Any

from factories.fontcheat import search_icon_5


def build_total(
    *,
    module: str,
    param: str,
    validation: str,
    raw: Any,
    graphic: list,
    profile: list,
    timeline: list,
    tasks: list | None = None,
) -> list[dict[str, Any]]:
    total: list[dict[str, Any]] = [
        {"module": module},
        {"param": param},
        {"validation": validation},
        {"raw": raw},
        {"graphic": graphic},
        {"profile": profile},
        {"timeline": timeline},
    ]
    if tasks:
        total.append({"tasks": tasks})
    return total


def root_node(name: str, title: str, icon: str, subtitle: str = "") -> dict[str, Any]:
    return {
        "name-node": name,
        "title": title,
        "subtitle": subtitle,
        "icon": icon,
        "link": name,
    }


def site_icon(site: str, default: str = "fas fa-dot-circle") -> str:
    """Font Awesome icon for a site name (brand icon when one exists)."""
    try:
        candidate = str(site).lower().split(".")[0].replace(" ", "")
        icon = search_icon_5(candidate)
        if icon:
            return icon
    except Exception:
        pass
    return default
