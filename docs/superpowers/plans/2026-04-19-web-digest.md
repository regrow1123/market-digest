# Web Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Telegram delivery with a mobile-first static website generated from `{DATE}.json` files, served by Caddy and exposed via the existing Cloudflare Tunnel.

**Architecture:** Claude emits a single structured JSON per day (no more MD or stdout cards). A new `market_digest.web.build(nas_dir)` step renders card pages, per-item detail pages, and a search index into `nas_dir/site/`. Caddy serves that directory; Cloudflare Tunnel adds a hostname.

**Tech Stack:** Python 3.12, pydantic v2, Jinja2, markdown-it-py; vanilla HTML/CSS/JS for the site; Caddy for serving.

**Spec:** `docs/superpowers/specs/2026-04-19-web-digest-design.md`

---

## File Structure

Create:
- `market_digest/models.py` — pydantic models (`Item`, `Group`, `Digest`, `CardIndexEntry`)
- `market_digest/web/__init__.py` — exports `build`
- `market_digest/web/builder.py` — `build(nas_dir)`, `collect_digests`, `build_index`, renderers, atomic swap
- `market_digest/web/templates/base.html.j2`
- `market_digest/web/templates/card_page.html.j2`
- `market_digest/web/templates/detail_page.html.j2`
- `market_digest/web/templates/search.html.j2`
- `market_digest/web/assets/style.css`
- `market_digest/web/assets/search.js`
- `tests/web/__init__.py`
- `tests/web/test_models.py`
- `tests/web/test_collect.py`
- `tests/web/test_index.py`
- `tests/web/test_render.py`
- `tests/web/test_build.py`
- `deploy/Caddyfile.example`
- `deploy/README.md`

Modify:
- `pyproject.toml` — deps (pydantic, jinja2, markdown-it-py); remove unused (`requests` still used by fetchers/telegram — keep)
- `CLAUDE.md` — rewrite for JSON output; remove Telegram/stdout sections
- `market_digest/summarize.py` — expect `{DATE}.json`, drop `telegram_markdown`
- `market_digest/run.py` — drop Telegram send, call `web.build`, validate JSON
- `.env.example` — remove Telegram envs

Delete:
- `market_digest/telegram.py`

---

## Task 1: Add dependencies and pydantic models

**Files:**
- Modify: `pyproject.toml`
- Create: `market_digest/models.py`
- Create: `tests/web/__init__.py` (empty)
- Create: `tests/web/test_models.py`

- [ ] **Step 1: Add runtime deps to `pyproject.toml`**

In the `[project]` `dependencies` list, add:

```toml
    "pydantic>=2.7",
    "jinja2>=3.1",
    "markdown-it-py>=3.0",
```

- [ ] **Step 2: Install**

Run: `cd /home/sund4y/market-digest && uv sync`
Expected: resolves and installs pydantic, jinja2, markdown-it-py without error.

- [ ] **Step 3: Write failing model tests**

Create `tests/web/__init__.py` (empty file) and `tests/web/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from market_digest.models import Digest, Group, Item


def _minimal_item(**over) -> dict:
    base = {
        "id": "kr-company-0",
        "headline": "HBM 업황 회복",
        "body_md": "- line 1",
    }
    base.update(over)
    return base


def _minimal_group(**over) -> dict:
    base = {
        "region": "kr",
        "category": "company",
        "title": "국내 기업리포트",
        "items": [_minimal_item()],
    }
    base.update(over)
    return base


def test_digest_parses_minimal_payload():
    d = Digest.model_validate({"date": "2026-04-19", "groups": []})
    assert d.date == "2026-04-19"
    assert d.groups == []


def test_digest_parses_full_payload():
    d = Digest.model_validate(
        {
            "date": "2026-04-19",
            "groups": [
                _minimal_group(
                    items=[
                        {
                            "id": "kr-company-0",
                            "house": "미래에셋",
                            "ticker": "005930",
                            "name": "삼성전자",
                            "headline": "HBM 업황 회복",
                            "opinion": "Buy",
                            "target": "85,000 → 95,000",
                            "body_md": "- 목표가 85k→95k",
                            "url": "https://example.com/x",
                        }
                    ]
                )
            ],
        }
    )
    item = d.groups[0].items[0]
    assert item.name == "삼성전자"
    assert item.ticker == "005930"
    assert item.url == "https://example.com/x"


def test_item_requires_id_headline_body_md():
    with pytest.raises(ValidationError):
        Item.model_validate({"headline": "x", "body_md": "y"})  # missing id
    with pytest.raises(ValidationError):
        Item.model_validate({"id": "a", "body_md": "y"})  # missing headline
    with pytest.raises(ValidationError):
        Item.model_validate({"id": "a", "headline": "x"})  # missing body_md


def test_group_region_must_be_kr_or_us():
    with pytest.raises(ValidationError):
        Group.model_validate(_minimal_group(region="jp"))


def test_group_category_restricted_set():
    with pytest.raises(ValidationError):
        Group.model_validate(_minimal_group(category="unknown"))


def test_digest_date_format_yyyy_mm_dd():
    with pytest.raises(ValidationError):
        Digest.model_validate({"date": "20260419", "groups": []})
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_models.py -v`
Expected: FAIL (ImportError — `market_digest.models` does not exist)

- [ ] **Step 5: Implement `market_digest/models.py`**

```python
"""Pydantic models for the daily digest JSON."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Region = Literal["kr", "us"]
Category = Literal["company", "industry", "8k", "rating"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Item(BaseModel):
    id: str
    headline: str
    body_md: str
    house: str | None = None
    ticker: str | None = None
    name: str | None = None
    opinion: str | None = None
    target: str | None = None
    url: str | None = None


class Group(BaseModel):
    region: Region
    category: Category
    title: str
    items: list[Item] = Field(default_factory=list)


class Digest(BaseModel):
    date: str
    groups: list[Group] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError("date must match YYYY-MM-DD")
        return v


class CardIndexEntry(BaseModel):
    """Flat record used in cards.json (no body_md)."""

    date: str
    id: str
    region: Region
    category: Category
    headline: str
    house: str | None = None
    ticker: str | None = None
    name: str | None = None
    opinion: str | None = None
    target: str | None = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_models.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/sund4y/market-digest
git add pyproject.toml uv.lock market_digest/models.py tests/web/__init__.py tests/web/test_models.py
git commit -m "feat(web): add pydantic models for digest JSON"
```

---

## Task 2: Collect digests from NAS

**Files:**
- Create: `market_digest/web/__init__.py`
- Create: `market_digest/web/builder.py`
- Create: `tests/web/test_collect.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_collect.py`:

```python
import json
from pathlib import Path

from market_digest.web.builder import collect_digests


def _write(nas: Path, date: str, payload: dict) -> None:
    y, m, _ = date.split("-")
    p = nas / y / m / f"{date}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_sorts_by_date_ascending(tmp_path):
    _write(tmp_path, "2026-04-18", {"date": "2026-04-18", "groups": []})
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    _write(tmp_path, "2026-04-17", {"date": "2026-04-17", "groups": []})

    digests = collect_digests(tmp_path)
    assert [d.date for d in digests] == ["2026-04-17", "2026-04-18", "2026-04-19"]


def test_collect_skips_invalid_json(tmp_path, caplog):
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    bad = tmp_path / "2026" / "04" / "2026-04-18.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        digests = collect_digests(tmp_path)

    assert [d.date for d in digests] == ["2026-04-19"]
    assert any("2026-04-18" in r.message for r in caplog.records)


def test_collect_skips_schema_mismatch(tmp_path, caplog):
    _write(tmp_path, "2026-04-19", {"date": "2026-04-19", "groups": []})
    _write(tmp_path, "2026-04-18", {"date": "bad-date", "groups": []})

    with caplog.at_level("WARNING"):
        digests = collect_digests(tmp_path)

    assert [d.date for d in digests] == ["2026-04-19"]


def test_collect_returns_empty_when_no_json(tmp_path):
    assert collect_digests(tmp_path) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_collect.py -v`
Expected: FAIL (ImportError — `market_digest.web` does not exist)

- [ ] **Step 3: Create package and implement collector**

Create `market_digest/web/__init__.py`:

```python
from market_digest.web.builder import build

__all__ = ["build"]
```

Create `market_digest/web/builder.py`:

```python
"""Static site generator for market-digest."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from market_digest.models import Digest

log = logging.getLogger(__name__)


def collect_digests(nas_dir: Path) -> list[Digest]:
    """Load every `{YYYY}/{MM}/{DATE}.json` under nas_dir, sorted ascending.

    Individual file failures (unreadable / invalid JSON / schema mismatch)
    are logged and skipped — the rest of the site still builds.
    """
    digests: list[Digest] = []
    for path in sorted(nas_dir.glob("*/*/*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            digests.append(Digest.model_validate(raw))
        except json.JSONDecodeError as exc:
            log.warning("web.build: invalid JSON at %s: %s", path, exc)
        except ValidationError as exc:
            log.warning("web.build: schema mismatch at %s: %s", path, exc)
        except OSError as exc:
            log.warning("web.build: cannot read %s: %s", path, exc)
    digests.sort(key=lambda d: d.date)
    return digests
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_collect.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/__init__.py market_digest/web/builder.py tests/web/test_collect.py
git commit -m "feat(web): collect digest JSON files from NAS"
```

---

## Task 3: Build search index (cards.json)

**Files:**
- Modify: `market_digest/web/builder.py`
- Create: `tests/web/test_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_index.py`:

```python
from market_digest.models import Digest
from market_digest.web.builder import build_index


def _digest(date: str, items: list[dict]) -> Digest:
    return Digest.model_validate(
        {
            "date": date,
            "groups": [
                {
                    "region": "kr",
                    "category": "company",
                    "title": "국내 기업리포트",
                    "items": items,
                }
            ],
        }
    )


def test_index_flattens_across_dates_in_descending_order():
    d1 = _digest("2026-04-18", [{"id": "kr-company-0", "headline": "a", "body_md": "x"}])
    d2 = _digest("2026-04-19", [{"id": "kr-company-0", "headline": "b", "body_md": "y"}])

    entries = build_index([d1, d2])

    assert [e.date for e in entries] == ["2026-04-19", "2026-04-18"]


def test_index_excludes_body_md():
    d = _digest(
        "2026-04-19",
        [
            {
                "id": "kr-company-0",
                "headline": "HBM",
                "body_md": "detail that should not leak",
                "house": "미래에셋",
                "ticker": "005930",
                "name": "삼성전자",
                "opinion": "Buy",
                "target": "85→95k",
            }
        ],
    )
    entries = build_index([d])
    dumped = entries[0].model_dump()
    assert "body_md" not in dumped
    assert dumped["name"] == "삼성전자"
    assert dumped["ticker"] == "005930"


def test_index_empty_when_no_items():
    d = Digest.model_validate({"date": "2026-04-19", "groups": []})
    assert build_index([d]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_index.py -v`
Expected: FAIL (ImportError — `build_index` not defined)

- [ ] **Step 3: Implement `build_index`**

Append to `market_digest/web/builder.py`:

```python
from market_digest.models import CardIndexEntry


def build_index(digests: list[Digest]) -> list[CardIndexEntry]:
    """Flatten all items into a single date-descending list for cards.json."""
    entries: list[CardIndexEntry] = []
    for d in sorted(digests, key=lambda x: x.date, reverse=True):
        for g in d.groups:
            for item in g.items:
                entries.append(
                    CardIndexEntry(
                        date=d.date,
                        id=item.id,
                        region=g.region,
                        category=g.category,
                        headline=item.headline,
                        house=item.house,
                        ticker=item.ticker,
                        name=item.name,
                        opinion=item.opinion,
                        target=item.target,
                    )
                )
    return entries
```

Also add the import at the top by merging with the existing `from market_digest.models import Digest` line:

```python
from market_digest.models import CardIndexEntry, Digest
```

(Remove the duplicate import appended above if it remains.)

- [ ] **Step 4: Run tests**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_index.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/builder.py tests/web/test_index.py
git commit -m "feat(web): build flat cards.json search index"
```

---

## Task 4: Jinja templates and base layout

**Files:**
- Create: `market_digest/web/templates/base.html.j2`
- Create: `market_digest/web/templates/card_page.html.j2`
- Create: `market_digest/web/templates/empty_day.html.j2`
- Modify: `market_digest/web/builder.py`
- Create: `tests/web/test_render.py`

- [ ] **Step 1: Write failing render tests (cards page only for now)**

Create `tests/web/test_render.py`:

```python
from bs4 import BeautifulSoup

from market_digest.models import Digest
from market_digest.web.builder import render_card_page


def _digest() -> Digest:
    return Digest.model_validate(
        {
            "date": "2026-04-19",
            "groups": [
                {
                    "region": "kr",
                    "category": "company",
                    "title": "국내 기업리포트",
                    "items": [
                        {
                            "id": "kr-company-0",
                            "headline": "HBM 업황 회복",
                            "body_md": "- line",
                            "house": "미래에셋",
                            "ticker": "005930",
                            "name": "삼성전자",
                            "opinion": "Buy",
                            "target": "85→95k",
                        }
                    ],
                }
            ],
        }
    )


def test_card_page_has_date_and_weekday():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    header = soup.find(class_="date-header")
    assert "2026-04-19" in header.text
    assert "일" in header.text  # 2026-04-19 is Sunday (일요일) — only the char


def test_card_links_to_detail_page():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("a.card")
    assert link["href"] == "2026-04-19/kr-company-0.html"
    assert "삼성전자" in link.text
    assert "HBM 업황 회복" in link.text


def test_prev_next_links_when_present():
    html = render_card_page(_digest(), prev_date="2026-04-18", next_date="2026-04-20")
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "2026-04-18.html"
    assert soup.select_one("a.nav-next")["href"] == "2026-04-20.html"


def test_prev_next_disabled_when_absent():
    html = render_card_page(_digest(), prev_date=None, next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".nav-prev.disabled") is not None
    assert soup.select_one(".nav-next.disabled") is not None


def test_empty_day_message():
    d = Digest.model_validate({"date": "2026-04-20", "groups": []})
    html = render_card_page(d, prev_date="2026-04-19", next_date=None)
    soup = BeautifulSoup(html, "html.parser")
    assert "오늘 수집된 리포트 없음" in soup.text
```

Make sure `beautifulsoup4` is in dev deps (it's already a runtime dep via fetchers — confirmed).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py -v`
Expected: FAIL (`render_card_page` not importable)

- [ ] **Step 3: Create `base.html.j2`**

Create `market_digest/web/templates/base.html.j2`:

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
<main class="page">
{% block content %}{% endblock %}
</main>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 4: Create `card_page.html.j2`**

Create `market_digest/web/templates/card_page.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ digest.date }} · 마켓 다이제스트{% endblock %}
{% block content %}
<header class="date-header">
  {% if prev_date %}<a class="nav-prev" href="{{ prev_date }}.html">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  <span class="date-label">{{ digest.date }} ({{ weekday }})</span>
  {% if next_date %}<a class="nav-next" href="{{ next_date }}.html">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
  <a class="nav-search" href="search.html">🔍</a>
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
        <a class="card" href="{{ digest.date }}/{{ item.id }}.html">
          {% if item.house %}<span class="tag">[{{ item.house }}]</span>{% endif %}
          {% if item.name %}<span class="name">{{ item.name }}</span>{% if item.ticker %} ({{ item.ticker }}){% endif %}{% endif %}
          <span class="dash">—</span>
          <span class="headline">{{ item.headline }}</span>
          {% if item.opinion or item.target %}<span class="meta">· {{ item.opinion }} {{ item.target }}</span>{% endif %}
        </a>
      </li>
      {% endfor %}
    </ul>
  </section>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Implement `render_card_page` in builder**

Add to the top of `market_digest/web/builder.py`:

```python
import datetime as _dt
from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(
    loader=PackageLoader("market_digest.web", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _flag(region: str) -> str:
    return {"kr": "🇰🇷", "us": "🇺🇸"}.get(region, "")


_env.globals["group_flag"] = _flag


def _weekday(date: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return _WEEKDAYS[_dt.date(y, m, d).weekday()]
```

Then add:

```python
def render_card_page(digest: Digest, *, prev_date: str | None, next_date: str | None) -> str:
    template = _env.get_template("card_page.html.j2")
    return template.render(
        digest=digest,
        prev_date=prev_date,
        next_date=next_date,
        weekday=_weekday(digest.date),
        asset_prefix="",
    )
```

- [ ] **Step 6: Run tests**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py -v`
Expected: 5 passed. (2026-04-19 is a Sunday in reality; test uses `"일" in header.text` which is permissive.)

- [ ] **Step 7: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/templates/ market_digest/web/builder.py tests/web/test_render.py
git commit -m "feat(web): render card page template"
```

---

## Task 5: Detail page rendering (markdown + prev/next)

**Files:**
- Create: `market_digest/web/templates/detail_page.html.j2`
- Modify: `market_digest/web/builder.py`
- Modify: `tests/web/test_render.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_render.py`:

```python
from market_digest.web.builder import render_detail_page


def _group_with_three_items():
    return {
        "region": "kr",
        "category": "company",
        "title": "국내 기업리포트",
        "items": [
            {"id": "kr-company-0", "headline": "A", "body_md": "- body A"},
            {"id": "kr-company-1", "headline": "B", "body_md": "- body B"},
            {"id": "kr-company-2", "headline": "C", "body_md": "- body C"},
        ],
    }


def test_detail_renders_body_md_as_html():
    d = Digest.model_validate({"date": "2026-04-19", "groups": [_group_with_three_items()]})
    html = render_detail_page(
        digest=d,
        group_index=0,
        item_index=1,
        flat_ids=["kr-company-0", "kr-company-1", "kr-company-2"],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("main.page article") is not None
    # markdown-it renders `- body B` as a <ul><li>body B</li></ul>
    li = soup.select_one("article li")
    assert li is not None and "body B" in li.text


def test_detail_prev_next_within_day():
    d = Digest.model_validate({"date": "2026-04-19", "groups": [_group_with_three_items()]})
    html = render_detail_page(
        digest=d,
        group_index=0,
        item_index=1,
        flat_ids=["kr-company-0", "kr-company-1", "kr-company-2"],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("a.nav-prev")["href"] == "kr-company-0.html"
    assert soup.select_one("a.nav-next")["href"] == "kr-company-2.html"


def test_detail_prev_disabled_at_first_item():
    d = Digest.model_validate({"date": "2026-04-19", "groups": [_group_with_three_items()]})
    html = render_detail_page(
        digest=d,
        group_index=0,
        item_index=0,
        flat_ids=["kr-company-0", "kr-company-1", "kr-company-2"],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".nav-prev.disabled") is not None


def test_detail_back_link_to_card_page():
    d = Digest.model_validate({"date": "2026-04-19", "groups": [_group_with_three_items()]})
    html = render_detail_page(
        digest=d,
        group_index=0,
        item_index=0,
        flat_ids=["kr-company-0"],
    )
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("a.back")["href"] == "../2026-04-19.html"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py -v`
Expected: the new tests FAIL (`render_detail_page` missing).

- [ ] **Step 3: Create `detail_page.html.j2`**

Create `market_digest/web/templates/detail_page.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ item.name or item.headline }} · {{ digest.date }}{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="../{{ digest.date }}.html">←&nbsp;{{ digest.date }}</a>
  {% if prev_id %}<a class="nav-prev" href="{{ prev_id }}.html">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  {% if next_id %}<a class="nav-next" href="{{ next_id }}.html">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
</header>

<article>
  <h1>
    {% if item.name %}{{ item.name }}{% if item.ticker %} ({{ item.ticker }}){% endif %}{% else %}{{ item.headline }}{% endif %}
    {% if item.house %}<span class="tag">[{{ item.house }}]</span>{% endif %}
  </h1>
  {% if item.opinion or item.target %}
  <p class="meta">{{ item.opinion }}{% if item.opinion and item.target %} · {% endif %}{{ item.target }}</p>
  {% endif %}
  <div class="body">
    {{ body_html|safe }}
  </div>
  {% if item.url %}<p class="source"><a href="{{ item.url }}" rel="noopener">원문 링크</a></p>{% endif %}
</article>
{% endblock %}
```

- [ ] **Step 4: Implement `render_detail_page`**

Append to `market_digest/web/builder.py`:

```python
from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})


def render_detail_page(
    *,
    digest: Digest,
    group_index: int,
    item_index: int,
    flat_ids: list[str],
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
        asset_prefix="../",
    )
```

- [ ] **Step 5: Run tests**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py -v`
Expected: all 9 pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/templates/detail_page.html.j2 market_digest/web/builder.py tests/web/test_render.py
git commit -m "feat(web): render detail pages with markdown body and in-day nav"
```

---

## Task 6: Search page template and JS

**Files:**
- Create: `market_digest/web/templates/search.html.j2`
- Create: `market_digest/web/assets/search.js`
- Modify: `market_digest/web/builder.py`
- Modify: `tests/web/test_render.py`

- [ ] **Step 1: Extend tests**

Append to `tests/web/test_render.py`:

```python
from market_digest.web.builder import render_search_page


def test_search_page_loads_cards_json():
    html = render_search_page()
    soup = BeautifulSoup(html, "html.parser")
    # The search page references cards.json via script
    assert "cards.json" in html
    assert soup.select_one("input#search-input") is not None
    assert soup.select_one("#search-results") is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py::test_search_page_loads_cards_json -v`
Expected: FAIL.

- [ ] **Step 3: Create `search.html.j2`**

Create `market_digest/web/templates/search.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}검색 · 마켓 다이제스트{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="index.html">← 홈</a>
  <span class="date-label">검색</span>
</header>
<input id="search-input" type="search" placeholder="종목, 티커, 하우스…" autocomplete="off">
<p id="search-count" class="subtitle"></p>
<ul id="search-results" class="cards"></ul>
{% endblock %}
{% block scripts %}
<script src="assets/search.js" defer></script>
{% endblock %}
```

- [ ] **Step 4: Create `search.js`**

Create `market_digest/web/assets/search.js`:

```javascript
(async () => {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const count = document.getElementById("search-count");

  let cards = [];
  try {
    cards = await (await fetch("cards.json")).json();
  } catch (e) {
    count.textContent = "검색 데이터를 불러오지 못했습니다.";
    return;
  }

  const render = (matches) => {
    count.textContent = `결과 ${matches.length}`;
    results.innerHTML = matches.map((c) => {
      const flag = c.region === "us" ? "🇺🇸" : "🇰🇷";
      const href = `${c.date}/${c.id}.html`;
      const tag = c.house ? `<span class="tag">[${c.house}]</span>` : "";
      const nameLine = c.name ? `<span class="name">${c.name}</span>` : "";
      const ticker = c.ticker ? ` (${c.ticker})` : "";
      const meta = (c.opinion || c.target) ? `<span class="meta">· ${c.opinion || ""} ${c.target || ""}</span>` : "";
      return `<li><a class="card" href="${href}"><span class="date-chip">${c.date}</span> ${flag} ${tag} ${nameLine}${ticker} <span class="dash">—</span> <span class="headline">${c.headline}</span> ${meta}</a></li>`;
    }).join("");
  };

  const match = (q) => {
    q = q.trim().toLowerCase();
    if (!q) return [];
    return cards.filter((c) => {
      const hay = [c.name, c.ticker, c.house, c.headline].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(q);
    });
  };

  input.addEventListener("input", () => render(match(input.value)));
  input.focus();
})();
```

- [ ] **Step 5: Implement `render_search_page`**

Append to `market_digest/web/builder.py`:

```python
def render_search_page() -> str:
    template = _env.get_template("search.html.j2")
    return template.render(asset_prefix="")
```

- [ ] **Step 6: Run tests**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_render.py -v`
Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/templates/search.html.j2 market_digest/web/assets/search.js market_digest/web/builder.py tests/web/test_render.py
git commit -m "feat(web): search page with client-side filter over cards.json"
```

---

## Task 7: Mobile-first stylesheet

**Files:**
- Create: `market_digest/web/assets/style.css`

- [ ] **Step 1: Create the stylesheet**

Create `market_digest/web/assets/style.css`:

```css
:root {
  --bg: #fbfbfb;
  --fg: #111;
  --muted: #666;
  --card-bg: #fff;
  --border: #e3e3e3;
  --accent: #2266dd;
  color-scheme: light dark;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121212;
    --fg: #eee;
    --muted: #888;
    --card-bg: #1b1b1b;
    --border: #2a2a2a;
    --accent: #6aa6ff;
  }
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
      "Malgun Gothic", Roboto, sans-serif;
}

.page {
  max-width: 640px;
  margin: 0 auto;
  padding: 0 16px 32px;
}

.date-header {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; gap: 12px;
  padding: 12px 0;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  font-weight: 600;
}
.date-header .date-label { flex: 1; text-align: center; }
.date-header a, .date-header .disabled {
  text-decoration: none; color: var(--fg);
  padding: 4px 8px; border-radius: 6px;
}
.date-header .disabled { color: var(--muted); opacity: 0.4; }
.date-header .back { flex: 0 0 auto; color: var(--accent); }
.date-header .nav-search { margin-left: auto; }

section.group { margin: 16px 0; }
section.group h2 { font-size: 15px; margin: 16px 0 8px; color: var(--muted); font-weight: 600; }

ul.cards { list-style: none; margin: 0; padding: 0; }
ul.cards li { margin: 0 0 8px; }

a.card {
  display: block;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  color: var(--fg);
  text-decoration: none;
  font-size: 15px;
}
a.card:active { background: var(--border); }
a.card .tag { color: var(--muted); font-size: 13px; margin-right: 4px; }
a.card .name { font-weight: 600; }
a.card .dash { color: var(--muted); margin: 0 4px; }
a.card .meta { color: var(--muted); font-size: 13px; margin-left: 4px; }
a.card .date-chip { color: var(--muted); font-size: 12px; margin-right: 6px; }

article h1 { font-size: 20px; margin: 16px 0 4px; }
article h1 .tag { color: var(--muted); font-size: 14px; font-weight: 500; margin-left: 6px; }
article .meta { color: var(--muted); margin: 0 0 16px; }
article .body { font-size: 15px; }
article .body ul { padding-left: 20px; }
article .body a { color: var(--accent); }
article .source { margin-top: 24px; font-size: 14px; }
article .source a { color: var(--accent); }

#search-input {
  width: 100%;
  font-size: 16px;
  padding: 10px 12px;
  margin: 16px 0 8px;
  background: var(--card-bg);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 10px;
}
#search-count { color: var(--muted); font-size: 13px; margin: 4px 0 12px; }

p.empty { color: var(--muted); text-align: center; margin: 48px 0; }
p.subtitle { color: var(--muted); font-size: 14px; }
```

- [ ] **Step 2: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/assets/style.css
git commit -m "feat(web): mobile-first stylesheet with dark mode"
```

---

## Task 8: Orchestrating `build()` with atomic swap

**Files:**
- Modify: `market_digest/web/builder.py`
- Create: `tests/web/test_build.py`

- [ ] **Step 1: Write failing build tests**

Create `tests/web/test_build.py`:

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


def _company_group(items: list[dict]) -> dict:
    return {"region": "kr", "category": "company", "title": "국내 기업리포트", "items": items}


def test_build_writes_expected_files(tmp_path):
    _write(tmp_path, "2026-04-19", [
        _company_group([{"id": "kr-company-0", "headline": "h", "body_md": "- b"}])
    ])

    site = build(tmp_path)

    assert (site / "index.html").is_file()
    assert (site / "2026-04-19.html").is_file()
    assert (site / "2026-04-19" / "kr-company-0.html").is_file()
    assert (site / "search.html").is_file()
    assert (site / "cards.json").is_file()
    assert (site / "assets" / "style.css").is_file()
    assert (site / "assets" / "search.js").is_file()


def test_build_index_is_newest_day(tmp_path):
    _write(tmp_path, "2026-04-18", [_company_group([{"id": "kr-company-0", "headline": "old", "body_md": "-"}])])
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "new", "body_md": "-"}])])

    site = build(tmp_path)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "new" in index
    assert "2026-04-19" in index


def test_build_prev_next_links(tmp_path):
    for d in ("2026-04-17", "2026-04-18", "2026-04-19"):
        _write(tmp_path, d, [_company_group([{"id": "kr-company-0", "headline": d, "body_md": "-"}])])

    site = build(tmp_path)
    middle = BeautifulSoup((site / "2026-04-18.html").read_text(encoding="utf-8"), "html.parser")
    assert middle.select_one("a.nav-prev")["href"] == "2026-04-17.html"
    assert middle.select_one("a.nav-next")["href"] == "2026-04-19.html"

    first = BeautifulSoup((site / "2026-04-17.html").read_text(encoding="utf-8"), "html.parser")
    assert first.select_one(".nav-prev.disabled") is not None

    last = BeautifulSoup((site / "2026-04-19.html").read_text(encoding="utf-8"), "html.parser")
    assert last.select_one(".nav-next.disabled") is not None


def test_build_empty_day_renders_message(tmp_path):
    _write(tmp_path, "2026-04-19", [])

    site = build(tmp_path)
    html = (site / "2026-04-19.html").read_text(encoding="utf-8")
    assert "오늘 수집된 리포트 없음" in html


def test_build_cards_json_excludes_body_md_and_sorts_desc(tmp_path):
    _write(tmp_path, "2026-04-18", [_company_group([{"id": "kr-company-0", "headline": "old", "body_md": "X"}])])
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "new", "body_md": "Y"}])])

    site = build(tmp_path)
    cards = json.loads((site / "cards.json").read_text(encoding="utf-8"))
    assert cards[0]["date"] == "2026-04-19"
    assert cards[1]["date"] == "2026-04-18"
    assert "body_md" not in cards[0]


def test_build_is_idempotent(tmp_path):
    _write(tmp_path, "2026-04-19", [_company_group([{"id": "kr-company-0", "headline": "h", "body_md": "-"}])])

    site1 = build(tmp_path)
    first = (site1 / "2026-04-19.html").read_text(encoding="utf-8")

    site2 = build(tmp_path)
    second = (site2 / "2026-04-19.html").read_text(encoding="utf-8")

    assert first == second


def test_build_returns_empty_site_when_no_digests(tmp_path):
    site = build(tmp_path)
    # Empty NAS should still produce a usable site (search page + empty index)
    assert (site / "search.html").is_file()
    assert (site / "cards.json").read_text(encoding="utf-8").strip() == "[]"
```

- [ ] **Step 2: Run to verify failures**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_build.py -v`
Expected: FAIL (no `build` function yet that writes all these artifacts).

- [ ] **Step 3: Implement `build()` with atomic swap**

Append to `market_digest/web/builder.py`:

```python
import json as _json
import shutil
from importlib import resources


def _flat_ids_for_day(digest: Digest) -> list[str]:
    return [item.id for group in digest.groups for item in group.items]


def _copy_assets(site: Path) -> None:
    dest = site / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    pkg = resources.files("market_digest.web") / "assets"
    for name in ("style.css", "search.js"):
        src = pkg / name
        (dest / name).write_bytes(src.read_bytes())


def build(nas_dir: Path) -> Path:
    """Generate the static site at `nas_dir/site/`. Returns the site path.

    Writes to `site.tmp/` then renames to `site/` so a failed build leaves
    the previous version untouched.
    """
    digests = collect_digests(nas_dir)
    dates = [d.date for d in digests]

    tmp = nas_dir / "site.tmp"
    final = nas_dir / "site"
    old = nas_dir / "site.old"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    # cards.json (search index)
    entries = build_index(digests)
    (tmp / "cards.json").write_text(
        _json.dumps([e.model_dump(exclude_none=True) for e in entries], ensure_ascii=False),
        encoding="utf-8",
    )

    # search page
    (tmp / "search.html").write_text(render_search_page(), encoding="utf-8")

    # per-day pages
    for i, digest in enumerate(digests):
        prev_date = dates[i - 1] if i > 0 else None
        next_date = dates[i + 1] if i < len(dates) - 1 else None
        card_html = render_card_page(digest, prev_date=prev_date, next_date=next_date)
        (tmp / f"{digest.date}.html").write_text(card_html, encoding="utf-8")

        # detail pages
        flat_ids = _flat_ids_for_day(digest)
        day_dir = tmp / digest.date
        if flat_ids:
            day_dir.mkdir(exist_ok=True)
        for gi, group in enumerate(digest.groups):
            for ii, item in enumerate(group.items):
                detail_html = render_detail_page(
                    digest=digest,
                    group_index=gi,
                    item_index=ii,
                    flat_ids=flat_ids,
                )
                (day_dir / f"{item.id}.html").write_text(detail_html, encoding="utf-8")

    # index.html = latest day's card page (or a minimal placeholder page)
    if digests:
        latest = digests[-1]
        (tmp / "index.html").write_text(
            render_card_page(latest, prev_date=dates[-2] if len(dates) > 1 else None, next_date=None),
            encoding="utf-8",
        )
    else:
        (tmp / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>마켓 다이제스트</title>"
            "<p style='font:16px sans-serif;text-align:center;padding:48px'>아직 리포트가 없습니다.</p>",
            encoding="utf-8",
        )

    _copy_assets(tmp)

    # atomic swap
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        final.rename(old)
    tmp.rename(final)
    if old.exists():
        shutil.rmtree(old)

    return final
```

- [ ] **Step 4: Run tests**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/ -v`
Expected: all tests pass (models, collect, index, render, build).

- [ ] **Step 5: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/builder.py tests/web/test_build.py
git commit -m "feat(web): build() orchestrator with atomic swap"
```

---

## Task 9: Rewrite `CLAUDE.md` for JSON output

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Replace the full contents of `CLAUDE.md`**

Overwrite `/home/sund4y/market-digest/CLAUDE.md` with:

```markdown
# market-digest 요약 에이전트

너는 이 프로젝트에서 "매일 장마감 후 증권 리포트를 구조화 JSON 으로 요약하는 에이전트" 역할이다. headless 모드(`claude -p`)로 호출된다.

## 작업 순서

1. 호출자가 지시문에서 오늘 날짜(`YYYY-MM-DD`)와 저장 경로를 알려준다.
2. `Glob` 으로 `inbox/{DATE}/*.txt` 를 찾고, 각 파일을 `Read` 한다.
3. 각 파일은 한 개의 리포트/공시/레이팅 변경이다. 파일 상단에 메타데이터(출처·증권사·종목·제목·URL)가 YAML front matter 로 붙어 있다.
4. 내용을 분류·그룹핑하여 아래 스키마에 맞는 JSON 을 만든다.
5. `Write` 로 지정된 경로 하나에만 저장한다. 최종 응답(stdout)은 "저장 완료" 한 줄이면 충분하며, 어떤 다른 포맷도 출력하지 말 것.
6. 다른 툴(Read, Glob, Write 외) 호출 금지.

## JSON 스키마

```json
{
  "date": "YYYY-MM-DD",
  "groups": [
    {
      "region": "kr" | "us",
      "category": "company" | "industry" | "8k" | "rating",
      "title": "국내 기업리포트",
      "items": [
        {
          "id": "{region}-{category}-{index}",
          "house": "미래에셋",
          "ticker": "005930",
          "name": "삼성전자",
          "headline": "HBM 업황 회복, 목표가 상향",
          "opinion": "Buy",
          "target": "85,000 → 95,000",
          "body_md": "- 목표가 85k→95k\n- 2Q 부터 실적 개선",
          "url": "https://..."
        }
      ]
    }
  ]
}
```

필드 규칙:

- `date`: `YYYY-MM-DD` 정확히 일치
- `region`: `"kr"` 또는 `"us"` 만
- `category`: `"company"`, `"industry"`, `"8k"`, `"rating"` 중 하나
- `title`: 사람에게 보여질 그룹 제목 (예: `"국내 기업리포트"`, `"국내 시황·산업"`, `"미국 8-K 주요 공시"`, `"미국 애널리스트 변경"`)
- `items[].id`: `{region}-{category}-{index}` 형식, index 는 그룹 내 0 부터. 예: `"kr-company-0"`, `"us-8k-3"`
- `items[].headline`: **1줄 카드용**. 핵심 요지를 한 줄로. 투자의견/목표가 문구는 `opinion`/`target` 에 넣지 말고 headline 에서는 제외
- `items[].body_md`: **상세용 Markdown**. 3~5줄의 핵심 요약, 필요한 메타 포함
- `items[].opinion`: 투자의견 (`Buy`, `Hold`, ...) — 없으면 생략
- `items[].target`: 목표가. 변경 시 `"85,000 → 95,000"` 형식 — 없으면 생략
- `items[].url`: 원문 URL — 없으면 생략
- `items[].house`, `items[].ticker`, `items[].name`: 식별 불가 시 생략

그룹이 없는 섹션은 `groups` 배열에서 아예 뺀다.

## 필터·편집 원칙

- 중복 제거: 같은 종목·같은 이벤트가 여러 파일에 있으면 한 item 으로 합친다.
- 노이즈 제거: 단순 주가 언급, 일일 시황 반복, 광고성 문구는 item 으로 만들지 않는다.
- 우선순위: 투자의견·목표가 **변경** > 신규 커버리지 > 실적 리뷰 > 단순 업데이트.
- 종목 식별이 모호하면 빼지 말고 `name` 을 "주제"로 묶어 기술한다(예: `"반도체 업황"`).
- 한국어로 작성. 숫자·티커는 원문 유지.

## 실패 처리

- `inbox/{DATE}/` 가 없거나 비어 있으면 `{"date": "{DATE}", "groups": []}` 만 Write 한다.
- 일부 파일 읽기 실패 시 그 파일은 건너뛰고 나머지로 진행.
- JSON 은 반드시 유효한 UTF-8 JSON 이어야 한다. 검증된 후 저장.
```

- [ ] **Step 2: Commit**

```bash
cd /home/sund4y/market-digest
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md for JSON output (drops Telegram format)"
```

---

## Task 10: Update `summarize.py` to expect JSON

**Files:**
- Modify: `market_digest/summarize.py`

- [ ] **Step 1: Replace the module**

Overwrite `/home/sund4y/market-digest/market_digest/summarize.py`:

```python
"""Invoke Claude Code headless to read inbox/{date}/ and produce a digest JSON.

The summarization rules live in the project's CLAUDE.md (auto-loaded when
`claude` is run with CWD=project root).
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SummarizeResult:
    json_path: Path
    usage: dict
    session_id: str


def summarize(
    date: str,
    project_dir: Path,
    nas_report_dir: Path,
    claude_cli: str,
    allowed_tools: str,
    permission_mode: str,
    timeout_sec: int = 900,
    max_budget_usd: float | None = None,
) -> SummarizeResult:
    """Run claude -p and return the path of the digest JSON it produced."""
    yyyy, mm, _ = date.split("-")
    json_path = nas_report_dir / yyyy / mm / f"{date}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)

    instruction = (
        f"오늘 날짜는 {date}이다. "
        f"inbox/{date}/ 디렉토리의 모든 .txt 파일을 읽고, "
        f"CLAUDE.md 에 정의된 JSON 스키마에 따라 {json_path} 에 Write 하라."
    )

    cmd = [
        claude_cli,
        "-p",
        instruction,
        "--allowed-tools",
        allowed_tools,
        "--permission-mode",
        permission_mode,
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    log.info("summarize: launching claude -p (timeout=%ds)", timeout_sec)
    proc = subprocess.run(
        cmd,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_sec,
    )
    if proc.returncode != 0:
        log.error("claude stderr: %s", proc.stderr)
        raise RuntimeError(f"claude -p failed with code {proc.returncode}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.error("claude stdout was not JSON:\n%s", proc.stdout[:2000])
        raise

    usage = payload.get("usage") or payload.get("total_usage") or {}
    session_id = payload.get("session_id", "")

    if not json_path.exists():
        raise RuntimeError(f"claude did not write expected JSON at {json_path}")

    return SummarizeResult(json_path=json_path, usage=usage, session_id=session_id)
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `cd /home/sund4y/market-digest && uv run pytest -v`
Expected: all tests pass (no tests exist for summarize yet).

- [ ] **Step 3: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/summarize.py
git commit -m "refactor(summarize): expect digest JSON from claude, drop telegram payload"
```

---

## Task 11: Rewrite `run.py` (drop Telegram, add web.build)

**Files:**
- Modify: `market_digest/run.py`

- [ ] **Step 1: Replace the module**

Overwrite `/home/sund4y/market-digest/market_digest/run.py`:

```python
"""market-digest orchestrator.

Runs fetchers, calls `claude -p` for summarization, validates the produced
digest JSON, and rebuilds the static site.

Usage:
    python -m market_digest.run                # today (KST)
    python -m market_digest.run --date 2026-04-17
    python -m market_digest.run --dry-run      # write JSON + site to ./out/
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import zoneinfo
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from market_digest.fetchers import hankyung, sec_edgar, yfinance_recs
from market_digest.models import Digest
from market_digest.summarize import summarize
from market_digest.web import build as web_build

PROJECT_DIR = Path(__file__).resolve().parent.parent
KST = zoneinfo.ZoneInfo("Asia/Seoul")


def setup_logging(date: str) -> logging.Logger:
    logs_dir = PROJECT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{date}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return logging.getLogger("market_digest")


def load_config() -> dict:
    with open(PROJECT_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_digest(json_path: Path, logs_dir: Path, date: str, log: logging.Logger) -> bool:
    """Return True if JSON parses as a valid Digest. On failure, dump a copy."""
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        Digest.model_validate(raw)
        return True
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        log.error("digest validation failed: %s", exc)
        dump = logs_dir / f"{date}-invalid.json"
        try:
            dump.write_bytes(json_path.read_bytes())
            log.error("copied invalid digest to %s", dump)
        except OSError:
            pass
        return False


def run(date: str, dry_run: bool) -> int:
    log = setup_logging(date)
    load_dotenv(PROJECT_DIR / ".env")
    cfg = load_config()

    inbox_dir = PROJECT_DIR / "inbox" / date
    inbox_dir.mkdir(parents=True, exist_ok=True)

    nas_dir = Path(cfg["nas_report_dir"]) if not dry_run else PROJECT_DIR / "out"
    logs_dir = PROJECT_DIR / "logs"

    total = 0

    if cfg["hankyung"]["enabled"]:
        try:
            n = hankyung.fetch_and_save(
                date=date,
                inbox_dir=inbox_dir,
                user_agent=cfg["hankyung"]["user_agent"],
                request_interval_sec=cfg["hankyung"]["request_interval_sec"],
                max_reports=cfg["hankyung"]["max_reports"],
            )
            log.info("hankyung: %d reports saved", n)
            total += n
        except Exception as exc:
            log.exception("hankyung fetcher failed: %s", exc)

    if cfg["sec_edgar"]["enabled"]:
        try:
            ua = os.environ.get("SEC_EDGAR_UA", "market-digest/0.1 (contact@example.com)")
            n = sec_edgar.fetch_and_save(
                date=date,
                inbox_dir=inbox_dir,
                watchlist=cfg["yfinance"]["watchlist"],
                form_types=cfg["sec_edgar"]["form_types"],
                max_items=cfg["sec_edgar"]["max_items"],
                user_agent=ua,
                cache_dir=PROJECT_DIR / ".cache",
            )
            log.info("sec_edgar: %d filings saved", n)
            total += n
        except Exception as exc:
            log.exception("sec_edgar fetcher failed: %s", exc)

    if cfg["yfinance"]["enabled"]:
        try:
            n = yfinance_recs.fetch_and_save(
                date=date,
                inbox_dir=inbox_dir,
                watchlist=cfg["yfinance"]["watchlist"],
            )
            log.info("yfinance: %d analyst changes saved", n)
            total += n
        except Exception as exc:
            log.exception("yfinance fetcher failed: %s", exc)

    log.info("fetch phase done: %d total items in inbox", total)

    result = summarize(
        date=date,
        project_dir=PROJECT_DIR,
        nas_report_dir=nas_dir,
        claude_cli=cfg["claude"]["cli_path"],
        allowed_tools=cfg["claude"]["allowed_tools"],
        permission_mode=cfg["claude"]["permission_mode"],
        timeout_sec=cfg["claude"]["timeout_sec"],
        max_budget_usd=cfg["claude"].get("max_budget_usd"),
    )
    log.info("summarize: json=%s usage=%s session=%s", result.json_path, result.usage, result.session_id)

    if not _validate_digest(result.json_path, logs_dir, date, log):
        # Keep going — the build step will skip this one date.
        pass

    try:
        site = web_build(nas_dir)
        log.info("web.build: site=%s", site)
    except Exception as exc:
        log.exception("web.build failed: %s", exc)
        return 1

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="market-digest runner")
    p.add_argument("--date", help="YYYY-MM-DD (default: today in KST)")
    p.add_argument("--dry-run", action="store_true", help="write JSON + site under ./out/")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    date = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    return run(date=date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/sund4y/market-digest && uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/run.py
git commit -m "refactor(run): drop telegram send, add JSON validation + web.build"
```

---

## Task 12: Delete `telegram.py` and clean env

**Files:**
- Delete: `market_digest/telegram.py`
- Modify: `.env.example`

- [ ] **Step 1: Remove the module and env vars**

Run:

```bash
cd /home/sund4y/market-digest
git rm market_digest/telegram.py
```

Overwrite `.env.example`:

```
# Claude Code CLI 는 기본적으로 로컬 로그인 세션을 사용.
# cron 환경에서 로그인 세션 접근이 안 될 때만 아래 주석을 풀어 API 키를 지정.
# ANTHROPIC_API_KEY=

# SEC EDGAR 는 User-Agent 에 이메일 포함을 요구함 (미포함 시 403)
SEC_EDGAR_UA=market-digest/0.1 (sund4y1123@gmail.com)
```

- [ ] **Step 2: Check nothing still imports the removed module**

Run: `cd /home/sund4y/market-digest && uv run pytest -v && uv run python -c "import market_digest.run"`
Expected: tests pass, import succeeds.

- [ ] **Step 3: Commit**

```bash
cd /home/sund4y/market-digest
git add -A
git commit -m "chore: remove telegram module and env vars"
```

---

## Task 13: Deployment notes (Caddy + Cloudflare Tunnel)

**Files:**
- Create: `deploy/Caddyfile.example`
- Create: `deploy/README.md`

- [ ] **Step 1: Create Caddyfile example**

Create `deploy/Caddyfile.example`:

```Caddyfile
# Append this block to /etc/caddy/Caddyfile.
# Pick a port that's currently free (ss -tlnp to check; avoid 8080/8081/8082/8088/8123/3000/8501).

:8086 {
  root * /mnt/nas/market-digest/site
  encode gzip
  file_server
}
```

- [ ] **Step 2: Create deploy README**

Create `deploy/README.md`:

```markdown
# Deploying the web digest

## 1. Caddy

```bash
sudo apt install caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile.market-digest
# Then either append the block to /etc/caddy/Caddyfile or import it.
sudo systemctl enable --now caddy
curl -I http://localhost:8086    # should return 200 or 404 if site/ isn't built yet
```

## 2. Cloudflare Tunnel

The existing `sund4y-tunnel` is managed from the Cloudflare dashboard
(not a local `config.yml`). Add an ingress rule there:

- Hostname: `market-digest.<your-domain>`
- Service: `http://localhost:8086`

Verify `cloudflared` is running:

```bash
systemctl --user status cloudflared  # or: ps -fp $(pgrep cloudflared)
```

## 3. First build

Static files are produced by `market_digest.run`. Trigger a build with
today's data, or rebuild from existing JSON only:

```bash
uv run python -c "from pathlib import Path; from market_digest.web import build; print(build(Path('/mnt/nas/market-digest')))"
```

## 4. Daily run

The existing cron / scheduler that invokes `python -m market_digest.run`
now also rebuilds the site as its last step.
```

- [ ] **Step 3: Commit**

```bash
cd /home/sund4y/market-digest
git add deploy/
git commit -m "docs(deploy): Caddy + Cloudflare Tunnel setup notes"
```

---

## Final checks

- [ ] **Full test run**

Run: `cd /home/sund4y/market-digest && uv run pytest -v`
Expected: all tests pass.

- [ ] **Dry-run end-to-end**

Run: `cd /home/sund4y/market-digest && uv run python -m market_digest.run --dry-run`
(Requires `claude` CLI login; OK if claude call fails, but `web.build` on `./out/` should still succeed when JSON exists. Skip if claude CLI is not available in the current environment.)

- [ ] **Manual browser sanity check**

Open `file:///home/sund4y/market-digest/out/site/index.html` (after a dry run) on desktop, then on phone via `http://<lan-ip>:<port>` once Caddy is configured. Confirm:
- 카드 탭 → 상세 페이지 이동
- ◀▶ 로 날짜 이동
- 검색어 입력 시 결과 카드 → 상세 이동
- 다크모드 전환 시 정상 렌더
