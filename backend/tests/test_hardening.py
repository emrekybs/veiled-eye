"""Crash and false-positive guards: SystemExit in vendored tools, URL
segments mistaken for handles, link parsing and LinkedIn result parsing."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from factories import pivots
from factories.links import profile_from_url, profiles_in


def test_system_exit_never_kills_the_worker():
    from modules.gitsniff.gitsniff_tasks import t_gitsniff

    class Boom:
        def scan_user_or_org(self, *a, **k):
            raise SystemExit(1)  # what GitSniff does on a rate limit

    with patch("modules.gitsniff.gitsniff_tasks._make_scanner", return_value=Boom()):
        out = t_gitsniff("someone", dev_mode=False)
    raw = next(i["raw"] for i in out if "raw" in i)
    assert raw[0]["status"] == "Warning"
    assert "github_token" in raw[0]["reason"]


@pytest.mark.parametrize("word", ["reel", "p", "stories", "explore", "watch", "status"])
def test_url_path_words_are_not_pivots(word):
    assert not pivots.worth_following(word)


@pytest.mark.parametrize(
    ("url", "hit"),
    [
        ("https://x.com/emrekybs8", ("twitter", "emrekybs8")),
        ("twitter.com/@abc_1", ("twitter", "abc_1")),
        ("https://www.instagram.com/reel/Cx1", None),
        ("https://github.com/emrekybs", ("github", "emrekybs")),
        ("https://github.com/features", None),
        ("https://www.reddit.com/user/spez/", ("reddit", "spez")),
        ("https://news.ycombinator.com/user?id=pg", ("hackernews", "pg")),
        ("https://www.youtube.com/@mkbhd", ("youtube", "mkbhd")),
        ("https://example.com/whatever", None),
    ],
)
def test_profile_from_url(url, hit):
    assert profile_from_url(url) == hit


def test_profiles_in_text():
    text = "Me: https://x.com/emrekybs8 · code github.com/emrekybs"
    assert profiles_in([text]) == [("twitter", "emrekybs8"), ("github", "emrekybs")]


def test_crosslinked_parse_rejects_other_companies():
    from modules.crosslinked.crosslinked_tasks import parse_result

    ok = parse_result(
        "Jane Doe - Security Engineer - Acme Labs | LinkedIn",
        "https://tr.linkedin.com/in/janedoe?trk=x",
        "",
        "Acme Labs",
    )
    assert ok == {
        "name": "Jane Doe",
        "title": "Security Engineer",
        "url": "https://tr.linkedin.com/in/janedoe",
    }
    assert (
        parse_result(
            "Jane Doe - Dev - Other Co | LinkedIn",
            "https://linkedin.com/in/j",
            "",
            "Acme Labs",
        )
        is None
    )
    assert (
        parse_result(
            "Acme Labs | LinkedIn", "https://linkedin.com/company/acme", "", "Acme Labs"
        )
        is None
    )


def test_userscanner_drops_conflicting_cross_hits():
    from modules.userscanner.userscanner_tasks import t_userscanner

    first = [
        {
            "site_name": "GitHub",
            "username": "jd",
            "url": "https://github.com/jd",
            "found": True,
            "category": "dev",
        }
    ]
    cross = [
        {
            "site_name": "Reddit",
            "username": "jd_alt",
            "url": "https://reddit.com/u/jd_alt",
            "found": True,
            "extra": {"confidence": "confirmed"},
        },
        {
            "site_name": "Steam",
            "username": "jd_x",
            "url": "u",
            "found": True,
            "extra": {"confidence": "conflicting"},
        },
        {
            "site_name": "Kick",
            "username": "jd_y",
            "url": "u2",
            "found": True,
            "extra": {"confidence": "candidate"},
        },
    ]

    class R(dict):
        def as_dict(self):
            return dict(self)

        def is_found(self):
            return self["found"]

    with patch(
        "modules.userscanner.userscanner_tasks._scan",
        return_value=([R(x) for x in first], [R(x) for x in cross]),
    ):
        out = t_userscanner("jd", dev_mode=False)
    social = next(i["profile"] for i in out if "profile" in i)[0]["social"]
    names = {s["name"] for s in social}
    assert "Reddit" in names and "Steam" not in names and "Kick" not in names
    tasks = next(i["tasks"] for i in out if "tasks" in i)
    assert tasks == [{"module": "maigret", "param": "jd_alt"}]


def test_http_defaults_browser_ua_and_retry(monkeypatch):
    import requests
    from factories import http_defaults

    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {"Retry-After": "0"}

    def fake(self, method, url, **kw):
        calls.append(dict(self.headers))
        return Resp(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(http_defaults, "_installed", False)
    monkeypatch.setattr(requests.Session, "request", fake)
    monkeypatch.setattr(http_defaults.time, "sleep", lambda s: None)
    monkeypatch.setattr(http_defaults.proxies, "applies_to", lambda url: False)
    http_defaults.install()
    r = requests.Session().get("https://example.org/x")
    assert r.status_code == 200 and len(calls) == 2
    assert not calls[0]["User-Agent"].startswith("python-requests")
