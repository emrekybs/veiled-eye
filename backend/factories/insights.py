"""Cross-source insights used by crossref: places for the map and activity
hours / time zone estimate.

* ``places()``   every ``geo`` point any module produced, plus the most cited
  free-text locations geocoded once (Nominatim, max ``VEILED_GEOCODE_MAX``,
  ``VEILED_GEOCODE=0`` to switch off)
* ``activity()`` UTC hour histogram of every dated event (posts, commits,
  account creations…) and the UTC offset that best fits a normal day;
  offsets read from commit ``.patch`` headers win when present
"""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _section(result: Any, key: str) -> Any:
    for item in result or []:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def places(collected: dict[tuple[str, str], list]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[float, float]] = set()
    texts: Counter = Counter()
    text_sources: dict[str, set] = {}
    for (module, _param), result in collected.items():
        for item in _section(result, "profile") or []:
            if not isinstance(item, dict):
                continue
            geo = item.get("geo")
            if isinstance(geo, dict) and geo.get("Latitude") not in (None, ""):
                try:
                    lat, lng = float(geo["Latitude"]), float(geo["Longitude"])
                except (TypeError, ValueError):
                    continue
                key = (round(lat, 4), round(lng, 4))
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "name": geo.get("Name") or "",
                        "lat": lat,
                        "lng": lng,
                        "kind": geo.get("Accessibility") or "location",
                        "time": geo.get("Time") or "",
                        "source": module,
                    }
                )
            loc = item.get("location")
            if isinstance(loc, str) and 2 < len(loc) < 120:
                norm = re.sub(r"\s+", " ", loc).strip()
                texts[norm] += 1
                text_sources.setdefault(norm, set()).add(module)

    if os.environ.get("VEILED_GEOCODE", "1") != "0":
        named = {p["name"].lower() for p in out}
        budget = int(os.environ.get("VEILED_GEOCODE_MAX", "5"))
        for text, _n in texts.most_common():
            if budget <= 0:
                break
            if text.lower() in named:
                continue
            budget -= 1
            try:
                from factories.helpers import location_geo

                loc = location_geo(text)
            except Exception:
                loc = None
            if loc and loc.get("Latitude") not in (None, ""):
                out.append(
                    {
                        "name": text,
                        "lat": float(loc["Latitude"]),
                        "lng": float(loc["Longitude"]),
                        "kind": "stated location",
                        "time": "",
                        "source": ", ".join(sorted(text_sources[text])),
                    }
                )
    return out


_DATE_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M",
)


def parse_time(value: Any) -> datetime | None:
    """A dated event with a real time of day (UTC), else None."""
    s = str(value or "").strip()
    if not s or len(s) < 12:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("/", "-"))
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(s[:19], fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return None  # date-only values carry no time of day
    return dt


def _fmt_offset(hours: int) -> str:
    return f"UTC{'+' if hours >= 0 else '-'}{abs(hours):02d}:00"


# Typical share of online activity by local hour (low at night, evening peak)
_DAY = [
    0.30,
    0.15,
    0.08,
    0.05,
    0.05,
    0.08,
    0.20,
    0.40,
    0.60,
    0.70,
    0.75,
    0.80,
    0.85,
    0.85,
    0.80,
    0.80,
    0.85,
    0.90,
    0.95,
    1.00,
    1.00,
    1.00,
    0.90,
    0.60,
]


def estimate_offset(hours: list[int]) -> tuple[int, float]:
    """UTC offset whose local day best matches a typical daily rhythm.

    Returns (offset hours, fit 0..1). An estimate, roughly ±2 hours.
    """
    total = sum(hours) or 1
    best, best_score = 0, -1.0
    for off in range(-12, 15):
        score = sum(hours[h] * _DAY[(h + off) % 24] for h in range(24))
        if score > best_score:
            best, best_score = off, score
    return best, best_score / total


def activity(collected: dict[tuple[str, str], list]) -> dict:
    hours = [0] * 24
    weekdays = [0] * 7
    per_source: Counter = Counter()
    commit_tz: Counter = Counter()
    for (module, _param), result in collected.items():
        for ev in _section(result, "timeline") or []:
            if not isinstance(ev, dict):
                continue
            dt = parse_time(ev.get("date"))
            if dt:
                hours[dt.hour] += 1
                weekdays[dt.weekday()] += 1
                per_source[module] += 1
        raw = _section(result, "raw")
        if isinstance(raw, dict) and isinstance(raw.get("deep"), dict):
            commit_tz.update(raw["deep"].get("timezones") or {})
    samples = sum(hours)
    out = {
        "hours_utc": hours,
        "weekdays": weekdays,
        "samples": samples,
        "sources": dict(per_source),
        "commit_offsets": dict(commit_tz.most_common()),
        "estimate": "",
        "basis": "",
    }
    if commit_tz:
        out["estimate"] = commit_tz.most_common(1)[0][0]
        out["basis"] = "commit timestamps (author's own clock)"
    elif samples >= 8:
        off, fit = estimate_offset(hours)
        out["estimate"] = _fmt_offset(off)
        out["basis"] = (
            f"rough (±2 h): daily rhythm of {samples} dated events, fit {fit:.0%}"
        )
    else:
        out["basis"] = "not enough dated activity"
    return out


def reverse_image_links(picture: str) -> dict[str, str]:
    """Search engines that look up a picture by URL (opened by the analyst)."""
    from urllib.parse import quote

    u = quote(picture, safe="")
    return {
        "Yandex": f"https://yandex.com/images/search?rpt=imageview&url={u}",
        "Bing": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{u}",
        "Google Lens": f"https://lens.google.com/uploadbyurl?url={u}",
    }


def username_candidates(full_name: str, limit: int = 12) -> list[str]:
    """Usual handle patterns for a person's name (shown, not auto-run)."""
    import unicodedata

    clean = unicodedata.normalize("NFKD", full_name or "")
    clean = "".join(c for c in clean if not unicodedata.combining(c))
    clean = clean.replace("\u0131", "i")  # Turkish dotless i
    parts = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in clean.split()]
    parts = [w for w in parts if w]
    if len(parts) < 2:
        return []
    first, last = parts[0], parts[-1]
    pats = [
        f"{first}{last}",
        f"{first}.{last}",
        f"{first}_{last}",
        f"{first}-{last}",
        f"{first[0]}{last}",
        f"{first[0]}.{last}",
        f"{last}{first}",
        f"{last}.{first}",
        f"{first}{last[0]}",
        f"{last}{first[0]}",
        f"{first}.{last[0]}",
        f"{first[0]}{last[0]}{last[1:]}",
    ]
    out = []
    for p in pats:
        if p not in out:
            out.append(p)
    return out[:limit]
