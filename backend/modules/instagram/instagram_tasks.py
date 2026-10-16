#!/usr/bin/env python
"""Instagram module — public profile data, no password ever stored.

Sources, tried in order. A source that answers with a login wall or rate
limit is put on a 10-minute cool-down shared by all workers, so the next
lookups go straight to the next one:

1. ``public-api``         web_profile_info, anonymous (name, bio, counters,
                          latest 12 posts)
2. ``public-api+cookie``  the same endpoint with your own session cookies
3. ``profile-page``       og: meta tags of instagram.com/<user>, anonymous
                          (name, counters, avatar; works when the API is closed)

With session cookies (API keys page: ``instagram_sessionid`` and friends, or
paste a Cookie-Editor export into ``instagram_cookies``) the module also
reads, from the mobile API, what the profile shows publicly:

* business contact: category, public e-mail / phone, address, coordinates
* bio links and pronouns
* the latest posts with their place names and coordinates (for the map),
  tagged users, likes and comments

and resolves a numeric Instagram user ID to the username.

The output keeps the original shape (graphic: instagram, postslist,
postsloc, hashtags, mentions, tagged, hour, week, mediatype, photos) so the
Instagram cards render unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from html import unescape

import requests
from factories import result_cache
from factories.configuration import api_keys_search
from factories.cookie_utils import parse_cookie_box
from factories.helpers import analize_rrss
from factories.task_wrapper import module_task

PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
# public web app id used by instagram.com for logged-out visitors
APP_ID = "936619743392459"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": APP_ID,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
}
COOLDOWN = 600
ANDROID_HEADERS = {
    "User-Agent": (
        "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; "
        "SM-G991B; o1s; exynos2100; en_US; 458229237)"
    ),
    "X-IG-App-ID": "567067343352427",
    "Accept-Language": "en-US",
}
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
HASHTAG_RE = re.compile(r"(?<!\w)#(\w+)")
MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9._]{1,30})")
TIMEOUT = 20
MAX_POSTS = 12


class RateLimited(Exception):
    """Instagram answered with a login wall / rate limit."""


class CookieExpired(Exception):
    """The configured session cookie is no longer valid."""


def _handle(param: str) -> str:
    h = str(param or "").strip()
    h = re.sub(r"^https?://(www\.)?instagram\.com/", "", h).strip("/").lstrip("@")
    h = h.split("/")[0].split("?")[0]
    if "@" in h:  # e-mail given: try the local part
        h = h.split("@")[0]
    if not HANDLE_RE.match(h):
        raise Exception(f"warn: '{param}' is not a valid Instagram username or ID")
    return h


# Cookies read from the API keys page (``instagram_<name>``). ``sessionid``
# is what authenticates; the others make the request look like the browser
# session it came from.
COOKIE_NAMES = (
    "sessionid",
    "ds_user_id",
    "csrftoken",
    "mid",
    "ig_did",
    "datr",
    "ps_l",
    "ps_n",
    "wd",
    "rur",
)


def session_cookies() -> dict:
    """Instagram cookies from the API keys page (fields win over the box)."""
    jar = {
        k: v
        for k, v in parse_cookie_box(api_keys_search("instagram_cookies")).items()
        if k in COOKIE_NAMES
    }
    for name in COOKIE_NAMES:
        value = api_keys_search(f"instagram_{name}")
        if value:
            jar.update(
                parse_cookie_box(value) if name == "sessionid" else {name: str(value)}
            )
    return jar if jar.get("sessionid") else {}


def _session_cookie() -> str:
    jar = session_cookies()
    return "; ".join(f"{k}={jar[k]}" for k in COOKIE_NAMES if k in jar)


def _auth_headers(base: dict, cookie: str) -> dict:
    headers = dict(base, Cookie=cookie)
    m = re.search(r"csrftoken=([^;]+)", cookie)
    if m:
        headers["X-CSRFToken"] = m.group(1)
    return headers


# ---------------------------------------------------------------------------
# collectors -> one normalised dict
# ---------------------------------------------------------------------------
def _count(node: dict, *keys: str) -> int:
    for k in keys:
        v = node.get(k)
        if isinstance(v, dict) and "count" in v:
            return int(v.get("count") or 0)
    return 0


def fetch_public(
    username: str, session: requests.Session | None = None, cookie: str = ""
) -> dict:
    s = session or requests.Session()
    headers = _auth_headers(HEADERS, cookie) if cookie else HEADERS
    r = s.get(
        PROFILE_URL, params={"username": username}, headers=headers, timeout=TIMEOUT
    )
    if r.status_code == 404:
        raise Exception("warn: Profile not found")
    if cookie and r.status_code in (401, 403) and "login_required" in (r.text or ""):
        raise CookieExpired()
    if r.status_code in (401, 403, 429) or "login" in r.url:
        raise RateLimited(f"HTTP {r.status_code}")
    r.raise_for_status()
    try:
        user = (r.json().get("data") or {}).get("user")
    except ValueError:
        raise RateLimited("non-JSON answer (login wall)") from None
    if not user:
        raise Exception("warn: Profile not found")

    posts = []
    media = user.get("edge_owner_to_timeline_media") or {}
    for edge in (media.get("edges") or [])[:MAX_POSTS]:
        n = edge.get("node") or {}
        caps = (n.get("edge_media_to_caption") or {}).get("edges") or []
        caption = (caps[0].get("node") or {}).get("text", "") if caps else ""
        tagged = [
            ((e.get("node") or {}).get("user") or {}).get("username")
            for e in ((n.get("edge_media_to_tagged_user") or {}).get("edges") or [])
        ]
        ts = n.get("taken_at_timestamp")
        posts.append(
            {
                "date": datetime.fromtimestamp(ts, UTC) if ts else None,
                "likes": _count(n, "edge_liked_by", "edge_media_preview_like"),
                "comments": _count(n, "edge_media_to_comment"),
                "caption": caption or "",
                "acc_caption": n.get("accessibility_caption") or "",
                "typename": n.get("__typename") or "",
                "url": n.get("display_url") or "",
                "tagged": [t for t in tagged if t],
                "location": (n.get("location") or {}).get("name") or "",
            }
        )

    return {
        "full_name": user.get("full_name") or "",
        "username": user.get("username") or username,
        "userid": user.get("id") or "",
        "biography": user.get("biography") or "",
        "external_url": user.get("external_url") or "",
        "is_private": bool(user.get("is_private")),
        "is_business": bool(user.get("is_business_account")),
        "is_verified": bool(user.get("is_verified")),
        "followers": _count(user, "edge_followed_by"),
        "followees": _count(user, "edge_follow"),
        "mediacount": int(media.get("count") or 0),
        "igtvcount": _count(user, "edge_felix_video_timeline"),
        "pic": user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        "posts": posts,
        "via": "public profile" + (" (session cookie)" if cookie else ""),
    }


_NUM = re.compile(r"([\d.,]+)\s*([KkMmBb]?)")


def _num(text: str) -> int:
    m = _NUM.match(text.strip())
    if not m:
        return 0
    value, unit = m.groups()
    if unit:
        n = float(value.replace(",", ""))
        return int(n * {"k": 1e3, "m": 1e6, "b": 1e9}[unit.lower()])
    return int(re.sub(r"[.,]", "", value) or 0)


def _meta(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', html
    ) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"', html
    )
    return unescape(m.group(1)) if m else ""


def fetch_page(username: str, session: requests.Session | None = None) -> dict:
    """og: meta tags of the public profile page (counters, name, avatar)."""
    s = session or requests.Session()
    headers = {k: v for k, v in HEADERS.items() if not k.startswith("X-")}
    headers["Accept"] = "text/html,application/xhtml+xml"
    r = s.get(
        f"https://www.instagram.com/{username}/", headers=headers, timeout=TIMEOUT
    )
    if r.status_code == 404:
        raise Exception("warn: Profile not found")
    if r.status_code in (401, 403, 429) or "accounts/login" in r.url:
        raise RateLimited(f"HTTP {r.status_code}")
    r.raise_for_status()
    desc = _meta(r.text, "og:description") or _meta(r.text, "description")
    # "1,234 Followers, 56 Following, 78 Posts - See Instagram photos and
    #  videos from Name (@user)"
    m = re.search(
        r"([\d.,]+\s*[KkMmBb]?)\s+Followers?,\s*([\d.,]+\s*[KkMmBb]?)\s+Following,"
        r"\s*([\d.,]+\s*[KkMmBb]?)\s+Posts?",
        desc,
    )
    if not m:
        raise RateLimited("profile page without public counters")
    title = _meta(r.text, "og:title")
    name = re.sub(r"\s*\(@[^)]*\).*$", "", title).strip()
    bio = ""
    bio_m = re.search(r"on Instagram:\s*\"(.*)\"\s*$", desc, re.S)
    if bio_m:
        bio = bio_m.group(1).strip()
    return {
        "full_name": name,
        "username": username,
        "userid": "",
        "biography": bio,
        "external_url": "",
        "is_private": False,
        "is_business": False,
        "is_verified": False,
        "followers": _num(m.group(1)),
        "followees": _num(m.group(2)),
        "mediacount": _num(m.group(3)),
        "igtvcount": 0,
        "pic": _meta(r.text, "og:image"),
        "posts": [],
        "via": "public profile page",
    }


def resolve_user_id(user_id: str, cookie: str = "") -> str:
    """Numeric Instagram user ID -> username (mobile API)."""
    headers = _auth_headers(ANDROID_HEADERS, cookie) if cookie else ANDROID_HEADERS
    try:
        r = requests.get(
            f"https://i.instagram.com/api/v1/users/{user_id}/info/",
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            username = ((r.json() or {}).get("user") or {}).get("username")
            if username:
                return username
        if r.status_code == 404:
            raise Exception(f"warn: No Instagram account with ID {user_id}")
    except requests.RequestException:
        pass
    raise Exception(
        "warn: Resolving an Instagram user ID needs your session cookie "
        "(instagram_sessionid or instagram_cookies on the API keys page)."
    )


def _mobile_get(path: str, cookie: str, params: dict | None = None) -> dict:
    r = requests.get(
        f"https://i.instagram.com/api/v1/{path}",
        params=params,
        headers=_auth_headers(ANDROID_HEADERS, cookie),
        timeout=TIMEOUT,
    )
    if r.status_code in (401, 403) and "login_required" in (r.text or ""):
        raise CookieExpired()
    if r.status_code in (401, 403, 429):
        raise RateLimited(f"HTTP {r.status_code}")
    r.raise_for_status()
    return r.json() or {}


def _media_type(item: dict) -> str:
    return {1: "GraphImage", 2: "GraphVideo", 8: "GraphSidecar"}.get(
        item.get("media_type"), ""
    )


def enrich_with_session(d: dict, cookie: str) -> dict:
    """Public business contact, bio links and post locations (mobile API).

    Best effort: any failure leaves ``d`` as it is and is noted in ``notes``.
    """
    notes = d.setdefault("notes", [])
    uid = d.get("userid")
    if not uid:
        return d
    try:
        u = _mobile_get(f"users/{uid}/info/", cookie).get("user") or {}
    except CookieExpired:
        notes.append("session cookie expired — export it again")
        return d
    except (RateLimited, requests.RequestException, ValueError) as exc:
        notes.append(f"profile details unavailable ({exc})")
        u = {}
    phone = u.get("contact_phone_number") or (
        f"+{u['public_phone_country_code']} {u['public_phone_number']}"
        if u.get("public_phone_number") and u.get("public_phone_country_code")
        else ""
    )
    address = ", ".join(
        str(x) for x in (u.get("address_street"), u.get("zip"), u.get("city_name")) if x
    )
    d["contact"] = {
        "category": u.get("category") or u.get("business_category_name") or "",
        "email": u.get("public_email") or "",
        "phone": phone,
        "address": address,
        "lat": u.get("latitude"),
        "lng": u.get("longitude"),
        "pronouns": ", ".join(u.get("pronouns") or []),
        "bio_links": [
            link.get("url")
            for link in (u.get("bio_links") or [])
            if isinstance(link, dict) and link.get("url")
        ],
    }
    if d.get("is_private"):
        return d
    try:
        feed = _mobile_get(f"feed/user/{uid}/", cookie, {"count": MAX_POSTS})
    except (CookieExpired, RateLimited, requests.RequestException, ValueError) as exc:
        notes.append(f"posts with locations unavailable ({exc})")
        return d
    posts = []
    for it in (feed.get("items") or [])[:MAX_POSTS]:
        loc = it.get("location") or {}
        cands = ((it.get("image_versions2") or {}).get("candidates")) or []
        ts = it.get("taken_at")
        posts.append(
            {
                "date": datetime.fromtimestamp(ts, UTC) if ts else None,
                "likes": int(it.get("like_count") or 0),
                "comments": int(it.get("comment_count") or 0),
                "caption": ((it.get("caption") or {}).get("text")) or "",
                "acc_caption": it.get("accessibility_caption") or "",
                "typename": _media_type(it),
                "url": cands[0].get("url", "") if cands else "",
                "tagged": [
                    ((t.get("user") or {}).get("username"))
                    for t in ((it.get("usertags") or {}).get("in") or [])
                    if (t.get("user") or {}).get("username")
                ],
                "location": loc.get("name") or "",
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
            }
        )
    if posts:
        d["posts"] = posts
    return d


def collect(username: str) -> dict:
    cookie = _session_cookie()
    chain = [("public-api", lambda: fetch_public(username))]
    if cookie:
        chain.append(
            ("public-api+cookie", lambda: fetch_public(username, cookie=cookie))
        )
    chain.append(("profile-page", lambda: fetch_page(username)))

    tried = []
    for name, fn in chain:
        if result_cache.cooling(f"instagram:{name}"):
            tried.append(f"{name} (cooling down)")
            continue
        try:
            d = fn()
        except CookieExpired:
            tried.append(f"{name} (session cookie expired)")
            continue
        except RateLimited as exc:
            result_cache.cooldown(f"instagram:{name}", COOLDOWN)
            tried.append(f"{name} (blocked: {exc})")
            continue
        except requests.RequestException as exc:
            tried.append(f"{name} (network: {type(exc).__name__})")
            continue
        if cookie:
            d = enrich_with_session(d, cookie)
        return d
    hint = (
        ""
        if cookie
        else " Adding your Instagram session cookies on the API keys page "
        "usually fixes this (see docs/COOKIES.md)."
    )
    raise Exception(
        "warn: Instagram blocked every free source for now: "
        + "; ".join(tried)
        + "."
        + hint
    )


# ---------------------------------------------------------------------------
# output (unchanged shape)
# ---------------------------------------------------------------------------
def build(username: str, d: dict, from_m: str = "Initial") -> list[dict]:
    link = "Instagram"
    profile: list[dict] = []
    tasks: list[dict] = []
    timeline: list[dict] = []

    def node(name, title, subtitle, icon, **extra):
        item = {
            "name-node": name,
            "title": title,
            "subtitle": subtitle,
            "icon": icon,
            "link": link,
        }
        item.update(extra)
        return item

    gather = [
        node("Instagram", "Instagram", d["via"], "fab fa-instagram"),
        node("Instname", "Name", d["full_name"], "fas fa-user"),
        node("InstPosts", "Posts", d["mediacount"], "fas fa-photo-video"),
        node("InstIGTV", "IGTV", d["igtvcount"], "fas fa-tv"),
        node("InstFollowers", "Followers", d["followers"], "fas fa-users"),
        node("InstFollowing", "Following", d["followees"], "fas fa-users"),
        {
            "name-node": "InstAvatar",
            "title": "Avatar",
            "picture": d["pic"],
            "subtitle": "",
            "link": link,
        },
        node("InstBio", "Bio", d["biography"], "fas fa-heart"),
        node("InstURL", "URL", d["external_url"], "fas fa-code"),
        node("InstPrivate", "Private account", d["is_private"], "fas fa-user-shield"),
        node("InstUsername", "Username", d["username"], "fas fa-user"),
        node("InstUserID", "User ID", d["userid"], "fas fa-user-circle"),
        node("InstBuss", "Business account", d["is_business"], "fas fa-building"),
        node("InstVerified", "Verified", d["is_verified"], "fas fa-certificate"),
    ]
    contact = d.get("contact") or {}
    for key, title, icon in (
        ("category", "Category", "fas fa-tag"),
        ("email", "Public e-mail", "fas fa-envelope"),
        ("phone", "Public phone", "fas fa-phone"),
        ("address", "Address", "fas fa-map-marker-alt"),
        ("pronouns", "Pronouns", "fas fa-user-tag"),
    ):
        if contact.get(key):
            gather.append(node(f"Inst-{key}", title, contact[key], icon))
    for i, url in enumerate(contact.get("bio_links") or []):
        gather.append(node(f"InstLink{i}", "Bio link", url, "fas fa-link", help=url))
        profile.append({"url": url})
    if contact.get("email"):
        profile.append({"email": contact["email"]})
    if contact.get("phone"):
        profile.append({"phone": contact["phone"]})
    if contact.get("address"):
        profile.append({"location": contact["address"]})
    if contact.get("lat") and contact.get("lng"):
        profile.append(
            {
                "geo": {
                    "Caption": "Instagram",
                    "Accessibility": "business address",
                    "Latitude": contact["lat"],
                    "Longitude": contact["lng"],
                    "Name": contact.get("address") or "Business address",
                    "Time": "",
                }
            }
        )
    if d["full_name"]:
        profile.append({"name": d["full_name"]})
    if d["pic"]:
        profile.append({"photos": [{"picture": d["pic"], "title": "Instagram"}]})
    if d["biography"]:
        profile.append({"bio": d["biography"]})
        analyze = analize_rrss(d["biography"])
        profile.extend(analyze.get("url", []))
        tasks.extend(analyze.get("tasks", []))
    if d["external_url"]:
        profile.append({"url": d["external_url"]})
    profile.append(
        {
            "social": [
                {
                    "name": "Instagram",
                    "url": f"https://instagram.com/{d['username']}",
                    "icon": "fab fa-instagram",
                    "source": "Instagram",
                    "username": d["username"],
                }
            ]
        }
    )

    photos = [node("Instagram", "Instagram", "", "fab fa-instagram")]
    s_lk, s_cm, hashtags_t, mentions_t, tagged_t, weeks, hours = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    kinds = Counter()
    captions, acc_captions, postloc = [], [], []
    for i, post in enumerate(d["posts"]):
        s_lk.append({"name": str(i), "value": str(post["likes"])})
        s_cm.append({"name": str(i), "value": str(post["comments"])})
        hashtags_t += HASHTAG_RE.findall(post["caption"])
        mentions_t += MENTION_RE.findall(post["caption"])
        tagged_t += post["tagged"]
        if post["caption"]:
            captions.append(post["caption"])
        if post["acc_caption"]:
            acc_captions.append(post["acc_caption"])
        if post["location"]:
            postloc.append({"name": post["location"], "value": 1})
            if post.get("lat") and post.get("lng"):
                profile.append(
                    {
                        "geo": {
                            "Caption": "Instagram",
                            "Accessibility": "post location",
                            "Latitude": post["lat"],
                            "Longitude": post["lng"],
                            "Name": post["location"],
                            "Time": str(post["date"].replace(tzinfo=None))
                            if post.get("date")
                            else "",
                        }
                    }
                )
        if post["date"]:
            weeks.append(post["date"].strftime("%A"))
            hours.append(post["date"].strftime("%H"))
            if i == 0:
                timeline.append(
                    {
                        "date": str(post["date"].replace(tzinfo=None)),
                        "action": "Instagram : Last Post",
                        "icon": "fa-instagram",
                    }
                )
        kinds[post["typename"]] += 1
        if post["typename"] == "GraphImage" and post["url"]:
            photos.append(
                {
                    "name-node": f"Inst{i}",
                    "title": f"Image{i}",
                    "picture": post["url"],
                    "subtitle": "",
                    "link": link,
                }
            )

    def counted(items):
        return [{"label": k, "value": v} for k, v in Counter(items).items()]

    hour_c, week_c = Counter(hours), Counter(weeks)
    hourset = [
        {"name": f"{h:02d}", "value": hour_c.get(f"{h:02d}", 0)} for h in range(24)
    ]
    weekset = [
        {"name": day, "value": week_c.get(day, 0)}
        for day in "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()
    ]
    mediatype = [
        {"name": "Images", "value": str(kinds["GraphImage"])},
        {"name": "Sidecar", "value": str(kinds["GraphSidecar"])},
        {"name": "Videos", "value": str(kinds["GraphVideo"])},
    ]
    profile.append(
        {
            "presence": [
                {
                    "name": "instagram",
                    "children": [
                        {"name": "followers", "value": int(d["followers"])},
                        {"name": "following", "value": int(d["followees"])},
                    ],
                }
            ]
        }
    )

    graphic = [
        {"instagram": gather},
        {
            "postslist": [
                {"name": "Likes", "series": s_lk},
                {"name": "Comments", "series": s_cm},
            ]
        },
        {"postsloc": postloc},
        {"hashtags": counted(hashtags_t)},
        {"mentions": counted(mentions_t)},
        {"tagged": counted(tagged_t)},
        {"hour": hourset},
        {"week": weekset},
        {"mediatype": mediatype},
        {"photos": photos},
    ]
    return [
        {"module": "instagram"},
        {"param": username},
        {"validation": "no" if from_m == "Initial" else "soft"},
        {
            "raw": {
                "captions": captions,
                "acc_captions": acc_captions,
                "source": d["via"],
                "notes": d.get("notes") or [],
            }
        },
        {"graphic": graphic},
        {"profile": profile},
        {"timeline": timeline},
        {"tasks": tasks},
    ]


@module_task(module_name="instagram", dev_mode_sleep=3)
def p_instagram(username, from_m="Initial"):
    handle = _handle(username)
    if handle.isdigit() and len(handle) >= 5:  # numeric Instagram user ID
        handle = resolve_user_id(handle, _session_cookie())
    return build(handle, collect(handle), from_m)


t_instagram = p_instagram

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("username")
    print(
        json.dumps(
            t_instagram(ap.parse_args().username, dev_mode=False), indent=2, default=str
        )
    )
