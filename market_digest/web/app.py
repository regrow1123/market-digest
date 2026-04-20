"""FastAPI application for market-digest."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt

log = logging.getLogger(__name__)


def _build_env() -> Environment:
    env = Environment(
        loader=PackageLoader("market_digest.web", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["group_flag"] = lambda region: {"kr": "🇰🇷", "us": "🇺🇸"}.get(region, "")
    return env


def create_app(nas_dir: Path | None) -> FastAPI:
    """Build a FastAPI app bound to `nas_dir` (None = test stub)."""
    app = FastAPI(title="market-digest", docs_url=None, redoc_url=None)
    app.state.nas_dir = nas_dir
    app.state.env = _build_env()
    app.state.md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app
