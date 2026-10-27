# Error Analysis

Filled in with the `error-analysis` skill after an eval run. One section per component;
newest analysis first within each section. Always note the eval run it refers to
(results file timestamp, git commit, model).

## Template

```markdown
### <component> — YYYY-MM-DD (commit abc1234, model <name>)
- Eval run: evals/<component>/results/<timestamp>.json — <headline metric>
- Sample: N failures of M total, sampled with seed S (stratified by <...>)

| Category | Count | % of failures | Example (id) | Likely cause |
|---|---|---|---|---|
| ... | | | | |

**Findings:** 2–4 bullets.
**Actions:** what to change next (link docs/decisions.md entry if a decision follows).
```

## filing_loader

### filing_loader — 2026-10-27 (dev split, no LLM)
- Eval run: evals/filing_loader/results/latest.json — segmentation_accuracy 0.9333 (14/15)
- Sample: all 1 failure inspected.

| Category | Count | % of failures | Example (id) | Likely cause |
|---|---|---|---|---|
| Running header kept as paragraph | 1 | 100% | JPM_2024:1A | "Parts I and II" repeats < 3 times as a standalone block, so the boilerplate filter misses it |

**Findings:** boundaries themselves are right in all 15 cases; the only error is residual
page furniture. Pointer resolution (JPM, XOM) works on both filings.
**Actions:** low priority — paragraph-level noise does not affect risk/claim extraction much.
Build a held-out gold split before tuning further.

## kpi_extractor
_No analysis yet._ Expected categories: wrong tag, wrong period (quarter vs FY), scale
(thousands vs units), sign, restated value, missing.

## indicator_engine
_No analysis yet._

## risk_detector
_No analysis yet._

## consistency_checker
_No analysis yet._

## report_generator
_No analysis yet._
