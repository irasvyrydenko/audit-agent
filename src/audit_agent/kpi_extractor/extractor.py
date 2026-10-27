"""KPI extraction: XBRL companyfacts (ground truth) for the current and prior fiscal year.

`extract_with_llm` / `reconcile` are not implemented yet (deferred until after the demo).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation
from audit_agent.common.config import KPIDefinition, load_settings
from audit_agent.common.edgar_client import EdgarClient
from audit_agent.common.llm_client import LLMClient
from audit_agent.filing_loader.loader import Filing, FilingRef
from audit_agent.kpi_extractor.xbrl import (
    Term,
    XBRLFact,
    parse_expression,
    prior_period_end,
    select_fact,
    tag_rows,
)


class KPIValue(BaseModel):
    name: str
    value: float | None  # None = not reported / not applicable
    unit: str
    period_end: date
    expression: str | None = None  # the candidate expression that resolved
    facts: list[XBRLFact] = []
    source: Literal["xbrl", "llm"] = "xbrl"
    citations: list[Citation] = []  # one per XBRL fact; empty only when value is None


class KPISet(BaseModel):
    ticker: str
    fiscal_year: int
    period_end: date
    accession: str
    values: dict[str, KPIValue]

    def get(self, name: str) -> float | None:
        kpi = self.values.get(name)
        return kpi.value if kpi else None


def _citation(fact: XBRLFact) -> Citation:
    return Citation(source_type="xbrl", ref=fact.ref, accession=fact.accession)


def _term_facts(
    term: Term,
    companyfacts: dict[str, Any],
    kpi: KPIDefinition,
    accession: str,
    period_end: date,
    resolved: Mapping[str, KPIValue],
) -> tuple[float, list[XBRLFact]] | None:
    """Value and supporting facts of one term, or None if absent."""
    if term.is_kpi_ref:
        ref = resolved.get(term.name)
        if ref is None or ref.value is None:
            return None
        return ref.value, ref.facts
    rows = tag_rows(companyfacts, kpi.taxonomy, term.name, kpi.unit)
    fact = select_fact(
        rows,
        taxonomy=kpi.taxonomy,
        tag=term.name,
        accession=accession,
        period_end=period_end,
        period_type=kpi.period_type,
    )
    return (fact.value, [fact]) if fact else None


def evaluate_expression(
    expr: str,
    companyfacts: dict[str, Any],
    kpi: KPIDefinition,
    accession: str,
    period_end: date,
    resolved: Mapping[str, KPIValue],
) -> tuple[float, list[XBRLFact]] | None:
    """Sum the terms; None if a required term is absent or no term is present."""
    total = 0.0
    facts: list[XBRLFact] = []
    for term in parse_expression(expr):
        found = _term_facts(term, companyfacts, kpi, accession, period_end, resolved)
        if found is None:
            if not term.optional:
                return None
            continue
        total += term.sign * found[0]
        facts.extend(found[1])
    return (total, facts) if facts else None


def extract_kpi(
    kpi: KPIDefinition,
    companyfacts: dict[str, Any],
    accession: str,
    period_end: date,
    resolved: Mapping[str, KPIValue],
) -> KPIValue:
    """First candidate expression that resolves wins; otherwise value=None."""
    for expr in kpi.tags:
        found = evaluate_expression(expr, companyfacts, kpi, accession, period_end, resolved)
        if found is not None:
            value, facts = found
            return KPIValue(
                name=kpi.name,
                value=value,
                unit=kpi.unit,
                period_end=period_end,
                expression=expr,
                facts=facts,
                citations=[_citation(f) for f in facts],
            )
    return KPIValue(name=kpi.name, value=None, unit=kpi.unit, period_end=period_end)


def extract_from_xbrl(
    companyfacts: dict[str, Any],
    *,
    ticker: str,
    fiscal_year: int,
    accession: str,
    period_end: date,
    kpis: list[KPIDefinition],
) -> KPISet:
    """All KPIs for one filing and period. KPIs are resolved in config order."""
    values: dict[str, KPIValue] = {}
    for kpi in kpis:
        values[kpi.name] = extract_kpi(kpi, companyfacts, accession, period_end, values)
    return KPISet(
        ticker=ticker.upper(),
        fiscal_year=fiscal_year,
        period_end=period_end,
        accession=accession,
        values=values,
    )


def extract_years(
    companyfacts: dict[str, Any],
    ref: FilingRef,
    ticker: str,
    fiscal_year: int,
    kpis: list[KPIDefinition],
) -> tuple[KPISet, KPISet | None]:
    """Current year and the prior-year comparatives, both as reported in the same 10-K."""
    current = extract_from_xbrl(
        companyfacts,
        ticker=ticker,
        fiscal_year=fiscal_year,
        accession=ref.accession,
        period_end=ref.report_date,
        kpis=kpis,
    )
    prior_end = prior_period_end(companyfacts, ref.accession, ref.report_date)
    if prior_end is None:
        return current, None
    prior = extract_from_xbrl(
        companyfacts,
        ticker=ticker,
        fiscal_year=fiscal_year - 1,
        accession=ref.accession,
        period_end=prior_end,
        kpis=kpis,
    )
    return current, prior


def load_kpis(
    ticker: str, fiscal_year: int, ref: FilingRef, client: EdgarClient | None = None
) -> tuple[KPISet, KPISet | None]:
    """Fetch companyfacts (cached) and extract current + prior year KPIs."""
    client = client or EdgarClient()
    companyfacts = client.get_companyfacts(ref.cik)
    return extract_years(companyfacts, ref, ticker, fiscal_year, load_settings().kpis)


def extract_with_llm(filing: Filing, kpis: list[KPIDefinition], client: LLMClient) -> KPISet:
    """Ask the LLM to read Item 8 tables; output must be JSON matching KPISet."""
    raise NotImplementedError


def reconcile(xbrl: KPISet, llm: KPISet, rel_tol: float) -> KPISet:
    """Prefer XBRL; flag disagreements beyond rel_tol for review."""
    raise NotImplementedError
