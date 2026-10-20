"""DNS lookups over HTTPS (Google Public DNS JSON API). Passive and proxy-friendly."""
from __future__ import annotations

import logging
from functools import lru_cache

import requests

log = logging.getLogger(__name__)
TYPES = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28, "CAA": 257}


failures = 0  # lookups that failed, as opposed to answering "no such record"; compare before and after a pass


@lru_cache(maxsize=4096)
def _resolve(name: str, rtype: str) -> tuple:
    global failures
    try:
        r = requests.get("https://dns.google/resolve", params={"name": name, "type": rtype}, timeout=10)
        j = r.json()
    except Exception as e:
        log.info("DoH %s %s failed: %s", name, rtype, e)
        failures += 1
        return ()
    if j.get("Status") not in (0, 3, None):  # 0 NOERROR, 3 NXDOMAIN; anything else (SERVFAIL…) is a failed lookup
        failures += 1
        return ()
    want = TYPES.get(rtype)
    out = []
    for a in j.get("Answer") or []:
        if want and a.get("type") != want:
            continue
        d = a.get("data", "")
        if rtype == "TXT":
            d = d.strip('"').replace('" "', "")
        out.append(d.rstrip(".") if rtype in ("CNAME", "NS", "MX", "PTR") else d)
    return tuple(out)


def query(name: str, rtype: str) -> list[str]:
    return list(_resolve(name.lower().rstrip("."), rtype))


def cname_chain(name: str) -> list[str]:
    """Follow CNAMEs (Google DNS returns the chain inside the A answer)."""
    try:
        j = requests.get("https://dns.google/resolve", params={"name": name, "type": "A"}, timeout=10).json()
    except Exception:
        return []
    return [a["data"].rstrip(".") for a in j.get("Answer") or [] if a.get("type") == 5]


def clear():
    _resolve.cache_clear()
