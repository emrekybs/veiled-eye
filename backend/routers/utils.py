"""Utility routes: task state/result polling, tasklist, apikey, testing."""

import asyncio
import logging
import os

from celery_app import celery
from factories import categories, chain
from factories.configuration import api_keys_read, api_keys_write
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from module_registry import MODULE_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter()

_DEBUG = os.environ.get("FASTAPI_DEBUG", "").lower() in ("1", "true", "yes")
# maigret / gitsniff sweeps can outlive the old hard-coded 120s
_RESULT_TIMEOUT = float(os.environ.get("VEILED_RESULT_TIMEOUT", "600"))
# How long one GET /result long-polls (default 5s) before answering 504. The web UI then
# switches to cheap /state polling, so a 20-40 module scan never pins all
# six browser connections (which used to stall page loads / navigation).
_RESULT_WAIT = float(os.environ.get("VEILED_RESULT_WAIT", "5"))


@router.get("/tasklist")
def r_tasklist():
    """Return list of available module routes."""
    # Build the list from the registry + variant routes so it stays in
    # sync automatically.  The old Flask version iterated url_map; here
    # we replicate the same list the frontend expects.
    modules = [
        *sorted(MODULE_REGISTRY.keys()),
        "spotify",
        "tweetiment",
        "dorks",
        "twitter_info",
        "twitter_infos",
        "twitter_comp",
        "twitter_comps",
    ]
    # Deduplicate while preserving order (registry already has some of these)
    seen: set[str] = set()
    unique: list[str] = []
    for m in modules:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    # Add utility routes that Flask's url_map also exposed
    for extra in ("tasklist", "state", "result", "apikey", "testing"):
        if extra not in seen:
            seen.add(extra)
            unique.append(extra)
    return {"modules": unique}


@router.get("/about")
def r_about():
    """Version, modules (with their one-line description) and credits."""
    import ast
    from pathlib import Path

    from veiled_meta import VERSION

    base = Path(__file__).resolve().parents[1]
    mods = []
    for name, (path, _) in sorted(MODULE_REGISTRY.items()):
        file = base / Path(*path.split(".")[:-1]).with_suffix(".py")
        summary = ""
        try:
            doc = ast.get_docstring(ast.parse(file.read_text(encoding="utf-8"))) or ""
            summary = next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")
        except (OSError, SyntaxError, ValueError):
            pass
        mods.append({"name": name, "summary": summary[:160]})
    return {"name": "Veiled Eye", "version": VERSION, "modules": mods}


@router.get("/state/{task_id}/{task_app}")
def r_state(task_id: str, task_app: str):
    """Poll the state of a dispatched Celery task."""
    res = celery.AsyncResult(task_id).state
    return {"state": res, "task_id": task_id, "task_app": task_app}


@router.get("/result/{task_id}")
async def r_result(task_id: str, wait: float | None = None):
    """Retrieve the result of a completed Celery task.

    Waits on the event loop (cheap polling) instead of parking a worker
    thread in ``AsyncResult.get()``: one search fans out to 20-40 modules,
    and blocking calls used to exhaust the threadpool so the UI's static
    files and API stalled. ``?wait=`` (seconds, capped by
    ``VEILED_RESULT_TIMEOUT``) overrides the default ``VEILED_RESULT_WAIT``.
    """
    ares = celery.AsyncResult(task_id)
    loop = asyncio.get_running_loop()
    budget = _RESULT_WAIT if wait is None else wait
    deadline = loop.time() + max(0.0, min(budget, _RESULT_TIMEOUT))
    delay = 0.1
    try:
        while not await run_in_threadpool(ares.ready):
            if loop.time() >= deadline:
                raise TimeoutError(task_id)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 1.5)
        res = await run_in_threadpool(ares.get, timeout=5)
    except Exception as exc:
        raise HTTPException(status_code=504, detail="Task timed out or failed") from exc
    # Extended modules are triggered through the result's ``tasks`` element
    # (see factories/chain.py) — existing module outputs are left untouched.
    out = await run_in_threadpool(lambda: chain.inject(categories.decorate(res)))
    return {"result": out}


@router.post("/apikey")
async def r_apikey(request: Request):
    """Read or write API keys.

    - Empty body or non-list body (e.g. ``{}``) → read current keys.
    - Array body → validate and write keys.
    """
    body = await request.body()
    if body:
        api_keys = await request.json()
        # If the body is a list, treat it as a write operation
        if isinstance(api_keys, list):
            if not all(
                isinstance(k, dict) and set(k.keys()) <= {"id", "name", "key"}
                for k in api_keys
            ):
                raise HTTPException(status_code=400, detail="Invalid API key format")
            keys = api_keys_write(api_keys)
            return {"keys": keys}
    # Any non-list body (empty, {}, null) → read
    keys = api_keys_read()
    return {"keys": keys}


@router.get("/export/{target}")
def r_export(target: str, format: str = "html"):  # noqa: A002 - query name
    """Export everything collected for *target* (html/pdf/stix/graphml/csv/json).

    Built from the cross-module result cache, so it reflects every module that
    ran for the target (and its pivots) during the cache TTL.
    """
    from factories import exporter
    from modules.crossref.crossref_tasks import collect

    fmt = format.lower()
    if fmt not in exporter.FORMATS:
        raise HTTPException(
            status_code=400, detail=f"format must be one of {sorted(exporter.FORMATS)}"
        )
    collected = collect(target, 0)
    if not collected:
        raise HTTPException(
            status_code=404, detail="Nothing collected for this target yet"
        )
    body = exporter.render(exporter.build_case(target, collected), fmt)
    mime, ext = exporter.FORMATS[fmt]
    safe = "".join(c if c.isalnum() or c in "._-@" else "_" for c in target)[:80]
    disposition = "inline" if fmt == "html" else "attachment"
    return Response(
        content=body,
        media_type=mime,
        headers={
            "Content-Disposition": f'{disposition}; filename="veiled-eye-{safe}.{ext}"'
        },
    )


@router.post("/testing")
async def r_testing(request: Request):
    """Echo JSON body back — only available in debug mode."""
    if not _DEBUG:
        raise HTTPException(status_code=404, detail="Not Found")
    result = await request.json()
    logger.debug("Testing endpoint received: %s", result)
    return result
