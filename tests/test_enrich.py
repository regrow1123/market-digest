import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_digest.enrich import BlurbCache, fetch_company_description


def test_cache_returns_none_when_missing(tmp_path):
    cache = BlurbCache(tmp_path / "blurbs.json", ttl_days=90)
    assert cache.get("AAPL") is None


def test_cache_returns_fresh_entry(tmp_path):
    path = tmp_path / "blurbs.json"
    today = date(2026, 4, 20).isoformat()
    path.write_text(json.dumps({"AAPL": {"blurb": "x", "fetched_at": today, "source": "t"}}))
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    assert cache.get("AAPL") == "x"


def test_cache_treats_old_entry_as_expired(tmp_path):
    path = tmp_path / "blurbs.json"
    old = (date(2026, 4, 20) - timedelta(days=120)).isoformat()
    path.write_text(json.dumps({"AAPL": {"blurb": "x", "fetched_at": old, "source": "t"}}))
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    assert cache.get("AAPL") is None


def test_cache_set_and_persist(tmp_path):
    path = tmp_path / "blurbs.json"
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    cache.set("AAPL", "스마트폰 제조사", source="fmp+sonnet")
    cache.save()
    data = json.loads(path.read_text())
    assert data["AAPL"]["blurb"] == "스마트폰 제조사"
    assert data["AAPL"]["fetched_at"] == "2026-04-20"
    assert data["AAPL"]["source"] == "fmp+sonnet"


def test_cache_save_noop_when_clean(tmp_path):
    path = tmp_path / "blurbs.json"
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    cache.save()
    assert not path.exists()


def test_cache_save_writes_only_once_per_mutation(tmp_path):
    path = tmp_path / "blurbs.json"
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    cache.set("AAPL", "x", source="t")
    cache.save()
    mtime1 = path.stat().st_mtime_ns
    cache.save()  # no new mutation — should be a no-op
    assert path.stat().st_mtime_ns == mtime1


def test_cache_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "blurbs.json"
    path.write_text("{{{ not json")
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    assert cache.get("AAPL") is None
    cache.set("AAPL", "x", source="t")
    cache.save()
    assert json.loads(path.read_text())["AAPL"]["blurb"] == "x"


def test_fetch_company_description_returns_description_field():
    with patch("market_digest.enrich.requests.get") as m:
        m.return_value.status_code = 200
        m.return_value.json.return_value = [{
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "description": "Apple Inc. designs, manufactures, and markets smartphones...",
        }]
        desc = fetch_company_description("AAPL", "key")
    assert desc and "Apple Inc." in desc


def test_fetch_company_description_returns_none_on_http_error():
    with patch("market_digest.enrich.requests.get") as m:
        m.return_value.status_code = 404
        m.return_value.json.return_value = {}
        assert fetch_company_description("BADXYZ", "key") is None


def test_fetch_company_description_returns_none_on_empty_list():
    with patch("market_digest.enrich.requests.get") as m:
        m.return_value.status_code = 200
        m.return_value.json.return_value = []
        assert fetch_company_description("AAPL", "key") is None


from market_digest.enrich import generate_blurb


def _make_proc(stdout: str, returncode: int = 0):
    class R:
        def __init__(self):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode
    return R()


def test_generate_blurb_strips_and_returns_single_line():
    with patch("market_digest.enrich.subprocess.run",
               return_value=_make_proc("  한국 메모리반도체 제조사\n\n")) as m:
        out = generate_blurb(
            ticker="005930",
            name="삼성전자",
            description="Samsung Electronics ...",
            claude_cli="/usr/bin/claude",
            model="claude-sonnet-4-6",
        )
    assert out == "한국 메모리반도체 제조사"
    args, _ = m.call_args
    cmd = args[0]
    assert cmd[0] == "/usr/bin/claude"
    assert "--model" in cmd
    assert "claude-sonnet-4-6" in cmd


def test_generate_blurb_returns_none_on_nonzero_exit():
    with patch("market_digest.enrich.subprocess.run",
               return_value=_make_proc("", returncode=2)):
        assert generate_blurb(
            ticker="AAPL", name="Apple", description="x",
            claude_cli="/bin/claude", model="m",
        ) is None


def test_generate_blurb_truncates_to_120_chars():
    long = "가" * 500
    with patch("market_digest.enrich.subprocess.run",
               return_value=_make_proc(long)):
        out = generate_blurb(
            ticker="X", name="X", description="x",
            claude_cli="/bin/claude", model="m",
        )
    assert out is not None
    assert len(out) <= 120


from market_digest.enrich import enrich_digest


def test_enrich_digest_fills_from_cache_without_network(tmp_path):
    blurbs = tmp_path / "blurbs.json"
    today = date(2026, 4, 20).isoformat()
    blurbs.write_text(json.dumps({
        "AAPL": {"blurb": "미국 스마트폰", "fetched_at": today, "source": "cache"},
    }))

    json_path = tmp_path / "2026-04-20.json"
    json_path.write_text(json.dumps({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                       "headline": "h", "body_md": "b"}],
        }],
    }), encoding="utf-8")

    with patch("market_digest.enrich.fetch_company_description") as fcd, \
         patch("market_digest.enrich.generate_blurb") as gb:
        enrich_digest(
            json_path=json_path,
            cache_path=blurbs,
            api_key="dummy",
            claude_cli="/bin/claude",
            model="m",
            ttl_days=90,
            today=date(2026, 4, 20),
        )

    fcd.assert_not_called()
    gb.assert_not_called()
    out = json.loads(json_path.read_text())
    assert out["groups"][0]["items"][0]["company_blurb"] == "미국 스마트폰"


def test_enrich_digest_generates_when_cache_miss(tmp_path):
    blurbs = tmp_path / "blurbs.json"
    json_path = tmp_path / "2026-04-20.json"
    json_path.write_text(json.dumps({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{"id": "us-rating-0", "ticker": "NVDA", "name": "NVIDIA",
                       "headline": "h", "body_md": "b"}],
        }],
    }), encoding="utf-8")

    with patch("market_digest.enrich.fetch_company_description",
               return_value="NVIDIA designs GPUs and accelerated computing platforms."), \
         patch("market_digest.enrich.generate_blurb",
               return_value="GPU·AI 가속기 설계사"):
        enrich_digest(
            json_path=json_path, cache_path=blurbs,
            api_key="dummy", claude_cli="/bin/claude", model="m",
            ttl_days=90, today=date(2026, 4, 20),
        )

    out = json.loads(json_path.read_text())
    assert out["groups"][0]["items"][0]["company_blurb"] == "GPU·AI 가속기 설계사"
    cached = json.loads(blurbs.read_text())
    assert cached["NVDA"]["blurb"] == "GPU·AI 가속기 설계사"


def test_enrich_digest_skips_items_without_ticker(tmp_path):
    blurbs = tmp_path / "blurbs.json"
    json_path = tmp_path / "2026-04-20.json"
    json_path.write_text(json.dumps({
        "date": "2026-04-20",
        "groups": [{
            "region": "kr", "category": "industry", "title": "국내 시황·산업",
            "items": [{"id": "kr-industry-0", "headline": "반도체 업황", "body_md": "-"}],
        }],
    }), encoding="utf-8")

    with patch("market_digest.enrich.fetch_company_description") as fcd:
        enrich_digest(
            json_path=json_path, cache_path=blurbs,
            api_key="dummy", claude_cli="/bin/claude", model="m",
            ttl_days=90, today=date(2026, 4, 20),
        )

    fcd.assert_not_called()
    out = json.loads(json_path.read_text())
    assert out["groups"][0]["items"][0].get("company_blurb") in (None, "")


def test_enrich_digest_skips_sonnet_when_description_missing(tmp_path):
    blurbs = tmp_path / "blurbs.json"
    json_path = tmp_path / "2026-04-20.json"
    json_path.write_text(json.dumps({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{"id": "us-rating-0", "ticker": "OBSCURE", "name": "Obscure",
                       "headline": "h", "body_md": "b"}],
        }],
    }), encoding="utf-8")

    with patch("market_digest.enrich.fetch_company_description", return_value=None), \
         patch("market_digest.enrich.generate_blurb") as gb:
        enrich_digest(
            json_path=json_path, cache_path=blurbs,
            api_key="dummy", claude_cli="/bin/claude", model="m",
            ttl_days=90, today=date(2026, 4, 20),
        )

    gb.assert_not_called()
    out = json.loads(json_path.read_text())
    assert out["groups"][0]["items"][0].get("company_blurb") in (None, "")


def test_enrich_digest_tolerates_generate_failure(tmp_path):
    blurbs = tmp_path / "blurbs.json"
    json_path = tmp_path / "2026-04-20.json"
    json_path.write_text(json.dumps({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                       "headline": "h", "body_md": "b"}],
        }],
    }), encoding="utf-8")

    with patch("market_digest.enrich.fetch_company_description", return_value="x"), \
         patch("market_digest.enrich.generate_blurb", return_value=None):
        enrich_digest(
            json_path=json_path, cache_path=blurbs,
            api_key="dummy", claude_cli="/bin/claude", model="m",
            ttl_days=90, today=date(2026, 4, 20),
        )

    out = json.loads(json_path.read_text())
    assert out["groups"][0]["items"][0].get("company_blurb") in (None, "")
