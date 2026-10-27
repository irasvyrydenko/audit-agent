"""Draw the paragraph sample for risk_detector gold labeling (deterministic, seed from config).

Writes data/gold/risk_detector/paragraphs.jsonl with empty `labels`; existing labels for the
same paragraph_id are kept, so re-running never discards manual work. Half of each company's
sample is `dev` (prompt / batch-size choices), half `test` (reported metrics only).
Run: python -m evals.risk_detector.sample_gold [per_company]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

from audit_agent.common.config import load_companies, load_settings, resolve_path
from audit_agent.filing_loader.loader import load_filing
from audit_agent.risk_detector.llm_classifier import select_paragraphs

DEFAULT_PER_COMPANY = 16


def gold_path() -> Path:
    return resolve_path(load_settings().paths.gold) / "risk_detector" / "paragraphs.jsonl"


def read_gold(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sample_company(ticker: str, fiscal_year: int, k: int, seed: int) -> list[dict[str, Any]]:
    settings = load_settings()
    filing = load_filing(ticker, fiscal_year)
    pool = select_paragraphs(filing.sections["1A"].paragraphs, settings.risk_detector)
    rng = random.Random(f"{seed}-{ticker}-{fiscal_year}")
    chosen = sorted(rng.sample(pool, min(k, len(pool))), key=lambda p: p.index)
    dev_ids = {p.id for p in rng.sample(chosen, len(chosen) // 2)}  # half dev, half test
    return [
        {
            "paragraph_id": p.id,
            "ticker": ticker,
            "fy": fiscal_year,
            "text": p.text,
            "labels": [],
            "split": "dev" if p.id in dev_ids else "test",
            "labeled_by": None,
        }
        for p in chosen
    ]


def main(per_company: int = DEFAULT_PER_COMPANY) -> int:
    settings = load_settings()
    companies = load_companies()
    path = gold_path()
    existing = {(r["ticker"], r["fy"], r["paragraph_id"]): r for r in read_gold(path)}
    rows = []
    for company in companies.companies:
        for row in sample_company(
            company.ticker, companies.default_fiscal_year, per_company, settings.eval.random_seed
        ):
            old = existing.get((row["ticker"], row["fy"], row["paragraph_id"]))
            if old:  # keep manual labels, refresh the deterministic split
                row = {**row, "labels": old["labels"], "labeled_by": old["labeled_by"]}
            rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} paragraphs -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PER_COMPANY))
