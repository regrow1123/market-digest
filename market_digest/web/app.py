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

    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    from market_digest.web.data import build_cards_index, list_dates

    PLACEHOLDER = (
        "<!doctype html><meta charset=utf-8><title>마켓 다이제스트</title>"
        "<p style='font:16px sans-serif;text-align:center;padding:48px'>아직 리포트가 없습니다.</p>"
    )

    @app.get("/")
    async def home() -> HTMLResponse | RedirectResponse:
        if app.state.nas_dir is None:
            return HTMLResponse(PLACEHOLDER)
        dates = list_dates(app.state.nas_dir)
        if not dates:
            return HTMLResponse(PLACEHOLDER)
        return RedirectResponse(url=f"/{dates[-1]}", status_code=307)

    @app.get("/cards.json")
    async def cards_json() -> JSONResponse:
        if app.state.nas_dir is None:
            return JSONResponse([])
        return JSONResponse(build_cards_index(app.state.nas_dir))

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app
