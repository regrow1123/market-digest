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

from market_digest.fetchers import fmp, hankyung, sec_edgar
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
    """Return True if JSON parses as a valid Digest.

    On failure: dump a copy to logs/ and quarantine the NAS file by
    renaming it to `{date}.json.invalid` so the next `collect_digests`
    run does not re-log the same error.
    """
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
        quarantine = json_path.with_suffix(".json.invalid")
        try:
            json_path.rename(quarantine)
            log.error("quarantined bad digest to %s", quarantine)
        except OSError as exc:
            log.error("failed to quarantine %s: %s", json_path, exc)
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
                watchlist=cfg["watchlist"],
                form_types=cfg["sec_edgar"]["form_types"],
                max_items=cfg["sec_edgar"]["max_items"],
                user_agent=ua,
                cache_dir=PROJECT_DIR / ".cache",
            )
            log.info("sec_edgar: %d filings saved", n)
            total += n
        except Exception as exc:
            log.exception("sec_edgar fetcher failed: %s", exc)

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
