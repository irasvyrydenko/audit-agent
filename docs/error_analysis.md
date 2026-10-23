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
_No analysis yet._

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
