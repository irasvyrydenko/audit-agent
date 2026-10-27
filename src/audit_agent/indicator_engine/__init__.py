"""indicator_engine — deterministic financial indicators and anomaly flags.

Purpose: Compute growth rates, margins, current ratio, leverage, DSO, cash conversion,
    Altman Z'' and rule-based anomaly flags from KPIs (D-012). Pure functions; no I/O —
    `IndicatorSettings` is passed in. Beneish M-score is deferred.
Input: current-year `KPISet`, prior-year `KPISet` (optional), `IndicatorSettings`, is_bank.
Output: list[`Indicator`] (value, status ok/missing/not_applicable, formula, inputs, XBRL
    citations of the inputs) and list[`AnomalyFlag`] (triggered, reason, citations).
Calls a model: no.
External tool: no.
Eval: unit tests vs hand calculations (tests/test_indicator_engine.py) +
    evals/indicator_engine for coverage across the company set.
"""
