"""Static site generator for market-digest."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from market_digest.models import CardIndexEntry, Digest

log = logging.getLogger(__name__)


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
