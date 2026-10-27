"""kpi_extractor — key financial KPIs as JSON, with XBRL as ground truth.

Purpose: Produce revenue, net income, operating cash flow, total debt, cash, etc. for the
    fiscal year (and prior year). XBRL companyfacts is the ground truth; the LLM extracts
    the same KPIs from Item 8 tables so the two can be compared and reconciled.
Input: `Filing` (from filing_loader) + XBRL companyfacts JSON + KPI definitions
    (config/settings.yaml: kpis).
Output: (current, prior) `KPISet` — {kpi_name -> KPIValue(value, unit, period_end,
    expression, facts, citations)}; one xbrl Citation per fact used.
Status: XBRL part implemented (xbrl.py fact selection + candidate expressions, D-011);
    LLM extraction / reconcile not yet.
Calls a model: planned — LLM extraction from tables (fixed model from config, cached).
External tool: yes — EDGAR XBRL companyfacts API.
Eval: evals/kpi_extractor — now: coverage, match vs Item 8 tables, cross-filing agreement;
    planned: LLM exact match within 0.5% vs XBRL, scale/sign errors separately.
"""
