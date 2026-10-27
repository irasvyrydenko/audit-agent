# Design Decisions

Format: `D-NNN — title (date)`, then Context / Decision / Alternatives / Consequences.
Add an entry for every non-obvious choice. Never delete entries; mark superseded ones.

## D-001 — Package layout `src/audit_agent/<component>/` (2026-10-23)
- **Context:** spec suggested `src/<component>/`.
- **Decision:** one importable package `audit_agent` with components as subpackages.
- **Alternatives:** top-level packages per component (name clashes, awkward imports).
- **Consequences:** `from audit_agent.kpi_extractor.extractor import KPISet`; editable install via `pip install -e .`.

## D-002 — pip + venv instead of uv (2026-10-23)
- **Context:** uv not installed on the dev machine.
- **Decision:** `pyproject.toml` with pip; `make setup` creates `.venv`.
- **Consequences:** uv still works (`uv pip install -e ".[dev]"`) if adopted later.

## D-003 — Makefile delegates to `scripts/tasks.py` (2026-10-23)
- **Context:** `make` is not available on the Windows dev machine; graders may use Linux.
- **Decision:** all task logic in a Python script; Makefile is a thin wrapper.
- **Consequences:** `py scripts/tasks.py lint test` == `make lint test`.

## D-004 — JSON-lines tracing as default (2026-10-23)
- **Context:** need traces for debugging and the report; Langfuse needs an account/keys.
- **Decision:** `common.tracing.JsonTracer` writes `logs/<run_id>.jsonl`; Langfuse optional (`tracing.backend`).
- **Consequences:** zero setup; secrets redacted by key name.

## D-005 — LLM model: `nvidia/nemotron-3-super-120b-a12b:free` (2026-10-27)
- **Context:** the initial placeholder `meta-llama/llama-3.3-70b-instruct:free` was no longer
  free on OpenRouter (checked via the models API, 17 free models available).
- **Decision:** Nemotron 3 Super 120B (MoE, 12B active): 262k context, structured outputs,
  `seed` support, on OpenRouter since 2026-03 (less likely to disappear).
- **Alternatives:** `google/gemma-4-31b-it:free` (JSON mode, smaller; fallback);
  `nvidia/nemotron-3.5-super-vl:free` (newer, multimodal — not needed). Models without
  JSON output support were excluded.
- **Consequences:** reasoning-capable model — responses may include reasoning tokens, so
  `max_tokens` must leave room for them. Changing the model later requires re-running all evals.

## D-006 — LLM cache key = full request hash (2026-10-23)
- **Decision:** sha256 of canonical JSON (model, messages, temperature, max_tokens, seed, response_format).
- **Consequences:** any prompt/model change is a miss → no stale results; cache is safe to commit-ignore and rebuild.

## D-005a — Model replaced by `nvidia/nemotron-3.5-super-vl:free` (2026-10-27, supersedes D-005)
- **Context:** one day after D-005, `nvidia/nemotron-3-super-120b-a12b:free` returned 404
  ("unavailable for free"). Probed every free JSON-capable model with the same extraction
  prompt: Nemotron 3.5 Super VL answered correctly in ~3 s; `xing4.0` got the scale wrong;
  both Gemma 4 models were rate-limited (429); `dots-3-note` truncated.
- **Decision:** `nvidia/nemotron-3.5-super-vl:free`.
- **Consequences:** free models can vanish at any time. Mitigation: every LLM call is cached
  on disk, so evals and the demo can be replayed from cache. Pre-warm the cache before the demo.

## D-007 — Reasoning disabled for LLM calls (2026-10-27)
- **Context:** with reasoning on, Nemotron 3.5 spent 600–1000+ tokens thinking; one run hit
  `max_tokens=1024` and returned no content. With reasoning off: 0.7 s, 25 tokens.
- **Decision:** `llm.reasoning_enabled: false`, `max_tokens: 2048`. Sent as
  `extra_body.reasoning.enabled` (part of the cache key).
- **Consequences:** without reasoning the model once misread "$391,035 million" as 391035 —
  KPI prompts must state units/scale explicitly; the kpi_extractor eval counts scale errors.
  Can be revisited per eval (would need a re-run).

## D-008 — Optional CIK override in companies.yaml (2026-10-27)
- **Context:** in 2026 the XOM ticker moved to ExxonMobil Holdings Corp (new CIK 0002115436,
  no 10-Ks); all historical 10-Ks are under Exxon Mobil Corp (CIK 0000034088).
- **Decision:** `Company.cik` optional override; `EdgarClient.resolve_cik()` uses it, else the
  ticker lookup. Used only for XOM.
- **Alternatives:** swap XOM for another energy company (loses the confirmed company set).
- **Consequences:** a CIK is an identifier, not a financial number, so the no-hardcoding rule holds.

## D-009 — Fiscal year = calendar year of the 10-K period end (2026-10-27)
- **Context:** non-calendar years: AAPL ends late September, WMT ends Jan 31.
- **Decision:** `fiscal_year_of(reportDate) = reportDate.year`. Matches how all five companies
  name their years (Walmart's year ending 2024-01-31 is "fiscal 2024"). Original 10-K is
  preferred; 10-K/A only if no original exists.
- **Consequences:** breaks for 52/53-week years ending in the first days of January (those
  companies name the year by the previous calendar year) — none in our set.

## D-010 — Item segmentation by heading candidates + pointer resolution (2026-10-27)
- **Context:** inspected the five FY2024 10-Ks. AAPL/JNJ/WMT: Items 1A/7/8 under normal headings
  (XOM puts headings in layout tables). JPM and XOM: Items 7 and 8 are 1–3 line pointers
  ("Reference is made to ... in the Financial Section"); the real MD&A comes later, with the
  title repeated as a running header on every page.
- **Decision:**
  1. Flatten HTML into innermost block elements; inline tags merge into their block, so
     in-sentence references ("see Item 1A") are never heading candidates; small tables
     without numbers count as text (layout).
  2. Per Item (canonical order, each after the previous one), choose the heading candidate
     followed by the longest run before a later Item's candidate → skips the table of contents.
  3. If Item 7 is a pointer (≤250 words + "reference is made"/"financial section"/...),
     Item 7 = first MD&A title block → first "Management's report on internal control" /
     auditor's report / consolidated statements title; Item 8 = from there → "Supplemental
     information" / glossary / exhibits / signatures.
  4. Drop running headers/footers: short texts repeated ≥3 times after masking digits, page
     numbers, one-row tables.
- **Alternatives:** EDGAR-CORPUS (pre-split, but stops at 2020 and we need FY2024); LLM-based
  segmentation (slow, uses free-model quota, harder to evaluate).
- **Consequences:** dev eval 14/15 boundaries (see crisp_dm.md). For pointer filings Item 8
  starts at management's internal-control report rather than the auditor's report (gold uses
  the same convention).

## D-011 — XBRL KPI selection: candidate expressions, borrowings-only debt (2026-10-27)
- **Context:** the 5 companies tag the same KPI differently (see crisp_dm.md Data
  Understanding); some totals are not tagged at all (WMT `Liabilities`); debt lines overlap
  differently (JNJ short-term borrowings already include the current part of long-term debt,
  WMT's do not).
- **Decision:**
  1. Facts only from the chosen 10-K (`accn`), `end` = period end, durations 350–380 days,
     instants without `start`; duplicates → latest `filed`.
  2. Prior year = comparatives in the same 10-K; prior end = FY start − 1 day.
  3. Each KPI lists candidate expressions tried in order (`A`, `A - B`, `A? + B? + C?`,
     KPI references in snake_case). The KPI cites every fact it used.
  4. `total_debt = current_debt + long_term_debt`, borrowings only (no leases);
     `current_debt` = `DebtCurrent`, else `ShortTermBorrowings? + CommercialPaper? +
     LongTermDebtCurrent?`; `long_term_debt` = `LongTermDebtNoncurrent`, else
     `LongTermDebtAndCapitalLeaseObligations`.
  5. WMT total liabilities = `LiabilitiesAndStockholdersEquity −
     StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` (includes
     redeemable NCI, ~0.1%).
- **Alternatives:** fixed per-company tag map (not generic); summing all debt tags (double
  counts JNJ); including leases (inconsistent across filers, ASC 842 operating leases).
- **Consequences:** JNJ current_debt uses a rounded `DebtCurrent` (6,000 vs 5,983, 0.3%).
  JPM has no long-term-debt tag in this scheme → total_debt None (bank; see open question).

## Open questions
- ~~**total_debt definition**~~ → resolved in D-011.
- **Altman Z variant:** original Z needs market value of equity (price data, out of scope) → Z'' (book equity, non-manufacturers) is likely. Decide in indicator_engine.
- **Banks (JPM):** mark Altman Z / Beneish M / DSO as not applicable rather than computing them.
- ~~**Fiscal year matching**~~ → resolved in D-009.
