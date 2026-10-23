"""Stub: cited report generation and faithfulness check (see package docstring)."""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.common.citations import CitedStatement
from audit_agent.common.llm_client import LLMClient
from audit_agent.consistency_checker.checker import CheckResult
from audit_agent.filing_loader.loader import Filing
from audit_agent.indicator_engine.indicators import Indicator
from audit_agent.kpi_extractor.extractor import KPISet
from audit_agent.risk_detector.labels import RiskPrediction

DISCLAIMER = "Automated analysis of public filings. Not investment advice."


class Report(BaseModel):
    ticker: str
    fiscal_year: int
    statements: list[CitedStatement]
    disclaimer: str = DISCLAIMER


class FaithfulnessResult(BaseModel):
    n_statements: int
    n_supported: int
    n_citation_errors: int  # cited ref does not exist / wrong source
    unsupported_ids: list[int]


def generate_report(
    filing: Filing,
    kpis: KPISet,
    indicators: list[Indicator],
    risks: list[RiskPrediction],
    checks: list[CheckResult],
    client: LLMClient,
) -> Report:
    raise NotImplementedError


def check_faithfulness(
    report: Report, filing: Filing, kpis: KPISet, indicators: list[Indicator]
) -> FaithfulnessResult:
    raise NotImplementedError
