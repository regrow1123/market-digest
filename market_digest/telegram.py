"""Telegram Bot API sender — HTTP sendMessage, MarkdownV2 aware, 4096-char splitter."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4000  # 4096 minus safety margin for MarkdownV2 overhead


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


def _split_for_telegram(text: str, max_len: int = MAX_LEN) -> list[str]:
    """Split preserving line breaks; never split mid-line."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        line_len = len(line) + 1  # for the \n
        if size + line_len > max_len and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += line_len
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def send(cfg: TelegramConfig, text: str, parse_mode: str | None = None) -> None:
    """Send a message; split into multiple messages if over the Telegram limit.

    Default is plain text (parse_mode=None) — safest for Korean reports with
    unpredictable punctuation. Emojis + line breaks carry the structure.
    """
    url = API_URL.format(token=cfg.bot_token)
    for i, chunk in enumerate(_split_for_telegram(text)):
        payload = {
            "chat_id": cfg.chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        resp = requests.post(url, data=payload, timeout=30)
        if not resp.ok:
            log.error("telegram: send failed: %s %s", resp.status_code, resp.text)
            resp.raise_for_status()
        if i < len(_split_for_telegram(text)) - 1:
            time.sleep(0.5)  # Telegram rate-limit courtesy
