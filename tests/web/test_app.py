import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from market_digest.web.app import create_app


def _write(nas: Path, date: str, groups: list) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


@pytest.fixture
def nas(tmp_path: Path) -> Path:
    return tmp_path


def test_health_endpoint():
    app = create_app(nas_dir=None)
    with TestClient(app) as c:
        resp = c.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


def test_home_redirects_to_latest_date(nas):
    _write(nas, "2026-04-17", [])
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app, follow_redirects=False) as c:
        resp = c.get("/")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/2026-04-19")


def test_home_placeholder_when_empty(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/")
    assert resp.status_code == 200
    assert "아직 리포트가 없습니다" in resp.text


def test_cards_json_is_date_desc(nas):
    _write(nas, "2026-04-18", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "old", "body_md": "x"}]},
    ])
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "new", "body_md": "y"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/cards.json")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["date"] for e in data] == ["2026-04-19", "2026-04-18"]


from bs4 import BeautifulSoup


def test_card_page_renders_groups_and_cards(nas):
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내 기업리포트",
         "items": [{"id": "kr-company-0", "headline": "HBM 회복", "body_md": "-",
                    "house": "MS", "name": "삼성전자", "ticker": "005930"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.select_one("a.card")
    assert link["href"] == "/2026-04-19/kr-company-0"
    assert "삼성전자" in link.text


def test_card_page_prev_next_clean_urls(nas):
    _write(nas, "2026-04-17", [])
    _write(nas, "2026-04-18", [])
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-18")
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "/2026-04-17"
    assert soup.select_one("a.nav-next")["href"] == "/2026-04-19"


def test_card_page_404_when_date_missing(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19")
    assert resp.status_code == 404


def test_detail_page_renders(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "MS upgrade", "body_md": "- detail",
                    "company_blurb": "스마트폰·서비스"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("article h1")
    assert "스마트폰" in resp.text
    # research UI present as BUTTON because md doesn't exist yet
    assert soup.select_one("button#research-btn") is not None
    assert soup.select_one("a.research-link") is None


def test_detail_page_research_link_when_md_exists(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text("# A\n", encoding="utf-8")
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.select_one("a.research-link")
    assert link is not None
    assert link["href"] == "/2026-04-19/us-rating-0/research"
    assert soup.select_one("button#research-btn") is None


def test_detail_page_404_when_item_missing(nas):
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/missing")
    assert resp.status_code == 404


def test_detail_page_prev_next_within_day(nas):
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [
             {"id": "kr-company-0", "headline": "a", "body_md": "-"},
             {"id": "kr-company-1", "headline": "b", "body_md": "-"},
             {"id": "kr-company-2", "headline": "c", "body_md": "-"},
         ]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/kr-company-1")
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "/2026-04-19/kr-company-0"
    assert soup.select_one("a.nav-next")["href"] == "/2026-04-19/kr-company-2"
    assert soup.select_one("a.back")["href"] == "/2026-04-19"


def test_research_page_renders_md(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text(
        "# 딥 리서치\n\n- alpha research line\n", encoding="utf-8"
    )
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0/research")
    assert resp.status_code == 200
    assert "alpha research line" in resp.text


def test_research_page_404_without_md(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0/research")
    assert resp.status_code == 404


def test_search_page_renders(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/search")
    assert resp.status_code == 200
    assert "cards.json" in resp.text
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("input#search-input") is not None


def test_static_asset_served(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/assets/style.css")
    assert resp.status_code == 200
    assert "page" in resp.text  # stylesheet contains .page rule


def test_static_asset_404_for_unknown(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/assets/does-not-exist.js")
    assert resp.status_code == 404


def _fake_runner(tracker, job_id, ticker, date_str, out_path):
    """Test runner: marks running, writes a stub md, marks done."""
    tracker.mark_running(job_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(f"# {ticker} stub — {date_str}\n", encoding="utf-8")
    tracker.mark_done(job_id, f"/{date_str}/dummy/research")


def test_post_research_starts_new_job_and_returns_job_id(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("pending", "running", "done")
    assert body["job_id"]


def test_post_research_returns_existing_md_immediately(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text("# old\n", encoding="utf-8")
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    body = resp.json()
    assert body["status"] == "done"
    assert body["output_url"] == "/2026-04-19/us-rating-0/research"


def test_post_research_dedupes_active_job(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    def slow_runner(tracker, job_id, *args, **kwargs):
        tracker.mark_running(job_id)  # leave running; never calls mark_done
    app = create_app(nas_dir=nas, research_runner=slow_runner)
    with TestClient(app) as c:
        r1 = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
        r2 = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_post_research_400_if_ticker_not_in_digest(nas):
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "XYZ", "date": "2026-04-19"})
    assert resp.status_code == 400


def test_get_research_status_returns_state(nas):
    app = create_app(nas_dir=nas)
    tracker = app.state.tracker
    j = tracker.create("AAPL", "2026-04-19")
    tracker.mark_running(j.job_id)
    with TestClient(app) as c:
        resp = c.get(f"/api/research/status/{j.job_id}")
    body = resp.json()
    assert body["status"] == "running"
    assert body["ticker"] == "AAPL"
    assert body["date"] == "2026-04-19"


def test_get_research_status_404_for_unknown(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/api/research/status/does-not-exist")
    assert resp.status_code == 404


def test_get_research_active_lists_only_pending_running(nas):
    app = create_app(nas_dir=nas)
    tracker = app.state.tracker
    j1 = tracker.create("AAPL", "2026-04-19")
    j2 = tracker.create("MSFT", "2026-04-19")
    tracker.mark_done(j2.job_id, "/x")
    with TestClient(app) as c:
        resp = c.get("/api/research/active")
    body = resp.json()
    ids = {j["job_id"] for j in body}
    assert j1.job_id in ids
    assert j2.job_id not in ids


def test_research_js_served(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        r = c.get("/assets/research.js")
        b = c.get("/assets/base.js")
    assert r.status_code == 200 and "fetch(\"/api/research\"" in r.text
    assert b.status_code == 200 and "global-research-badge" in b.text


def test_detail_page_includes_tv_chart_when_ticker_present(nas):
    _write(nas, "2026-04-20", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "ticker": "005930", "name": "삼성전자",
                    "headline": "h", "body_md": "-"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-20/kr-company-0")
    assert resp.status_code == 200
    assert "embed-widget-advanced-chart.js" in resp.text
    assert "KRX:005930" in resp.text


def test_detail_page_no_tv_chart_when_ticker_missing(nas):
    _write(nas, "2026-04-20", [
        {"region": "kr", "category": "industry", "title": "국내 시황·산업",
         "items": [{"id": "kr-industry-0", "headline": "반도체 업황", "body_md": "-"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-20/kr-industry-0")
    assert resp.status_code == 200
    assert "embed-widget-advanced-chart.js" not in resp.text
    assert "tradingview-widget-container" not in resp.text


def test_detail_page_us_ticker_uses_bare_symbol(nas):
    _write(nas, "2026-04-20", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "-"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-20/us-rating-0")
    assert resp.status_code == 200
    assert "\"symbol\": \"AAPL\"" in resp.text
    assert "KRX" not in resp.text
