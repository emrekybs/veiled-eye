#!/usr/bin/env python
"""Build the Veiled Eye web UI from the upstream compiled Angular bundle.

    python tools/ui_build/patch.py <extracted-frontend-dir>

The result is committed as backend/frontend_dist; this script is a
maintenance tool and is not shipped in the Python package. The anchors below
necessarily quote the upstream bundle's own strings; the final rebrand pass
renames every upstream identifier (component tags, CSS variables, labels,
links) so nothing of the upstream name survives in the built UI.

What it does (idempotent — every step checks whether it is already applied):
  * swaps logo / favicon / background assets
  * injects veiled.css (theme) and veiled.js (selector auto-detect + identity
    modules) into index.html
  * re-colours hard-coded cyan/green of the old theme in every bundle file
  * applies anchored string patches to the compiled bundle:
      - quick search accepts e-mail, username, phone or wallet
      - advanced search fires the identity modules (and shows their toggles)
      - "I Know You" -> "Every Shadow Has a Story", new sidebar (icons + names)

Every anchor must match exactly once; a non-matching anchor (different
upstream build) is reported and skipped instead of corrupting the bundle.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MARKER = ".veiled-patched"

COLOR_MAP = [
    # Veiled Eye keeps the original look (glass panels, light type, glow)
    # and only moves the neon cyan to the ice blue of the eye logo.
    (re.compile(r"05fcfc", re.I), "4fd2ff"),
    (re.compile(r"rgba\(\s*5\s*,\s*252\s*,\s*252\s*,"), "rgba(79, 210, 255,"),
    (re.compile(r"rgb\(\s*5\s*,\s*252\s*,\s*252\s*\)"), "rgb(79, 210, 255)"),
    (re.compile(r"#00fbff", re.I), "#4fd2ff"),  # graph labels
    (re.compile(r"rgba\(0,204,204,"), "rgba(63,178,226,"),  # graph nodes / bubbles
    (re.compile(r"rgba\(0,153,170,"), "rgba(47,138,186,"),
    (re.compile(r"rgba\(0,102,114,"), "rgba(31,92,126,"),
    (
        re.compile(r"#016565", re.I),
        "#0b1118",
    ),  # page colour behind the background image
]

# Applied last to every bundle file: upstream names -> Veiled Eye names.
REBRAND = [
    (re.compile(r"iKy-Logo\.png"), "logo.png"),
    (
        re.compile(r"https://gitlab\.com/kennbroorg/iKy/-/wikis/APIs/ApiKeys-get"),
        "https://github.com/emrekybs/veiled-eye#api-keys",
    ),
    (
        re.compile(
            r"https?://(?:www\.)?(?:github\.com|gitlab\.com|twitter\.com|"
            r"instagram\.com|vimeo\.com)/(?:kennbroorg|user85580359)[^\"'\s)`]*"
        ),
        "#",
    ),
    (re.compile(r"--iky-"), "--vey-"),
    (re.compile(r"\biky-"), "vey-"),
    (re.compile(r"\.iky-"), ".vey-"),
    (re.compile(r"ikyTooltip"), "veyTooltip"),
    (re.compile(r"ikyTheme"), "veyTheme"),
    (re.compile(r"IkyMap"), "VeyMap"),
    (re.compile(r'"iKy"'), '"auto"'),
    (re.compile(r"\biKy\b"), "Veiled Eye"),
]


def rebrand(text: str) -> str:
    for rx, new in REBRAND:
        text = rx.sub(new, text)
    return _strip_upstream_home(text)


def _empty_array(text: str, key: str) -> str:
    """``key=[ ... ]`` -> ``key=[]`` (bracket-matched, strings respected)."""
    start = text.find(key + "=[")
    if start < 0 or text.startswith(key + "=[]", start):
        return text
    i = start + len(key) + 1
    depth, quote = 0, ""
    for j in range(i, len(text)):
        c = text[j]
        if quote:
            if c == "\\":
                continue
            if c == quote and text[j - 1] != "\\":
                quote = ""
        elif c in "\"'`":
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[: i + 1] + text[j:]
    return text


def _strip_upstream_home(text: str) -> str:
    """The old home page carried the upstream author's disclaimer,
    contributor list and project links. The panels are hidden by veiled.css;
    this removes their content from the bundle as well."""
    if "contributors=[" not in text:
        return text
    for key in ("contributors", "projects", "accounts"):
        text = _empty_array(text, key)
    # disclaimer paragraphs + signature (the panel itself is hidden)
    text = re.sub(
        r'(r\(\d+,)"(?:Keep in mind that this software|We won\'t refund|'
        r'Do not use the tool if|By the way, for those)[^"]*"',
        r'\1""',
        text,
    )
    return re.sub(r'(r\(\d+,)"KennBro"', r'\1""', text)


EMAIL_TOGGLES = (
    ',{id:"userscanner",label:"User-Scanner",icon:"fas fa-user-check"}'
    ',{id:"emailreg",label:"E-mail registrations",icon:"fas fa-envelope-open-text"}'
    ',{id:"gravatar",label:"Gravatar",icon:"fas fa-user-circle"}'
    ',{id:"pgp",label:"PGP keys",icon:"fas fa-key"}'
    ',{id:"ahmia",label:"Ahmia (.onion)",icon:"fas fa-mask"}'
    ',{id:"darkweb",label:"Dark web",icon:"fas fa-spider"}'
)
USERNAME_TOGGLES = (
    ',{id:"maigret",label:"Maigret",icon:"fas fa-user-astronaut"}'
    ',{id:"whatsmyname",label:"WhatsMyName",icon:"fas fa-id-badge"}'
    ',{id:"userscanner",label:"User-Scanner",icon:"fas fa-user-check"}'
    ',{id:"darksherlock",label:"Dark-Sherlock",icon:"fas fa-user-secret"}'
    ',{id:"telegram",label:"Telegram",icon:"fab fa-telegram"}'
    ',{id:"snapchat",label:"Snapchat",icon:"fab fa-snapchat"}'
    ',{id:"steam",label:"Steam",icon:"fab fa-steam"}'
    ',{id:"bluesky",label:"Bluesky",icon:"fas fa-cloud"}'
    ',{id:"kick",label:"Kick",icon:"fas fa-video"}'
    ',{id:"hackernews",label:"Hacker News",icon:"fab fa-hacker-news"}'
    ',{id:"stackexchange",label:"Stack Exchange",icon:"fab fa-stack-exchange"}'
    ',{id:"wayback",label:"Wayback Machine",icon:"fas fa-history"}'
    ',{id:"pgp",label:"PGP keys",icon:"fas fa-key"}'
    ',{id:"ahmia",label:"Ahmia (.onion)",icon:"fas fa-mask"}'
    ',{id:"darkweb",label:"Dark web",icon:"fas fa-spider"}'
    ',{id:"phone",label:"Phone (+number)",icon:"fas fa-phone"}'
    ',{id:"crypto",label:"Crypto wallet",icon:"fas fa-wallet"}'
)
_EMAIL_IDS = '"userscanner","emailreg","gravatar","pgp","ahmia","darkweb"'
_USER_IDS = (
    '"maigret","whatsmyname","userscanner","darksherlock","telegram","snapchat",'
    '"steam","bluesky","kick","hackernews","stackexchange","wayback","pgp","ahmia",'
    '"darkweb","phone","crypto"'
)
_HOOK = "window.__veiled&&window.__veiled.extend(this,e,{gate},{fresh})"

# (description, old, new) — applied to whichever bundle file contains `old`
JS_PATCHES = [
    ("footer slogan", '"I Know You"', '"Every Shadow Has a Story"'),
    (
        "sidebar: names + icons",
        '{title:"Principal",icon:"fa-house",link:"/principal",home:!0},{title:"Gatherer",icon:"fa-binoculars",link:"/gatherer"},{title:"Profile",icon:"fa-user",link:"/profile"},{title:"Timeline",icon:"fa-stopwatch",link:"/timeline"},{title:"ApiKeys",icon:"fa-key",link:"/apikeys"}]',
        '{title:"Home",icon:"fa-eye",link:"/principal",home:!0},{title:"Investigation",icon:"fa-satellite-dish",link:"/gatherer"},{title:"Identity",icon:"fa-fingerprint",link:"/profile"},{title:"Graph",icon:"fa-circle-nodes",link:"/graph"},{title:"Timeline",icon:"fa-route",link:"/timeline"},{title:"API keys",icon:"fa-vault",link:"/apikeys"},{title:"About",icon:"fa-circle-info",link:"/about"}]',
    ),
    (
        "quick search placeholder",
        '"placeholder","Enter an email"',
        '"placeholder","E-mail, username, phone or wallet (comma-separate several)"',
    ),
    (
        "advanced search username placeholder",
        '"placeholder","Username"',
        '"placeholder","Username, +phone or wallet"',
    ),
    (
        "advanced search username label",
        'k(28,"USERNAME")',
        'k(28,"USERNAME \\xB7 PHONE \\xB7 WALLET")',
    ),
    (
        "quick search -> auto-detect",
        "this.gathererStore.gatherByEmail(t)",
        'this.gathererStore.gatherAdvance(window.__veiled?window.__veiled.form(t):{email:t,username:t.split("@")[0]})',
    ),
    (
        "search service form builder",
        'function p(s){return{email:s,username:s.split("@")[0]??""',
        'function p(s){if(window.__veiled)return window.__veiled.form(s);return{email:s,username:s.split("@")[0]??""',
    ),
    (
        "gatherAdvance -> identity modules",
        '"search",o,"iKy",1)}}gatherAdvanceIncremental(',
        '"search",o,"iKy",1)}'
        + _HOOK.format(gate="s", fresh=1)
        + "}gatherAdvanceIncremental(",
    ),
    (
        "gatherAdvanceIncremental -> identity modules",
        '"search",r,"iKy",1)}}executeIfAllowed(',
        '"search",r,"iKy",1)}' + _HOOK.format(gate="i", fresh=0) + "}executeIfAllowed(",
    ),
    (
        "e-mail module toggles",
        '{id:"hudsonrock",label:"Hudson Rock",icon:"fas fa-bug"}]',
        '{id:"hudsonrock",label:"Hudson Rock",icon:"fas fa-bug"}' + EMAIL_TOGGLES + "]",
    ),
    (
        "username module toggles",
        '{id:"search",label:"Search",icon:"fas fa-search"}]',
        '{id:"search",label:"Search",icon:"fas fa-search"}' + USERNAME_TOGGLES + "]",
    ),
    (
        "re-search: changed e-mail modules",
        'let c=["emailrep","leaklookup","holehe","peopledatalabs","leaks","socialscan","hudsonrock"];',
        'let c=["emailrep","leaklookup","holehe","peopledatalabs","leaks","socialscan","hudsonrock",'
        + _EMAIL_IDS
        + "];",
    ),
    (
        "re-search: changed username modules",
        'let p=["dorks","search","hudsonrock"];',
        'let p=["dorks","search","hudsonrock",' + _USER_IDS + "];",
    ),
    ("quick search hint", 'k(7,"Hit enter to search")', 'k(7,"Press Enter to search")'),
    ("logo alt text", '"iKy Logo"', '"Veiled Eye"'),
    # /result long-polls for VEILED_RESULT_WAIT (5s) then the UI polls /state
    # every 2s; upstream gives up after 60 polls (2 min) — too short for
    # maigret / user-scanner sweeps queued behind a big scan. 10 minutes.
    (
        "state polling: 2 min -> 10 min",
        "pollTaskUntilDone(e,t,s,a){if(a>=60){",
        "pollTaskUntilDone(e,t,s,a){if(a>=300){",
    ),
    # Upstream fires the gather (dozens of requests + toasts) and only then
    # navigates; the first lazy load of the Gatherer page can stall behind
    # that burst and the UI stays on Home. Navigate first, then gather.
    (
        "quick search -> /gatherer",
        'for(let i of this.listeners)i(e);this.router.navigate(["/gatherer"])}',
        'this.router.navigate(["/gatherer"]).finally(()=>{for(let i of this.listeners)i(e)})}',
    ),
    (
        "advanced search -> /gatherer",
        'for(let e of this.advListeners)e(t);this.router.navigate(["/gatherer"])',
        'this.router.navigate(["/gatherer"]).finally(()=>{for(let e of this.advListeners)e(t)})',
    ),
]


def _bundle_files(root: Path) -> list[Path]:
    own = {"veiled.js", "veiled.css", "graph.js"}
    files = [*root.glob("*.js"), *root.glob("*.css"), root / "index.html"]
    return sorted(p for p in files if p.name not in own)


def patch(root: Path) -> list[str]:
    root = Path(root)
    report: list[str] = []
    if not (root / "index.html").is_file():
        raise SystemExit(f"{root} does not look like a built frontend (no index.html)")
    # Idempotent: every step checks whether it is already applied, so a
    # patched tree can be re-run to pick up newly added patches.

    # 1. assets
    images = root / "assets" / "images"
    images.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "assets" / "veiled-logo.png", images / "logo.png")
    upstream_logo = images / "iKy-Logo.png"
    if upstream_logo.exists():
        upstream_logo.unlink()
    shutil.copy(HERE / "assets" / "blur-bg.jpg", images / "blur-bg.jpg")
    shutil.copy(HERE / "assets" / "favicon.png", root / "favicon.png")
    shutil.copy(HERE / "assets" / "favicon.png", root / "favicon-32x32.png")
    shutil.copy(HERE / "assets" / "favicon.ico", root / "favicon.ico")
    shutil.copy(HERE / "assets" / "favicon.png", root / "veiled-icon.png")
    shutil.copy(HERE / "assets" / "apple-touch-icon.png", root / "apple-touch-icon.png")
    shutil.copy(HERE / "veiled.css", root / "veiled.css")
    shutil.copy(HERE / "veiled.js", root / "veiled.js")
    # relationship graph: Cytoscape.js + fCoSE (MIT), loaded on /graph only
    shutil.copytree(
        HERE / "assets" / "graph", root / "assets" / "graph", dirs_exist_ok=True
    )
    shutil.copy(HERE / "graph.js", root / "graph.js")
    report.append("assets: logo, favicon, background, veiled.css, veiled.js, graph")

    # 2. colours + anchored patches
    pending = list(JS_PATCHES)
    for path in _bundle_files(root):
        text = path.read_text(encoding="utf-8")
        original = text
        for rx, new in COLOR_MAP:
            text = rx.sub(new, text)
        for item in list(pending):
            desc, old, new = item
            count = text.count(old)
            if new in text or rebrand(new) in text:
                pending.remove(item)
                report.append(f"done {desc} ({path.name})")
            elif count == 1:
                text = text.replace(old, new)
                pending.remove(item)
                report.append(f"ok   {desc} ({path.name})")
            elif count > 1:
                pending.remove(item)
                report.append(f"SKIP {desc}: ambiguous anchor in {path.name}")
        text = rebrand(text)
        if text != original:
            path.write_text(text, encoding="utf-8")
    for desc, _, _ in pending:
        report.append(f"SKIP {desc}: anchor not found (different upstream build?)")

    # 3. index.html: title + stylesheet + helper script (before the bundle)
    index = root / "index.html"
    html = index.read_text(encoding="utf-8")
    html = re.sub(
        r"<title>.*?</title>",
        "<title>Veiled Eye · OSINT</title>",
        html,
        count=1,
        flags=re.S,
    )
    if "veiled.js" not in html:
        html = html.replace(
            "</head>", '  <script src="veiled.js"></script>\n</head>', 1
        )
    if "veiled.css" not in html:
        html = html.replace(
            "</head>", '  <link rel="stylesheet" href="veiled.css">\n</head>', 1
        )
    html = html.replace('content="#05fcfc"', 'content="#0b1118"')
    # versioned icon links: browsers keep a cached favicon for a long time
    html = re.sub(
        r'\s*<link rel="(?:icon|shortcut icon|apple-touch-icon)"[^>]*>', "", html
    )
    html = html.replace(
        "</head>",
        '  <link rel="icon" type="image/png" sizes="256x256" href="veiled-icon.png?v=3">\n'
        '  <link rel="icon" type="image/x-icon" href="favicon.ico?v=3">\n'
        '  <link rel="apple-touch-icon" href="apple-touch-icon.png?v=3">\n</head>',
        1,
    )
    index.write_text(html, encoding="utf-8")
    report.append("index.html: title, veiled.css, veiled.js")

    (root / MARKER).write_text("\n".join(report) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for line in patch(Path(sys.argv[1])):
        print(line)
