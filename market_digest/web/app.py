"""FastAPI application for market-digest."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from pydantic import BaseModel

log = logging.getLogger(__name__)


class ResearchRequest(BaseModel):
    ticker: str
    date: str


def _build_env() -> Environment:
    env = Environment(
        loader=PackageLoader("market_digest.web", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["group_flag"] = lambda region: {"kr": "🇰🇷", "us": "🇺🇸"}.get(region, "")
    return env


def create_app(nas_dir: Path | None, research_runner=None) -> FastAPI:
    """Build a FastAPI app bound to `nas_dir` (None = test stub)."""
    app = FastAPI(title="market-digest", docs_url=None, redoc_url=None)
    app.state.nas_dir = nas_dir
    app.state.env = _build_env()
    app.state.md = MarkdownIt("commonmark", {"breaks": True, "linkify": True})

    from market_digest.web.jobs import JobTracker

    app.state.tracker = JobTracker()
    app.state.research_runner = research_runner

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

    import datetime as _dt

    from fastapi import HTTPException, Path as PathParam

    from market_digest.web.data import load_digest, prev_next

    _WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
    _DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

    def _weekday(date: str) -> str:
        y, m, d = (int(x) for x in date.split("-"))
        return _WEEKDAYS[_dt.date(y, m, d).weekday()]

    from fastapi.responses import FileResponse
    from importlib import resources

    @app.get("/search")
    async def search_page() -> HTMLResponse:
        html = app.state.env.get_template("search.html.j2").render(asset_prefix="/")
        return HTMLResponse(html)

    @app.get("/assets/{name}")
    async def asset(name: str):
        if "/" in name or ".." in name:
            raise HTTPException(status_code=404)
        try:
            ref = resources.files("market_digest.web").joinpath("assets", name)
        except (ModuleNotFoundError, FileNotFoundError):
            raise HTTPException(status_code=404)
        path = Path(str(ref))
        if not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    from fastapi import Body
    from market_digest.models import Digest as _Digest
    from market_digest.web.data import load_digest as _load_digest_api
    from market_digest.web.data import research_md_path as _research_md_path_api

    def _find_item_for_ticker(digest: _Digest, ticker: str):
        for g in digest.groups:
            for i in g.items:
                if (i.ticker or "").upper() == ticker.upper():
                    return i
        return None

    def _default_runner(tracker, job_id, ticker, date_str, out_path):
        """Production runner: runs claude via subprocess in an executor thread."""
        from market_digest.research import run_research
        import yaml

        cfg_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        tracker.mark_running(job_id)
        try:
            run_research(
                ticker=ticker,
                date_str=date_str,
                out_path=out_path,
                claude_cli=cfg["claude"]["cli_path"],
                model=cfg["claude"]["research_model"],
                context=None,
                dry_run=False,
            )
        except Exception as exc:
            tracker.mark_failed(job_id, str(exc))
            return
        digest = _load_digest_api(app.state.nas_dir, date_str)
        item_id = ""
        if digest:
            it = _find_item_for_ticker(digest, ticker)
            if it is not None:
                item_id = it.id
        tracker.mark_done(job_id, f"/{date_str}/{item_id}/research")

    @app.post("/api/research")
    async def post_research(body: ResearchRequest = Body(...)) -> dict:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = _load_digest_api(app.state.nas_dir, body.date)
        if digest is None:
            raise HTTPException(status_code=400, detail="digest missing")
        item = _find_item_for_ticker(digest, body.ticker)
        if item is None:
            raise HTTPException(status_code=400, detail="ticker not in digest")

        md_path = _research_md_path_api(app.state.nas_dir, body.ticker, body.date)
        if md_path is not None and md_path.exists():
            return {"job_id": "", "status": "done",
                    "output_url": f"/{body.date}/{item.id}/research"}

        existing = app.state.tracker.find_active(body.ticker.upper(), body.date)
        if existing is not None:
            return {"job_id": existing.job_id, "status": existing.status}

        job = app.state.tracker.create(body.ticker.upper(), body.date)
        runner = app.state.research_runner or _default_runner

        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            runner,
            app.state.tracker,
            job.job_id,
            body.ticker.upper(),
            body.date,
            md_path,
        )
        return {"job_id": job.job_id, "status": "pending"}

    @app.get("/api/research/status/{job_id}")
    async def research_status(job_id: str) -> dict:
        job = app.state.tracker.get(job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return {
            "job_id": job.job_id,
            "ticker": job.ticker,
            "date": job.date,
            "status": job.status,
            "output_url": job.output_url,
            "error": job.error,
        }

    @app.get("/api/research/active")
    async def research_active() -> list:
        return [
            {"job_id": j.job_id, "ticker": j.ticker, "date": j.date,
             "status": j.status}
            for j in app.state.tracker.active()
        ]

    @app.get("/{date}")
    async def card_page(date: str = PathParam(..., pattern=_DATE_PATTERN)) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        dates = list_dates(app.state.nas_dir)
        prev_d, next_d = prev_next(dates, date)
        html = app.state.env.get_template("card_page.html.j2").render(
            digest=digest,
            prev_date=prev_d,
            next_date=next_d,
            weekday=_weekday(date),
            asset_prefix="/",
        )
        return HTMLResponse(html)

    from market_digest.web.data import find_item, flat_ids, research_md_path

    @app.get("/{date}/{item_id}")
    async def detail_page(
        date: str = PathParam(..., pattern=_DATE_PATTERN),
        item_id: str = PathParam(...),
    ) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        found = find_item(digest, item_id)
        if found is None:
            raise HTTPException(status_code=404)
        gi, ii, item = found
        ids = flat_ids(digest)
        pos = ids.index(item_id)
        prev_id = ids[pos - 1] if pos > 0 else None
        next_id = ids[pos + 1] if pos < len(ids) - 1 else None
        md_path = research_md_path(app.state.nas_dir, item.ticker, date)
        has_research = md_path is not None and md_path.exists()
        chart_link: dict | None = None
        if item.ticker:
            t = item.ticker.strip()
            if len(t) == 6 and t.isdigit():
                chart_link = {
                    "url": f"https://finance.naver.com/item/main.naver?code={t}",
                    "label": "📈 네이버 금융에서 차트 보기",
                }
            else:
                chart_link = {
                    "url": f"https://m.stock.naver.com/worldstock/stock/{t}/total",
                    "label": "📈 네이버 해외주식에서 차트 보기",
                }
        body_html = app.state.md.render(item.body_md)
        html = app.state.env.get_template("detail_page.html.j2").render(
            digest=digest,
            item=item,
            prev_id=prev_id,
            next_id=next_id,
            body_html=body_html,
            has_research=has_research,
            chart_link=chart_link,
            asset_prefix="/",
        )
        return HTMLResponse(html)

    @app.get("/{date}/{item_id}/research")
    async def research_page(
        date: str = PathParam(..., pattern=_DATE_PATTERN),
        item_id: str = PathParam(...),
    ) -> HTMLResponse:
        if app.state.nas_dir is None:
            raise HTTPException(status_code=404)
        digest = load_digest(app.state.nas_dir, date)
        if digest is None:
            raise HTTPException(status_code=404)
        found = find_item(digest, item_id)
        if found is None:
            raise HTTPException(status_code=404)
        _, _, item = found
        md_path = research_md_path(app.state.nas_dir, item.ticker, date)
        if md_path is None or not md_path.exists():
            raise HTTPException(status_code=404)
        body_html = app.state.md.render(md_path.read_text(encoding="utf-8"))
        html = app.state.env.get_template("research_page.html.j2").render(
            digest=digest, item=item, body_html=body_html, asset_prefix="/",
        )
        return HTMLResponse(html)

    return app


def production_app() -> FastAPI:
    """uvicorn entry point: binds nas_dir from config.yaml."""
    import yaml

    cfg_path = Path(__file__).resolve().parent.parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return create_app(nas_dir=Path(cfg["nas_report_dir"]))
