"""Static site generator for market-digest."""
from __future__ import annotations

import datetime as _dt
import json
import logging
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
