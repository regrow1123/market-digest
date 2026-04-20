from unittest.mock import patch

from market_digest.web.naver import resolve_overseas_url


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def setup_function(_):
    resolve_overseas_url.cache_clear()


def test_resolve_prefers_exact_code_match():
    payload = {"items": [
        {"code": "TSM", "reutersCode": "TSM", "category": "stock",
         "nationCode": "USA", "typeCode": "NYSE",
         "url": "/worldstock/stock/TSM/total"},
        {"code": "TSME", "reutersCode": "TSME.K", "category": "stock",
         "nationCode": "USA", "typeCode": "AMEX",
         "url": "/worldstock/etf/TSME.K"},
    ]}
    with patch("market_digest.web.naver.requests.get",
               return_value=FakeResp(200, payload)):
        url = resolve_overseas_url("TSM")
    assert url == "https://m.stock.naver.com/worldstock/stock/TSM/total"


def test_resolve_matches_reuters_code_prefix():
    payload = {"items": [
        {"code": "AAPL", "reutersCode": "AAPL.O", "category": "stock",
         "nationCode": "USA", "typeCode": "NASDAQ",
         "url": "/worldstock/stock/AAPL.O/total"},
    ]}
    with patch("market_digest.web.naver.requests.get",
               return_value=FakeResp(200, payload)):
        url = resolve_overseas_url("AAPL")
    assert url.endswith("/worldstock/stock/AAPL.O/total")


def test_resolve_falls_back_to_search_on_http_error():
    with patch("market_digest.web.naver.requests.get",
               return_value=FakeResp(500, {})):
        url = resolve_overseas_url("XYZ")
    assert url == "https://m.stock.naver.com/search?query=XYZ"


def test_resolve_falls_back_to_search_on_exception():
    with patch("market_digest.web.naver.requests.get",
               side_effect=__import__("requests").RequestException("boom")):
        url = resolve_overseas_url("XYZ")
    assert url == "https://m.stock.naver.com/search?query=XYZ"


def test_resolve_falls_back_to_search_when_no_us_match():
    payload = {"items": [
        {"code": "AAPL", "reutersCode": "AAPL.KS", "category": "stock",
         "nationCode": "KOR", "typeCode": "KOSPI", "url": "/unrelated"},
    ]}
    with patch("market_digest.web.naver.requests.get",
               return_value=FakeResp(200, payload)):
        url = resolve_overseas_url("AAPL")
    assert url == "https://m.stock.naver.com/search?query=AAPL"


def test_resolve_caches_results():
    payload = {"items": [
        {"code": "AAPL", "reutersCode": "AAPL.O", "category": "stock",
         "nationCode": "USA", "typeCode": "NASDAQ",
         "url": "/worldstock/stock/AAPL.O/total"},
    ]}
    with patch("market_digest.web.naver.requests.get",
               return_value=FakeResp(200, payload)) as m:
        a = resolve_overseas_url("AAPL")
        b = resolve_overseas_url("AAPL")
    assert a == b
    assert m.call_count == 1
