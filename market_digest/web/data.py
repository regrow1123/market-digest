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
