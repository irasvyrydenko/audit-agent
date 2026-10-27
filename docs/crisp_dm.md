# CRISP-DM Log

Updated after each work session (see `.claude/skills/crisp-dm-log`). Entries are dated
(YYYY-MM-DD) and tagged with the component, newest last within each phase.

## Component status

| Component | Bus./Data understanding | Built | Eval run | Key metric |
|---|---|---|---|---|
| filing_loader | ✓ 2026-10-27 | ✓ 2026-10-27 | ✓ 2026-10-27 (dev) | segmentation acc. 0.933 (14/15) |
| kpi_extractor | – | – | – | – |
| indicator_engine | – | – | – | – |
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

## 3. Data Preparation

### Log
- 2026-10-27 — filing_loader — Parser: HTML → blocks → Item spans → paragraphs (`item_7:p12`)
  and tables (`item_8:t3`), cached in `data/processed/filings/<TICKER>_<FY>.json`. FY2024
  sizes: Item 1A 47–666 paragraphs, Item 7 96–1324, Item 8 178–1346; 39–276 tables per filing.
- 2026-10-27 — filing_loader — Dev gold `data/gold/filing_loader/*_2024.json`: first/last
  paragraph of Items 1A/7/8 for the 5 companies, drafted from parser output after manual
  inspection of every boundary; JPM 1A end corrected by hand. **Not independent** of the
  parser — a held-out test split (e.g. FY2022, labeled before running) is still needed.

## 4. Modeling

### Log
- _(prompts, baseline config, rules; link decisions.md entries)_

## 5. Evaluation

Record metrics from `evals/<component>/results/latest.json` (commit hash + model) and
what they mean.

### Log
- 2026-10-27 — filing_loader — dev split, 5 filings × 3 Items: segmentation_accuracy 0.9333,
  start 1.0, end 0.9333, per item 1A 0.8 / 7 1.0 / 8 1.0, 0 missing (commit bee95f4+, model
  n/a). Only failure: JPM 1A keeps the running header "Parts I and II" as last paragraph.
  Takeaway: good enough for the demo; next: held-out FY2022 gold. [→ results/latest.json]

## 6. Deployment

Streamlit app (`make app`) with JSON tracing in `logs/`.

### Log
- _(app milestones, demo notes)_
