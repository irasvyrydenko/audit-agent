"""Shared metric format for all component evals.

Each run writes evals/<component>/results/latest.json and, for real runs (status "ok"),
also a timestamped copy <YYYYmmddTHHMMSSZ>.json to keep history. Schema:

{
  "component": str,
  "timestamp": ISO-8601 UTC,
  "git_commit": str | null,
  "model": str,                 # settings.llm.model at run time
  "status": "ok" | "stub",
  "dataset": {"name": str, "n": int, ...},
  "metrics": {name: float | dict | null},
  "baseline": {name: float | dict | null} | null,
  "notes": str
}
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from audit_agent.common.config import PROJECT_ROOT, load_settings

EVALS_DIR = Path(__file__).resolve().parent
REQUIRED_KEYS = {
    "component",
    "timestamp",
    "git_commit",
    "model",
    "status",
    "dataset",
    "metrics",
    "baseline",
    "notes",
}


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def write_results(
    component: str,
    metrics: dict[str, Any],
    dataset: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    status: Literal["ok", "stub"] = "ok",
    notes: str = "",
    results_root: Path | None = None,
) -> Path:
    """Write results JSON; return the path of latest.json."""
    now = datetime.now(UTC)
    record = {
        "component": component,
        "timestamp": now.isoformat(),
        "git_commit": git_commit(),
        "model": load_settings().llm.model,
        "status": status,
        "dataset": dataset,
        "metrics": metrics,
        "baseline": baseline,
        "notes": notes,
    }
    results_dir = (results_root or EVALS_DIR) / component / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, ensure_ascii=False)
    latest = results_dir / "latest.json"
    latest.write_text(payload, encoding="utf-8")
    if status == "ok":
        (results_dir / f"{now:%Y%m%dT%H%M%SZ}.json").write_text(payload, encoding="utf-8")
    return latest
