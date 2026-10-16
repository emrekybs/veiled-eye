#!/usr/bin/env python
"""PGP module — public keys bound to an e-mail / name on public keyservers.

* keys.openpgp.org (VKS): returns a key only for e-mail addresses whose owner
  VERIFIED them, so a hit is a strong ownership signal.  User IDs are read
  straight from the armored key (tiny OpenPGP packet parser, no gpg needed).
* keyserver.ubuntu.com (HKP machine-readable index): every key whose user ID
  contains the search string, with all other user IDs on the same key —
  other names / addresses the person used, plus key creation dates.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from datetime import UTC, datetime
from urllib.parse import quote, unquote

import requests
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

VKS = "https://keys.openpgp.org/vks/v1/by-email/{}"
HKP = "https://keyserver.ubuntu.com/pks/lookup"
UID_RE = re.compile(
    r"^(?P<name>.*?)\s*(?:\((?P<comment>[^)]*)\))?\s*<(?P<email>[^>]+)>\s*$"
)
ALGOS = {
    "1": "RSA",
    "16": "ElGamal",
    "17": "DSA",
    "18": "ECDH",
    "19": "ECDSA",
    "22": "EdDSA",
}


# ---------------------------------------------------------------------------
# Armored key -> (created, [user ids])
# ---------------------------------------------------------------------------
def dearmor(text: str) -> bytes:
    lines, body = text.strip().splitlines(), []
    started = False
    for line in lines:
        if line.startswith("-----BEGIN"):
            started = True
            continue
        if line.startswith("-----END"):
            break
        if not started or ":" in line or line.startswith("="):
            continue
        body.append(line.strip())
    return base64.b64decode("".join(body)) if body else b""


def parse_packets(data: bytes) -> dict:
    """Return {"created": iso|None, "uids": [str]} from binary OpenPGP data."""
    uids, created, pos = [], None, 0
    while pos < len(data):
        tag_byte = data[pos]
        pos += 1
        if not tag_byte & 0x80:
            break
        if tag_byte & 0x40:  # new format
            tag = tag_byte & 0x3F
            first = data[pos]
            pos += 1
            if first < 192:
                length = first
            elif first < 224:
                length = ((first - 192) << 8) + data[pos] + 192
                pos += 1
            elif first == 255:
                length = int.from_bytes(data[pos : pos + 4], "big")
                pos += 4
            else:  # partial lengths do not occur in key material
                break
        else:  # old format
            tag = (tag_byte >> 2) & 0x0F
            ltype = tag_byte & 0x03
            size = {0: 1, 1: 2, 2: 4}.get(ltype)
            if size is None:
                break
            length = int.from_bytes(data[pos : pos + size], "big")
            pos += size
        body = data[pos : pos + length]
        pos += length
        if tag == 6 and created is None and len(body) >= 5 and body[0] in (4, 5):
            ts = int.from_bytes(body[1:5], "big")
            created = datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
        elif tag == 13:
            uids.append(body.decode("utf-8", "replace"))
    return {"created": created, "uids": uids}


def split_uid(uid: str) -> dict:
    m = UID_RE.match(uid.strip())
    if not m:
        return {
            "name": uid.strip() if "@" not in uid else "",
            "email": uid.strip() if "@" in uid else "",
        }
    return {
        "name": m.group("name").strip(),
        "email": m.group("email").strip().lower(),
        "comment": m.group("comment") or "",
    }


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def vks_lookup(email: str) -> dict | None:
    resp = requests.get(VKS.format(quote(email)), timeout=20)
    if resp.status_code == 404:
        return None
    if resp.status_code == 429:
        raise Exception("warn: keys.openpgp.org rate limited")
    resp.raise_for_status()
    info = parse_packets(dearmor(resp.text))
    return {"source": "keys.openpgp.org", "verified": True, **info}


def hkp_index(query: str) -> list[dict]:
    resp = requests.get(
        HKP,
        params={"op": "index", "options": "mr", "fingerprint": "on", "search": query},
        timeout=25,
    )
    if resp.status_code == 404:
        return []
    if resp.status_code == 429:
        raise Exception("warn: keyserver.ubuntu.com rate limited")
    resp.raise_for_status()
    return parse_mr(resp.text)


def _date(ts: str) -> str | None:
    try:
        return (
            datetime.fromtimestamp(int(ts), tz=UTC).date().isoformat() if ts else None
        )
    except ValueError:
        return None


def parse_mr(text: str) -> list[dict]:
    """HKP machine-readable index -> keys with uids."""
    keys, cur = [], None
    for line in text.splitlines():
        parts = line.strip().split(":")
        if parts[0] == "pub" and len(parts) >= 5:
            cur = {
                "source": "keyserver.ubuntu.com",
                "fingerprint": parts[1],
                "algorithm": ALGOS.get(parts[2], parts[2]),
                "bits": parts[3],
                "created": _date(parts[4]),
                "expires": _date(parts[5]) if len(parts) > 5 else None,
                "revoked": "r" in (parts[6] if len(parts) > 6 else ""),
                "uids": [],
            }
            keys.append(cur)
        elif parts[0] == "uid" and cur is not None and len(parts) >= 2:
            cur["uids"].append(unquote(parts[1]))
    return keys


@module_task(module_name="pgp", dev_mode_sleep=2)
def p_pgp(param):
    """Task of Celery that finds PGP keys and the identities on them."""
    query = param.strip()
    is_email = "@" in query
    keys: list[dict] = []
    if is_email:
        vks = vks_lookup(query)
        if vks:
            keys.append(vks)
    for key in hkp_index(query):
        if not is_email:  # name search: keep keys whose uids contain the token
            token = query.lower()
            if not any(token in uid.lower() for uid in key["uids"]):
                continue
        keys.append(key)
    if not keys:
        raise Exception("warn: No public PGP key found")

    gather = [root_node("PGP", query, "fas fa-key", f"{len(keys)} keys")]
    profile, timeline, identities = [], [], {}
    for idx, key in enumerate(keys):
        label = key.get("fingerprint") or (
            "verified key" if key.get("verified") else f"key {idx}"
        )
        gather.append(
            {
                "name-node": f"PGP-{idx}",
                "title": f"{key.get('algorithm', 'PGP')} {key.get('bits', '')}".strip()
                if key.get("algorithm")
                else "PGP key",
                "subtitle": f"{label[-16:]} · {key.get('created') or '?'} · {key['source']}",
                "icon": "fas fa-key",
                "link": "PGP",
                "help": "verified e-mail (keys.openpgp.org)"
                if key.get("verified")
                else "",
            }
        )
        if key.get("created"):
            timeline.append(
                {
                    "date": key["created"],
                    "action": f"PGP : key created ({key['source']})",
                    "icon": "fas fa-key",
                }
            )
        for uid in key["uids"]:
            ident = split_uid(uid)
            k = (ident.get("name", ""), ident.get("email", ""))
            identities.setdefault(k, set()).add(key["source"])
    for (name, email), sources in identities.items():
        gather.append(
            {
                "name-node": f"PGP-uid-{name}-{email}",
                "title": name or email,
                "subtitle": email if name else "",
                "icon": "fas fa-id-card",
                "link": "PGP",
                "help": ", ".join(sorted(sources)),
            }
        )
        if name:
            profile.append({"name": name})
        if email:
            profile.append({"email": email})
    profile.append(
        {
            "presence": [
                {
                    "name": "pgp",
                    "children": [
                        {"name": "keys", "value": len(keys)},
                        {"name": "identities", "value": len(identities)},
                    ],
                }
            ]
        }
    )
    tasks = [
        {"module": "gravatar", "param": e}
        for (_, e) in identities
        if e and e != query.lower()
    ][:1]
    return build_total(
        module="pgp",
        param=param,
        validation="hard" if any(k.get("verified") for k in keys) else "soft",
        raw={"query": query, "keys": keys},
        graphic=[{"pgp": gather}, {"keys": keys}],
        profile=profile,
        timeline=timeline,
        tasks=tasks,
    )


t_pgp = p_pgp

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    print(json.dumps(t_pgp(ap.parse_args().target, dev_mode=False), indent=2))
