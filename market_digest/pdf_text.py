"""PDF → text extraction for Korean reports.

Primary: pdfminer.six (handles most Korean-font-embedded PDFs well).
Fallback: pypdf (faster, weaker on complex layouts / CJK).
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def pdf_to_text(pdf_path: Path, max_chars: int = 30_000) -> str:
    pdf_path = Path(pdf_path)
    text = ""
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(str(pdf_path)) or ""
    except Exception as exc:
        log.warning("pdfminer failed on %s: %s; trying pypdf", pdf_path.name, exc)
    if not text.strip():
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as exc:
            log.warning("pypdf failed on %s: %s", pdf_path.name, exc)
            return ""
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text
