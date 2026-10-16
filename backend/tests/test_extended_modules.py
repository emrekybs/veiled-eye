"""Tests for the extended modules (maigret, userscanner, darksherlock,
gitsniff, crosslinked, crossref) and the auto-chain / result-cache glue.

Network is always mocked.  Where possible the *real* third-party result
objects are used (user-scanner ``Result``, maigret ``MaigretCheckResult``)
so attribute drift in those libraries is caught here.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from factories import chain, result_cache
from module_registry import MODULE_REGISTRY

EXTENDED = (
    "maigret",
    "userscanner",
    "darksherlock",
    "gitsniff",
    "crosslinked",
    "crossref",
)
ORDER = ["module", "param", "validation", "raw", "graphic", "profile", "timeline"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No dev-mode golden files, in-memory cache, clean between tests."""
    monkeypatch.setenv("VEILED_CACHE", "memory")
    monkeypatch.setenv("VEILED_CROSSREF_WAIT", "0")
    result_cache.clear_memory()
    with patch.object(Path, "cwd", return_value=tmp_path):
        yield
    result_cache.clear_memory()


def keys(result):
    return [next(iter(item)) for item in result]


def section(result, key):
    return next(item[key] for item in result if key in item)


# ---------------------------------------------------------------------------
# Registry / contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", EXTENDED)
def test_registered(name):
    path, pass_from = MODULE_REGISTRY[name]
    assert path == f"modules.{name}.{name}_tasks.t_{name}"
    assert pass_from is False


def test_celery_imports_extended():
    from celery_app import celery

    for name in EXTENDED:
        assert f"modules.{name}.{name}_tasks" in celery.conf.imports


def test_tasklist_exposes_extended(client):
    mods = client.get("/tasklist").json()["modules"]
    for name in EXTENDED:
        assert name in mods


# ---------------------------------------------------------------------------
# darksherlock
# ---------------------------------------------------------------------------
def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    return r


def test_darksherlock_success():
    from modules.darksherlock.darksherlock_tasks import t_darksherlock

    payload = {
        "results": [{"forum": "XSS", "date": "2023-01-02"}, {"source": "Exploit"}]
    }
    with patch(
        "modules.darksherlock.darksherlock_tasks.requests.get",
        return_value=_resp(200, payload),
    ):
        out = t_darksherlock("someuser@mail.com", dev_mode=False)
    assert keys(out) == ORDER
    gather = section(out, "graphic")[0]["darksherlock"]
    assert [n["title"] for n in gather[1:]] == ["XSS", "Exploit"]
    assert section(out, "raw")["username"] == "someuser"  # local part used
    assert len(section(out, "timeline")) == 1


def test_darksherlock_no_hits_is_warning():
    from modules.darksherlock.darksherlock_tasks import t_darksherlock

    with patch(
        "modules.darksherlock.darksherlock_tasks.requests.get",
        return_value=_resp(200, {"results": []}),
    ):
        out = t_darksherlock("nobody", dev_mode=False)
    assert section(out, "raw")[0]["status"] == "Warning"


def test_darksherlock_rate_limit():
    from modules.darksherlock.darksherlock_tasks import t_darksherlock

    with patch(
        "modules.darksherlock.darksherlock_tasks.requests.get", return_value=_resp(429)
    ):
        out = t_darksherlock("x", dev_mode=False)
    assert "Rate limited" in section(out, "raw")[0]["reason"]


# ---------------------------------------------------------------------------
# maigret
# ---------------------------------------------------------------------------
def _maigret_info(site, claimed=True, ids=None, tags=None, rank=1):
    from maigret.result import MaigretCheckResult, MaigretCheckStatus

    status = MaigretCheckResult(
        "johndoe",
        site,
        f"https://{site.lower()}.com/johndoe",
        MaigretCheckStatus.CLAIMED if claimed else MaigretCheckStatus.AVAILABLE,
        ids_data=ids or {},
        tags=tags or [],
    )
    return {
        "status": status,
        "url_user": f"https://{site.lower()}.com/johndoe",
        "http_status": 200,
        "rank": rank,
        "ids_usernames": {"jdoe_alt": "username"},
        "ids_links": ["https://jdoe.dev"],
    }


def test_maigret_success_maps_identity():
    from modules.maigret.maigret_tasks import t_maigret

    raw = {
        "GitHub": _maigret_info(
            "GitHub",
            ids={
                "fullname": "John Doe",
                "image": "https://img/x.png",
                "created_at": "2015-01-01",
            },
            tags=["coding"],
        ),
        "Reddit": _maigret_info("Reddit", tags=["forum"], rank=5),
        "Nope": _maigret_info("Nope", claimed=False),
    }
    with patch("modules.maigret.maigret_tasks._run_maigret", return_value=raw):
        out = t_maigret("johndoe", dev_mode=False)
    assert keys(out) == [*ORDER, "tasks"]
    # the alternative handle maigret parsed is swept next
    assert {"module": "maigret", "param": "jdoe_alt"} in section(out, "tasks")
    gather = section(out, "graphic")[0]["maigret"]
    assert [n["title"] for n in gather[1:]] == ["GitHub", "Reddit"]
    profile = section(out, "profile")
    assert {"name": "John Doe"} in profile
    assert any("photos" in p for p in profile)
    assert section(out, "timeline")[0]["date"] == "2015-01-01"
    pivots = section(out, "graphic")[3]["pivots"]
    assert pivots["usernames"] == ["jdoe_alt"]


def test_maigret_crosscheck_linked_profiles():
    """A GitHub bio linking x.com/emrekybs8 adds that Twitter account."""
    from modules.maigret.maigret_tasks import t_maigret

    raw = {
        "GitHub": _maigret_info(
            "GitHub",
            ids={"bio": "infosec", "twitter": "https://x.com/emrekybs8"},
            tags=["coding"],
        ),
    }
    with patch("modules.maigret.maigret_tasks._run_maigret", return_value=raw):
        out = t_maigret("emrekybs", dev_mode=False)
    social = section(out, "profile")[0]["social"]
    tw = [s for s in social if s["username"] == "emrekybs8"]
    assert tw and tw[0]["url"] == "https://x.com/emrekybs8"
    assert tw[0]["linked_from"] == "GitHub"
    tasks = section(out, "tasks")
    assert {"module": "twitter", "param": "emrekybs8"} in tasks
    assert {"module": "maigret", "param": "emrekybs8"} in tasks
    assert section(out, "raw")["crosscheck"][0]["platform"] == "twitter"


def test_maigret_nothing_found():
    from modules.maigret.maigret_tasks import t_maigret

    with patch(
        "modules.maigret.maigret_tasks._run_maigret",
        return_value={"A": _maigret_info("A", claimed=False)},
    ):
        out = t_maigret("johndoe", dev_mode=False)
    assert section(out, "raw")[0]["status"] == "Warning"


def test_maigret_settings_env(monkeypatch):
    from modules.maigret import maigret_tasks

    monkeypatch.setenv("VEILED_MAIGRET_TOP", "all")
    monkeypatch.setenv("TOR_PROXY_URL", "socks5h://tor:9050")
    cfg = maigret_tasks._settings()
    assert cfg["top"] > 10_000
    assert cfg["tor"] == "socks5://tor:9050"


# ---------------------------------------------------------------------------
# userscanner
# ---------------------------------------------------------------------------
def _us(site, status="taken", is_email=False, **extra):
    from user_scanner.core.result import Result

    factory = getattr(Result, status)
    return factory(
        username="john@x.com" if is_email else "johndoe",
        site_name=site,
        category="Social",
        url=f"https://{site.lower()}.com/johndoe",
        is_email=is_email,
        extra=extra,
    )


def test_userscanner_username_with_cross():
    from modules.userscanner.userscanner_tasks import t_userscanner

    first = [_us("GitHub", name="John Doe"), _us("Nope", status="available")]
    cross = [_us("Twitter", confidence="likely", pivot_source="link from GitHub")]
    with patch(
        "modules.userscanner.userscanner_tasks._scan", return_value=(first, cross)
    ):
        out = t_userscanner("johndoe", dev_mode=False)
    assert keys(out) == ORDER
    lists = section(out, "graphic")[1]["lists"]
    assert [(r["title"], r["pass"], r["confidence"]) for r in lists] == [
        ("GitHub", "first", "confirmed"),
        ("Twitter", "cross", "likely"),
    ]
    assert {"name": "John Doe"} in section(out, "profile")


def test_userscanner_email_is_hard_validation():
    from modules.userscanner.userscanner_tasks import t_userscanner

    first = [_us("Spotify", is_email=True)]
    with patch("modules.userscanner.userscanner_tasks._scan", return_value=(first, [])):
        out = t_userscanner("john@x.com", dev_mode=False)
    assert section(out, "validation") == "hard"
    assert {"email": "john@x.com"} in section(out, "profile")


def test_userscanner_nothing_found():
    from modules.userscanner.userscanner_tasks import t_userscanner

    with patch(
        "modules.userscanner.userscanner_tasks._scan",
        return_value=([_us("A", status="available")], []),
    ):
        out = t_userscanner("johndoe", dev_mode=False)
    assert section(out, "raw")[0]["status"] == "Warning"


# ---------------------------------------------------------------------------
# gitsniff
# ---------------------------------------------------------------------------
def test_gitsniff_groups_emails():
    from modules.gitsniff.gitsniff_tasks import t_gitsniff

    entries = [
        {
            "email": "a@x.com",
            "name": "Al",
            "repo": "https://github.com/u/r1",
            "commit_sha": "1",
        },
        {
            "email": "a@x.com",
            "name": "Al",
            "repo": "https://github.com/u/r2",
            "commit_sha": "2",
        },
        {
            "email": "b@y.com",
            "name": "Bo",
            "repo": "https://github.com/u/r1",
            "commit_sha": "3",
        },
    ]
    with patch("modules.gitsniff.gitsniff_tasks._scan", return_value=entries):
        out = t_gitsniff("u", dev_mode=False)
    lists = section(out, "graphic")[1]["lists"]
    assert lists[0]["title"] == "a@x.com" and lists[0]["commits"] == 2
    profile = section(out, "profile")
    assert {"email": "b@y.com"} in profile and {"name": "Al"} in profile


def test_gitsniff_scanner_is_thread_safe():
    """GitSniff installs a SIGINT handler in __init__ — must not explode in threads."""
    import threading

    from modules.gitsniff.gitsniff_tasks import _make_scanner

    errors = []

    def build():
        try:
            _make_scanner()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    t = threading.Thread(target=build)
    t.start()
    t.join()
    assert errors == []


# ---------------------------------------------------------------------------
# crosslinked
# ---------------------------------------------------------------------------
def test_crosslinked_domain_derives_emails():
    from modules.crosslinked.crosslinked_tasks import t_crosslinked

    found = [
        {
            "url": "https://linkedin.com/in/jane",
            "name": "Jane Smith",
            "title": "CISO",
            "engine": "bing",
        },
        {
            "url": "https://linkedin.com/in/jane",
            "name": "Jane Smith",
            "title": "CISO",
            "engine": "google",
        },
    ]
    with patch(
        "modules.crosslinked.crosslinked_tasks._search", return_value=found
    ) as search:
        out = t_crosslinked("acme.com.tr", dev_mode=False)
    search.assert_called_once_with("acme")
    lists = section(out, "graphic")[1]["lists"]
    assert len(lists) == 1
    assert "jane.smith@acme.com.tr" in lists[0]["emails"]
    assert {"organization": "acme"} in section(out, "profile")


def test_crosslinked_company_name_no_emails():
    from modules.crosslinked.crosslinked_tasks import t_crosslinked

    found = [{"url": "u", "name": "Jane Smith", "title": "Dev"}]
    with patch("modules.crosslinked.crosslinked_tasks._search", return_value=found):
        out = t_crosslinked("Acme Corp", dev_mode=False)
    assert section(out, "graphic")[1]["lists"][0]["emails"] == []


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------
def _ok_result(module, param, graphic=None, profile=None):
    return [
        {"module": module},
        {"param": param},
        {"validation": "soft"},
        {"raw": {}},
        {"graphic": graphic or []},
        {"profile": profile or []},
        {"timeline": []},
    ]


def test_chain_username_anchor():
    tasks = chain.next_tasks(_ok_result("search", "johndoe"))
    assert {"module": "maigret", "param": "johndoe"} in tasks
    assert {"module": "darksherlock", "param": "johndoe"} in tasks


def test_chain_corporate_email_triggers_crosslinked():
    tasks = chain.next_tasks(_ok_result("holehe", "j@acme.com"))
    assert {"module": "userscanner", "param": "j@acme.com"} in tasks
    assert {"module": "crosslinked", "param": "acme.com"} in tasks
    tasks = chain.next_tasks(_ok_result("holehe", "j@gmail.com"))
    assert not any(t["module"] == "crosslinked" for t in tasks)


def test_chain_github_company_and_gitsniff():
    graphic = [{"github": [{"name-node": "GitCompany", "subtitle": "@acme"}]}]
    tasks = chain.next_tasks(_ok_result("github", "johndoe", graphic))
    assert {"module": "gitsniff", "param": "johndoe"} in tasks
    assert {"module": "crosslinked", "param": "acme"} in tasks


def test_chain_error_result_does_not_trigger_github_followups():
    err = [
        {"module": "github"},
        {"param": "x"},
        {"validation": "not_used"},
        {"raw": [{"status": "Fail"}]},
    ]
    assert chain.next_tasks(err) == []


def test_chain_inject_merges_existing_tasks_and_keeps_order():
    res = [
        *_ok_result("search", "johndoe"),
        {"tasks": [{"module": "twitter", "param": "johndoe"}]},
    ]
    out = chain.inject(res)
    assert keys(out) == [*ORDER, "tasks"]
    mods = [t["module"] for t in out[7]["tasks"]]
    assert mods[0] == "twitter" and "maigret" in mods


def test_chain_disabled(monkeypatch):
    monkeypatch.setenv("VEILED_AUTOCHAIN", "0")
    res = _ok_result("search", "johndoe")
    assert chain.inject(res) == _ok_result("search", "johndoe")


def test_company_from_domain():
    assert chain.company_from_domain("mail.acme-corp.com") == "acme corp"
    assert chain.company_from_domain("acme.co.uk") == "acme"
    assert chain.company_from_domain("gmail.com") is None


def test_result_endpoint_injects_tasks(client, mock_celery_send):
    mock_celery_send.AsyncResult.return_value.get.return_value = _ok_result(
        "dorks", "johndoe"
    )
    body = client.get("/result/abc").json()["result"]
    assert keys(body)[-1] == "tasks"
    assert {"module": "maigret", "param": "johndoe"} in body[-1]["tasks"]


def test_result_endpoint_passthrough_non_list(client, mock_celery_send):
    body = client.get("/result/abc").json()
    assert body == {"result": {"raw": "result-data"}}


# ---------------------------------------------------------------------------
# result cache + crossref
# ---------------------------------------------------------------------------
def test_task_wrapper_stores_in_cache():
    from modules.darksherlock.darksherlock_tasks import t_darksherlock

    with patch(
        "modules.darksherlock.darksherlock_tasks.requests.get",
        return_value=_resp(200, {"results": [{"forum": "XSS"}]}),
    ):
        t_darksherlock("johndoe", dev_mode=False)
    assert result_cache.state("darksherlock", "johndoe") == "DONE"
    assert result_cache.fetch("darksherlock", "johndoe")[0] == {
        "module": "darksherlock"
    }


def _social(name, user, source):
    return {
        "name": name,
        "url": f"https://{name}.com/{user}",
        "icon": "",
        "source": source,
        "username": user,
    }


def test_crossref_correlates_sources():
    from modules.crossref.crossref_tasks import t_crossref

    result_cache.store(
        "maigret",
        "johndoe",
        _ok_result(
            "maigret",
            "johndoe",
            profile=[
                {
                    "social": [
                        _social("GitHub", "johndoe", "maigret"),
                        _social("Reddit", "johndoe", "maigret"),
                    ]
                },
                {"name": "John Doe"},
            ],
        ),
    )
    result_cache.store(
        "userscanner",
        "johndoe",
        _ok_result(
            "userscanner",
            "johndoe",
            graphic=[
                {"userscanner": []},
                {
                    "lists": [
                        {
                            "title": "Reddit",
                            "subtitle": "johndoe",
                            "confidence": "confirmed",
                        }
                    ]
                },
            ],
            profile=[
                {
                    "social": [
                        _social("github", "johndoe", "userscanner"),
                        _social("Reddit", "johndoe", "userscanner"),
                    ]
                }
            ],
        ),
    )
    result_cache.store(
        "github",
        "johndoe",
        _ok_result(
            "github",
            "johndoe",
            profile=[
                {"social": [_social("Github", "johndoe", "Github")]},
                {"name": "John Doe"},
                {"email": "jd@acme.com"},
            ],
        ),
    )
    result_cache.store(
        "darksherlock",
        "johndoe",
        _ok_result(
            "darksherlock",
            "johndoe",
            profile=[{"social": [_social("XSS", "johndoe", "darksherlock")]}],
        ),
    )
    # hop: e-mail discovered by github is looked up too
    result_cache.store(
        "hudsonrock", "jd@acme.com", _ok_result("hudsonrock", "jd@acme.com")
    )

    out = t_crossref("johndoe", dev_mode=False)
    assert keys(out) == ORDER
    accounts = {
        (a["platform"].lower(), a["handle"]): a
        for a in section(out, "graphic")[1]["accounts"]
    }
    gh = accounts[("github", "johndoe")]
    assert gh["confidence"] == "confirmed" and gh["score"] == 3
    assert (
        accounts[("reddit", "johndoe")]["confidence"] == "confirmed"
    )  # user-scanner hint
    assert accounts[("xss", "johndoe")]["underground"] is True
    identity = section(out, "graphic")[2]["identity"]
    assert identity["name"][0] == {
        "value": "John Doe",
        "sources": ["github", "maigret"],
        "score": 2,
    }
    exposure = section(out, "graphic")[4]["exposure"]
    assert {"source": "hudsonrock", "selectors": ["jd@acme.com"]} in exposure
    assert {"name": "John Doe"} in section(out, "profile")


def test_crossref_nothing_cached_is_warning():
    from modules.crossref.crossref_tasks import t_crossref

    out = t_crossref("ghost", dev_mode=False)
    assert section(out, "raw")[0]["status"] == "Warning"


def test_crossref_skips_error_outputs():
    from modules.crossref.crossref_tasks import correlate

    err = [
        {"module": "maigret"},
        {"param": "x"},
        {"validation": "not_used"},
        {"raw": [{"status": "Fail"}]},
    ]
    rep = correlate("x", {("maigret", "x"): err})
    assert rep["sources_error"] == ["maigret"] and rep["accounts"] == []


def test_crossref_platform_normalisation():
    from modules.crossref.crossref_tasks import norm_platform

    assert norm_platform("x | twitter") == "twitter"
    assert norm_platform("GitHub.com") == "github"
    assert norm_platform("LinkedIn - Jane Smith") == "linkedin"
