"""GitHub deep investigation: commit e-mails, previous logins, TZ, keys."""

import base64
import hashlib
from unittest.mock import MagicMock

from modules.github import deep

KEY = "ssh-ed25519 " + base64.b64encode(b"key-blob-123").decode()


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = text
    return r


def make_session(routes):
    s = MagicMock()

    def get(url, **kw):
        for frag, resp in routes:
            if frag in url:
                return resp
        return _resp(404, None)

    s.get.side_effect = get
    return s


def test_investigate_end_to_end():
    commits = [
        {
            "sha": "abc",
            "author": {"login": "tailmon"},
            "committer": {"login": "web-flow"},
            "commit": {
                "author": {
                    "email": "Tail@Mon.dev",
                    "name": "Tail Mon",
                    "date": "2023-01-02T10:00:00Z",
                },
                "committer": {
                    "email": "noreply@github.com",
                    "name": "GitHub",
                    "date": "2023-01-02T10:00:00Z",
                },
            },
        },
        {
            "sha": "def",
            "author": {"login": "tailmon"},
            "committer": None,
            "commit": {
                "author": {
                    "email": "42+oldname@users.noreply.github.com",
                    "name": "Tail",
                    "date": "2019-05-01T10:00:00Z",
                },
                "committer": {},
            },
        },
    ]
    events = [
        {
            "type": "PushEvent",
            "repo": {"name": "other/proj"},
            "created_at": "2024-03-01T00:00:00Z",
            "payload": {
                "commits": [{"author": {"email": "work@acme.com", "name": "T. Mon"}}]
            },
        }
    ]
    routes = [
        (
            "/gpg_keys",
            _resp(
                200,
                [
                    {
                        "emails": [{"email": "gpg@tailmon.dev"}],
                        "created_at": "2022-01-01",
                    }
                ],
            ),
        ),
        ("/repos/tailmon/tool/commits", _resp(200, commits)),
        ("/events/public", _resp(200, events)),
        (
            ".patch",
            _resp(200, None, "From abc\nDate: Mon, 2 Jan 2023 13:00:00 +0300\n"),
        ),
        (
            "raw.githubusercontent.com",
            _resp(
                200,
                None,
                "Hi! https://tailmon.dev mail me: me@tailmon.dev ![](https://img.shields.io/x)",
            ),
        ),
        ("gitlab.com/tailmon.keys", _resp(200, None, KEY + "\n")),
    ]
    session = make_session(routes)
    user = {"login": "tailmon", "id": 42, "name": "Tail Mon", "email": None}
    repos = [
        {"name": "tool", "full_name": "tailmon/tool", "fork": False},
        {"name": "f", "fork": True},
    ]
    out = deep.investigate(session, user, repos, [{"key": KEY}])

    emails = {e["email"]: e for e in out["emails"]}
    assert {
        "tail@mon.dev",
        "work@acme.com",
        "gpg@tailmon.dev",
        "me@tailmon.dev",
    } <= set(emails)
    assert "noreply@github.com" not in emails  # web-flow committer is not the user
    assert out["previous_logins"][0]["login"] == "oldname"
    assert out["timezones"] == {"UTC+03:00": 2}
    assert out["ssh_matches"][0]["forge"] == "GitLab"
    assert out["readme_urls"] == ["https://tailmon.dev"]
    assert "Tail Mon" in out["commit_names"]


def test_noreply_with_other_id_is_not_a_previous_login():
    e = deep.Emails()
    e.add("99+someoneelse@users.noreply.github.com")
    assert deep.previous_logins(42, "tailmon", e) == []


def test_ssh_fingerprint_format():
    fp = deep.ssh_fingerprint(KEY)
    expected = (
        base64.b64encode(hashlib.sha256(b"key-blob-123").digest()).decode().rstrip("=")
    )
    assert fp == "SHA256:" + expected


def test_gharchive_is_skipped_without_project(monkeypatch):
    monkeypatch.delenv("VEILED_GHARCHIVE_PROJECT", raising=False)
    assert deep.gharchive_logins(42) == []
