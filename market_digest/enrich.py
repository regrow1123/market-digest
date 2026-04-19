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


import requests

_PROFILE_URL = "https://financialmodelingprep.com/api/v3/profile/{ticker}"


def fetch_company_description(ticker: str, api_key: str) -> str | None:
    """Fetch FMP company profile description. None on any failure."""
    if not api_key:
        return None
    try:
        resp = requests.get(
            _PROFILE_URL.format(ticker=ticker),
            params={"apikey": api_key},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.warning("enrich: profile request failed for %s: %s", ticker, exc)
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    if not isinstance(data, list) or not data:
        return None
    desc = data[0].get("description")
    return desc if isinstance(desc, str) and desc.strip() else None


import subprocess

_BLURB_MAX = 120


def generate_blurb(
    *,
    ticker: str,
    name: str | None,
    description: str | None,
    claude_cli: str,
    model: str,
    timeout_sec: int = 60,
) -> str | None:
    """One-shot Sonnet call to compress a company description to a Korean one-liner."""
    display_name = name or ticker
    base_desc = (description or "").strip()
    prompt = (
        f"다음 회사를 한국어 한 줄(최대 60자)로 요약하라. "
        f"'~회사' 같은 상투어는 빼고 사업 핵심만. "
        f"출력은 한 줄 텍스트만.\n\n"
        f"티커: {ticker}\n이름: {display_name}\n설명: {base_desc}"
    )
    cmd = [
        claude_cli,
        "-p", prompt,
        "--model", model,
        "--allowed-tools", "",
        "--permission-mode", "dontAsk",
        "--output-format", "text",
        "--no-session-persistence",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec, check=False
        )
    except subprocess.TimeoutExpired:
        log.warning("enrich: sonnet timeout for %s", ticker)
        return None
    if proc.returncode != 0:
        log.warning("enrich: sonnet rc=%s for %s: %s",
                    proc.returncode, ticker, proc.stderr[:200])
        return None
    text = proc.stdout.strip().splitlines()
    if not text:
        return None
    return text[0].strip()[:_BLURB_MAX]
