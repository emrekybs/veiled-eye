"""Domain profile: RDAP, DNS and certificate transparency (mocked)."""

from unittest.mock import MagicMock, patch

from modules.domaininfo import domaininfo_tasks as dom


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


RDAP = {
    "events": [{"eventAction": "registration", "eventDate": "2015-03-01T10:00:00Z"}],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["fn", {}, "text", "Example Registrar"]]],
        },
        {
            "roles": ["registrant"],
            "vcardArray": [
                "vcard",
                [
                    ["org", {}, "text", "Acme Ltd"],
                    ["adr", {}, "text", ["", "", "", "", "", "", "TR"]],
                ],
            ],
        },
    ],
}
CRT = [
    {"name_value": "mail.acme.com\n*.acme.com", "not_before": "2016-01-01T00:00:00"},
    {"name_value": "vpn.acme.com", "not_before": "2018-01-01T00:00:00"},
]


def test_domain_profile():
    def get(url, **kw):
        return _resp(200, RDAP) if "rdap" in url else _resp(200, CRT)

    dns_info = {
        "mx": ["aspmx.l.google.com"],
        "provider": "Google Workspace",
        "spf": "v=spf1",
        "dmarc": "",
        "ns": ["ns1.acme.com"],
    }
    with (
        patch.object(dom.requests, "get", side_effect=get),
        patch.object(dom, "dns_records", return_value=dns_info),
    ):
        out = dom.t_domaininfo("john@Acme.com", dev_mode=False)
    raw = next(e["raw"] for e in out if "raw" in e)
    assert raw["domain"] == "acme.com"
    assert raw["rdap"]["org"] == "Acme Ltd" and raw["rdap"]["country"] == "TR"
    assert raw["certificates"]["subdomains"] == ["mail.acme.com", "vpn.acme.com"]
    assert {"organization": "Acme Ltd"} in next(
        e["profile"] for e in out if "profile" in e
    )


def test_chain_runs_domaininfo_for_corporate_mail_only():
    from factories import chain

    def tasks(email):
        res = [
            {"module": "holehe"},
            {"param": email},
            {"validation": "hard"},
            {"raw": []},
            {"graphic": []},
            {"profile": []},
            {"timeline": []},
        ]
        return {t["module"] for t in chain.next_tasks(res)}

    assert "domaininfo" in tasks("john@acme.com")
    assert "domaininfo" not in tasks("john@gmail.com")
