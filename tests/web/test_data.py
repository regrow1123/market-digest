import json
from pathlib import Path

from market_digest.models import Digest
from market_digest.web.data import (
    build_cards_index,
    find_item,
    flat_ids,
    list_dates,
    load_digest,
    prev_next,
    research_md_path,
)


def _write(nas: Path, date: str, groups: list[dict]) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


def test_list_dates_sorted_ascending_and_excludes_non_date_dirs(tmp_path):
    _write(tmp_path, "2026-04-18", [])
    _write(tmp_path, "2026-04-19", [])
    _write(tmp_path, "2026-04-17", [])
    # stray site/ dir should NOT leak in
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "cards.json").write_text("[]", encoding="utf-8")

    assert list_dates(tmp_path) == ["2026-04-17", "2026-04-18", "2026-04-19"]


def test_list_dates_empty(tmp_path):
    assert list_dates(tmp_path) == []


def test_load_digest_returns_none_when_missing(tmp_path):
    assert load_digest(tmp_path, "2026-04-20") is None


def test_load_digest_parses_valid_file(tmp_path):
    _write(tmp_path, "2026-04-19", [])
    d = load_digest(tmp_path, "2026-04-19")
    assert isinstance(d, Digest)
    assert d.date == "2026-04-19"


def test_load_digest_returns_none_on_corrupt_file(tmp_path):
    p = tmp_path / "2026" / "04" / "2026-04-19.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ not json", encoding="utf-8")
    assert load_digest(tmp_path, "2026-04-19") is None


def test_prev_next_middle():
    dates = ["2026-04-17", "2026-04-18", "2026-04-19"]
    assert prev_next(dates, "2026-04-18") == ("2026-04-17", "2026-04-19")


def test_prev_next_ends():
    dates = ["2026-04-17", "2026-04-18", "2026-04-19"]
    assert prev_next(dates, "2026-04-17") == (None, "2026-04-18")
    assert prev_next(dates, "2026-04-19") == ("2026-04-18", None)


def test_prev_next_missing_date():
    assert prev_next(["2026-04-17"], "2026-04-20") == (None, None)


def test_find_item_by_id(tmp_path):
    _write(tmp_path, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [
             {"id": "us-rating-0", "headline": "h", "body_md": "b"},
             {"id": "us-rating-1", "headline": "h", "body_md": "b"},
         ]},
    ])
    d = load_digest(tmp_path, "2026-04-19")
    found = find_item(d, "us-rating-1")
    assert found is not None
    gi, ii, item = found
    assert gi == 0 and ii == 1 and item.id == "us-rating-1"
    assert find_item(d, "does-not-exist") is None


def test_flat_ids_preserves_group_order(tmp_path):
    _write(tmp_path, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "x", "body_md": "-"},
                   {"id": "kr-company-1", "headline": "x", "body_md": "-"}]},
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "x", "body_md": "-"}]},
    ])
    d = load_digest(tmp_path, "2026-04-19")
    assert flat_ids(d) == ["kr-company-0", "kr-company-1", "us-rating-0"]


def test_research_md_path_shape(tmp_path):
    p = research_md_path(tmp_path, "AAPL", "2026-04-17")
    assert p == tmp_path / "research" / "AAPL-2026-04-17.md"
    assert research_md_path(tmp_path, None, "2026-04-17") is None
    # also handles lowercased input
    assert research_md_path(tmp_path, "aapl", "2026-04-17") == tmp_path / "research" / "AAPL-2026-04-17.md"


def test_build_cards_index_flattens_desc_with_blurb(tmp_path):
    _write(tmp_path, "2026-04-18", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "old", "body_md": "x",
                    "ticker": "AAPL", "name": "Apple", "company_blurb": "스마트폰"}]},
    ])
    _write(tmp_path, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "new", "body_md": "y",
                    "ticker": "005930", "name": "삼성전자"}]},
    ])
    index = build_cards_index(tmp_path)
    assert [e["date"] for e in index] == ["2026-04-19", "2026-04-18"]
    assert index[1]["company_blurb"] == "스마트폰"
    assert "body_md" not in index[0]
