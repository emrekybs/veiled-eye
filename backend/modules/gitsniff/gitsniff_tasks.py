#!/usr/bin/env python
"""GitSniff module — commit e-mail mining for a GitHub user / org.

Wraps Reginald-Gillespie/GitSniff (MIT).  GitSniff bare-clones the target's
public repositories and reads ``git log`` (plus the public events API) to
collect every author / committer e-mail and name — usually far more than the
single address the GitHub profile exposes.

No token needed.  ``GITHUB_TOKEN`` (env, optional) only raises the API rate
limit.  Requires the ``git`` binary.

Tunables (env):
  VEILED_GITSNIFF_MAX_REPOS    repositories to clone (default 15)
  VEILED_GITSNIFF_MAX_COMMITS  commits per repository (default 300)
  VEILED_GITSNIFF_MAX_EVENTS   public events to read (default 300)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import defaultdict

from celery.utils.log import get_task_logger
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task
from factories.tokens import github_token

logger = get_task_logger(__name__)

LINK = "GitSniff"


def _local_part(param: str) -> str:
    return param.split("@")[0] if "@" in param else param


def _make_scanner():
    """Build a GitSniff scanner that is safe inside Celery / threads."""
    import importlib

    from rich.console import Console

    # ``gitsniff/__init__`` re-exports a ``main`` function that shadows the
    # submodule, so ``import gitsniff.main as gs`` would bind the function.
    gs = importlib.import_module("gitsniff.main")

    gs.console = Console(quiet=True)  # silence rich progress output
    original_signal = gs.signal.signal
    gs.signal.signal = lambda *a, **k: None  # __init__ installs a SIGINT handler
    try:
        scanner = gs.GitHubScanner(token=github_token() or None)
    finally:
        gs.signal.signal = original_signal
    # upstream sets {"https": ""}, which breaks requests behind a proxy pool
    scanner.proxies = None
    return scanner


def _scan(username: str) -> list[dict]:
    scanner = _make_scanner()
    try:
        return _run(scanner, username)
    except SystemExit:
        raise Exception(
            "warn: GitHub API rate limit reached. Add a free GitHub token "
            "(github_token on the API keys page) for 5000 requests per hour."
        ) from None


def _run(scanner, username: str) -> list[dict]:
    return (
        scanner.scan_user_or_org(
            username,
            include_forks=False,
            max_commits=int(os.environ.get("VEILED_GITSNIFF_MAX_COMMITS", "300")),
            max_repos=int(os.environ.get("VEILED_GITSNIFF_MAX_REPOS", "15")),
            scan_repos=shutil.which("git") is not None,
            scan_events=True,
            max_events=int(os.environ.get("VEILED_GITSNIFF_MAX_EVENTS", "300")),
        )
        or []
    )


def _organize(entries: list[dict]) -> dict[str, dict]:
    org: dict[str, dict] = defaultdict(
        lambda: {"names": set(), "repos": defaultdict(set)}
    )
    for e in entries:
        email = (e.get("email") or "").lower().strip()
        if not email:
            continue
        if e.get("name"):
            org[email]["names"].add(e["name"])
        org[email]["repos"][e.get("repo", "")].add(e.get("commit_sha", ""))
    return org


@module_task(module_name="gitsniff", dev_mode_sleep=8)
def p_gitsniff(param):
    """Task of Celery that mines commit e-mails of a GitHub account."""
    username = _local_part(param)
    entries = _scan(username)
    organized = _organize(entries)
    if not organized:
        raise Exception("warn: No commit e-mails found (or GitHub user not found)")

    gather = [root_node(LINK, username, "fab fa-git-alt", f"{len(organized)} e-mails")]
    lists, profile = [], []
    names_seen: set[str] = set()
    raw = []

    # Rank: addresses that appear in more commits first
    ranked = sorted(
        organized.items(),
        key=lambda kv: -sum(len(c) for c in kv[1]["repos"].values()),
    )
    for idx, (email, info) in enumerate(ranked):
        commits = sum(len(c) for c in info["repos"].values())
        repos = sorted(r for r in info["repos"] if r)
        names = sorted(info["names"])
        gather.append(
            {
                "name-node": f"GS-{idx}",
                "title": email,
                "subtitle": ", ".join(names[:2]) or f"{commits} commits",
                "icon": "fas fa-at",
                "link": LINK,
                "help": f"{commits} commits in {len(repos)} repos",
            }
        )
        lists.append(
            {
                "title": email,
                "subtitle": ", ".join(names),
                "commits": commits,
                "repos": repos,
            }
        )
        profile.append({"email": email})
        for name in names:
            if name.lower() not in names_seen:
                names_seen.add(name.lower())
                profile.append({"name": name})
        raw.append({"email": email, "names": names, "commits": commits, "repos": repos})

    profile.append({"username": username})
    profile.append(
        {
            "presence": [
                {
                    "name": "gitsniff",
                    "children": [
                        {"name": "emails", "value": len(organized)},
                        {"name": "names", "value": len(names_seen)},
                    ],
                }
            ]
        }
    )

    graphic = [{"gitsniff": gather}, {"lists": lists}]

    return build_total(
        module="gitsniff",
        param=param,
        validation="hard",
        raw={"username": username, "emails": raw},
        graphic=graphic,
        profile=profile,
        timeline=[],
    )


t_gitsniff = p_gitsniff


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GitSniff commit e-mail mining (Veiled Eye module)"
    )
    parser.add_argument("username")
    print(
        json.dumps(t_gitsniff(parser.parse_args().username, dev_mode=False), indent=2)
    )
