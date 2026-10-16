import json
import os
import shutil
from pathlib import Path
from typing import Any

_FACTORIES_DIR = Path(__file__).resolve().parent


def _api_keys_path() -> Path:
    """Return the absolute path to apikeys.json.

    ``VEILED_APIKEYS`` overrides the location (the pip/pipx ``veiled-eye`` CLI points it
    at ``~/.config/veiled-eye/apikeys.json`` so keys survive upgrades).
    """
    override = os.environ.get("VEILED_APIKEYS")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(_FACTORIES_DIR / "apikeys_default.json", path)
        return path
    path = _FACTORIES_DIR / "apikeys.json"
    if not path.is_file():  # first run outside Docker: start from the defaults
        try:
            shutil.copy(_FACTORIES_DIR / "apikeys_default.json", path)
        except OSError:
            return _FACTORIES_DIR / "apikeys_default.json"
    return path


# Fields that no longer exist (dead services, password logins).
_OBSOLETE = {
    "instagram_user",
    "instagram_pass",
    "fullcontact_api",
    "haveibeenpwned_key",
}

# "Paste everything here" boxes: a Cookie-Editor export / cookie string is
# split into the per-cookie fields on save, then the box is emptied.
_COOKIE_BOXES = {
    "instagram_cookies": (
        "instagram_",
        (
            "sessionid",
            "ds_user_id",
            "csrftoken",
            "mid",
            "ig_did",
            "datr",
            "ps_l",
            "ps_n",
            "wd",
        ),
    ),
}


def expand_cookie_boxes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from factories.cookie_utils import parse_cookie_box

    by_name = {i.get("name"): i for i in items}
    for box, (prefix, names) in _COOKIE_BOXES.items():
        entry = by_name.get(box)
        if not entry or not str(entry.get("key") or "").strip():
            continue
        jar = parse_cookie_box(entry["key"])
        if not jar:
            continue
        for name in names:
            field = by_name.get(prefix + name)
            if field is not None and jar.get(name):
                field["key"] = jar[name]
        entry["key"] = ""
    return items


def _with_defaults(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add fields introduced after the user's apikeys.json was created."""
    items = [i for i in items if i.get("name") not in _OBSOLETE]
    try:
        defaults = json.loads((_FACTORIES_DIR / "apikeys_default.json").read_text())
    except (OSError, ValueError):
        return items
    have = {i.get("name") for i in items}
    next_id = max([int(i.get("id") or 0) for i in items] + [0]) + 1
    for d in defaults:
        if d["name"] not in have:
            items.append({"id": next_id, "name": d["name"], "key": ""})
            next_id += 1
    return items


def api_keys_read() -> list[dict[str, Any]]:
    with _api_keys_path().open() as f:
        return _with_defaults(json.load(f))


def api_keys_write(
    api_keys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    api_keys = expand_cookie_boxes(_with_defaults(list(api_keys)))
    with _api_keys_path().open("w") as f:
        json.dump(api_keys, f)
    return api_keys


def api_keys_search(api_name: str) -> str | bool:
    try:
        with _api_keys_path().open() as f:
            items = json.load(f)
    except (OSError, ValueError):
        return False
    for item in items:
        if item["name"] == api_name:
            return item["key"]
    return False
