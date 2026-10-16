"""Investigation export — HTML, PDF, STIX 2.1, GraphML, CSV, JSON.

``build_case(target, collected)`` turns every cached module output for a
target (plus the ``crossref`` correlation) into one case dict; the
``to_*`` functions render it.  Every format carries the SHA-256 of the
canonical JSON of the collected evidence, so a report can later be checked
against the raw data it was built from.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import itertools
import json
import uuid
from datetime import UTC, datetime
from xml.sax.saxutils import escape as xml_escape

FORMATS = {
    "json": ("application/json", "json"),
    "html": ("text/html; charset=utf-8", "html"),
    "pdf": ("application/pdf", "pdf"),
    "stix": ("application/stix+json;version=2.1", "stix.json"),
    "graphml": ("application/graphml+xml", "graphml"),
    "csv": ("text/csv; charset=utf-8", "csv"),
}
_NS = uuid.UUID("6f0d0c3e-9b2a-4a51-8a8e-1b9a0f1e7c11")


def _section(result, key):
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and key in item:
                return item[key]
    return None


def _status(result) -> str:
    raw = _section(result, "raw")
    if (
        isinstance(raw, list)
        and raw
        and isinstance(raw[0], dict)
        and raw[0].get("status") in ("Fail", "Warning")
    ):
        return raw[0]["status"]
    return "OK"


def build_case(
    target: str, collected: dict[tuple[str, str], list], report: dict | None = None
) -> dict:
    """Assemble the exportable case."""
    from modules.crossref.crossref_tasks import correlate

    report = report or correlate(target, collected)
    modules = {}
    timeline = []
    for (module, param), result in sorted(collected.items()):
        status = _status(result)
        reason = ""
        if status != "OK":
            reason = str((_section(result, "raw") or [{}])[0].get("reason", ""))[:200]
        modules.setdefault(module, {})[param] = {
            "status": status,
            "reason": reason,
            "result": result,
        }
        if status == "OK":
            for ev in _section(result, "timeline") or []:
                if isinstance(ev, dict) and ev.get("date"):
                    timeline.append({**ev, "module": module})
    timeline.sort(key=lambda e: str(e.get("date")))
    evidence = json.dumps(
        {f"{m}|{p}": r for (m, p), r in sorted(collected.items())},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).encode()
    try:
        from factories import insights

        places = insights.places(collected)
        activity = insights.activity(collected)
    except Exception:
        places, activity = [], {}
    return {
        "places": places,
        "activity": activity,
        "target": target,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": "Veiled Eye",
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "report": report,
        "modules": modules,
        "timeline": timeline,
    }


# ---------------------------------------------------------------------------
def to_json(case: dict) -> bytes:
    return json.dumps(case, indent=2, ensure_ascii=False, default=str).encode()


def to_csv(case: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "value", "platform", "confidence", "score", "sources", "url"])
    rep = case["report"]
    for acc in rep.get("accounts", []):
        w.writerow(
            [
                "account",
                acc["handle"],
                acc["platform"],
                acc["confidence"],
                acc["score"],
                ";".join(acc["sources"]),
                (acc["urls"] or [""])[0],
            ]
        )
    for key, rows in rep.get("identity", {}).items():
        for row in rows:
            w.writerow(
                [key, row["value"], "", "", row["score"], ";".join(row["sources"]), ""]
            )
    for row in rep.get("exposure", []):
        for sel in row["selectors"]:
            w.writerow(["exposure", sel, row["source"], "", "", row["source"], ""])
    return buf.getvalue().encode()


# ---------------------------------------------------------------------------
def _graph(case: dict) -> tuple[list[dict], list[tuple[str, str, str]]]:
    rep = case["report"]
    nodes = {"target": {"id": "target", "label": case["target"], "type": "target"}}
    edges = []

    def node(nid, label, ntype, **attrs):
        nodes.setdefault(nid, {"id": nid, "label": label, "type": ntype, **attrs})
        return nid

    for acc in rep.get("accounts", []):
        nid = node(
            f"acc:{acc['platform']}:{acc['handle']}",
            f"{acc['platform']}/{acc['handle']}",
            "account",
            confidence=acc["confidence"],
            score=acc["score"],
            url=(acc["urls"] or [""])[0],
        )
        edges.append(("target", nid, "has_account"))
    for key in ("email", "phone", "name", "wallet", "location", "organization"):
        for row in rep.get("identity", {}).get(key, []):
            nid = node(f"{key}:{row['value']}", row["value"], key, score=row["score"])
            edges.append(("target", nid, f"has_{key}"))
    for match in rep.get("avatar_matches", []):
        ids = [f"acc:{p}:{h}" for p, h in match["accounts"]]
        for a, b in itertools.pairwise(ids):
            if a in nodes and b in nodes:
                edges.append((a, b, "same_avatar"))
    for row in rep.get("exposure", []):
        nid = node(f"exposure:{row['source']}", row["source"], "exposure")
        edges.append(("target", nid, "exposed_in"))
    return list(nodes.values()), edges


def to_graphml(case: dict) -> bytes:
    nodes, edges = _graph(case)
    keys = ["label", "type", "confidence", "score", "url"]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for k in keys:
        out.append(f'  <key id="{k}" for="node" attr.name="{k}" attr.type="string"/>')
    out.append(
        '  <key id="relation" for="edge" attr.name="relation" attr.type="string"/>'
    )
    out.append(f'  <graph id="{xml_escape(case["target"])}" edgedefault="directed">')
    for n in nodes:
        out.append(f'    <node id="{xml_escape(n["id"], {chr(34): "&quot;"})}">')
        for k in keys:
            if n.get(k) not in (None, ""):
                out.append(f'      <data key="{k}">{xml_escape(str(n[k]))}</data>')
        out.append("    </node>")
    for i, (a, b, rel) in enumerate(edges):
        q = {chr(34): "&quot;"}
        out.append(
            f'    <edge id="e{i}" source="{xml_escape(a, q)}" target="{xml_escape(b, q)}"><data key="relation">{rel}</data></edge>'
        )
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out).encode()


# ---------------------------------------------------------------------------
def _sid(kind: str, value: str) -> str:
    return f"{kind}--{uuid.uuid5(_NS, f'{kind}:{value}')}"


def to_stix(case: dict) -> bytes:
    """STIX 2.1 bundle: identity (individual) + observables + relationships."""
    now = case["generated"].replace("+00:00", "Z")
    rep = case["report"]
    common = {"spec_version": "2.1", "created": now, "modified": now}
    target_id = _sid("identity", case["target"])
    names = rep.get("identity", {}).get("name") or []
    objects = [
        {
            "type": "identity",
            "id": target_id,
            **common,
            "name": names[0]["value"] if names else case["target"],
            "identity_class": "individual",
            "description": f"OSINT subject investigated with Veiled Eye (selector: {case['target']}). "
            f"Evidence SHA-256: {case['evidence_sha256']}",
            "x_veiled_selector": case["target"],
        }
    ]
    observed = []

    def rel(src, dst, rtype="related-to", conf=None):
        r = {
            "type": "relationship",
            "id": _sid("relationship", f"{src}>{dst}>{rtype}"),
            **common,
            "relationship_type": rtype,
            "source_ref": src,
            "target_ref": dst,
        }
        if conf is not None:
            r["confidence"] = conf
        objects.append(r)

    conf_map = {"confirmed": 85, "likely": 60, "candidate": 30}
    for acc in rep.get("accounts", []):
        oid = _sid("user-account", f"{acc['platform']}|{acc['handle']}")
        objects.append(
            {
                "type": "user-account",
                "id": oid,
                "spec_version": "2.1",
                "account_login": acc["handle"],
                "account_type": str(acc["platform"]).lower(),
                **({"x_veiled_url": acc["urls"][0]} if acc["urls"] else {}),
                "x_veiled_sources": acc["sources"],
                "x_veiled_confidence": acc["confidence"],
            }
        )
        observed.append(oid)
        rel(target_id, oid, conf=conf_map.get(acc["confidence"]))
    for row in rep.get("identity", {}).get("email", []):
        oid = _sid("email-addr", row["value"])
        objects.append(
            {
                "type": "email-addr",
                "id": oid,
                "spec_version": "2.1",
                "value": row["value"],
            }
        )
        observed.append(oid)
        rel(target_id, oid, conf=min(90, 30 + 15 * row["score"]))
    for row in rep.get("identity", {}).get("wallet", []):
        oid = _sid("x-crypto-wallet", row["value"])
        objects.append(
            {
                "type": "x-crypto-wallet",
                "id": oid,
                "spec_version": "2.1",
                "value": row["value"],
            }
        )
        observed.append(oid)
        rel(target_id, oid)
    if observed:
        objects.append(
            {
                "type": "observed-data",
                "id": _sid("observed-data", case["target"] + case["generated"]),
                **common,
                "first_observed": now,
                "last_observed": now,
                "number_observed": 1,
                "object_refs": observed,
            }
        )
    for row in rep.get("exposure", []):
        nid = _sid("note", f"{case['target']}|{row['source']}")
        objects.append(
            {
                "type": "note",
                "id": nid,
                **common,
                "abstract": f"Exposure: {row['source']}",
                "content": f"Selectors found in {row['source']}: {', '.join(row['selectors'])}",
                "object_refs": [target_id],
            }
        )
    bundle = {
        "type": "bundle",
        "id": _sid("bundle", case["target"] + case["generated"]),
        "objects": objects,
    }
    return json.dumps(bundle, indent=2, ensure_ascii=False).encode()


# ---------------------------------------------------------------------------
_CSS = """
:root{--bg:#0e1621;--panel:#152232;--line:#24384f;--ink:#dbe7f3;--dim:#8aa0b6;--acc:#05fcfc;
--ok:#00f9a6;--mid:#3aa0ff;--low:#8aa0b6;--bad:#ff3d71}
@media (prefers-color-scheme: light){:root{--bg:#f4f7fb;--panel:#fff;--line:#d5dfeb;--ink:#14202e;--dim:#5a6b7d;
--acc:#00838f;--ok:#0a8f5c;--mid:#1f6fd1;--low:#6b7a8c;--bad:#c62848}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--acc);margin:28px 0 10px}
.meta{color:var(--dim);font-size:12px;word-break:break-all}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px}.card b{display:block;font-size:22px}
.wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:8px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--dim);font-weight:600;font-size:12px}
a{color:var(--acc)}.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;border:1px solid currentColor}
.confirmed{color:var(--ok)}.likely{color:var(--mid)}.candidate{color:var(--low)}.bad{color:var(--bad)}
.thumbs img{width:56px;height:56px;object-fit:cover;border-radius:6px;margin-right:6px;border:1px solid var(--line)}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def to_html(case: dict) -> bytes:
    rep = case["report"]
    accounts = rep.get("accounts", [])
    counts = {
        g: sum(1 for a in accounts if a["confidence"] == g)
        for g in ("confirmed", "likely", "candidate")
    }
    ok_mods = sum(
        1 for m in case["modules"].values() for v in m.values() if v["status"] == "OK"
    )
    rows = []
    for a in accounts:
        url = (a["urls"] or [""])[0]
        link = (
            f'<a href="{_e(url)}" rel="noreferrer noopener" target="_blank">{_e(url)}</a>'
            if url.startswith("http")
            else _e(url)
        )
        flags = (
            " · <span class='bad'>underground</span>" if a.get("underground") else ""
        ) + (" · same avatar" if a.get("avatar_match") else "")
        rows.append(
            f"<tr><td><span class='pill {a['confidence']}'>{a['confidence']}</span> {a['score']}</td>"
            f"<td>{_e(a['platform'])}{flags}</td><td>{_e(a['handle'])}</td><td>{_e(', '.join(a['sources']))}</td><td>{link}</td></tr>"
        )
    ident = []
    for key in (
        "name",
        "email",
        "phone",
        "username",
        "location",
        "organization",
        "wallet",
        "url",
    ):
        for r in (rep.get("identity", {}).get(key) or [])[:12]:
            ident.append(
                f"<tr><td>{key}</td><td>{_e(r['value'])}</td><td>{r['score']}</td><td>{_e(', '.join(r['sources']))}</td></tr>"
            )
    expo = "".join(
        f"<tr><td class='bad'>{_e(r['source'])}</td><td>{_e(', '.join(r['selectors']))}</td></tr>"
        for r in rep.get("exposure", [])
    )
    avatars = "".join(
        "<tr><td class='thumbs'>"
        + "".join(
            f'<img src="{_e(p)}" alt="" loading="lazy" referrerpolicy="no-referrer">'
            for p in m["pictures"][:6]
        )
        + f"</td><td>{_e(' = '.join(f'{p}/{h}' for p, h in m['accounts']))}</td><td>{m['distance']}/64</td></tr>"
        for m in rep.get("avatar_matches", [])
    )
    timeline = "".join(
        f"<tr><td>{_e(str(e.get('date'))[:19])}</td><td>{_e(e.get('module'))}</td><td>{_e(e.get('action'))}</td></tr>"
        for e in case["timeline"][-200:]
    )
    status = "".join(
        f"<tr><td>{_e(m)}</td><td>{_e(p)}</td><td class='{'confirmed' if v['status'] == 'OK' else 'bad' if v['status'] == 'Fail' else 'candidate'}'>"
        f"{v['status']}</td><td>{_e(v['reason'])}</td></tr>"
        for m, params in sorted(case["modules"].items())
        for p, v in params.items()
    )

    def table(head, body):
        if not body:
            return "<p class='meta'>—</p>"
        return f"<div class='wrap'><table><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr>{body}</table></div>"

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Veiled Eye case: {_e(case["target"])}</title>
<style>{_CSS}</style></head><body><main>
<h1>Identity investigation: {_e(case["target"])}</h1>
<div class="meta">Generated {_e(case["generated"])} · {_e(case["tool"])}<br>Evidence SHA-256: {case["evidence_sha256"]}</div>
<h2>Summary</h2><div class="cards">
<div class="card"><b class="confirmed">{counts["confirmed"]}</b>confirmed accounts</div>
<div class="card"><b class="likely">{counts["likely"]}</b>likely accounts</div>
<div class="card"><b>{counts["candidate"]}</b>candidates</div>
<div class="card"><b>{ok_mods}</b>sources with data</div>
<div class="card"><b class="bad">{len(rep.get("exposure", []))}</b>exposure sources</div>
<div class="card"><b>{len(rep.get("avatar_matches", []))}</b>avatar matches</div></div>
<h2>Accounts</h2>{table(["Confidence", "Platform", "Handle", "Sources", "URL"], "".join(rows))}
<h2>Identity attributes</h2>{table(["Type", "Value", "Score", "Sources"], "".join(ident))}
<h2>Same profile picture</h2>{table(["Pictures", "Accounts", "Distance"], avatars)}
<h2>Exposure</h2>{table(["Source", "Selectors"], expo)}
<h2>Timeline</h2>{table(["Date", "Module", "Event"], timeline)}
<h2>Module status</h2>{table(["Module", "Selector", "Status", "Detail"], status)}
</main></body></html>"""
    return doc.encode()


# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------
_PDF_FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold"}


def _pdf_fonts() -> dict:
    """DejaVu Sans (bundled) covers Turkish and most Latin/Cyrillic text."""
    from pathlib import Path

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _PDF_FONTS["regular"] == "VE-Sans":
        return _PDF_FONTS
    here = Path(__file__).resolve().parent / "fonts"
    try:
        pdfmetrics.registerFont(TTFont("VE-Sans", str(here / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(
            TTFont("VE-Sans-Bold", str(here / "DejaVuSans-Bold.ttf"))
        )
        pdfmetrics.registerFontFamily("VE-Sans", normal="VE-Sans", bold="VE-Sans-Bold")
        _PDF_FONTS.update(regular="VE-Sans", bold="VE-Sans-Bold")
    except Exception:  # fonts missing: core fonts still render ASCII
        pass
    return _PDF_FONTS


def _logo_path() -> str | None:
    from pathlib import Path

    base = Path(__file__).resolve().parents[1]
    for cand in (
        base / "frontend_dist" / "assets" / "images" / "logo.png",
        base.parent / "tools" / "ui_build" / "assets" / "veiled-logo.png",
    ):
        if cand.is_file():
            return str(cand)
    return None


def to_pdf(case: dict) -> bytes:
    """A4 investigation report: cover band, summary figures, accounts,
    identity, places, activity, exposure, timeline and module status.

    Column widths are fixed (no auto-sizing) and long values wrap inside
    their cell, so the layout never shifts with the data."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (
        CondPageBreak,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    fonts = _pdf_fonts()
    REG, BOLD = fonts["regular"], fonts["bold"]
    INK = colors.HexColor("#0f1b24")
    MUTED = colors.HexColor("#5f6f7b")
    LINE = colors.HexColor("#d5dee5")
    ACCENT = colors.HexColor("#1f8fc4")
    BAND = colors.HexColor("#07121a")
    ZEBRA = colors.HexColor("#f4f8fb")
    GRADE = {
        "confirmed": colors.HexColor("#0f8a5f"),
        "likely": colors.HexColor("#1f6fb8"),
        "candidate": colors.HexColor("#6b7782"),
    }

    W, H = A4
    M = 16 * mm
    CW = W - 2 * M  # content width

    body = ParagraphStyle(
        "b", fontName=REG, fontSize=8.6, leading=11.2, textColor=INK, alignment=TA_LEFT
    )
    small = ParagraphStyle("s", parent=body, fontSize=7.6, leading=9.6, textColor=MUTED)
    cell = ParagraphStyle("c", parent=body, fontSize=8, leading=10.2)
    head = ParagraphStyle(
        "h",
        parent=body,
        fontName=BOLD,
        fontSize=7.4,
        leading=9.4,
        textColor=colors.white,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=body,
        fontName=BOLD,
        fontSize=12.5,
        leading=16,
        textColor=INK,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=1,
    )
    kpi_n = ParagraphStyle(
        "kn", parent=body, fontName=BOLD, fontSize=17, leading=20, textColor=INK
    )
    kpi_l = ParagraphStyle("kl", parent=small, fontSize=7.2, leading=9)

    rep = case.get("report") or {}
    target = str(case.get("target", ""))
    accounts = rep.get("accounts", []) or []
    identity = rep.get("identity", {}) or {}
    grades = {g: sum(1 for a in accounts if a.get("confidence") == g) for g in GRADE}
    modules = case.get("modules", {}) or {}
    status_rows = [
        (m, p, info.get("status", ""), info.get("reason", ""))
        for m, per in sorted(modules.items())
        for p, info in sorted(per.items())
    ]
    ok_n = sum(1 for r in status_rows if r[2] == "OK")
    case_id = str(case.get("evidence_sha256", ""))[:12].upper()
    names = identity.get("name") or []
    subject = names[0]["value"] if names else target
    logo = _logo_path()

    def P(text, style=cell):
        return Paragraph(_e(text), style)

    def link(url, text=None):
        u = str(url or "")
        if not u.startswith(("http://", "https://")):
            return P(text or u)
        return Paragraph(
            f'<link href="{html.escape(u, quote=True)}" color="#1f6fb8">{_e(text or u)}</link>',
            cell,
        )

    def section(title, flow):
        bar = Table([[""]], colWidths=[CW], rowHeights=[1.2])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
        # heading + rule stay together; long tables split across pages
        # never leave a heading alone at the bottom of a page
        return [
            CondPageBreak(38 * mm),
            KeepTogether([Paragraph(_e(title), h2), bar, Spacer(1, 5)]),
            *flow,
        ]

    def table(headers, rows, widths_mm, empty="Nothing found."):
        if not rows:
            return [Paragraph(_e(empty), small), Spacer(1, 4)]
        widths = [w * mm for w in widths_mm]
        scale = CW / sum(widths)
        widths = [w * scale for w in widths]
        data = [[Paragraph(_e(h).upper(), head) for h in headers], *rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BAND),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ]
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
        t.setStyle(TableStyle(style))
        return [t, Spacer(1, 6)]

    # --- page decoration ------------------------------------------------
    class Numbered(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total):
            n = self._pageNumber
            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(M, 12 * mm, W - M, 12 * mm)
            self.setFont(REG, 7)
            self.setFillColor(MUTED)
            self.drawString(
                M,
                8.5 * mm,
                f"Veiled Eye · Identity investigation report · Case {case_id} · Confidential",
            )
            self.drawRightString(W - M, 8.5 * mm, f"Page {n} of {total}")
            if n > 1:
                self.setFillColor(BAND)
                self.rect(0, H - 11 * mm, W, 11 * mm, stroke=0, fill=1)
                if logo:
                    self.drawImage(
                        logo, M, H - 9.4 * mm, 7.8 * mm, 7.8 * mm, mask="auto"
                    )
                self.setFillColor(colors.white)
                self.setFont(BOLD, 8.5)
                self.drawString(M + 11 * mm, H - 6.8 * mm, "VEILED EYE")
                self.setFont(REG, 8)
                self.setFillColor(colors.HexColor("#9fd8f0"))
                self.drawRightString(W - M, H - 6.8 * mm, target[:80])

    def cover(c, _doc):
        band = 62 * mm
        c.saveState()
        c.setFillColor(BAND)
        c.rect(0, H - band, W, band, stroke=0, fill=1)
        c.setFillColor(ACCENT)
        c.rect(0, H - band, W, 1.6, stroke=0, fill=1)
        if logo:
            c.drawImage(logo, M, H - band + 14 * mm, 34 * mm, 34 * mm, mask="auto")
        x = M + 42 * mm
        c.setFillColor(colors.HexColor("#4fd2ff"))
        c.setFont(BOLD, 9)
        c.drawString(x, H - 18 * mm, "IDENTITY INVESTIGATION REPORT")
        c.setFillColor(colors.white)
        c.setFont(BOLD, 22)
        title = subject if len(subject) <= 34 else subject[:33] + "…"
        c.drawString(x, H - 29 * mm, title)
        c.setFont(REG, 9.5)
        c.setFillColor(colors.HexColor("#c8d6df"))
        c.drawString(x, H - 37 * mm, f"Target: {target[:70]}")
        c.drawString(
            x,
            H - 43 * mm,
            f"Generated: {str(case.get('generated', ''))[:19].replace('T', ' ')} UTC",
        )
        c.drawString(
            x,
            H - 49 * mm,
            f"Case {case_id}  ·  {ok_n} of {len(status_rows)} sources answered",
        )
        c.restoreState()

    story: list = [Spacer(1, 52 * mm)]

    # --- summary figures ----------------------------------------------------
    def kpi(n, label):
        return [Paragraph(str(n), kpi_n), Paragraph(_e(label).upper(), kpi_l)]

    ids = identity
    figures = [
        kpi(len(accounts), "accounts"),
        kpi(grades["confirmed"], "confirmed"),
        kpi(grades["likely"], "likely"),
        kpi(len(ids.get("email") or []), "e-mails"),
        kpi(len(ids.get("phone") or []), "phones"),
        kpi(len(case.get("places") or []), "places"),
    ]
    kt = Table([figures], colWidths=[CW / 6] * 6)
    kt.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LINEAFTER", (0, 0), (-2, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story += [kt, Spacer(1, 6)]
    act = case.get("activity") or {}
    summary = (
        f"{_e(subject)} — {len(accounts)} accounts were found across the sources checked, "
        f"{grades['confirmed']} of them confirmed by several independent sources or by the platform itself."
    )
    if act.get("estimate"):
        summary += f" Likely time zone: <b>{_e(act['estimate'])}</b> ({_e(act.get('basis', ''))})."
    story += [Paragraph(summary, body), Spacer(1, 4)]
    story.append(
        Paragraph(
            "Confidence: <b>confirmed</b> = three or more sources, or the platform's own data; "
            "<b>likely</b> = two sources or the same profile picture; <b>candidate</b> = one source only "
            "(a matching username is not proof of identity).",
            small,
        )
    )

    # --- accounts -------------------------------------------------------------
    acc_rows = []
    strong = [
        a
        for a in accounts
        if a.get("confidence") in ("confirmed", "likely") or a.get("underground")
    ]
    weak = [a for a in accounts if a not in strong]
    for a in strong:
        g = a.get("confidence", "candidate")
        badge = Paragraph(
            f'<font color="{GRADE.get(g, MUTED).hexval().replace("0x", "#")}"><b>{_e(g)}</b></font>'
            f'<br/><font size="6.8" color="#5f6f7b">{a.get("score", 0)} source(s)</font>',
            cell,
        )
        url = (a.get("urls") or [""])[0]
        plat = a.get("platform", "")
        if a.get("underground"):
            plat += " ⚠"
        acc_rows.append(
            [
                badge,
                P(plat),
                P(a.get("handle", "")),
                P(", ".join(a.get("sources", []))),
                link(url),
            ]
        )
    story += section(
        "Accounts",
        table(
            ["Confidence", "Platform", "Handle", "Found by", "Link"],
            acc_rows,
            [24, 32, 32, 40, 50],
            empty="No account is supported by more than one source.",
        ),
    )
    if weak:
        # single-source hits: compact, three per row
        cells = []
        for a in weak:
            url = (a.get("urls") or [""])[0]
            txt = f"{a.get('platform', '')} · {a.get('handle', '')}"
            cells.append(link(url, txt) if str(url).startswith("http") else P(txt))
        rows = [cells[i : i + 3] for i in range(0, len(cells), 3)]
        rows[-1] += [P("")] * (3 - len(rows[-1]))
        t = Table(rows, colWidths=[CW / 3] * 3)
        t.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                ]
            )
        )
        story += section(
            f"Single-source hits ({len(weak)})",
            [
                Paragraph(
                    "Each reported by one source only: leads to verify, not findings.",
                    small,
                ),
                Spacer(1, 4),
                t,
                Spacer(1, 6),
            ],
        )

    # --- identity -----------------------------------------------------------------
    label = {
        "name": "Name",
        "email": "E-mail",
        "phone": "Phone",
        "username": "Username",
        "location": "Location",
        "organization": "Organisation",
        "wallet": "Wallet",
        "url": "Website",
    }
    id_rows = [
        [
            P(label[k]),
            P(r["value"]),
            P(str(r.get("score", ""))),
            P(", ".join(r.get("sources", []))),
        ]
        for k in label
        for r in (identity.get(k) or [])[:12]
    ]
    story += section(
        "Identity attributes",
        table(["Type", "Value", "Count", "Reported by"], id_rows, [24, 68, 16, 70]),
    )

    # --- places ---------------------------------------------------------------------
    pl_rows = [
        [
            P(p.get("name") or "—"),
            P(p.get("kind", "")),
            link(
                f"https://www.openstreetmap.org/?mlat={p['lat']}&mlon={p['lng']}#map=12/{p['lat']}/{p['lng']}",
                f"{float(p['lat']):.4f}, {float(p['lng']):.4f}",
            ),
            P(p.get("source", "")),
        ]
        for p in (case.get("places") or [])[:40]
        if p.get("lat") is not None
    ]
    story += section(
        "Places",
        table(["Place", "Kind", "Coordinates", "Source"], pl_rows, [60, 30, 46, 42]),
    )

    # --- avatar re-use + exposure ------------------------------------------------------
    av_rows = [
        [
            P(" = ".join(f"{p}/{h}" for p, h in m.get("accounts", []))),
            P(f"{m.get('distance', '')}/64"),
        ]
        for m in rep.get("avatar_matches", [])
    ]
    if av_rows:
        story += section(
            "Same profile picture",
            table(["Accounts", "Hash distance"], av_rows, [150, 28]),
        )
    ex_rows = [
        [P(r["source"]), P(", ".join(r.get("selectors", [])))]
        for r in rep.get("exposure", [])
    ]
    if ex_rows:
        story += section("Exposure", table(["Source", "Selectors"], ex_rows, [50, 128]))

    # --- timeline ---------------------------------------------------------------------
    tl_rows = [
        [P(str(e.get("date", ""))[:19]), P(e.get("module", "")), P(e.get("action", ""))]
        for e in (case.get("timeline") or [])[-150:]
    ]
    story += section(
        "Timeline", table(["Date", "Module", "Event"], tl_rows, [34, 26, 118])
    )

    # --- module status --------------------------------------------------------------
    st_color = {"OK": "#0f8a5f", "Warning": "#a86b00", "Fail": "#b3263e"}
    st_rows = [
        [
            P(m),
            P(p),
            Paragraph(
                f'<font color="{st_color.get(st, "#5f6f7b")}"><b>{_e(st)}</b></font>',
                cell,
            ),
            P(reason[:180]),
        ]
        for m, p, st, reason in status_rows
    ]
    story += section(
        "Sources checked",
        table(["Module", "Selector", "Status", "Detail"], st_rows, [28, 44, 18, 88]),
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Evidence SHA-256: {case.get('evidence_sha256', '')}. The hash covers every raw module result "
            "this report was built from; keep the JSON export to verify it. Public sources only.",
            small,
        )
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=M,
        rightMargin=M,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Veiled Eye report — {target}",
        author="Veiled Eye",
        subject="Identity investigation report",
    )
    doc.build(story, onFirstPage=cover, canvasmaker=Numbered)
    return buf.getvalue()


RENDER = {
    "json": to_json,
    "html": to_html,
    "pdf": to_pdf,
    "stix": to_stix,
    "graphml": to_graphml,
    "csv": to_csv,
}


def render(case: dict, fmt: str) -> bytes:
    if fmt not in RENDER:
        raise ValueError(f"unknown format {fmt!r} (use: {', '.join(RENDER)})")
    return RENDER[fmt](case)
