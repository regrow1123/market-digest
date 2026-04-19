"""Pydantic models for the daily digest JSON."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Region = Literal["kr", "us"]
Category = Literal["company", "industry", "8k", "rating"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Item(BaseModel):
    id: str
    headline: str
    body_md: str
    house: str | None = None
    ticker: str | None = None
    name: str | None = None
    opinion: str | None = None
    target: str | None = None
    url: str | None = None
    company_blurb: str | None = None


class Group(BaseModel):
    region: Region
    category: Category
    title: str
    items: list[Item] = Field(default_factory=list)


class Digest(BaseModel):
    date: str
    groups: list[Group] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError("date must match YYYY-MM-DD")
        return v


class CardIndexEntry(BaseModel):
    """Flat record used in cards.json (no body_md)."""

    date: str
    id: str
    region: Region
    category: Category
    headline: str
    house: str | None = None
    ticker: str | None = None
    name: str | None = None
    opinion: str | None = None
    target: str | None = None
