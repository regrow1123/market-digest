"""market-digest orchestrator.

Runs fetchers, calls `claude -p` for summarization, sends Telegram card list,
and writes a detailed digest to NAS.

Usage:
    python -m market_digest.run                # today (KST)
    python -m market_digest.run --date 2026-04-17
    python -m market_digest.run --dry-run      # skip Telegram; write detail to ./out/
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import zoneinfo
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from market_digest.fetchers import hankyung, sec_edgar, yfinance_recs
from market_digest.summarize import summarize
from market_digest.telegram import TelegramConfig, send

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


def run(date: str, dry_run: bool) -> int:
    log = setup_logging(date)
    load_dotenv(PROJECT_DIR / ".env")
    cfg = load_config()

    inbox_dir = PROJECT_DIR / "inbox" / date
    inbox_dir.mkdir(parents=True, exist_ok=True)

    nas_dir = Path(cfg["nas_report_dir"]) if not dry_run else PROJECT_DIR / "out"

    total = 0

    # 1. Hankyung Consensus
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

    # 2. SEC EDGAR
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

    # 3. yfinance analyst changes
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

    # 4. Summarize with Claude Code headless
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
    log.info(
        "summarize: detail=%s usage=%s session=%s",
        result.detail_path, result.usage, result.session_id,
    )

    # 5. Telegram delivery
    if not result.telegram_markdown:
        log.warning("claude produced empty telegram payload; skipping send")
        return 0
    if dry_run:
        log.info("--dry-run: would send %d chars to Telegram", len(result.telegram_markdown))
        print("---- TELEGRAM PREVIEW ----")
        print(result.telegram_markdown)
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing; skipping send")
        return 1
    send(TelegramConfig(bot_token=token, chat_id=chat_id), result.telegram_markdown)
    log.info("telegram: sent")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="market-digest runner")
    p.add_argument("--date", help="YYYY-MM-DD (default: today in KST)")
    p.add_argument("--dry-run", action="store_true", help="skip Telegram; write detail to ./out/")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    date = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    return run(date=date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
