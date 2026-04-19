"""Tests for run._validate_digest quarantine behavior."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from market_digest.run import _validate_digest


def _write_json(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")


def test_valid_digest_leaves_file_intact(tmp_path, caplog):
    nas = tmp_path / "nas" / "2026" / "04"
    logs = tmp_path / "logs"
    logs.mkdir()
    json_path = nas / "2026-04-19.json"
    _write_json(json_path, {"date": "2026-04-19", "groups": []})

    log = logging.getLogger("test")
    assert _validate_digest(json_path, logs, "2026-04-19", log) is True
    assert json_path.exists()
    assert not (json_path.with_suffix(".json.invalid")).exists()


def test_invalid_schema_quarantines_file(tmp_path, caplog):
    nas = tmp_path / "nas" / "2026" / "04"
    logs = tmp_path / "logs"
    logs.mkdir()
    json_path = nas / "2026-04-19.json"
    _write_json(json_path, {"date": "bad-date", "groups": []})

    log = logging.getLogger("test")
    with caplog.at_level(logging.ERROR):
        assert _validate_digest(json_path, logs, "2026-04-19", log) is False

    assert not json_path.exists(), "original should be renamed"
    quarantined = json_path.with_suffix(".json.invalid")
    assert quarantined.exists(), "quarantined file should exist"
    assert (logs / "2026-04-19-invalid.json").exists(), "log dump should exist"


def test_malformed_json_quarantines_file(tmp_path):
    nas = tmp_path / "nas" / "2026" / "04"
    logs = tmp_path / "logs"
    logs.mkdir()
    json_path = nas / "2026-04-19.json"
    _write_json(json_path, "{ not valid json")

    log = logging.getLogger("test")
    assert _validate_digest(json_path, logs, "2026-04-19", log) is False
    assert not json_path.exists()
    assert json_path.with_suffix(".json.invalid").exists()
