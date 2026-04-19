import json
from pathlib import Path

from bs4 import BeautifulSoup

from market_digest.web import build


def _write(nas: Path, date: str, groups: list[dict]) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


def test_build_renders_research_md_into_site(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text(
        "# AAPL 딥 리서치 — 2026-04-20\n\n## 회사 개요\n- detail alpha\n",
        encoding="utf-8",
    )

    site = build(tmp_path)
    research_page = site / "2026-04-20" / "us-rating-0.research.html"
    assert research_page.is_file()
    soup = BeautifulSoup(research_page.read_text(encoding="utf-8"), "html.parser")
    assert "detail alpha" in soup.text


def test_detail_page_links_to_research_when_present(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text(
        "# AAPL\n- x\n", encoding="utf-8",
    )

    site = build(tmp_path)
    detail = site / "2026-04-20" / "us-rating-0.html"
    soup = BeautifulSoup(detail.read_text(encoding="utf-8"), "html.parser")
    link = soup.select_one("a.research-link")
    assert link is not None
    assert link["href"] == "us-rating-0.research.html"


def test_detail_page_omits_research_link_when_absent(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    # no research md written

    site = build(tmp_path)
    detail = site / "2026-04-20" / "us-rating-0.html"
    soup = BeautifulSoup(detail.read_text(encoding="utf-8"), "html.parser")
    assert soup.select_one("a.research-link") is None


def test_build_skips_research_md_without_ticker(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "kr", "category": "industry", "title": "국내 시황·산업",
        "items": [{"id": "kr-industry-0", "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text("# AAPL\n", encoding="utf-8")

    site = build(tmp_path)
    # no research page should be generated when no item has that ticker on that date
    assert not list((site / "2026-04-20").glob("*.research.html"))
