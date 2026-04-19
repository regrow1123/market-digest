# Analyst Enrichment + Deep Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace yfinance with FMP Free for target prices + broader US coverage, attach a one-line company blurb to every card via Claude Sonnet, and add an on-demand deep research CLI that renders into the existing static site.

**Architecture:** `run.py` pipeline gains two new stages after `summarize`: `enrich` (fills `company_blurb` via FMP profile + Sonnet) and (unchanged) `web.build`. A new `market_digest.research` CLI writes per-ticker markdown files to NAS; `web.build` auto-renders them and links from the relevant detail page.

**Tech Stack:** FMP REST API (free tier), Claude CLI subprocess (Sonnet + Opus), pydantic, Jinja2, markdown-it-py — all already in the project.

**Spec:** `docs/superpowers/specs/2026-04-20-analyst-enrichment-research-design.md`

---

## File Structure

**Create:**
- `market_digest/fetchers/fmp.py` — FMP global ratings feed fetcher (replaces yfinance)
- `market_digest/enrich.py` — post-summarize blurb enrichment
- `market_digest/research.py` — on-demand deep research CLI entry
- `market_digest/web/templates/research_page.html.j2` — render research markdown into the site
- `tests/test_fmp.py`
- `tests/test_enrich.py`
- `tests/test_research_cli.py`
- `tests/web/test_research_render.py`

**Modify:**
- `market_digest/models.py` — add `company_blurb: str | None` to Item
- `market_digest/run.py` — drop yfinance call, add FMP call, call enrich after validate
- `market_digest/web/builder.py` — scan `research/` dir, render research pages, link in detail
- `market_digest/web/templates/card_page.html.j2` — render blurb under card
- `market_digest/web/templates/detail_page.html.j2` — render blurb + research link
- `market_digest/web/assets/style.css` — `.blurb` class styling
- `config.yaml` — remove `yfinance`, add `fmp`, add `claude.blurb_model`, `claude.research_model`, `claude.blurb_cache_ttl_days`
- `.env.example` — add `FMP_API_KEY`
- `CLAUDE.md` — note that `company_blurb` is filled post-hoc; Claude must NOT output it

**Delete:**
- `market_digest/fetchers/yfinance_recs.py`
- `tests/test_yfinance_recs.py` (if exists — none currently)

---

## Task 1: FMP fetcher (config + request layer)

**Files:**
- Create: `market_digest/fetchers/fmp.py`
- Create: `tests/test_fmp.py`
- Modify: `config.yaml`
- Modify: `.env.example`

**Background:** FMP exposes `/api/v3/upgrades-downgrades-rss-feed` returning a JSON list of recent grade changes across the market. Each record contains at minimum: `symbol`, `publishedDate`, `newGrade`, `previousGrade`, `gradingCompany`, `action`, `priceWhenPosted`, and optionally `newsURL`, `newsTitle`. The endpoint is on the free tier. The implementer should make one live test call to confirm the exact schema before wiring it up.

- [ ] **Step 1: Add `fmp` section to `config.yaml`**

Replace the existing `yfinance:` block with:

```yaml
fmp:
  enabled: true
  min_market_cap_usd: 1000000000
  target_change_threshold: 0.10   # 10%; used only when targets are present
  page_limit: 3                   # pages of feed to fetch (100 records each)
  request_interval_sec: 1

# watchlist is still consumed by sec_edgar; keep it at the top level
watchlist:
  - AAPL
  - MSFT
  - NVDA
  - GOOGL
  - AMZN
  - META
  - TSLA
  - AVGO
  - AMD
  - TSM
```

Then update the `sec_edgar` section and the reference in `run.py` later to read `cfg["watchlist"]` instead of `cfg["yfinance"]["watchlist"]`.

- [ ] **Step 2: Add `FMP_API_KEY` to `.env.example`**

Append to `.env.example`:

```
# Financial Modeling Prep free API key (250 calls/day)
# Register at https://site.financialmodelingprep.com/developer/docs
FMP_API_KEY=
```

- [ ] **Step 3: Smoke-test FMP manually before coding**

Run (user provides FMP_API_KEY in their .env beforehand):

```bash
cd /home/sund4y/market-digest
source .env
curl -s "https://financialmodelingprep.com/api/v3/upgrades-downgrades-rss-feed?page=0&apikey=${FMP_API_KEY}" | python -m json.tool | head -60
```

Record the actual field names and types. If any field differs from what this plan assumes (e.g., `gradingCompany` vs `publisher`), use the actual names when implementing and note the divergence in the commit message.

- [ ] **Step 4: Write failing fetcher tests**

Create `tests/test_fmp.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

from market_digest.fetchers.fmp import _filter_records, fetch_and_save


def test_filter_keeps_initiate_regardless_of_target_change():
    records = [
        {"symbol": "AAPL", "action": "initiate", "newGrade": "Buy",
         "previousGrade": "", "gradingCompany": "MS", "publishedDate": "2026-04-20 12:00:00",
         "priceWhenPosted": 150.0, "priceTarget": 170.0, "previousPriceTarget": None,
         "newsURL": "https://example.com/a", "newsTitle": "t"},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert len(kept) == 1


def test_filter_drops_below_mcap_floor():
    records = [
        {"symbol": "TINY", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 5.0, "priceTarget": 8.0, "previousPriceTarget": 6.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"TINY": 500_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert kept == []


def test_filter_drops_small_target_moves_on_non_initiate():
    records = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 150.0, "priceTarget": 155.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert kept == []


def test_filter_keeps_large_target_moves():
    records = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "X", "publishedDate": "2026-04-20",
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    mcap = {"AAPL": 2_000_000_000_000}
    kept = _filter_records(records, mcap, min_market_cap_usd=1_000_000_000,
                           target_change_threshold=0.10)
    assert len(kept) == 1


def test_fetch_and_save_writes_yaml_txt(tmp_path):
    rows = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "Morgan Stanley",
         "publishedDate": "2026-04-20 06:30:00",
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "https://x.com/r", "newsTitle": "MS upgrades AAPL"},
    ]
    profiles = {"AAPL": {"mktCap": 2_000_000_000_000, "companyName": "Apple Inc."}}

    with patch("market_digest.fetchers.fmp._fetch_feed", return_value=rows), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            target_change_threshold=0.10,
            page_limit=1,
            request_interval_sec=0,
        )
    assert n == 1
    out = list(tmp_path.glob("fmp_*.txt"))
    assert len(out) == 1
    content = out[0].read_text(encoding="utf-8")
    assert "ticker: \"AAPL\"" in content
    assert "firm: \"Morgan Stanley\"" in content
    assert "target: \"150.0 -> 180.0\"" in content
    assert "Rating: Hold -> Buy" in content


def test_fetch_and_save_filters_by_date(tmp_path):
    rows = [
        {"symbol": "AAPL", "action": "upgrade", "newGrade": "Buy",
         "previousGrade": "Hold", "gradingCompany": "MS",
         "publishedDate": "2026-04-19 06:30:00",  # different date
         "priceWhenPosted": 150.0, "priceTarget": 180.0, "previousPriceTarget": 150.0,
         "newsURL": "", "newsTitle": ""},
    ]
    profiles = {"AAPL": {"mktCap": 2_000_000_000_000, "companyName": "Apple Inc."}}
    with patch("market_digest.fetchers.fmp._fetch_feed", return_value=rows), \
         patch("market_digest.fetchers.fmp._fetch_profile", side_effect=lambda t, k: profiles.get(t)):
        n = fetch_and_save(
            date="2026-04-20",
            inbox_dir=tmp_path,
            api_key="dummy",
            min_market_cap_usd=1_000_000_000,
            target_change_threshold=0.10,
            page_limit=1,
            request_interval_sec=0,
        )
    assert n == 0
```

- [ ] **Step 5: Run tests (expect failure)**

```bash
cd /home/sund4y/market-digest
uv run pytest tests/test_fmp.py -v
```

Expected: `ImportError`.

- [ ] **Step 6: Implement `market_digest/fetchers/fmp.py`**

```python
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
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_fmp.py -v
```

Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add market_digest/fetchers/fmp.py tests/test_fmp.py config.yaml .env.example
git commit -m "feat(fetchers): add FMP global rating feed fetcher"
```

---

## Task 2: Wire FMP into run.py and remove yfinance

**Files:**
- Delete: `market_digest/fetchers/yfinance_recs.py`
- Modify: `market_digest/run.py`
- Modify: `market_digest/fetchers/__init__.py` (if it exports `yfinance_recs`)

- [ ] **Step 1: Inspect and clean fetcher package exports**

```bash
cd /home/sund4y/market-digest
cat market_digest/fetchers/__init__.py
```

If it contains `from market_digest.fetchers import yfinance_recs` or similar, remove that line in the same commit as the rest.

- [ ] **Step 2: Remove yfinance module**

```bash
git rm market_digest/fetchers/yfinance_recs.py
```

Also remove `yfinance>=0.2.40` from `pyproject.toml` dependencies list.

Run `uv sync` to prune the lock file.

- [ ] **Step 3: Update `run.py`**

In `market_digest/run.py`, apply these changes:

Replace the import block:

```python
from market_digest.fetchers import hankyung, sec_edgar, yfinance_recs
```

with:

```python
from market_digest.fetchers import fmp, hankyung, sec_edgar
```

Replace the existing `yfinance` block (`if cfg["yfinance"]["enabled"]:` ... `total += n`) with:

```python
    if cfg["fmp"]["enabled"]:
        try:
            api_key = os.environ.get("FMP_API_KEY", "")
            n = fmp.fetch_and_save(
                date=date,
                inbox_dir=inbox_dir,
                api_key=api_key,
                min_market_cap_usd=cfg["fmp"]["min_market_cap_usd"],
                target_change_threshold=cfg["fmp"]["target_change_threshold"],
                page_limit=cfg["fmp"]["page_limit"],
                request_interval_sec=cfg["fmp"]["request_interval_sec"],
            )
            log.info("fmp: %d rating changes saved", n)
            total += n
        except Exception as exc:
            log.exception("fmp fetcher failed: %s", exc)
```

Update the `sec_edgar` call so the watchlist reference reads from the top-level key:

```python
            n = sec_edgar.fetch_and_save(
                date=date,
                inbox_dir=inbox_dir,
                watchlist=cfg["watchlist"],
                form_types=cfg["sec_edgar"]["form_types"],
                max_items=cfg["sec_edgar"]["max_items"],
                user_agent=ua,
                cache_dir=PROJECT_DIR / ".cache",
            )
```

- [ ] **Step 4: Verify nothing else references yfinance**

```bash
cd /home/sund4y/market-digest
grep -rn "yfinance" --include="*.py" . || echo "OK"
grep -rn "yfinance" config.yaml pyproject.toml || echo "OK"
```

Expected: no matches. If matches remain, clean them up.

- [ ] **Step 5: Run tests + import check**

```bash
uv run pytest -v
uv run python -c "import market_digest.run; print('ok')"
```

Expected: all tests pass, import prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(run): switch analyst source from yfinance to FMP"
```

---

## Task 3: Add `company_blurb` to Item schema

**Files:**
- Modify: `market_digest/models.py`
- Modify: `tests/web/test_models.py`

- [ ] **Step 1: Extend model test**

Append to `tests/web/test_models.py`:

```python
def test_item_accepts_company_blurb():
    item = Item.model_validate({
        "id": "us-rating-0",
        "headline": "h",
        "body_md": "b",
        "company_blurb": "미국 스마트폰 제조사",
    })
    assert item.company_blurb == "미국 스마트폰 제조사"


def test_item_company_blurb_defaults_to_none():
    item = Item.model_validate({"id": "x", "headline": "h", "body_md": "b"})
    assert item.company_blurb is None
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_models.py::test_item_accepts_company_blurb tests/web/test_models.py::test_item_company_blurb_defaults_to_none -v
```

Expected: FAIL with `company_blurb` attribute missing.

- [ ] **Step 3: Add the field**

In `market_digest/models.py`, inside class `Item`, add between `url` and the end of the class:

```python
    company_blurb: str | None = None
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/ -v
```

Expected: all pass (including the two new tests).

- [ ] **Step 5: Commit**

```bash
git add market_digest/models.py tests/web/test_models.py
git commit -m "feat(models): add company_blurb field to Item"
```

---

## Task 4: Blurb cache helpers

**Files:**
- Create: `market_digest/enrich.py`
- Create: `tests/test_enrich.py`

- [ ] **Step 1: Write failing cache tests**

Create `tests/test_enrich.py`:

```python
import json
from datetime import date, timedelta
from pathlib import Path

from market_digest.enrich import BlurbCache


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


def test_cache_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "blurbs.json"
    path.write_text("{{{ not json")
    cache = BlurbCache(path, ttl_days=90, today=date(2026, 4, 20))
    assert cache.get("AAPL") is None
    cache.set("AAPL", "x", source="t")
    cache.save()
    assert json.loads(path.read_text())["AAPL"]["blurb"] == "x"
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement cache**

Create `market_digest/enrich.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add market_digest/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): blurb cache with 90-day TTL"
```

---

## Task 5: FMP profile lookup for blurb source

**Files:**
- Modify: `market_digest/enrich.py`
- Modify: `tests/test_enrich.py`

- [ ] **Step 1: Extend tests**

Append to `tests/test_enrich.py`:

```python
from unittest.mock import patch

from market_digest.enrich import fetch_company_description


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
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: ImportError on `fetch_company_description`.

- [ ] **Step 3: Add function to `market_digest/enrich.py`**

Append to `market_digest/enrich.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: 8 passed (3 new + 5 prior).

- [ ] **Step 5: Commit**

```bash
git add market_digest/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): FMP profile description lookup"
```

---

## Task 6: Sonnet blurb generator

**Files:**
- Modify: `market_digest/enrich.py`
- Modify: `tests/test_enrich.py`

- [ ] **Step 1: Extend tests**

Append to `tests/test_enrich.py`:

```python
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
    # First positional arg should be a list starting with the CLI path
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
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_enrich.py -v
```

- [ ] **Step 3: Implement generator**

Append to `market_digest/enrich.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: 11 passed (3 new + 8 prior).

- [ ] **Step 5: Commit**

```bash
git add market_digest/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): Sonnet blurb generator"
```

---

## Task 7: Enrich orchestrator (reads JSON, fills blurbs, writes JSON)

**Files:**
- Modify: `market_digest/enrich.py`
- Modify: `tests/test_enrich.py`

- [ ] **Step 1: Extend tests**

Append to `tests/test_enrich.py`:

```python
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
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_enrich.py -v
```

- [ ] **Step 3: Implement `enrich_digest`**

Append to `market_digest/enrich.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_enrich.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add market_digest/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): orchestrator — cache hit or Sonnet+FMP fill"
```

---

## Task 8: Wire enrich into run.py + config + CLAUDE.md guidance

**Files:**
- Modify: `market_digest/run.py`
- Modify: `config.yaml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Extend `config.yaml` `claude:` block**

Add three keys inside the `claude:` section:

```yaml
  blurb_model: "claude-sonnet-4-6"
  research_model: "claude-opus-4-7"
  blurb_cache_ttl_days: 90
```

- [ ] **Step 2: Add enrich step to `run.py`**

In `market_digest/run.py`, after the `_validate_digest` call block and before the `web_build` call, insert:

```python
    try:
        from market_digest.enrich import enrich_digest
        enrich_digest(
            json_path=result.json_path,
            cache_path=nas_dir / "blurbs.json",
            api_key=os.environ.get("FMP_API_KEY", ""),
            claude_cli=cfg["claude"]["cli_path"],
            model=cfg["claude"]["blurb_model"],
            ttl_days=cfg["claude"]["blurb_cache_ttl_days"],
        )
        log.info("enrich: blurbs refreshed")
    except Exception as exc:
        log.exception("enrich failed (continuing): %s", exc)
```

- [ ] **Step 3: Append `company_blurb` guidance to `CLAUDE.md`**

Add this paragraph to `CLAUDE.md` directly below the `items[].url` bullet (and before the sentence "그룹이 없는 섹션은..."):

```markdown
- `items[].company_blurb`: **이 필드는 생성하지 말고 비워둘 것**. 후처리 단계에서 외부 소스로 자동 채운다.
```

- [ ] **Step 4: Verify import + tests**

```bash
cd /home/sund4y/market-digest
uv run python -c "import market_digest.run"
uv run pytest -v
```

Expected: import OK, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add market_digest/run.py config.yaml CLAUDE.md
git commit -m "feat(run): call enrich between validate and build"
```

---

## Task 9: Card page shows blurb

**Files:**
- Modify: `market_digest/web/templates/card_page.html.j2`
- Modify: `tests/web/test_render.py`

- [ ] **Step 1: Extend render test**

Append to `tests/web/test_render.py`:

```python
def test_card_renders_company_blurb_when_present():
    d = Digest.model_validate({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{
                "id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                "headline": "MS upgrade", "body_md": "-",
                "company_blurb": "미국 스마트폰·서비스 생태계",
            }],
        }],
    })
    html = render_card_page(d, prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    blurb = soup.select_one("a.card .blurb")
    assert blurb is not None
    assert "미국 스마트폰" in blurb.text


def test_card_omits_blurb_span_when_none():
    d = Digest.model_validate({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{"id": "us-rating-0", "headline": "h", "body_md": "-"}],
        }],
    })
    html = render_card_page(d, prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("a.card .blurb") is None
```

- [ ] **Step 2: Run (expect failure on the first)**

```bash
uv run pytest tests/web/test_render.py::test_card_renders_company_blurb_when_present -v
```

- [ ] **Step 3: Update card template**

In `market_digest/web/templates/card_page.html.j2`, inside the `<a class="card" ...>` anchor, add a conditional span on its own line (after the `{% if item.opinion or item.target %}` block but BEFORE the closing `</a>`):

```jinja
{% if item.company_blurb %}<span class="blurb">{{ item.company_blurb }}</span>{% endif %}
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/ -v
```

Expected: all tests pass including the new ones.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/templates/card_page.html.j2 tests/web/test_render.py
git commit -m "feat(web): render company blurb under card headline"
```

---

## Task 10: Detail page shows blurb

**Files:**
- Modify: `market_digest/web/templates/detail_page.html.j2`
- Modify: `tests/web/test_render.py`

- [ ] **Step 1: Extend render test**

Append to `tests/web/test_render.py`:

```python
def test_detail_renders_company_blurb_when_present():
    d = Digest.model_validate({
        "date": "2026-04-20",
        "groups": [{
            "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
            "items": [{
                "id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                "headline": "h", "body_md": "b",
                "company_blurb": "미국 스마트폰·서비스",
            }],
        }],
    })
    html = render_detail_page(
        digest=d, group_index=0, item_index=0, flat_ids=["us-rating-0"]
    )
    soup = BeautifulSoup(html, "html.parser")
    b = soup.select_one("article .blurb")
    assert b is not None and "미국 스마트폰" in b.text
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_render.py::test_detail_renders_company_blurb_when_present -v
```

- [ ] **Step 3: Update detail template**

In `market_digest/web/templates/detail_page.html.j2`, add this line immediately after the `</h1>` closing tag (i.e. between the h1 block and the `{% if item.opinion or item.target %}` block):

```jinja
{% if item.company_blurb %}<p class="blurb">{{ item.company_blurb }}</p>{% endif %}
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/ -v
```

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/templates/detail_page.html.j2 tests/web/test_render.py
git commit -m "feat(web): render company blurb on detail page"
```

---

## Task 11: Blurb styling

**Files:**
- Modify: `market_digest/web/assets/style.css`

- [ ] **Step 1: Append blurb styles**

Append to `market_digest/web/assets/style.css`:

```css
a.card .blurb {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
  font-weight: normal;
}

article .blurb {
  color: var(--muted);
  font-size: 14px;
  margin: 0 0 12px;
}
```

- [ ] **Step 2: Commit**

```bash
git add market_digest/web/assets/style.css
git commit -m "feat(web): style company blurb on card and detail"
```

---

## Task 12: Research CLI

**Files:**
- Create: `market_digest/research.py`
- Create: `tests/test_research_cli.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_research_cli.py`:

```python
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from market_digest.research import build_output_path, main, run_research


def test_build_output_path(tmp_path):
    p = build_output_path(root=tmp_path, ticker="AAPL", date_str="2026-04-20")
    assert p == tmp_path / "research" / "AAPL-2026-04-20.md"


def test_run_research_dry_run_writes_placeholder(tmp_path):
    out = tmp_path / "research" / "AAPL-2026-04-20.md"
    run_research(
        ticker="AAPL",
        date_str="2026-04-20",
        out_path=out,
        claude_cli="/bin/claude",
        model="m",
        context=None,
        dry_run=True,
    )
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "AAPL" in text and "2026-04-20" in text


def test_run_research_invokes_claude_with_web_tools(tmp_path):
    out = tmp_path / "research" / "NVDA-2026-04-20.md"
    out.parent.mkdir(parents=True)
    out.write_text("placeholder before call", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        class R:
            stdout = ""
            stderr = ""
            returncode = 0
        return R()

    with patch("market_digest.research.subprocess.run", side_effect=fake_run):
        run_research(
            ticker="NVDA",
            date_str="2026-04-20",
            out_path=out,
            claude_cli="/bin/claude",
            model="claude-opus-4-7",
            context=None,
            dry_run=False,
        )

    cmd = captured["cmd"]
    assert cmd[0] == "/bin/claude"
    assert "--allowed-tools" in cmd
    idx = cmd.index("--allowed-tools")
    tools = cmd[idx + 1]
    assert "WebSearch" in tools
    assert "WebFetch" in tools
    assert "Write" in tools
    assert str(out) in " ".join(cmd)


def test_main_exit_zero_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("market_digest.research.run_research") as rr:
        rc = main([
            "AAPL",
            "--date", "2026-04-20",
            "--root", str(tmp_path),
            "--claude-cli", "/bin/claude",
            "--model", "m",
            "--dry-run",
        ])
    assert rc == 0
    rr.assert_called_once()
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_research_cli.py -v
```

- [ ] **Step 3: Implement `research.py`**

Create `market_digest/research.py`:

```python
"""Deep research CLI — on-demand per-ticker research backed by claude -p.

Usage:
    python -m market_digest.research AAPL [--date 2026-04-20] [--context "..."]

Writes:
    {root}/research/{TICKER}-{DATE}.md

The CLI enables WebSearch + WebFetch + Write on claude so it can pull
from public sources (Yahoo Finance /analyst, SA free pages, news,
Motley Fool, transcripts).
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import zoneinfo
from datetime import datetime
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
KST = zoneinfo.ZoneInfo("Asia/Seoul")


def build_output_path(*, root: Path, ticker: str, date_str: str) -> Path:
    return root / "research" / f"{ticker.upper()}-{date_str}.md"


def _prompt(ticker: str, date_str: str, out_path: Path, context: str | None) -> str:
    extra = f"\n사용자 포커스: {context}" if context else ""
    return (
        f"{ticker} 종목에 대한 딥 리서치 리포트를 한국어로 작성하라. "
        f"날짜 기준은 {date_str} (KST). 공개 자료만 사용: "
        f"Yahoo Finance /analyst 페이지, Seeking Alpha 무료 요약, "
        f"Motley Fool, Bloomberg 무료 기사, 실적 transcript. "
        f"다음 섹션으로 구성: "
        f"## 회사 개요, ## 주요 애널리스트 의견 (하우스명+요지+출처), "
        f"## Thesis, ## 리스크, ## 최근 이벤트, ## 출처. "
        f"WebSearch/WebFetch 로 수집하고, 출처 URL 을 각 인용마다 붙여라.{extra} "
        f"완성된 Markdown 을 Write 도구로 {out_path} 에 저장하라."
    )


def run_research(
    *,
    ticker: str,
    date_str: str,
    out_path: Path,
    claude_cli: str,
    model: str,
    context: str | None,
    dry_run: bool,
    timeout_sec: int = 600,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        out_path.write_text(
            f"# {ticker.upper()} 딥 리서치 — {date_str}\n\n"
            f"(dry-run placeholder)\n",
            encoding="utf-8",
        )
        return

    cmd = [
        claude_cli,
        "-p", _prompt(ticker, date_str, out_path, context),
        "--model", model,
        "--allowed-tools", "WebSearch,WebFetch,Read,Write",
        "--permission-mode", "dontAsk",
        "--output-format", "text",
        "--no-session-persistence",
    ]
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True,
        timeout=timeout_sec, check=False,
    )
    if proc.returncode != 0:
        log.error("research: claude rc=%s stderr=%s",
                  proc.returncode, proc.stderr[:400])
        raise RuntimeError(f"claude research failed (rc={proc.returncode})")
    if not out_path.exists():
        raise RuntimeError(f"claude did not write {out_path}")


def _load_cfg() -> dict:
    with open(PROJECT_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="market-digest deep research")
    p.add_argument("ticker")
    p.add_argument("--date", help="YYYY-MM-DD (default: today KST)")
    p.add_argument("--context", default=None)
    p.add_argument("--root", help="NAS root; defaults to config.yaml nas_report_dir")
    p.add_argument("--claude-cli", help="override claude CLI path")
    p.add_argument("--model", help="override research model")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = _load_cfg()
    root = Path(args.root) if args.root else Path(cfg["nas_report_dir"])
    claude_cli = args.claude_cli or cfg["claude"]["cli_path"]
    model = args.model or cfg["claude"]["research_model"]
    date_str = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    out_path = build_output_path(root=root, ticker=args.ticker, date_str=date_str)
    try:
        run_research(
            ticker=args.ticker, date_str=date_str, out_path=out_path,
            claude_cli=claude_cli, model=model,
            context=args.context, dry_run=args.dry_run,
        )
    except Exception as exc:
        log.error("research failed: %s", exc)
        return 1
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_research_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add market_digest/research.py tests/test_research_cli.py
git commit -m "feat(research): on-demand deep research CLI"
```

---

## Task 13: Web build renders research pages + detail link

**Files:**
- Modify: `market_digest/web/builder.py`
- Modify: `market_digest/web/templates/detail_page.html.j2`
- Create: `market_digest/web/templates/research_page.html.j2`
- Create: `tests/web/test_research_render.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_research_render.py`:

```python
import json
from pathlib import Path

from bs4 import BeautifulSoup

from market_digest.web import build


def _write(nas: Path, date: str, groups: list[dict]) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


def test_build_renders_research_md_into_site(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text(
        "# AAPL 딥 리서치 — 2026-04-20\n\n## 회사 개요\n- detail alpha\n",
        encoding="utf-8",
    )

    site = build(tmp_path)
    research_page = site / "2026-04-20" / "us-rating-0.research.html"
    assert research_page.is_file()
    soup = BeautifulSoup(research_page.read_text(encoding="utf-8"), "html.parser")
    assert "detail alpha" in soup.text


def test_detail_page_links_to_research_when_present(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text(
        "# AAPL\n- x\n", encoding="utf-8",
    )

    site = build(tmp_path)
    detail = site / "2026-04-20" / "us-rating-0.html"
    soup = BeautifulSoup(detail.read_text(encoding="utf-8"), "html.parser")
    link = soup.select_one("a.research-link")
    assert link is not None
    assert link["href"] == "us-rating-0.research.html"


def test_detail_page_omits_research_link_when_absent(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "us", "category": "rating", "title": "미국 애널리스트 변경",
        "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                   "headline": "h", "body_md": "b"}],
    }])
    # no research md written

    site = build(tmp_path)
    detail = site / "2026-04-20" / "us-rating-0.html"
    soup = BeautifulSoup(detail.read_text(encoding="utf-8"), "html.parser")
    assert soup.select_one("a.research-link") is None


def test_build_skips_research_md_without_ticker(tmp_path):
    _write(tmp_path, "2026-04-20", [{
        "region": "kr", "category": "industry", "title": "국내 시황·산업",
        "items": [{"id": "kr-industry-0", "headline": "h", "body_md": "b"}],
    }])
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "AAPL-2026-04-20.md").write_text("# AAPL\n", encoding="utf-8")

    site = build(tmp_path)
    # no research page should be generated when no item has that ticker on that date
    assert not list((site / "2026-04-20").glob("*.research.html"))
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_research_render.py -v
```

- [ ] **Step 3: Create `research_page.html.j2`**

Create `market_digest/web/templates/research_page.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}🔍 {{ item.name or item.ticker }} 딥 리서치 · {{ digest.date }}{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="{{ item.id }}.html">←&nbsp;상세로 돌아가기</a>
</header>
<article>
  <div class="body">
    {{ body_html|safe }}
  </div>
</article>
{% endblock %}
```

- [ ] **Step 4: Add research rendering to `web.build`**

In `market_digest/web/builder.py`, update `build()` so that after the detail pages are written for a given day, it looks for matching research markdown and renders a research page. Replace the existing per-item detail loop with:

```python
        for gi, group in enumerate(digest.groups):
            for ii, item in enumerate(group.items):
                detail_html = render_detail_page(
                    digest=digest,
                    group_index=gi,
                    item_index=ii,
                    flat_ids=flat_ids,
                    has_research=_research_md_exists(nas_dir, item.ticker, digest.date),
                )
                (day_dir / f"{item.id}.html").write_text(detail_html, encoding="utf-8")

                research_md = _research_md_path(nas_dir, item.ticker, digest.date)
                if research_md is not None and research_md.exists():
                    research_html = render_research_page(
                        digest=digest, item=item,
                        body_html=_md.render(research_md.read_text(encoding="utf-8")),
                    )
                    (day_dir / f"{item.id}.research.html").write_text(
                        research_html, encoding="utf-8"
                    )
```

Add these helpers near the top of `builder.py` (after existing helpers):

```python
def _research_md_path(nas_dir: Path, ticker: str | None, date_str: str) -> Path | None:
    if not ticker:
        return None
    return nas_dir / "research" / f"{ticker.upper()}-{date_str}.md"


def _research_md_exists(nas_dir: Path, ticker: str | None, date_str: str) -> bool:
    p = _research_md_path(nas_dir, ticker, date_str)
    return p is not None and p.exists()
```

Add `render_research_page`:

```python
def render_research_page(*, digest: Digest, item, body_html: str) -> str:
    template = _env.get_template("research_page.html.j2")
    return template.render(
        digest=digest,
        item=item,
        body_html=body_html,
        asset_prefix="../",
    )
```

Extend `render_detail_page` signature to accept `has_research` and pass it to the template:

```python
def render_detail_page(
    *,
    digest: Digest,
    group_index: int,
    item_index: int,
    flat_ids: list[str],
    has_research: bool = False,
) -> str:
    group = digest.groups[group_index]
    item = group.items[item_index]
    current = item.id
    pos = flat_ids.index(current)
    prev_id = flat_ids[pos - 1] if pos > 0 else None
    next_id = flat_ids[pos + 1] if pos < len(flat_ids) - 1 else None
    body_html = _md.render(item.body_md)
    template = _env.get_template("detail_page.html.j2")
    return template.render(
        digest=digest,
        item=item,
        prev_id=prev_id,
        next_id=next_id,
        body_html=body_html,
        has_research=has_research,
        asset_prefix="../",
    )
```

- [ ] **Step 5: Update detail template for the link**

In `market_digest/web/templates/detail_page.html.j2`, add this line immediately BEFORE the closing `</article>` tag (i.e. after the `{% if item.url %}...{% endif %}` line):

```jinja
{% if has_research %}<p class="source"><a class="research-link" href="{{ item.id }}.research.html" rel="noopener">🔍 딥 리서치</a></p>{% endif %}
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/web/ -v
```

Expected: all pass (new + prior).

- [ ] **Step 7: Commit**

```bash
git add market_digest/web/builder.py market_digest/web/templates/research_page.html.j2 market_digest/web/templates/detail_page.html.j2 tests/web/test_research_render.py
git commit -m "feat(web): render research markdown and link from detail page"
```

---

## Task 14: Deploy note for FMP key

**Files:**
- Modify: `deploy/README.md`

- [ ] **Step 1: Append FMP setup section**

Append to `deploy/README.md`:

```markdown
## 5. FMP API key

1. Register free account at https://site.financialmodelingprep.com/developer/docs
2. Copy API key into `.env`:
   ```
   FMP_API_KEY=your_key_here
   ```
3. Free tier: 250 calls/day. Daily run uses ~10-30 calls (feed + profiles).
```

- [ ] **Step 2: Commit**

```bash
git add deploy/README.md
git commit -m "docs(deploy): FMP API key setup note"
```

---

## Final checks

- [ ] **Full test run**

```bash
cd /home/sund4y/market-digest
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Import sanity**

```bash
uv run python -c "import market_digest.run; import market_digest.enrich; import market_digest.research"
```

Expected: prints nothing, exit 0.

- [ ] **Manual end-to-end smoke (optional, requires FMP_API_KEY + claude login)**

```bash
cd /home/sund4y/market-digest
uv run python -m market_digest.run --date 2026-04-20
uv run python -m market_digest.research AAPL --date 2026-04-20 --dry-run
ls -la /mnt/nas/market-digest/site/2026-04-20/ | grep research
```

Confirm: site regenerates, dry-run research file appears, detail page shows "🔍 딥 리서치" link.
