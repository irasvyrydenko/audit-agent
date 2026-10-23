"""Stub: TF-IDF + logistic regression baseline (one-vs-rest, multi-label)."""

from __future__ import annotations

from pathlib import Path

from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.labels import RiskPrediction


class TfidfLogRegBaseline:
    def __init__(self, labels: list[str], seed: int = 42) -> None:
        self.labels = labels
        self.seed = seed

    def fit(self, texts: list[str], targets: list[list[str]]) -> None:
        raise NotImplementedError

    def predict(self, paragraphs: list[Paragraph]) -> list[RiskPrediction]:
        raise NotImplementedError

    def save(self, path: Path) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path) -> TfidfLogRegBaseline:
        raise NotImplementedError
