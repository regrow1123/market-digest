from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from market_digest.research import build_output_path, main, run_research


def test_build_output_path(tmp_path):
    p = build_output_path(root=tmp_path, ticker="AAPL", date_str="2026-04-20")
    assert p == tmp_path / "research" / "AAPL-2026-04-20.md"


def test_run_research_dry_run_writes_placeholder(tmp_path):
    out = tmp_path / "research" / "AAPL-2026-04-20.md"
    run_research(
        ticker="AAPL",
        date_str="2026-04-20",
        out_path=out,
        claude_cli="/bin/claude",
        model="m",
        context=None,
        dry_run=True,
    )
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "AAPL" in text and "2026-04-20" in text


def test_run_research_invokes_claude_with_web_tools(tmp_path):
    out = tmp_path / "research" / "NVDA-2026-04-20.md"
    out.parent.mkdir(parents=True)
    out.write_text("placeholder before call", encoding="utf-8")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        class R:
            stdout = ""
            stderr = ""
            returncode = 0
        return R()

    with patch("market_digest.research.subprocess.run", side_effect=fake_run):
        run_research(
            ticker="NVDA",
            date_str="2026-04-20",
            out_path=out,
            claude_cli="/bin/claude",
            model="claude-opus-4-7",
            context=None,
            dry_run=False,
        )

    cmd = captured["cmd"]
    assert cmd[0] == "/bin/claude"
    assert "--allowed-tools" in cmd
    idx = cmd.index("--allowed-tools")
    tools = cmd[idx + 1]
    assert "WebSearch" in tools
    assert "WebFetch" in tools
    assert "Write" in tools
    assert str(out) in " ".join(cmd)


def test_main_exit_zero_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("market_digest.research.run_research") as rr:
        rc = main([
            "AAPL",
            "--date", "2026-04-20",
            "--root", str(tmp_path),
            "--claude-cli", "/bin/claude",
            "--model", "m",
            "--dry-run",
        ])
    assert rc == 0
    rr.assert_called_once()
