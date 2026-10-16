"""Profile links -> (platform, handle).

Used to cross-check what one profile says about another: a GitHub bio
that links ``twitter.com/emrekybs8`` names a Twitter account of the same
person, which is stronger evidence than a username that merely exists on
Twitter.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# platform -> (host regex, path regex with the handle in group 1)
_RULES: list[tuple[str, str, str]] = [
    ("twitter", r"(^|\.)(twitter|x)\.com$", r"^/@?([A-Za-z0-9_]{1,15})/?$"),
    ("instagram", r"(^|\.)instagram\.com$", r"^/([A-Za-z0-9_.]{1,30})/?$"),
    ("github", r"(^|\.)github\.com$", r"^/([A-Za-z0-9-]{1,39})/?$"),
    ("gitlab", r"(^|\.)gitlab\.com$", r"^/([A-Za-z0-9_.-]{1,255})/?$"),
    ("reddit", r"(^|\.)reddit\.com$", r"^/(?:u|user)/([A-Za-z0-9_-]{3,20})/?"),
    ("telegram", r"^(t\.me|telegram\.me)$", r"^/([A-Za-z0-9_]{5,32})/?$"),
    ("tiktok", r"(^|\.)tiktok\.com$", r"^/@([A-Za-z0-9_.]{2,24})/?"),
    ("youtube", r"(^|\.)youtube\.com$", r"^/@([A-Za-z0-9_.-]{3,30})/?"),
    ("linkedin", r"(^|\.)linkedin\.com$", r"^/in/([A-Za-z0-9-]{3,100})/?"),
    ("facebook", r"(^|\.)facebook\.com$", r"^/([A-Za-z0-9.]{5,50})/?$"),
    ("medium", r"(^|\.)medium\.com$", r"^/@([A-Za-z0-9_.-]{1,50})/?"),
    ("keybase", r"(^|\.)keybase\.io$", r"^/([A-Za-z0-9_]{2,16})/?$"),
    ("bluesky", r"^bsky\.app$", r"^/profile/([A-Za-z0-9_.-]{3,253})/?"),
    ("twitch", r"(^|\.)twitch\.tv$", r"^/([A-Za-z0-9_]{4,25})/?$"),
    ("steam", r"(^|\.)steamcommunity\.com$", r"^/id/([A-Za-z0-9_-]{2,32})/?"),
    ("hackernews", r"^news\.ycombinator\.com$", r"^/user$"),
    ("stackoverflow", r"(^|\.)stackoverflow\.com$", r"^/users/\d+/([A-Za-z0-9-]+)/?"),
    ("pinterest", r"(^|\.)pinterest\.[a-z.]+$", r"^/([A-Za-z0-9_]{3,30})/?$"),
    ("soundcloud", r"(^|\.)soundcloud\.com$", r"^/([A-Za-z0-9_-]{3,25})/?$"),
    ("spotify", r"^open\.spotify\.com$", r"^/user/([A-Za-z0-9_.-]+)/?"),
    ("snapchat", r"(^|\.)snapchat\.com$", r"^/add/([A-Za-z0-9_.-]{3,15})/?"),
    ("vk", r"^(m\.)?vk\.com$", r"^/([A-Za-z0-9_.]{5,32})/?$"),
]

# first path segments that are pages, not people
_RESERVED = {
    "about",
    "explore",
    "home",
    "login",
    "signup",
    "settings",
    "search",
    "share",
    "intent",
    "i",
    "p",
    "reel",
    "reels",
    "stories",
    "watch",
    "channel",
    "c",
    "hashtag",
    "help",
    "privacy",
    "terms",
    "orgs",
    "topics",
    "features",
    "marketplace",
    "sponsors",
    "pricing",
    "events",
    "groups",
    "pages",
    "jobs",
    "company",
    "school",
    "feed",
    "notifications",
    "messages",
    "join",
    "download",
}

# modules that read a single profile of that platform
PLATFORM_MODULE = {
    "twitter": "twitter",
    "instagram": "instagram",
    "github": "github",
    "gitlab": "gitlab",
    "reddit": "reddit",
    "telegram": "telegram",
    "tiktok": "tiktok",
    "keybase": "keybase",
    "bluesky": "bluesky",
    "twitch": "twitch",
    "steam": "steam",
    "linkedin": "linkedin",
    "youtube": "youtube",
    "snapchat": "snapchat",
}


def profile_from_url(url: str) -> tuple[str, str] | None:
    """``https://x.com/emrekybs8`` -> ("twitter", "emrekybs8")."""
    u = str(url or "").strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    try:
        parsed = urlparse(u)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("mobile.")
    path = parsed.path or "/"
    for platform, host_rx, path_rx in _RULES:
        if not re.search(host_rx, host):
            continue
        if platform == "hackernews":
            m = re.search(r"(?:^|&)id=([A-Za-z0-9_-]{2,15})", parsed.query or "")
            return (platform, m.group(1)) if m else None
        m = re.match(path_rx, path)
        if not m:
            return None
        handle = m.group(1).lstrip("@")
        if handle.lower() in _RESERVED:
            return None
        return platform, handle
    return None


def profiles_in(values) -> list[tuple[str, str]]:
    """Every distinct (platform, handle) found in a list of URLs / texts."""
    out: list[tuple[str, str]] = []
    for v in values or []:
        for url in re.findall(r"(?:https?://)?[\w.-]+\.[a-z]{2,}/[^\s\"'<>)]*", str(v)):
            hit = profile_from_url(url)
            if hit and hit not in out:
                out.append(hit)
    return out
