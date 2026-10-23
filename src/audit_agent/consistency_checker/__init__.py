"""consistency_checker — do MD&A claims agree with the numbers?

Purpose: Extract quantitative/directional claims from MD&A ("revenue grew 8%", "margins
    improved") and verify each against KPIs and computed indicators.
Input: Item 7 `Section` + `KPISet` (current, prior) + list[`Indicator`].
Output: list[`CheckResult`] — verdict supported / contradicted / unverifiable, evidence
    citations, short rationale.
Calls a model: yes — claim extraction (fixed model, cached). Verification is deterministic.
External tool: no.
Eval: evals/consistency_checker — verdict accuracy on gold claims, including perturbed
    claims (numbers/directions flipped) that must become "contradicted".
"""
