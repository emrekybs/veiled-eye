#!/usr/bin/env python
"""``veiled-eye`` command line (short alias ``veye``) — installed by ``pip install`` / ``pipx install``.

  veiled-eye scan johndoe                     # username investigation (no Redis needed)
  veiled-eye scan -e john@acme.com -u johndoe # e-mail + username, cross-correlated
  veiled-eye scan johndoe -m maigret,gitsniff -o report.json
  veiled-eye serve                            # web UI on http://127.0.0.1:4300
  veiled-eye modules                          # list modules
  veiled-eye doctor                           # check optional system dependencies

User data (API keys, session cookies, downloaded frontend) lives in
``$VEILED_HOME`` (default ``~/.config/veiled-eye``) so it survives upgrades.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
if str(PKG_DIR) not in sys.path:
    sys.path.insert(0, str(PKG_DIR))

VEILED_HOME = Path(
    os.environ.get("VEILED_HOME") or Path.home() / ".config" / "veiled-eye"
).expanduser()

from factories.chain import EMAIL_IDENTITY, USERNAME_IDENTITY  # noqa: E402

# Modules that work without API keys / cookies — the CLI default set,
# per selector type (detected automatically).
USERNAME_START = ["github", "gitlab", "keybase", "hudsonrock", *USERNAME_IDENTITY]
EMAIL_START = ["holehe", "hudsonrock", "leaks", "socialscan", *EMAIL_IDENTITY]
START = {
    "username": USERNAME_START,
    "email": EMAIL_START,
    "phone": ["phone"],
    "wallet": ["crypto"],
    "domain": ["crosslinked", "wayback", "pgp"],
}
KEYLESS = set(
    USERNAME_START
    + EMAIL_START
    + ["gitsniff", "crosslinked", "reddit", "mastodon", "phone", "crypto", "gravatar"]
)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def _prepare_env(cache: str) -> None:
    VEILED_HOME.mkdir(parents=True, exist_ok=True)
    cookies = VEILED_HOME / "cookies"
    cookies.mkdir(exist_ok=True)
    os.environ.setdefault("VEILED_APIKEYS", str(VEILED_HOME / "apikeys.json"))
    for name in ("LINKEDIN_COOKIE_DIR", "TWITTER_COOKIE_DIR", "TIKTOK_COOKIE_DIR"):
        os.environ.setdefault(name, str(cookies))
    os.environ["VEILED_CACHE"] = cache
    os.environ.setdefault("PYTHONPATH", str(PKG_DIR))


def _console():
    try:
        from rich.console import Console

        return Console(stderr=False)
    except Exception:  # pragma: no cover
        return None


def _say(con, msg: str) -> None:
    if con:
        con.print(msg)
    else:
        import re

        print(re.sub(r"\[/?[a-z #0-9]+\]", "", msg))


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------
def _load_task(module: str):
    from module_registry import MODULE_REGISTRY

    path, pass_from = MODULE_REGISTRY[module]
    mod_path, attr = path.rsplit(".", 1)
    return getattr(importlib.import_module(mod_path), attr), pass_from


def _run_module(module: str, param: str):
    task, pass_from = _load_task(module)
    args = (param, "Initial") if pass_from else (param,)
    try:
        return task(*args, dev_mode=False)
    except Exception as exc:  # modules without @module_task may raise
        return [
            {"module": module},
            {"param": param},
            {"validation": "not_used"},
            {"raw": [{"status": "Fail", "reason": str(exc)}]},
        ]


def _status(result) -> tuple[str, str]:
    from modules.crossref.crossref_tasks import is_error, section

    if is_error(result):
        raw = section(result, "raw")[0]
        reason = str(raw.get("reason", "")).split("(Caused by")[0].strip()
        return raw.get("status", "Fail"), reason[:60]
    graphic = section(result, "graphic") or []
    nodes = 0
    if graphic and isinstance(graphic[0], dict):
        first = next(iter(graphic[0].values()))
        nodes = max(0, len(first) - 1) if isinstance(first, list) else 0
    return "OK", f"{nodes} findings"


def _follow(result, allowed: set[str], chain_enabled: bool) -> list[tuple[str, str]]:
    from factories import chain

    if not chain_enabled:
        return []
    out = []
    for item in chain.inject(result) if isinstance(result, list) else []:
        if isinstance(item, dict) and isinstance(item.get("tasks"), list):
            out += [(t.get("module"), t.get("param")) for t in item["tasks"]]
    return [(m, p) for m, p in out if m in allowed and p and m != "crossref"]


def cmd_scan(args) -> int:
    _prepare_env("memory")
    os.environ["VEILED_CROSSREF_WAIT"] = "0"
    if not args.verbose:
        os.environ["VEILED_QUIET"] = "1"
        import logging

        logging.disable(logging.WARNING)
    con = _console()

    from factories.chain import EXTENDED_MODULES
    from factories.identity import selector_type
    from module_registry import MODULE_REGISTRY

    targets = [t for t in (args.target or []) if t]
    if args.email:
        targets.append(args.email)
    if args.username:
        targets.append(args.username)
    if not targets:
        print(
            "veiled-eye scan: give a username, e-mail, phone, wallet or domain (veiled-eye scan -h)",
            file=sys.stderr,
        )
        return 2
    from factories import pivots

    for t in targets:
        pivots.mark_root(t)

    if args.modules:
        chosen = [m.strip() for m in args.modules.split(",") if m.strip()]
        unknown = [m for m in chosen if m not in MODULE_REGISTRY]
        if unknown:
            print(
                f"Unknown module(s): {', '.join(unknown)} — see `veiled-eye modules`",
                file=sys.stderr,
            )
            return 2
        allowed = (
            set(chosen)
            if args.no_chain
            else set(chosen) | KEYLESS | set(EXTENDED_MODULES)
        )
        queue = [(m, t) for t in targets for m in chosen if m != "crossref"]
    else:
        allowed = KEYLESS | set(EXTENDED_MODULES)
        queue = []
        for t in targets:
            queue += [(m, t) for m in START[selector_type(t)]]

    seen: set[tuple[str, str]] = set()
    results: dict[str, dict[str, list]] = {}
    _say(
        con,
        f"[bold]Veiled Eye[/] scanning {', '.join(targets)} "
        f"({'chain off' if args.no_chain else 'auto-chain on'})\n",
    )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        running = {}

        def submit(module, param):
            if (module, param) in seen:
                return
            seen.add((module, param))
            running[pool.submit(_run_module, module, param)] = (module, param)

        for m, p in queue:
            submit(m, p)
        while running:
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in done:
                module, param = running.pop(fut)
                result = fut.result()
                results.setdefault(module, {})[param] = result
                status, detail = _status(result)
                color = {"OK": "green", "Warning": "yellow"}.get(status, "red")
                _say(
                    con,
                    f"  [{color}]{status:<7}[/] {module:<13} {param:<28} [dim]{detail}[/]",
                )
                for m, p in _follow(result, allowed, not args.no_chain):
                    submit(m, p)

    if not args.no_crossref:
        for t in targets:
            results.setdefault("crossref", {})[t] = _run_module("crossref", t)
        _print_crossref(con, results.get("crossref", {}))

    if args.output:
        Path(args.output).write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str)
        )
        _say(con, f"\n[bold]Full JSON report:[/] {args.output}")
    if args.export:
        for path in _export(results, targets, args.export, Path(args.outdir)):
            _say(con, f"[bold]Export:[/] {path}")
    return 0


def _export(
    results: dict, targets: list[str], formats: str, outdir: Path
) -> list[Path]:
    from factories import exporter
    from modules.crossref.crossref_tasks import is_error, section

    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    bad = [f for f in wanted if f not in exporter.FORMATS]
    if bad:
        raise SystemExit(
            f"unknown export format(s): {', '.join(bad)} — use {', '.join(exporter.FORMATS)}"
        )
    collected = {
        (m, p): r
        for m, params in results.items()
        if m != "crossref"
        for p, r in params.items()
    }
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for t in targets:
        cref = results.get("crossref", {}).get(t)
        report = (
            section(cref, "raw") if cref is not None and not is_error(cref) else None
        )
        case = exporter.build_case(t, collected, report)
        safe = "".join(c if c.isalnum() or c in "._-@" else "_" for c in t)[:80]
        for fmt in wanted:
            path = outdir / f"veiled-eye-{safe}.{exporter.FORMATS[fmt][1]}"
            path.write_bytes(exporter.render(case, fmt))
            written.append(path)
    return written


def _print_crossref(con, crossrefs: dict) -> None:
    from modules.crossref.crossref_tasks import is_error, section

    for target, result in crossrefs.items():
        if is_error(result):
            continue
        rep = section(result, "raw")
        _say(con, f"\n[bold magenta]== CROSS ANALYSIS: {target} ==[/]")
        if not rep["sources_ok"]:
            _say(con, "[yellow]No successful module output to correlate.[/]")
            continue
        _say(con, f"[dim]sources: {', '.join(rep['sources_ok'])}[/]")
        try:
            from rich.table import Table

            table = Table(show_header=True, header_style="bold")
            for col in ("confidence", "platform", "handle", "sources", "url"):
                table.add_column(col)
            for acc in rep["accounts"]:
                if acc["confidence"] == "candidate" and not acc["underground"]:
                    continue
                color = {"confirmed": "green", "likely": "cyan"}.get(
                    acc["confidence"], "white"
                )
                flag = " [red](underground)[/]" if acc["underground"] else ""
                table.add_row(
                    f"[{color}]{acc['confidence']}[/] ({acc['score']})",
                    acc["platform"] + flag,
                    acc["handle"],
                    ", ".join(acc["sources"]),
                    (acc["urls"] or [""])[0],
                )
            if table.row_count:
                con.print(table) if con else None
            else:
                _say(con, "[dim]No account confirmed by more than one source.[/]")
        except Exception:
            for acc in rep["accounts"]:
                print(acc["confidence"], acc["platform"], acc["handle"], acc["sources"])
        candidates = sum(1 for a in rep["accounts"] if a["confidence"] == "candidate")
        if candidates:
            _say(
                con,
                f"[dim]+ {candidates} single-source candidate accounts (see JSON)[/]",
            )
        for key in ("name", "email", "phone", "location", "organization", "wallet"):
            rows = rep["identity"].get(key) or []
            if rows:
                top = ", ".join(f"{r['value']} ({r['score']})" for r in rows[:4])
                _say(con, f"[bold]{key:<12}[/] {top}")
        for match in rep.get("avatar_matches", []):
            pairs = " = ".join(f"{p}/{h}" for p, h in match["accounts"])
            _say(
                con,
                f"[bold cyan]same avatar[/]  {pairs} [dim](distance {match['distance']}/64)[/]",
            )
        for row in rep["exposure"]:
            _say(
                con,
                f"[bold red]exposure[/]     {row['source']}: {', '.join(row['selectors'])}",
            )
        for emp in rep["org_matches"]:
            _say(
                con,
                f"[bold yellow]org match[/]    {emp.get('title')} — {emp.get('subtitle')} {emp.get('url')}",
            )


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------
def _port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _gateway(frontend_dir: Path):
    """One ASGI app: SPA at ``/`` + the API at ``/api`` (like nginx.conf)."""
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, PlainTextResponse
    from main import create_app

    gw = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    gw.mount("/api", create_app())

    @gw.get("/health")
    def health():
        return PlainTextResponse("ok\n")

    root = frontend_dir.resolve()

    @gw.get("/{path:path}")
    async def spa(path: str):  # async: never queued behind API threads
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            return FileResponse(target)
        return FileResponse(root / "index.html")

    return gw


def cmd_serve(args) -> int:
    _prepare_env("redis")
    broker = os.environ.setdefault(
        "CELERY_BROKER_URL", f"redis://127.0.0.1:{args.redis_port}/0"
    )
    os.environ.setdefault("CELERY_RESULT_BACKEND", broker)
    procs: list[subprocess.Popen] = []

    def stop(*_):
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    from urllib.parse import urlparse

    u = urlparse(broker)
    rhost, rport = u.hostname or "127.0.0.1", u.port or 6379
    if not _port_open(rhost, rport):
        if shutil.which("redis-server") and rhost in ("127.0.0.1", "localhost"):
            print(f">>> starting redis-server on :{rport}")
            procs.append(
                subprocess.Popen(
                    [
                        "redis-server",
                        "--port",
                        str(rport),
                        "--save",
                        "",
                        "--appendonly",
                        "no",
                    ],
                    stdout=subprocess.DEVNULL,
                )
            )
            for _ in range(20):
                if _port_open(rhost, rport):
                    break
                time.sleep(0.25)
        else:
            print(
                f"!!! Redis not reachable at {rhost}:{rport}.\n"
                "    Install redis-server, or run:  docker run -d -p 6379:6379 redis:7-alpine\n"
                "    (`veiled-eye scan` works without Redis.)",
                file=sys.stderr,
            )
            return 1

    if not args.no_worker:
        env = dict(os.environ, PYTHONPATH=str(PKG_DIR))
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "celery_worker.celery",
                    "worker",
                    "--loglevel=INFO",
                    f"--concurrency={args.concurrency}",
                    "-O",
                    "fair",
                    "--prefetch-multiplier=1",
                ],
                cwd=str(PKG_DIR),
                env=env,
            )
        )

    frontend = (
        Path(args.frontend_dir) if args.frontend_dir else PKG_DIR / "frontend_dist"
    )
    if not (frontend / "index.html").is_file():
        print(f"!!! web UI not found in {frontend}", file=sys.stderr)
        stop()

    import uvicorn

    print(
        f"\n>>> Veiled Eye UI: http://{args.host}:{args.port}\n>>> Veiled Eye API: http://{args.host}:{args.port}/api\n"
    )
    try:
        uvicorn.run(
            _gateway(frontend), host=args.host, port=args.port, log_level="info"
        )
    finally:
        stop()
    return 0


# ---------------------------------------------------------------------------
# modules / doctor
# ---------------------------------------------------------------------------
def cmd_modules(_args) -> int:
    from factories.chain import EXTENDED_MODULES
    from module_registry import MODULE_REGISTRY

    for name in sorted(MODULE_REGISTRY):
        tags = []
        if name in EXTENDED_MODULES:
            tags.append("extended")
        if name in KEYLESS:
            tags.append("no-key")
        print(f"{name:<16} {' '.join(tags)}")
    return 0


def cmd_proxies(args) -> int:
    """Check every proxy in proxy_list: exit IP and latency."""
    _prepare_env("memory")
    import requests
    from factories import proxies

    proxies.reset_cache()
    pool, hosts = proxies._load()
    if not pool:
        print("No proxies configured. Add them on the API keys page (proxy_list).")
        return 0
    print(
        f"{len(pool)} proxies"
        + (f", only for: {', '.join(hosts)}" if hosts else ", used for every site")
    )
    bad = 0
    for proxy in pool:
        t0 = time.monotonic()
        try:
            r = requests.get(
                "https://api.ipify.org?format=json",
                proxies=proxies.as_requests(proxy),
                timeout=(8, 12),
            )
            ip = r.json().get("ip", "?")
            print(
                f"  ok    {proxy}  exit {ip}  {int((time.monotonic() - t0) * 1000)} ms"
            )
        except Exception as exc:
            bad += 1
            print(f"  FAIL  {proxy}  {type(exc).__name__}")
    return 1 if bad == len(pool) else 0


def cmd_doctor(_args) -> int:
    _prepare_env("memory")
    ok = True

    def check(label, good, hint=""):
        nonlocal ok
        ok &= bool(good) or not hint.startswith("required")
        mark = "OK " if good else "-- "
        print(f"[{mark}] {label}" + ("" if good else f"   ({hint})"))

    check(
        f"python {sys.version.split()[0]}",
        sys.version_info >= (3, 10),
        "required: >= 3.10",
    )
    check(
        "git (GitSniff repo cloning)",
        shutil.which("git"),
        "optional: events-only scan without it",
    )
    check(
        "redis-server (veiled-eye serve)",
        shutil.which("redis-server"),
        "optional: or use docker redis",
    )
    check(
        "tor socks proxy :9050 (darkweb module)",
        _port_open("127.0.0.1", 9050),
        "optional",
    )
    for mod in (
        "maigret",
        "user_scanner",
        "gitsniff",
        "crosslinked",
        "holehe",
        "celery",
        "fastapi",
    ):
        try:
            importlib.import_module(mod)
            check(f"python package {mod}", True)
        except Exception as exc:
            check(f"python package {mod}", False, f"required: {exc}")
    print(f"\nVEILED_HOME = {VEILED_HOME}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="veiled-eye",
        description="Veiled Eye — identity investigation (OSINT). Every shadow has a story.",
    )
    from veiled_meta import VERSION

    p.add_argument("--version", action="version", version=f"veiled-eye {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="investigate a username / e-mail from the terminal")
    s.add_argument(
        "target",
        nargs="*",
        help="username, e-mail, +phone, crypto wallet or domain (type is auto-detected)",
    )
    s.add_argument("-e", "--email")
    s.add_argument("-u", "--username")
    s.add_argument("-m", "--modules", help="comma list of modules to start with")
    s.add_argument("--no-chain", action="store_true", help="do not follow pivots")
    s.add_argument("--no-crossref", action="store_true", help="skip the cross analysis")
    s.add_argument("-w", "--workers", type=int, default=8)
    s.add_argument(
        "-x",
        "--export",
        help="comma list: html,pdf,stix,graphml,csv,json (written to --outdir)",
    )
    s.add_argument("--outdir", default=".", help="directory for --export files")
    s.add_argument("-o", "--output", help="write the full JSON report here")
    s.add_argument(
        "-v", "--verbose", action="store_true", help="show module tracebacks / logs"
    )
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("serve", help="run API + worker + web UI")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=4300)
    v.add_argument("--redis-port", type=int, default=6379)
    v.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("VEILED_WORKERS", max(12, os.cpu_count() or 4))),
    )
    v.add_argument(
        "--no-worker", action="store_true", help="API/UI only (worker runs elsewhere)"
    )
    v.add_argument("--frontend-dir", help="serve the web UI from this folder instead")
    v.set_defaults(func=cmd_serve)

    sub.add_parser("modules", help="list modules").set_defaults(func=cmd_modules)
    sub.add_parser(
        "proxies", help="check the proxy_list (exit IP, latency)"
    ).set_defaults(func=cmd_proxies)
    sub.add_parser("doctor", help="check optional dependencies").set_defaults(
        func=cmd_doctor
    )
    return p


def main(argv: list[str] | None = None) -> int:
    import warnings

    # third-party tools ship regex strings with invalid escapes
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
