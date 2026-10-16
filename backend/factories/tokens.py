"""Optional free tokens that lift rate limits (env var wins over API key)."""

from __future__ import annotations

import os


def _key(name: str) -> str:
    try:
        from factories.configuration import api_keys_search

        return str(api_keys_search(name) or "").strip()
    except Exception:
        return ""


def github_token() -> str:
    """GITHUB_TOKEN or the github_token API key: 60 -> 5000 requests/hour."""
    return os.environ.get("GITHUB_TOKEN", "").strip() or _key("github_token")
