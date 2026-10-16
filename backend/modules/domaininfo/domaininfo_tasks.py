#!/usr/bin/env python
"""Domain profile for corporate / own-domain e-mail addresses.

* RDAP (rdap.org): registrar, creation / expiry dates, registrant
  organisation and country when the registry publishes them
* DNS: MX (which mail provider the organisation uses), SPF / DMARC, NS
* crt.sh: certificate transparency — subdomains and when the domain first
  got a TLS certificate

All public, no key. Run automatically for e-mails whose domain is not a free
webmail provider.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime

import requests
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

LINK = "Domain"
TIMEOUT = 20
MX_PROVIDERS = {
    "google.com": "Google Workspace",
    "googlemail.com": "Google Workspace",
    "outlook.com": "Microsoft 365",
    "protection.outlook.com": "Microsoft 365",
    "zoho": "Zoho Mail",
    "yandex": "Yandex 360",
    "protonmail.ch": "Proton Mail",
    "mailgun.org": "Mailgun",
    "secureserver.net": "GoDaddy",
    "mimecast.com": "Mimecast",
    "pphosted.com": "Proofpoint",
    "icloud.com": "iCloud+",
    "messagingengine.com": "Fastmail",
    "yandex.net": "Yandex 360",
}


def _domain(param: str) -> str:
    d = str(param or "").strip().lower()
    d = d.split("@")[-1]
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", d):
        raise Exception(f"warn: '{param}' is not a domain or e-mail address")
    return d


def rdap(domain: str) -> dict:
    try:
        r = requests.get(f"https://rdap.org/domain/{domain}", timeout=TIMEOUT)
    except requests.RequestException:
        return {}
    if r.status_code != 200:
        return {}
    try:
        data = r.json()
    except ValueError:
        return {}
    out = {
        "events": {},
        "registrar": "",
        "org": "",
        "country": "",
        "status": data.get("status") or [],
    }
    for ev in data.get("events") or []:
        if ev.get("eventAction") and ev.get("eventDate"):
            out["events"][ev["eventAction"]] = ev["eventDate"]
    for ent in data.get("entities") or []:
        roles = ent.get("roles") or []
        vcard = (ent.get("vcardArray") or [None, []])[1]
        fields = {f[0]: f[3] for f in vcard if isinstance(f, list) and len(f) > 3}
        if "registrar" in roles:
            out["registrar"] = fields.get("fn") or out["registrar"]
        if "registrant" in roles:
            org = fields.get("org") or fields.get("fn") or ""
            if org and not re.search(
                r"redacted|privacy|proxy|withheld", str(org), re.I
            ):
                out["org"] = str(org)
            adr = fields.get("adr")
            if isinstance(adr, list) and adr and adr[-1]:
                out["country"] = str(adr[-1])
    return out


def dns_records(domain: str) -> dict:
    out = {"mx": [], "provider": "", "spf": "", "dmarc": "", "ns": []}
    try:
        import dns.resolver
    except ImportError:
        return out
    res = dns.resolver.Resolver()
    res.lifetime = 6

    def q(name, rtype):
        try:
            return [r.to_text() for r in res.resolve(name, rtype)]
        except Exception:
            return []

    mx = sorted(
        q(domain, "MX"),
        key=lambda s: int(s.split()[0]) if s.split()[0].isdigit() else 99,
    )
    out["mx"] = [m.split()[-1].rstrip(".") for m in mx]
    for host in out["mx"]:
        for key, name in MX_PROVIDERS.items():
            if key in host:
                out["provider"] = name
                break
        if out["provider"]:
            break
    if out["mx"] and not out["provider"]:
        out["provider"] = "self-hosted / other"
    out["spf"] = next((t.strip('"') for t in q(domain, "TXT") if "v=spf1" in t), "")
    out["dmarc"] = next(
        (t.strip('"') for t in q(f"_dmarc.{domain}", "TXT") if "v=DMARC1" in t), ""
    )
    out["ns"] = [n.rstrip(".") for n in q(domain, "NS")]
    return out


def certificates(domain: str, limit: int = 40) -> dict:
    try:
        r = requests.get(
            "https://crt.sh/", params={"q": f"%.{domain}", "output": "json"}, timeout=40
        )
        rows = r.json() if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        rows = []
    subs, first = set(), ""
    for row in rows:
        for name in str(row.get("name_value") or "").splitlines():
            name = name.strip().lower().lstrip("*.")
            if name.endswith(domain) and name != domain:
                subs.add(name)
        nb = str(row.get("not_before") or "")
        if nb and (not first or nb < first):
            first = nb
    return {"subdomains": sorted(subs)[:limit], "total": len(subs), "first_cert": first}


@module_task(module_name="domaininfo", dev_mode_sleep=3)
def p_domaininfo(param):
    domain = _domain(param)
    reg, dns_info, certs = rdap(domain), dns_records(domain), certificates(domain)
    if not reg and not dns_info["mx"] and not dns_info["ns"] and not certs["total"]:
        raise Exception(f"warn: No public data for {domain}")

    created = (reg.get("events") or {}).get("registration", "")
    gather = [root_node(LINK, domain, "fas fa-globe", dns_info["provider"] or "domain")]

    def node(key, title, value, icon):
        if value:
            gather.append(
                {
                    "name-node": f"DOM-{key}",
                    "title": title,
                    "subtitle": str(value),
                    "icon": icon,
                    "link": LINK,
                }
            )

    node("org", "Registrant", reg.get("org"), "fas fa-building")
    node("country", "Registrant country", reg.get("country"), "fas fa-flag")
    node("registrar", "Registrar", reg.get("registrar"), "fas fa-id-card")
    node("created", "Registered", created[:10], "fas fa-calendar-plus")
    node(
        "expires",
        "Expires",
        (reg.get("events") or {}).get("expiration", "")[:10],
        "fas fa-calendar-times",
    )
    node("mail", "Mail provider", dns_info["provider"], "fas fa-envelope")
    node("mx", "MX", ", ".join(dns_info["mx"][:3]), "fas fa-server")
    node("dmarc", "DMARC", dns_info["dmarc"][:80], "fas fa-shield-alt")
    node("ns", "Name servers", ", ".join(dns_info["ns"][:3]), "fas fa-network-wired")
    node(
        "certs",
        "Subdomains (certificates)",
        f"{certs['total']} · first cert {certs['first_cert'][:10]}"
        if certs["total"]
        else "",
        "fas fa-certificate",
    )
    for i, sub in enumerate(certs["subdomains"][:15]):
        gather.append(
            {
                "name-node": f"DOM-sub-{i}",
                "title": sub,
                "subtitle": "subdomain",
                "icon": "fas fa-sitemap",
                "link": LINK,
                "help": f"https://{sub}",
            }
        )

    profile = []
    if reg.get("org"):
        profile.append({"organization": reg["org"]})
    if reg.get("country"):
        profile.append({"location": reg["country"]})
    profile.append({"url": f"https://{domain}"})
    timeline = []
    if created:
        timeline.append(
            {
                "date": created[:19].replace("T", " "),
                "action": f"Domain : {domain} registered",
                "icon": "fa-globe",
            }
        )
    if certs["first_cert"]:
        timeline.append(
            {
                "date": certs["first_cert"][:19].replace("T", " "),
                "action": f"Domain : first TLS certificate for {domain}",
                "icon": "fa-certificate",
            }
        )

    return build_total(
        module="domaininfo",
        param=domain,
        validation="hard",
        raw={
            "domain": domain,
            "rdap": reg,
            "dns": dns_info,
            "certificates": certs,
            "checked": datetime.now().isoformat(timespec="seconds"),
        },
        graphic=[{"domaininfo": gather}],
        profile=profile,
        timeline=timeline,
    )


t_domaininfo = p_domaininfo

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("domain")
    print(json.dumps(t_domaininfo(ap.parse_args().domain, dev_mode=False), indent=2))
