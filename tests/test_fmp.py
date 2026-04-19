import json
from pathlib import Path
from unittest.mock import patch

from market_digest.fetchers.fmp import (
    _filter_grades,
    _filter_targets,
    fetch_and_save,
)


def test_filter_grades_drops_maintain():
    records = [
        {"symbol": "AAPL", "action": "maintain", "newGrade": "Buy",
         "previousGrade": "Buy", "gradingCompany": "X",
         "publishedDate": "2026-04-20", "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    assert _filter_grades(records, mcap, min_mcap=1_000_000_000) == []


def test_filter_grades_keeps_upgrade_downgrade_initiate():
    records = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X",
         "publishedDate": "2026-04-20", "newsURL": "", "newsTitle": ""},
        {"symbol": "MSFT", "action": "downgrade", "newGrade": "Hold",
         "previousGrade": "Buy", "gradingCompany": "Y",
         "publishedDate": "2026-04-20", "newsURL": "", "newsTitle": ""},
        {"symbol": "NVDA", "action": "initiate", "newGrade": "Buy",
         "previousGrade": None, "gradingCompany": "Z",
         "publishedDate": "2026-04-20", "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 3e12, "MSFT": 3e12, "NVDA": 3e12}
    kept = _filter_grades(records, mcap, min_mcap=1e9)
    assert len(kept) == 3


def test_filter_grades_drops_below_mcap_floor():
    records = [{"symbol": "TINY", "action": "upgrade", "newGrade": "Buy",
                "previousGrade": "Hold", "gradingCompany": "X",
                "publishedDate": "2026-04-20", "newsURL": "", "newsTitle": ""}]
    mcap = {"TINY": 500_000_000}
    assert _filter_grades(records, mcap, min_mcap=1_000_000_000) == []


def test_filter_targets_gates_on_mcap():
    records = [
        {"symbol": "AAPL", "priceTarget": 180, "publishedDate": "2026-04-20"},
        {"symbol": "TINY", "priceTarget": 10, "publishedDate": "2026-04-20"},
    ]
    mcap = {"AAPL": 3e12, "TINY": 5e8}
    kept = _filter_targets(records, mcap, min_mcap=1e9)
    assert len(kept) == 1
    assert kept[0]["symbol"] == "AAPL"


def test_fetch_and_save_writes_grade_and_target_files(tmp_path):
    grades = [{"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
               "previousGrade": "Hold", "gradingCompany": "Morgan Stanley",
               "publishedDate": "2026-04-20T06:30:00.000Z",
               "priceWhenPosted": 150.0,
               "newsURL": "https://x.com/g", "newsTitle": "MS upgrades AAPL"}]
    targets = [{"symbol": "AAPL", "priceTarget": 180, "adjPriceTarget": 180,
                "priceWhenPosted": 150.0,
                "publishedDate": "2026-04-20T06:30:00.000Z",
                "analystCompany": "Goldman Sachs", "analystName": "Jane",
                "newsURL": "https://x.com/t",
                "newsTitle": "AAPL target raised to $180 from $160 at GS"}]
    profiles = {"AAPL": {"marketCap": 2_000_000_000_000, "companyName": "Apple Inc."}}

    with patch("market_digest.fetchers.fmp._fetch_grades", return_value=grades), \
         patch("market_digest.fetchers.fmp._fetch_targets", return_value=targets), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            request_interval_sec=0,
        )
    assert n == 2
    grade_files = list(tmp_path.glob("fmp_grade_*.txt"))
    target_files = list(tmp_path.glob("fmp_target_*.txt"))
    assert len(grade_files) == 1
    assert len(target_files) == 1

    g_content = grade_files[0].read_text(encoding="utf-8")
    assert "ticker: \"AAPL\"" in g_content
    assert "firm: \"Morgan Stanley\"" in g_content
    assert "Rating: Hold -> Buy" in g_content
    assert "Action: upgrade" in g_content
    assert 'source: "fmp_grades"' in g_content

    t_content = target_files[0].read_text(encoding="utf-8")
    assert "ticker: \"AAPL\"" in t_content
    assert "firm: \"Goldman Sachs\"" in t_content
    assert "Target: 180" in t_content
    assert 'source: "fmp_targets"' in t_content


def test_fetch_and_save_filters_by_date(tmp_path):
    grades = [{"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
               "previousGrade": "Hold", "gradingCompany": "MS",
               "publishedDate": "2026-04-19T06:30:00.000Z",
               "priceWhenPosted": 150.0,
               "newsURL": "", "newsTitle": ""}]
    targets = []
    profiles = {"AAPL": {"marketCap": 2e12}}
    with patch("market_digest.fetchers.fmp._fetch_grades", return_value=grades), \
         patch("market_digest.fetchers.fmp._fetch_targets", return_value=targets), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            request_interval_sec=0,
        )
    assert n == 0


def test_fetch_and_save_skips_when_no_api_key(tmp_path):
    assert fetch_and_save(
        date="2026-04-20",
        inbox_dir=tmp_path,
        api_key="",
        min_market_cap_usd=1_000_000_000,
        request_interval_sec=0,
    ) == 0
