"""yfinance fetcher — analyst upgrades/downgrades for the watchlist.

Uses yfinance's Ticker.upgrades_downgrades DataFrame (GradeDate, Firm,
ToGrade, FromGrade, Action). Filters rows whose GradeDate equals `date`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from pathlib import Path

import yfinance as yf

log = logging.getLogger(__name__)


@dataclass
class AnalystChange:
    ticker: str
    grade_date: str
    firm: str
    from_grade: str
    to_grade: str
    action: str


def _yaml_front_matter(ch: AnalystChange) -> str:
    lines = ["---"]
    for k, v in asdict(ch).items():
        s = str(v).replace("\n", " ").strip()
        lines.append(f'{k}: "{s}"')
    lines.append('source: "yfinance"')
    lines.append("---")
    return "\n".join(lines)


def fetch_and_save(date: str, inbox_dir: Path, watchlist: list[str]) -> int:
    """Save one .txt per analyst change on `date` for tickers in watchlist."""
    if not watchlist:
        return 0
    inbox_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for ticker in watchlist:
        try:
            t = yf.Ticker(ticker)
            df = t.upgrades_downgrades
        except Exception as exc:
            log.warning("yfinance: upgrades_downgrades fetch failed for %s: %s", ticker, exc)
            continue
        if df is None or df.empty:
            continue
        # The index is GradeDate (DatetimeIndex, may be timezone-aware)
        df = df.reset_index()
        date_col = "GradeDate" if "GradeDate" in df.columns else df.columns[0]
        for _, row in df.iterrows():
            row_date = str(row[date_col])[:10]
            if row_date != date:
                continue
            firm = str(row.get("Firm", "")).strip()
            change = AnalystChange(
                ticker=ticker.upper(),
                grade_date=row_date,
                firm=firm,
                from_grade=str(row.get("FromGrade", "")).strip(),
                to_grade=str(row.get("ToGrade", "")).strip(),
                action=str(row.get("Action", "")).strip(),
            )
            safe_firm = "".join(c for c in firm if c.isalnum())[:20] or "unknown"
            out_txt = inbox_dir / f"yf_{ticker.upper()}_{safe_firm}_{row_date}.txt"
            if out_txt.exists():
                continue
            body = (
                f"Ticker: {change.ticker}\n"
                f"Date: {change.grade_date}\n"
                f"Firm: {change.firm}\n"
                f"Rating: {change.from_grade} -> {change.to_grade}\n"
                f"Action: {change.action}\n"
            )
            out_txt.write_text(_yaml_front_matter(change) + "\n\n" + body, encoding="utf-8")
            saved += 1
    return saved
