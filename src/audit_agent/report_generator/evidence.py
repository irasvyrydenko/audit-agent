"""Evidence items: short factual sentences built by code from KPIs, indicators, flags and risk
predictions. Each carries its citations. They are the "Details" part of the report and the
only material the LLM summary may use (D-014).
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from audit_agent.common.citations import Citation
from audit_agent.filing_loader.loader import Filing
from audit_agent.indicator_engine.indicators import AnomalyFlag, Indicator, altman_zone
from audit_agent.kpi_extractor.extractor import KPISet
from audit_agent.risk_detector.labels import RiskPrediction

KEY_KPIS = (
    ("revenue", "Revenue"),
    ("net_income", "Net income"),
    ("operating_cash_flow", "Operating cash flow"),
    ("cash", "Cash and cash equivalents"),
    ("total_debt", "Total debt"),
    ("total_assets", "Total assets"),
    ("stockholders_equity", "Stockholders' equity"),
)
SECTIONS = {
    "profitability": ("gross_margin", "operating_margin", "net_margin", "cash_conversion"),
    "liquidity_leverage": ("current_ratio", "debt_to_equity", "liabilities_to_assets", "dso"),
}
LABELS = {
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "cash_conversion": "Cash conversion (operating cash flow / net income)",
    "current_ratio": "Current ratio",
    "debt_to_equity": "Debt to equity",
    "liabilities_to_assets": "Liabilities to assets",
    "dso": "Days sales outstanding",
}
PERCENT = {"gross_margin", "operating_margin", "net_margin"}
QUOTE_WORDS = 25
MAX_RISK_EXAMPLES = 3


class Evidence(BaseModel):
    id: str  # "E1", "E2", ... (stable for one report)
    section: str
    text: str
    citations: list[Citation] = Field(min_length=1)


def money(value: float) -> str:
    """$391.04B / $812.50M / -$1.20B."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.2f}B"
    return f"{sign}${v / 1e6:,.2f}M"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def signed_pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def format_indicator(ind: Indicator) -> str:
    assert ind.value is not None
    if ind.name in PERCENT:
        return pct(ind.value)
    if ind.unit == "days":
        return f"{ind.value:.1f} days"
    return f"{ind.value:.2f}"


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: dict[tuple[str, str | None], Citation] = {}
    for c in citations:
        seen.setdefault((c.ref, c.accession), c)
    return list(seen.values())


def _indicator_cites(ind: Indicator) -> list[Citation]:
    return [ind.citation, *ind.citations]


def kpi_evidence(
    current: KPISet, prior: KPISet | None, indicators: dict[str, Indicator]
) -> list[tuple[str, str, list[Citation]]]:
    items = []
    fy = current.fiscal_year
    for name, label in KEY_KPIS:
        kpi = current.values.get(name)
        if kpi is None or kpi.value is None:
            continue
        text = f"{label}: {money(kpi.value)} in FY{fy}"
        cites = list(kpi.citations)
        prev = prior.values.get(name) if prior else None
        if prev is not None and prev.value is not None:
            text += f" vs {money(prev.value)} in FY{fy - 1}"
            cites += prev.citations
            growth = indicators.get(f"{name}_growth")
            if growth is not None and growth.value is not None:
                text += f" ({signed_pct(growth.value)})"
                cites += _indicator_cites(growth)
        items.append(("key_figures", text + ".", cites))
    return items


def indicator_evidence(
    indicators: dict[str, Indicator], fiscal_year: int
) -> list[tuple[str, str, list[Citation]]]:
    items = []
    for section, names in SECTIONS.items():
        for name in names:
            ind = indicators.get(name)
            if ind is None or ind.value is None:
                continue
            text = f"{LABELS[name]}: {format_indicator(ind)} in FY{fiscal_year}."
            items.append((section, text, _indicator_cites(ind)))
    return items


def altman_evidence(
    indicators: dict[str, Indicator], fiscal_year: int, distress_below: float, safe_above: float
) -> list[tuple[str, str, list[Citation]]]:
    ind = indicators.get("altman_z2")
    if ind is None or ind.value is None:
        return []
    zone = altman_zone(ind.value, distress_below, safe_above)
    text = (
        f"Altman Z'' score: {ind.value:.2f} in FY{fiscal_year}, {zone} zone "
        f"(distress below {distress_below}, safe above {safe_above})."
    )
    return [("solvency", text, _indicator_cites(ind))]


def not_applicable_evidence(indicators: list[Indicator]) -> list[tuple[str, str, list[Citation]]]:
    na = [i for i in indicators if i.status == "not_applicable"]
    if not na:
        return []
    names = ", ".join(i.name for i in na)
    text = f"Not applicable for a bank and therefore not computed: {names}."
    return [("solvency", text, [i.citation for i in na])]


def flag_evidence(flags: list[AnomalyFlag]) -> list[tuple[str, str, list[Citation]]]:
    triggered = [f for f in flags if f.triggered]
    items = [("red_flags", f"Red flag {f.name}: {f.reason}.", list(f.citations)) for f in triggered]
    if flags and not triggered:
        cites = [c for f in flags for c in f.citations if c.source_type == "computed"]
        if cites:
            items.append(
                (
                    "red_flags",
                    f"None of the {len(flags)} evaluated red-flag rules triggered.",
                    cites,
                )
            )
    return items


def _paragraph_citation(filing: Filing, paragraph_id: str) -> Citation:
    quote = None
    for section in filing.sections.values():
        for p in section.paragraphs:
            if p.id == paragraph_id:
                words = p.text.split()
                quote = " ".join(words[:QUOTE_WORDS]) + (" ..." if len(words) > QUOTE_WORDS else "")
    return Citation(
        source_type="section", ref=paragraph_id, accession=filing.ref.accession, quote=quote
    )


def risk_evidence(
    filing: Filing, risks: list[RiskPrediction], label_order: list[str]
) -> list[tuple[str, str, list[Citation]]]:
    if not risks:
        return []
    counts = Counter(label for r in risks for label in r.labels if label != "none")
    order = {label: i for i, label in enumerate(label_order)}
    items = []
    for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99))):
        examples = [r.paragraph_id for r in risks if label in r.labels][:MAX_RISK_EXAMPLES]
        text = (
            f"Risk theme {label}: main topic of {n} of {len(risks)} classified Item 1A "
            f"paragraphs (examples: {', '.join(examples)})."
        )
        items.append(("risk_themes", text, [_paragraph_citation(filing, pid) for pid in examples]))
    return items


def build_evidence(
    filing: Filing,
    current: KPISet,
    prior: KPISet | None,
    indicators: list[Indicator],
    flags: list[AnomalyFlag],
    risks: list[RiskPrediction],
    *,
    risk_labels: list[str],
    distress_below: float,
    safe_above: float,
) -> list[Evidence]:
    by_name = {i.name: i for i in indicators}
    fy = current.fiscal_year
    raw = [
        *kpi_evidence(current, prior, by_name),
        *indicator_evidence(by_name, fy),
        *altman_evidence(by_name, fy, distress_below, safe_above),
        *not_applicable_evidence(indicators),
        *flag_evidence(flags),
        *risk_evidence(filing, risks, risk_labels),
    ]
    cited = [(section, text, cites) for section, text, cites in raw if cites]
    return [
        Evidence(id=f"E{i}", section=section, text=text, citations=_dedupe(cites))
        for i, (section, text, cites) in enumerate(cited, start=1)
    ]
