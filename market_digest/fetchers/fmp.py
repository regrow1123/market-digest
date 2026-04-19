"""FMP (Financial Modeling Prep) fetcher — global analyst rating + target changes.

Uses /stable/grades-latest-news (rating changes) and
/stable/price-target-latest-news (target changes), both free tier.

Free-tier caps (verified 2026-04-20):
  - limit <= 10 per feed call
  - page must be 0 (pagination is premium-only)

Result: up to 10 newest global rating changes + 10 newest target changes
per run. Sufficient for discovery on most days but misses tail events on
heavy news days. Upgrade tier to unlock pagination + larger limits.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

log = logging.getLogger(__name__)

GRADES_URL = "https://financialmodelingprep.com/stable/grades-latest-news"
TARGETS_URL = "https://financialmodelingprep.com/stable/price-target-latest-news"
PROFILE_URL = "https://financialmodelingprep.com/stable/profile"

GRADES_DROP_ACTIONS = {"maintain"}


@dataclass
class GradeChange:
    ticker: str
    grade_date: str
    firm: str
    from_grade: str
    to_grade: str
    action: str
    price_when_posted: float | None
    news_url: str
    news_title: str


@dataclass
class TargetChange:
    ticker: str
    grade_date: str
    firm: str
    analyst: str
    price_target: float | None
    adj_price_target: float | None
    price_when_posted: float | None
    news_url: str
    news_title: str


def _fetch_grades(api_key: str, page: int, limit: int = 10) -> list[dict]:
    resp = requests.get(
        GRADES_URL,
        params={"page": page, "limit": limit, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _fetch_targets(api_key: str, page: int, limit: int = 10) -> list[dict]:
    resp = requests.get(
        TARGETS_URL,
        params={"page": page, "limit": limit, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _fetch_profile(ticker: str, api_key: str) -> dict | None:
    resp = requests.get(
        PROFILE_URL,
        params={"symbol": ticker, "apikey": api_key},
        timeout=30,
    )
    if resp.status_code != 200:
        log.warning("fmp: profile %s returned %s", ticker, resp.status_code)
        return None
    data = resp.json()
    return data[0] if isinstance(data, list) and data else None


def _filter_grades(records: list[dict], mcaps: dict[str, float], min_mcap: float) -> list[dict]:
    out = []
    for r in records:
        if mcaps.get(r.get("symbol", ""), 0.0) < min_mcap:
            continue
        if (r.get("action") or "").lower() in GRADES_DROP_ACTIONS:
            continue
        out.append(r)
    return out


def _filter_targets(records: list[dict], mcaps: dict[str, float], min_mcap: float) -> list[dict]:
    return [r for r in records if mcaps.get(r.get("symbol", ""), 0.0) >= min_mcap]


def _yaml_front_matter(obj, source: str) -> str:
    lines = ["---"]
    for k, v in asdict(obj).items():
        s = "" if v is None else str(v).replace("\n", " ").strip()
        lines.append(f'{k}: "{s}"')
    lines.append(f'source: "{source}"')
    lines.append("---")
    return "\n".join(lines)


def _safe_firm(name: str) -> str:
    return "".join(c for c in name if c.isalnum())[:20] or "unknown"


def fetch_and_save(
    date: str,
    inbox_dir: Path,
    api_key: str,
    min_market_cap_usd: float,
    request_interval_sec: float,
    target_change_threshold: float | None = None,  # kept for back-compat; ignored
) -> int:
    """Fetch today's grade + target changes, save one .txt per record."""
    if not api_key:
        log.warning("fmp: FMP_API_KEY not set; skipping")
        return 0
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch both feeds
    # Global rating feed — free tier caps at limit=10, page=0 only
    try:
        grades_raw = _fetch_grades(api_key, page=0)
    except Exception as exc:
        log.warning("fmp: grades fetch failed: %s", exc)
        grades_raw = []
    time.sleep(request_interval_sec)

    try:
        targets_raw = _fetch_targets(api_key, page=0)
    except Exception as exc:
        log.warning("fmp: targets fetch failed: %s", exc)
        targets_raw = []
    time.sleep(request_interval_sec)

    # 2. Filter by date
    grades_today = [r for r in grades_raw if str(r.get("publishedDate", ""))[:10] == date]
    targets_today = [r for r in targets_raw if str(r.get("publishedDate", ""))[:10] == date]

    if not grades_today and not targets_today:
        return 0

    # 3. Resolve market caps (unique union of symbols)
    symbols = sorted({r["symbol"] for r in (grades_today + targets_today) if r.get("symbol")})
    mcaps: dict[str, float] = {}
    for t in symbols:
        prof = _fetch_profile(t, api_key)
        if prof is None:
            continue
        cap = prof.get("marketCap")
        if cap is not None:
            mcaps[t] = float(cap)
        time.sleep(request_interval_sec)

    # 4. Filter + write files
    saved = 0

    for r in _filter_grades(grades_today, mcaps, min_market_cap_usd):
        sym = r["symbol"]
        firm = str(r.get("gradingCompany", "")).strip()
        change = GradeChange(
            ticker=sym,
            grade_date=str(r.get("publishedDate", ""))[:10],
            firm=firm,
            from_grade=str(r.get("previousGrade") or "").strip(),
            to_grade=str(r.get("newGrade", "")).strip(),
            action=str(r.get("action", "")).strip(),
            price_when_posted=r.get("priceWhenPosted"),
            news_url=str(r.get("newsURL", "")).strip(),
            news_title=str(r.get("newsTitle", "")).strip(),
        )
        out_txt = inbox_dir / f"fmp_grade_{sym}_{_safe_firm(firm)}_{change.grade_date}.txt"
        if out_txt.exists():
            continue
        body = (
            f"Type: rating\n"
            f"Ticker: {change.ticker}\n"
            f"Date: {change.grade_date}\n"
            f"Firm: {change.firm}\n"
            f"Rating: {change.from_grade or '-'} -> {change.to_grade}\n"
            f"Action: {change.action}\n"
            f"Price when posted: {change.price_when_posted}\n"
            f"News: {change.news_title}\n"
            f"URL: {change.news_url}\n"
        )
        out_txt.write_text(
            _yaml_front_matter(change, "fmp_grades") + "\n\n" + body, encoding="utf-8"
        )
        saved += 1

    for r in _filter_targets(targets_today, mcaps, min_market_cap_usd):
        sym = r["symbol"]
        firm = str(r.get("analystCompany") or r.get("newsPublisher") or "").strip()
        change = TargetChange(
            ticker=sym,
            grade_date=str(r.get("publishedDate", ""))[:10],
            firm=firm,
            analyst=str(r.get("analystName") or "").strip(),
            price_target=r.get("priceTarget"),
            adj_price_target=r.get("adjPriceTarget"),
            price_when_posted=r.get("priceWhenPosted"),
            news_url=str(r.get("newsURL", "")).strip(),
            news_title=str(r.get("newsTitle", "")).strip(),
        )
        out_txt = inbox_dir / f"fmp_target_{sym}_{_safe_firm(firm)}_{change.grade_date}.txt"
        if out_txt.exists():
            continue
        body = (
            f"Type: price_target\n"
            f"Ticker: {change.ticker}\n"
            f"Date: {change.grade_date}\n"
            f"Firm: {change.firm}\n"
            f"Analyst: {change.analyst}\n"
            f"Target: {change.price_target}\n"
            f"Price when posted: {change.price_when_posted}\n"
            f"News: {change.news_title}\n"
            f"URL: {change.news_url}\n"
        )
        out_txt.write_text(
            _yaml_front_matter(change, "fmp_targets") + "\n\n" + body, encoding="utf-8"
        )
        saved += 1

    return saved
