#!/usr/bin/env python
"""User-Scanner module — username / email registration sweep + cross-scan.

Wraps kaifcodec/user-scanner (MIT).  A username runs the username sweep, an
email runs the email-registration sweep.  Then user-scanner's own
*cross-scan* follows the handles and links found in profile metadata and
rates every hit (confirmed / likely / candidate / conflicting) — that rating
is kept on every node so ``crossref`` can weigh it.

"Loud" checks (ones that notify the target, e.g. password-reset flows) are
NEVER run.

Tunables (env):
  VEILED_USERSCANNER_TIMEOUT  per-request timeout (default 10)
  VEILED_USERSCANNER_CROSS    "0" disables the cross-scan pass (default on)
  VEILED_USERSCANNER_SWEEP    full sweeps the cross-scan may spend (default 1)
  VEILED_USERSCANNER_CROSS_DEPTH   hops the cross-scan follows (default 2)
  VEILED_USERSCANNER_CROSS_LINKS   verified (default) or all
  VEILED_USERSCANNER_NSFW     "1" includes adult / dating categories (default off)
"""

from __future__ import annotations

import argparse
import json
import os

from celery.utils.log import get_task_logger
from factories.output_builder import build_total, root_node, site_icon
from factories.quiet import silenced
from factories.task_wrapper import module_task

logger = get_task_logger(__name__)

LINK = "UserScanner"


class _NullProgress:
    """Drop-in for ``rich.progress.Progress`` that renders nothing."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_task(self, *args, **kwargs):
        return 0

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _scan(target: str, is_email: bool) -> tuple[list, list]:
    """Return (first_pass, cross_pass) user-scanner Result objects."""
    # rich's live progress bar renders from its own refresh thread, which a
    # per-thread silence cannot catch — swap it for a no-op.
    import user_scanner.core.email_orchestrator as _eo
    import user_scanner.core.orchestrator as _uo
    from user_scanner.core.cross_scan import CrossScanConfig, run_cross_scan
    from user_scanner.core.email_orchestrator import run_email_full_batch
    from user_scanner.core.helpers import ScanConfig, set_global_timeout
    from user_scanner.core.orchestrator import run_user_full

    _uo.Progress = _NullProgress
    _eo.Progress = _NullProgress

    timeout = float(os.environ.get("VEILED_USERSCANNER_TIMEOUT", "10"))
    set_global_timeout(timeout)
    cfg = ScanConfig(
        allow_loud=False,
        no_nsfw=os.environ.get("VEILED_USERSCANNER_NSFW", "0") != "1",
        show_all=False,
        verbose=False,
        timeout=timeout,
    )

    # user-scanner prints a rich progress UI — keep worker logs clean.
    with silenced():
        first = (
            run_email_full_batch(target, cfg)
            if is_email
            else run_user_full(target, cfg)
        )
        cross: list = []
        if os.environ.get("VEILED_USERSCANNER_CROSS", "1") != "0":
            try:
                cross = run_cross_scan(
                    first,
                    cfg,
                    CrossScanConfig(
                        # --cross-links verified: only links the platform itself
                        # verified (fewer false positives than "all")
                        links=os.environ.get(
                            "VEILED_USERSCANNER_CROSS_LINKS", "verified"
                        ),
                        emails="none",  # never mail-scan third-party addresses
                        sweep=int(os.environ.get("VEILED_USERSCANNER_SWEEP", "1")),
                        # --cross-depth 2: follow links two hops deep
                        depth=int(
                            os.environ.get("VEILED_USERSCANNER_CROSS_DEPTH", "2")
                        ),
                    ),
                )
            except Exception as exc:  # cross-scan is a bonus, never fatal
                logger.warning(f"user-scanner cross-scan failed: {exc}")
    return first, cross


def _as_dict(result) -> dict:
    data = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    data["found"] = (
        bool(result.is_found())
        if hasattr(result, "is_found")
        else (data.get("status") in ("Found", "Registered"))
    )
    return data


@module_task(module_name="userscanner", dev_mode_sleep=8)
def p_userscanner(param):
    """Task of Celery that sweeps a username or email with user-scanner."""
    is_email = "@" in param
    first, cross = _scan(param, is_email)

    first_hits = [_as_dict(r) for r in first]
    cross_hits = [_as_dict(r) for r in cross]
    found = [r for r in first_hits if r["found"]]
    # false-positive control: a cross-scan hit whose metadata contradicts the
    # confirmed profiles is dropped; "candidate" hits stay but are marked
    cross_found = [
        r
        for r in cross_hits
        if r["found"] and str((r.get("extra") or {}).get("confidence")) != "conflicting"
    ]
    if not found and not cross_found:
        raise Exception("warn: No registrations found by user-scanner")

    kind = "Email registrations" if is_email else "Username accounts"
    gather = [root_node(LINK, param, "fas fa-user-check", kind)]
    lists, social, profile, timeline = [], [], [], []
    categories: dict[str, int] = {}
    confidence: dict[str, int] = {}

    def add_hit(hit: dict, pass_name: str) -> None:
        site = str(hit.get("site_name") or "unknown")
        cat = str(hit.get("category") or "other")
        extra = hit.get("extra") or {}
        media = hit.get("media") or {}
        conf = str(
            extra.get("confidence")
            or ("confirmed" if pass_name == "first" else "candidate")
        )
        handle = str(hit.get("username") or param)
        url = hit.get("url") or ""
        icon = site_icon(site)

        categories[cat] = categories.get(cat, 0) + 1
        confidence[conf] = confidence.get(conf, 0) + 1

        gather.append(
            {
                "name-node": f"US-{pass_name}-{site}-{handle}",
                "title": site,
                "subtitle": f"{handle} · {cat} · {conf}",
                "icon": icon,
                "link": LINK,
                "help": url or (extra.get("pivot_source") or ""),
                "confidence": conf,
                "pass": pass_name,
            }
        )
        lists.append(
            {
                "title": site,
                "subtitle": handle,
                "category": cat,
                "url": url,
                "confidence": conf,
                "pass": pass_name,
                "pivot_source": extra.get("pivot_source", ""),
                "extra": extra,
            }
        )
        weak = pass_name == "cross" and conf == "candidate"
        if (url or not hit.get("is_email")) and not weak:
            social.append(
                {
                    "name": site,
                    "url": url,
                    "icon": icon,
                    "source": "userscanner",
                    "username": handle,
                    "category": cat,
                }
            )
        # metadata harvested by the scanner modules
        for key in ("name", "full_name", "display_name"):
            if extra.get(key):
                profile.append({"name": str(extra[key])})
        for key in ("bio", "about", "description"):
            if extra.get(key):
                profile.append({"bio": str(extra[key])})
        if extra.get("location"):
            profile.append({"location": str(extra["location"])})
        for key in ("avatar", "profile_pic", "image", "photo"):
            pic = media.get(key) or extra.get(key)
            if pic and str(pic).startswith("http"):
                profile.append({"photos": [{"picture": str(pic), "title": site}]})
                break
        for key in ("created_at", "joined", "created", "registered"):
            if extra.get(key):
                timeline.append(
                    {
                        "date": str(extra[key]),
                        "action": f"UserScanner : account on {site}",
                        "icon": icon,
                    }
                )
                break

    for hit in found:
        add_hit(hit, "first")
    for hit in cross_found:
        add_hit(hit, "cross")

    # handles the cross-scan tied to the target lead to deeper sweeps
    tasks: list[dict] = []
    seen_handles = {param.lower()}
    for hit in cross_found:
        conf = str((hit.get("extra") or {}).get("confidence") or "")
        handle = str(hit.get("username") or "").strip()
        if (
            conf in ("confirmed", "likely")
            and handle
            and handle.lower() not in seen_handles
        ):
            seen_handles.add(handle.lower())
            tasks.append({"module": "maigret", "param": handle})

    profile.insert(0, {"social": social})
    if is_email:
        profile.append({"email": param})
    else:
        profile.append({"username": param})
    profile.append(
        {
            "presence": [
                {
                    "name": "userscanner",
                    "children": [
                        {"name": c, "value": n} for c, n in sorted(categories.items())
                    ],
                }
            ]
        }
    )

    graphic = [
        {"userscanner": gather},
        {"lists": lists},
        {"categories": categories},
        {"confidence": confidence},
    ]

    return build_total(
        module="userscanner",
        param=param,
        validation="hard" if is_email else "soft",
        raw={
            "target": param,
            "is_email": is_email,
            "checked": len(first_hits),
            "found": found,
            "cross": cross_found,
        },
        graphic=graphic,
        profile=profile,
        timeline=timeline,
        tasks=tasks[:5],
    )


t_userscanner = p_userscanner


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="user-scanner sweep (Veiled Eye module)"
    )
    parser.add_argument("target", help="username or email")
    print(
        json.dumps(t_userscanner(parser.parse_args().target, dev_mode=False), indent=2)
    )
