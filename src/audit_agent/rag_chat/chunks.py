"""Filing paragraphs -> retrieval chunks (pure, no I/O).

One chunk = one text paragraph, so the paragraph id is the citation. The nearest preceding
heading of the same Item is kept as context and prepended to the embedded text.
"""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.filing_loader.loader import Filing, Section

ITEM_TITLES = {
    "1A": "Risk Factors",
    "7": "Management's Discussion and Analysis (MD&A)",
    "8": "Financial Statements and Notes",
}


class Chunk(BaseModel):
    id: str  # "<TICKER>_<FY>:<paragraph id>", unique across filings
    ticker: str
    fiscal_year: int
    accession: str
    item: str
    paragraph_id: str  # e.g. "item_7:p12" — the citation ref
    heading: str | None = None
    text: str

    @property
    def embed_text(self) -> str:
        return f"{self.heading}\n{self.text}" if self.heading else self.text


def filing_key(ticker: str, fiscal_year: int) -> str:
    return f"{ticker.upper()}_{fiscal_year}"


def section_chunks(filing: Filing, section: Section, min_words: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading: str | None = None
    key = filing_key(filing.ticker, filing.fiscal_year)
    for p in section.paragraphs:
        if p.kind == "heading":
            heading = p.text
            continue
        if len(p.text.split()) < min_words:
            continue
        chunks.append(
            Chunk(
                id=f"{key}:{p.id}",
                ticker=filing.ticker.upper(),
                fiscal_year=filing.fiscal_year,
                accession=filing.ref.accession,
                item=section.item,
                paragraph_id=p.id,
                heading=heading,
                text=p.text,
            )
        )
    return chunks


def build_chunks(filing: Filing, items: list[str], min_words: int) -> list[Chunk]:
    """Text paragraphs of the given Items with at least `min_words` words."""
    return [
        c
        for item in items
        if item in filing.sections
        for c in section_chunks(filing, filing.sections[item], min_words)
    ]
