"""Veiled Eye UI: platform categories, selector routing, non-blocking /result
and the frontend patcher (anchors + idempotency)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from factories import categories, chain
from factories.identity import selector_type

BACKEND = Path(__file__).resolve().parents[1]
OVERLAY = BACKEND.parent / "tools" / "ui_build"
sys.path.insert(0, str(OVERLAY))
DIST = BACKEND / "frontend_dist"


# ---------------------------------------------------------------------------
# platform categories
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "kw", "kind"),
    [
        ("Cracked", {"module": "darksherlock"}, "underground"),
        ("Some forum", {"url": "http://abcdefghijklmnop.onion/u/x"}, "underground"),
        ("Reddit", {}, "forum"),
        ("Snapchat", {}, "social"),
        ("Telegram", {}, "messaging"),
        ("GitHub", {}, "dev"),
        ("Steam", {}, "gaming"),
    ],
)
def test_classify(name, kw, kind):
    assert categories.classify(name, **kw) == kind


def test_decorate_adds_category_and_icon_class():
    res = [
        {"module": "maigret"},
        {"param": "johndoe"},
        {"validation": "soft"},
        {"raw": {}},
        {"graphic": []},
        {
            "profile": [
                {
                    "social": [
                        {
                            "name": "reddit",
                            "url": "https://reddit.com/u/johndoe",
                            "icon": "fab fa-reddit",
                        }
                    ]
                }
            ]
        },
        {"timeline": []},
    ]
    out = categories.decorate(res)
    social = out[5]["profile"][0]["social"][0]
    assert social["category"] == "forum"
    assert "cat-forum" in social["icon"].split()
    # idempotent: decorating twice does not stack classes
    again = categories.decorate(out)[5]["profile"][0]["social"][0]
    assert again["icon"].split().count("cat-forum") == 1


def test_decorate_never_raises_on_odd_input():
    for odd in (None, "x", {"raw": 1}, [None, 3, "a"]):
        categories.decorate(odd)


# ---------------------------------------------------------------------------
# selector routing (single search box)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("john@acme.com", "email"),
        ("+90 532 123 45 67", "phone"),
        ("05321234567", "phone"),
        ("0x52908400098527886E0F7030069857D2E4169EE7", "wallet"),
        ("johndoe", "username"),
    ],
)
def test_selector_type(value, kind):
    assert selector_type(value) == kind


def _ok(module, param):
    return [
        {"module": module},
        {"param": param},
        {"validation": "hard"},
        {"raw": {}},
        {"graphic": []},
        {"profile": []},
        {"timeline": []},
    ]


def test_chain_routes_phone_and_wallet_from_username_box():
    phone = chain.inject(_ok("search", "+905321234567"))
    mods = {t["module"] for t in phone[-1]["tasks"]}
    assert "phone" in mods and "maigret" not in mods

    wallet = chain.inject(_ok("search", "0x52908400098527886E0F7030069857D2E4169EE7"))
    mods = {t["module"] for t in wallet[-1]["tasks"]}
    assert "crypto" in mods and "maigret" not in mods


# ---------------------------------------------------------------------------
# /result no longer parks a thread for the whole task
# ---------------------------------------------------------------------------
def test_result_returns_504_quickly_when_not_ready(client, mock_celery_send):
    mock_celery_send.AsyncResult.return_value.ready.return_value = False
    r = client.get("/result/abc?wait=0.2")
    assert r.status_code == 504


def test_result_ready_is_decorated(client, mock_celery_send):
    ar = mock_celery_send.AsyncResult.return_value
    ar.ready.return_value = True
    ar.get.return_value = _ok("maigret", "johndoe")
    body = client.get("/result/abc").json()["result"]
    assert body[0] == {"module": "maigret"}


# ---------------------------------------------------------------------------
# frontend patcher
# ---------------------------------------------------------------------------
def _fake_upstream(root: Path) -> None:
    """Minimal bundle that carries every anchor the patcher looks for."""
    import patch as P

    root.mkdir(parents=True)
    (root / "index.html").write_text(
        '<html><head><title>Veiled Eye</title><meta name="theme-color" content="#05fcfc"></head><body></body></html>',
        encoding="utf-8",
    )
    # spread anchors over several files like the real build
    olds = [old for _, old, _ in P.JS_PATCHES]
    half = len(olds) // 2
    (root / "main-AAAA.js").write_text(
        ";".join(olds[:half]) + ";a{color:#05fcfc;font-family:Roboto,sans-serif}",
        encoding="utf-8",
    )
    (root / "chunk-BBBB.js").write_text(";".join(olds[half:]), encoding="utf-8")
    (root / "styles-CCCC.css").write_text("b{background:#016565}", encoding="utf-8")


def test_patch_applies_every_anchor_and_is_idempotent(tmp_path):
    from patch import patch

    root = tmp_path / "dist"
    _fake_upstream(root)
    first = patch(root)
    assert not [line for line in first if line.startswith("SKIP")], first
    snapshot = {
        p.name: p.read_bytes() for p in root.glob("*.*") if p.name != ".veiled-patched"
    }

    second = patch(root)
    assert not [line for line in second if line.startswith(("SKIP", "ok "))], second
    assert {
        p.name: p.read_bytes() for p in root.glob("*.*") if p.name != ".veiled-patched"
    } == snapshot

    html = (root / "index.html").read_text(encoding="utf-8")
    assert "<title>Veiled Eye" in html and "veiled.js" in html and "veiled.css" in html
    main = (root / "main-AAAA.js").read_text(encoding="utf-8")
    # stock look kept, neon cyan moved to the logo's ice blue
    assert "05fcfc" not in main and "4fd2ff" in main
    assert (root / "assets" / "images" / "blur-bg.jpg").is_file()


def test_patch_reports_missing_anchors(tmp_path):
    from patch import patch

    root = tmp_path / "other"
    root.mkdir()
    (root / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
    (root / "main.js").write_text("nothing here", encoding="utf-8")
    report = patch(root)
    assert any(line.startswith("SKIP") for line in report)


@pytest.mark.skipif(not DIST.is_dir(), reason="bundled UI not present")
def test_bundled_dist_is_fully_patched(tmp_path):
    from patch import patch

    copy = tmp_path / "dist"
    shutil.copytree(DIST, copy)
    report = patch(copy)
    assert not [line for line in report if line.startswith(("SKIP", "ok "))], report
    assert (copy / "veiled.js").read_text(encoding="utf-8") == (
        OVERLAY / "veiled.js"
    ).read_text(encoding="utf-8")
    assert (copy / "veiled.css").read_text(encoding="utf-8") == (
        OVERLAY / "veiled.css"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(not DIST.is_dir(), reason="bundled UI not present")
def test_bundled_ui_has_no_upstream_branding():
    import re

    for path in DIST.rglob("*"):
        if path.is_file() and path.suffix in {".js", ".css", ".html"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not re.search(r"iky|kennbro", text, re.I), path.name
    assert not (DIST / "assets" / "images" / "iKy-Logo.png").exists()


# ---------------------------------------------------------------------------
# relationship graph (/graph)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not DIST.is_dir(), reason="bundled UI not present")
def test_bundled_graph_assets():
    assert (DIST / "graph.js").read_text(encoding="utf-8") == (
        OVERLAY / "graph.js"
    ).read_text(encoding="utf-8")
    for name in (
        "cytoscape.min.js",
        "layout-base.js",
        "cose-base.js",
        "cytoscape-fcose.js",
        "LICENSE-cytoscape",
        "LICENSE-cytoscape-fcose",
    ):
        assert (DIST / "assets" / "graph" / name).is_file(), name
    bundle = "".join(p.read_text(encoding="utf-8") for p in DIST.glob("main-*.js"))
    assert '{title:"Graph",icon:"fa-circle-nodes",link:"/graph"}' in bundle


_GRAPH_HARNESS = r"""
const fs = require("fs");
const results = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
global.window = {};
global.document = {};
const kind = (v) => /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v) ? "email"
  : /^\+?[\d\s().-]{9,}$/.test(v) ? "phone" : "username";
window.__veiled = {
  kind, label: (m) => m, catLabel: (c) => c, subscribe() {},
  reverseLinks: () => ({}), state: () => ({ results, roots: ["tailmon"] }),
};
window.cytoscape = function () {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const m = window.__veiledGraph.model();
const out = { nodes: {}, edges: [] };
for (const [id, n] of Object.entries(m.nodes)) out.nodes[id] = { type: n.type, label: n.label, confidence: n.confidence, sources: Object.keys(n.sources) };
for (const e of Object.values(m.edges)) out.edges.push([e.source, e.target, e.kind, Object.keys(e.checks)]);
console.log(JSON.stringify(out));
"""


def _res(module, param, profile=(), tasks=None, raw=None):
    r = [
        {"module": module},
        {"param": param},
        {"validation": "hard"},
        {"raw": raw if raw is not None else {}},
        {"graphic": []},
        {"profile": list(profile)},
        {"timeline": []},
    ]
    if tasks is not None:
        r.append({"tasks": tasks})
    return r


def _soc(name, user, cat="social"):
    return {
        "name": name,
        "url": f"https://{name.lower()}.com/{user}",
        "username": user,
        "category": cat,
    }


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_graph_model(tmp_path):
    import json
    import subprocess

    results = {
        "github|tailmon": _res(
            "github",
            "tailmon",
            [
                {"name": "Deniz Arslan"},
                {"location": "Istanbul, Turkey"},
                {"email": "Deniz@Acme-Labs.io"},
                {
                    "social": [
                        {
                            "name": "Blog",
                            "url": "https://denizarslan.dev",
                            "username": "tailmon",
                        }
                    ]
                },
            ],
            tasks=[{"module": "emailreg", "param": "deniz@acme-labs.io", "depth": 1}],
        ),
        "instagram|tailmon": _res(
            "instagram", "tailmon", [{"name": "Deniz Arslan"}, {"location": "İstanbul"}]
        ),
        "maigret|tailmon": _res(
            "maigret",
            "tailmon",
            [
                {
                    "social": [_soc("GitHub", "tailmon", "dev")]
                    + [_soc(f"Site{i}", "tailmon") for i in range(40)]
                }
            ],
        ),
        "emailreg|deniz@acme-labs.io": _res(
            "emailreg",
            "deniz@acme-labs.io",
            [{"social": [_soc("Spotify", "deniz@acme-labs.io", "music")]}],
        ),
        "steam|tailmon": _res(
            "steam", "tailmon", raw=[{"status": "Fail", "reason": "HTTP 0"}]
        ),
    }
    data = tmp_path / "results.json"
    data.write_text(json.dumps(results), encoding="utf-8")
    harness = tmp_path / "harness.js"
    harness.write_text(_GRAPH_HARNESS, encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), str(OVERLAY / "graph.js"), str(data)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    g = json.loads(out.stdout)
    nodes, edges = g["nodes"], g["edges"]

    # the consensus name became the subject, joined to the searched username
    assert nodes["subject"]["label"] == "Deniz Arslan"
    assert ["subject", "sel:username:tailmon", "root", []] in edges
    # the platform's own module confirms its account; maigret adds a source
    gh = nodes["acc:github:tailmon"]
    assert gh["confidence"] == "confirmed" and set(gh["sources"]) == {
        "github",
        "maigret",
    }
    # e-mails are canonical, and the followed lead is a pivot edge
    assert "sel:email:deniz@acme-labs.io" in nodes
    assert [
        "acc:github:tailmon",
        "sel:email:deniz@acme-labs.io",
        "pivot",
        ["emailreg"],
    ] in edges
    # registrations are not accounts; a blog is a domain lead
    assert nodes["acc:spotify:deniz@acme-labs.io"]["type"] == "signup"
    assert nodes["sel:domain:denizarslan.dev"]["type"] == "domain"
    # "Istanbul, Turkey" and "İstanbul" are one place
    assert len([n for n in nodes.values() if n["type"] == "place"]) == 1
    # a failed source adds nothing
    assert not any("steam" in n["sources"] for n in nodes.values())
