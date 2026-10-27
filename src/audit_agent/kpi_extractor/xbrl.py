"""Pick facts from an XBRL companyfacts JSON for one 10-K and one period (D-011).

Rules (see .claude/skills/edgar-fetch):
- only facts whose `accn` is the chosen 10-K's accession (values as reported in that filing);
- `end` must equal the period end; durations must span 350–380 days, instants have no `start`;
- duplicates of the same period: latest `filed` wins (they normally carry the same value).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel

PeriodType = Literal["duration", "instant"]

MIN_YEAR_DAYS = 350
MAX_YEAR_DAYS = 380

_TERM = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<optional>\?)?$")


class XBRLFact(BaseModel):
    taxonomy: str
    tag: str
    value: float
    start: date | None
    end: date
    accession: str
    filed: date | None = None

    @property
    def ref(self) -> str:
        """Citation ref, e.g. 'us-gaap:NetIncomeLoss@2024-09-28'."""
        return f"{self.taxonomy}:{self.tag}@{self.end.isoformat()}"


@dataclass(frozen=True)
class Term:
    name: str
    sign: int  # +1 or -1
    optional: bool

    @property
    def is_kpi_ref(self) -> bool:
        """snake_case names refer to earlier KPIs, CamelCase names to XBRL tags."""
        return self.name[0].islower()


def parse_expression(expr: str) -> list[Term]:
    """'A? + B - C' -> [Term(A, +1, optional), Term(B, +1), Term(C, -1)]."""
    tokens = expr.split()
    if not tokens or len(tokens) % 2 == 0:
        raise ValueError(f"malformed KPI expression: {expr!r}")
    terms: list[Term] = []
    sign = 1
    for i, token in enumerate(tokens):
        if i % 2 == 1:
            if token not in "+-" or len(token) != 1:
                raise ValueError(f"expected + or - in {expr!r}, got {token!r}")
            sign = 1 if token == "+" else -1
            continue
        match = _TERM.match(token)
        if not match:
            raise ValueError(f"bad term {token!r} in {expr!r}")
        terms.append(Term(match["name"], sign, bool(match["optional"])))
    return terms


def tag_rows(companyfacts: dict[str, Any], taxonomy: str, tag: str, unit: str) -> list[dict]:
    """Raw fact rows for one tag/unit; [] when the company never used the tag."""
    concept = companyfacts.get("facts", {}).get(taxonomy, {}).get(tag, {})
    return concept.get("units", {}).get(unit, [])


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _matches_period(row: dict, period_end: date, period_type: PeriodType) -> bool:
    if _parse_date(row.get("end")) != period_end:
        return False
    start = _parse_date(row.get("start"))
    if period_type == "instant":
        return start is None
    return start is not None and MIN_YEAR_DAYS <= (period_end - start).days <= MAX_YEAR_DAYS


def select_fact(
    rows: list[dict],
    *,
    taxonomy: str,
    tag: str,
    accession: str,
    period_end: date,
    period_type: PeriodType,
) -> XBRLFact | None:
    """The fact for this filing and period, or None."""
    hits = [
        r
        for r in rows
        if r.get("accn") == accession and _matches_period(r, period_end, period_type)
    ]
    if not hits:
        return None
    best = max(hits, key=lambda r: r.get("filed") or "")
    return XBRLFact(
        taxonomy=taxonomy,
        tag=tag,
        value=float(best["val"]),
        start=_parse_date(best.get("start")),
        end=period_end,
        accession=accession,
        filed=_parse_date(best.get("filed")),
    )


def _iter_rows(companyfacts: dict[str, Any], unit: str) -> list[dict]:
    rows: list[dict] = []
    for concepts in companyfacts.get("facts", {}).values():
        for concept in concepts.values():
            rows.extend(concept.get("units", {}).get(unit, []))
    return rows


def prior_period_end(
    companyfacts: dict[str, Any], accession: str, period_end: date, unit: str = "USD"
) -> date | None:
    """Prior fiscal year end = (start of the current fiscal year) - 1 day.

    The start is the most common `start` among this filing's full-year facts ending on
    `period_end`, so 52/53-week years (AAPL, WMT) are handled without date arithmetic.
    """
    starts = Counter(
        row["start"]
        for row in _iter_rows(companyfacts, unit)
        if row.get("accn") == accession and _matches_period(row, period_end, "duration")
    )
    if not starts:
        return None
    start = date.fromisoformat(starts.most_common(1)[0][0])
    return start - timedelta(days=1)
