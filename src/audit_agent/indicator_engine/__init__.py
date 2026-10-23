"""indicator_engine — deterministic financial indicators and anomaly flags.

Purpose: Compute growth rates, margins, leverage, DSO, Altman Z, Beneish M-score and
    rule-based anomaly flags from KPIs. Pure functions; no I/O.
Input: current-year `KPISet` and prior-year `KPISet` (optional).
Output: list[`Indicator`] — value (None if inputs missing / not applicable), formula, and
    the XBRL-backed inputs used (for citations).
Calls a model: no.
External tool: no.
Eval: unit tests vs hand calculations (tests/test_indicator_engine.py) +
    evals/indicator_engine for coverage across the company set.
"""
