"""Korean stock OHLCV fetcher (Naver).

Naver's public chart XML endpoint returns daily OHLCV bars in EUC-KR.
This module is a thin, mockable wrapper with a clean dict output.
"""
from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

_URL = "https://fchart.stock.naver.com/sise.nhn"
_ITEM_RE = re.compile(r'data="([0-9|]+)"')


def fetch_kr_ohlc(ticker: str, count: int = 120, timeframe: str = "day") -> list[dict]:
    """Fetch Naver OHLCV bars. Returns empty list on any failure.

    Each bar: {"time": "YYYY-MM-DD", "open": int, "high": int, "low": int,
                "close": int, "volume": int}.
    """
    try:
        resp = requests.get(
            _URL,
            params={"symbol": ticker, "timeframe": timeframe,
                    "count": count, "requestType": 0},
            headers={"User-Agent": "market-digest/0.1",
                     "Referer": "https://finance.naver.com/"},
            timeout=15,
        )
    except requests.RequestException as exc:
        log.warning("naver chart: request failed for %s: %s", ticker, exc)
        return []
    if resp.status_code != 200:
        log.warning("naver chart: %s returned %s", ticker, resp.status_code)
        return []
    # Naver returns EUC-KR; requests will guess wrong. Use response bytes.
    text = resp.content.decode("euc-kr", errors="replace")
    bars: list[dict] = []
    for m in _ITEM_RE.finditer(text):
        parts = m.group(1).split("|")
        if len(parts) < 6:
            continue
        try:
            d = parts[0]
            bars.append({
                "time": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
                "open": int(parts[1]),
                "high": int(parts[2]),
                "low": int(parts[3]),
                "close": int(parts[4]),
                "volume": int(parts[5]),
            })
        except (ValueError, IndexError):
            continue
    return bars
