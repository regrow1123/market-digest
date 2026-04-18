from pathlib import Path

from market_digest.fetchers.hankyung import parse_list

FIXTURE = Path(__file__).parent / "fixtures" / "hankyung_list.html"


def test_parse_list_returns_expected_report_count():
    html = FIXTURE.read_text(encoding="utf-8", errors="ignore")
    reports = parse_list(html)
    assert len(reports) == 10


def test_parse_list_first_report_fields():
    html = FIXTURE.read_text(encoding="utf-8", errors="ignore")
    first = parse_list(html)[0]
    assert first.date == "2026-04-17"
    assert first.category == "기업"
    assert first.report_idx == "648548"
    assert "코스모신소재" in first.title
    assert first.author == "백영찬"
    assert first.firm == "상상인증권"
    assert first.url.startswith("https://consensus.hankyung.com/analysis/downpdf?report_idx=")


def test_parse_list_all_reports_have_required_fields():
    html = FIXTURE.read_text(encoding="utf-8", errors="ignore")
    reports = parse_list(html)
    for r in reports:
        assert r.report_idx.isdigit()
        assert r.date
        assert r.title
        assert r.firm
