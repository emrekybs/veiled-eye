"""Deeper GitHub identity work for the github module.

Everything here reads public data:

* **commit e-mails** — author / committer e-mails and names in the user's own
  repositories (commits API) and in recent public push events
* **previous usernames** — GitHub's ``<id>+<login>@users.noreply.github.com``
  addresses carry the account's numeric ID, which never changes; a different
  login next to the same ID is a former username. Optionally GH Archive
  (Google BigQuery, your own project) lists every login the ID ever used.
* **time zone** — the ``Date:`` line of ``.patch`` files keeps the author's
  UTC offset
* **keys** — e-mails inside public GPG keys; SSH key fingerprints, checked
  against the same username on GitLab and Codeberg (same key = same person)
* **profile README** — links and e-mails in ``<user>/<user>/README.md``

``GITHUB_TOKEN`` (optional) raises the API limit from 60 to 5000 calls/hour.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests

API = "https://api.github.com"
NOREPLY_RE = re.compile(
    r"^(?:(\d+)\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$", re.I
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BOT_EMAIL_RE = re.compile(
    r"(noreply@github\.com|\[bot\]|dependabot|github-actions|renovate|"
    r"@localhost|\.local$|example\.(com|org))",
    re.I,
)
TIMEOUT = 20


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def api_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "VeiledEye-OSINT"}
    from factories.tokens import github_token

    token = github_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get_json(session, url: str, **params):
    r = session.get(url, headers=api_headers(), params=params or None, timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


class Emails:
    """e-mail -> sources, names, repos, first/last seen."""

    def __init__(self):
        self.data: dict[str, dict] = {}

    def add(self, email, name="", source="", repo="", date=""):
        email = str(email or "").strip().lower()
        if not email or "@" not in email:
            return
        d = self.data.setdefault(
            email,
            {
                "sources": set(),
                "names": set(),
                "repos": set(),
                "first": "",
                "last": "",
                "count": 0,
            },
        )
        d["count"] += 1
        if source:
            d["sources"].add(source)
        if name:
            d["names"].add(str(name).strip())
        if repo:
            d["repos"].add(repo)
        if date:
            date = str(date)
            d["first"] = min(d["first"] or date, date)
            d["last"] = max(d["last"], date)

    def as_list(self) -> list[dict]:
        out = []
        for email, d in self.data.items():
            out.append(
                {
                    "email": email,
                    "sources": sorted(d["sources"]),
                    "names": sorted(d["names"]),
                    "repos": sorted(d["repos"])[:10],
                    "first": d["first"],
                    "last": d["last"],
                    "count": d["count"],
                    "noreply": bool(NOREPLY_RE.match(email)),
                    "bot": bool(BOT_EMAIL_RE.search(email)),
                }
            )
        return sorted(out, key=lambda e: (e["noreply"] or e["bot"], -e["count"]))


def commit_emails(
    session, login: str, repos: list[dict], emails: Emails
) -> list[tuple[str, str]]:
    """Commits API over the user's own repos; returns (repo, sha) samples."""
    samples = []
    max_repos = _env_int("VEILED_GITHUB_DEEP_REPOS", 15)
    own = [r for r in repos if isinstance(r, dict) and not r.get("fork")][:max_repos]
    for repo in own:
        full = repo.get("full_name") or f"{login}/{repo.get('name')}"
        commits = _get_json(session, f"{API}/repos/{full}/commits", per_page=100) or []
        if not isinstance(commits, list):
            continue
        for c in commits:
            info = c.get("commit") or {}
            author, committer = info.get("author") or {}, info.get("committer") or {}
            mine = (c.get("author") or {}).get("login", "").lower() == login.lower()
            if mine or not c.get("author"):
                emails.add(
                    author.get("email"),
                    author.get("name"),
                    "commits",
                    full,
                    author.get("date", ""),
                )
            if (c.get("committer") or {}).get("login", "").lower() == login.lower():
                emails.add(
                    committer.get("email"),
                    committer.get("name"),
                    "commits",
                    full,
                    committer.get("date", ""),
                )
            if mine and len(samples) < _env_int("VEILED_GITHUB_PATCH_SAMPLES", 12):
                samples.append((full, c.get("sha", "")))
    return samples


def event_emails(session, login: str, emails: Emails) -> None:
    events = (
        _get_json(session, f"{API}/users/{login}/events/public", per_page=100) or []
    )
    for ev in events if isinstance(events, list) else []:
        if ev.get("type") != "PushEvent":
            continue
        repo = (ev.get("repo") or {}).get("name", "")
        for c in (ev.get("payload") or {}).get("commits") or []:
            a = c.get("author") or {}
            emails.add(
                a.get("email"),
                a.get("name"),
                "push events",
                repo,
                ev.get("created_at", ""),
            )


def patch_offsets(session, samples: list[tuple[str, str]]) -> Counter:
    """UTC offsets from the Date: line of .patch files (author's clock)."""
    offsets: Counter = Counter()
    for full, sha in samples:
        if not sha:
            continue
        try:
            r = session.get(
                f"https://github.com/{full}/commit/{sha}.patch", timeout=TIMEOUT
            )
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        m = re.search(r"^Date: (.+)$", r.text or "", re.M)
        if not m:
            continue
        try:
            dt = parsedate_to_datetime(m.group(1).strip())
        except (TypeError, ValueError):
            continue
        if dt.utcoffset() is not None:
            minutes = int(dt.utcoffset().total_seconds() // 60)
            offsets[
                f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
            ] += 1
    return offsets


def previous_logins(user_id: int, login: str, emails: Emails) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in emails.as_list():
        m = NOREPLY_RE.match(item["email"])
        if not m:
            continue
        uid, old = m.group(1), m.group(2)
        if old.lower() == login.lower():
            continue
        if uid and int(uid) == int(user_id):
            seen[old.lower()] = {
                "login": old,
                "evidence": f"noreply address with account ID {uid}",
                "first": item["first"],
                "last": item["last"],
                "confidence": "confirmed",
            }
    return list(seen.values())


def gharchive_logins(user_id: int) -> list[dict]:
    """Every login GH Archive saw for this account ID (optional, BigQuery).

    Needs ``google-cloud-bigquery`` and credentials
    (``GOOGLE_APPLICATION_CREDENTIALS``) plus ``VEILED_GHARCHIVE_PROJECT``.
    A dry run checks the scan size first; queries above
    ``VEILED_GHARCHIVE_MAX_GB`` (default 100) are not run.
    """
    project = os.environ.get("VEILED_GHARCHIVE_PROJECT")
    if not project:
        return []
    try:
        from google.cloud import bigquery
    except ImportError:
        return [{"note": "install google-cloud-bigquery to use GH Archive"}]
    years = os.environ.get("VEILED_GHARCHIVE_YEARS", "2015-2026")
    first, last = [*years.split("-"), years][:2]
    sql = (
        "SELECT actor.login AS login, MIN(created_at) AS first, MAX(created_at) AS last "
        "FROM `githubarchive.year.20*` "
        "WHERE _TABLE_SUFFIX BETWEEN @a AND @b AND actor.id = @id "
        "GROUP BY login ORDER BY first"
    )
    params = [
        bigquery.ScalarQueryParameter("a", "STRING", first[-2:]),
        bigquery.ScalarQueryParameter("b", "STRING", last[-2:]),
        bigquery.ScalarQueryParameter("id", "INT64", int(user_id)),
    ]
    client = bigquery.Client(project=project)
    cap = _env_int("VEILED_GHARCHIVE_MAX_GB", 100) * 1024**3
    dry = client.query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=params, dry_run=True)
    )
    if dry.total_bytes_processed > cap:
        gb = dry.total_bytes_processed / 1024**3
        return [
            {
                "note": f"GH Archive query would scan {gb:.0f} GB (cap {cap / 1024**3:.0f} GB); narrow VEILED_GHARCHIVE_YEARS"
            }
        ]
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=params, maximum_bytes_billed=cap
        ),
    )
    return [
        {
            "login": row["login"],
            "first": str(row["first"]),
            "last": str(row["last"]),
            "evidence": "GH Archive",
        }
        for row in job.result()
    ]


def gpg_emails(session, login: str, emails: Emails) -> int:
    keys = _get_json(session, f"{API}/users/{login}/gpg_keys") or []
    n = 0
    for key in keys if isinstance(keys, list) else []:
        for e in key.get("emails") or []:
            emails.add(e.get("email"), "", "GPG key", "", key.get("created_at", ""))
            n += 1
    return n


def ssh_fingerprint(key_line: str) -> str:
    parts = str(key_line or "").split()
    if len(parts) < 2:
        return ""
    try:
        blob = base64.b64decode(parts[1] + "==")
    except (ValueError, TypeError):
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip(
        "="
    )


def ssh_matches(session, login: str, keys: list[dict]) -> list[dict]:
    """Same SSH key under the same username on other forges."""
    mine = {ssh_fingerprint(k.get("key", "")) for k in keys if isinstance(k, dict)} - {
        ""
    }
    if not mine:
        return []
    out = []
    for forge, url in (
        ("GitLab", f"https://gitlab.com/{login}.keys"),
        ("Codeberg", f"https://codeberg.org/{login}.keys"),
    ):
        try:
            r = session.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code != 200 or not r.text.strip():
            continue
        theirs = {ssh_fingerprint(line) for line in r.text.splitlines()} - {""}
        shared = sorted(mine & theirs)
        if shared:
            out.append(
                {
                    "forge": forge,
                    "url": url.rsplit(".keys", 1)[0],
                    "fingerprints": shared,
                }
            )
    return out


def readme_links(session, login: str) -> dict:
    try:
        r = session.get(
            f"https://raw.githubusercontent.com/{login}/{login}/HEAD/README.md",
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return {}
    if r.status_code != 200:
        return {}
    text = r.text or ""
    urls = sorted(set(re.findall(r"https?://[^\s)\"'<>\]]+", text)))
    urls = [
        u
        for u in urls
        if not re.search(
            r"(shields\.io|githubusercontent|github-readme|komarev|vercel\.app/api)", u
        )
    ]
    return {
        "text": text[:4000],
        "urls": urls[:40],
        "emails": sorted(set(EMAIL_RE.findall(text))),
    }


def investigate(session, user: dict, repos: list[dict], keys: list[dict]) -> dict:
    login = user.get("login") or ""
    uid = user.get("id") or 0
    emails = Emails()
    if user.get("email"):
        emails.add(user["email"], user.get("name"), "profile")
    gpg = gpg_emails(session, login, emails)
    samples = commit_emails(session, login, repos, emails)
    event_emails(session, login, emails)
    offsets = patch_offsets(session, samples)
    readme = readme_links(session, login)
    for e in readme.get("emails", []):
        emails.add(e, "", "profile README")
    old = previous_logins(uid, login, emails)
    try:
        archive = gharchive_logins(uid) if uid else []
    except Exception as exc:  # optional source, never fatal
        archive = [{"note": f"GH Archive failed: {exc}"}]
    for row in archive:
        new = row.get("login") and row["login"].lower() != login.lower()
        if new and all(o["login"].lower() != row["login"].lower() for o in old):
            old.append({**row, "confidence": "confirmed"})
    names = Counter()
    for item in emails.as_list():
        if not item["bot"]:
            for n in item["names"]:
                names[n] += item["count"]
    return {
        "emails": emails.as_list(),
        "previous_logins": old,
        "gharchive_notes": [r["note"] for r in archive if r.get("note")],
        "commit_names": [n for n, _ in names.most_common(10)],
        "timezones": dict(offsets.most_common()),
        "gpg_emails": gpg,
        "ssh_matches": ssh_matches(session, login, keys),
        "readme_urls": readme.get("urls", []),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
