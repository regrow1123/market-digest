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
