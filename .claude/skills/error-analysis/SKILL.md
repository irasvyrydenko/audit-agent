---
name: error-analysis
description: Use after an eval run when metrics are below target or before changing prompts/rules — explains how to sample failures, group them into categories, and write findings into docs/error_analysis.md.
---

# Error analysis

Goal: understand *why* a component fails before changing it. Write findings in
`docs/error_analysis.md` under the component's section, newest first.

## 1. Collect failures
- Source: `evals/<component>/results/predictions_latest.jsonl` (id, gold, pred, correct).
  If missing, add it to the eval script first (see `add-component-eval`).
- Note the run: results timestamp, git commit, model (from `latest.json`).

## 2. Sample
- ≤ 30 failures: inspect all.
- More: random sample of 30–50 with a fixed seed (`eval.random_seed`), **stratified** by the
  most relevant dimension (company, risk label, KPI, verdict) so rare classes are seen.
- Also look at ~5 correct examples to check they're right for the right reason.

## 3. Categorize (open coding, then merge)
- First pass: write a short free-text reason per failure.
- Second pass: merge into 4–8 categories; each failure gets exactly one primary category.
- Starter categories per component:
  - filing_loader: heading not detected, TOC matched instead of body, Item merged/split, table in text.
  - kpi_extractor: wrong tag, wrong period (Q vs FY / prior year), **scale**, **sign**, restatement, missing.
  - risk_detector: label ambiguity (gold questionable), boilerplate, multi-label miss, rare class, hallucinated label.
  - consistency_checker: claim mis-extracted, wrong metric mapped, tolerance edge, non-GAAP metric, segment-level claim.
  - report_generator: unsupported statement, wrong citation, citation to wrong period, uncited.
- If gold looks wrong, count it as "gold error" and fix `data/gold/` (log the fix).

## 4. Write it up
Use the template at the top of `docs/error_analysis.md`: table with category, count,
% of failures, example id, likely cause; then 2–4 findings and concrete actions.
Prioritize actions by (count × ease of fix).

## 5. Close the loop
- Non-obvious fix → entry in `docs/decisions.md`.
- After the fix, rerun the eval and record before/after in `docs/crisp_dm.md` → Evaluation.
- Don't fix on the test split by memorizing examples; fix the category.
