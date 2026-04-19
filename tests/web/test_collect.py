import json
from pathlib import Path

from market_digest.web.builder import collect_digests


def _write(nas: Path, date: str, payload: dict) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_sorts_by_date_ascending(tmp_path):
    _write(tmp_path, "2026-04-18", {"date": "2026-04-18", "groups": []})
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    _write(tmp_path, "2026-04-17", {"date": "2026-04-17", "groups": []})

    digests = collect_digests(tmp_path)
    assert [d.date for d in digests] == ["2026-04-17", "2026-04-18", "2026-04-19"]


def test_collect_skips_invalid_json(tmp_path, caplog):
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    bad = tmp_path / "2026" / "04" / "2026-04-18.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        digests = collect_digests(tmp_path)

    assert [d.date for d in digests] == ["2026-04-19"]
    assert any("2026-04-18" in r.message for r in caplog.records)


def test_collect_skips_schema_mismatch(tmp_path, caplog):
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    _write(tmp_path, "2026-04-18", {"date": "bad-date", "groups": []})

    with caplog.at_level("WARNING"):
        digests = collect_digests(tmp_path)

    assert [d.date for d in digests] == ["2026-04-19"]
    assert any("2026-04-18" in r.message for r in caplog.records)


def test_collect_returns_empty_when_no_json(tmp_path):
    assert collect_digests(tmp_path) == []


def test_collect_ignores_stray_site_files(tmp_path, caplog):
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    stray = tmp_path / "site" / "cards.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text('{"not": "a digest"}', encoding="utf-8")
    stray_asset = tmp_path / "site" / "assets" / "style.json"
    stray_asset.parent.mkdir(parents=True, exist_ok=True)
    stray_asset.write_text('{"also": "not a digest"}', encoding="utf-8")

    with caplog.at_level("WARNING"):
        digests = collect_digests(tmp_path)

    assert [d.date for d in digests] == ["2026-04-19"]
    assert not any("site" in r.message for r in caplog.records)
