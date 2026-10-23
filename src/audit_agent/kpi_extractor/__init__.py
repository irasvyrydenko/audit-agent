"""kpi_extractor — key financial KPIs as JSON, with XBRL as ground truth.

Purpose: Produce revenue, net income, operating cash flow, total debt, cash, etc. for the
    fiscal year (and prior year). XBRL companyfacts is the ground truth; the LLM extracts
    the same KPIs from Item 8 tables so the two can be compared and reconciled.
Input: `Filing` (from filing_loader) + XBRL companyfacts JSON + KPI definitions
    (config/settings.yaml: kpis).
Output: `KPISet` — {kpi_name -> KPIValue(value, unit, period_end, xbrl_tag, citation)}.
Calls a model: yes — LLM extraction from tables (fixed model from config, cached).
External tool: yes — EDGAR XBRL companyfacts API.
Eval: evals/kpi_extractor — exact match within 0.5% vs XBRL; scale (x1000) and sign
    errors counted separately.
"""
