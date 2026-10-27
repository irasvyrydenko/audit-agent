"""Find Item boundaries in a flattened 10-K (see docs/decisions.md D-010).

1. Heading candidates: short text blocks starting with "Item <n>".
2. For each Item in canonical order pick the candidate after the previous Item that is
   followed by the longest run before a *later* Item's candidate (skips the table of
   contents and stray references).
3. "Pointer" sections (JPM, XOM: "Reference is made to ... in the Financial Section") are
   resolved by title: MD&A heading -> auditor's report / financial statements.
"""

from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel

from audit_agent.filing_loader.html_blocks import Block

ITEM_ORDER = [
    "1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8",
    "9", "9A", "9B", "9C", "10", "11", "12", "13", "14", "15", "16",
]  # fmt: skip
HEADING_MAX_CHARS = 200
POINTER_MAX_WORDS = 250

_ITEM_HEADING = re.compile(r"^item\s*(\d{1,2}[a-c]?)\b\s*[.:\-–—]?\s*(.*)$", re.IGNORECASE)
_POINTER = re.compile(
    r"reference is made|appears on pages?|incorporated (herein )?by reference|"
    r"is included (on|in) pages?|financial section",
    re.IGNORECASE,
)
_MDNA_TITLE = re.compile(
    r"^management[’']?s discussion and analysis"
    r"( of (financial condition and results of operations|results of operations and financial "
    r"condition))?\.?$",
    re.IGNORECASE,
)
_FS_START = re.compile(
    r"^(report of independent registered public accounting firm|"
    r"management[’']?s report on internal control over financial reporting|"
    r"consolidated (balance sheets?|statements? of (income|earnings|operations)))\.?$",
    re.IGNORECASE,
)
_FS_END = re.compile(
    r"^(supplement(al|ary) (information|data)|glossary of terms|index to exhibits|exhibit index|"
    r"signatures|part iv\b)",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(r"^(page\s*)?\d{1,3}$|^table of contents$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")


class Span(BaseModel):
    item: str
    title: str
    start: int  # index of the heading block
    end: int  # exclusive
    resolved_pointer: bool = False


def heading_candidates(blocks: list[Block]) -> list[tuple[int, str, str]]:
    """(block index, item id, title) for blocks that look like Item headings."""
    found = []
    for block in blocks:
        if block.kind != "text" or len(block.text) > HEADING_MAX_CHARS:
            continue
        match = _ITEM_HEADING.match(block.text)
        if match and match.group(1).upper() in ITEM_ORDER:
            found.append((block.index, match.group(1).upper(), match.group(2)))
    return found


def _gap_to_later_item(pos: int, item: str, candidates: list[tuple[int, str, str]], n: int) -> int:
    rank = ITEM_ORDER.index(item)
    later = [i for i, it, _ in candidates if i > pos and ITEM_ORDER.index(it) > rank]
    return (min(later) if later else n) - pos


def choose_headings(candidates: list[tuple[int, str, str]], n_blocks: int) -> list[Span]:
    chosen: list[tuple[int, str, str]] = []
    last = -1
    for item in ITEM_ORDER:
        options = [c for c in candidates if c[1] == item and c[0] > last]
        if not options:
            continue
        best = max(options, key=lambda c: _gap_to_later_item(c[0], item, candidates, n_blocks))
        chosen.append(best)
        last = best[0]
    spans = []
    for k, (pos, item, title) in enumerate(chosen):
        end = chosen[k + 1][0] if k + 1 < len(chosen) else n_blocks
        spans.append(Span(item=item, title=title, start=pos, end=end))
    return spans


def is_pointer(span: Span, blocks: list[Block]) -> bool:
    body = " ".join(b.text for b in blocks[span.start + 1 : span.end])
    return len(body.split()) <= POINTER_MAX_WORDS and bool(_POINTER.search(body))


def _first_match(blocks: list[Block], pattern: re.Pattern[str], start: int) -> int | None:
    for block in blocks[start:]:
        is_short_text = block.kind == "text" and len(block.text) <= HEADING_MAX_CHARS
        if is_short_text and pattern.match(block.text):
            return block.index
    return None


def resolve_pointers(spans: list[Span], blocks: list[Block]) -> list[Span]:
    """Replace pointer Items 7 / 8 with the real MD&A / financial statements by title."""
    by_item = {s.item: s for s in spans}
    item7, item8 = by_item.get("7"), by_item.get("8")
    if item7 is None or not is_pointer(item7, blocks):
        return spans
    mdna = _first_match(blocks, _MDNA_TITLE, item7.end)
    fs = _first_match(blocks, _FS_START, mdna + 1) if mdna is not None else None
    if mdna is None or fs is None:
        return spans
    fs_end = _first_match(blocks, _FS_END, fs + 1) or len(blocks)
    fixed = {"7": Span(item="7", title=item7.title, start=mdna, end=fs, resolved_pointer=True)}
    if item8 is not None and is_pointer(item8, blocks):
        fixed["8"] = Span(item="8", title=item8.title, start=fs, end=fs_end, resolved_pointer=True)
    return [fixed.get(s.item, s) for s in spans]


def _shape(text: str) -> str:
    """Text with digits masked, so 'Form 10-K | 26' and 'Form 10-K | 27' count as one."""
    return _DIGITS.sub("#", text)


def boilerplate(blocks: list[Block], min_repeats: int = 3, max_chars: int = 150) -> set[str]:
    """Running page headers/footers: short texts repeated (up to digits) across the document."""
    counts = Counter(
        _shape(b.text) for b in blocks if b.kind == "text" and len(b.text) <= max_chars
    )
    return {shape for shape, n in counts.items() if n >= min_repeats}


def is_noise(block: Block, repeated: set[str]) -> bool:
    if block.kind != "text":
        return False
    return _shape(block.text) in repeated or bool(_PAGE_NUMBER.match(block.text))


def segment(blocks: list[Block]) -> list[Span]:
    spans = choose_headings(heading_candidates(blocks), len(blocks))
    return resolve_pointers(spans, blocks)
