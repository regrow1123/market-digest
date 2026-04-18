"""SEC EDGAR fetcher — watchlist-focused 8-K filings.

For each ticker in the watchlist:
  1. Resolve ticker -> CIK (via cached company_tickers.json)
  2. Fetch https://data.sec.gov/submissions/CIK{padded}.json
  3. Extract filings filed today (or yesterday if we run after market close)
     that match the requested form types.
  4. Save each filing as inbox/{date}/sec_{ticker}_{accession}.txt with a
     YAML front matter and the index page URL.

EDGAR requires a descriptive User-Agent including a contact email; set
SEC_EDGAR_UA in the environment.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass
class SecFiling:
    ticker: str
    company: str
    cik: str
    form: str
    filed: str  # YYYY-MM-DD
    accession: str
    items: str  # e.g. "2.02,9.01"
    primary_doc: str
    index_url: str


def _load_ticker_map(cache_path: Path, user_agent: str) -> dict[str, tuple[str, str]]:
    """Return {ticker: (padded_cik, company_name)}. Cached on disk for 7 days."""
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < 7 * 86400:
        data = json.loads(cache_path.read_text())
    else:
        resp = requests.get(TICKER_MAP_URL, headers={"User-Agent": user_agent}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))
    mapping: dict[str, tuple[str, str]] = {}
    for row in data.values():
        ticker = str(row["ticker"]).upper()
        cik_padded = str(row["cik_str"]).zfill(10)
        mapping[ticker] = (cik_padded, row["title"])
    return mapping


def _recent_filings_for(cik: str, user_agent: str) -> dict:
    url = SUBMISSIONS_URL.format(cik=cik)
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _yaml_front_matter(f: SecFiling) -> str:
    lines = ["---"]
    for k, v in asdict(f).items():
        s = str(v).replace("\n", " ").strip()
        lines.append(f'{k}: "{s}"')
    lines.append('source: "sec_edgar"')
    lines.append("---")
    return "\n".join(lines)


def fetch_and_save(
    date: str,
    inbox_dir: Path,
    watchlist: list[str],
    form_types: list[str],
    max_items: int,
    user_agent: str,
    cache_dir: Path,
) -> int:
    """Fetch today's filings for watchlist tickers and save them as .txt.

    Returns the number of filings saved.
    """
    if not watchlist:
        return 0
    inbox_dir.mkdir(parents=True, exist_ok=True)
    ticker_map = _load_ticker_map(cache_dir / "sec_tickers.json", user_agent)
    saved = 0
    for ticker in watchlist:
        if saved >= max_items:
            break
        key = ticker.upper()
        if key not in ticker_map:
            log.warning("sec: ticker %s not in company map", ticker)
            continue
        cik, company = ticker_map[key]
        try:
            data = _recent_filings_for(cik, user_agent)
        except Exception as exc:
            log.warning("sec: submissions fetch failed for %s: %s", ticker, exc)
            continue
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        items_list = recent.get("items", [""] * len(forms))
        primary_docs = recent.get("primaryDocument", [""] * len(forms))
        for form, filed, acc, items, primary in zip(forms, dates, accs, items_list, primary_docs):
            if filed != date or form not in form_types:
                continue
            acc_nodashes = acc.replace("-", "")
            index_url = f"{ARCHIVES_BASE}/{int(cik)}/{acc_nodashes}/{acc}-index.htm"
            filing = SecFiling(
                ticker=key,
                company=company,
                cik=cik,
                form=form,
                filed=filed,
                accession=acc,
                items=items or "",
                primary_doc=primary or "",
                index_url=index_url,
            )
            out_txt = inbox_dir / f"sec_{key}_{acc_nodashes}.txt"
            if out_txt.exists():
                continue
            body = f"Form: {form}\nFiled: {filed}\nItems: {items}\nIndex: {index_url}\n"
            out_txt.write_text(_yaml_front_matter(filing) + "\n\n" + body, encoding="utf-8")
            saved += 1
            if saved >= max_items:
                break
        time.sleep(0.15)  # SEC allows 10 req/sec; stay polite
    return saved
