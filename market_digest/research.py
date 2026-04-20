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
import re
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
        "-p", build_prompt(ticker, date_str, out_path, context),
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
