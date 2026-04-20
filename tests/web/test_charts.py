from unittest.mock import patch

from market_digest.web.charts import fetch_kr_ohlc


def _fake_resp(status: int, body_bytes: bytes):
    class R:
        status_code = status
        content = body_bytes
    return R()


SAMPLE_XML = b"""<?xml version="1.0" encoding="EUC-KR" ?>
<protocol>
  <chartdata symbol="005930" count="3" timeframe="day">
    <item data="20251024|97900|99000|97700|98800|18801925" />
    <item data="20251027|101300|102000|100600|102000|22169970" />
    <item data="20251028|100900|101000|99100|99500|20002282" />
  </chartdata>
</protocol>"""


def test_fetch_parses_bars():
    with patch("market_digest.web.charts.requests.get",
               return_value=_fake_resp(200, SAMPLE_XML)):
        bars = fetch_kr_ohlc("005930", count=3)
    assert len(bars) == 3
    assert bars[0] == {"time": "2025-10-24", "open": 97900, "high": 99000,
                       "low": 97700, "close": 98800, "volume": 18801925}


def test_fetch_returns_empty_on_http_error():
    with patch("market_digest.web.charts.requests.get",
               return_value=_fake_resp(500, b"")):
        assert fetch_kr_ohlc("005930") == []


def test_fetch_returns_empty_on_exception():
    with patch("market_digest.web.charts.requests.get",
               side_effect=__import__("requests").RequestException("boom")):
        assert fetch_kr_ohlc("005930") == []


def test_fetch_skips_malformed_rows():
    body = b"""<protocol><chartdata>
      <item data="20251024|97900|99000|97700|98800|18801925" />
      <item data="badrow" />
      <item data="20251028|100900|101000|99100|99500|20002282" />
    </chartdata></protocol>"""
    with patch("market_digest.web.charts.requests.get",
               return_value=_fake_resp(200, body)):
        bars = fetch_kr_ohlc("005930")
    assert len(bars) == 2
