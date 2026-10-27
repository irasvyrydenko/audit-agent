"""consistency_checker — do MD&A claims agree with the numbers?

Purpose: Extract quantitative/directional claims from MD&A ("revenue grew 8%", "margins
    improved") and verify each against KPIs and computed indicators.
Input: Item 7 paragraphs + `KPISet` (current, prior).
Output: list[`CheckResult`] — verdict supported / contradicted / unverifiable, evidence
    citations (paragraph + XBRL facts), rationale, computed value.
Modules: extractor.py (candidate paragraphs by code, LLM returns number + unit as written,
    scaling in code, quotes must occur in the paragraph); checker.py (metric values incl.
    margins from KPIs, rounding-aware tolerance, verdicts, perturb_claim) — D-016.
Calls a model: yes — claim extraction only (fixed model, cached, <= 3 calls per filing).
    Verification is deterministic.
External tool: no.
Eval: evals/consistency_checker — verdict accuracy on gold claims, including perturbed
    claims (numbers/directions flipped) that must become "contradicted".
"""
