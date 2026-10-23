"""Stub: end-to-end pipeline used by the UI and by end-to-end tests."""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.common.tracing import JsonTracer
from audit_agent.report_generator.generator import FaithfulnessResult, Report


class PipelineResult(BaseModel):
    run_id: str
    report: Report
    faithfulness: FaithfulnessResult


def run_pipeline(ticker: str, fiscal_year: int, tracer: JsonTracer) -> PipelineResult:
    """filing_loader -> kpi_extractor -> indicator_engine -> risk_detector
    -> consistency_checker -> report_generator, one tracer span per step."""
    raise NotImplementedError
