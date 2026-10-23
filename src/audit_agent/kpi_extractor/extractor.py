"""Stub: data types and entry points for kpi_extractor (see package docstring)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation
from audit_agent.common.config import KPIDefinition
from audit_agent.common.llm_client import LLMClient
from audit_agent.filing_loader.loader import Filing


class KPIValue(BaseModel):
    name: str
    value: float | None  # None = not reported / not applicable
    unit: str
    period_end: date | None
    xbrl_tag: str | None
    source: Literal["xbrl", "llm"]
    citation: Citation


class KPISet(BaseModel):
    ticker: str
    fiscal_year: int
    values: dict[str, KPIValue]


def extract_from_xbrl(
    companyfacts: dict[str, Any], fiscal_year: int, kpis: list[KPIDefinition]
) -> KPISet:
    """Select 10-K, full-year (duration ~365d) or year-end (instant) facts per KPI."""
    raise NotImplementedError


def extract_with_llm(filing: Filing, kpis: list[KPIDefinition], client: LLMClient) -> KPISet:
    """Ask the LLM to read Item 8 tables; output must be JSON matching KPISet."""
    raise NotImplementedError


def reconcile(xbrl: KPISet, llm: KPISet, rel_tol: float) -> KPISet:
    """Prefer XBRL; flag disagreements beyond rel_tol for review."""
    raise NotImplementedError
