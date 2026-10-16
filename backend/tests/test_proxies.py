"""Proxy pool: parsing, host rules, rotation, benching, retry."""

import json
from unittest.mock import patch

import pytest
import requests
from factories import http_defaults, proxies, result_cache


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    keys = tmp_path / "k.json"
    monkeypatch.setenv("VEILED_APIKEYS", str(keys))
    monkeypatch.setenv("VEILED_CACHE", "memory")
    result_cache.clear_memory()
    proxies.reset_cache()
    http_defaults.install()
    yield keys
    proxies.reset_cache()


def configure(keys, plist="", hosts=""):
    keys.write_text(
        json.dumps(
            [
                {"id": 1, "name": "proxy_list", "key": plist},
                {"id": 2, "name": "proxy_hosts", "key": hosts},
            ]
        )
    )
    proxies.reset_cache()


def test_parse_list(monkeypatch):
    monkeypatch.setenv("TOR_PROXY_URL", "socks5h://tor:9050")
    assert proxies.parse_list("1.2.3.4:8080, socks5h://h:1080\ntor") == [
        "http://1.2.3.4:8080",
        "socks5h://h:1080",
        "socks5h://tor:9050",
    ]


def test_no_proxies_means_no_pool(_env):
    configure(_env)
    assert not proxies.applies_to("https://example.org/")
    assert proxies.pick() is None


def test_host_rules(_env):
    configure(_env, "http://p1:1", "instagram.com")
    assert proxies.applies_to("https://www.instagram.com/x")
    assert not proxies.applies_to("https://api.github.com/x")


def test_rotation_bench_and_retry(_env):
    configure(_env, "http://p1:1, http://p2:2")
    used = []

    def send(self, req, **kw):
        p = kw["proxies"]["https"]
        used.append(p)
        if p == "http://p1:1":
            raise requests.exceptions.ProxyError("dead")
        r = requests.Response()
        r.status_code = 200
        r._content = b"ok"
        r.request = req
        return r

    with patch.object(requests.adapters.HTTPAdapter, "send", send):
        for _ in range(3):
            assert requests.get("https://example.org/").status_code == 200
    assert used.count("http://p1:1") == 1  # benched after the first failure
    assert result_cache.cooling("proxy:http://p1:1")


def test_all_benched_never_falls_back_to_direct(_env):
    configure(_env, "http://p1:1")
    proxies.bench("http://p1:1")
    with pytest.raises(requests.ConnectionError, match="benched"):
        requests.get("https://example.org/")


def test_subprocess_env_only_when_pool_covers_everything(_env):
    configure(_env, "http://p1:1")
    assert proxies.env_for_subprocess()["HTTPS_PROXY"] == "http://p1:1"
    configure(_env, "http://p1:1", "instagram.com")
    assert proxies.env_for_subprocess() == {}
