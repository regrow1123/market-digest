"""Invoke Claude Code headless to read inbox/{date}/ and produce summaries.

The summarization rules live in the project's CLAUDE.md (auto-loaded when
`claude` is run with CWD=project root). We only pass a short instruction
here.
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
    telegram_markdown: str
    detail_path: Path
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
    """Run claude -p and return the parsed result.

    Claude writes the detail markdown to NAS and returns only the Telegram
    card list in stdout `result`.
    """
    yyyy, mm, _ = date.split("-")
    detail_path = nas_report_dir / yyyy / mm / f"{date}.md"
    detail_path.parent.mkdir(parents=True, exist_ok=True)

    instruction = (
        f"오늘 날짜는 {date}이다. "
        f"inbox/{date}/ 디렉토리의 모든 .txt 파일을 읽고, "
        f"CLAUDE.md 에 정의된 규칙에 따라 상세본을 {detail_path} 에 Write 하라. "
        f"최종 응답(stdout)에는 텔레그램으로 보낼 MarkdownV2 카드 리스트만 출력하라."
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

    # stream-json and json formats differ slightly; json has `result`
    result_text = payload.get("result") or payload.get("response") or ""
    usage = payload.get("usage") or payload.get("total_usage") or {}
    session_id = payload.get("session_id", "")

    # Trim any prefatory chatter; the telegram card must start with 📊
    marker = "📊"
    idx = result_text.find(marker)
    if idx > 0:
        result_text = result_text[idx:]
    result_text = result_text.strip()

    if not result_text:
        log.warning("claude returned empty result; payload keys=%s", list(payload.keys()))

    # Cache the telegram payload so a send failure doesn't require
    # re-running the expensive claude -p call.
    cache_path = project_dir / "logs" / f"{date}_telegram.txt"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(result_text, encoding="utf-8")

    return SummarizeResult(
        telegram_markdown=result_text,
        detail_path=detail_path,
        usage=usage,
        session_id=session_id,
    )
