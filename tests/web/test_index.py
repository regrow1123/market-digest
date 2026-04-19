from market_digest.models import Digest
from market_digest.web.builder import build_index


def _digest(date: str, items: list[dict]) -> Digest:
    return Digest.model_validate(
        {
            "date": date,
            "groups": [
                {
                    "region": "kr",
                    "category": "company",
                    "title": "국내 기업리포트",
                    "items": items,
                }
            ],
        }
    )


def test_index_flattens_across_dates_in_descending_order():
    d1 = _digest("2026-04-18", [{"id": "kr-company-0", "headline": "a", "body_md": "x"}])
    d2 = _digest("2026-04-19", [{"id": "kr-company-0", "headline": "b", "body_md": "y"}])

    entries = build_index([d1, d2])

    assert [e.date for e in entries] == ["2026-04-19", "2026-04-18"]


def test_index_excludes_body_md():
    d = _digest(
        "2026-04-19",
        [
            {
                "id": "kr-company-0",
                "headline": "HBM",
                "body_md": "detail that should not leak",
                "house": "미래에셋",
                "ticker": "005930",
                "name": "삼성전자",
                "opinion": "Buy",
                "target": "85→95k",
            }
        ],
    )
    entries = build_index([d])
    dumped = entries[0].model_dump()
    assert "body_md" not in dumped
    assert dumped["name"] == "삼성전자"
    assert dumped["ticker"] == "005930"


def test_index_empty_when_no_items():
    d = Digest.model_validate({"date": "2026-04-19", "groups": []})
    assert build_index([d]) == []
