"""Instagram source chain: cookie, profile-page fallback, cool-downs, user IDs."""

import json
from unittest.mock import MagicMock, patch

import pytest
from factories import result_cache
from modules.instagram import instagram_tasks as ig

PAGE = """<html><head>
<meta property="og:title" content="Tail Mon (@tailmon) &#x2022; Instagram photos and videos" />
<meta property="og:description" content="1.2K Followers, 80 Following, 34 Posts - See Instagram photos and videos from Tail Mon (@tailmon)" />
<meta property="og:image" content="https://cdn/pic.jpg" />
</head></html>"""


def _resp(status=200, payload=None, text="", url="https://www.instagram.com/x/"):
    r = MagicMock()
    r.status_code = status
    r.url = url
    r.text = text
    r.json.return_value = payload if payload is not None else {}
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    keys = tmp_path / "apikeys.json"
    monkeypatch.setenv("VEILED_APIKEYS", str(keys))
    monkeypatch.setenv("VEILED_CACHE", "memory")
    result_cache.clear_memory()
    yield keys


def _set_keys(path, **values):
    from factories.configuration import api_keys_read, api_keys_write

    items = api_keys_read()
    for item in items:
        if item["name"] in values:
            item["key"] = values[item["name"]]
    api_keys_write(items)


def sec(out, key):
    return next(e[key] for e in out if key in e)


def test_new_key_field_is_added_to_existing_files(_env):
    _env.write_text(json.dumps([{"id": 1, "name": "brave_key", "key": "x"}]))
    from factories.configuration import api_keys_read

    names = [i["name"] for i in api_keys_read()]
    assert "instagram_sessionid" in names and "instagram_cookies" in names
    assert "brave_key" in names


def test_profile_page_fallback_when_api_blocked():
    def get(url, **kw):
        if "web_profile_info" in url:
            return _resp(401)
        return _resp(200, text=PAGE)

    with patch.object(ig.requests.Session, "get", side_effect=get):
        out = ig.t_instagram("tailmon", dev_mode=False)
    nodes = {n["title"]: n["subtitle"] for n in sec(out, "graphic")[0]["instagram"]}
    assert (
        nodes["Followers"] == 1200 and nodes["Following"] == 80 and nodes["Posts"] == 34
    )
    assert {"name": "Tail Mon"} in sec(out, "profile")
    assert sec(out, "raw")["source"] == "public profile page"
    assert result_cache.cooling("instagram:public-api")


def test_cooling_source_is_skipped():
    result_cache.cooldown("instagram:public-api", 600)
    calls = []

    def get(url, **kw):
        calls.append(url)
        return _resp(200, text=PAGE)

    with patch.object(ig.requests.Session, "get", side_effect=get):
        ig.t_instagram("tailmon", dev_mode=False)
    assert not any("web_profile_info" in c for c in calls)


def test_session_cookie_is_used_and_accepts_cookie_editor_json(_env):
    export = json.dumps(
        [
            {"name": "sessionid", "value": "S1"},
            {"name": "csrftoken", "value": "C1"},
            {"name": "other", "value": "x"},
        ]
    )
    _set_keys(_env, instagram_sessionid=export)
    assert ig._session_cookie() == "sessionid=S1; csrftoken=C1"
    _set_keys(_env, instagram_sessionid="RAWVALUE")
    assert ig._session_cookie() == "sessionid=RAWVALUE"

    seen = []

    def get(url, headers=None, **kw):
        seen.append(headers.get("Cookie") if headers else None)
        if len(seen) == 1:
            return _resp(429)
        return _resp(200, {"data": {"user": {"username": "tailmon", "full_name": "T"}}})

    with (
        patch.object(ig.requests.Session, "get", side_effect=get),
        patch.object(ig.requests, "get", return_value=_resp(500)),
    ):
        out = ig.t_instagram("tailmon", dev_mode=False)
    assert seen == [None, "sessionid=RAWVALUE"]
    assert sec(out, "raw")["source"] == "public profile (session cookie)"


def test_everything_blocked_explains_and_suggests_cookie():
    with patch.object(ig.requests.Session, "get", return_value=_resp(429)):
        out = ig.t_instagram("tailmon", dev_mode=False)
    raw = sec(out, "raw")[0]
    assert raw["status"] == "Warning"
    assert "public-api" in raw["reason"] and "COOKIES.md" in raw["reason"]


def test_numeric_user_id_is_resolved(_env):
    _set_keys(_env, instagram_sessionid="S")
    resolved = _resp(200, {"user": {"username": "tailmon"}})
    with (
        patch.object(ig.requests, "get", return_value=resolved) as g,
        patch.object(
            ig.requests.Session,
            "get",
            return_value=_resp(200, {"data": {"user": {"username": "tailmon"}}}),
        ),
    ):
        out = ig.t_instagram("1234567890", dev_mode=False)
    assert "users/1234567890/info" in g.call_args[0][0]
    assert sec(out, "param") == "tailmon"


def test_count_parser():
    assert (
        ig._num("1,234") == 1234
        and ig._num("1.2M") == 1200000
        and ig._num("12K") == 12000
    )


def test_session_enrichment_adds_contact_and_geo(_env):
    _set_keys(_env, instagram_sessionid="S", instagram_csrftoken="C")
    info = {
        "user": {
            "category": "Artist",
            "public_email": "hi@tailmon.dev",
            "public_phone_country_code": "90",
            "public_phone_number": "5321234567",
            "city_name": "Istanbul",
            "latitude": 41.0,
            "longitude": 29.0,
            "bio_links": [{"url": "https://tailmon.dev"}],
        }
    }
    feed = {
        "items": [
            {
                "taken_at": 1714557600,
                "like_count": 5,
                "comment_count": 1,
                "media_type": 1,
                "caption": {"text": "#osint"},
                "location": {"name": "Galata Tower", "lat": 41.0256, "lng": 28.9744},
                "usertags": {"in": [{"user": {"username": "pal"}}]},
                "image_versions2": {"candidates": [{"url": "https://cdn/p.jpg"}]},
            }
        ]
    }
    mobile = []

    def mget(url, headers=None, **kw):
        mobile.append(headers)
        return _resp(200, info if "/info/" in url else feed)

    public = _resp(200, {"data": {"user": {"username": "tailmon", "id": "77"}}})
    with (
        patch.object(ig.requests.Session, "get", return_value=public),
        patch.object(ig.requests, "get", side_effect=mget),
    ):
        out = ig.t_instagram("tailmon", dev_mode=False)
    profile = sec(out, "profile")
    assert {"email": "hi@tailmon.dev"} in profile and {
        "phone": "+90 5321234567"
    } in profile
    geos = [p["geo"] for p in profile if "geo" in p]
    assert {g["Name"] for g in geos} == {"Istanbul", "Galata Tower"}
    assert mobile[0]["X-CSRFToken"] == "C"
    graphic = {next(iter(g)): next(iter(g.values())) for g in sec(out, "graphic")}
    assert {"label": "pal", "value": 1} in graphic["tagged"]


def test_expired_cookie_is_reported(_env):
    _set_keys(_env, instagram_sessionid="OLD")
    expired = _resp(401, text='{"message":"login_required"}')

    def get(url, headers=None, **kw):
        return expired if headers and headers.get("Cookie") else _resp(429)

    with patch.object(ig.requests.Session, "get", side_effect=get):
        out = ig.t_instagram("tailmon", dev_mode=False)
    assert "session cookie expired" in sec(out, "raw")[0]["reason"]
