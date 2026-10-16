"""E-mail registrations: holehe + user-scanner merged per site."""

from unittest.mock import patch

import pytest
from factories import result_cache
from modules.emailreg import emailreg_tasks as er

HOLEHE = [
    {
        "name": "instagram",
        "domain": "instagram.com",
        "exists": True,
        "rateLimit": False,
        "emailrecovery": None,
        "phoneNumber": "+90 ••• ••• •• 67",
        "others": None,
    },
    {
        "name": "spotify",
        "domain": "spotify.com",
        "exists": True,
        "rateLimit": False,
        "emailrecovery": "j•••@g•••.com",
        "phoneNumber": None,
        "others": None,
    },
    {
        "name": "twitter",
        "domain": "twitter.com",
        "exists": False,
        "rateLimit": False,
        "emailrecovery": None,
        "phoneNumber": None,
        "others": None,
    },
    {
        "name": "amazon",
        "domain": "amazon.com",
        "exists": None,
        "rateLimit": True,
        "emailrecovery": None,
        "phoneNumber": None,
        "others": None,
    },
]
SCANNER = [
    {
        "site_name": "Instagram",
        "url": "https://instagram.com/x",
        "category": "social",
        "found": True,
        "extra": {"confidence": "confirmed"},
    },
    {
        "site_name": "Amazon",
        "url": "",
        "category": "shopping",
        "found": True,
        "extra": {"confidence": "confirmed"},
    },
    {
        "site_name": "GitHub",
        "url": "https://github.com/x",
        "category": "dev",
        "found": True,
        "extra": {},
    },
]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_APIKEYS", str(tmp_path / "k.json"))
    monkeypatch.setenv("VEILED_CACHE", "memory")
    monkeypatch.setenv("VEILED_EMAILREG_WAIT", "0")
    result_cache.clear_memory()


def test_merge_grades_by_agreement():
    rows = {r["site"].lower(): r for r in er.merge(HOLEHE, SCANNER)}
    assert rows["instagram"]["status"] == "confirmed"
    assert rows["instagram"]["recovery_phone"].endswith("67")
    assert rows["spotify"]["status"] == "likely"
    assert rows["spotify"]["recovery_email"].startswith("j")
    # holehe could not check amazon (rate limited) -> scanner's own rating holds
    assert rows["amazon"]["status"] == "confirmed"
    assert rows["github"]["status"] == "likely"
    assert "twitter" not in rows


def test_uses_cached_scanner_results():
    email = "john@acme.com"
    result_cache.store("holehe", email, [{"module": "holehe"}, {"raw": HOLEHE}])
    result_cache.store(
        "userscanner", email, [{"module": "userscanner"}, {"raw": {"found": SCANNER}}]
    )
    with (
        patch("modules.holehe.holehe_tasks._holehe_query", side_effect=AssertionError),
        patch(
            "modules.userscanner.userscanner_tasks._scan", side_effect=AssertionError
        ),
    ):
        out = er.t_emailreg(email, dev_mode=False)
    raw = next(e["raw"] for e in out if "raw" in e)
    assert raw["provider"] == "corporate / own domain"
    assert len(raw["sites"]) == 4
    nodes = next(e["graphic"] for e in out if "graphic" in e)[0]["emailreg"]
    insta = next(n for n in nodes if n["title"].lower() == "instagram")
    assert "confirmed (holehe + user-scanner)" in insta["subtitle"]
    assert "recovery phone" in insta["subtitle"]


def test_provider_kind():
    assert er.provider_kind("gmail.com") == "free webmail"
    assert er.provider_kind("proton.me") == "privacy-focused"
    assert er.provider_kind("mailinator.com") == "disposable"
    assert er.provider_kind("acme.com") == "corporate / own domain"


def test_not_an_email_is_warning():
    out = er.t_emailreg("johndoe", dev_mode=False)
    assert next(e["raw"] for e in out if "raw" in e)[0]["status"] == "Warning"
