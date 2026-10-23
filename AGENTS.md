# AGENTS.md

Instructions for coding agents (Claude Code, Codex, etc.) working in this repo.

## Goal

Analyze a company's SEC 10-K for a chosen fiscal year: download from EDGAR, extract KPIs
(XBRL = ground truth), compute indicators, detect risk signals, check MD&A claims against
the numbers, and write a short summary where **every statement cites its source**.
It is an analysis tool, not investment advice. Course project, 2-week scope.

## Repo map

| Path | What |
|---|---|
| `src/audit_agent/common/` | config loader, LLM client + disk cache, EDGAR client, JSON tracing, citation types |
| `src/audit_agent/filing_loader/` | EDGAR → 10-K split into Items 1A/7/8 + tables (no LLM) |
| `src/audit_agent/kpi_extractor/` | KPIs as JSON: XBRL ground truth + LLM extraction |
| `src/audit_agent/indicator_engine/` | deterministic ratios, Altman Z, Beneish M, anomaly flags |
| `src/audit_agent/risk_detector/` | paragraph risk labels: LLM vs TF-IDF+LogReg baseline |
| `src/audit_agent/consistency_checker/` | MD&A claims → supported / contradicted / unverifiable |
| `src/audit_agent/report_generator/` | cited summary + faithfulness check |
| `src/audit_agent/app/` | Streamlit UI + pipeline orchestration with tracing |
| `evals/<component>/run_eval.py` | eval script per component; results in `evals/<component>/results/` |
| `evals/common.py` | shared results JSON format (`write_results`) |
| `config/settings.yaml` | model name, EDGAR limits, KPI→XBRL tags, risk labels, thresholds |
| `config/companies.yaml` | company set (placeholders until confirmed) |
| `data/raw/`, `data/processed/` | caches, gitignored. `data/gold/` = hand-labeled eval data, committed |
| `docs/` | `architecture.md`, `crisp_dm.md`, `decisions.md`, `error_analysis.md` |
| `.claude/skills/` | `edgar-fetch`, `add-component-eval`, `error-analysis`, `crisp-dm-log` |

Each component package's `__init__.py` docstring states purpose, input, output, model/tool
use and eval. Keep it accurate when you change the component.

Commands: `make setup`, `make lint test`, `make eval [C=<component>]`, `make app`.
Without make: `py scripts/tasks.py lint test` (Windows) / `python3 scripts/tasks.py ...`.

## Workflow (CRISP-DM, small iterations)

1. **Before building a component:** write its Business Understanding and Data Understanding
   notes in `docs/crisp_dm.md` (what question it answers, what data, known pitfalls).
   Look at real data first (one cached filing / companyfacts file) before writing code.
2. **Build** in small steps: one function + its test at a time. Prefer the simplest
   version that can be evaluated end to end, then improve.
3. **After building:** run its eval (`make eval C=<component>`), record metrics and
   takeaways under Evaluation in `docs/crisp_dm.md`, and log non-obvious choices in
   `docs/decisions.md`. If metrics are weak, run the `error-analysis` skill.
4. Order: filing_loader → kpi_extractor → indicator_engine → risk_detector →
   consistency_checker → report_generator → app.

## Rules

- **No hardcoded financial numbers** in `src/`. Every number comes from XBRL or is computed
  by code from XBRL-backed KPIs. Hand-calculated values belong only in `tests/` fixtures
  and `data/gold/`.
- **Every generated report statement carries ≥1 `Citation`** (filing paragraph id, XBRL tag,
  or computed indicator whose inputs cite XBRL). Uncited statements are bugs.
- **Model name only from `config/settings.yaml` (`llm.model`).** Never pass a model string in
  code. All LLM calls go through `common.llm_client.LLMClient` (disk-cached, temperature 0).
  Changing the model → log in `decisions.md` and re-run all evals.
- **EDGAR only through `common.edgar_client`**: User-Agent from `EDGAR_USER_AGENT`,
  ≤ `edgar.max_requests_per_second`, cache raw downloads in `data/raw/`. See `edgar-fetch` skill.
- **Secrets:** never log, print, commit or hardcode API keys / `.env` values. Tracing
  redacts secret-looking keys; don't work around it.
- **Code style:** type hints everywhere (ruff `ANN` enforced), small single-purpose
  functions, pydantic models for data passed between components, no I/O inside
  `indicator_engine`.
- **A component is not done** without an eval script producing real metrics and tests.
- Run **`make lint test`** before finishing any task; both must pass.

## Evaluation rules

Metrics JSON format: see `evals/common.py` (and the `add-component-eval` skill).
Fixed seed and fixed model; LLM cache makes reruns reproducible.

| Component | Metric |
|---|---|
| filing_loader | segmentation accuracy per Item vs gold boundaries |
| kpi_extractor | exact match within 0.5% vs XBRL; **scale errors (×1e3/×1e6) and sign errors counted separately**; missing rate |
| indicator_engine | unit tests vs hand calculations (every formula, incl. None/zero-denominator cases) |
| risk_detector | per-class precision / recall / F1 + macro F1, **LLM vs TF-IDF+LogReg baseline** on the same test split |
| consistency_checker | verdict accuracy incl. **perturbed-claim tests** (flipped direction / shifted number → contradicted) |
| report_generator | faithfulness rate and citation correctness; uncited statements = 0 |

Never tune on the test split. Report the baseline next to every LLM metric where one exists.

## Definition of done (per task)

- [ ] Code typed, small functions, component docstring still accurate
- [ ] Tests added/updated; `make lint test` passes
- [ ] For component work: eval runs and writes `results/latest.json` with `status: "ok"`
- [ ] `docs/crisp_dm.md` updated (see `crisp-dm-log` skill)
- [ ] Non-obvious choices logged in `docs/decisions.md`
- [ ] No secrets, no hardcoded numbers, no model names outside config

## Decisions log

When you make a non-obvious choice (tag selection rule, threshold, label definition,
prompt format, fallback behaviour, deviation from these rules), add an entry to
`docs/decisions.md`: context, decision, alternatives, consequences.
