"""Hankyung Consensus (consensus.hankyung.com) fetcher.

Crawls the daily list page, downloads attached PDF reports, and saves
each report to inbox/{date}/hankyung_{report_idx}.txt with YAML front matter.
Runs sequentially with a polite sleep between PDF downloads.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from market_digest.pdf_text import pdf_to_text

log = logging.getLogger(__name__)

BASE = "https://consensus.hankyung.com"
LIST_URL = BASE + "/?sdate={date}&edate={date}&pagenum={pagenum}"
PDF_URL = BASE + "/analysis/downpdf?report_idx={idx}"


@dataclass
class HankyungReport:
    date: str
    category: str
    title: str
    summary: str
    author: str
    firm: str
    report_idx: str
    url: str


def parse_list(html: str) -> list[HankyungReport]:
    """Parse the consensus list HTML. Pure function — unit testable on fixture."""
    soup = BeautifulSoup(html, "lxml")
    reports: list[HankyungReport] = []
    table = soup.find("table")
    if table is None:
        return reports
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 5:
            continue
        date = tds[0].get_text(strip=True)
        category = tds[1].get_text(strip=True)
        title_td = tds[2]
        a = title_td.find("a")
        if a is None or "report_idx=" not in a.get("href", ""):
            continue
        title = a.get_text(strip=True)
        href = a["href"]
        report_idx = href.split("report_idx=", 1)[1].split("&", 1)[0]
        # Summary lives in a layer popup inside the same td
        bullets = [li.get_text(strip=True) for li in title_td.select(".layerPop li")]
        summary = "\n".join(b for b in bullets if b)
        author = tds[3].get_text(strip=True)
        firm = tds[4].get_text(strip=True)
        reports.append(
            HankyungReport(
                date=date,
                category=category,
                title=title,
                summary=summary,
                author=author,
                firm=firm,
                report_idx=report_idx,
                url=BASE + href,
            )
        )
    return reports


def fetch_list(date: str, pagenum: int, user_agent: str) -> list[HankyungReport]:
    url = LIST_URL.format(date=date, pagenum=pagenum)
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return parse_list(resp.text)


def download_pdf(report_idx: str, out_path: Path, user_agent: str) -> Path:
    url = PDF_URL.format(idx=report_idx)
    with requests.get(url, headers={"User-Agent": user_agent}, timeout=60, stream=True) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
    return out_path


def _yaml_front_matter(report: HankyungReport) -> str:
    meta = asdict(report)
    lines = ["---"]
    for k, v in meta.items():
        # Escape quotes by switching to single quote if the value contains double quotes
        s = str(v).replace("\n", " ").strip()
        lines.append(f'{k}: "{s}"')
    lines.append('source: "hankyung"')
    lines.append("---")
    return "\n".join(lines)


def fetch_and_save(
    date: str,
    inbox_dir: Path,
    user_agent: str,
    request_interval_sec: float,
    max_reports: int,
    pagenum: int = 50,
) -> int:
    """Fetch the list and save each report as a .txt in inbox_dir.

    Returns the number of reports saved. Re-running the same day skips files
    that already exist.
    """
    inbox_dir.mkdir(parents=True, exist_ok=True)
    reports = fetch_list(date, pagenum=pagenum, user_agent=user_agent)[:max_reports]
    log.info("hankyung: list fetched, %d reports", len(reports))
    saved = 0
    tmp_pdf = inbox_dir / ".tmp.pdf"
    for i, rep in enumerate(reports):
        out_txt = inbox_dir / f"hankyung_{rep.report_idx}.txt"
        if out_txt.exists():
            log.debug("hankyung: %s already saved, skipping", rep.report_idx)
            continue
        try:
            download_pdf(rep.report_idx, tmp_pdf, user_agent=user_agent)
            body = pdf_to_text(tmp_pdf)
        except Exception as exc:
            log.warning("hankyung: pdf failed %s: %s", rep.report_idx, exc)
            body = "(PDF 추출 실패)"
        content = _yaml_front_matter(rep) + "\n\n" + body.strip() + "\n"
        out_txt.write_text(content, encoding="utf-8")
        saved += 1
        if i < len(reports) - 1:
            time.sleep(request_interval_sec)
    if tmp_pdf.exists():
        tmp_pdf.unlink()
    return saved
