"""Stub: claim extraction and verification (see package docstring)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation
from audit_agent.common.llm_client import LLMClient
from audit_agent.filing_loader.loader import Section
from audit_agent.indicator_engine.indicators import Indicator
from audit_agent.kpi_extractor.extractor import KPISet

Verdict = Literal["supported", "contradicted", "unverifiable"]


class Claim(BaseModel):
    id: str
    paragraph_id: str
    text: str
    metric: str | None  # kpi/indicator name the claim is about
    direction: Literal["up", "down", "flat"] | None = None
    value: float | None = None  # claimed number, normalized (e.g. 0.08 for 8%)


class CheckResult(BaseModel):
    claim: Claim
    verdict: Verdict
    evidence: list[Citation]
    rationale: str


def extract_claims(mdna: Section, client: LLMClient) -> list[Claim]:
    raise NotImplementedError


def verify_claim(
    claim: Claim,
    current: KPISet,
    prior: KPISet | None,
    indicators: list[Indicator],
    tolerance: float,
) -> CheckResult:
    raise NotImplementedError


def perturb_claim(claim: Claim, seed: int) -> Claim:
    """Eval helper: flip direction or shift the number so the claim should be contradicted."""
    raise NotImplementedError
