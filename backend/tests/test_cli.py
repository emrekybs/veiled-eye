"""Tests for the pip/pipx ``veiled-eye`` CLI (scan orchestration + serve gateway)."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import cli
import pytest
from factories import result_cache
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "VEILED_HOME", tmp_path / "home")
    monkeypatch.setenv("VEILED_CACHE", "memory")
    result_cache.clear_memory()
    with patch.object(Path, "cwd", return_value=tmp_path):
        yield
    result_cache.clear_memory()


def _out(module, param, profile, graphic=None):
    return [
        {"module": module},
        {"param": param},
        {"validation": "soft"},
        {"raw": {}},
        {"graphic": graphic or [{module: [{"name-node": module}]}]},
        {"profile": profile},
        {"timeline": []},
    ]


def _social(name, user):
    return {
        "name": name,
        "url": f"https://{name}.com/{user}",
        "icon": "",
        "source": "x",
        "username": user,
    }


def test_scan_follows_chain_and_correlates(tmp_path, capsys):
    calls = []
    real_run = cli._run_module

    def fake_run(module, param):
        calls.append((module, param))
        if module == "crossref":
            return real_run(module, param)  # real correlation over the cache
        if module == "github":
            out = _out(
                "github",
                param,
                [{"social": [_social("github", param)]}, {"name": "John Doe"}],
                [{"github": [{"name-node": "GitCompany", "subtitle": "acme"}]}],
            )
        elif module == "maigret":
            out = _out(
                "maigret",
                param,
                [{"social": [_social("GitHub", param), _social("Reddit", param)]}],
            )
        elif module == "userscanner":
            out = _out(
                "userscanner",
                param,
                [{"social": [_social("github", param)]}, {"name": "John Doe"}],
            )
        else:
            out = [
                {"module": module},
                {"param": param},
                {"validation": "not_used"},
                {"raw": [{"status": "Warning", "reason": "nothing"}]},
            ]
        result_cache.store(module, param, out)
        return out

    report = tmp_path / "r.json"
    with patch.object(cli, "_run_module", side_effect=fake_run):
        rc = cli.main(["scan", "johndoe", "-w", "2", "-o", str(report)])
    assert rc == 0
    # github result chained gitsniff + crosslinked(company)
    assert ("gitsniff", "johndoe") in calls
    assert ("crosslinked", "acme") in calls
    assert calls[-1] == ("crossref", "johndoe")

    data = json.loads(report.read_text())
    accounts = data["crossref"]["johndoe"][4]["graphic"][1]["accounts"]
    gh = next(a for a in accounts if a["platform"].lower() == "github")
    assert gh["confidence"] == "confirmed"
    printed = capsys.readouterr().out
    assert "CROSS ANALYSIS" in printed and "John Doe" in printed


def test_scan_rejects_unknown_module(capsys):
    assert cli.main(["scan", "x", "-m", "nope"]) == 2


def test_scan_requires_target(capsys):
    assert cli.main(["scan"]) == 2


def test_modules_lists_extended(capsys):
    cli.main(["modules"])
    out = capsys.readouterr().out
    assert "maigret" in out and "extended" in out


def test_apikeys_relocated_to_veiled_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VEILED_APIKEYS", str(tmp_path / "cfg" / "apikeys.json"))
    from factories.configuration import api_keys_read

    keys = api_keys_read()
    assert isinstance(keys, list) and (tmp_path / "cfg" / "apikeys.json").is_file()


def test_gateway_serves_spa_and_api(tmp_path):
    fe = tmp_path / "fe"
    fe.mkdir()
    (fe / "index.html").write_text("<html>veiled-ui</html>")
    (fe / "main.js").write_text("console.log(1)")
    client = TestClient(cli._gateway(fe))
    assert client.get("/health").text == "ok\n"
    assert client.get("/main.js").text == "console.log(1)"
    assert "veiled-ui" in client.get("/principal/deep/route").text  # SPA fallback
    assert (
        client.get("/../../etc/passwd").text == "<html>veiled-ui</html>"
    )  # no traversal
    assert "maigret" in client.get("/api/tasklist").json()["modules"]


def test_bundled_web_ui_is_packaged():
    assert (cli.PKG_DIR / "frontend_dist" / "index.html").is_file()
    assert not hasattr(cli, "_download_frontend")  # no upstream download path


def test_server_is_an_alias_of_serve():
    args = cli.build_parser().parse_args(["server", "--port", "4301"])
    assert args.func is cli.cmd_serve and args.port == 4301


def test_local_queue_replaces_redis(tmp_path, monkeypatch):
    for name in ("VEILED_QUEUE_DIR", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        monkeypatch.setenv(name, "unset")  # restored after the test
    stale = tmp_path / "home" / "queue" / "messages" / "old.celery.msg"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    cli._use_local_queue()
    queue = tmp_path / "home" / "queue"
    assert os.environ["CELERY_BROKER_URL"] == "filesystem://"
    assert os.environ["CELERY_RESULT_BACKEND"] == (queue / "results").as_uri()
    assert os.environ["VEILED_QUEUE_DIR"] == str(queue)
    assert not stale.exists()  # tasks from a previous run are dropped
    assert all((queue / d).is_dir() for d in ("messages", "control", "results"))
