"""Post-summarize enrichment: attach company_blurb to each item.

Pipeline role:
    summarize -> validate -> enrich -> web.build

Cache layout (JSON):
    {"AAPL": {"blurb": "...", "fetched_at": "2026-04-20", "source": "fmp+sonnet"}}
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from pathlib import Path

log = logging.getLogger(__name__)


class BlurbCache:
    """90-day TTL cache of (ticker -> blurb). Corrupt files are tolerated."""

    def __init__(self, path: Path, ttl_days: int, today: _date | None = None) -> None:
        self.path = path
        self.ttl_days = ttl_days
        self._today = today or _date.today()
        self._data: dict[str, dict] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("blurb cache unreadable at %s: %s", path, exc)

    def get(self, ticker: str) -> str | None:
        entry = self._data.get(ticker)
        if not entry:
            return None
        try:
            fetched = _date.fromisoformat(entry.get("fetched_at", ""))
        except ValueError:
            return None
        if (self._today - fetched).days > self.ttl_days:
            return None
        return entry.get("blurb")

    def set(self, ticker: str, blurb: str, *, source: str) -> None:
        self._data[ticker] = {
            "blurb": blurb,
            "fetched_at": self._today.isoformat(),
            "source": source,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
