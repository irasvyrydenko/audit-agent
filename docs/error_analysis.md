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

### kpi_extractor — 2026-10-27 (XBRL part, no LLM)
- Eval run: evals/kpi_extractor/results/latest.json — table_match_rate 0.987 (74/75)
- Sample: all failures inspected (1 table miss; 2 earlier misses were an eval parsing bug:
  negatives written as "( 19,154 )").

| Category | Count | % of failures | Example (id) | Likely cause |
|---|---|---|---|---|
| Rounded text fact preferred over statement line | 1 | 100% | JNJ current_debt | `DebtCurrent` = 6,000 from a note; balance sheet "Loans and notes payable" 5,983 (0.3% off) |

**Findings:** missing KPIs are genuinely unreported concepts, not selection errors.
**Actions:** none for the demo; revisit if a filer-specific current-debt rule is needed.

Expected categories for the LLM part: wrong tag, wrong period (quarter vs FY), scale
(thousands vs units), sign, restated value, missing.

## indicator_engine
_No analysis yet._

## risk_detector

### risk_detector — 2026-10-27 (preliminary, model nvidia/nemotron-3.5-super-vl:free)
- Eval run: evals/risk_detector/results/latest.json — micro-F1 0.688 on 80 agent-drafted gold
  paragraphs (run before the dev/test split)
- Sample: all 30 mismatching paragraphs inspected.

| Category | Count | % of failures | Example (id) | Likely cause |
|---|---|---|---|---|
| Risk label(s) where gold is none | 13 | 43% | XOM item_1A:p46 (reputation → cybersecurity, supply_chain) | topic mentioned in passing; some look like batch id confusion (AAPL p24, p55) |
| Extra label, gold labels kept | 10 | 33% | WMT item_1A:p83 (+litigation) | "main topic" rule ignored; litigation/regulatory co-occur |
| Wrong label, no overlap | 4 | 13% | AAPL item_1A:p35 (litigation for single-source components) | id confusion inside a 15-paragraph batch of unrelated text; same paragraph is correct in pipeline batches |
| Missed label | 3 | 10% | WMT item_1A:p43 (IT upgrade → none) | IT-system failure not seen as cybersecurity; JPM p4 bullet list read as none |

**Findings:** precision, not recall, is the problem; part of the error is an artefact of
batching unrelated paragraphs.
**Actions:** on the dev split compare batch sizes 15 / 5 / 1 and an id-echo format; tighten
the "passing mention" rule with an example; human review of the draft gold.

## consistency_checker
_No analysis yet._

## report_generator
_No analysis yet._
