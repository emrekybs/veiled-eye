"""Run a vendored SOCMIntelligence collector (``socmint_tools/*.py``).

Every collector is a standalone CLI that prints ONE JSON object on stdout, or
``{"error": kind, "message": ...}`` (kind: not_found | private |
rate_limited | error).  Running them in a subprocess keeps them isolated from
Celery / CLI threads (they use module-level sessions, ``sys.exit`` and
print freely).

Errors are mapped onto the module convention: ``warn: ...`` exceptions become
"Warning" results (nothing found / blocked), anything else becomes "Fail".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from factories import proxies

TOOLS_DIR = Path(__file__).resolve().parent.parent / "socmint_tools"

_SOFT = {"not_found", "private", "rate_limited"}


def _last_json(stdout: str) -> dict | None:
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def run_tool(script: str, args: list[str], timeout: int = 150) -> dict:
    """Run ``socmint_tools/<script>`` and return its JSON object."""
    path = TOOLS_DIR / script
    try:
        proc = subprocess.run(
            [sys.executable, str(path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TOOLS_DIR),
            env=dict(
                os.environ, PYTHONIOENCODING="utf-8", **proxies.env_for_subprocess()
            ),
        )
    except subprocess.TimeoutExpired as exc:
        raise Exception(f"warn: {script} timed out after {timeout}s") from exc

    data = _last_json(proc.stdout)
    if data is None:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise Exception(f"{script} failed: {tail[0][:200]}")
    if isinstance(data, dict) and data.get("error"):
        kind, msg = str(data["error"]), str(data.get("message") or data["error"])
        if kind in _SOFT:
            raise Exception(f"warn: {msg}")
        raise Exception(msg)
    return data


def run_snapchat(username: str, timeout: int = 90) -> dict:
    """snap_osint.py writes its JSON to a file and signals errors by exit code."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "snap.json"
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_DIR / "snap_osint.py"),
                    username,
                    "--no-heatmap",
                    "--save-json",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
                env=dict(
                    os.environ, PYTHONIOENCODING="utf-8", **proxies.env_for_subprocess()
                ),
            )
        except subprocess.TimeoutExpired as exc:
            raise Exception(f"warn: Snapchat timed out after {timeout}s") from exc
        if out.is_file():  # JSON is saved before the terminal report prints
            try:
                return json.loads(out.read_text(encoding="utf-8"))
            except ValueError:
                pass
        if proc.returncode == 2:
            raise Exception(f"warn: Snapchat user @{username} not found")
        if proc.returncode == 3:
            raise Exception("warn: Snapchat rate limited")
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
            msg = tail[0].replace("ERROR: ", "")[:200]
            if "private" in msg.lower() or "no usable data" in msg.lower():
                raise Exception(f"warn: {msg}")
            raise Exception(f"Snapchat: {msg}")
        return json.loads(out.read_text(encoding="utf-8"))
