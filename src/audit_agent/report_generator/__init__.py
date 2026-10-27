"""report_generator — short cited summary + faithfulness check.

Purpose: Build cited evidence sentences by code (evidence.py: KPIs, indicators, red flags,
    risk themes), add a short LLM summary whose sentences must reference evidence ids, then
    verify every statement deterministically: citations resolve to an existing paragraph /
    XBRL fact / indicator and every number appears in the cited evidence (D-014).
    Includes a "not investment advice" disclaimer.
Input: `Filing`, current + prior `KPISet`, list[`Indicator`], list[`AnomalyFlag`],
    list[`RiskPrediction`] (consistency results: not yet).
Output: `Report` (list[ReportStatement], each a CitedStatement) + `FaithfulnessResult`.
Calls a model: yes — one summary call per company-year (fixed model, cached); optional.
External tool: no.
Eval: evals/report_generator — faithfulness rate and citation correctness (cited source
    exists and supports the statement).
"""
