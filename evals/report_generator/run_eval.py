"""Eval: report_generator.

Runs the full pipeline (cached) for the company set and the deterministic faithfulness check.
Metrics:
- faithfulness_rate: supported statements / all statements (template + LLM summary);
- summary_faithfulness_rate: same, LLM summary sentences only (null if no summary generated);
- citation_correctness: citations that resolve to an existing paragraph / XBRL fact /
  indicator, over all citations;
- uncited_statement_count: must be 0;
- perturbed_detection_rate: every number-bearing statement is copied with its first number
  shifted by +10%; share of these planted false statements the checker rejects;
- summaries_generated: companies with an LLM summary (free-tier quota may block it);
- judge_agreement: null until a manual sample exists in data/gold/report_generator/.
Run: python -m evals.report_generator.run_eval
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from audit_agent.app.pipeline import PipelineResult, run_pipeline
from audit_agent.common.config import load_companies, load_settings, resolve_path
from audit_agent.common.tracing import JsonTracer
from audit_agent.report_generator.generator import (
    Report,
    ReportStatement,
    check_faithfulness,
    numbers_in,
)
from evals.common import write_results

COMPONENT = "report_generator"
SHIFT = 1.10
_FIRST_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def perturb(statement: ReportStatement) -> ReportStatement | None:
    """Copy with the first number scaled by SHIFT; None if the text has no number."""
    match = _FIRST_NUMBER.search(statement.text)
    if not match:
        return None
    value = float(match.group().replace(",", "")) * SHIFT
    text = statement.text[: match.start()] + f"{value:.2f}" + statement.text[match.end() :]
    return statement.model_copy(update={"text": text})


def perturbed_detection(result: PipelineResult) -> tuple[int, int]:
    """(detected, planted) for one company's report."""
    planted = [p for s in result.report.statements if numbers_in(s.text) and (p := perturb(s))]
    if not planted:
        return 0, 0
    fake = Report(
        ticker=result.report.ticker, fiscal_year=result.report.fiscal_year, statements=planted
    )
    kpi_sets = [result.kpis] + ([result.prior_kpis] if result.prior_kpis else [])
    check = check_faithfulness(fake, result.evidence, result.filing, kpi_sets, result.indicators)
    return len(check.unsupported_ids), len(planted)


def company_rows(result: PipelineResult) -> dict[str, Any]:
    f = result.faithfulness
    summary_idx = [i for i, s in enumerate(result.report.statements) if s.origin == "llm"]
    detected, planted = perturbed_detection(result)
    return {
        "ticker": result.company.ticker,
        "statements": f.n_statements,
        "supported": f.n_supported,
        "summary_statements": len(summary_idx),
        "summary_supported": sum(i not in f.unsupported_ids for i in summary_idx),
        "citations": sum(len(s.citations) for s in result.report.statements),
        "citation_errors": f.n_citation_errors,
        "uncited": sum(not s.citations for s in result.report.statements),
        "perturbed_detected": detected,
        "perturbed_planted": planted,
        "summary_status": result.report.summary_status,
        "unsupported_reasons": {str(k): v for k, v in f.reasons.items()},
    }


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = lambda key: sum(r[key] for r in rows)  # noqa: E731
    return {
        "faithfulness_rate": _ratio(total("supported"), total("statements")),
        "summary_faithfulness_rate": _ratio(
            total("summary_supported"), total("summary_statements")
        ),
        "citation_correctness": _ratio(
            total("citations") - total("citation_errors"), total("citations")
        ),
        "uncited_statement_count": total("uncited"),
        "perturbed_detection_rate": _ratio(total("perturbed_detected"), total("perturbed_planted")),
        "summaries_generated": sum(r["summary_statements"] > 0 for r in rows),
        "judge_agreement": None,
    }


def main(results_root: Path | None = None) -> int:
    settings = load_settings()
    companies = load_companies()
    fy = companies.default_fiscal_year
    rows = []
    for company in companies.companies:
        tracer = JsonTracer(resolve_path(settings.tracing.log_dir))
        rows.append(company_rows(run_pipeline(company.ticker, fy, tracer)))
    metrics = score(rows)
    path = write_results(
        COMPONENT,
        metrics=metrics,
        dataset={"name": "pipeline_reports", "n": len(rows), "fiscal_year": fy},
        notes="Deterministic faithfulness check (citations resolve, numbers in cited evidence). "
        "LLM summaries depend on the free daily quota; no manual sample yet.",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    predictions.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"{COMPONENT}: {json.dumps(metrics, indent=1)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
