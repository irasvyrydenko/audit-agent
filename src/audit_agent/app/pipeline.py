"""End-to-end pipeline used by the UI, the report eval and the cache warm-up script.

filing_loader -> kpi_extractor -> indicator_engine -> risk_detector -> report_generator,
one tracer span per step. consistency_checker is not wired in yet (not implemented).
Every step is cached (EDGAR raw files, processed filing JSON, LLM disk cache), so a rerun
of the same (ticker, fiscal year) makes no network or LLM calls.
"""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.common.config import Company, Settings, load_companies, load_settings
from audit_agent.common.edgar_client import EdgarClient
from audit_agent.common.llm_client import LLMClient, LLMRateLimitError
from audit_agent.common.tracing import JsonTracer
from audit_agent.filing_loader.loader import Filing, load_filing
from audit_agent.indicator_engine.indicators import (
    AnomalyFlag,
    Indicator,
    anomaly_flags,
    compute_all,
)
from audit_agent.kpi_extractor.extractor import KPISet, load_kpis
from audit_agent.report_generator.evidence import Evidence, build_evidence
from audit_agent.report_generator.generator import (
    FaithfulnessResult,
    Report,
    check_faithfulness,
    generate_report,
)
from audit_agent.risk_detector.labels import RiskPrediction
from audit_agent.risk_detector.llm_classifier import detect_risks


class PipelineResult(BaseModel):
    run_id: str
    company: Company
    filing: Filing
    kpis: KPISet
    prior_kpis: KPISet | None
    indicators: list[Indicator]
    flags: list[AnomalyFlag]
    risks: list[RiskPrediction]
    risk_status: str  # "ok" | "partial: ..." | "skipped: ..."
    evidence: list[Evidence]
    report: Report
    faithfulness: FaithfulnessResult


def find_company(ticker: str) -> Company:
    for company in load_companies().companies:
        if company.ticker.upper() == ticker.upper():
            return company
    return Company(ticker=ticker.upper(), name=ticker.upper(), sector="unknown")


def _risks(
    filing: Filing, client: LLMClient, settings: Settings, tracer: JsonTracer
) -> tuple[list[RiskPrediction], str]:
    failed: list[str] = []
    try:
        risks = detect_risks(
            filing.sections["1A"].paragraphs if "1A" in filing.sections else [],
            client,
            settings,
            on_error=lambda p, e: failed.append(p.id),
        )
    except LLMRateLimitError as exc:
        tracer.log("risk_detector", "rate_limited", error=str(exc)[:200])
        return [], "skipped: LLM daily quota exhausted"
    status = f"partial: {len(failed)} paragraphs failed" if failed else "ok"
    return risks, status


def run_pipeline(
    ticker: str,
    fiscal_year: int,
    tracer: JsonTracer,
    *,
    edgar: EdgarClient | None = None,
    llm: LLMClient | None = None,
    summarize: bool = True,
) -> PipelineResult:
    """Run all implemented components for one company-year."""
    settings = load_settings()
    company = find_company(ticker)
    edgar = edgar or EdgarClient()
    llm = llm or LLMClient()
    tracer.log("pipeline", "start", ticker=company.ticker, fiscal_year=fiscal_year)

    with tracer.span("filing_loader", "load_filing"):
        filing = load_filing(company.ticker, fiscal_year, client=edgar)
    tracer.log(
        "filing_loader", "result", accession=filing.ref.accession, sections=list(filing.sections)
    )

    with tracer.span("kpi_extractor", "extract"):
        current, prior = load_kpis(company.ticker, fiscal_year, filing.ref, client=edgar)
    tracer.log(
        "kpi_extractor",
        "result",
        present=sum(v.value is not None for v in current.values.values()),
        total=len(current.values),
    )

    with tracer.span("indicator_engine", "compute"):
        indicators = compute_all(current, prior, settings.indicators, is_bank=company.bank)
        flags = anomaly_flags(current, indicators, settings.indicators, is_bank=company.bank)
    tracer.log("indicator_engine", "result", triggered=[f.name for f in flags if f.triggered])

    with tracer.span("risk_detector", "classify"):
        risks, risk_status = _risks(filing, llm, settings, tracer)
    tracer.log("risk_detector", "result", n=len(risks), status=risk_status)

    with tracer.span("report_generator", "generate"):
        zones = settings.indicators.altman_z2_zones
        evidence = build_evidence(
            filing,
            current,
            prior,
            indicators,
            flags,
            risks,
            risk_labels=settings.risk_labels,
            distress_below=zones.distress_below,
            safe_above=zones.safe_above,
        )
        report = generate_report(
            company.ticker, fiscal_year, evidence, llm if summarize else None, company.name
        )
        kpi_sets = [current] + ([prior] if prior else [])
        faithfulness = check_faithfulness(report, evidence, filing, kpi_sets, indicators)
    tracer.log(
        "report_generator",
        "result",
        statements=faithfulness.n_statements,
        supported=faithfulness.n_supported,
        citation_errors=faithfulness.n_citation_errors,
        summary_status=report.summary_status,
    )
    tracer.log("pipeline", "end", ticker=company.ticker, fiscal_year=fiscal_year)
    return PipelineResult(
        run_id=tracer.run_id,
        company=company,
        filing=filing,
        kpis=current,
        prior_kpis=prior,
        indicators=indicators,
        flags=flags,
        risks=risks,
        risk_status=risk_status,
        evidence=evidence,
        report=report,
        faithfulness=faithfulness,
    )
