"""Stub: indicator formulas (see package docstring).

Convention: every function returns None when an input is missing or a denominator is 0.
"""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.kpi_extractor.extractor import KPISet


class Indicator(BaseModel):
    name: str
    value: float | None
    formula: str
    inputs: dict[str, str]  # kpi name -> citation ref (XBRL tag)


class AnomalyFlag(BaseModel):
    name: str
    triggered: bool
    reason: str


def growth_rate(current: float | None, prior: float | None) -> float | None:
    raise NotImplementedError


def margin(numerator: float | None, revenue: float | None) -> float | None:
    raise NotImplementedError


def leverage(total_debt: float | None, equity: float | None) -> float | None:
    raise NotImplementedError


def dso(accounts_receivable: float | None, revenue: float | None, days: int = 365) -> float | None:
    raise NotImplementedError


def altman_z(current: KPISet) -> float | None:
    """Variant (original vs. Z'' book-value) is an open decision — see docs/decisions.md."""
    raise NotImplementedError


def beneish_m(current: KPISet, prior: KPISet) -> float | None:
    raise NotImplementedError


def anomaly_flags(current: KPISet, prior: KPISet | None) -> list[AnomalyFlag]:
    raise NotImplementedError


def compute_all(current: KPISet, prior: KPISet | None) -> list[Indicator]:
    raise NotImplementedError
