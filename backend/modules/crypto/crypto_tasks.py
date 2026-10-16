#!/usr/bin/env python
"""Crypto module — wallet profile from keyless public explorers.

Accepts one or more addresses (comma separated); the chain is detected and
checksum-validated (``factories/identity.wallet_chain``).

  bitcoin   mempool.space        litecoin  litecoinspace.org
  ethereum  eth.blockscout.com   (ENS name + public tags = identity)
  tron      tronscan / trongrid  dogecoin  blockchair
  monero    validated only (no public ledger by design)

Per wallet: balance, total received / sent, tx count, first / last seen,
top counterparties (who the wallet transacts with most).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime

import requests
from factories.identity import split_multi, wallet_chain
from factories.output_builder import build_total, root_node
from factories.task_wrapper import module_task

UA = {"User-Agent": "VeiledEye-OSINT", "Accept": "application/json"}
SYMBOL = {
    "bitcoin": "BTC",
    "litecoin": "LTC",
    "ethereum": "ETH",
    "tron": "TRX",
    "dogecoin": "DOGE",
    "monero": "XMR",
}
EXPLORER = {
    "bitcoin": "https://mempool.space/address/{a}",
    "litecoin": "https://litecoinspace.org/address/{a}",
    "ethereum": "https://etherscan.io/address/{a}",
    "tron": "https://tronscan.org/#/address/{a}",
    "dogecoin": "https://blockchair.com/dogecoin/address/{a}",
    "monero": "",
}
ICON = {
    "bitcoin": "fab fa-bitcoin",
    "ethereum": "fab fa-ethereum",
    "monero": "fab fa-monero",
}


def _get(url: str, **params):
    resp = requests.get(url, params=params or None, headers=UA, timeout=25)
    if resp.status_code == 429:
        raise Exception("warn: Explorer rate limited")
    if resp.status_code in (400, 404):
        return None
    resp.raise_for_status()
    return resp.json()


def _iso(ts) -> str | None:
    try:
        ts = int(ts)
        if ts > 10**11:  # milliseconds
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _utxo(base: str, addr: str, unit: float = 1e8) -> dict:
    info = _get(f"{base}/api/address/{addr}")
    if not info:
        return {}
    cs = info.get("chain_stats") or {}
    txs = _get(f"{base}/api/address/{addr}/txs") or []
    peers: Counter = Counter()
    times = []
    for tx in txs:
        t = (tx.get("status") or {}).get("block_time")
        if t:
            times.append(t)
        for vin in tx.get("vin") or []:
            a = (vin.get("prevout") or {}).get("scriptpubkey_address")
            if a and a != addr:
                peers[a] += 1
        for vout in tx.get("vout") or []:
            a = vout.get("scriptpubkey_address")
            if a and a != addr:
                peers[a] += 1
    received, sent = cs.get("funded_txo_sum", 0), cs.get("spent_txo_sum", 0)
    return {
        "balance": (received - sent) / unit,
        "received": received / unit,
        "sent": sent / unit,
        "tx_count": cs.get("tx_count"),
        "first_seen": _iso(min(times)) if times else None,  # within last page
        "last_seen": _iso(max(times)) if times else None,
        "counterparties": [
            {"address": a, "count": c} for a, c in peers.most_common(10)
        ],
    }


def _ethereum(addr: str) -> dict:
    base = "https://eth.blockscout.com/api/v2/addresses"
    info = _get(f"{base}/{addr}")
    if not info:
        return {}
    counters = _get(f"{base}/{addr}/counters") or {}
    txs = (_get(f"{base}/{addr}/transactions") or {}).get("items") or []
    peers: Counter = Counter()
    times = []
    for tx in txs:
        if tx.get("timestamp"):
            times.append(tx["timestamp"])
        for side in ("from", "to"):
            h = (tx.get(side) or {}).get("hash")
            if h and h.lower() != addr.lower():
                peers[h] += 1
    tags = [
        t.get("display_name") or t.get("label")
        for t in info.get("public_tags") or []
        if isinstance(t, dict)
    ]
    tags += [
        t.get("name")
        for t in (info.get("metadata") or {}).get("tags") or []
        if isinstance(t, dict)
    ]
    return {
        "balance": int(info.get("coin_balance") or 0) / 1e18,
        "tx_count": int(counters.get("transactions_count") or 0) or None,
        "token_transfers": int(counters.get("token_transfers_count") or 0) or None,
        "ens": info.get("ens_domain_name"),
        "name": info.get("name"),
        "is_contract": info.get("is_contract"),
        "labels": [t for t in tags if t],
        "first_seen": min(times) if times else None,
        "last_seen": max(times) if times else None,
        "counterparties": [
            {"address": a, "count": c} for a, c in peers.most_common(10)
        ],
    }


def _tron(addr: str) -> dict:
    try:
        info = _get("https://apilist.tronscanapi.com/api/accountv2", address=addr)
    except Exception:
        info = None
    if info and info.get("address"):
        return {
            "balance": int(info.get("balance") or 0) / 1e6,
            "tx_count": info.get("totalTransactionCount"),
            "first_seen": _iso(info.get("date_created")),
            "last_seen": _iso(info.get("latest_operation_time")),
            "labels": [x for x in (info.get("addressTag"), info.get("name")) if x],
        }
    grid = (_get(f"https://api.trongrid.io/v1/accounts/{addr}") or {}).get("data") or []
    if not grid:
        return {}
    acc = grid[0]
    return {
        "balance": int(acc.get("balance") or 0) / 1e6,
        "first_seen": _iso(acc.get("create_time")),
        "last_seen": _iso(
            acc.get("latest_opration_time") or acc.get("latest_operation_time")
        ),
    }


def _dogecoin(addr: str) -> dict:
    data = (
        _get(f"https://api.blockchair.com/dogecoin/dashboards/address/{addr}") or {}
    ).get("data") or {}
    a = (data.get(addr) or {}).get("address") or {}
    if not a:
        return {}
    return {
        "balance": (a.get("balance") or 0) / 1e8,
        "received": (a.get("received") or 0) / 1e8,
        "sent": (a.get("spent") or 0) / 1e8,
        "tx_count": a.get("transaction_count"),
        "first_seen": a.get("first_seen_receiving"),
        "last_seen": a.get("last_seen_spending") or a.get("last_seen_receiving"),
    }


FETCH = {
    "bitcoin": lambda a: _utxo("https://mempool.space", a),
    "litecoin": lambda a: _utxo("https://litecoinspace.org", a),
    "ethereum": _ethereum,
    "tron": _tron,
    "dogecoin": _dogecoin,
    "monero": lambda a: {"note": "Monero ledger is private by design"},
}


def wallet_report(addr: str) -> dict:
    chain = wallet_chain(addr)
    if not chain:
        return {"address": addr, "chain": None, "valid": False}
    try:
        data = FETCH[chain](addr)
        error = None
    except Exception as exc:
        data, error = {}, str(exc).replace("warn: ", "")
    return {
        "address": addr,
        "chain": chain,
        "symbol": SYMBOL[chain],
        "valid": True,
        "explorer": EXPLORER[chain].format(a=addr),
        "found": bool(data),
        "error": error,
        **data,
    }


@module_task(module_name="crypto", dev_mode_sleep=2)
def p_crypto(param):
    """Task of Celery that profiles crypto wallet addresses."""
    addresses = list(dict.fromkeys(split_multi(param)))
    reports = [wallet_report(a) for a in addresses]
    valid = [r for r in reports if r["valid"]]
    if not valid:
        raise Exception("warn: No valid wallet address")

    gather = [
        root_node(
            "Crypto",
            param if len(param) < 60 else f"{len(valid)} wallets",
            "fas fa-wallet",
            f"{len(valid)} wallet(s)",
        )
    ]
    profile, timeline = (
        [
            {
                "wallet": [
                    {"currency": r["symbol"], "address": r["address"]} for r in valid
                ]
            }
        ],
        [],
    )
    for idx, r in enumerate(valid):
        amount = (
            f"{r.get('balance'):.8g} {r['symbol']}"
            if isinstance(r.get("balance"), int | float)
            else ""
        )
        gather.append(
            {
                "name-node": f"CW-{idx}",
                "title": f"{r['symbol']} {r['address'][:10]}…{r['address'][-6:]}",
                "subtitle": " · ".join(
                    x
                    for x in (
                        amount,
                        f"{r.get('tx_count')} tx" if r.get("tx_count") else "",
                        r.get("error") or "",
                    )
                    if x
                ),
                "icon": ICON.get(r["chain"], "fas fa-coins"),
                "link": "Crypto",
                "help": r.get("explorer") or "",
            }
        )
        for label in [r.get("ens"), r.get("name"), *(r.get("labels") or [])]:
            if label:
                gather.append(
                    {
                        "name-node": f"CW-{idx}-lbl-{label}",
                        "title": str(label),
                        "subtitle": "ENS / public label",
                        "icon": "fas fa-tag",
                        "link": "Crypto",
                    }
                )
        if r.get("ens"):
            profile.append({"username": r["ens"]})
        for cp in (r.get("counterparties") or [])[:5]:
            gather.append(
                {
                    "name-node": f"CW-{idx}-cp-{cp['address']}",
                    "title": f"{cp['address'][:10]}…{cp['address'][-6:]}",
                    "subtitle": f"counterparty · {cp['count']} tx",
                    "icon": "fas fa-exchange-alt",
                    "link": "Crypto",
                }
            )
        for key, label in (
            ("first_seen", "first activity"),
            ("last_seen", "last activity"),
        ):
            if r.get(key):
                timeline.append(
                    {
                        "date": str(r[key]),
                        "action": f"Crypto : {r['symbol']} wallet {label}",
                        "icon": ICON.get(r["chain"], "fas fa-coins"),
                    }
                )
    profile.append(
        {
            "presence": [
                {
                    "name": "crypto",
                    "children": [
                        {"name": r["symbol"], "value": r.get("tx_count") or 0}
                        for r in valid
                    ],
                }
            ]
        }
    )
    return build_total(
        module="crypto",
        param=param,
        validation="hard",
        raw={"wallets": reports},
        graphic=[{"crypto": gather}, {"wallets": reports}],
        profile=profile,
        timeline=timeline,
    )


t_crypto = p_crypto

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("addresses", help="one or more addresses, comma separated")
    print(json.dumps(t_crypto(ap.parse_args().addresses, dev_mode=False), indent=2))
