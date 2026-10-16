"""Pivot control for automatic lead following.

Every selector the analyst typed is a **root** (depth 0). A selector found in
a result for a depth-``d`` selector is depth ``d + 1``. Three guards keep the
investigation focused:

* **depth**  — tasks deeper than ``VEILED_PIVOT_DEPTH`` (default 2) are
  dropped: "username -> GitHub -> commit e-mail -> registrations" happens,
  crawling the whole internet does not
* **budget** — at most ``VEILED_PIVOT_BUDGET`` (default 40) new selectors per
  root, so one noisy source cannot flood the queue
* **quality** — leads that identify nobody are never followed: no-reply and
  role addresses (``noreply@``, ``info@``, ``support@``…), example / test
  domains, platform system accounts, very short or generic usernames,
  invalid phone numbers

Selectors are compared in canonical form (e-mails lower-case, phones in
E.164, usernames without ``@``), so ``+90 532 123 45 67`` and
``05321234567`` are the same lead. Tasks on the same selector (another
module for the same username) never count as a step.

State lives in the shared cache, so the web UI (/result) and
``veiled-eye scan`` behave the same.
"""

from __future__ import annotations

import os
import re
from typing import Any

from factories import result_cache

ROLE_LOCALPARTS = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "info",
    "support",
    "admin",
    "administrator",
    "contact",
    "hello",
    "help",
    "sales",
    "office",
    "webmaster",
    "postmaster",
    "abuse",
    "security",
    "privacy",
    "billing",
    "team",
    "mail",
    "email",
    "marketing",
    "press",
    "jobs",
    "careers",
    "hr",
    "notifications",
    "notification",
    "bounce",
    "mailer-daemon",
    "root",
}
JUNK_DOMAINS = re.compile(
    r"(^|\.)(example\.(com|org|net)|test|localhost|local|invalid|"
    r"users\.noreply\.github\.com|noreply\.github\.com|sentry\.io|"
    r"wixpress\.com|domain\.com|email\.com)$",
    re.I,
)
GENERIC_HANDLES = {
    "admin",
    "user",
    "test",
    "root",
    "guest",
    "info",
    "support",
    "null",
    "undefined",
    "none",
    "anonymous",
    "unknown",
    "default",
    "home",
    "login",
    "signup",
    "about",
    "contact",
    "help",
    "search",
    "share",
    "intent",
    "explore",
    "settings",
    "privacy",
    "terms",
    "api",
    "www",
    "status",
    "github",
    "twitter",
    "instagram",
    "facebook",
    "youtube",
    "tiktok",
    "linkedin",
    "reddit",
    "telegram",
    "web-flow",
    "dependabot",
    "actions",
    # URL path segments mistaken for handles (instagram.com/reel/...)
    "reel",
    "reels",
    "p",
    "tv",
    "stories",
    "story",
    "highlights",
    "accounts",
    "account",
    "watch",
    "channel",
    "channels",
    "c",
    "users",
    "profile",
    "profiles",
    "hashtag",
    "tags",
    "tag",
    "statuses",
    "i",
    "in",
    "pub",
    "company",
    "school",
    "groups",
    "group",
    "pages",
    "page",
    "events",
    "photo",
    "photos",
    "video",
    "videos",
    "post",
    "posts",
    "sharer",
    "embed",
    "oauth",
    "auth",
    "join",
    "invite",
    "s",
    "t",
    "u",
    "r",
    "m",
    "feed",
    "notifications",
    "messages",
    "direct",
    "trending",
    "discover",
    "music",
    "live",
    "shorts",
    "playlist",
    "results",
    "legal",
    "download",
    "app",
    "apps",
    "mobile",
    "nan",
    "true",
    "false",
}


def max_depth() -> int:
    try:
        return max(0, int(os.environ.get("VEILED_PIVOT_DEPTH", "2")))
    except ValueError:
        return 2


def budget() -> int:
    try:
        return max(1, int(os.environ.get("VEILED_PIVOT_BUDGET", "40")))
    except ValueError:
        return 40


def canonical(value: Any) -> str:
    """Comparable form of a selector (e-mail, phone, wallet, handle…)."""
    v = str(value or "").strip()
    if not v:
        return ""
    if "@" in v and not v.startswith("@"):
        return v.lower()
    digits = re.sub(r"[\s().\-]", "", v)
    if re.fullmatch(r"\+?\d{7,16}", digits):
        try:
            from factories.identity import normalize_phone

            e164 = normalize_phone(
                digits,
                None
                if digits.startswith("+")
                else os.environ.get("VEILED_PHONE_REGION", "TR"),
            )
            if e164:
                return e164
        except Exception:
            pass
        return digits
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
        return v.lower()
    if re.fullmatch(
        r"[13LMDT][1-9A-HJ-NP-Za-km-z]{25,40}|(bc1|ltc1)[a-z0-9]{20,90}", v
    ):
        return v  # base58 / bech32 wallets are case-sensitive
    return v.lstrip("@").lower()


_norm = canonical


def worth_following(value: Any) -> bool:
    """False for leads that identify nobody (role mailboxes, junk, generic)."""
    v = str(value or "").strip()
    if not v:
        return False
    if "@" in v and not v.startswith("@"):
        local, _, domain = v.lower().rpartition("@")
        if not local or not domain or "." not in domain:
            return False
        if local in ROLE_LOCALPARTS or local.startswith(
            ("noreply", "no-reply", "bounce")
        ):
            return False
        return not JUNK_DOMAINS.search(domain)
    digits = re.sub(r"[\s().\-]", "", v)
    if re.fullmatch(r"\+[\d\s().\-]+", v) and not re.fullmatch(r"\+\d{7,16}", digits):
        return False  # "+..." that cannot be a phone number
    if re.fullmatch(r"\+?\d{7,16}", digits):
        if canonical(v).startswith("+"):
            return True  # valid phone number
        if digits.startswith("+"):
            return False  # looks like a phone but is not a valid one
        # otherwise a numeric account ID (Instagram, Telegram…): handle rules
    handle = v.lstrip("@").lower()
    if len(handle) < 3 or handle in GENERIC_HANDLES:
        return False
    if handle.isdigit() and len(handle) < 5:
        return False
    return not re.fullmatch(r"[._\-]+", handle)


def _record(param: Any) -> dict:
    rec = result_cache.recall(f"pivot:{canonical(param)}")
    return rec if isinstance(rec, dict) else {}


def depth_of(param: Any) -> int:
    rec = _record(param)
    try:
        return int(rec.get("d", 0))
    except (TypeError, ValueError):
        return 0


def root_of(param: Any) -> str:
    return _record(param).get("root") or canonical(param)


def mark_root(param: Any) -> None:
    """A selector the analyst asked for: depth 0, whatever was seen before."""
    key = canonical(param)
    if key:
        result_cache.remember(f"pivot:{key}", {"d": 0, "root": key})
        result_cache.remember(f"pivotcount:{key}", 0)


def _claim(target: Any, depth: int, root: str) -> bool:
    """Register ``target`` at ``depth`` under ``root``; False if over budget."""
    key = canonical(target)
    rec = _record(target)
    if rec:
        if int(rec.get("d", 99)) > depth:
            result_cache.remember(
                f"pivot:{key}", {"d": depth, "root": rec.get("root") or root}
            )
        return True  # already known: following it again costs nothing
    used = result_cache.recall(f"pivotcount:{root}") or 0
    if int(used) >= budget():
        return False
    result_cache.remember(f"pivotcount:{root}", int(used) + 1)
    result_cache.remember(f"pivot:{key}", {"d": depth, "root": root})
    return True


def _param(result: list) -> str:
    for item in result or []:
        if isinstance(item, dict) and "param" in item:
            return str(item["param"])
    return ""


def limit(result: Any) -> Any:
    """Drop the result's tasks that are junk, too deep or over budget."""
    if not isinstance(result, list):
        return result
    tasks_item = next(
        (i for i in result if isinstance(i, dict) and isinstance(i.get("tasks"), list)),
        None,
    )
    if not tasks_item:
        return result
    source = _param(result)
    src_key = canonical(source)
    depth = depth_of(source)
    root = root_of(source)
    nxt = depth + 1
    keep, seen = [], set()
    for task in tasks_item["tasks"]:
        if not isinstance(task, dict):
            continue
        target = task.get("param")
        tkey = canonical(target)
        if not tkey:
            continue
        sig = (task.get("module"), tkey)
        if sig in seen:
            continue  # same module + same selector written two ways
        seen.add(sig)
        if tkey == src_key:
            keep.append(task)
            continue
        if nxt > max_depth() or not worth_following(target):
            continue
        if not _claim(target, nxt, root):
            continue
        task = dict(task)
        task["depth"] = nxt
        keep.append(task)
    tasks_item["tasks"] = keep
    return result
