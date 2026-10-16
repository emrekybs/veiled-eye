"""Identity helpers shared by the extended modules.

* platform -> Veiled Eye module mapping (to emit ``tasks`` for discovered accounts)
* social list -> Veiled Eye ``profile.social`` entries
* selector detection: crypto wallet (checksum-validated), phone, e-mail
"""

from __future__ import annotations

import hashlib
import re

from factories.output_builder import site_icon

# Platform names used by the SOCMINT toolkit / other modules -> Veiled Eye module
PLATFORM_MODULE = {
    "github": "github",
    "gitlab": "gitlab",
    "keybase": "keybase",
    "reddit": "reddit",
    "telegram": "telegram",
    "steam": "steam",
    "bluesky": "bluesky",
    "hackernews": "hackernews",
    "kick": "kick",
    "snapchat": "snapchat",
    "twitter": "twitter",
    "x": "twitter",
    "instagram": "instagram",
    "tiktok": "tiktok",
}

PLATFORM_ICON = {
    "telegram": "fab fa-telegram",
    "steam": "fab fa-steam",
    "bluesky": "fas fa-cloud",
    "hackernews": "fab fa-hacker-news",
    "kick": "fas fa-video",
    "snapchat": "fab fa-snapchat",
    "stackexchange": "fab fa-stack-exchange",
    "gravatar": "fas fa-user-circle",
    "wayback": "fas fa-history",
    "pgp": "fas fa-key",
    "twitter": "fab fa-twitter",
    "x": "fab fa-twitter",
}


def icon_for(platform: str) -> str:
    p = str(platform or "").lower()
    return PLATFORM_ICON.get(p) or site_icon(p)


def socials_to_profile(socials: list[dict], source: str) -> list[dict]:
    """SOCMINT ``{platform, handle, url}`` -> Veiled Eye ``social`` entries."""
    out = []
    for s in socials or []:
        if not isinstance(s, dict) or not s.get("handle"):
            continue
        plat = str(s.get("platform") or "")
        out.append(
            {
                "name": plat.title() if plat else "Link",
                "url": s.get("url") or "",
                "icon": icon_for(plat),
                "source": source,
                "username": str(s["handle"]),
            }
        )
    return out


def socials_to_tasks(socials: list[dict], skip: str = "") -> list[dict]:
    """Discovered accounts -> ``tasks`` for the matching Veiled Eye modules."""
    tasks: list[dict] = []
    for s in socials or []:
        if not isinstance(s, dict):
            continue
        module = PLATFORM_MODULE.get(str(s.get("platform") or "").lower())
        handle = str(s.get("handle") or "").lstrip("@")
        if not module or not handle or module == skip or "@" in handle:
            continue
        task = {"module": module, "param": handle}
        if task not in tasks:
            tasks.append(task)
    return tasks


# ---------------------------------------------------------------------------
# Crypto wallets (validated — no regex-only false positives)
# ---------------------------------------------------------------------------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b58decode_check(s: str) -> bytes | None:
    num = 0
    for ch in s:
        idx = _B58.find(ch)
        if idx < 0:
            return None
        num = num * 58 + idx
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(s) - len(s.lstrip("1"))
    raw = b"\x00" * pad + raw
    if len(raw) < 5:
        return None
    body, check = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != check:
        return None
    return body


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_valid(addr: str) -> bool:
    addr = addr.lower()
    if "1" not in addr:
        return False
    hrp, data = addr.rsplit("1", 1)
    if not hrp or len(data) < 6 or any(c not in _BECH32 for c in data):
        return False
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    values += [_BECH32.index(c) for c in data]
    const = _bech32_polymod(values)
    return const in (1, 0x2BC830A3)  # bech32 / bech32m


_WALLET_RE = re.compile(
    r"\b("
    r"(?:bc1|ltc1)[a-z0-9]{20,90}"  # bech32 BTC / LTC
    r"|0x[a-fA-F0-9]{40}"  # EVM (ETH, BSC, Polygon...)
    r"|T[1-9A-HJ-NP-Za-km-z]{33}"  # TRON
    r"|[13LMD][1-9A-HJ-NP-Za-km-z]{25,34}"  # BTC legacy/P2SH, LTC, DOGE
    r"|[48][1-9A-HJ-NP-Za-km-z]{94}"  # Monero
    r")\b"
)


def wallet_chain(addr: str) -> str | None:
    """Return the chain of a *valid* address, else None."""
    a = addr.strip()
    low = a.lower()
    if low.startswith("bc1"):
        return "bitcoin" if _bech32_valid(a) else None
    if low.startswith("ltc1"):
        return "litecoin" if _bech32_valid(a) else None
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", a):
        return "ethereum"
    if re.fullmatch(r"[48][1-9A-HJ-NP-Za-km-z]{94}", a):
        return "monero"
    body = _b58decode_check(a)
    if body is None or len(body) != 21:
        return None
    version = body[0]
    if a.startswith("T") and version == 0x41:
        return "tron"
    if version in (0x00, 0x05):
        return "bitcoin"
    if version in (0x30, 0x32):
        return "litecoin"
    if version == 0x1E:
        return "dogecoin"
    return None


def find_wallets(text: str) -> list[dict]:
    out, seen = [], set()
    for m in _WALLET_RE.finditer(text or ""):
        addr = m.group(1)
        chain = wallet_chain(addr)
        if chain and addr not in seen:
            seen.add(addr)
            out.append({"address": addr, "chain": chain})
    return out


# ---------------------------------------------------------------------------
# Phones / e-mails / selector type
# ---------------------------------------------------------------------------
_PHONE_HINT = re.compile(r"^\+?[\d\s().\-]{7,20}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def normalize_phone(value: str, region: str | None = None) -> str | None:
    """E.164 form of a *valid* phone number, else None."""
    try:
        import phonenumbers

        num = phonenumbers.parse(value, region)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None
    return None


def find_phones(text: str) -> list[str]:
    """International (+CC) phone numbers in free text."""
    out: list[str] = []
    try:
        import phonenumbers

        for match in phonenumbers.PhoneNumberMatcher(text or "", None):
            e164 = phonenumbers.format_number(
                match.number, phonenumbers.PhoneNumberFormat.E164
            )
            if e164 not in out:
                out.append(e164)
    except Exception:
        pass
    return out


def selector_type(value: str) -> str:
    """email | phone | wallet | domain | username"""
    v = (value or "").strip()
    if EMAIL_RE.match(v):
        return "email"
    if wallet_chain(v):
        return "wallet"
    if _PHONE_HINT.match(v) and v.lstrip().startswith("+") and normalize_phone(v):
        return "phone"
    digits = re.sub(r"[\s().\-]", "", v)
    if re.fullmatch(r"0?\d{10,14}", digits):
        import os

        if normalize_phone(digits, os.environ.get("VEILED_PHONE_REGION", "TR")):
            return "phone"
    if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", v.lower()):
        return "domain"
    return "username"


def split_multi(param: str) -> list[str]:
    """Modules that accept several selectors in one param ("a,b,c")."""
    # not on whitespace: "+90 555 123 45 67" must stay one phone number
    return [p.strip() for p in re.split(r"[,;|\n]+", param or "") if p.strip()]
