"""TF-IDF + logistic regression baseline (one-vs-rest, multi-label) — D-015.

"none" is not a trained class: a paragraph gets ["none"] when no risk label reaches the
probability threshold. Labels without positive training examples are never predicted.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from audit_agent.common.citations import Citation
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.labels import RiskPrediction

NONE_LABEL = "none"
THRESHOLD = 0.5


class TfidfLogRegBaseline:
    def __init__(self, labels: list[str], seed: int = 42, threshold: float = THRESHOLD) -> None:
        self.labels = [label for label in labels if label != NONE_LABEL]
        self.seed = seed
        self.threshold = threshold
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), sublinear_tf=True, min_df=1, stop_words="english"
        )
        self.models: dict[str, LogisticRegression | None] = {}

    def fit(self, texts: list[str], targets: list[list[str]]) -> TfidfLogRegBaseline:
        if not texts or len(texts) != len(targets):
            raise ValueError("texts and targets must be non-empty and aligned")
        x = self.vectorizer.fit_transform(texts)
        for label in self.labels:
            y = np.array([label in t for t in targets], dtype=int)
            if y.min() == y.max():  # no positives (or no negatives): cannot learn this label
                self.models[label] = None
                continue
            model = LogisticRegression(
                class_weight="balanced", max_iter=1000, random_state=self.seed
            )
            self.models[label] = model.fit(x, y)
        return self

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        if not self.models:
            raise RuntimeError("fit() first")
        x = self.vectorizer.transform(texts)
        probs: list[dict[str, float]] = [{} for _ in texts]
        for label, model in self.models.items():
            column = model.predict_proba(x)[:, 1] if model is not None else np.zeros(len(texts))
            for row, p in zip(probs, column, strict=True):
                row[label] = float(p)
        return probs

    def predict_labels(self, texts: list[str]) -> list[list[str]]:
        return [
            [label for label in self.labels if p[label] >= self.threshold] or [NONE_LABEL]
            for p in self.predict_proba(texts)
        ]

    def predict(self, paragraphs: list[Paragraph]) -> list[RiskPrediction]:
        texts = [p.text for p in paragraphs]
        out = []
        for paragraph, probs, labels in zip(
            paragraphs, self.predict_proba(texts), self.predict_labels(texts), strict=True
        ):
            out.append(
                RiskPrediction(
                    paragraph_id=paragraph.id,
                    labels=labels,
                    scores={k: round(v, 4) for k, v in probs.items()},
                    method="baseline",
                    citation=Citation(source_type="section", ref=paragraph.id),
                )
            )
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(self))

    @classmethod
    def load(cls, path: Path) -> TfidfLogRegBaseline:
        model = pickle.loads(path.read_bytes())  # noqa: S301 - our own local artifact
        if not isinstance(model, cls):
            raise TypeError(f"{path} does not contain a {cls.__name__}")
        return model
