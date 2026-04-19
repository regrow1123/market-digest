from bs4 import BeautifulSoup

from market_digest.models import Digest
from market_digest.web.builder import render_card_page


def _digest() -> Digest:
    return Digest.model_validate(
        {
            "date": "2026-04-19",
            "groups": [
                {
                    "region": "kr",
                    "category": "company",
                    "title": "국내 기업리포트",
                    "items": [
                        {
                            "id": "kr-company-0",
                            "headline": "HBM 업황 회복",
                            "body_md": "- line",
                            "house": "미래에셋",
                            "ticker": "005930",
                            "name": "삼성전자",
                            "opinion": "Buy",
                            "target": "85→95k",
                        }
                    ],
                }
            ],
        }
    )


def test_card_page_has_date_and_weekday():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    header = soup.find(class_="date-header")
    assert "2026-04-19" in header.text
    assert "일" in header.text  # 2026-04-19 is Sunday (일요일) — only the char


def test_card_links_to_detail_page():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a.card")
    assert link["href"] == "2026-04-19/kr-company-0.html"
    assert "삼성전자" in link.text
    assert "HBM 업황 회복" in link.text


def test_prev_next_links_when_present():
    html = render_card_page(_digest(), prev_date="2026-04-18", next_date="2026-04-20")
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "2026-04-18.html"
    assert soup.select_one("a.nav-next")["href"] == "2026-04-20.html"


def test_prev_next_disabled_when_absent():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".nav-prev.disabled") is not None
    assert soup.select_one(".nav-next.disabled") is not None


def test_empty_day_message():
    d = Digest.model_validate({"date": "2026-04-20", "groups": []})
    html = render_card_page(d, prev_date="2026-04-19", next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    assert "오늘 수집된 리포트 없음" in soup.text
