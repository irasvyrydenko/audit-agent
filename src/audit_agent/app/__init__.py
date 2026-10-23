"""app — Streamlit UI and pipeline orchestration with tracing.

Purpose: Let the user pick a company (config/companies.yaml) and fiscal year, run the full
    pipeline, and show KPIs, indicators, risks, consistency verdicts and the cited report.
Input: user selection (ticker, fiscal_year).
Output: rendered UI; trace in logs/<run_id>.jsonl (JSON backend) or Langfuse.
Calls a model: indirectly, through the components.
External tool: indirectly (EDGAR via filing_loader / kpi_extractor).
Eval: none of its own; end-to-end smoke test once components exist.
"""
