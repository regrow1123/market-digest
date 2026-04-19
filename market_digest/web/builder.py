"""Static site generator for market-digest."""
from __future__ import annotations

import datetime as _dt
import json
import json as _json
import logging
import shutil
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from pydantic import ValidationError

from market_digest.models import CardIndexEntry, Digest

log = logging.getLogger(__name__)

_env = Environment(
    loader=PackageLoader("market_digest.web", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

_md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})


def _flag(region: str) -> str:
    return {"kr": "🇰🇷", "us": "🇺🇸"}.get(region, "")


_env.globals["group_flag"] = _flag


def _weekday(date: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return _WEEKDAYS[_dt.date(y, m, d).weekday()]


def collect_digests(nas_dir: Path) -> list[Digest]:
    """Load every `{YYYY}/{MM}/{DATE}.json` under nas_dir, sorted ascending.

    Individual file failures (unreadable / invalid JSON / schema mismatch)
    are logged and skipped — the rest of the site still builds.
    """
    digests: list[Digest] = []
    for path in sorted(nas_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.json")):
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


def render_card_page(digest: Digest, *, prev_date: str | None, next_date: str | None) -> str:
    template = _env.get_template("card_page.html.j2")
    return template.render(
        digest=digest,
        prev_date=prev_date,
        next_date=next_date,
        weekday=_weekday(digest.date),
        asset_prefix="",
    )


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


def render_research_page(*, digest: Digest, item, body_html: str) -> str:
    template = _env.get_template("research_page.html.j2")
    return template.render(
        digest=digest,
        item=item,
        body_html=body_html,
        asset_prefix="../",
    )


def render_search_page() -> str:
    template = _env.get_template("search.html.j2")
    return template.render(asset_prefix="")


def _flat_ids_for_day(digest: Digest) -> list[str]:
    return [item.id for group in digest.groups for item in group.items]


def _research_md_path(nas_dir: Path, ticker: str | None, date_str: str) -> Path | None:
    if not ticker:
        return None
    return nas_dir / "research" / f"{ticker.upper()}-{date_str}.md"


def _research_md_exists(nas_dir: Path, ticker: str | None, date_str: str) -> bool:
    p = _research_md_path(nas_dir, ticker, date_str)
    return p is not None and p.exists()


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
                has_research = _research_md_exists(nas_dir, item.ticker, digest.date)
                detail_html = render_detail_page(
                    digest=digest,
                    group_index=gi,
                    item_index=ii,
                    flat_ids=flat_ids,
                    has_research=has_research,
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
