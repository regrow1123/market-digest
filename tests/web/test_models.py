import pytest
from pydantic import ValidationError

from market_digest.models import Digest, Group, Item


def _minimal_item(**over) -> dict:
    base = {
        "id": "kr-company-0",
        "headline": "HBM 업황 회복",
        "body_md": "- line 1",
    }
    base.update(over)
    return base


def _minimal_group(**over) -> dict:
    base = {
        "region": "kr",
        "category": "company",
        "title": "국내 기업리포트",
        "items": [_minimal_item()],
    }
    base.update(over)
    return base


def test_digest_parses_minimal_payload():
    d = Digest.model_validate({"date": "2026-04-19", "groups": []})
    assert d.date == "2026-04-19"
    assert d.groups == []


def test_digest_parses_full_payload():
    d = Digest.model_validate(
        {
            "date": "2026-04-19",
            "groups": [
                _minimal_group(
                    items=[
                        {
                            "id": "kr-company-0",
                            "house": "미래에셋",
                            "ticker": "005930",
                            "name": "삼성전자",
                            "headline": "HBM 업황 회복",
                            "opinion": "Buy",
                            "target": "85,000 → 95,000",
                            "body_md": "- 목표가 85k→95k",
                            "url": "https://example.com/x",
                        }
                    ]
                )
            ],
        }
    )
    item = d.groups[0].items[0]
    assert item.name == "삼성전자"
    assert item.ticker == "005930"
    assert item.url == "https://example.com/x"


def test_item_requires_only_id_and_headline():
    # id + headline are required
    with pytest.raises(ValidationError):
        Item.model_validate({"headline": "x"})  # missing id
    with pytest.raises(ValidationError):
        Item.model_validate({"id": "a"})  # missing headline
    # body_md is optional, defaults to empty string
    item = Item.model_validate({"id": "a", "headline": "x"})
    assert item.body_md == ""


def test_group_region_must_be_kr_or_us():
    with pytest.raises(ValidationError):
        Group.model_validate(_minimal_group(region="jp"))


def test_group_category_restricted_set():
    with pytest.raises(ValidationError):
        Group.model_validate(_minimal_group(category="unknown"))


def test_digest_date_format_yyyy_mm_dd():
    with pytest.raises(ValidationError):
        Digest.model_validate({"date": "20260419", "groups": []})


def test_item_accepts_company_blurb():
    item = Item.model_validate({
        "id": "us-rating-0",
        "headline": "h",
        "body_md": "b",
        "company_blurb": "미국 스마트폰 제조사",
    })
    assert item.company_blurb == "미국 스마트폰 제조사"


def test_item_company_blurb_defaults_to_none():
    item = Item.model_validate({"id": "x", "headline": "h", "body_md": "b"})
    assert item.company_blurb is None
