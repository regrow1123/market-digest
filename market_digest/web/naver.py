"""Naver Finance URL resolver for overseas (US) tickers.

Korean tickers use the stable `finance.naver.com/item/main.naver?code=...`
path directly. Overseas tickers have per-exchange suffixes that we resolve
via Naver's public autocomplete API with a simple in-process LRU cache.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import requests

log = logging.getLogger(__name__)

_AC_URL = "https://ac.stock.naver.com/ac"
_BASE = "https://m.stock.naver.com"
_FALLBACK = "https://m.stock.naver.com/search?query={q}"

_PREFERRED_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")


@lru_cache(maxsize=512)
def resolve_overseas_url(ticker: str) -> str:
    """Return an absolute Naver URL for a US-listed ticker.

    Falls back to the Naver search page URL on any failure so the user
    never hits a dead link.
    """
    t = ticker.strip().upper()
    if not t:
        return _FALLBACK.format(q="")
    try:
        resp = requests.get(
            _AC_URL,
            params={"q": t, "target": "stock", "alphabet": "false"},
            headers={"User-Agent": "market-digest/0.1"},
            timeout=10,
        )
        if resp.status_code != 200:
            log.warning("naver ac: %s returned %s", t, resp.status_code)
            return _FALLBACK.format(q=t)
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("naver ac: request failed for %s: %s", t, exc)
        return _FALLBACK.format(q=t)
    except ValueError:
        log.warning("naver ac: non-JSON response for %s", t)
        return _FALLBACK.format(q=t)

    items = data.get("items") or []
    candidates = [
        it for it in items
        if it.get("category") == "stock"
        and it.get("nationCode") == "USA"
        and (it.get("code") == t or (it.get("reutersCode") or "").split(".")[0] == t)
    ]
    if not candidates:
        return _FALLBACK.format(q=t)

    preferred = [it for it in candidates if it.get("typeCode") in _PREFERRED_EXCHANGES]
    picked = (preferred or candidates)[0]
    url_path = picked.get("url")
    if not url_path:
        return _FALLBACK.format(q=t)
    return f"{_BASE}{url_path}"
