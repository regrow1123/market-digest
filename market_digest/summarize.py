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
