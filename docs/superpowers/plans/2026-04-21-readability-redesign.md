# Readability Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign card and detail pages for readability — left accent bar (direction-colored), serif company names (Noto Serif KR), monospace meta, no emoji, text region badges.

**Architecture:** Pure frontend redesign. Add a `direction` inference utility (`web/direction.py`), extend `CardIndexEntry` with a `direction` field, recompute in `build_cards_index`, pass `region`/`direction` to detail template, rewrite templates + CSS + `search.js` result renderer. No route changes, no new features.

**Tech Stack:** Jinja2, vanilla CSS/JS, Noto Serif KR via Google Fonts.

**Spec:** `docs/superpowers/specs/2026-04-21-readability-redesign-design.md`

---

## File Structure

**Create:**
- `market_digest/web/direction.py` — pure function `infer_direction(opinion, target) -> Literal["up","down","neutral"]`
- `tests/web/test_direction.py`

**Modify:**
- `market_digest/models.py` — add `direction` to `CardIndexEntry`
- `market_digest/web/data.py` — `build_cards_index` populates `direction`
- `market_digest/web/app.py` — detail_page handler computes `region` + `direction`
- `market_digest/web/templates/base.html.j2` — Google Fonts link, badge text cleanup
- `market_digest/web/templates/card_page.html.j2` — full rewrite
- `market_digest/web/templates/detail_page.html.j2` — full rewrite
- `market_digest/web/templates/search.html.j2` — minor polish
- `market_digest/web/assets/style.css` — full rewrite
- `market_digest/web/assets/search.js` — rewrite result card renderer (include direction + region)
- `market_digest/web/assets/base.js` — badge output simplified
- `tests/web/test_app.py` — adjust markup assertions for redesigned cards/detail
- `tests/web/test_data.py` — cards_index now includes `direction`

---

## Task 1: Direction inference utility

**Files:**
- Create: `market_digest/web/direction.py`
- Create: `tests/web/test_direction.py`

- [ ] **Step 1: Write failing tests**

Create `tests/web/test_direction.py`:

```python
from market_digest.web.direction import infer_direction


def test_up_from_target_arrow_with_commas():
    assert infer_direction(None, "85,000 → 95,000") == "up"


def test_down_from_target_arrow_with_dollar():
    assert infer_direction(None, "$230 → $190") == "down"


def test_neutral_when_target_values_equal():
    assert infer_direction(None, "100 → 100") == "neutral"


def test_ascii_arrow_supported():
    assert infer_direction(None, "50 -> 60") == "up"


def test_opinion_buy_is_up():
    assert infer_direction("Buy", None) == "up"
    assert infer_direction("outperform", None) == "up"
    assert infer_direction("Overweight", None) == "up"
    assert infer_direction("Strong Buy", None) == "up"


def test_opinion_sell_is_down():
    assert infer_direction("Sell", None) == "down"
    assert infer_direction("Underperform", None) == "down"
    assert infer_direction("Underweight", None) == "down"


def test_opinion_hold_is_neutral():
    assert infer_direction("Hold", None) == "neutral"
    assert infer_direction("Neutral", None) == "neutral"
    assert infer_direction("Market Perform", None) == "neutral"


def test_both_missing_is_neutral():
    assert infer_direction(None, None) == "neutral"
    assert infer_direction("", "") == "neutral"


def test_target_arrow_takes_priority_over_opinion():
    # target arrow says down even though opinion is Buy
    assert infer_direction("Buy", "100 → 80") == "down"


def test_target_without_arrow_falls_back_to_opinion():
    assert infer_direction("Buy", "95,000") == "up"


def test_garbled_target_falls_back_to_opinion():
    assert infer_direction("Sell", "TBD") == "down"


def test_unknown_opinion_is_neutral():
    assert infer_direction("Market Weight Update", None) == "neutral"
```

- [ ] **Step 2: Run tests (expect failure)**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_direction.py -v`
Expected: ImportError — module not found.

- [ ] **Step 3: Implement direction.py**

Create `market_digest/web/direction.py`:

```python
"""Infer accent direction (up/down/neutral) for a rating item."""
from __future__ import annotations

import re
from typing import Literal

Direction = Literal["up", "down", "neutral"]

_ARROW_RE = re.compile(r"(.+?)(?:→|->)(.+)")
_NUMBER_RE = re.compile(r"[\d]+(?:,\d+)*(?:\.\d+)?")

_UP_OPINIONS = frozenset({
    "buy", "strong buy", "outperform", "overweight",
    "accumulate", "market outperform", "add", "positive",
})
_DOWN_OPINIONS = frozenset({
    "sell", "strong sell", "underperform", "underweight",
    "reduce", "negative",
})


def _last_number(text: str) -> float | None:
    matches = _NUMBER_RE.findall(text)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


def infer_direction(opinion: str | None, target: str | None) -> Direction:
    """Return up/down/neutral for a card item.

    Priority:
      1. target with arrow ('→' or '->') — compare the last number on each side.
      2. opinion text dictionary lookup (case-insensitive).
      3. neutral as safe default.
    """
    if target:
        m = _ARROW_RE.match(target)
        if m:
            left = _last_number(m.group(1))
            right = _last_number(m.group(2))
            if left is not None and right is not None:
                if right > left:
                    return "up"
                if right < left:
                    return "down"
                return "neutral"
    if opinion:
        key = opinion.strip().lower()
        if key in _UP_OPINIONS:
            return "up"
        if key in _DOWN_OPINIONS:
            return "down"
    return "neutral"
```

- [ ] **Step 4: Run tests (expect pass)**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_direction.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sund4y/market-digest
git add market_digest/web/direction.py tests/web/test_direction.py
git commit -m "feat(web): direction inference utility (up/down/neutral)"
```

---

## Task 2: CardIndexEntry + build_cards_index with direction

**Files:**
- Modify: `market_digest/models.py`
- Modify: `market_digest/web/data.py`
- Modify: `tests/web/test_models.py`
- Modify: `tests/web/test_data.py`

- [ ] **Step 1: Extend model test**

Append to `tests/web/test_models.py`:

```python
def test_card_index_entry_accepts_direction():
    from market_digest.models import CardIndexEntry
    e = CardIndexEntry(
        date="2026-04-20", id="us-rating-0", region="us", category="rating",
        headline="h", direction="up",
    )
    assert e.direction == "up"


def test_card_index_entry_direction_defaults_none():
    from market_digest.models import CardIndexEntry
    e = CardIndexEntry(
        date="2026-04-20", id="us-rating-0", region="us", category="rating", headline="h",
    )
    assert e.direction is None
```

- [ ] **Step 2: Run (expect failure)**

Run: `uv run pytest tests/web/test_models.py -v`
Expected: `direction` field is unknown — validation error.

- [ ] **Step 3: Add field to `CardIndexEntry`**

In `market_digest/models.py`, inside class `CardIndexEntry` (after `target` field, before end of class), add:

```python
    direction: Literal["up", "down", "neutral"] | None = None
```

`Literal` already imported at the top. Keep everything else.

- [ ] **Step 4: Run model tests (expect pass)**

Run: `uv run pytest tests/web/test_models.py -v`
Expected: all pass.

- [ ] **Step 5: Extend data test**

Append to `tests/web/test_data.py`:

```python
def test_build_cards_index_populates_direction_from_target_arrow(tmp_path):
    _write(tmp_path, "2026-04-20", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "headline": "h",
                    "body_md": "-", "target": "$200 → $240"}]},
    ])
    index = build_cards_index(tmp_path)
    assert index[0]["direction"] == "up"


def test_build_cards_index_direction_down_from_opinion(tmp_path):
    _write(tmp_path, "2026-04-20", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "TSLA", "headline": "h",
                    "body_md": "-", "opinion": "Sell"}]},
    ])
    index = build_cards_index(tmp_path)
    assert index[0]["direction"] == "down"


def test_build_cards_index_direction_absent_when_no_signals(tmp_path):
    _write(tmp_path, "2026-04-20", [
        {"region": "kr", "category": "company", "title": "국내",
         "items": [{"id": "kr-company-0", "headline": "h", "body_md": "-"}]},
    ])
    index = build_cards_index(tmp_path)
    # neutral items: direction still populated but equals "neutral"
    assert index[0]["direction"] == "neutral"
```

- [ ] **Step 6: Run (expect failure)**

Run: `uv run pytest tests/web/test_data.py -v`
Expected: `direction` key missing in index entries.

- [ ] **Step 7: Wire direction into build_cards_index**

In `market_digest/web/data.py`, locate `build_cards_index`. Add an import at the top of the file:

```python
from market_digest.web.direction import infer_direction
```

Then replace the `CardIndexEntry(...)` call inside the loop. Replace the existing block:

```python
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
```

with:

```python
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
                    direction=infer_direction(item.opinion, item.target),
                )
                out.append(entry.model_dump(exclude_none=True))
```

- [ ] **Step 8: Run (expect pass)**

Run: `uv run pytest tests/web/test_data.py tests/web/test_models.py -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add market_digest/models.py market_digest/web/data.py tests/web/test_data.py tests/web/test_models.py
git commit -m "feat(web): direction field on CardIndexEntry and cards index"
```

---

## Task 3: Detail page context — region + direction

**Files:**
- Modify: `market_digest/web/app.py`

- [ ] **Step 1: Update detail_page handler**

In `market_digest/web/app.py`, locate the `detail_page` route handler. Inside the handler, after `gi, ii, item = found`, add:

```python
        region = digest.groups[gi].region
```

And after the existing `chart_link` / `chart_tv` computation block, compute direction:

```python
        from market_digest.web.direction import infer_direction
        direction = infer_direction(item.opinion, item.target)
```

Update the `template.render(...)` call to include both:

```python
        html = app.state.env.get_template("detail_page.html.j2").render(
            digest=digest,
            item=item,
            region=region,
            direction=direction,
            prev_id=prev_id,
            next_id=next_id,
            body_html=body_html,
            has_research=has_research,
            chart_link=chart_link,
            chart_tv=chart_tv,
            asset_prefix="/",
        )
```

Similarly update the card_page handler to pass `direction` per item. Since card_page iterates in the template, we precompute a dict:

Locate the `card_page` route handler. Before the `template.render` call, add:

```python
        from market_digest.web.direction import infer_direction
        directions = {
            item.id: infer_direction(item.opinion, item.target)
            for group in digest.groups for item in group.items
        }
```

Update `template.render(...)` to include `directions=directions`:

```python
        html = app.state.env.get_template("card_page.html.j2").render(
            digest=digest,
            prev_date=prev_d,
            next_date=next_d,
            weekday=_weekday(date),
            directions=directions,
            asset_prefix="/",
        )
```

- [ ] **Step 2: Run full suite to make sure nothing breaks yet**

Run: `cd /home/sund4y/market-digest && uv run pytest -v`
Expected: all existing tests still pass (nothing asserts on `directions`/`region` yet).

- [ ] **Step 3: Commit**

```bash
git add market_digest/web/app.py
git commit -m "feat(web): pass region + direction to card/detail templates"
```

---

## Task 4: Base layout — Noto Serif KR + badge simplification

**Files:**
- Modify: `market_digest/web/templates/base.html.j2`
- Modify: `market_digest/web/assets/base.js`

- [ ] **Step 1: Update base.html.j2**

Replace the full content of `market_digest/web/templates/base.html.j2` with:

```jinja
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{% block title %}마켓 다이제스트{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@500;700&display=swap">
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

- [ ] **Step 2: Simplify badge output in base.js**

Find the line in `market_digest/web/assets/base.js`:

```javascript
        badge.textContent = `🔍 ${jobs.length}`;
```

Replace with:

```javascript
        badge.textContent = String(jobs.length);
```

- [ ] **Step 3: Sanity check**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_app.py -v`
Expected: the `test_research_js_served` test currently asserts `"global-research-badge" in base.js` — still passes. `test_static_asset_served` still passes (base.js served).

- [ ] **Step 4: Commit**

```bash
git add market_digest/web/templates/base.html.j2 market_digest/web/assets/base.js
git commit -m "style(web): load Noto Serif KR in base template; clean badge text"
```

---

## Task 5: Card page template rewrite

**Files:**
- Modify: `market_digest/web/templates/card_page.html.j2`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Replace card_page template**

Overwrite `market_digest/web/templates/card_page.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ digest.date }} · 마켓 다이제스트{% endblock %}
{% block content %}
<header class="date-header">
  {% if prev_date %}<a class="nav-prev" href="/{{ prev_date }}">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  <span class="date-label">{{ digest.date }} ({{ weekday }})</span>
  {% if next_date %}<a class="nav-next" href="/{{ next_date }}">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
  <a class="nav-search" href="/search">검색</a>
</header>

{% if not digest.groups %}
  <p class="empty">오늘 수집된 리포트 없음</p>
{% else %}
  {% for group in digest.groups %}
  <section class="group">
    <h2 class="group-title">{{ group.title }}</h2>
    <ul class="cards">
      {% for item in group.items %}
      {% set dir = directions[item.id] %}
      <li>
        <a class="card card-{{ dir }}" href="/{{ digest.date }}/{{ item.id }}">
          <span class="accent"></span>
          <div class="card-body">
            <div class="eyebrow">
              <span class="region">{{ "KR" if group.region == "kr" else "US" }}</span>
              {% if item.house %}<b class="house">{{ item.house }}</b>{% endif %}
              {% if item.ticker %}<span class="sep">·</span><span class="ticker">{{ item.ticker }}</span>{% endif %}
            </div>
            {% if item.name %}<div class="name">{{ item.name }}{% if item.ticker %}<span class="ticker-inline">{{ item.ticker }}</span>{% endif %}</div>{% endif %}
            <div class="headline">{{ item.headline }}</div>
            {% if item.opinion or item.target %}
            <div class="meta meta-{{ dir }}">{% if item.opinion %}{{ item.opinion|upper }}{% endif %}{% if item.opinion and item.target %} · {% endif %}{% if item.target %}{{ item.target }}{% endif %}</div>
            {% endif %}
            {% if item.company_blurb %}<div class="blurb">{{ item.company_blurb }}</div>{% endif %}
          </div>
        </a>
      </li>
      {% endfor %}
    </ul>
  </section>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Update existing card tests**

In `tests/web/test_app.py`, locate `test_card_page_renders_groups_and_cards`. Replace it with:

```python
def test_card_page_renders_groups_and_cards(nas):
    _write(nas, "2026-04-19", [
        {"region": "kr", "category": "company", "title": "국내 기업리포트",
         "items": [{"id": "kr-company-0", "headline": "HBM 회복", "body_md": "-",
                    "house": "메리츠", "name": "삼성전자", "ticker": "005930",
                    "opinion": "Buy", "target": "85,000 → 95,000"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    link = soup.select_one("a.card")
    assert link["href"] == "/2026-04-19/kr-company-0"
    assert "card-up" in (link.get("class") or [])
    assert soup.select_one("a.card .accent") is not None
    assert soup.select_one("a.card .region").text == "KR"
    assert soup.select_one("a.card .name").get_text(strip=False).startswith("삼성전자")
    # group h2 should be plain text without emoji
    h2 = soup.select_one("section.group h2.group-title")
    assert h2.text.strip() == "국내 기업리포트"
    assert "🇰🇷" not in resp.text
```

- [ ] **Step 3: Run (expect pass)**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_app.py::test_card_page_renders_groups_and_cards -v`
Expected: PASS.

- [ ] **Step 4: Run full suite to see breakage from other tests**

Run: `uv run pytest -v`
Expected: other card-page tests may need minor updates (prev/next still pass — template unchanged there). Note any failures; they will be addressed when CSS lands (Task 8). For now, only the test we just rewrote must pass; others referencing old CSS classes may pass anyway as they target layout anchors (a.nav-prev etc.).

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/templates/card_page.html.j2 tests/web/test_app.py
git commit -m "feat(web): card page template with accent bar + eyebrow + serif name"
```

---

## Task 6: Detail page template rewrite

**Files:**
- Modify: `market_digest/web/templates/detail_page.html.j2`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Replace detail_page template**

Overwrite `market_digest/web/templates/detail_page.html.j2` with:

```jinja
{% extends "base.html.j2" %}
{% block title %}{{ item.name or item.headline }} · {{ digest.date }}{% endblock %}
{% block content %}
<header class="date-header">
  <a class="back" href="/{{ digest.date }}">← {{ digest.date }}</a>
  {% if prev_id %}<a class="nav-prev" href="/{{ digest.date }}/{{ prev_id }}">◀</a>{% else %}<span class="nav-prev disabled">◀</span>{% endif %}
  {% if next_id %}<a class="nav-next" href="/{{ digest.date }}/{{ next_id }}">▶</a>{% else %}<span class="nav-next disabled">▶</span>{% endif %}
  <a class="nav-search" href="/search">검색</a>
</header>

<article class="detail detail-{{ direction }}">
  <span class="accent"></span>
  <div class="detail-body">
    <div class="eyebrow">
      <span class="region">{{ "KR" if region == "kr" else "US" }}</span>
      {% if item.house %}<b class="house">{{ item.house }}</b>{% endif %}
      {% if item.ticker %}<span class="sep">·</span><span class="ticker">{{ item.ticker }}</span>{% endif %}
    </div>
    <h1>{% if item.name %}{{ item.name }}{% if item.ticker %}<span class="ticker-inline">{{ item.ticker }}</span>{% endif %}{% else %}{{ item.headline }}{% endif %}</h1>
    {% if item.company_blurb %}<p class="blurb">{{ item.company_blurb }}</p>{% endif %}
    {% if item.opinion or item.target %}
    <div class="meta-strip meta-{{ direction }}">
      {% if item.opinion %}<span class="label">RATING</span> {{ item.opinion|upper }}{% endif %}
      {% if item.opinion and item.target %} &nbsp;·&nbsp; {% endif %}
      {% if item.target %}<span class="label">TARGET</span> {{ item.target }}{% endif %}
    </div>
    {% endif %}
    {% if body_html %}
    <div class="body">
      {{ body_html|safe }}
    </div>
    {% endif %}

    <div class="actions">
      {% if item.url %}<a class="action" href="{{ item.url }}" rel="noopener" target="_blank">원문 링크 →</a>{% endif %}
      {% if chart_link %}
      <a class="action" href="{{ chart_link.url }}" rel="noopener" target="_blank">{{ chart_link.label }}</a>
      {% elif chart_tv %}
      <div class="chart-embed">
        <div class="tradingview-widget-container">
          <div class="tradingview-widget-container__widget"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
          {
            "autosize": true,
            "symbol": "{{ chart_tv.symbol }}",
            "interval": "D",
            "range": "6M",
            "timezone": "Asia/Seoul",
            "theme": "light",
            "style": "2",
            "locale": "kr",
            "toolbar_bg": "transparent",
            "hide_top_toolbar": true,
            "hide_side_toolbar": true,
            "hide_legend": false,
            "allow_symbol_change": false,
            "save_image": false,
            "withdateranges": true
          }
          </script>
        </div>
      </div>
      {% endif %}
      {% if has_research %}
        <a class="action" href="/{{ digest.date }}/{{ item.id }}/research" rel="noopener">딥 리서치 보기</a>
      {% elif item.ticker %}
        <button id="research-btn" class="action" type="button"
                data-ticker="{{ item.ticker }}" data-date="{{ digest.date }}">딥 리서치 시작</button>
        <span id="research-status" class="subtitle"></span>
      {% endif %}
    </div>
  </div>
</article>
{% endblock %}
{% block scripts %}
<script src="/assets/research.js" defer></script>
{% endblock %}
```

Note: we added `"range": "6M"` and `"withdateranges": true` to the TradingView config.

- [ ] **Step 2: Update detail tests**

In `tests/web/test_app.py`, find `test_detail_page_renders` and replace with:

```python
def test_detail_page_renders(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "MS upgrade", "body_md": "- detail",
                    "opinion": "Buy", "target": "$200 → $240",
                    "company_blurb": "스마트폰·서비스"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("article.detail.detail-up") is not None
    assert soup.select_one("article .accent") is not None
    assert soup.select_one(".eyebrow .region").text == "US"
    h1 = soup.select_one("article h1")
    assert "Apple" in h1.text
    assert "스마트폰" in resp.text
    # meta strip
    assert "RATING" in resp.text and "TARGET" in resp.text
    # no emoji
    assert "🇺🇸" not in resp.text
    assert "📈" not in resp.text
    # research UI as button (no md)
    assert soup.select_one("button#research-btn") is not None


def test_detail_page_actions_order(nas):
    _write(nas, "2026-04-19", [
        {"region": "us", "category": "rating", "title": "미국",
         "items": [{"id": "us-rating-0", "ticker": "AAPL", "name": "Apple",
                    "headline": "h", "body_md": "-", "url": "https://src.example/x"}]},
    ])
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/2026-04-19/us-rating-0")
    # Order: url (원문) appears before research button or tv embed in source order
    i_url = resp.text.find("원문 링크")
    i_chart = resp.text.find("embed-widget-advanced-chart.js")
    i_research = resp.text.find("딥 리서치")
    assert i_url != -1
    assert 0 <= i_url < i_chart
    assert i_chart < i_research
```

- [ ] **Step 3: Run (expect pass)**

Run: `uv run pytest tests/web/test_app.py::test_detail_page_renders tests/web/test_app.py::test_detail_page_actions_order -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add market_digest/web/templates/detail_page.html.j2 tests/web/test_app.py
git commit -m "feat(web): detail page redesign with accent bar, serif h1, action order"
```

---

## Task 7: Search page + search.js result renderer

**Files:**
- Modify: `market_digest/web/templates/search.html.j2`
- Modify: `market_digest/web/assets/search.js`
- Modify: `tests/web/test_app.py`

- [ ] **Step 1: Replace search.html.j2**

Overwrite `market_digest/web/templates/search.html.j2`:

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

- [ ] **Step 2: Replace search.js result renderer**

Overwrite `market_digest/web/assets/search.js`:

```javascript
(async () => {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const count = document.getElementById("search-count");

  let cards = [];
  try {
    cards = await (await fetch("/cards.json")).json();
  } catch (e) {
    count.textContent = "검색 데이터를 불러오지 못했습니다.";
    return;
  }

  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const render = (matches) => {
    count.textContent = `결과 ${matches.length}`;
    results.innerHTML = matches.map((c) => {
      const dir = c.direction || "neutral";
      const region = c.region === "us" ? "US" : "KR";
      const href = `/${c.date}/${c.id}`;
      const house = c.house ? `<b class="house">${esc(c.house)}</b>` : "";
      const tickerRow = c.ticker ? `<span class="sep">·</span><span class="ticker">${esc(c.ticker)}</span>` : "";
      const nameLine = c.name
        ? `<div class="name">${esc(c.name)}${c.ticker ? `<span class="ticker-inline">${esc(c.ticker)}</span>` : ""}</div>`
        : "";
      const metaParts = [];
      if (c.opinion) metaParts.push(esc(c.opinion).toUpperCase());
      if (c.target) metaParts.push(esc(c.target));
      const meta = metaParts.length
        ? `<div class="meta meta-${dir}">${metaParts.join(" · ")}</div>`
        : "";
      const blurb = c.company_blurb ? `<div class="blurb">${esc(c.company_blurb)}</div>` : "";
      const dateChip = `<span class="date-chip">${esc(c.date)}</span>`;
      return `<li><a class="card card-${dir}" href="${href}">`
        + `<span class="accent"></span>`
        + `<div class="card-body">`
        +   `<div class="eyebrow">${dateChip}<span class="region">${region}</span>${house}${tickerRow}</div>`
        +   nameLine
        +   `<div class="headline">${esc(c.headline)}</div>`
        +   meta
        +   blurb
        + `</div></a></li>`;
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

- [ ] **Step 3: Tests — search asset still served + result shape**

In `tests/web/test_app.py` find `test_search_page_renders` and replace body (assertions slightly stricter for redesigned markup):

```python
def test_search_page_renders(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/search")
    assert resp.status_code == 200
    assert "/cards.json" in resp.text
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.select_one("input#search-input") is not None
    assert soup.select_one("#search-results") is not None
```

Append a new test verifying the search.js card template shape:

```python
def test_search_js_renders_card_shape(nas):
    app = create_app(nas_dir=nas)
    with TestClient(app) as c:
        resp = c.get("/assets/search.js")
    assert resp.status_code == 200
    assert "card-${dir}" in resp.text
    assert ".accent" in resp.text or "class=\\\"accent\\\"" in resp.text or 'class="accent"' in resp.text
    assert "region" in resp.text
```

- [ ] **Step 4: Run search tests**

Run: `uv run pytest tests/web/test_app.py -k search -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_digest/web/templates/search.html.j2 market_digest/web/assets/search.js tests/web/test_app.py
git commit -m "feat(web): redesigned search result cards matching list style"
```

---

## Task 8: Stylesheet rewrite

**Files:**
- Modify: `market_digest/web/assets/style.css`

This task replaces the whole stylesheet in one shot. Since there's no unit test for CSS, the verification is (a) existing asset-served test still passes, (b) spot-check with rendered HTML containing all the class selectors we now rely on.

- [ ] **Step 1: Replace style.css**

Overwrite `market_digest/web/assets/style.css` with:

```css
:root {
  --bg-page: #fafafa;
  --bg-card: #ffffff;
  --bg-badge: #eeeeee;
  --fg-primary: #222;
  --fg-muted: #888;
  --fg-subtle: #999;
  --fg-eyebrow: #333;
  --border: #e5e5e5;
  --border-dashed: #e5e5e5;
  --accent-up: #1a7f1a;
  --accent-down: #c22233;
  --accent-neutral: #aaaaaa;
  --link: #0066cc;
  color-scheme: light dark;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg-page: #121212;
    --bg-card: #1b1b1b;
    --bg-badge: #2a2a2a;
    --fg-primary: #eee;
    --fg-muted: #888;
    --fg-subtle: #777;
    --fg-eyebrow: #ccc;
    --border: #2a2a2a;
    --accent-up: #4ec94e;
    --accent-down: #ef4e4e;
    --accent-neutral: #555;
    --link: #6aa6ff;
  }
}

* { box-sizing: border-box; }

html, body {
  margin: 0; padding: 0;
  background: var(--bg-page);
  color: var(--fg-primary);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI",
      "Apple SD Gothic Neo", "Malgun Gothic", Roboto, sans-serif;
}

.page {
  max-width: 640px;
  margin: 0 auto;
  padding: 0 16px 48px;
}

/* ---------- Sticky header ---------- */
.date-header {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 0;
  background: var(--bg-page);
  border-bottom: 1px solid var(--border);
  font-size: 13px; font-weight: 600;
}
.date-header .date-label { flex: 1; text-align: center; }
.date-header a, .date-header .disabled {
  color: var(--fg-primary); text-decoration: none;
  padding: 4px 8px; border-radius: 6px;
}
.date-header .disabled { color: var(--fg-muted); opacity: 0.4; }
.date-header .back { flex: 0 0 auto; color: var(--link); }
.date-header .nav-search { margin-left: auto; color: var(--link); font-weight: 500; }

/* ---------- Group heading ---------- */
section.group { margin: 18px 0; }
section.group h2.group-title {
  font: 600 11px/1 "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--fg-muted);
  margin: 16px 0 10px;
}

/* ---------- Cards ---------- */
ul.cards { list-style: none; margin: 0; padding: 0; }
ul.cards li { margin: 0 0 10px; }

a.card {
  display: flex; gap: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  color: var(--fg-primary);
  text-decoration: none;
  transition: background 120ms ease;
}
a.card:active { background: var(--border); }

a.card .accent {
  flex: 0 0 4px;
  background: var(--accent-neutral);
}
a.card.card-up .accent { background: var(--accent-up); }
a.card.card-down .accent { background: var(--accent-down); }

a.card .card-body {
  flex: 1;
  padding: 10px 12px;
  min-width: 0;
}

a.card .eyebrow,
article.detail .eyebrow {
  font: 10px/1 "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--fg-subtle);
  display: flex; gap: 6px; align-items: center;
  margin-bottom: 5px;
  flex-wrap: wrap;
}
.eyebrow .region {
  color: var(--fg-eyebrow);
  font-weight: 700;
  background: var(--bg-badge);
  padding: 1px 5px;
  border-radius: 2px;
  letter-spacing: 0.5px;
}
.eyebrow .house { color: var(--fg-eyebrow); font-weight: 600; letter-spacing: 0; }
.eyebrow .ticker { color: var(--fg-subtle); }
.eyebrow .sep { color: var(--fg-subtle); }
.eyebrow .date-chip { color: var(--fg-eyebrow); font-weight: 600; }

a.card .name {
  font: 700 17px/1.25 'Noto Serif KR', Charter, Georgia, serif;
  color: var(--fg-primary);
  margin: 2px 0 4px;
  letter-spacing: -0.2px;
}
a.card .name .ticker-inline,
article h1 .ticker-inline {
  color: var(--fg-subtle);
  font: 400 12px/1 "SF Mono", Menlo, monospace;
  margin-left: 6px;
  letter-spacing: 0.3px;
  vertical-align: middle;
}

a.card .headline {
  font-size: 13px;
  line-height: 1.5;
  color: var(--fg-primary);
}
a.card .meta,
article .meta-strip {
  font: 600 12px/1 "SF Mono", Menlo, Consolas, monospace;
  letter-spacing: 0.3px;
  margin-top: 5px;
  color: var(--fg-primary);
}
.meta-up, a.card.card-up .meta { color: var(--accent-up); }
.meta-down, a.card.card-down .meta { color: var(--accent-down); }
.meta-neutral, a.card.card-neutral .meta { color: var(--fg-primary); }

a.card .blurb,
article.detail .blurb {
  color: var(--fg-muted);
  font: italic 12px/1.5 -apple-system, "Apple SD Gothic Neo", sans-serif;
  margin-top: 6px;
  padding-top: 5px;
  border-top: 1px dashed var(--border-dashed);
}
article.detail .blurb {
  border-top: none;
  padding-top: 0;
  font-size: 13px;
  margin-bottom: 10px;
}

/* ---------- Detail page ---------- */
article.detail {
  display: flex;
  gap: 14px;
  padding: 18px 0 8px;
}
article.detail .accent {
  flex: 0 0 4px;
  background: var(--accent-neutral);
  border-radius: 2px;
}
article.detail.detail-up .accent { background: var(--accent-up); }
article.detail.detail-down .accent { background: var(--accent-down); }
article.detail .detail-body { flex: 1; min-width: 0; }

article.detail h1 {
  font: 700 26px/1.2 'Noto Serif KR', Charter, Georgia, serif;
  letter-spacing: -0.3px;
  margin: 4px 0 8px;
  color: var(--fg-primary);
}
article.detail .meta-strip {
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  margin: 4px 0 14px;
}
article.detail .meta-strip .label {
  color: var(--fg-subtle);
  font-weight: 400;
  margin-right: 4px;
  font-size: 10px;
  letter-spacing: 1px;
}

article.detail .body {
  font-size: 14px;
  line-height: 1.65;
  color: var(--fg-primary);
}
article.detail .body ul { padding-left: 20px; margin: 10px 0; }
article.detail .body li { margin: 4px 0; }
article.detail .body a { color: var(--link); }

article.detail .actions {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 8px;
}
article.detail .actions .action {
  display: block;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--fg-primary);
  text-decoration: none;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
}
article.detail .actions .action:active { background: var(--border); }
article.detail .actions .subtitle { color: var(--fg-muted); font-size: 12px; margin-top: -2px; }

article.detail .chart-embed {
  height: 360px;
  width: 100%;
}
article.detail .chart-embed .tradingview-widget-container,
article.detail .chart-embed .tradingview-widget-container__widget {
  height: 100%;
  width: 100%;
}

/* ---------- Search ---------- */
#search-input {
  width: 100%;
  font-size: 16px;
  padding: 10px 12px;
  margin: 16px 0 6px;
  background: var(--bg-card);
  color: var(--fg-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-family: inherit;
}
#search-count { color: var(--fg-muted); font-size: 13px; margin: 4px 0 12px; }

/* ---------- Misc ---------- */
p.empty { color: var(--fg-muted); text-align: center; margin: 48px 0; }
p.subtitle { color: var(--fg-muted); font-size: 13px; }

.nav-badge {
  position: fixed; top: 12px; right: 12px; z-index: 20;
  background: var(--link); color: #fff;
  width: 26px; height: 26px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
  font-family: "SF Mono", Menlo, monospace;
}
```

- [ ] **Step 2: Asset still served + spot-check selectors**

Run: `cd /home/sund4y/market-digest && uv run pytest tests/web/test_app.py::test_static_asset_served -v`
Expected: PASS.

Also a quick content check:

```bash
cd /home/sund4y/market-digest
uv run python -c "
from pathlib import Path
css = Path('market_digest/web/assets/style.css').read_text()
for sel in ['a.card.card-up .accent', 'article.detail', '.eyebrow .region',
            '.meta-down', 'ul.cards', '.nav-badge', '--accent-up']:
    assert sel in css, sel
print('css selectors ok')
"
```

Expected: `css selectors ok`.

- [ ] **Step 3: Full suite regression**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add market_digest/web/assets/style.css
git commit -m "style(web): redesigned stylesheet — accent bars, serif, monospace meta"
```

---

## Task 9: Final end-to-end check + push

**Files:**
- (none; verification only)

- [ ] **Step 1: Full test suite**

Run: `cd /home/sund4y/market-digest && uv run pytest -v`
Expected: all green.

- [ ] **Step 2: Import sanity**

Run:

```bash
uv run python -c "
from market_digest.web.app import create_app, production_app
from market_digest.web.direction import infer_direction
assert infer_direction('Buy', '10 → 20') == 'up'
print('ok')
"
```

Expected: `ok`.

- [ ] **Step 3: Local server smoke**

Run:

```bash
cd /home/sund4y/market-digest
uv run python -c "
import threading, time, urllib.request
from pathlib import Path
import uvicorn
from market_digest.web.app import create_app
app = create_app(nas_dir=Path('/mnt/nas/market-digest'))
config = uvicorn.Config(app, host='127.0.0.1', port=18099, log_level='warning')
server = uvicorn.Server(config)
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1.5)
for ep in ['/healthz', '/', '/cards.json', '/search']:
    with urllib.request.urlopen(f'http://127.0.0.1:18099{ep}') as r:
        body = r.read().decode('utf-8', errors='ignore')
        print(ep, r.status, 'emoji?' if any(c in body for c in ['🇰🇷','🇺🇸','📈','🔍']) else 'clean')
"
```

Expected: all endpoints return 200, `emoji?` prints `clean` for every one.

- [ ] **Step 4: Restart service and push**

```bash
cd /home/sund4y/market-digest
git push origin master
sudo systemctl restart market-digest-web
sleep 2
curl -s http://localhost:8086/healthz
```

Expected: `{"ok":true}` via Caddy.
