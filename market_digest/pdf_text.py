"""PDF → text extraction for Korean market reports using PyMuPDF."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)


def pdf_to_text(pdf_path: Path, max_chars: int = 30_000) -> str:
    """Extract text from a PDF. Returns empty string on failure."""
    pdf_path = Path(pdf_path)
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        log.warning("pymupdf failed on %s: %s", pdf_path.name, exc)
        return ""
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"
    return text
