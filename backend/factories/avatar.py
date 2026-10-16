"""Avatar perceptual hashing — "is it the same picture?" across platforms.

A person re-using one profile picture on several platforms is one of the
strongest same-owner signals OSINT has.  Pictures are downloaded (bounded),
reduced to 64-bit **dHash** + **aHash** fingerprints (Pillow only — robust to
resizing, re-compression and format changes) and clustered by Hamming
distance.

Default / placeholder avatars are filtered out:
* near-uniform images (very low pixel variance),
* fingerprints that appear for many *different* handles (shared defaults).
"""

from __future__ import annotations

import io
import os
from concurrent.futures import ThreadPoolExecutor

MAX_BYTES = 3_000_000
MAX_IMAGES = int(os.environ.get("VEILED_AVATAR_MAX", "40"))
THRESHOLD = int(
    os.environ.get("VEILED_AVATAR_THRESHOLD", "6")
)  # bits of 64; copies score 0-2
MIN_STDDEV = 8.0


def _fetch(url: str) -> bytes | None:
    import requests

    try:
        with requests.get(
            url,
            timeout=12,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 VeiledEye-OSINT"},
        ) as resp:
            if resp.status_code != 200:
                return None
            data = b""
            for chunk in resp.iter_content(65536):
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
            return data
    except Exception:
        return None


def fingerprint(data: bytes) -> dict | None:
    """Return {"dhash": int, "ahash": int} or None for unusable images."""
    try:
        from PIL import Image, ImageStat

        img = Image.open(io.BytesIO(data))
        img.load()
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        gray = Image.alpha_composite(bg, img).convert("L")
    except Exception:
        return None
    if ImageStat.Stat(gray.resize((32, 32))).stddev[0] < MIN_STDDEV:
        return None  # blank / single-colour placeholder
    d = gray.resize((9, 8), Image.LANCZOS)
    px = list(d.tobytes())
    dhash = 0
    for row in range(8):
        for col in range(8):
            dhash = (dhash << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    a = list(gray.resize((8, 8), Image.LANCZOS).tobytes())
    mean = sum(a) / 64
    ahash = 0
    for value in a:
        ahash = (ahash << 1) | (value > mean)
    return {"dhash": dhash, "ahash": ahash}


def distance(a: dict, b: dict) -> int:
    """Hamming distance on dHash, confirmed by aHash (max of the two)."""
    return max(
        bin(a["dhash"] ^ b["dhash"]).count("1"), bin(a["ahash"] ^ b["ahash"]).count("1")
    )


def match_avatars(photos: list[dict], fetch=_fetch) -> list[dict]:
    """Cluster pictures of DIFFERENT accounts that show the same image.

    ``photos``: [{"picture": url, "account": (platform, handle), "module": m}]
    Returns clusters: [{"accounts": [...], "pictures": [...], "distance": n}]
    """
    seen, items = set(), []
    for p in photos:
        url = p.get("picture")
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            items.append(p)
    items = items[:MAX_IMAGES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        blobs = list(pool.map(lambda p: fetch(p["picture"]), items))
    prints = []
    for item, blob in zip(items, blobs, strict=False):
        fp = fingerprint(blob) if blob else None
        if fp:
            prints.append({**item, "fp": fp})

    # union-find over pairs of different accounts within the threshold
    parent = list(range(len(prints)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    best: dict[tuple[int, int], int] = {}
    for i in range(len(prints)):
        for j in range(i + 1, len(prints)):
            if prints[i]["account"] == prints[j]["account"]:
                continue
            dist = distance(prints[i]["fp"], prints[j]["fp"])
            if dist <= THRESHOLD:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
                best[(i, j)] = dist

    clusters: dict[int, list[int]] = {}
    for i in range(len(prints)):
        clusters.setdefault(find(i), []).append(i)
    out = []
    for members in clusters.values():
        accounts = {tuple(prints[i]["account"]) for i in members}
        if len(accounts) < 2:
            continue
        handles = {a[1] for a in accounts}
        # the same image behind many unrelated handles = a default avatar
        if len(handles) > 4 and len(accounts) > 6:
            continue
        dists = [d for (i, j), d in best.items() if i in members and j in members]
        out.append(
            {
                "accounts": sorted([list(a) for a in accounts]),
                "pictures": [prints[i]["picture"] for i in members],
                "modules": sorted({prints[i]["module"] for i in members}),
                "distance": min(dists) if dists else 0,
            }
        )
    return out
