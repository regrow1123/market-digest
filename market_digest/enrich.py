"""Post-summarize enrichment: attach company_blurb to each item.

Pipeline role:
    summarize -> validate -> enrich -> web.build

Cache layout (JSON):
    {"AAPL": {"blurb": "...", "fetched_at": "2026-04-20", "source": "fmp+sonnet"}}
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import date as _date
from pathlib import Path

import requests

log = logging.getLogger(__name__)


import re

_KR_TICKER_RE = re.compile(r"^\d{6}$")


def _is_korean_ticker(ticker: str) -> bool:
    return bool(_KR_TICKER_RE.match(ticker or ""))


class BlurbCache:
    """90-day TTL cache of (ticker -> blurb). Corrupt files are tolerated."""

    def __init__(self, path: Path, ttl_days: int, today: _date | None = None) -> None:
        self.path = path
        self.ttl_days = ttl_days
        self._today = today or _date.today()
        self._data: dict[str, dict] = {}
        self._dirty: bool = False
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
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False


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
        f"잘 알려지지 않은 기업이라 확신이 서지 않으면 '정보 없음' 한 단어만 답하라. "
        f"출력은 한 줄 텍스트만.\n\n"
        f"티커: {ticker}\n이름: {display_name}\n설명: {base_desc or '(미제공)'}"
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
    line = text[0].strip()[:_BLURB_MAX]
    if line in {"정보 없음", "정보없음"}:
        return None
    return line


def enrich_digest(
    *,
    json_path: Path,
    cache_path: Path,
    api_key: str,
    claude_cli: str,
    model: str,
    ttl_days: int,
    today: _date | None = None,
) -> None:
    """Load the digest JSON, fill company_blurb for items with a ticker, write back.

    - Cache-hit items use the stored blurb (no network).
    - Cache-miss items fetch FMP description and generate a Sonnet blurb.
    - Items without `ticker` are skipped.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cache = BlurbCache(cache_path, ttl_days=ttl_days, today=today)
    mutated = False

    for group in data.get("groups", []):
        for item in group.get("items", []):
            ticker = item.get("ticker")
            if not ticker:
                continue
            existing = cache.get(ticker)
            if existing is not None:
                item["company_blurb"] = existing
                mutated = True
                continue
            if _is_korean_ticker(ticker):
                description = None
            else:
                description = fetch_company_description(ticker, api_key)
            blurb = generate_blurb(
                ticker=ticker,
                name=item.get("name"),
                description=description,
                claude_cli=claude_cli,
                model=model,
            )
            if blurb:
                cache.set(ticker, blurb, source="fmp+sonnet")
                item["company_blurb"] = blurb
                mutated = True

    cache.save()
    if mutated:
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
