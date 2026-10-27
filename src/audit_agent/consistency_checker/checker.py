"""Claim verification against XBRL-backed KPIs (deterministic) — D-016.

A claim is structured (metric, scope, fiscal year, kind, direction, value in base units).
Verdicts:
- unverifiable: segment-level claim, unknown metric, year outside {FY, FY-1}, missing data;
- supported / contradicted: claimed value vs value computed from KPIs, with a tolerance that
  respects how the number was written ("$58.5 billion" is exact to +-$0.05B).
"""

from __future__ import annotations

import random
import re
from typing import Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation
from audit_agent.indicator_engine.indicators import gross_margin, growth_rate, margin
from audit_agent.kpi_extractor.extractor import KPISet

Verdict = Literal["supported", "contradicted", "unverifiable"]
Kind = Literal["level", "change_pct", "change_abs", "change_pp", "direction"]
Direction = Literal["up", "down", "flat"]

# Ratio metrics computed from KPIs of one year: name -> (kpis used, formula).
RATIO_METRICS: dict[str, tuple[str, ...]] = {
    "gross_margin": ("revenue", "cost_of_revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
    "pretax_margin": ("pretax_income", "revenue"),
}
# Money metrics = KPIs a company-level MD&A claim can be checked against.
MONEY_METRICS = (
    "revenue",
    "cost_of_revenue",
    "operating_income",
    "pretax_income",
    "net_income",
    "net_income_incl_nci",
    "operating_cash_flow",
    "cash",
    "total_debt",
    "total_assets",
    "stockholders_equity",
)
SUPPORTED_METRICS = (*MONEY_METRICS, *RATIO_METRICS)

# Default half rounding unit when the claim's wording is unknown.
DEFAULT_HALF_UNIT = {"change_pct": 0.005, "change_pp": 0.0005}
_UNITS = (
    (re.compile(r"basis points?|bps?\b", re.I), 1e-4),
    (re.compile(r"percentage points?", re.I), 0.01),
    (re.compile(r"%|percent", re.I), 0.01),
    (re.compile(r"\bbillion|\bbn\b|\d\s*B\b", re.I), 1e9),
    (re.compile(r"\bmillion|\bmn\b|\d\s*M\b", re.I), 1e6),
    (re.compile(r"\bthousand", re.I), 1e3),
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.(\d+))?")


class Claim(BaseModel):
    id: str
    paragraph_id: str
    text: str  # quote from the paragraph
    metric: str | None  # one of SUPPORTED_METRICS, else unverifiable
    scope: Literal["company", "segment"] = "company"
    fiscal_year: int | None = None  # year the claim is about; None = filing year
    kind: Kind = "direction"
    direction: Direction | None = None
    value: float | None = None  # base units: USD, fraction (0.18), fraction points (0.0027)
    as_written: str | None = None  # e.g. "$58.5 billion", "18%", "27 basis points"


class CheckResult(BaseModel):
    claim: Claim
    verdict: Verdict
    evidence: list[Citation]
    rationale: str
    computed: float | None = None


def half_unit(as_written: str | None) -> float | None:
    """Half of the last written digit in base units: '$58.5 billion' -> 0.05e9."""
    if not as_written:
        return None
    number = _NUMBER.search(as_written)
    if not number:
        return None
    decimals = len(number.group(1) or "")
    for pattern, scale in _UNITS:
        if pattern.search(as_written):
            return 0.5 * 10**-decimals * scale
    return None


def metric_value(kpis: KPISet, metric: str) -> float | None:
    if metric in RATIO_METRICS:
        a, b = (kpis.get(name) for name in RATIO_METRICS[metric])
        return gross_margin(a, b) if metric == "gross_margin" else margin(a, b)
    return kpis.get(metric)


def metric_citations(kpis: KPISet | None, metric: str) -> list[Citation]:
    if kpis is None:
        return []
    names = RATIO_METRICS.get(metric, (metric,))
    return [c for n in names if (k := kpis.values.get(n)) for c in k.citations]


def _signed(claim: Claim) -> float | None:
    """Claimed change with sign from the direction ('down 17%' -> -0.17)."""
    if claim.value is None:
        return None
    if claim.kind == "level":
        return claim.value
    return -abs(claim.value) if claim.direction == "down" else claim.value


def _computed(claim: Claim, cur: float | None, base: float | None) -> float | None:
    if claim.kind == "level":
        return cur
    if cur is None or base is None:
        return None
    if claim.kind == "change_pct":
        return growth_rate(cur, base)
    if claim.kind in ("change_abs", "change_pp"):
        return cur - base
    # direction: relative change for money, absolute change for ratios
    return cur - base if claim.metric in RATIO_METRICS else growth_rate(cur, base)


def _direction_of(change: float, flat: float) -> Direction:
    if abs(change) < flat:
        return "flat"
    return "up" if change > 0 else "down"


def _tolerance(claim: Claim, computed: float, rel_tol: float) -> float:
    """Half of the last written digit; relative tolerance only when the wording is unknown."""
    written = half_unit(claim.as_written)
    if written is not None:
        return written * (1 + 1e-9)
    return max(rel_tol * abs(computed), DEFAULT_HALF_UNIT.get(claim.kind, 0.0), 1e-12)


def _result(
    claim: Claim,
    verdict: Verdict,
    rationale: str,
    evidence: list[Citation],
    computed: float | None = None,
) -> CheckResult:
    return CheckResult(
        claim=claim, verdict=verdict, evidence=evidence, rationale=rationale, computed=computed
    )


def verify_claim(
    claim: Claim,
    current: KPISet,
    prior: KPISet | None,
    tolerance: float,
    flat_threshold: float = 0.01,
) -> CheckResult:
    """Deterministic verdict for one structured claim."""
    paragraph = Citation(
        source_type="section", ref=claim.paragraph_id, accession=current.accession, quote=claim.text
    )
    if claim.scope == "segment":
        return _result(
            claim,
            "unverifiable",
            "segment / product level claim; only company totals are checked",
            [paragraph],
        )
    if claim.metric not in SUPPORTED_METRICS:
        return _result(
            claim, "unverifiable", f"metric {claim.metric!r} is not checked", [paragraph]
        )
    year = claim.fiscal_year or current.fiscal_year
    if year == current.fiscal_year:
        cur_set, base_set = current, prior
    elif year == current.fiscal_year - 1 and claim.kind == "level":
        cur_set, base_set = prior, None
    else:
        return _result(
            claim,
            "unverifiable",
            f"claim about FY{year} needs data beyond FY{current.fiscal_year - 1}",
            [paragraph],
        )
    if cur_set is None:
        return _result(claim, "unverifiable", "no prior-year KPIs", [paragraph])

    metric = claim.metric
    cur = metric_value(cur_set, metric)
    base = metric_value(base_set, metric) if base_set else None
    computed = _computed(claim, cur, base)
    evidence = [paragraph, *metric_citations(cur_set, metric), *metric_citations(base_set, metric)]
    if computed is None:
        return _result(
            claim, "unverifiable", f"{metric} not available for the needed years", evidence
        )

    if claim.kind == "direction" or claim.value is None:
        if claim.direction is None:
            return _result(
                claim,
                "unverifiable",
                "claim states neither a number nor a direction",
                evidence,
                computed,
            )
        flat = flat_threshold / 10 if metric in RATIO_METRICS else flat_threshold
        actual = _direction_of(computed, flat)
        verdict: Verdict = "supported" if actual == claim.direction else "contradicted"
        return _result(
            claim,
            verdict,
            f"claimed {claim.direction}, computed {actual} ({computed:+.4f})",
            evidence,
            computed,
        )

    claimed = _signed(claim)
    assert claimed is not None
    tol = _tolerance(claim, computed, tolerance)
    diff = abs(claimed - computed)
    verdict = "supported" if diff <= tol else "contradicted"
    rationale = (
        f"claimed {claimed:,.6g}, computed {computed:,.6g} "
        f"(|diff| {diff:,.4g} vs tolerance {tol:,.4g})"
    )
    return _result(claim, verdict, rationale, evidence, computed)


def perturb_claim(claim: Claim, seed: int) -> Claim:
    """Eval helper: flip the direction or shift the number so the claim should be contradicted."""
    rng = random.Random(f"{seed}-{claim.id}")
    flip = {"up": "down", "down": "up", "flat": "up"}
    can_flip = claim.direction is not None and claim.kind != "level"
    if claim.value is None or (can_flip and rng.random() < 0.5):
        new_direction = flip[claim.direction] if claim.direction else "up"
        return claim.model_copy(update={"id": f"{claim.id}-flip", "direction": new_direction})
    factor = rng.choice([0.5, 1.5])  # +-50%: beyond rounding tolerance even for "$0.3 billion"
    return claim.model_copy(update={"id": f"{claim.id}-shift", "value": claim.value * factor})
