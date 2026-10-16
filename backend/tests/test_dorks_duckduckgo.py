"""Dorks must fall back to the keyless ddgs/DuckDuckGo provider."""

from pathlib import Path
from unittest.mock import patch

import ddgs
import pytest


class FakeDDGS:
    def text(self, q, max_results=10):
        if "site:twitter.com" in q:
            return [
                {
                    "title": "Tail Mon (@tailmon) / X",
                    "href": "https://twitter.com/tailmon",
                    "body": "Tail Mon #osint",
                }
            ]
        if "site:github.com" in q:
            return [
                {
                    "title": "tailmon (Tail Mon) · GitHub",
                    "href": "https://github.com/tailmon",
                    "body": "Tail Mon",
                }
            ]
        if "site:" in q:
            return []
        return [
            {
                "title": "Tail Mon (@tailmon) / X",
                "href": "https://twitter.com/tailmon",
                "body": "researcher #osint @behind24",
            },
            {
                "title": "tailmon - GitHub",
                "href": "https://github.com/tailmon",
                "body": "tailmon repositories",
            },
        ]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_APIKEYS", str(tmp_path / "apikeys.json"))
    monkeypatch.setenv("VEILED_CACHE", "memory")
    with patch.object(Path, "cwd", return_value=tmp_path), patch("time.sleep"):
        yield


def test_ddg_search_with_dorks_format():
    from factories.search_providers import DuckDuckGoProvider

    with patch.object(ddgs, "DDGS", FakeDDGS):
        node = DuckDuckGoProvider().search_with_dorks("tailmon")
    assert {"dork", "titles", "links", "descriptions"} <= set(node[0])
    assert any(n["dork"] == "twitter" for n in node)


def test_dorks_cards_filled_without_keys():
    from modules.dorks.dorks_tasks import t_dorks

    with patch.object(ddgs, "DDGS", FakeDDGS):
        out = t_dorks("tailmon", "Initial", dev_mode=False)
    graphic = {next(iter(g)): next(iter(g.values())) for g in out[4]["graphic"]}
    assert graphic["names"] and graphic["mentions"] and graphic["hashtags"]
    assert len(graphic["social"]) > 1 and graphic["searches"]
