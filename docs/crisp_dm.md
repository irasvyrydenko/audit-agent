# CRISP-DM Log

Updated after each work session (see `.claude/skills/crisp-dm-log`). Entries are dated
(YYYY-MM-DD) and tagged with the component, newest last within each phase.

## Component status

| Component | Bus./Data understanding | Built | Eval run | Key metric |
|---|---|---|---|---|
| filing_loader | – | – | – | – |
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

## 2. Data Understanding

Sources: EDGAR 10-K HTML (Items 1A, 7, 8), XBRL companyfacts API, optionally EDGAR-CORPUS
(Hugging Face) for extra risk-paragraph training data.

Open questions to answer by inspecting real data:
- How consistent are Item headings across filers (for segmentation)?
- Which XBRL tags does each company actually use per KPI? Fiscal-year vs calendar-year mismatches?
- Label distribution of risk categories (expect heavy imbalance: going concern is rare for large caps).

### Log
- _(per component, before building)_

## 3. Data Preparation

### Log
- _(parsing, cleaning, gold set construction, train/test splits)_

## 4. Modeling

### Log
- _(prompts, baseline config, rules; link decisions.md entries)_

## 5. Evaluation

Record metrics from `evals/<component>/results/latest.json` (commit hash + model) and
what they mean.

### Log
- _(component — metric values — takeaway — next step)_

## 6. Deployment

Streamlit app (`make app`) with JSON tracing in `logs/`.

### Log
- _(app milestones, demo notes)_
