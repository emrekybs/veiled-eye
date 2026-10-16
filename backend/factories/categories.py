"""Platform categories for the social-profile grid.

Every profile ``social`` entry leaving the API gets a ``category`` and a
``cat-<kind>`` class appended to its icon.  The Veiled Eye UI draws a badge from
that class (``tools/ui_build/veiled.css``) so each card says whether the
account sits on an underground forum, a social network, a forum, a dev site...

Order of evidence: the entry's own ``category`` (WhatsMyName / user-scanner /
maigret tags) -> the module that found it (dark-sherlock, Ahmia, dark web)
-> a curated platform list -> "other".
"""

from __future__ import annotations

import re
from typing import Any

KINDS = (
    "underground",
    "forum",
    "social",
    "messaging",
    "dev",
    "gaming",
    "video",
    "music",
    "art",
    "dating",
    "finance",
    "shopping",
    "blog",
    "identity",
    "professional",
    "other",
)

UNDERGROUND_MODULES = {"darksherlock", "ahmia", "darkweb"}

# Known cybercrime / hacking forums and markets (lower-case, no spaces)
UNDERGROUND = {
    "cracked",
    "crackedto",
    "crackedio",
    "nulled",
    "nulledto",
    "xss",
    "xssis",
    "exploit",
    "exploitin",
    "breachforums",
    "breached",
    "breachedvc",
    "darkforums",
    "darkforumsst",
    "leakbase",
    "raidforums",
    "dread",
    "hackforums",
    "sinister",
    "sinisterly",
    "blackhatworld",
    "bhf",
    "bhfio",
    "dark2web",
    "crdpro",
    "carder",
    "carders",
    "omertà",
    "omerta",
    "exploitforum",
    "ramp",
    "rampforum",
    "altenen",
    "dublikat",
    "verified",
    "lolz",
    "lolzteam",
    "zelenka",
    "antichat",
    "probiv",
    "xreactor",
    "patched",
    "cracking",
    "crackingking",
    "nulledbb",
    "hackingforums",
    "breachstars",
    "breachstarsv2",
    "leakzone",
    "sqli",
    "blackforums",
    "demonforums",
    "bidencash",
}
CURATED = {
    "social": {
        "twitter",
        "x",
        "instagram",
        "facebook",
        "tiktok",
        "snapchat",
        "bluesky",
        "mastodon",
        "vk",
        "vkontakte",
        "threads",
        "pinterest",
        "tumblr",
        "ok",
        "odnoklassniki",
        "weibo",
        "gab",
        "parler",
        "truthsocial",
        "myspace",
        "bereal",
        "linktree",
        "aboutme",
        "gettr",
        "minds",
    },
    "messaging": {
        "telegram",
        "discord",
        "skype",
        "signal",
        "whatsapp",
        "kik",
        "icq",
        "viber",
        "wechat",
        "line",
    },
    "forum": {
        "reddit",
        "quora",
        "4chan",
        "hackernews",
        "ycombinator",
        "disqus",
        "lobsters",
        "slashdot",
        "kaskus",
        "tapatalk",
    },
    "dev": {
        "github",
        "gitlab",
        "bitbucket",
        "stackoverflow",
        "stackexchange",
        "npm",
        "pypi",
        "dockerhub",
        "docker",
        "codepen",
        "replit",
        "leetcode",
        "hackerone",
        "bugcrowd",
        "tryhackme",
        "hackthebox",
        "kaggle",
        "sourceforge",
        "devto",
        "codeberg",
        "gitea",
        "huggingface",
        "gitsniff",
    },
    "gaming": {
        "steam",
        "xbox",
        "playstation",
        "psn",
        "roblox",
        "minecraft",
        "epicgames",
        "chess",
        "lichess",
        "battlenet",
        "osu",
        "speedrun",
        "nintendo",
    },
    "video": {
        "youtube",
        "twitch",
        "kick",
        "vimeo",
        "dailymotion",
        "rumble",
        "odysee",
        "trovo",
    },
    "music": {
        "spotify",
        "soundcloud",
        "bandcamp",
        "lastfm",
        "mixcloud",
        "applemusic",
        "deezer",
    },
    "art": {
        "behance",
        "dribbble",
        "artstation",
        "deviantart",
        "picsart",
        "flickr",
        "500px",
        "unsplash",
        "vsco",
        "figma",
    },
    "dating": {"tinder", "bumble", "badoo", "okcupid", "hinge", "grindr", "pof"},
    "finance": {
        "venmo",
        "paypal",
        "cashapp",
        "patreon",
        "kofi",
        "buymeacoffee",
        "coinbase",
        "binance",
        "crypto",
        "opensea",
        "etherscan",
    },
    "shopping": {
        "ebay",
        "etsy",
        "amazon",
        "aliexpress",
        "mercadolibre",
        "depop",
        "poshmark",
        "vinted",
    },
    "blog": {
        "medium",
        "blogspot",
        "blogger",
        "wordpress",
        "substack",
        "livejournal",
        "carrd",
        "ghost",
        "hashnode",
        "telegraph",
    },
    "identity": {
        "keybase",
        "gravatar",
        "pgp",
        "openpgp",
        "wayback",
        "phone",
        "hudsonrock",
    },
    "professional": {
        "linkedin",
        "xing",
        "angellist",
        "crunchbase",
        "upwork",
        "fiverr",
        "freelancer",
        "crosslinked",
    },
}
_CURATED_INDEX = {name: kind for kind, names in CURATED.items() for name in names}

# Category labels coming from WhatsMyName / user-scanner / maigret tags
TAG_MAP = {
    "social": "social",
    "community": "forum",
    "forum": "forum",
    "hobby": "forum",
    "political": "forum",
    "coding": "dev",
    "tech": "dev",
    "dev": "dev",
    "hacking": "underground",
    "carding": "underground",
    "darkweb": "underground",
    "gaming": "gaming",
    "games": "gaming",
    "video": "video",
    "streaming": "video",
    "creator": "video",
    "music": "music",
    "art": "art",
    "images": "art",
    "photo": "art",
    "creative": "art",
    "design": "art",
    "dating": "dating",
    "finance": "finance",
    "crypto": "finance",
    "donation": "finance",
    "shopping": "shopping",
    "news": "blog",
    "blog": "blog",
    "business": "professional",
    "jobs": "professional",
    "professional": "professional",
    "messaging": "messaging",
    "chat": "messaging",
    "email": "identity",
}

DISPLAY = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "twitter": "Twitter / X",
    "x": "Twitter / X",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "reddit": "Reddit",
    "linkedin": "LinkedIn",
    "facebook": "Facebook",
    "telegram": "Telegram",
    "snapchat": "Snapchat",
    "steam": "Steam",
    "twitch": "Twitch",
    "keybase": "Keybase",
    "mastodon": "Mastodon",
    "bluesky": "Bluesky",
    "spotify": "Spotify",
    "hackernews": "Hacker News",
    "kick": "Kick",
    "stackexchange": "Stack Exchange",
    "gravatar": "Gravatar",
    "pinterest": "Pinterest",
    "discord": "Discord",
    "vimeo": "Vimeo",
    "soundcloud": "SoundCloud",
    "medium": "Medium",
}


def _key(value: Any) -> str:
    v = str(value or "").lower()
    v = re.sub(r"^linkedin - .*", "linkedin", v)
    v = re.sub(r"\(.*?\)", "", v)
    v = re.sub(
        r"\.(com|net|org|io|to|is|in|st|vc|me|tv|gg|co|cc|su|ru)$", "", v.strip()
    )
    return re.sub(r"[^a-z0-9]+", "", v)


def classify(
    name: str, *, module: str = "", tag: str | None = None, url: str = ""
) -> str:
    key = _key(name)
    if key in UNDERGROUND:
        return "underground"
    if module in UNDERGROUND_MODULES:
        return "underground"
    if ".onion" in str(url or ""):
        return "underground"
    if key in _CURATED_INDEX:
        return _CURATED_INDEX[key]
    for t in re.split(r"[,/|;]", str(tag or "").lower()):
        mapped = TAG_MAP.get(t.strip())
        if mapped:
            return mapped
    host = _key(re.sub(r"^https?://(www\.)?", "", str(url or "")).split("/")[0])
    if host in UNDERGROUND:
        return "underground"
    if host in _CURATED_INDEX:
        return _CURATED_INDEX[host]
    return "other"


def _decorate_social(entry: dict, module: str) -> None:
    name = entry.get("name") or entry.get("source") or ""
    kind = classify(
        name,
        module=str(entry.get("source") or module or "").lower(),
        tag=entry.get("category"),
        url=entry.get("url") or "",
    )
    entry["category"] = kind
    display = DISPLAY.get(_key(name))
    if display:
        entry["name"] = display
    icon = re.sub(r"\s*\bcat-[a-z]+\b", "", str(entry.get("icon") or "")).strip()
    entry["icon"] = f"{icon or 'fas fa-globe'} cat-{kind}"


def decorate(result: Any) -> Any:
    """Add categories to every profile social entry (in place, never raises)."""
    try:
        if not isinstance(result, list):
            return result
        module = ""
        for item in result:
            if isinstance(item, dict) and "module" in item:
                module = str(item["module"])
            if isinstance(item, dict) and isinstance(item.get("profile"), list):
                for entry in item["profile"]:
                    if isinstance(entry, dict) and isinstance(
                        entry.get("social"), list
                    ):
                        for social in entry["social"]:
                            if isinstance(social, dict):
                                _decorate_social(social, module)
    except Exception:
        pass
    return result
