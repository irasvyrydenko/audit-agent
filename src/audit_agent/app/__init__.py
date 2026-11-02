"""app — Streamlit UI and pipeline orchestration with tracing.

Purpose: Let the user pick a company (config/companies.yaml) and fiscal year, run the full
    pipeline, and show KPIs, indicators, risks, consistency verdicts and the cited report.
Input: user selection (ticker, fiscal_year).
Output: rendered UI; trace in logs/<run_id>.jsonl (JSON backend) or Langfuse.
Calls a model: indirectly, through the components.
External tool: indirectly (EDGAR via filing_loader / kpi_extractor).
Status: `run_pipeline` runs a LangGraph `StateGraph` (D-017), one traced node per
    component: filing_loader → kpi_extractor → indicator_engine → risk_detector →
    consistency_checker → report_generator. UI tabs: Report, KPIs, Indicators & flags,
    Risks, Trace. `scripts/warm_cache.py` pre-fills caches.
Eval: none of its own; covered by evals/report_generator (runs the full pipeline).
"""
