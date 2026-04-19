import json
from pathlib import Path

from bs4 import BeautifulSoup

from market_digest.web import build


def _write(nas: Path, date: str, groups: list[dict]) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


def _company_group(items: list[dict]) -> dict:
    return {"region": "kr", "category": "company", "title": "국내 기업리포트", "items": items}


def test_build_writes_expected_files(tmp_path):
    _write(tmp_path, "2026-04-19", [
        _company_group([{"id": "kr-company-0", "headline": "h", "body_md": "- b"}])
    ])

    site = build(tmp_path)

    assert (site / "index.html").is_file()
    assert (site / "2026-04-19.html").is_file()
    assert (site / "2026-04-19" / "kr-company-0.html").is_file()
    assert (site / "search.html").is_file()
    assert (site / "cards.json").is_file()
    assert (site / "assets" / "style.css").is_file()
    assert (site / "assets" / "search.js").is_file()


def test_build_index_is_newest_day(tmp_path):
    _write(tmp_path, "2026-04-18", [_company_group([{"id": "kr-company-0", "headline": "old", "body_md": "-"}])])
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "new", "body_md": "-"}])])

    site = build(tmp_path)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "new" in index
    assert "2026-04-19" in index


def test_build_prev_next_links(tmp_path):
    for d in ("2026-04-17", "2026-04-18", "2026-04-19"):
        _write(tmp_path, d, [_company_group([{"id": "kr-company-0", "headline": d, "body_md": "-"}])])

    site = build(tmp_path)
    middle = BeautifulSoup((site / "2026-04-18.html").read_text(encoding="utf-8"), "html.parser")
    assert middle.select_one("a.nav-prev")["href"] == "2026-04-17.html"
    assert middle.select_one("a.nav-next")["href"] == "2026-04-19.html"

    first = BeautifulSoup((site / "2026-04-17.html").read_text(encoding="utf-8"), "html.parser")
    assert first.select_one(".nav-prev.disabled") is not None

    last = BeautifulSoup((site / "2026-04-19.html").read_text(encoding="utf-8"), "html.parser")
    assert last.select_one(".nav-next.disabled") is not None


def test_build_empty_day_renders_message(tmp_path):
    _write(tmp_path, "2026-04-19", [])

    site = build(tmp_path)
    html = (site / "2026-04-19.html").read_text(encoding="utf-8")
    assert "오늘 수집된 리포트 없음" in html


def test_build_cards_json_excludes_body_md_and_sorts_desc(tmp_path):
    _write(tmp_path, "2026-04-18", [_company_group([{"id": "kr-company-0", "headline": "old", "body_md": "X"}])])
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "new", "body_md": "Y"}])])

    site = build(tmp_path)
    cards = json.loads((site / "cards.json").read_text(encoding="utf-8"))
    assert cards[0]["date"] == "2026-04-19"
    assert cards[1]["date"] == "2026-04-18"
    assert "body_md" not in cards[0]


def test_build_is_idempotent(tmp_path):
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "h", "body_md": "-"}])])

    site1 = build(tmp_path)
    first = (site1 / "2026-04-19.html").read_text(encoding="utf-8")

    site2 = build(tmp_path)
    second = (site2 / "2026-04-19.html").read_text(encoding="utf-8")

    assert first == second


def test_build_returns_empty_site_when_no_digests(tmp_path):
    site = build(tmp_path)
    # Empty NAS should still produce a usable site (search page + empty index)
    assert (site / "search.html").is_file()
    assert (site / "cards.json").read_text(encoding="utf-8").strip() == "[]"
