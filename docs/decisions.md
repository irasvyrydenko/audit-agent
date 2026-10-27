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

## Open questions
- **total_debt definition:** sum of `LongTermDebtNoncurrent + LongTermDebtCurrent + ShortTermBorrowings`? Include finance leases / commercial paper? Decide after inspecting companyfacts for the 5 companies.
- **Altman Z variant:** original Z needs market value of equity (price data, out of scope) → Z'' (book equity, non-manufacturers) is likely. Decide in indicator_engine.
- **Banks (JPM):** mark Altman Z / Beneish M / DSO as not applicable rather than computing them.
- **Fiscal year matching:** use the 10-K's `reportDate` year, or the companyfacts `fy` field? (They differ for e.g. WMT.)
