"""Cross-platform task runner. The Makefile delegates here.

Without make (e.g. Windows), run directly:
    py scripts/tasks.py lint test          # Windows
    python3 scripts/tasks.py lint test     # Linux/macOS

Tasks: setup, lint, format, test, eval, eval:<component>, app
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
COMPONENTS = [
    "filing_loader",
    "kpi_extractor",
    "indicator_engine",
    "risk_detector",
    "consistency_checker",
    "report_generator",
]


def venv_python() -> Path:
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return VENV / sub


def python() -> str:
    """Prefer the project venv; fall back to the interpreter running this script."""
    candidate = venv_python()
    return str(candidate) if candidate.exists() else sys.executable


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def setup() -> None:
    if not venv_python().exists():
        run(sys.executable, "-m", "venv", str(VENV))
    run(python(), "-m", "pip", "install", "--upgrade", "pip")
    run(python(), "-m", "pip", "install", "-e", ".[dev]")


def lint() -> None:
    run(python(), "-m", "ruff", "check", ".")
    run(python(), "-m", "ruff", "format", "--check", ".")


def fmt() -> None:
    run(python(), "-m", "ruff", "format", ".")
    run(python(), "-m", "ruff", "check", "--fix", ".")


def test() -> None:
    run(python(), "-m", "pytest")


def evaluate(component: str | None = None) -> None:
    targets = [component] if component else COMPONENTS
    for name in targets:
        if name not in COMPONENTS:
            sys.exit(f"Unknown component '{name}'. Choose from: {', '.join(COMPONENTS)}")
        run(python(), "-m", f"evals.{name}.run_eval")


def app() -> None:
    run(python(), "-m", "streamlit", "run", "src/audit_agent/app/streamlit_app.py")


TASKS: dict[str, Callable[[], None]] = {
    "setup": setup,
    "lint": lint,
    "format": fmt,
    "test": test,
    "eval": evaluate,
    "app": app,
}


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    for task in argv:
        if task.startswith("eval:"):
            evaluate(task.split(":", 1)[1])
        elif task in TASKS:
            TASKS[task]()
        else:
            sys.exit(f"Unknown task '{task}'.\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
