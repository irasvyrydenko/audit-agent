"""Run the pipeline for every company in config/companies.yaml so all EDGAR downloads and LLM
answers land in the disk caches (do this before a demo; rerun after the LLM quota resets).

Run: py scripts/warm_cache.py [fiscal_year]
"""

from __future__ import annotations

import sys

from audit_agent.app.pipeline import run_pipeline
from audit_agent.common.config import load_companies, load_settings, resolve_path
from audit_agent.common.tracing import JsonTracer


def main(fiscal_year: int | None = None) -> int:
    companies = load_companies()
    fy = fiscal_year or companies.default_fiscal_year
    log_dir = resolve_path(load_settings().tracing.log_dir)
    for company in companies.companies:
        result = run_pipeline(company.ticker, fy, JsonTracer(log_dir))
        f = result.faithfulness
        print(
            f"{company.ticker} FY{fy}: risks {result.risk_status}, "
            f"summary {result.report.summary_status}, faithful {f.n_supported}/{f.n_statements}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
