# 10-K Financial Report Analyzer

Course project ("Build an NLP System"). Pick a company and fiscal year; the system downloads
the 10-K from SEC EDGAR, extracts KPIs (XBRL as ground truth), computes financial
indicators, detects risk signals, checks MD&A claims against the numbers, and writes a
short summary where every statement cites its source.

> Analysis tool, not investment advice.

**Status:** skeleton only — all components are stubs. See [docs/architecture.md](docs/architecture.md).

## Setup

Requires Python 3.11+.

```bash
cp .env.example .env        # then fill EDGAR_USER_AGENT and OPENROUTER_API_KEY
make setup                  # creates .venv and installs the package + dev tools
```

On Windows without `make`, call the task runner directly:

```powershell
copy .env.example .env
py scripts/tasks.py setup
```

Every `make <target>` has an equivalent `py scripts/tasks.py <target>`.

## Run

| Command | What |
|---|---|
| `make lint test` | ruff + pytest |
| `make eval` | run all component evals → `evals/<component>/results/latest.json` |
| `make eval C=kpi_extractor` | run one eval |
| `make app` | Streamlit UI *(placeholder — pipeline not implemented)* |
| `make format` | auto-format with ruff |

Usage of the full pipeline: *TBD once components are implemented.*

## Configuration

- `config/settings.yaml` — the single fixed LLM model (OpenRouter), EDGAR rate limit,
  KPI→XBRL tag mapping, risk labels, eval thresholds.
- `config/companies.yaml` — the company set (placeholders, to be confirmed).
- `.env` — `EDGAR_USER_AGENT`, `OPENROUTER_API_KEY` (never committed).

## Data

- `data/raw/` — cached EDGAR downloads (gitignored)
- `data/processed/` — parsed filings, KPI JSON (gitignored)
- `data/cache/` — LLM response cache (gitignored)
- `data/gold/` — hand-labeled evaluation data (committed)

Sources: EDGAR 10-K HTML, XBRL companyfacts API, optionally EDGAR-CORPUS (Hugging Face).

## Docs

- [Architecture](docs/architecture.md) · [CRISP-DM log](docs/crisp_dm.md) ·
  [Decisions](docs/decisions.md) · [Error analysis](docs/error_analysis.md)
- Agent instructions: [AGENTS.md](AGENTS.md)
