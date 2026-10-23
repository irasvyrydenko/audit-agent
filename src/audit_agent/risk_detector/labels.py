"""Shared types for risk_detector. The label set itself lives in config/settings.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation


class RiskPrediction(BaseModel):
    paragraph_id: str
    labels: list[str]
    scores: dict[str, float]
    method: Literal["baseline", "llm"]
    citation: Citation
