"""Indicator formulas and anomaly flags. Pure functions: no I/O, settings are passed in.

Convention: every formula returns None when an input is missing or a denominator is 0.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation
from audit_agent.common.config import IndicatorSettings
from audit_agent.kpi_extractor.extractor import KPISet, KPIValue

Unit = Literal["ratio", "days", "score"]
Status = Literal["ok", "missing", "not_applicable"]
Zone = Literal["distress", "grey", "safe"]
PRIOR = "@prior"

# Altman Z'' (Altman 1995, non-manufacturers / emerging markets), book-value variant.
Z2_WEIGHTS = (6.56, 3.26, 6.72, 1.05)


class Indicator(BaseModel):
    name: str
    value: float | None
    unit: Unit
    formula: str
    status: Status
    period_end: date
    inputs: dict[str, float | None]  # "kpi" or "kpi@prior" -> value
    citations: list[Citation] = []  # XBRL facts behind the inputs (empty unless status ok)

    @property
    def citation(self) -> Citation:
        return Citation(source_type="computed", ref=f"indicator:{self.name}")


class AnomalyFlag(BaseModel):
    name: str
    triggered: bool
    reason: str
    citations: list[Citation]


# --- formulas ------------------------------------------------------------------------------


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def growth_rate(current: float | None, prior: float | None) -> float | None:
    """(current - prior) / |prior|; |prior| keeps the sign meaningful for negative bases."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def margin(numerator: float | None, revenue: float | None) -> float | None:
    return safe_div(numerator, revenue)


def gross_margin(revenue: float | None, cost_of_revenue: float | None) -> float | None:
    if revenue is None or cost_of_revenue is None:
        return None
    return safe_div(revenue - cost_of_revenue, revenue)


def leverage(total_debt: float | None, equity: float | None) -> float | None:
    """Debt / equity; None for non-positive equity (ratio is meaningless, flagged separately)."""
    if equity is None or equity <= 0:
        return None
    return safe_div(total_debt, equity)


def dso(accounts_receivable: float | None, revenue: float | None, days: int = 365) -> float | None:
    """Days sales outstanding on year-end receivables."""
    ratio = safe_div(accounts_receivable, revenue)
    return None if ratio is None else ratio * days


def cash_conversion(operating_cash_flow: float | None, net_income: float | None) -> float | None:
    """OCF / net income; None when net income <= 0 (ratio flips meaning)."""
    if net_income is None or net_income <= 0:
        return None
    return safe_div(operating_cash_flow, net_income)


def altman_z2(
    current_assets: float | None,
    current_liabilities: float | None,
    retained_earnings: float | None,
    ebit: float | None,
    total_assets: float | None,
    equity: float | None,
    total_liabilities: float | None,
) -> float | None:
    """Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4 (book equity, no market data needed).

    X1 = working capital / TA, X2 = retained earnings / TA, X3 = EBIT / TA,
    X4 = book equity / total liabilities.
    """
    if current_assets is None or current_liabilities is None:
        return None
    xs = (
        safe_div(current_assets - current_liabilities, total_assets),
        safe_div(retained_earnings, total_assets),
        safe_div(ebit, total_assets),
        safe_div(equity, total_liabilities),
    )
    if any(x is None for x in xs):
        return None
    return sum(w * x for w, x in zip(Z2_WEIGHTS, xs, strict=True))  # type: ignore[operator]


def altman_zone(z: float | None, distress_below: float, safe_above: float) -> Zone | None:
    if z is None:
        return None
    if z < distress_below:
        return "distress"
    return "safe" if z > safe_above else "grey"


def beneish_m(current: KPISet, prior: KPISet) -> float | None:
    """Deferred until after the demo (needs more KPIs: SG&A, depreciation, PP&E history)."""
    raise NotImplementedError


# --- indicator specs -----------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    name: str
    unit: Unit
    formula: str
    inputs: tuple[str, ...]  # "kpi" or "kpi@prior", passed positionally to compute
    compute: Callable[..., float | None]


def _growth(kpi: str) -> Spec:
    return Spec(
        f"{kpi}_growth",
        "ratio",
        f"({kpi} - {kpi}{PRIOR}) / |{kpi}{PRIOR}|",
        (kpi, kpi + PRIOR),
        growth_rate,
    )


def build_specs(settings: IndicatorSettings) -> tuple[Spec, ...]:
    """All indicators in report order."""
    return (
        _growth("revenue"),
        _growth("net_income"),
        _growth("operating_cash_flow"),
        Spec(
            "gross_margin",
            "ratio",
            "(revenue - cost_of_revenue) / revenue",
            ("revenue", "cost_of_revenue"),
            gross_margin,
        ),
        Spec(
            "operating_margin",
            "ratio",
            "operating_income / revenue",
            ("operating_income", "revenue"),
            margin,
        ),
        Spec("net_margin", "ratio", "net_income / revenue", ("net_income", "revenue"), margin),
        Spec(
            "current_ratio",
            "ratio",
            "current_assets / current_liabilities",
            ("current_assets", "current_liabilities"),
            safe_div,
        ),
        Spec(
            "debt_to_equity",
            "ratio",
            "total_debt / stockholders_equity",
            ("total_debt", "stockholders_equity"),
            leverage,
        ),
        Spec(
            "liabilities_to_assets",
            "ratio",
            "total_liabilities / total_assets",
            ("total_liabilities", "total_assets"),
            safe_div,
        ),
        Spec(
            "cash_conversion",
            "ratio",
            "operating_cash_flow / net_income",
            ("operating_cash_flow", "net_income"),
            cash_conversion,
        ),
        Spec(
            "dso",
            "days",
            f"accounts_receivable / revenue * {settings.days_in_year}",
            ("accounts_receivable", "revenue"),
            partial(dso, days=settings.days_in_year),
        ),
        _growth("accounts_receivable"),
        Spec(
            "altman_z2",
            "score",
            "6.56*(current_assets - current_liabilities)/total_assets"
            " + 3.26*retained_earnings/total_assets + 6.72*ebit/total_assets"
            " + 1.05*stockholders_equity/total_liabilities",
            (
                "current_assets",
                "current_liabilities",
                "retained_earnings",
                "ebit",
                "total_assets",
                "stockholders_equity",
                "total_liabilities",
            ),
            altman_z2,
        ),
    )


def _input_kpi(name: str, current: KPISet, prior: KPISet | None) -> KPIValue | None:
    if name.endswith(PRIOR):
        return prior.values.get(name.removesuffix(PRIOR)) if prior else None
    return current.values.get(name)


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: dict[tuple[str, str | None], Citation] = {}
    for c in citations:
        seen.setdefault((c.ref, c.accession), c)
    return list(seen.values())


def compute_indicator(
    spec: Spec, current: KPISet, prior: KPISet | None, *, not_applicable: bool = False
) -> Indicator:
    kpis = {name: _input_kpi(name, current, prior) for name in spec.inputs}
    inputs = {name: (k.value if k else None) for name, k in kpis.items()}
    value = None if not_applicable else spec.compute(*inputs.values())
    status: Status = (
        "not_applicable" if not_applicable else ("ok" if value is not None else "missing")
    )
    citations = [c for k in kpis.values() if k for c in k.citations] if value is not None else []
    return Indicator(
        name=spec.name,
        value=value,
        unit=spec.unit,
        formula=spec.formula,
        status=status,
        period_end=current.period_end,
        inputs=inputs,
        citations=_dedupe(citations),
    )


def compute_all(
    current: KPISet,
    prior: KPISet | None,
    settings: IndicatorSettings,
    *,
    is_bank: bool = False,
) -> list[Indicator]:
    na = set(settings.not_applicable_for_banks) if is_bank else set()
    return [
        compute_indicator(spec, current, prior, not_applicable=spec.name in na)
        for spec in build_specs(settings)
    ]


# --- anomaly flags -------------------------------------------------------------------------


def _flag(name: str, triggered: bool, reason: str, sources: list[Indicator]) -> AnomalyFlag:
    citations = [c for ind in sources for c in [ind.citation, *ind.citations]]
    return AnomalyFlag(name=name, triggered=triggered, reason=reason, citations=_dedupe(citations))


def _threshold_flag(
    name: str,
    ind: Indicator | None,
    threshold: float,
    *,
    below: bool,
) -> AnomalyFlag | None:
    if ind is None or ind.value is None:
        return None
    triggered = ind.value < threshold if below else ind.value > threshold
    word = "below" if below else "above"
    reason = f"{ind.name} = {ind.value:.3f} ({'' if triggered else 'not '}{word} {threshold})"
    return _flag(name, triggered, reason, [ind])


def _receivables_flag(by_name: dict[str, Indicator], gap: float) -> AnomalyFlag | None:
    ar, rev = by_name.get("accounts_receivable_growth"), by_name.get("revenue_growth")
    if ar is None or rev is None or ar.value is None or rev.value is None:
        return None
    diff = ar.value - rev.value
    reason = f"receivables growth {ar.value:.1%} vs revenue growth {rev.value:.1%} (gap {diff:.1%})"
    return _flag("receivables_outpace_revenue", diff > gap, reason, [ar, rev])


def _sign_flag(name: str, kpi: KPIValue | None) -> AnomalyFlag | None:
    if kpi is None or kpi.value is None:
        return None
    triggered = kpi.value < 0
    reason = f"{kpi.name} {'is negative' if triggered else 'is not negative'}"
    return AnomalyFlag(name=name, triggered=triggered, reason=reason, citations=kpi.citations)


def anomaly_flags(
    current: KPISet,
    indicators: list[Indicator],
    settings: IndicatorSettings,
    *,
    is_bank: bool = False,
) -> list[AnomalyFlag]:
    """Rule-based red flags; a flag is omitted when its inputs are missing / not applicable."""
    by_name = {i.name: i for i in indicators}
    thr = settings.anomaly
    candidates = [
        _threshold_flag(
            "revenue_decline", by_name.get("revenue_growth"), thr.revenue_decline_below, below=True
        ),
        _threshold_flag(
            "weak_cash_conversion",
            by_name.get("cash_conversion"),
            thr.cash_conversion_below,
            below=True,
        ),
        _threshold_flag(
            "high_leverage", by_name.get("debt_to_equity"), thr.debt_to_equity_above, below=False
        ),
        _threshold_flag(
            "low_liquidity", by_name.get("current_ratio"), thr.current_ratio_below, below=True
        ),
        _threshold_flag(
            "altman_distress",
            by_name.get("altman_z2"),
            settings.altman_z2_zones.distress_below,
            below=True,
        ),
        _receivables_flag(by_name, thr.receivables_growth_gap_above),
        _sign_flag("negative_equity", current.values.get("stockholders_equity")),
        _sign_flag("negative_operating_cash_flow", current.values.get("operating_cash_flow")),
    ]
    na = set(settings.not_applicable_for_banks) if is_bank else set()
    return [f for f in candidates if f is not None and f.name not in na]
