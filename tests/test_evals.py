import importlib
import json

import pytest

from evals.common import REQUIRED_KEYS

COMPONENTS = [
    "filing_loader",
    "kpi_extractor",
    "indicator_engine",
    "risk_detector",
    "consistency_checker",
    "report_generator",
]


@pytest.mark.parametrize("component", COMPONENTS)
def test_eval_writes_valid_results(component, tmp_path):
    module = importlib.import_module(f"evals.{component}.run_eval")
    assert module.main(results_root=tmp_path) == 0
    record = json.loads((tmp_path / component / "results" / "latest.json").read_text())
    assert record.keys() >= REQUIRED_KEYS
    assert record["component"] == component
