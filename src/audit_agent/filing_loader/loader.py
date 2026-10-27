"""filing_loader entry points: pick the 10-K, download, split into Items, cache as JSON."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from audit_agent.common.config import load_settings, resolve_path
from audit_agent.common.edgar_client import EdgarClient, EdgarError
from audit_agent.filing_loader.html_blocks import Block, parse_blocks
from audit_agent.filing_loader.segmenter import Span, boilerplate, is_noise, segment

SUBHEADING_MAX_CHARS = 120


class Paragraph(BaseModel):
    id: str  # stable, e.g. "item_7:p12" — used as citation ref
    item: str  # "1A" | "7" | "8"
    index: int
    kind: Literal["text", "heading"] = "text"
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
    resolved_pointer: bool = False  # True if found by title (Item 7/8 only referenced elsewhere)


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


def fiscal_year_of(report_date: date) -> int:
    """Fiscal year = calendar year of the period end (D-009)."""
    return report_date.year


def find_10k(filings: Iterable[dict[str, Any]], cik: str, fiscal_year: int) -> FilingRef:
    """Pick the original 10-K for fiscal_year; fall back to a 10-K/A only if none exists."""
    matches = [
        f
        for f in filings
        if f.get("form") in ("10-K", "10-K/A")
        and f.get("reportDate")
        and fiscal_year_of(date.fromisoformat(f["reportDate"])) == fiscal_year
    ]
    if not matches:
        raise EdgarError(f"No 10-K with fiscal year {fiscal_year} for CIK {cik}")
    originals = [f for f in matches if f["form"] == "10-K"]
    best = max(originals or matches, key=lambda f: f["filingDate"])
    return FilingRef(
        cik=cik,
        accession=best["accessionNumber"],
        form=best["form"],
        filing_date=date.fromisoformat(best["filingDate"]),
        report_date=date.fromisoformat(best["reportDate"]),
        primary_document=best["primaryDocument"],
    )


def _paragraph_kind(text: str) -> Literal["text", "heading"]:
    short = len(text) <= SUBHEADING_MAX_CHARS
    return "heading" if short and not text.rstrip().endswith((".", ":", ";")) else "text"


def _build_section(
    span: Span, blocks: list[Block], repeated: set[str]
) -> tuple[Section, list[Table]]:
    paragraphs: list[Paragraph] = []
    tables: list[Table] = []
    last_text: str | None = None
    for block in blocks[span.start + 1 : span.end]:
        if is_noise(block, repeated):
            continue
        if block.kind == "table":
            if len(block.rows) < 2:
                continue  # page numbers / footers laid out as one-row tables
            caption = last_text if last_text and len(last_text) <= SUBHEADING_MAX_CHARS else None
            tid = f"item_{span.item}:t{len(tables) + 1}"
            tables.append(Table(id=tid, item=span.item, caption=caption, rows=block.rows))
            continue
        pid = f"item_{span.item}:p{len(paragraphs) + 1}"
        paragraphs.append(
            Paragraph(
                id=pid,
                item=span.item,
                index=len(paragraphs) + 1,
                kind=_paragraph_kind(block.text),
                text=block.text,
            )
        )
        last_text = block.text
    section = Section(
        item=span.item,
        title=span.title,
        paragraphs=paragraphs,
        resolved_pointer=span.resolved_pointer,
    )
    return section, tables


def split_filing(html: str | bytes, items: list[str]) -> tuple[dict[str, Section], list[Table]]:
    """Segment 10-K HTML into the requested Items (paragraphs + tables)."""
    blocks = parse_blocks(html)
    repeated = boilerplate(blocks)
    sections: dict[str, Section] = {}
    tables: list[Table] = []
    for span in segment(blocks):
        if span.item in items:
            section, section_tables = _build_section(span, blocks, repeated)
            sections[span.item] = section
            tables.extend(section_tables)
    return sections, tables


def _cache_path(ticker: str, fiscal_year: int) -> Path:
    processed = resolve_path(load_settings().paths.processed)
    return processed / "filings" / f"{ticker.upper()}_{fiscal_year}.json"


def load_filing(
    ticker: str, fiscal_year: int, client: EdgarClient | None = None, refresh: bool = False
) -> Filing:
    """End-to-end: CIK -> find_10k -> download (cached) -> split -> Filing (cached JSON)."""
    cache = _cache_path(ticker, fiscal_year)
    if cache.exists() and not refresh:
        return Filing.model_validate_json(cache.read_text(encoding="utf-8"))
    client = client or EdgarClient()
    cik = client.resolve_cik(ticker)
    ref = find_10k(client.iter_filings(cik), cik, fiscal_year)
    path = client.download_filing(cik, ref.accession, ref.primary_document)
    sections, tables = split_filing(path.read_bytes(), load_settings().filing.items)
    filing = Filing(
        ticker=ticker.upper(), fiscal_year=fiscal_year, ref=ref, sections=sections, tables=tables
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(filing.model_dump_json(indent=1), encoding="utf-8")
    return filing
