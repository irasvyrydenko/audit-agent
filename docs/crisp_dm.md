# CRISP-DM Log

Updated after each work session (see `.claude/skills/crisp-dm-log`). Entries are dated
(YYYY-MM-DD) and tagged with the component, newest last within each phase.

## Component status

| Component | Bus./Data understanding | Built | Eval run | Key metric |
|---|---|---|---|---|
| filing_loader | ✓ 2026-10-27 | ✓ 2026-10-27 | ✓ 2026-10-27 (dev) | segmentation acc. 0.933 (14/15) |
| kpi_extractor | ✓ 2026-10-27 | ✓ XBRL part 2026-10-27 | ✓ 2026-10-27 (XBRL checks) | table match 0.987, coverage 0.86 |
| indicator_engine | ✓ 2026-10-27 | ✓ 2026-10-27 (no Beneish) | ✓ 2026-10-27 | hand-calc match 1.0 (22/22) |
| risk_detector | – | – | – | – |
| consistency_checker | – | – | – | – |
| report_generator | – | – | – | – |
| app | – | – | – | – |

## 1. Business Understanding

**Problem.** Reading a 10-K to judge financial health and spot red flags takes hours. The
tool gives a fast, *verifiable* first pass: KPIs, indicators, risk signals, and whether
management's narrative (MD&A) matches the numbers.

**Users.** Students / analysts doing a first screening. Not investment advice.

**Success criteria (project level).**
- KPIs match XBRL within 0.5% for the company set.
- Risk detector LLM beats the TF-IDF baseline on macro F1.
- Consistency checker catches perturbed (false) claims.
- Every report statement is cited and the citation supports it.

**Constraints.** 2 weeks; free OpenRouter models; EDGAR fair-access (≤10 req/s, User-Agent).

### Log
- 2026-10-23 — setup: repo skeleton created; components stubbed.
- 2026-10-27 — setup: company set confirmed (AAPL, JPM, XOM, JNJ, WMT); LLM model fixed. [→ D-005]
  Demo scope agreed: XBRL KPIs + indicators + LLM risks + cited report in Streamlit;
  LLM KPI extraction, TF-IDF baseline and consistency checker follow after the demo.

## 2. Data Understanding

Sources: EDGAR 10-K HTML (Items 1A, 7, 8), XBRL companyfacts API, optionally EDGAR-CORPUS
(Hugging Face) for extra risk-paragraph training data.

Open questions to answer by inspecting real data:
- How consistent are Item headings across filers (for segmentation)?
- Which XBRL tags does each company actually use per KPI? Fiscal-year vs calendar-year mismatches?
- Label distribution of risk categories (expect heavy imbalance: going concern is rare for large caps).

### Log
- 2026-10-27 — infra — EDGAR: AAPL/JPM/JNJ/WMT each have 32–37 10-Ks in submissions;
  latest are FY2025. XOM ticker now points to a new holding entity without 10-Ks → CIK
  override. [→ D-008] Report periods confirm non-calendar years: AAPL 2025-09-27,
  WMT 2026-01-31 (Walmart calls this FY2026). XOM companyfacts: 94 us-gaap tags.
- 2026-10-27 — infra — OpenRouter free models are unstable (chosen model disappeared within
  a day); reasoning output can exhaust max_tokens. [→ D-005a, D-007]
- 2026-10-27 — filing_loader — Business: downstream components need clean Item 1A (risks),
  Item 7 (MD&A claims) and Item 8 (tables) with stable paragraph ids for citations.
  Data: FY2024 10-Ks are 1.5–12.5 MB inline-XBRL HTML. Two layouts: (a) normal Item headings
  (AAPL, JNJ, WMT; XOM headings are layout tables); (b) JPM and XOM Items 7/8 only point to
  an "Annual Report"/"Financial Section" later in the file. Table of contents lists every
  Item first; page headers/footers repeat with changing page numbers. Files are UTF-8.
  [→ D-009, D-010]
- 2026-10-27 — kpi_extractor — Business: indicators and report need FY + prior-year KPIs
  whose every number traces to one XBRL fact. Data: companyfacts for the 5 companies; each
  FY2024 10-K carries 2–3 years of comparatives under its own `accn`. Tag use differs:
  WMT has no `Liabilities` and uses `ReceivablesNetCurrent` / `DepreciationAmortizationAndAccretionNet`;
  JNJ has only equity incl. NCI; XOM debt is `DebtCurrent` + `LongTermDebtAndCapitalLeaseObligations`;
  JNJ `DebtCurrent` (6,000) is a rounded text value, balance sheet shows 5,983. JPM (bank)
  has no cost of revenue, current assets/liabilities, receivables or long-term debt tags.
  Fiscal years: AAPL/WMT 52–53 weeks. [→ D-011]
- 2026-10-27 — indicator_engine — Business: turn KPIs into comparable ratios + red flags the
  report can cite. Data: no market prices → Altman Z'' (book equity). XOM/JNJ have no
  operating income → EBIT = pre-tax income + interest expense. JPM (bank) has no
  current/non-current split and its operating cash flow swings with trading assets. [→ D-012]

## 3. Data Preparation

### Log
- 2026-10-27 — filing_loader — Parser: HTML → blocks → Item spans → paragraphs (`item_7:p12`)
  and tables (`item_8:t3`), cached in `data/processed/filings/<TICKER>_<FY>.json`. FY2024
  sizes: Item 1A 47–666 paragraphs, Item 7 96–1324, Item 8 178–1346; 39–276 tables per filing.
- 2026-10-27 — filing_loader — Dev gold `data/gold/filing_loader/*_2024.json`: first/last
  paragraph of Items 1A/7/8 for the 5 companies, drafted from parser output after manual
  inspection of every boundary; JPM 1A end corrected by hand. **Not independent** of the
  parser — a held-out test split (e.g. FY2022, labeled before running) is still needed.

- 2026-10-27 — kpi_extractor — 19 KPIs as candidate expressions in settings.yaml (tag
  fallbacks, `A - B` for WMT liabilities, optional-sum for current debt, `total_debt =
  current_debt + long_term_debt`). Prior year = same 10-K, period end = FY start − 1 day.

## 4. Modeling

### Log
- 2026-10-27 — indicator_engine — 13 indicators as specs (name, formula, inputs, function)
  and 8 rule-based flags; thresholds in settings.yaml `indicators`; bank not-applicable list.
- _(prompts, baseline config, rules; link decisions.md entries)_

## 5. Evaluation

Record metrics from `evals/<component>/results/latest.json` (commit hash + model) and
what they mean.

### Log
- 2026-10-27 — filing_loader — dev split, 5 filings × 3 Items: segmentation_accuracy 0.9333,
  start 1.0, end 0.9333, per item 1A 0.8 / 7 1.0 / 8 1.0, 0 missing (commit bee95f4+, model
  n/a). Only failure: JPM 1A keeps the running header "Parts I and II" as last paragraph.
  Takeaway: good enough for the demo; next: held-out FY2022 gold. [→ results/latest.json]
- 2026-10-27 — kpi_extractor — XBRL checks on FY2024, 5 companies × 19 KPIs: coverage 0.863
  (misses = concepts the company does not report: JPM bank items, XOM/JNJ operating income),
  Item 8 table match 0.987 (74/75 single-fact KPIs; miss = JNJ current_debt, see D-011),
  cross-filing agreement 1.0 (82 prior-year values equal the FY2023 10-K). LLM-vs-XBRL
  metrics pending. Takeaway: XBRL selection is reliable enough to be ground truth.
- 2026-10-27 — indicator_engine — 34 unit tests (hand calcs, None/zero-denominator, bank,
  flags). Full chain on FY2024: hand-calc match 1.0 (22/22, AAPL + WMT from Item 8 figures,
  drafted by the agent — spot-check pending); coverage 1.0 except gross margin 0.75 and
  operating margin 0.5 (concept not reported); 9 not-applicable (JPM). Flags: low liquidity
  AAPL/WMT, receivables outpace revenue AAPL/XOM.

## 6. Deployment

Streamlit app (`make app`) with JSON tracing in `logs/`.

### Log
- _(app milestones, demo notes)_
