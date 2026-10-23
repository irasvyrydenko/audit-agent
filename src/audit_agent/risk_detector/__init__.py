"""risk_detector — label Item 1A / MD&A paragraphs with risk categories.

Purpose: Multi-label classification of paragraphs into risk labels (config: risk_labels —
    going concern, litigation, customer concentration, covenants, cyber, ...). Two methods:
    a TF-IDF + logistic regression baseline (baseline.py) and an LLM classifier
    (llm_classifier.py), always evaluated side by side.
Input: list[`Paragraph`] from filing_loader (Items 1A and 7).
Output: list[`RiskPrediction`] — labels + scores per paragraph, with paragraph citation.
Calls a model: yes — LLM classifier (fixed model, cached); baseline is scikit-learn.
External tool: no.
Eval: evals/risk_detector — per-class precision/recall/F1 for LLM vs baseline on
    data/gold/risk_detector/.
"""
