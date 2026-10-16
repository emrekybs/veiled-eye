"""Instagram: public no-login lookup, optional login fallback, clean errors."""

from unittest.mock import MagicMock, patch

import pytest
from modules.instagram import instagram_tasks as ig

USER = {
    "full_name": "Tail Mon",
    "username": "tailmon",
    "id": "123",
    "biography": "osint #cti github.com/tailmon",
    "external_url": "https://tailmon.dev",
    "is_private": False,
    "is_business_account": False,
    "is_verified": False,
    "edge_followed_by": {"count": 1500},
    "edge_follow": {"count": 80},
    "edge_felix_video_timeline": {"count": 0},
    "profile_pic_url_hd": "https://cdn/pic.jpg",
    "edge_owner_to_timeline_media": {
        "count": 2,
        "edges": [
            {
                "node": {
                    "__typename": "GraphImage",
                    "taken_at_timestamp": 1714557600,
                    "edge_liked_by": {"count": 10},
                    "edge_media_to_comment": {"count": 2},
                    "display_url": "https://cdn/p1.jpg",
                    "edge_media_to_caption": {
                        "edges": [{"node": {"text": "hi #osint @friend"}}]
                    },
                    "edge_media_to_tagged_user": {
                        "edges": [{"node": {"user": {"username": "pal"}}}]
                    },
                    "location": {"name": "Istanbul"},
                }
            },
            {"node": {"__typename": "GraphVideo", "taken_at_timestamp": 1714471200}},
        ],
    },
}


def _resp(
    status=200,
    payload=None,
    url="https://www.instagram.com/api/v1/users/web_profile_info/",
):
    r = MagicMock()
    r.status_code = status
    r.url = url
    r.json.return_value = payload if payload is not None else {}
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_APIKEYS", str(tmp_path / "apikeys.json"))
    monkeypatch.setenv("VEILED_CACHE", "memory")
    from factories import result_cache

    result_cache.clear_memory()


def _run(resp):
    with patch.object(ig.requests.Session, "get", return_value=resp):
        return ig.t_instagram("@tailmon", dev_mode=False)


def sec(out, key):
    return next(e[key] for e in out if key in e)


def test_public_profile_without_login():
    out = _run(_resp(200, {"data": {"user": USER}}))
    assert sec(out, "module") == "instagram"
    graphic = {next(iter(g)): next(iter(g.values())) for g in sec(out, "graphic")}
    assert {n["title"]: n["subtitle"] for n in graphic["instagram"]}[
        "Followers"
    ] == 1500
    assert {"label": "osint", "value": 1} in graphic["hashtags"]
    assert {"label": "friend", "value": 1} in graphic["mentions"]
    assert {"label": "pal", "value": 1} in graphic["tagged"]
    assert graphic["mediatype"][0] == {"name": "Images", "value": "1"}
    profile = sec(out, "profile")
    assert {"name": "Tail Mon"} in profile
    assert sec(out, "raw")["source"] == "public profile"
    assert sec(out, "timeline")[0]["action"] == "Instagram : Last Post"


def test_not_found_is_warning():
    out = _run(_resp(404))
    raw = sec(out, "raw")[0]
    assert raw["status"] == "Warning" and "not found" in raw["reason"]


def test_rate_limited_without_login_is_clear_warning():
    out = _run(_resp(401))
    raw = sec(out, "raw")[0]
    assert raw["status"] == "Warning" and "blocked every free source" in raw["reason"]


def test_invalid_handle_is_warning():
    out = ig.t_instagram("not a handle!", dev_mode=False)
    assert sec(out, "raw")[0]["status"] == "Warning"
