import importlib
import json

import pytest

from evals.common import REQUIRED_KEYS

# Evals that still write placeholder results (no data / network needed).
# Implemented evals are tested through their pure score/compare functions instead.
STUB_EVALS = [
    "indicator_engine",
    "risk_detector",
    "consistency_checker",
    "report_generator",
]
ALL_EVALS = ["filing_loader", "kpi_extractor", *STUB_EVALS]


@pytest.mark.parametrize("component", ALL_EVALS)
def test_eval_module_has_main(component):
    module = importlib.import_module(f"evals.{component}.run_eval")
    assert callable(module.main)


@pytest.mark.parametrize("component", STUB_EVALS)
def test_stub_eval_writes_valid_results(component, tmp_path):
    module = importlib.import_module(f"evals.{component}.run_eval")
    assert module.main(results_root=tmp_path) == 0
    record = json.loads((tmp_path / component / "results" / "latest.json").read_text())
    assert record.keys() >= REQUIRED_KEYS
    assert record["component"] == component
