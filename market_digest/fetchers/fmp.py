"""FMP (Financial Modeling Prep) fetcher — global analyst rating changes.

Uses the /api/v3/upgrades-downgrades-rss-feed endpoint (free tier).
Filters by market cap floor and target-price move; any "initiate"
action is kept regardless of target move.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

log = logging.getLogger(__name__)

FEED_URL = "https://financialmodelingprep.com/api/v3/upgrades-downgrades-rss-feed"
PROFILE_URL = "https://financialmodelingprep.com/api/v3/profile/{ticker}"


@dataclass
class RatingChange:
    ticker: str
    grade_date: str
    firm: str
    from_grade: str
    to_grade: str
    action: str
    price_when_posted: float | None
    price_target: float | None
    previous_price_target: float | None
    news_url: str
    news_title: str


def _fetch_feed(api_key: str, page: int) -> list[dict]:
    resp = requests.get(
        FEED_URL,
        params={"page": page, "apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_profile(ticker: str, api_key: str) -> dict | None:
    resp = requests.get(
        PROFILE_URL.format(ticker=ticker),
        params={"apikey": api_key},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data[0] if isinstance(data, list) and data else None


def _pct_change(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old == 0:
        return None
    return abs(new - old) / abs(old)


def _filter_records(
    records: list[dict],
    mcaps: dict[str, float],
    min_market_cap_usd: float,
    target_change_threshold: float,
) -> list[dict]:
    out: list[dict] = []
    for r in records:
        sym = r.get("symbol", "")
        mcap = mcaps.get(sym)
        if mcap is None or mcap < min_market_cap_usd:
            continue
        action = (r.get("action") or "").lower()
        if action == "initiate":
            out.append(r)
            continue
        pct = _pct_change(r.get("previousPriceTarget"), r.get("priceTarget"))
        if pct is not None and pct >= target_change_threshold:
            out.append(r)
    return out


def _yaml_front_matter(ch: RatingChange) -> str:
    lines = ["---"]
    for k, v in asdict(ch).items():
        s = "" if v is None else str(v).replace("\n", " ").strip()
        lines.append(f'{k}: "{s}"')
    # combined target string for downstream convenience
    if ch.previous_price_target is not None and ch.price_target is not None:
        target_combined = f"{ch.previous_price_target} -> {ch.price_target}"
    elif ch.price_target is not None:
        target_combined = str(ch.price_target)
    else:
        target_combined = ""
    lines.append(f'target: "{target_combined}"')
    lines.append('source: "fmp"')
    lines.append("---")
    return "\n".join(lines)


def fetch_and_save(
    date: str,
    inbox_dir: Path,
    api_key: str,
    min_market_cap_usd: float,
    target_change_threshold: float,
    page_limit: int,
    request_interval_sec: float,
) -> int:
    """Fetch today's rating changes and save one .txt per change."""
    if not api_key:
        log.warning("fmp: FMP_API_KEY not set; skipping")
        return 0
    inbox_dir.mkdir(parents=True, exist_ok=True)

    raw: list[dict] = []
    for page in range(page_limit):
        try:
            batch = _fetch_feed(api_key, page)
        except Exception as exc:
            log.warning("fmp: feed fetch page=%d failed: %s", page, exc)
            break
        if not batch:
            break
        raw.extend(batch)
        time.sleep(request_interval_sec)

    # keep only today's records
    today_rows = [r for r in raw if str(r.get("publishedDate", ""))[:10] == date]
    if not today_rows:
        return 0

    tickers = sorted({r.get("symbol") for r in today_rows if r.get("symbol")})
    mcaps: dict[str, float] = {}
    for t in tickers:
        prof = _fetch_profile(t, api_key)
        if prof is None:
            continue
        cap = prof.get("mktCap")
        if cap is not None:
            mcaps[t] = float(cap)
        time.sleep(request_interval_sec)

    filtered = _filter_records(
        today_rows, mcaps,
        min_market_cap_usd=min_market_cap_usd,
        target_change_threshold=target_change_threshold,
    )

    saved = 0
    for r in filtered:
        sym = r["symbol"]
        change = RatingChange(
            ticker=sym,
            grade_date=str(r.get("publishedDate", ""))[:10],
            firm=str(r.get("gradingCompany", "")).strip(),
            from_grade=str(r.get("previousGrade", "")).strip(),
            to_grade=str(r.get("newGrade", "")).strip(),
            action=str(r.get("action", "")).strip(),
            price_when_posted=r.get("priceWhenPosted"),
            price_target=r.get("priceTarget"),
            previous_price_target=r.get("previousPriceTarget"),
            news_url=str(r.get("newsURL", "")).strip(),
            news_title=str(r.get("newsTitle", "")).strip(),
        )
        safe_firm = "".join(c for c in change.firm if c.isalnum())[:20] or "unknown"
        out_txt = inbox_dir / f"fmp_{sym}_{safe_firm}_{change.grade_date}.txt"
        if out_txt.exists():
            continue
        target_str = (
            f"{change.previous_price_target} -> {change.price_target}"
            if change.previous_price_target is not None and change.price_target is not None
            else (str(change.price_target) if change.price_target is not None else "")
        )
        body = (
            f"Ticker: {change.ticker}\n"
            f"Date: {change.grade_date}\n"
            f"Firm: {change.firm}\n"
            f"Rating: {change.from_grade} -> {change.to_grade}\n"
            f"Action: {change.action}\n"
            f"Target: {target_str}\n"
            f"Price when posted: {change.price_when_posted}\n"
            f"News: {change.news_title}\n"
            f"URL: {change.news_url}\n"
        )
        out_txt.write_text(
            _yaml_front_matter(change) + "\n\n" + body, encoding="utf-8"
        )
        saved += 1
    return saved
