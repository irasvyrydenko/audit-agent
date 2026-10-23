"""report_generator — short cited summary + faithfulness check.

Purpose: Write a short analyst-style summary where every statement cites a filing
    paragraph, XBRL fact or computed indicator; then verify each statement is supported by
    its citations. Includes a "not investment advice" disclaimer.
Input: `Filing`, `KPISet`, list[`Indicator`], list[`RiskPrediction`], list[`CheckResult`].
Output: `Report` (list[CitedStatement]) + `FaithfulnessResult`.
Calls a model: yes — generation and (optionally) LLM-judged faithfulness (fixed model, cached).
External tool: no.
Eval: evals/report_generator — faithfulness rate and citation correctness (cited source
    exists and supports the statement).
"""
