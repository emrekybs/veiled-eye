"""Tests for the identity modules (SOCMIntelligence ports + native),
avatar hashing, export and the related chain / crossref / CLI behaviour.

All network access is mocked.  Collectors' JSON shapes mirror what the
vendored ``socmint_tools`` scripts emit.
"""

import io
import json
import threading
import xml.dom.minidom
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from factories import chain, identity, result_cache
from factories.quiet import silenced

ORDER = ["module", "param", "validation", "raw", "graphic", "profile", "timeline"]
FIXTURES = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_CACHE", "memory")
    monkeypatch.setenv("VEILED_CROSSREF_WAIT", "0")
    monkeypatch.setenv("VEILED_AVATAR_HASH", "0")
    monkeypatch.setenv("VEILED_WMN_REMOTE", "0")
    result_cache.clear_memory()
    with patch.object(Path, "cwd", return_value=tmp_path):
        yield
    result_cache.clear_memory()


def keys(out):
    return [next(iter(i)) for i in out]


def sec(out, key):
    return next(i[key] for i in out if key in i)


def tasks_of(out):
    return sec(out, "tasks") if "tasks" in keys(out) else []


def is_warning(out):
    raw = sec(out, "raw")
    return isinstance(raw, list) and raw[0]["status"] == "Warning"


# ---------------------------------------------------------------------------
# identity helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("addr", "chain_name"),
    [
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "bitcoin"),
        ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "bitcoin"),
        ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "bitcoin"),
        ("0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe", "ethereum"),
        ("LVg2kJoFNg45Nbpy53h7Fe1wKyeXVRhMH9", "litecoin"),
        ("DH5yaieqoZN36fDVciNyRueRGvGLR3mr7L", "dogecoin"),
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb", None),  # bad checksum
        ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx", None),  # bad bech32
        ("johndoe", None),
    ],
)
def test_wallet_chain(addr, chain_name):
    assert identity.wallet_chain(addr) == chain_name


def test_find_wallets_and_phones_in_text():
    text = "BTC 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa call +90 532 123 45 67 fake 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"
    assert identity.find_wallets(text) == [
        {"address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "chain": "bitcoin"}
    ]
    assert identity.find_phones(text) == ["+905321234567"]


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("a@b.com", "email"),
        ("+905321234567", "phone"),
        ("0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe", "wallet"),
        ("acme.com", "domain"),
        ("johndoe", "username"),
        ("12345678", "username"),
    ],
)
def test_selector_type(value, kind):
    assert identity.selector_type(value) == kind


def test_split_multi_keeps_spaced_phone():
    assert identity.split_multi("+90 532 123 45 67, +1 650 253 0000") == [
        "+90 532 123 45 67",
        "+1 650 253 0000",
    ]


def test_socials_to_tasks_skips_self_and_mastodon():
    socials = [
        {"platform": "github", "handle": "jd"},
        {"platform": "telegram", "handle": "jd"},
        {"platform": "mastodon", "handle": "jd@infosec.exchange"},
        {"platform": "unknown", "handle": "x"},
    ]
    assert identity.socials_to_tasks(socials, skip="telegram") == [
        {"module": "github", "param": "jd"}
    ]


# ---------------------------------------------------------------------------
# socmint runner
# ---------------------------------------------------------------------------
def _fake_tool(tmp_path, body: str) -> str:
    (tmp_path / "fake_tool.py").write_text(body)
    return "fake_tool.py"


def test_runner_ok_soft_and_hard(tmp_path, monkeypatch):
    from factories import socmint_runner

    monkeypatch.setattr(socmint_runner, "TOOLS_DIR", tmp_path)
    ok = _fake_tool(
        tmp_path, 'import json,sys;print("noise");print(json.dumps({"x": sys.argv[1]}))'
    )
    assert socmint_runner.run_tool(ok, ["a"]) == {"x": "a"}
    _fake_tool(
        tmp_path,
        'import json;print(json.dumps({"error":"not_found","message":"nope"}))',
    )
    with pytest.raises(Exception, match="^warn: nope"):
        socmint_runner.run_tool("fake_tool.py", [])
    _fake_tool(
        tmp_path, 'import json;print(json.dumps({"error":"error","message":"boom"}))'
    )
    with pytest.raises(Exception, match="^boom"):
        socmint_runner.run_tool("fake_tool.py", [])
    _fake_tool(tmp_path, 'import sys;sys.stderr.write("trace\\nlast line");sys.exit(1)')
    with pytest.raises(Exception, match="last line"):
        socmint_runner.run_tool("fake_tool.py", [])
    _fake_tool(tmp_path, "import time;time.sleep(5)")
    with pytest.raises(Exception, match="timed out"):
        socmint_runner.run_tool("fake_tool.py", [], timeout=1)


def test_vendored_tools_are_present_and_compile():
    import py_compile

    from factories.socmint_runner import TOOLS_DIR

    for name in (
        "_toolkit",
        "telegram_osint",
        "gravatar_osint",
        "wayback_osint",
        "steam_osint",
        "bluesky_osint",
        "hackernews_osint",
        "stackexchange_osint",
        "kick_osint",
        "snap_osint",
    ):
        py_compile.compile(str(TOOLS_DIR / f"{name}.py"), doraise=True)
    # snap tool must not need matplotlib on the JSON path
    head = (TOOLS_DIR / "snap_osint.py").read_text().split("def generate_heatmap")[0]
    assert "import matplotlib" not in head


# ---------------------------------------------------------------------------
# SOCMINT-based wrappers
# ---------------------------------------------------------------------------
def test_telegram_wrapper():
    from modules.telegram.telegram_tasks import t_telegram

    data = {
        "username": "chan",
        "url": "https://t.me/chan",
        "kind": "channel",
        "title": "Chan News",
        "description": "contact admin@chan.io btc 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa github.com/chanio",
        "photo": "https://cdn.t.me/p.jpg",
        "verified": True,
        "subscribers": 1200,
        "description_emails": ["admin@chan.io"],
        "description_socials": [
            {
                "platform": "github",
                "handle": "chanio",
                "url": "https://github.com/chanio",
            }
        ],
        "description_mentions": ["otherchan"],
        "description_links": [],
        "posts": [{"id": 5, "date": "2024-05-01T10:00:00+00:00", "text": "hello"}],
        "analysis": {"posts_analyzed": 1, "top_forward_sources": {"srcchan": 3}},
    }
    with patch("modules.telegram.telegram_tasks.run_tool", return_value=data) as rt:
        out = t_telegram("@chan", dev_mode=False)
    assert rt.call_args[0][1][0] == "chan"
    assert keys(out) == [*ORDER, "tasks"]
    profile = sec(out, "profile")
    assert {"email": "admin@chan.io"} in profile and {"name": "Chan News"} in profile
    assert any("wallet" in p for p in profile)
    mods = {t["module"] for t in tasks_of(out)}
    assert {"github", "crypto", "gravatar", "pgp"} <= mods
    assert len(sec(out, "timeline")) == 1


def test_gravatar_wrapper_accounts_and_company():
    from modules.gravatar.gravatar_tasks import t_gravatar

    data = {
        "email": "jd@x.com",
        "username": "jdoe",
        "display_name": "John Doe",
        "has_avatar": True,
        "avatar_url": "https://gravatar.com/avatar/abc",
        "profile_url": "https://gravatar.com/jdoe",
        "company": "Acme",
        "job_title": "CISO",
        "about": "",
        "location": "Istanbul",
        "accounts": [
            {
                "type": "github",
                "username": "jdoe",
                "url": "https://github.com/jdoe",
                "verified": True,
            }
        ],
        "links": [{"title": "Blog", "url": "https://jd.dev"}],
        "crypto": [{"label": "BTC", "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}],
        "phones": ["+905321234567"],
        "emails": ["jd@x.com", "alt@y.com"],
        "socials": [],
    }
    with patch("modules.gravatar.gravatar_tasks.run_tool", return_value=data):
        out = t_gravatar("jd@x.com", dev_mode=False)
    profile = sec(out, "profile")
    assert {"organization": "Acme"} in profile
    assert {"phone": "+905321234567"} in profile
    assert {"email": "alt@y.com"} in profile and {"email": "jd@x.com"} not in profile
    mods = {t["module"] for t in tasks_of(out)}
    assert {"github", "crypto", "phone"} <= mods


def test_steam_wrapper_aliases_become_usernames_and_timeline():
    from modules.steam.steam_tasks import t_steam

    data = {
        "steamid": "76561197960287930",
        "custom_url": "gabelogannewell",
        "persona": "Rabscuttle",
        "profile_url": "https://steamcommunity.com/id/gabelogannewell",
        "avatar": "https://a/s.jpg",
        "aliases": [{"name": "OldNick", "changed": "2019-01-01"}],
        "groups": [{"id": "1", "name": "Valve"}],
        "friends": [],
        "summary": "",
        "summary_links": [],
        "summary_emails": [],
        "summary_socials": [],
    }
    with patch("modules.steam.steam_tasks.run_tool", return_value=data):
        out = t_steam("gabelogannewell", dev_mode=False)
    assert {"username": "OldNick"} in sec(out, "profile")
    assert any("OldNick" in e["action"] for e in sec(out, "timeline"))


def test_bluesky_actor_and_validation():
    from modules.bluesky.bluesky_tasks import actor_for, t_bluesky

    assert actor_for("johndoe") == "johndoe.bsky.social"
    assert actor_for("jd@x.com") == "jd.bsky.social"
    assert actor_for("name.dev") == "name.dev"
    data = {
        "handle": "johndoe.bsky.social",
        "did": "did:plc:x",
        "url": "https://bsky.app/profile/johndoe.bsky.social",
        "mentions": [{"handle": "pal.bsky.social", "count": 2}, {"handle": None}],
        "domains": [],
        "emails": [],
    }
    with patch("modules.bluesky.bluesky_tasks.run_tool", return_value=data):
        out = t_bluesky("johndoe", dev_mode=False)
    assert sec(out, "validation") == "soft"
    titles = [n["title"] for n in sec(out, "graphic")[0]["bluesky"]]
    assert "@pal.bsky.social" in titles


def test_stackexchange_requires_exact_name():
    from modules.stackexchange.stackexchange_tasks import t_stackexchange

    data = {
        "display_name": "John Doe Smith",
        "candidates": [{"display_name": "John Doe Smith"}],
    }
    with patch("modules.stackexchange.stackexchange_tasks.run_tool", return_value=data):
        out = t_stackexchange("johndoe", dev_mode=False)
    assert is_warning(out)
    data = {
        "display_name": "John Doe",
        "link": "https://so/u/1",
        "network": [{"site": "Super User", "reputation": 5}],
    }
    with patch("modules.stackexchange.stackexchange_tasks.run_tool", return_value=data):
        out = t_stackexchange("john_doe", dev_mode=False)
    assert not is_warning(out)


def test_kick_declared_socials_become_tasks():
    from modules.kick.kick_tasks import t_kick

    data = {
        "slug": "xqc",
        "url": "https://kick.com/xqc",
        "declared_socials": {"twitter": "https://x.com/xqc"},
        "socials": [],
    }
    with patch("modules.kick.kick_tasks.run_tool", return_value=data):
        out = t_kick("xqc", dev_mode=False)
    assert {"module": "twitter", "param": "xqc"} in tasks_of(out)


def test_snapchat_wrapper_and_runner_exit_codes(tmp_path, monkeypatch):
    from factories import socmint_runner
    from modules.snapchat.snapchat_tasks import t_snapchat

    data = {
        "account_information": {
            "username": "spez",
            "display_name": "Steve",
            "is_public": True,
            "bio": "",
            "website": "https://x.io",
        },
        "account_analysis": {
            "created_at": "2020-01-01 00:00:00 UTC",
            "last_active": "today",
        },
        "related_accounts": [{"username": "pal"}],
        "stories": {
            "snaps": [
                {"upload_date": "2024-01-01 10:00:00 UTC"},
                {"upload_date": "unknown"},
            ]
        },
        "snap_analytics": {"total_snaps": 2},
    }
    with patch("modules.snapchat.snapchat_tasks.run_snapchat", return_value=data):
        out = t_snapchat("spez", dev_mode=False)
    assert {"name": "Steve"} in sec(out, "profile")
    assert len(sec(out, "timeline")) == 2  # created + one dated story

    monkeypatch.setattr(socmint_runner, "TOOLS_DIR", tmp_path)
    (tmp_path / "snap_osint.py").write_text("import sys; sys.exit(2)")
    with pytest.raises(Exception, match="^warn: Snapchat user"):
        socmint_runner.run_snapchat("ghost")
    (tmp_path / "snap_osint.py").write_text(
        "import sys,json; p=sys.argv[sys.argv.index('--save-json')+1]; json.dump({'ok':1},open(p,'w')); sys.exit(1)"
    )
    assert socmint_runner.run_snapchat("x") == {
        "ok": 1
    }  # JSON saved before a report crash


def test_wayback_username_targets_and_titles():
    from modules.wayback.wayback_tasks import _name_from_title, t_wayback, targets_for

    t = dict(targets_for("johndoe"))
    assert (
        t["twitter"] == "twitter.com/johndoe" and t["tiktok"] == "tiktok.com/@johndoe"
    )
    assert targets_for("https://acme.com/about") == [("site", "acme.com/about")]
    assert _name_from_title("John Doe (@jdoe) / Twitter", "twitter") == "John Doe"
    assert _name_from_title("Log in • Instagram", "instagram") is None

    def fake(script, args, timeout):
        if args[0].startswith("twitter.com"):
            return {
                "target": args[0],
                "total_captures": 12,
                "first_capture": "2015-03-01",
                "last_capture": "2020-01-01",
                "last_capture_url": "https://web.archive.org/x",
                "snapshots": [
                    {
                        "date": "2015-03-01",
                        "title": "John Doe (@johndoe) / Twitter",
                        "description": "old bio",
                    }
                ],
                "emails": ["old@mail.com"],
                "socials": [{"platform": "github", "handle": "jdold", "url": "u"}],
            }
        raise Exception("warn: Wayback Machine'de arsiv kaydi yok")

    with patch("modules.wayback.wayback_tasks.run_tool", side_effect=fake):
        out = t_wayback("johndoe", dev_mode=False)
    profile = sec(out, "profile")
    assert (
        {"name": "John Doe"} in profile
        and {"email": "old@mail.com"} in profile
        and {"bio": "old bio"} in profile
    )
    assert {"module": "github", "param": "jdold"} in tasks_of(out)
    with patch(
        "modules.wayback.wayback_tasks.run_tool", side_effect=Exception("warn: none")
    ):
        assert is_warning(t_wayback("ghost", dev_mode=False))


# ---------------------------------------------------------------------------
# WhatsMyName
# ---------------------------------------------------------------------------
def test_wmn_bundled_dataset_and_classify():
    from modules.whatsmyname.whatsmyname_tasks import classify, load_sites

    sites = load_sites()
    assert len(sites) > 500
    assert all("{account}" in s["uri_check"] or s.get("post_body") for s in sites)
    site = {"e_code": 200, "e_string": "profile", "m_code": 404, "m_string": "missing"}
    assert classify(site, 200, "the profile page") == "found"
    assert classify(site, 404, "missing") == "missing"
    assert classify(site, 200, "nothing here") == "unknown"


def test_wmn_end_to_end_with_mock_transport(monkeypatch):
    import httpx
    from modules.whatsmyname import whatsmyname_tasks as wmn

    sites = [
        {
            "name": "SiteA",
            "uri_check": "https://a.test/{account}",
            "e_code": 200,
            "e_string": "user-card",
            "m_code": 404,
            "m_string": "nope",
            "cat": "social",
        },
        {
            "name": "SiteB",
            "uri_check": "https://b.test/u/{account}",
            "e_code": 200,
            "e_string": "profile",
            "m_code": 404,
            "m_string": "nope",
            "cat": "coding",
        },
        {
            "name": "SiteC",
            "uri_check": "https://c.test/api",
            "post_body": '{"u":"{account}"}',
            "e_code": 200,
            "e_string": '"id"',
            "m_code": 200,
            "m_string": "null",
            "cat": "social",
            "strip_bad_char": ".",
        },
    ]
    monkeypatch.setattr(wmn, "load_sites", lambda: sites)

    def handler(request):
        if request.url.host == "a.test":
            return httpx.Response(200, text="<div class=user-card>")
        if request.url.host == "c.test":
            assert json.loads(request.content) == {"u": "johndoe"}  # '.' stripped
            return httpx.Response(200, text='{"id": 1}')
        return httpx.Response(404, text="nope")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    out = wmn.t_whatsmyname("john.doe", dev_mode=False)
    found = {r["name"] for r in sec(out, "graphic")[1]["lists"]}
    assert found == {"SiteA", "SiteC"}
    assert sec(out, "graphic")[3]["stats"]["missing"] == 1


# ---------------------------------------------------------------------------
# PGP
# ---------------------------------------------------------------------------
def test_pgp_packet_parser_on_real_key():
    from modules.pgp.pgp_tasks import dearmor, parse_packets

    info = parse_packets(dearmor((FIXTURES / "fixtures_pgp_key.asc").read_text()))
    assert info["created"] and len(info["uids"]) == 2
    assert "Johnny D <johnny@other.org>" in info["uids"]


def test_pgp_email_lookup_merges_sources():
    from modules.pgp.pgp_tasks import t_pgp

    armored = (FIXTURES / "fixtures_pgp_key.asc").read_text()
    mr = "info:1:1\npub:ABCDEF0123456789:1:4096:1500000000::\nuid:John%20Doe%20%3Cjd%40example.com%3E:1500000000::\nuid:JD%20Work%20%3Cjd%40corp.com%3E:::\n"

    def fake_get(url, params=None, timeout=None):
        r = MagicMock()
        r.status_code = 200
        r.text = armored if "keys.openpgp.org" in url else mr
        r.raise_for_status = lambda: None
        return r

    with patch("modules.pgp.pgp_tasks.requests.get", side_effect=fake_get):
        out = t_pgp("jd@example.com", dev_mode=False)
    assert sec(out, "validation") == "hard"
    profile = sec(out, "profile")
    assert {"email": "jd@corp.com"} in profile and {
        "email": "johnny@other.org"
    } in profile
    assert {"name": "John Doe"} in profile
    assert len(sec(out, "timeline")) == 2


def test_pgp_name_search_filters_unrelated_keys():
    from modules.pgp.pgp_tasks import t_pgp

    mr = "pub:AA:1:2048:1500000000::\nuid:Someone%20Else%20%3Cs%40e.com%3E:::\n"
    resp = MagicMock(status_code=200, text=mr)
    resp.raise_for_status = lambda: None
    with patch("modules.pgp.pgp_tasks.requests.get", return_value=resp):
        assert is_warning(t_pgp("johndoe", dev_mode=False))


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------
def test_phone_offline_analysis_and_registrations():
    from modules.phone.phone_tasks import t_phone

    regs = [
        {"name": "instagram", "domain": "instagram.com", "exists": True},
        {"name": "amazon", "exists": False},
    ]
    web = [{"title": "Ad listing", "url": "https://ads.example/1", "snippet": "call"}]
    with (
        patch("modules.phone.phone_tasks.registrations", return_value=regs),
        patch("modules.phone.phone_tasks.web_mentions", return_value=web),
    ):
        out = t_phone("+90 532 123 45 67, 0212 555 12 12", dev_mode=False)
    numbers = sec(out, "raw")["numbers"]
    assert numbers[0]["e164"] == "+905321234567" and numbers[0]["line_type"] == "mobile"
    assert numbers[0]["region"] == "TR" and numbers[0]["timezones"]
    assert numbers[1]["e164"] == "+902125551212"  # parsed with default region TR
    profile = sec(out, "profile")
    assert {"phone": "+905321234567"} in profile
    assert profile[0]["social"][0]["name"] == "Instagram"


def test_phone_invalid_is_warning():
    from modules.phone.phone_tasks import t_phone

    with patch("modules.phone.phone_tasks.registrations", return_value=[]):
        assert is_warning(t_phone("+1 000", dev_mode=False))


def test_phone_ignorant_signature(monkeypatch):
    """The real ignorant check functions accept (phone, country_code, client, out)."""
    import inspect

    from ignorant.modules.shopping.amazon import amazon
    from ignorant.modules.social_media.instagram import instagram
    from ignorant.modules.social_media.snapchat import snapchat

    for fn in (amazon, instagram, snapchat):
        assert list(inspect.signature(fn).parameters) == [
            "phone",
            "country_code",
            "client",
            "out",
        ]


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------
BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ETH = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"


def _crypto_get(url, params=None, headers=None, timeout=None):
    r = MagicMock(status_code=200)
    r.raise_for_status = lambda: None
    if url.endswith(f"/api/address/{BTC}"):
        r.json.return_value = {
            "chain_stats": {
                "funded_txo_sum": 300_000_000,
                "spent_txo_sum": 100_000_000,
                "tx_count": 3,
            }
        }
    elif url.endswith(f"/api/address/{BTC}/txs"):
        r.json.return_value = [
            {
                "status": {"block_time": 1600000000},
                "vin": [{"prevout": {"scriptpubkey_address": "1Peer"}}],
                "vout": [{"scriptpubkey_address": BTC}],
            },
            {
                "status": {"block_time": 1700000000},
                "vin": [{"prevout": {"scriptpubkey_address": BTC}}],
                "vout": [{"scriptpubkey_address": "1Peer"}],
            },
        ]
    elif url.endswith(f"/addresses/{ETH}"):
        r.json.return_value = {
            "coin_balance": str(2 * 10**18),
            "ens_domain_name": "jd.eth",
            "public_tags": [{"display_name": "Exchange X"}],
        }
    elif url.endswith("/counters"):
        r.json.return_value = {"transactions_count": "42"}
    elif url.endswith("/transactions"):
        r.json.return_value = {
            "items": [
                {
                    "timestamp": "2021-01-01T00:00:00Z",
                    "from": {"hash": ETH},
                    "to": {"hash": "0xPeer"},
                }
            ]
        }
    else:
        r.status_code = 404
    return r


def test_crypto_btc_and_eth():
    from modules.crypto.crypto_tasks import t_crypto

    with patch("modules.crypto.crypto_tasks.requests.get", side_effect=_crypto_get):
        out = t_crypto(f"{BTC}, {ETH}, notawallet", dev_mode=False)
    wallets = {w["address"]: w for w in sec(out, "raw")["wallets"]}
    btc = wallets[BTC]
    assert btc["balance"] == 2.0 and btc["received"] == 3.0 and btc["tx_count"] == 3
    assert btc["counterparties"] == [{"address": "1Peer", "count": 2}]
    assert btc["first_seen"].startswith("2020-09-13")
    eth = wallets[ETH]
    assert (
        eth["balance"] == 2.0
        and eth["ens"] == "jd.eth"
        and "Exchange X" in eth["labels"]
    )
    assert wallets["notawallet"]["valid"] is False
    assert {"username": "jd.eth"} in sec(out, "profile")
    assert sec(out, "profile")[0]["wallet"][0] == {"currency": "BTC", "address": BTC}


def test_crypto_explorer_error_is_reported_not_raised():
    from modules.crypto.crypto_tasks import t_crypto

    with patch(
        "modules.crypto.crypto_tasks.requests.get", side_effect=ConnectionError("down")
    ):
        out = t_crypto(BTC, dev_mode=False)
    w = sec(out, "raw")["wallets"][0]
    assert w["valid"] and not w["found"] and "down" in w["error"]


def test_crypto_no_valid_wallet():
    from modules.crypto.crypto_tasks import t_crypto

    assert is_warning(t_crypto("hello,world", dev_mode=False))


# ---------------------------------------------------------------------------
# Ahmia
# ---------------------------------------------------------------------------
AHMIA_HOME = '<form id="searchForm" action="/search/"><input name="q"><input type="hidden" name="a1b2" value="zz9"></form>'
ONION = "a" * 56 + ".onion"
AHMIA_RESULTS = f"""<ol><li class="result"><h4><a href="/search/redirect?search_term=x&redirect_url=http://{ONION}/page">Forum profile</a></h4>
<p>user johndoe posted</p><cite>{ONION}/page</cite><span class="lastSeen" data-timestamp="1700000000"></span></li>
<li class="result"><h4><a href="/x">No onion here</a></h4></li></ol>"""


def test_ahmia_token_and_parser():
    from modules.ahmia.ahmia_tasks import form_token, parse_results

    assert form_token(AHMIA_HOME) == {"a1b2": "zz9"}
    hits = parse_results(AHMIA_RESULTS)
    assert (
        len(hits) == 1
        and hits[0]["onion"] == ONION
        and hits[0]["last_seen"] == "2023-11-14"
    )


def test_ahmia_search_sends_token():
    from modules.ahmia import ahmia_tasks

    calls = []

    class FakeSession:
        headers, proxies = {}, {}

        def get(self, url, params=None, timeout=None):
            calls.append((url, params))
            r = MagicMock(status_code=200)
            r.raise_for_status = lambda: None
            r.text = AHMIA_HOME if params is None else AHMIA_RESULTS
            return r

    with patch.object(ahmia_tasks, "_session", return_value=FakeSession()):
        hits = ahmia_tasks.search("johndoe")
    assert calls[1][1] == {"q": "johndoe", "a1b2": "zz9"} and len(hits) == 1


def test_ahmia_blocked_without_tor_is_warning():
    from modules.ahmia import ahmia_tasks

    with (
        patch.object(ahmia_tasks, "search", side_effect=RuntimeError("403")),
        patch.object(ahmia_tasks, "_tor_available", return_value=False),
    ):
        assert is_warning(ahmia_tasks.t_ahmia("johndoe", dev_mode=False))


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------
def _ok(module, param, profile=None, graphic=None):
    return [
        {"module": module},
        {"param": param},
        {"validation": "soft"},
        {"raw": {}},
        {"graphic": graphic or []},
        {"profile": profile or []},
        {"timeline": []},
    ]


def test_chain_username_fans_out_to_identity_modules():
    mods = {t["module"] for t in chain.next_tasks(_ok("search", "johndoe"))}
    assert set(chain.USERNAME_IDENTITY) <= mods


def test_chain_email_fans_out():
    mods = {t["module"] for t in chain.next_tasks(_ok("holehe", "jd@gmail.com"))}
    assert {"gravatar", "pgp", "userscanner", "ahmia"} <= mods


def test_chain_phone_and_wallet_from_any_profile():
    res = _ok(
        "peopledatalabs",
        "jd@x.com",
        profile=[{"phone": "+905321234567"}, {"wallet": [{"address": BTC}]}],
    )
    t = chain.next_tasks(res)
    assert {"module": "phone", "param": "+905321234567"} in t
    assert {"module": "crypto", "param": BTC} in t


# ---------------------------------------------------------------------------
# avatar hashing + crossref
# ---------------------------------------------------------------------------
def _png(seed: int, size=200, quality=None) -> bytes:
    from PIL import Image, ImageDraw

    base = 400  # draw once at a fixed size, then rescale -> same picture
    img = Image.new("RGB", (base, base), (seed * 40 % 255, 90, 160))
    d = ImageDraw.Draw(img)
    for i in range(6):
        x = (seed * 37 + i * 29) % (base - 140)
        d.ellipse(
            [x, i * base // 7, x + base // 3, i * base // 7 + base // 4],
            fill=((i * 60 + seed * 13) % 255, 255 - i * 30, (seed * 70) % 255),
        )
    img = img.resize((size, size))
    buf = io.BytesIO()
    if quality:
        img.save(buf, "JPEG", quality=quality)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def test_avatar_fingerprint_matches_resized_recompressed_copy():
    from factories.avatar import distance, fingerprint
    from PIL import Image

    a = fingerprint(_png(1, 400))
    b = fingerprint(_png(1, 96, quality=40))  # same picture, smaller + JPEG
    c = fingerprint(_png(5, 400))
    assert distance(a, b) <= 6 < distance(a, c)
    blank = io.BytesIO()
    Image.new("RGB", (100, 100), (200, 200, 200)).save(blank, "PNG")
    assert fingerprint(blank.getvalue()) is None


def test_match_avatars_clusters_different_accounts():
    from factories.avatar import match_avatars

    blobs = {
        "u1": _png(1, 300),
        "u2": _png(1, 120, 50),
        "u3": _png(7, 300),
        "u4": _png(1, 300),
    }
    photos = [
        {"picture": "https://x/u1", "account": ("github", "jd"), "module": "github"},
        {
            "picture": "https://x/u2",
            "account": ("telegram", "jd"),
            "module": "telegram",
        },
        {"picture": "https://x/u3", "account": ("steam", "other"), "module": "steam"},
        {
            "picture": "https://x/u4",
            "account": ("github", "jd"),
            "module": "maigret",
        },  # same account
    ]
    out = match_avatars(photos, fetch=lambda url: blobs[url.rsplit("/", 1)[1]])
    assert len(out) == 1
    assert out[0]["accounts"] == [["github", "jd"], ["telegram", "jd"]]


def test_crossref_avatar_upgrade_and_phone_wallet(monkeypatch):
    from modules.crossref import crossref_tasks

    monkeypatch.setenv("VEILED_AVATAR_HASH", "1")
    result_cache.store(
        "telegram",
        "jd",
        _ok(
            "telegram",
            "jd",
            profile=[
                {
                    "social": [
                        {"name": "Telegram", "url": "https://t.me/jd", "username": "jd"}
                    ]
                },
                {"photos": [{"picture": "https://x/a", "title": "telegram"}]},
                {"phone": "+905321234567"},
            ],
        ),
    )
    result_cache.store(
        "steam",
        "jd",
        _ok(
            "steam",
            "jd",
            profile=[
                {
                    "social": [
                        {"name": "Steam", "url": "https://steam/jd", "username": "jd"}
                    ]
                },
                {"photos": [{"picture": "https://x/b", "title": "steam"}]},
                {"wallet": [{"currency": "BTC", "address": BTC}]},
            ],
        ),
    )
    # phone module ran on the derived param -> must be collected via chain pivots
    result_cache.store(
        "phone",
        "+905321234567",
        _ok("phone", "+905321234567", profile=[{"location": "Turkey"}]),
    )
    fake_matches = [
        {
            "accounts": [["steam", "jd"], ["telegram", "jd"]],
            "pictures": ["https://x/a", "https://x/b"],
            "modules": ["steam", "telegram"],
            "distance": 2,
        }
    ]
    with patch.object(crossref_tasks, "match_avatars", return_value=fake_matches):
        out = crossref_tasks.t_crossref("jd", dev_mode=False)
    rep = sec(out, "raw")
    acc = {a["platform"].lower(): a for a in rep["accounts"]}
    assert acc["telegram"]["confidence"] == "likely" and acc["telegram"]["avatar_match"]
    assert rep["identity"]["phone"][0]["value"] == "+905321234567"
    assert rep["identity"]["wallet"][0]["value"] == BTC
    assert "phone" in rep["sources_ok"]
    assert rep["avatar_matches"] == fake_matches


def test_crossref_darkweb_without_hits_is_not_exposure():
    from modules.crossref.crossref_tasks import correlate

    empty = [
        {"module": "darkweb"},
        {"param": "jd"},
        {"validation": "no"},
        {"raw": []},
        {"graphic": []},
        {"profile": []},
        {"timeline": []},
    ]
    hit = [
        {"module": "darkweb"},
        {"param": "jd"},
        {"validation": "hard"},
        {"raw": [{"title": "t", "link": "l"}]},
        {"graphic": []},
        {"profile": []},
        {"timeline": []},
    ]
    assert correlate("jd", {("darkweb", "jd"): empty})["exposure"] == []
    assert correlate("jd", {("darkweb", "jd"): hit})["exposure"] == [
        {"source": "darkweb", "selectors": ["jd"]}
    ]


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
def _case():
    from factories import exporter

    collected = {
        ("github", "jd"): _ok(
            "github",
            "jd",
            profile=[
                {
                    "social": [
                        {
                            "name": "GitHub",
                            "url": "https://github.com/jd",
                            "username": "jd",
                        }
                    ]
                },
                {"name": "John <Doe>"},
                {"email": "jd@x.com"},
            ],
        ),
        ("telegram", "jd"): _ok(
            "telegram",
            "jd",
            profile=[
                {
                    "social": [
                        {
                            "name": "github",
                            "url": "https://github.com/jd",
                            "username": "jd",
                        }
                    ]
                },
                {"name": "John <Doe>"},
                {"wallet": [{"currency": "BTC", "address": BTC}]},
            ],
        ),
        ("hudsonrock", "jd@x.com"): _ok("hudsonrock", "jd@x.com"),
        ("kick", "jd"): [
            {"module": "kick"},
            {"param": "jd"},
            {"validation": "not_used"},
            {"raw": [{"status": "Warning", "reason": "blocked"}]},
        ],
    }
    collected[("github", "jd")][6]["timeline"].append(
        {"date": "2015-01-01", "action": "created"}
    )
    return exporter.build_case("jd", collected)


def test_build_case_and_hash_is_stable():
    a, b = _case(), _case()
    assert (
        a["evidence_sha256"] == b["evidence_sha256"] and len(a["evidence_sha256"]) == 64
    )
    assert a["modules"]["kick"]["jd"]["status"] == "Warning"
    assert a["timeline"][0]["module"] == "github"


@pytest.mark.parametrize("fmt", ["json", "html", "pdf", "stix", "graphml", "csv"])
def test_export_formats_render(fmt):
    from factories import exporter

    body = exporter.render(_case(), fmt)
    assert body
    if fmt == "pdf":
        assert body.startswith(b"%PDF")
    if fmt == "html":
        text = body.decode()
        assert "John &lt;Doe&gt;" in text and "<Doe>" not in text  # escaped
        assert "evidence" in text.lower() or "Evidence" in text
    if fmt == "graphml":
        xml.dom.minidom.parseString(body)
    if fmt in ("json", "stix"):
        json.loads(body)


def test_stix_bundle_references_resolve():
    from factories import exporter

    bundle = json.loads(exporter.to_stix(_case()))
    ids = {o["id"] for o in bundle["objects"]}
    for o in bundle["objects"]:
        assert o["id"].split("--")[0] == o["type"]
        for ref in [
            o.get("source_ref"),
            o.get("target_ref"),
            *(o.get("object_refs") or []),
        ]:
            if ref:
                assert ref in ids
    types = {o["type"] for o in bundle["objects"]}
    assert {
        "identity",
        "user-account",
        "email-addr",
        "relationship",
        "observed-data",
        "note",
    } <= types


def test_export_endpoint(client):
    result_cache.store(
        "github",
        "jd",
        _ok(
            "github",
            "jd",
            profile=[
                {
                    "social": [
                        {
                            "name": "GitHub",
                            "url": "https://github.com/jd",
                            "username": "jd",
                        }
                    ]
                }
            ],
        ),
    )
    r = client.get("/export/jd?format=csv")
    assert r.status_code == 200 and "github" in r.text.lower()
    assert 'filename="veiled-eye-jd.csv"' in r.headers["content-disposition"]
    assert client.get("/export/jd?format=docx").status_code == 400
    assert client.get("/export/nobody?format=html").status_code == 404


# ---------------------------------------------------------------------------
# quiet (thread-local silencing)
# ---------------------------------------------------------------------------
def test_silenced_only_affects_current_thread(capsys):
    started, release = threading.Event(), threading.Event()

    def noisy():
        with silenced():
            print("HIDDEN")
            started.set()
            release.wait(2)

    t = threading.Thread(target=noisy)
    t.start()
    started.wait(2)
    print("VISIBLE")
    release.set()
    t.join()
    out = capsys.readouterr().out
    assert "VISIBLE" in out and "HIDDEN" not in out


# ---------------------------------------------------------------------------
# CLI routing / export
# ---------------------------------------------------------------------------
def test_cli_routes_selectors_and_exports(tmp_path, monkeypatch):
    import cli

    monkeypatch.setattr(cli, "VEILED_HOME", tmp_path / "home")
    calls = []

    def fake_run(module, param):
        calls.append((module, param))
        if module == "crossref":
            from modules.crossref.crossref_tasks import t_crossref

            return t_crossref(param, dev_mode=False)
        out = _ok(
            module, param, profile=[{"phone": param}] if module == "phone" else []
        )
        result_cache.store(module, param, out)
        return out

    with patch.object(cli, "_run_module", side_effect=fake_run):
        rc = cli.main(
            [
                "scan",
                "+905321234567",
                BTC,
                "--no-chain",
                "-x",
                "html,stix",
                "--outdir",
                str(tmp_path / "out"),
            ]
        )
    assert rc == 0
    assert ("phone", "+905321234567") in calls and ("crypto", BTC) in calls
    assert not any(m == "maigret" for m, _ in calls)
    assert (tmp_path / "out" / "veiled-eye-_905321234567.html").is_file()
    assert (tmp_path / "out" / f"veiled-eye-{BTC}.stix.json").is_file()


@pytest.mark.parametrize(
    ("target", "module"),
    [("+905321234567", "phone"), (BTC, "crypto"), ("acme.com", "wayback")],
)
def test_crossref_collects_non_username_selectors(target, module):
    from modules.crossref.crossref_tasks import collect

    result_cache.store(module, target, _ok(module, target))
    assert (module, target) in collect(target, 0)
