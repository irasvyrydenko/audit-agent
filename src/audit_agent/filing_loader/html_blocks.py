"""Flatten 10-K HTML into an ordered list of text blocks and tables.

A block is the text of an innermost block-level element (p/div/li/h*). Inline tags (span,
a, ix:*) are merged into their block, so in-sentence cross-references ("see Item 1A")
never look like headings. Small tables without numbers are layout (e.g. XOM puts Item
headings in tables) and become text blocks; other tables keep their rows.
"""

from __future__ import annotations

import re
import warnings
from typing import Literal

from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning
from pydantic import BaseModel

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
LAYOUT_TABLE_MAX_ROWS = 2
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


class Block(BaseModel):
    index: int
    kind: Literal["text", "table"]
    text: str
    rows: list[list[str]] = []


def normalize(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _table_rows(table: Tag) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [normalize(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c and c not in {"$", "%", ")"}]
        if cells:
            rows.append(cells)
    return rows


def _is_layout_table(rows: list[list[str]]) -> bool:
    if len(rows) > LAYOUT_TABLE_MAX_ROWS:
        return False
    cells = [c for row in rows for c in row]
    return not any(_NUMBER.fullmatch(c.strip("()$%")) for c in cells)


RawBlock = tuple[str, str, list[list[str]]]


def _flush(buffer: list[str], out: list[RawBlock]) -> None:
    text = normalize(" ".join(buffer))
    if text:
        out.append(("text", text, []))
    buffer.clear()


def _add_table(table: Tag, out: list[RawBlock]) -> None:
    rows = _table_rows(table)
    if not rows:
        return
    if _is_layout_table(rows):
        out.append(("text", normalize(" ".join(c for r in rows for c in r)), []))
    else:
        out.append(("table", normalize(" ".join(" ".join(r) for r in rows)), rows))


def _walk(element: Tag, out: list[RawBlock]) -> None:
    """Depth-first; inline content between block children is kept as its own block."""
    buffer: list[str] = []
    for child in element.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            buffer.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        is_block = child.name in BLOCK_TAGS or child.find(BLOCK_TAGS) is not None
        if not is_block:
            buffer.append(child.get_text(" "))
            continue
        _flush(buffer, out)
        if child.name == "table":
            _add_table(child, out)
        elif child.find(BLOCK_TAGS) is None:
            _flush([child.get_text(" ")], out)
        else:
            _walk(child, out)
    _flush(buffer, out)


def parse_blocks(html: str | bytes) -> list[Block]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(re.compile(r"^ix:header$")):
        tag.decompose()  # hidden inline-XBRL metadata
    raw: list[RawBlock] = []
    _walk(soup.body or soup, raw)
    return [
        Block(index=i, kind=kind, text=text, rows=rows)  # type: ignore[arg-type]
        for i, (kind, text, rows) in enumerate(raw)
    ]
