# Dynamic Site + Research Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static-site generator with a FastAPI app that renders pages on demand from NAS JSON, and adds an async deep-research trigger (POST + polling) for both US and KR tickers.

**Architecture:** FastAPI + Jinja2 (reusing current templates) under uvicorn + systemd. Caddy reverse-proxies to the app. In-memory `JobTracker` + `asyncio.run_in_executor` drives background research jobs. `run.py` drops its `web.build()` step — JSON writes are visible immediately.

**Tech Stack:** FastAPI, uvicorn, Jinja2, httpx (TestClient dep), pydantic — added to existing Python 3.12 / uv project.

**Spec:** `docs/superpowers/specs/2026-04-20-dynamic-site-research-trigger-design.md`

---

## File Structure

**Create:**
- `market_digest/web/app.py` — FastAPI application, routes
- `market_digest/web/data.py` — pure helpers: `load_digest`, `list_dates`, `prev_next`, `flat_ids`, `find_item`, `research_md_path`, `build_cards_index`
- `market_digest/web/jobs.py` — `Job`, `JobTracker`, `JobStatus`
- `market_digest/web/assets/research.js` — detail-page research trigger + polling
- `market_digest/web/assets/base.js` — global active-jobs badge
- `tests/web/test_data.py`, `tests/web/test_jobs.py`, `tests/web/test_app.py`
- `deploy/market-digest-web.service.example`

**Modify:**
- `market_digest/research.py` — split prompt builder, add KR vs US branch
- `market_digest/run.py` — remove `web.build()` call
- `market_digest/web/__init__.py` — drop `build` export
- `market_digest/web/templates/base.html.j2` — global badge + base.js
- `market_digest/web/templates/card_page.html.j2` — URL scheme change (`{id}.html` → `{id}`)
- `market_digest/web/templates/detail_page.html.j2` — research button/link conditional + URL scheme + include research.js
- `market_digest/web/templates/search.html.j2` — URL scheme (card results)
- `market_digest/web/assets/search.js` — URL scheme (result links)
- `config.yaml` — `web:` section
- `pyproject.toml` — `fastapi`, `uvicorn`, `httpx` deps
- `deploy/Caddyfile.example` — `reverse_proxy` instead of `file_server`
- `deploy/README.md` — systemd + reverse proxy setup
- `tests/test_research_cli.py` — KR prompt coverage

**Delete:**
- `market_digest/web/builder.py` (functions migrated to `data.py` + `app.py`)
- `tests/web/test_build.py`
- `tests/web/test_collect.py`
- `tests/web/test_index.py`
- `tests/web/test_render.py`
- `tests/web/test_research_render.py`

---

## Task 1: Add FastAPI deps + minimal app + health route

**Files:**
- Modify: `pyproject.toml`
- Create: `market_digest/web/app.py`
- Create: `tests/web/test_app.py`

- [ ] **Step 1: Add deps**

In `pyproject.toml` `dependencies` add:

```toml
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "httpx>=0.27",
```

Run:

```bash
cd /home/sund4y/market-digest
uv sync --extra dev
```

- [ ] **Step 2: Write failing health test**

Create `tests/web/test_app.py`:

```python
from fastapi.testclient import TestClient

from market_digest.web.app import create_app


def test_health_endpoint():
    app = create_app(nas_dir=None)
    with TestClient(app) as c:
        resp = c.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/web/test_app.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement app skeleton**

Create `market_digest/web/app.py`:

```python
"""FastAPI application for market-digest."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt

log = logging.getLogger(__name__)


def _build_env() -> Environment:
    env = Environment(
        loader=PackageLoader("market_digest.web", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["group_flag"] = lambda region: {"kr": "🇰🇷", "us": "🇺🇸"}.get(region, "")
    return env


def create_app(nas_dir: Path | None) -> FastAPI:
    """Build a FastAPI app bound to `nas_dir` (None = test stub)."""
    app = FastAPI(title="market-digest", docs_url=None, redoc_url=None)
    app.state.nas_dir = nas_dir
    app.state.env = _build_env()
    app.state.md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/web/ -v
```

Expected: `test_health_endpoint` passes. Other web tests may fail for now — they will be deleted/replaced in later tasks. If existing tests break only because of unrelated issues, that's fine for this task.

Actually check: existing tests use functions from `builder.py` which still exists. So they should still pass. Confirm `uv run pytest -v` count unchanged except +1 for the new test.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock market_digest/web/app.py tests/web/test_app.py
git commit -m "feat(web): add FastAPI app skeleton with health endpoint"
```

---

## Task 2: JobTracker

**Files:**
- Create: `market_digest/web/jobs.py`
- Create: `tests/web/test_jobs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_jobs.py`:

```python
import time

from market_digest.web.jobs import JobTracker


def test_create_returns_pending_job():
    tr = JobTracker()
    job = tr.create("AAPL", "2026-04-17")
    assert job.status == "pending"
    assert job.ticker == "AAPL"
    assert job.date == "2026-04-17"
    assert job.job_id  # non-empty
    assert tr.get(job.job_id) is job


def test_find_active_matches_pending_and_running():
    tr = JobTracker()
    j1 = tr.create("AAPL", "2026-04-17")
    assert tr.find_active("AAPL", "2026-04-17") is j1
    tr.mark_running(j1.job_id)
    assert tr.find_active("AAPL", "2026-04-17") is j1
    tr.mark_done(j1.job_id, "/x")
    assert tr.find_active("AAPL", "2026-04-17") is None


def test_mark_done_sets_output_url():
    tr = JobTracker()
    j = tr.create("AAPL", "2026-04-17")
    tr.mark_done(j.job_id, "/2026-04-17/us-rating-0/research")
    got = tr.get(j.job_id)
    assert got.status == "done"
    assert got.output_url == "/2026-04-17/us-rating-0/research"


def test_mark_failed_stores_error():
    tr = JobTracker()
    j = tr.create("AAPL", "2026-04-17")
    tr.mark_failed(j.job_id, "boom")
    got = tr.get(j.job_id)
    assert got.status == "failed"
    assert got.error == "boom"


def test_active_lists_pending_and_running_only():
    tr = JobTracker()
    a = tr.create("AAPL", "2026-04-17")
    b = tr.create("MSFT", "2026-04-17")
    tr.mark_running(b.job_id)
    c = tr.create("NVDA", "2026-04-17")
    tr.mark_done(c.job_id, "/x")
    d = tr.create("META", "2026-04-17")
    tr.mark_failed(d.job_id, "x")
    active = tr.active()
    ids = {j.job_id for j in active}
    assert a.job_id in ids
    assert b.job_id in ids
    assert c.job_id not in ids
    assert d.job_id not in ids


def test_get_unknown_returns_none():
    tr = JobTracker()
    assert tr.get("does-not-exist") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/web/test_jobs.py -v
```

- [ ] **Step 3: Implement JobTracker**

Create `market_digest/web/jobs.py`:

```python
"""In-memory job tracker for research requests.

Jobs are keyed by a UUID. Status lifecycle: pending -> running -> done|failed.
Lost on server restart by design — clients re-request if needed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class Job:
    job_id: str
    ticker: str
    date: str
    status: JobStatus = "pending"
    output_url: str | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


class JobTracker:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, ticker: str, date: str) -> Job:
        job = Job(job_id=str(uuid.uuid4()), ticker=ticker, date=date)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find_active(self, ticker: str, date: str) -> Job | None:
        for j in self._jobs.values():
            if j.ticker == ticker and j.date == date and j.status in ("pending", "running"):
                return j
        return None

    def mark_running(self, job_id: str) -> None:
        j = self._jobs[job_id]
        j.status = "running"

    def mark_done(self, job_id: str, output_url: str) -> None:
        j = self._jobs[job_id]
        j.status = "done"
        j.output_url = output_url
        j.finished_at = datetime.now(timezone.utc)

    def mark_failed(self, job_id: str, error: str) -> None:
        j = self._jobs[job_id]
        j.status = "failed"
        j.error = error
        j.finished_at = datetime.now(timezone.utc)

    def active(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status in ("pending", "running")]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_jobs.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/jobs.py tests/web/test_jobs.py
git commit -m "feat(web): JobTracker for async research jobs"
```

---

## Task 3: Data helpers (migration from builder.py)

**Files:**
- Create: `market_digest/web/data.py`
- Create: `tests/web/test_data.py`

These helpers are pure functions that read from NAS and shape data. Moving them out of `builder.py` into `data.py` makes them usable from both the app and the (future) CLI without pulling Jinja in.

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_data.py`:

```python
import json
from pathlib import Path

from market_digest.models import Digest
from market_digest.web.data import (
    build_cards_index,
    find_item,
    flat_ids,
    list_dates,
    load_digest,
    prev_next,
    research_md_path,
)


def _write(nas: Path, date: str, groups: list[dict]) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


def test_list_dates_sorted_ascending_and_excludes_non_date_dirs(tmp_path):
    _write(tmp_path, "2026-04-18", [])
    _write(tmp_path, "2026-04-19", [])
    _write(tmp_path, "2026-04-17", [])
    # stray site/ dir should NOT leak in
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "cards.json").write_text("[]", encoding="utf-8")

    assert list_dates(tmp_path) == ["2026-04-17", "2026-04-18", "2026-04-19"]


def test_list_dates_empty(tmp_path):
    assert list_dates(tmp_path) == []


def test_load_digest_returns_none_when_missing(tmp_path):
    assert load_digest(tmp_path, "2026-04-20") is None


def test_load_digest_parses_valid_file(tmp_path):
    _write(tmp_path, "2026-04-19", [])
    d = load_digest(tmp_path, "2026-04-19")
    assert isinstance(d, Digest)
    assert d.date == "2026-04-19"


def test_load_digest_returns_none_on_corrupt_file(tmp_path):
    p = tmp_path / "2026" / "04" / "2026-04-19.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ not json", encoding="utf-8")
    assert load_digest(tmp_path, "2026-04-19") is None


def test_prev_next_middle():
    dates = ["2026-04-17", "2026-04-18", "2026-04-19"]
    assert prev_next(dates, "2026-04-18") == ("2026-04-17", "2026-04-19")


def test_prev_next_ends():
    dates = ["2026-04-17", "2026-04-18", "2026-04-19"]
    assert prev_next(dates, "2026-04-17") == (None, "2026-04-18")
    assert prev_next(dates, "2026-04-19") == ("2026-04-18", None)


def test_prev_next_missing_date():
    assert prev_next(["2026-04-17"], "2026-04-20") == (None, None)


def test_find_item_by_id(tmp_path):
    _write(tmp_path, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [
             {"id": "us-rating-0", "headline": "h", "body_md": "b"},
             {"id": "us-rating-1", "headline": "h", "body_md": "b"},
         ]},
    ])
    d = load_digest(tmp_path, "2026-04-19")
    found = find_item(d, "us-rating-1")
    assert found is not None
    gi, ii, item = found
    assert gi == 0 and ii == 1 and item.id == "us-rating-1"
    assert find_item(d, "does-not-exist") is None


def test_flat_ids_preserves_group_order(tmp_path):
    _write(tmp_path, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "x", "body_md": "-"},
                   {"id": "kr-company-1", "headline": "x", "body_md": "-"}]},
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "x", "body_md": "-"}]},
    ])
    d = load_digest(tmp_path, "2026-04-19")
    assert flat_ids(d) == ["kr-company-0", "kr-company-1", "us-rating-0"]


def test_research_md_path_shape(tmp_path):
    p = research_md_path(tmp_path, "AAPL", "2026-04-17")
    assert p == tmp_path / "research" / "AAPL-2026-04-17.md"
    assert research_md_path(tmp_path, None, "2026-04-17") is None
    # also handles lowercased input
    assert research_md_path(tmp_path, "aapl", "2026-04-17") == tmp_path / "research" / "AAPL-2026-04-17.md"


def test_build_cards_index_flattens_desc_with_blurb(tmp_path):
    _write(tmp_path, "2026-04-18", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "old", "body_md": "x",
                    "ticker": "AAPL", "name": "Apple", "company_blurb": "스마트폰"}]},
    ])
    _write(tmp_path, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "new", "body_md": "y",
                    "ticker": "005930", "name": "삼성전자"}]},
    ])
    index = build_cards_index(tmp_path)
    assert [e["date"] for e in index] == ["2026-04-19", "2026-04-18"]
    assert index[1]["company_blurb"] == "스마트폰"
    assert "body_md" not in index[0]
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/web/test_data.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement data.py**

Create `market_digest/web/data.py`:

```python
"""Pure data helpers for the web app — NAS I/O only, no rendering."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from market_digest.models import CardIndexEntry, Digest

log = logging.getLogger(__name__)


def list_dates(nas_dir: Path) -> list[str]:
    """Return YYYY-MM-DD dates (ascending) that have a digest JSON on NAS."""
    if not nas_dir.exists():
        return []
    dates: list[str] = []
    for p in nas_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.json"):
        name = p.stem
        if len(name) == 10 and name[4] == name[7] == "-":
            dates.append(name)
    return sorted(dates)


def load_digest(nas_dir: Path, date: str) -> Digest | None:
    """Load a single day's digest JSON; return None on any failure."""
    y, m, _ = date.split("-")
    path = nas_dir / y / m / f"{date}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Digest.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        log.warning("load_digest %s failed: %s", path, exc)
        return None


def prev_next(dates: list[str], date: str) -> tuple[str | None, str | None]:
    """Return (prev, next) neighbors in `dates` for `date`. (None, None) if missing."""
    try:
        i = dates.index(date)
    except ValueError:
        return (None, None)
    prev_d = dates[i - 1] if i > 0 else None
    next_d = dates[i + 1] if i < len(dates) - 1 else None
    return (prev_d, next_d)


def find_item(digest: Digest, item_id: str) -> tuple[int, int, object] | None:
    """Locate an item by id. Returns (group_index, item_index, item) or None."""
    for gi, group in enumerate(digest.groups):
        for ii, item in enumerate(group.items):
            if item.id == item_id:
                return (gi, ii, item)
    return None


def flat_ids(digest: Digest) -> list[str]:
    return [item.id for group in digest.groups for item in group.items]


def research_md_path(nas_dir: Path, ticker: str | None, date: str) -> Path | None:
    if not ticker:
        return None
    return nas_dir / "research" / f"{ticker.upper()}-{date}.md"


def build_cards_index(nas_dir: Path) -> list[dict]:
    """Flatten every item across every day into a date-descending list."""
    out: list[dict] = []
    for date in sorted(list_dates(nas_dir), reverse=True):
        digest = load_digest(nas_dir, date)
        if digest is None:
            continue
        for group in digest.groups:
            for item in group.items:
                entry = CardIndexEntry(
                    date=digest.date,
                    id=item.id,
                    region=group.region,
                    category=group.category,
                    headline=item.headline,
                    house=item.house,
                    ticker=item.ticker,
                    name=item.name,
                    opinion=item.opinion,
                    target=item.target,
                    company_blurb=item.company_blurb,
                )
                out.append(entry.model_dump(exclude_none=True))
    return out
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_data.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/data.py tests/web/test_data.py
git commit -m "feat(web): pure data helpers (load_digest, list_dates, build_cards_index)"
```

---

## Task 4: Home redirect + cards.json

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from market_digest.web.app import create_app


def _write(nas: Path, date: str, groups: list) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": date, "groups": groups}), encoding="utf-8")


@pytest.fixture
def nas(tmp_path: Path) -> Path:
    return tmp_path


def test_home_redirects_to_latest_date(nas):
    _write(nas, "2026-04-17", [])
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app, follow_redirects=False) as c:
        resp = c.get("/")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].endswith("/2026-04-19")


def test_home_placeholder_when_empty(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/")
    assert resp.status_code == 200
    assert "아직 리포트가 없습니다" in resp.text


def test_cards_json_is_date_desc(nas):
    _write(nas, "2026-04-18", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "headline": "old", "body_md": "x"}]},
    ])
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "new", "body_md": "y"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/cards.json")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["date"] for e in data] == ["2026-04-19", "2026-04-18"]
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 3: Add routes**

In `market_digest/web/app.py`, add inside `create_app()` before the `@app.get("/healthz")` block:

```python
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    from market_digest.web.data import build_cards_index, list_dates

    PLACEHOLDER = (
        "<!doctype html><meta charset=utf-8><title>마켓 다이제스트</title>"
        "<p style='font:16px sans-serif;text-align:center;padding:48px'>아직 리포트가 없습니다.</p>"
    )

    @app.get("/")
    async def home() -> HTMLResponse | RedirectResponse:
        if app.state.nas_dir is None:
            return HTMLResponse(PLACEHOLDER)
        dates = list_dates(app.state.nas_dir)
        if not dates:
            return HTMLResponse(PLACEHOLDER)
        return RedirectResponse(url=f"/{dates[-1]}", status_code=307)

    @app.get("/cards.json")
    async def cards_json() -> JSONResponse:
        if app.state.nas_dir is None:
            return JSONResponse([])
        return JSONResponse(build_cards_index(app.state.nas_dir))
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py tests/web/test_app.py
git commit -m "feat(web): home redirect + cards.json route"
```

---

## Task 5: Card page route + template URL scheme

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `market_digest/web/templates/card_page.html.j2`
- Modify: `tests/web/test_app.py`

The template currently links to `{date}/{id}.html` and `{prev_date}.html`. Dynamic site uses clean URLs: `/{date}/{id}` and `/{prev_date}`. Update the template.

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
from bs4 import BeautifulSoup


def test_card_page_renders_groups_and_cards(nas):
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내 기업리포트",
         "items": [{"id": "kr-company-0", "headline": "HBM 회복", "body_md": "-",
                    "house": "MS", "name": "삼성전자", "ticker": "005930"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.select_one("a.card")
    assert link["href"] == "/2026-04-19/kr-company-0"
    assert "삼성전자" in link.text


def test_card_page_prev_next_clean_urls(nas):
    _write(nas, "2026-04-17", [])
    _write(nas, "2026-04-18", [])
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-18")
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "/2026-04-17"
    assert soup.select_one("a.nav-next")["href"] == "/2026-04-19"


def test_card_page_404_when_date_missing(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19")
    assert resp.status_code == 404
```

- [ ] **Step 2: Update `card_page.html.j2`**

Replace the full contents of `market_digest/web/templates/card_page.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ digest.date }} · 마켓 다이제스트{% endblock %}
{% block content %}
<header class="date-header">
  {% if prev_date %}<a class="nav-prev" href="/{{ prev_date }}">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  <span class="date-label">{{ digest.date }} ({{ weekday }})</span>
  {% if next_date %}<a class="nav-next" href="/{{ next_date }}">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
  <a class="nav-search" href="/search">🔍</a>
</header>

{% if not digest.groups %}
  <p class="empty">오늘 수집된 리포트 없음</p>
{% else %}
  {% for group in digest.groups %}
  <section class="group">
    <h2>{{ group_flag(group.region) }} {{ group.title }}</h2>
    <ul class="cards">
      {% for item in group.items %}
      <li>
        <a class="card" href="/{{ digest.date }}/{{ item.id }}">
          {% if item.house %}<span class="tag">[{{ item.house }}]</span>{% endif %}
          {% if item.name %}<span class="name">{{ item.name }}</span>{% if item.ticker %} ({{ item.ticker }}){% endif %}{% endif %}
          <span class="dash">—</span>
          <span class="headline">{{ item.headline }}</span>
          {% if item.opinion or item.target %}<span class="meta">·{% if item.opinion %} {{ item.opinion }}{% endif %}{% if item.target %} {{ item.target }}{% endif %}</span>{% endif %}
          {% if item.company_blurb %}<span class="blurb">{{ item.company_blurb }}</span>{% endif %}
        </a>
      </li>
      {% endfor %}
    </ul>
  </section>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Add route + weekday helper**

In `market_digest/web/app.py` inside `create_app()`, below the existing routes, add:

```python
    import datetime as _dt

    from fastapi import HTTPException, Path as PathParam

    from market_digest.web.data import load_digest, prev_next

    _WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
    _DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

    def _weekday(date: str) -> str:
        y, m, d = (int(x) for x in date.split("-"))
        return _WEEKDAYS[_dt.date(y, m, d).weekday()]

    @app.get("/{date}")
    async def card_page(date: str = PathParam(..., pattern=_DATE_PATTERN)) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        dates = list_dates(app.state.nas_dir)
        prev_d, next_d = prev_next(dates, date)
        html = app.state.env.get_template("card_page.html.j2").render(
            digest=digest,
            prev_date=prev_d,
            next_date=next_d,
            weekday=_weekday(date),
            asset_prefix="/",
        )
        return HTMLResponse(html)
```

Notes:
- `asset_prefix="/"` so `base.html.j2`'s `<link rel="stylesheet" href="{{ asset_prefix }}assets/style.css">` becomes `/assets/style.css` (absolute path).
- `{date}` route catches any top-level path; make sure it's added AFTER `/`, `/cards.json`, `/healthz` so FastAPI route order resolves correctly.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py market_digest/web/templates/card_page.html.j2 tests/web/test_app.py
git commit -m "feat(web): card page route + clean URL scheme"
```

---

## Task 6: Detail page route + research link conditional

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `market_digest/web/templates/detail_page.html.j2`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
def test_detail_page_renders(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "MS upgrade", "body_md": "- detail",
                    "company_blurb": "스마트폰·서비스"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("article h1")
    assert "스마트폰" in soup.text
    # research UI present as BUTTON because md doesn't exist yet
    assert soup.select_one("button#research-btn") is not None
    assert soup.select_one("a.research-link") is None


def test_detail_page_research_link_when_md_exists(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text("# A\n", encoding="utf-8")
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.select_one("a.research-link")
    assert link is not None
    assert link["href"] == "/2026-04-19/us-rating-0/research"
    assert soup.select_one("button#research-btn") is None


def test_detail_page_404_when_item_missing(nas):
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/missing")
    assert resp.status_code == 404


def test_detail_page_prev_next_within_day(nas):
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [
             {"id": "kr-company-0", "headline": "a", "body_md": "-"},
             {"id": "kr-company-1", "headline": "b", "body_md": "-"},
             {"id": "kr-company-2", "headline": "c", "body_md": "-"},
         ]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/kr-company-1")
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "/2026-04-19/kr-company-0"
    assert soup.select_one("a.nav-next")["href"] == "/2026-04-19/kr-company-2"
    assert soup.select_one("a.back")["href"] == "/2026-04-19"
```

- [ ] **Step 2: Rewrite `detail_page.html.j2`**

Replace the full contents of `market_digest/web/templates/detail_page.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ item.name or item.headline }} · {{ digest.date }}{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="/{{ digest.date }}">←&nbsp;{{ digest.date }}</a>
  {% if prev_id %}<a class="nav-prev" href="/{{ digest.date }}/{{ prev_id }}">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  {% if next_id %}<a class="nav-next" href="/{{ digest.date }}/{{ next_id }}">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
</header>

<article>
  <h1>
    {% if item.name %}{{ item.name }}{% if item.ticker %} ({{ item.ticker }}){% endif %}{% else %}{{ item.headline }}{% endif %}
    {% if item.house %}<span class="tag">[{{ item.house }}]</span>{% endif %}
  </h1>
  {% if item.company_blurb %}<p class="blurb">{{ item.company_blurb }}</p>{% endif %}
  {% if item.opinion or item.target %}
  <p class="meta">{% if item.opinion %}{{ item.opinion }}{% endif %}{% if item.opinion and item.target %} · {% endif %}{% if item.target %}{{ item.target }}{% endif %}</p>
  {% endif %}
  <div class="body">
    {{ body_html|safe }}
  </div>
  {% if item.url %}<p class="source"><a href="{{ item.url }}" rel="noopener">원문 링크</a></p>{% endif %}

  <p class="source">
    {% if has_research %}
      <a class="research-link" href="/{{ digest.date }}/{{ item.id }}/research" rel="noopener">🔍 딥 리서치 보기</a>
    {% elif item.ticker %}
      <button id="research-btn" type="button"
              data-ticker="{{ item.ticker }}" data-date="{{ digest.date }}">🔍 딥 리서치 시작</button>
      <span id="research-status" class="subtitle"></span>
    {% endif %}
  </p>
</article>
{% endblock %}
{% block scripts %}
<script src="/assets/research.js" defer></script>
{% endblock %}
```

- [ ] **Step 3: Add route**

Append inside `create_app()` in `market_digest/web/app.py`:

```python
    from market_digest.web.data import find_item, flat_ids, research_md_path

    @app.get("/{date}/{item_id}")
    async def detail_page(
        date: str = PathParam(..., pattern=_DATE_PATTERN),
        item_id: str = PathParam(...),
    ) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        found = find_item(digest, item_id)
        if found is None:
            raise HTTPException(status_code=404)
        gi, ii, item = found
        ids = flat_ids(digest)
        pos = ids.index(item_id)
        prev_id = ids[pos - 1] if pos > 0 else None
        next_id = ids[pos + 1] if pos < len(ids) - 1 else None
        md_path = research_md_path(app.state.nas_dir, item.ticker, date)
        has_research = md_path is not None and md_path.exists()
        body_html = app.state.md.render(item.body_md)
        html = app.state.env.get_template("detail_page.html.j2").render(
            digest=digest,
            item=item,
            prev_id=prev_id,
            next_id=next_id,
            body_html=body_html,
            has_research=has_research,
            asset_prefix="/",
        )
        return HTMLResponse(html)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py market_digest/web/templates/detail_page.html.j2 tests/web/test_app.py
git commit -m "feat(web): detail page route with research link / button"
```

---

## Task 7: Research page route

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `market_digest/web/templates/research_page.html.j2`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
def test_research_page_renders_md(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text(
        "# 딥 리서치\n\n- alpha research line\n", encoding="utf-8"
    )
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0/research")
    assert resp.status_code == 200
    assert "alpha research line" in resp.text


def test_research_page_404_without_md(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0/research")
    assert resp.status_code == 404
```

- [ ] **Step 2: Update template**

Replace `market_digest/web/templates/research_page.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}🔍 {{ item.name or item.ticker }} 딥 리서치 · {{ digest.date }}{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="/{{ digest.date }}/{{ item.id }}">←&nbsp;상세로 돌아가기</a>
</header>
<article>
  <div class="body">
    {{ body_html|safe }}
  </div>
</article>
{% endblock %}
```

- [ ] **Step 3: Add route**

Append inside `create_app()`:

```python
    @app.get("/{date}/{item_id}/research")
    async def research_page(
        date: str = PathParam(..., pattern=_DATE_PATTERN),
        item_id: str = PathParam(...),
    ) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        found = find_item(digest, item_id)
        if found is None:
            raise HTTPException(status_code=404)
        _, _, item = found
        md_path = research_md_path(app.state.nas_dir, item.ticker, date)
        if md_path is None or not md_path.exists():
            raise HTTPException(status_code=404)
        body_html = app.state.md.render(md_path.read_text(encoding="utf-8"))
        html = app.state.env.get_template("research_page.html.j2").render(
            digest=digest, item=item, body_html=body_html, asset_prefix="/",
        )
        return HTMLResponse(html)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py market_digest/web/templates/research_page.html.j2 tests/web/test_app.py
git commit -m "feat(web): research page route"
```

---

## Task 8: Search page + static assets

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `market_digest/web/templates/search.html.j2`
- Modify: `market_digest/web/assets/search.js`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
def test_search_page_renders(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/search")
    assert resp.status_code == 200
    assert "cards.json" in resp.text
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("input#search-input") is not None


def test_static_asset_served(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/assets/style.css")
    assert resp.status_code == 200
    assert "page" in resp.text  # stylesheet contains .page rule


def test_static_asset_404_for_unknown(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/assets/does-not-exist.js")
    assert resp.status_code == 404
```

- [ ] **Step 2: Update `search.html.j2` URLs**

Replace full content with:

```jinja
{% extends "base.html.j2" %}
{% block title %}검색 · 마켓 다이제스트{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="/">← 홈</a>
  <span class="date-label">검색</span>
</header>
<input id="search-input" type="search" placeholder="종목, 티커, 하우스…" autocomplete="off">
<p id="search-count" class="subtitle"></p>
<ul id="search-results" class="cards"></ul>
<link rel="preload" href="/cards.json" as="fetch" crossorigin="anonymous">
{% endblock %}
{% block scripts %}
<script src="/assets/search.js" defer></script>
{% endblock %}
```

- [ ] **Step 3: Update `search.js` to clean URLs**

In `market_digest/web/assets/search.js`, replace the result-rendering line so result hrefs are absolute. Find the `const href = \`...\`` line and replace the whole render function's link construction with:

```javascript
      const href = `/${c.date}/${c.id}`;
```

And replace the `const results = ...` line and the `fetch("cards.json")` call:

```javascript
  cards = await (await fetch("/cards.json")).json();
```

- [ ] **Step 4: Add routes**

Append inside `create_app()`:

```python
    from fastapi.responses import FileResponse
    from importlib import resources

    @app.get("/search")
    async def search_page() -> HTMLResponse:
        html = app.state.env.get_template("search.html.j2").render(asset_prefix="/")
        return HTMLResponse(html)

    @app.get("/assets/{name}")
    async def asset(name: str):
        if "/" in name or ".." in name:
            raise HTTPException(status_code=404)
        try:
            ref = resources.files("market_digest.web").joinpath("assets", name)
        except (ModuleNotFoundError, FileNotFoundError):
            raise HTTPException(status_code=404)
        path = Path(str(ref))
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 6: Commit**

```bash
git add market_digest/web/app.py market_digest/web/templates/search.html.j2 market_digest/web/assets/search.js tests/web/test_app.py
git commit -m "feat(web): search page + static asset route"
```

---

## Task 9: Split research prompt (KR vs US)

**Files:**
- Modify: `market_digest/research.py`
- Modify: `tests/test_research_cli.py`

- [ ] **Step 1: Extend tests**

Append to `tests/test_research_cli.py`:

```python
from market_digest.research import build_prompt


def test_build_prompt_picks_kr_sources_for_6_digit_ticker(tmp_path):
    p = build_prompt("005930", "2026-04-19", tmp_path / "out.md", None)
    assert "네이버" in p or "한경" in p or "DART" in p
    assert "Seeking Alpha" not in p


def test_build_prompt_picks_us_sources_for_letter_ticker(tmp_path):
    p = build_prompt("AAPL", "2026-04-19", tmp_path / "out.md", None)
    assert "Yahoo Finance" in p or "Seeking Alpha" in p
    assert "네이버" not in p


def test_build_prompt_includes_context_when_present(tmp_path):
    p = build_prompt("AAPL", "2026-04-19", tmp_path / "out.md", "AI 리스크 중점")
    assert "AI 리스크 중점" in p
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/test_research_cli.py -v
```

- [ ] **Step 3: Split prompt in `research.py`**

Locate `_prompt(...)` in `market_digest/research.py`. Rename it to `build_prompt` (public) and replace its body so it branches on ticker shape:

```python
import re

_KR_TICKER_RE = re.compile(r"^\d{6}$")


def _kr_prompt(ticker: str, date_str: str, out_path: Path, context: str | None) -> str:
    extra = f"\n사용자 포커스: {context}" if context else ""
    return (
        f"{ticker} 한국 종목에 대한 딥 리서치 리포트를 한국어로 작성하라. "
        f"날짜 기준은 {date_str} (KST). 공개 자료만 사용: "
        f"네이버 금융 종목분석, 한경 컨센서스, DART 전자공시, 다음 금융, "
        f"이데일리·머니투데이·아시아경제 기사, 증권사 분석 요약. "
        f"다음 섹션으로 구성: "
        f"## 회사 개요, ## 주요 증권사 의견 (증권사명+목표가+요지+출처), "
        f"## Thesis, ## 리스크, ## 최근 이벤트, ## 출처. "
        f"WebSearch/WebFetch 로 수집하고, 출처 URL 을 각 인용마다 붙여라.{extra} "
        f"완성된 Markdown 을 Write 도구로 {out_path} 에 저장하라."
    )


def _us_prompt(ticker: str, date_str: str, out_path: Path, context: str | None) -> str:
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


def build_prompt(ticker: str, date_str: str, out_path: Path, context: str | None) -> str:
    """Return the research prompt; branches KR vs US by ticker shape."""
    if _KR_TICKER_RE.match(ticker):
        return _kr_prompt(ticker, date_str, out_path, context)
    return _us_prompt(ticker, date_str, out_path, context)
```

Update `run_research(...)` body: replace the `"-p", _prompt(ticker, date_str, out_path, context)` line with:

```python
        "-p", build_prompt(ticker, date_str, out_path, context),
```

Remove the old `_prompt(...)` function entirely.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_research_cli.py -v
```

Expected: all pass (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add market_digest/research.py tests/test_research_cli.py
git commit -m "feat(research): branch prompt on ticker shape for KR vs US sources"
```

---

## Task 10: POST /api/research + background spawn

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `tests/web/test_app.py`

The app uses a **research_runner** dependency so tests can inject a fast stub.

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
import asyncio


def _fake_runner(tracker, job_id, ticker, date_str, out_path):
    """Test runner: marks running, writes a stub md, marks done."""
    tracker.mark_running(job_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(f"# {ticker} stub — {date_str}\n", encoding="utf-8")
    tracker.mark_done(job_id, f"/{date_str}/dummy/research")


def test_post_research_starts_new_job_and_returns_job_id(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("pending", "running", "done")
    assert body["job_id"]


def test_post_research_returns_existing_md_immediately(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    (nas / "research").mkdir()
    (nas / "research" / "AAPL-2026-04-19.md").write_text("# old\n", encoding="utf-8")
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    body = resp.json()
    assert body["status"] == "done"
    assert body["output_url"] == "/2026-04-19/us-rating-0/research"


def test_post_research_dedupes_active_job(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "b"}]},
    ])
    def slow_runner(tracker, job_id, *args, **kwargs):
        tracker.mark_running(job_id)  # leave running; test inspects
    app = create_app(nas_dir=nas, research_runner=slow_runner)
    with TestClient(app) as c:
        r1 = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
        r2 = c.post("/api/research", json={"ticker": "AAPL", "date": "2026-04-19"})
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_post_research_400_if_ticker_not_in_digest(nas):
    _write(nas, "2026-04-19", [])
    app = create_app(nas_dir=nas, research_runner=_fake_runner)
    with TestClient(app) as c:
        resp = c.post("/api/research", json={"ticker": "XYZ", "date": "2026-04-19"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 3: Extend `create_app()` with the research pipeline**

Modify `create_app` signature:

```python
def create_app(nas_dir: Path | None, research_runner=None) -> FastAPI:
```

Inside the function, BEFORE the `@app.get("/")` block, add:

```python
    from market_digest.web.jobs import JobTracker

    app.state.tracker = JobTracker()
    app.state.research_runner = research_runner
```

Then, near the other routes (anywhere BEFORE the catch-all `/{date}` route so the path is matched first), add:

```python
    from fastapi import Body
    from pydantic import BaseModel

    class ResearchRequest(BaseModel):
        ticker: str
        date: str

    def _find_item_for_ticker(digest: Digest, ticker: str):
        for g in digest.groups:
            for i in g.items:
                if (i.ticker or "").upper() == ticker.upper():
                    return i
        return None

    def _default_runner(tracker, job_id, ticker, date_str, out_path):
        """Production runner: runs claude via subprocess in an executor thread."""
        from market_digest.research import run_research
        import yaml

        with open(Path(__file__).resolve().parent.parent.parent / "config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        tracker.mark_running(job_id)
        try:
            run_research(
                ticker=ticker,
                date_str=date_str,
                out_path=out_path,
                claude_cli=cfg["claude"]["cli_path"],
                model=cfg["claude"]["research_model"],
                context=None,
                dry_run=False,
            )
        except Exception as exc:
            tracker.mark_failed(job_id, str(exc))
            return
        # find item id again to build the output URL
        digest = load_digest(app.state.nas_dir, date_str)
        item_id = ""
        if digest:
            it = _find_item_for_ticker(digest, ticker)
            if it is not None:
                item_id = it.id
        tracker.mark_done(job_id, f"/{date_str}/{item_id}/research")

    @app.post("/api/research")
    async def post_research(body: ResearchRequest = Body(...)) -> dict:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, body.date)
        if digest is None:
            raise HTTPException(status_code=400, detail="digest missing")
        item = _find_item_for_ticker(digest, body.ticker)
        if item is None:
            raise HTTPException(status_code=400, detail="ticker not in digest")

        md_path = research_md_path(app.state.nas_dir, body.ticker, body.date)
        if md_path is not None and md_path.exists():
            return {"job_id": "", "status": "done",
                    "output_url": f"/{body.date}/{item.id}/research"}

        existing = app.state.tracker.find_active(body.ticker.upper(), body.date)
        if existing is not None:
            return {"job_id": existing.job_id, "status": existing.status}

        job = app.state.tracker.create(body.ticker.upper(), body.date)
        runner = app.state.research_runner or _default_runner

        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            runner,
            app.state.tracker,
            job.job_id,
            body.ticker.upper(),
            body.date,
            md_path,
        )
        return {"job_id": job.job_id, "status": "pending"}
```

Note: `Digest` is imported at the top of the file already via `load_digest`? No — that returns `Digest` but we don't have a local reference. Add `from market_digest.models import Digest` near the `from market_digest.web.data import ...` line inside `create_app()`. (Placing imports inside is acceptable for now to keep the FastAPI setup contained.)

Also: `loop.run_in_executor` is fire-and-forget; its Future is discarded. In tests, the runner is synchronous so we don't `await`. In production, the runner blocks inside the worker thread until claude finishes.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

Expected: all pass. Note that tests may race with the executor thread. Because `_fake_runner` is synchronous and finishes before `run_in_executor` returns control (the call is non-awaited), the actual sequencing may reveal status "pending" in the response even though the runner has already called `mark_done`. That's acceptable — the tests only check `status in ("pending","running","done")` or the output_url for the existing-md case.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py tests/web/test_app.py
git commit -m "feat(web): POST /api/research with background runner + dedup"
```

---

## Task 11: Status + active endpoints

**Files:**
- Modify: `market_digest/web/app.py`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_app.py`:

```python
def test_get_research_status_returns_state(nas):
    app = create_app(nas_dir=nas)
    tracker = app.state.tracker
    j = tracker.create("AAPL", "2026-04-19")
    tracker.mark_running(j.job_id)
    with TestClient(app) as c:
        resp = c.get(f"/api/research/status/{j.job_id}")
    body = resp.json()
    assert body["status"] == "running"
    assert body["ticker"] == "AAPL"
    assert body["date"] == "2026-04-19"


def test_get_research_status_404_for_unknown(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/api/research/status/does-not-exist")
    assert resp.status_code == 404


def test_get_research_active_lists_only_pending_running(nas):
    app = create_app(nas_dir=nas)
    tracker = app.state.tracker
    j1 = tracker.create("AAPL", "2026-04-19")
    j2 = tracker.create("MSFT", "2026-04-19")
    tracker.mark_done(j2.job_id, "/x")
    with TestClient(app) as c:
        resp = c.get("/api/research/active")
    body = resp.json()
    ids = {j["job_id"] for j in body}
    assert j1.job_id in ids
    assert j2.job_id not in ids
```

- [ ] **Step 2: Run (expect failure)**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 3: Add routes**

Append inside `create_app()`:

```python
    @app.get("/api/research/status/{job_id}")
    async def research_status(job_id: str) -> dict:
        job = app.state.tracker.get(job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return {
            "job_id": job.job_id,
            "ticker": job.ticker,
            "date": job.date,
            "status": job.status,
            "output_url": job.output_url,
            "error": job.error,
        }

    @app.get("/api/research/active")
    async def research_active() -> list:
        return [
            {"job_id": j.job_id, "ticker": j.ticker, "date": j.date,
             "status": j.status}
            for j in app.state.tracker.active()
        ]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/app.py tests/web/test_app.py
git commit -m "feat(web): /api/research/status/{id} + /api/research/active"
```

---

## Task 12: Frontend research.js + global badge

**Files:**
- Create: `market_digest/web/assets/research.js`
- Create: `market_digest/web/assets/base.js`
- Modify: `market_digest/web/templates/base.html.j2`
- Modify: `market_digest/web/assets/style.css`

- [ ] **Step 1: Write `research.js`**

Create `market_digest/web/assets/research.js`:

```javascript
(() => {
  const btn = document.getElementById("research-btn");
  const status = document.getElementById("research-status");
  if (!btn || !status) return;

  const ticker = btn.dataset.ticker;
  const date = btn.dataset.date;

  const setStatus = (text) => { status.textContent = text; };

  const poll = async (jobId) => {
    while (true) {
      await new Promise(r => setTimeout(r, 5000));
      const resp = await fetch(`/api/research/status/${jobId}`);
      if (!resp.ok) { setStatus("상태 조회 실패 — 페이지 새로고침 후 재시도"); return; }
      const body = await resp.json();
      if (body.status === "done" && body.output_url) {
        setStatus("완료 — 이동 중…");
        window.location.href = body.output_url;
        return;
      }
      if (body.status === "failed") {
        setStatus(`실패: ${body.error || "알 수 없음"}`);
        btn.disabled = false;
        return;
      }
      setStatus(`생성 중 (${body.status})…`);
    }
  };

  const start = async () => {
    btn.disabled = true;
    setStatus("요청 중…");
    try {
      const resp = await fetch("/api/research", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({ticker, date}),
      });
      if (!resp.ok) { setStatus("요청 실패"); btn.disabled = false; return; }
      const body = await resp.json();
      if (body.status === "done" && body.output_url) {
        window.location.href = body.output_url;
        return;
      }
      if (body.job_id) poll(body.job_id);
    } catch (e) {
      setStatus("네트워크 오류");
      btn.disabled = false;
    }
  };

  btn.addEventListener("click", start);

  // On load, check if an active job already exists for this (ticker, date)
  (async () => {
    try {
      const resp = await fetch("/api/research/active");
      if (!resp.ok) return;
      const jobs = await resp.json();
      const existing = jobs.find(j => j.ticker.toUpperCase() === ticker.toUpperCase() && j.date === date);
      if (existing) {
        btn.disabled = true;
        setStatus("이미 요청됨 — 상태 확인 중…");
        poll(existing.job_id);
      }
    } catch {}
  })();
})();
```

- [ ] **Step 2: Write `base.js`**

Create `market_digest/web/assets/base.js`:

```javascript
(async () => {
  const badge = document.getElementById("global-research-badge");
  if (!badge) return;
  const refresh = async () => {
    try {
      const resp = await fetch("/api/research/active");
      if (!resp.ok) return;
      const jobs = await resp.json();
      if (jobs.length > 0) {
        badge.textContent = `🔍 ${jobs.length}`;
        badge.style.display = "inline";
      } else {
        badge.style.display = "none";
      }
    } catch {}
  };
  await refresh();
  setInterval(refresh, 10000);
})();
```

- [ ] **Step 3: Update `base.html.j2`**

Replace full content of `market_digest/web/templates/base.html.j2` with:

```jinja
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{% block title %}마켓 다이제스트{% endblock %}</title>
<link rel="stylesheet" href="{{ asset_prefix }}assets/style.css">
</head>
<body>
<span id="global-research-badge" class="nav-badge" style="display:none"></span>
<main class="page">
{% block content %}{% endblock %}
</main>
<script src="/assets/base.js" defer></script>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: Append badge styles**

Append to `market_digest/web/assets/style.css`:

```css
.nav-badge {
  position: fixed;
  top: 12px;
  right: 12px;
  z-index: 20;
  background: var(--accent);
  color: #fff;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
}

button#research-btn {
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}
button#research-btn:disabled {
  background: var(--muted);
  cursor: wait;
}
```

- [ ] **Step 5: Verify assets served**

Add one sanity test to `tests/web/test_app.py`:

```python
def test_research_js_served(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        r = c.get("/assets/research.js")
        b = c.get("/assets/base.js")
    assert r.status_code == 200 and "fetch(\"/api/research\"" in r.text
    assert b.status_code == 200 and "global-research-badge" in b.text
```

Run:

```bash
uv run pytest tests/web/test_app.py -v
```

- [ ] **Step 6: Commit**

```bash
git add market_digest/web/assets/research.js market_digest/web/assets/base.js market_digest/web/templates/base.html.j2 market_digest/web/assets/style.css tests/web/test_app.py
git commit -m "feat(web): research trigger button + global active-jobs badge"
```

---

## Task 13: Drop web.build, delete builder.py + stale tests

**Files:**
- Modify: `market_digest/run.py`
- Modify: `market_digest/web/__init__.py`
- Delete: `market_digest/web/builder.py`
- Delete: `tests/web/test_build.py`
- Delete: `tests/web/test_collect.py`
- Delete: `tests/web/test_index.py`
- Delete: `tests/web/test_render.py`
- Delete: `tests/web/test_research_render.py`

- [ ] **Step 1: Remove `web_build` call from `run.py`**

In `market_digest/run.py`, delete the import line `from market_digest.web import build as web_build` and the entire `try: site = web_build(nas_dir) ... except Exception ...` block. Keep the rest of the pipeline intact (fetchers, summarize, validate, enrich).

- [ ] **Step 2: Simplify `market_digest/web/__init__.py`**

Replace content with:

```python
"""market_digest.web — FastAPI application package."""
from market_digest.web.app import create_app

__all__ = ["create_app"]
```

- [ ] **Step 3: Delete stale files**

```bash
cd /home/sund4y/market-digest
git rm market_digest/web/builder.py
git rm tests/web/test_build.py tests/web/test_collect.py tests/web/test_index.py tests/web/test_render.py tests/web/test_research_render.py
```

- [ ] **Step 4: Confirm full suite still passes**

```bash
uv run pytest -v
uv run python -c "import market_digest.run; import market_digest.web.app; print('ok')"
```

Expected: all remaining tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: drop static builder; run.py no longer calls web.build"
```

---

## Task 14: Config, systemd, Caddy, README

**Files:**
- Modify: `config.yaml`
- Create: `deploy/market-digest-web.service.example`
- Modify: `deploy/Caddyfile.example`
- Modify: `deploy/README.md`

- [ ] **Step 1: Add `web:` section to config.yaml**

Append to `config.yaml`:

```yaml
web:
  host: "127.0.0.1"
  port: 8087
```

- [ ] **Step 2: Create systemd unit example**

Create `deploy/market-digest-web.service.example`:

```ini
[Unit]
Description=market-digest web app
After=network.target

[Service]
Type=simple
User=sund4y
WorkingDirectory=/home/sund4y/market-digest
ExecStart=/home/sund4y/.local/bin/uv run uvicorn market_digest.web.app:create_app --factory --host 127.0.0.1 --port 8087
Restart=on-failure
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/home/sund4y/market-digest/.env

[Install]
WantedBy=multi-user.target
```

Note: uvicorn's `--factory` flag calls `create_app()` with no args, producing an app bound to `nas_dir=None`. Since production needs `nas_dir` to be the NAS root, we need a production factory wrapper. Add it to `app.py` end:

```python
def production_app() -> FastAPI:
    """uvicorn entry point: binds nas_dir from config.yaml."""
    import yaml

    cfg_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return create_app(nas_dir=Path(cfg["nas_report_dir"]))
```

And update the systemd `ExecStart`:

```
ExecStart=/home/sund4y/.local/bin/uv run uvicorn market_digest.web.app:production_app --factory --host 127.0.0.1 --port 8087
```

- [ ] **Step 3: Rewrite `deploy/Caddyfile.example`**

Replace with:

```
# Append this block to /etc/caddy/Caddyfile.

:8086 {
  encode gzip
  reverse_proxy localhost:8087
}
```

- [ ] **Step 4: Rewrite `deploy/README.md`**

Replace with:

```markdown
# Deploying the web digest (dynamic)

## 1. FastAPI app (systemd)

```bash
sudo cp deploy/market-digest-web.service.example /etc/systemd/system/market-digest-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now market-digest-web
curl -s http://127.0.0.1:8087/healthz   # -> {"ok":true}
```

## 2. Caddy (reverse proxy)

```bash
# append the block from deploy/Caddyfile.example to /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -I http://localhost:8086/healthz    # -> 200 via Caddy
```

## 3. Cloudflare Tunnel + Access

Ingress already routes the hostname to `http://localhost:8086`. Cloudflare
Access policy (email allowlist) is configured in the Cloudflare dashboard.

## 4. FMP API key

1. Register free account at https://site.financialmodelingprep.com/developer/docs
2. Copy API key into `.env`:
   ```
   FMP_API_KEY=your_key_here
   ```
3. Free tier: 250 calls/day.

## 5. Daily run

The existing cron that invokes `python -m market_digest.run` now writes JSON + blurbs only. The web app reads from NAS on every request; no build step required.

## 6. Deep research from the web

On any detail page for a ticker that has no research yet:
1. Click "🔍 딥 리서치 시작".
2. Status line updates as the background job progresses.
3. On completion, browser auto-navigates to the research page.
4. You can leave the page — the job keeps running; come back or watch the global badge (top-right) for progress.
```

- [ ] **Step 5: Run full suite one more time + import check**

```bash
cd /home/sund4y/market-digest
uv run pytest -v
uv run python -c "from market_digest.web.app import production_app; app = production_app(); print('ok')"
```

- [ ] **Step 6: Commit**

```bash
git add config.yaml deploy/market-digest-web.service.example deploy/Caddyfile.example deploy/README.md market_digest/web/app.py
git commit -m "docs/deploy: systemd + Caddy reverse-proxy + production factory"
```

---

## Final checks

- [ ] **All tests**

```bash
uv run pytest -v
```

All pass.

- [ ] **Local smoke**

```bash
cd /home/sund4y/market-digest
uv run uvicorn market_digest.web.app:production_app --factory --host 127.0.0.1 --port 8087 &
sleep 2
curl -s http://127.0.0.1:8087/healthz
curl -sI http://127.0.0.1:8087/
curl -sI http://127.0.0.1:8087/2026-04-17
curl -s  http://127.0.0.1:8087/cards.json | head -c 200
kill %1
```

Expected: healthz OK, `/` redirects to latest date, `/2026-04-17` returns 200 or 404 (depending on state), `/cards.json` returns a JSON array.

- [ ] **Post-deploy manual check** (after systemd + Caddy reload): open `http://localhost:8086/` in a browser, navigate to a detail page, click "🔍 딥 리서치 시작", observe status line updating, wait for auto-redirect.
