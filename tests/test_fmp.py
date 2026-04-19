import json
from pathlib import Path
from unittest.mock import patch

from market_digest.fetchers.fmp import _filter_records, fetch_and_save


def test_filter_keeps_initiate_regardless_of_target_change():
    records = [
        {"symbol": "AAPL", "action": "initiate", "newGrade": "Buy",
         "previousGrade": "", "gradingCompany": "MS", "publishedDate": "2026-04-20 12:00:00",
         "priceWhenPosted": 150.0, "priceTarget": 170.0, "previousPriceTarget": None,
         "newsURL": "https://example.com/a", "newsTitle": "t"},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert len(kept) == 1


def test_filter_drops_below_mcap_floor():
    records = [
        {"symbol": "TINY", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 5.0, "priceTarget": 8.0, "previousPriceTarget": 6.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"TINY": 500_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert kept == []


def test_filter_drops_small_target_moves_on_non_initiate():
    records = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 150.0, "priceTarget": 155.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert kept == []


def test_filter_keeps_large_target_moves():
    records = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert len(kept) == 1


def test_fetch_and_save_writes_yaml_txt(tmp_path):
    rows = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "Morgan Stanley",
         "publishedDate": "2026-04-20 06:30:00",
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "https://x.com/r", "newsTitle": "MS upgrades AAPL"},
    ]
    profiles = {"AAPL": {"mktCap": 2_000_000_000_000, "companyName": "Apple Inc."}}

    with patch("market_digest.fetchers.fmp._fetch_feed", return_value=rows), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            target_change_threshold=0.10,
            page_limit=1,
            request_interval_sec=0,
        )
    assert n == 1
    out = list(tmp_path.glob("fmp_*.txt"))
    assert len(out) == 1
    content = out[0].read_text(encoding="utf-8")
    assert "ticker: \"AAPL\"" in content
    assert "firm: \"Morgan Stanley\"" in content
    assert "target: \"150.0 -> 180.0\"" in content
    assert "Rating: Hold -> Buy" in content


def test_fetch_and_save_filters_by_date(tmp_path):
    rows = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "MS",
         "publishedDate": "2026-04-19 06:30:00",  # different date
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    profiles = {"AAPL": {"mktCap": 2_000_000_000_000, "companyName": "Apple Inc."}}
    with patch("market_digest.fetchers.fmp._fetch_feed", return_value=rows), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            target_change_threshold=0.10,
            page_limit=1,
            request_interval_sec=0,
        )
    assert n == 0
