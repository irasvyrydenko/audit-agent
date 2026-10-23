"""Stub: data types and entry points for filing_loader (see package docstring)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Paragraph(BaseModel):
    id: str  # stable, e.g. "item_7:p12" — used as citation ref
    item: str  # "1A" | "7" | "8"
    index: int
    text: str


class Table(BaseModel):
    id: str  # e.g. "item_8:t3"
    item: str
    caption: str | None = None
    rows: list[list[str]]


class Section(BaseModel):
    item: str
    title: str
    paragraphs: list[Paragraph]


class FilingRef(BaseModel):
    cik: str
    accession: str
    form: str
    filing_date: date
    report_date: date
    primary_document: str


class Filing(BaseModel):
    ticker: str
    fiscal_year: int
    ref: FilingRef
    sections: dict[str, Section]
    tables: list[Table]


def find_10k(cik: str, fiscal_year: int) -> FilingRef:
    """Pick the 10-K (not 10-K/A unless no original) whose report period matches fiscal_year."""
    raise NotImplementedError


def split_items(html: str, items: list[str]) -> dict[str, Section]:
    """Segment 10-K HTML into the requested Items with numbered paragraphs."""
    raise NotImplementedError


def extract_tables(html: str) -> list[Table]:
    raise NotImplementedError


def load_filing(ticker: str, fiscal_year: int) -> Filing:
    """End-to-end: CIK lookup -> find_10k -> download (cached) -> split -> Filing."""
    raise NotImplementedError
