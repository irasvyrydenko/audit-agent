"""Stub: LLM risk classifier (JSON output constrained to the configured label set)."""

from __future__ import annotations

from audit_agent.common.llm_client import LLMClient
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.labels import RiskPrediction


def classify_paragraphs(
    paragraphs: list[Paragraph], labels: list[str], client: LLMClient
) -> list[RiskPrediction]:
    raise NotImplementedError
