"""End-to-end pipeline used by the UI, the report eval and the cache warm-up script.

Orchestrated as a LangGraph ``StateGraph`` (D-017): one node per component,
filing_loader -> kpi_extractor -> indicator_engine -> risk_detector -> consistency_checker
-> report_generator, one tracer span per node. Nodes only wire components together; all
LLM calls still go through ``LLMClient`` (disk cache, temperature 0).
Every step is cached (EDGAR raw files, processed filing JSON, LLM disk cache), so a rerun
of the same (ticker, fiscal year) makes no network or LLM calls.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from audit_agent.common.config import Company, Settings, load_companies, load_settings
from audit_agent.common.edgar_client import EdgarClient
from audit_agent.common.llm_client import LLMClient, LLMRateLimitError
from audit_agent.common.tracing import JsonTracer
from audit_agent.consistency_checker.checker import CheckResult, verify_claim
from audit_agent.consistency_checker.extractor import extract_claims
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
    checks: list[CheckResult] = []
    check_status: str = "not run"
    evidence: list[Evidence]
    report: Report
    faithfulness: FaithfulnessResult


class PipelineState(TypedDict, total=False):
    """Graph state: the inputs, then the keys each node adds."""

    company: Company
    fiscal_year: int
    summarize: bool
    filing: Filing
    kpis: KPISet
    prior_kpis: KPISet | None
    indicators: list[Indicator]
    flags: list[AnomalyFlag]
    risks: list[RiskPrediction]
    risk_status: str
    checks: list[CheckResult]
    check_status: str
    evidence: list[Evidence]
    report: Report
    faithfulness: FaithfulnessResult


Update = dict[str, Any]
Node = Callable[[PipelineState], Update]

# (node / tracer component, span name), in execution order.
STEPS: list[tuple[str, str]] = [
    ("filing_loader", "load_filing"),
    ("kpi_extractor", "extract"),
    ("indicator_engine", "compute"),
    ("risk_detector", "classify"),
    ("consistency_checker", "check"),
    ("report_generator", "generate"),
]


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


def _checks(
    filing: Filing,
    current: KPISet,
    prior: KPISet | None,
    client: LLMClient,
    settings: Settings,
    tracer: JsonTracer,
) -> tuple[list[CheckResult], str]:
    cfg = settings.consistency
    paragraphs = filing.sections["7"].paragraphs if "7" in filing.sections else []
    try:
        claims, failed = extract_claims(paragraphs, filing.fiscal_year, client, cfg)
    except LLMRateLimitError as exc:
        tracer.log("consistency_checker", "rate_limited", error=str(exc)[:200])
        return [], "skipped: LLM daily quota exhausted"
    results = [
        verify_claim(c, current, prior, cfg.numeric_tolerance, cfg.flat_threshold) for c in claims
    ]
    status = f"partial: {failed} batches failed" if failed else "ok"
    return results, status


def _filing_node(edgar: EdgarClient, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        filing = load_filing(state["company"].ticker, state["fiscal_year"], client=edgar)
        tracer.log(
            "filing_loader",
            "result",
            accession=filing.ref.accession,
            sections=list(filing.sections),
        )
        return {"filing": filing}

    return node


def _kpi_node(edgar: EdgarClient, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        current, prior = load_kpis(
            state["company"].ticker, state["fiscal_year"], state["filing"].ref, client=edgar
        )
        tracer.log(
            "kpi_extractor",
            "result",
            present=sum(v.value is not None for v in current.values.values()),
            total=len(current.values),
        )
        return {"kpis": current, "prior_kpis": prior}

    return node


def _indicator_node(settings: Settings, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        bank = state["company"].bank
        current, prior = state["kpis"], state["prior_kpis"]
        indicators = compute_all(current, prior, settings.indicators, is_bank=bank)
        flags = anomaly_flags(current, indicators, settings.indicators, is_bank=bank)
        tracer.log("indicator_engine", "result", triggered=[f.name for f in flags if f.triggered])
        return {"indicators": indicators, "flags": flags}

    return node


def _risk_node(llm: LLMClient, settings: Settings, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        risks, status = _risks(state["filing"], llm, settings, tracer)
        tracer.log("risk_detector", "result", n=len(risks), status=status)
        return {"risks": risks, "risk_status": status}

    return node


def _check_node(llm: LLMClient, settings: Settings, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        checks, status = _checks(
            state["filing"], state["kpis"], state["prior_kpis"], llm, settings, tracer
        )
        tracer.log(
            "consistency_checker",
            "result",
            n=len(checks),
            verdicts=[c.verdict for c in checks],
            status=status,
        )
        return {"checks": checks, "check_status": status}

    return node


def _report_node(llm: LLMClient, settings: Settings, tracer: JsonTracer) -> Node:
    def node(state: PipelineState) -> Update:
        company = state["company"]
        filing, current, prior = state["filing"], state["kpis"], state["prior_kpis"]
        zones = settings.indicators.altman_z2_zones
        evidence = build_evidence(
            filing,
            current,
            prior,
            state["indicators"],
            state["flags"],
            state["risks"],
            risk_labels=settings.risk_labels,
            distress_below=zones.distress_below,
            safe_above=zones.safe_above,
            checks=state["checks"],
        )
        summarizer = llm if state["summarize"] else None
        report = generate_report(
            company.ticker, state["fiscal_year"], evidence, summarizer, company.name
        )
        kpi_sets = [current] + ([prior] if prior else [])
        faithfulness = check_faithfulness(report, evidence, filing, kpi_sets, state["indicators"])
        tracer.log(
            "report_generator",
            "result",
            statements=faithfulness.n_statements,
            supported=faithfulness.n_supported,
            citation_errors=faithfulness.n_citation_errors,
            summary_status=report.summary_status,
        )
        return {"evidence": evidence, "report": report, "faithfulness": faithfulness}

    return node


def _traced(component: str, name: str, node: Node, tracer: JsonTracer) -> Node:
    def wrapped(state: PipelineState) -> Update:
        with tracer.span(component, name):
            return node(state)

    return wrapped


def build_graph(
    settings: Settings, edgar: EdgarClient, llm: LLMClient, tracer: JsonTracer
) -> CompiledStateGraph:
    """Compile the pipeline graph: one traced node per component, run in ``STEPS`` order."""
    nodes: dict[str, Node] = {
        "filing_loader": _filing_node(edgar, tracer),
        "kpi_extractor": _kpi_node(edgar, tracer),
        "indicator_engine": _indicator_node(settings, tracer),
        "risk_detector": _risk_node(llm, settings, tracer),
        "consistency_checker": _check_node(llm, settings, tracer),
        "report_generator": _report_node(llm, settings, tracer),
    }
    graph = StateGraph(PipelineState)
    previous = START
    for component, name in STEPS:
        graph.add_node(component, _traced(component, name, nodes[component], tracer))
        graph.add_edge(previous, component)
        previous = component
    graph.add_edge(previous, END)
    return graph.compile()


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
    graph = build_graph(settings, edgar or EdgarClient(), llm or LLMClient(), tracer)
    tracer.log("pipeline", "start", ticker=company.ticker, fiscal_year=fiscal_year)
    state = graph.invoke({"company": company, "fiscal_year": fiscal_year, "summarize": summarize})
    tracer.log("pipeline", "end", ticker=company.ticker, fiscal_year=fiscal_year)
    return PipelineResult(
        run_id=tracer.run_id,
        company=company,
        filing=state["filing"],
        kpis=state["kpis"],
        prior_kpis=state["prior_kpis"],
        indicators=state["indicators"],
        flags=state["flags"],
        risks=state["risks"],
        risk_status=state["risk_status"],
        checks=state["checks"],
        check_status=state["check_status"],
        evidence=state["evidence"],
        report=state["report"],
        faithfulness=state["faithfulness"],
    )
