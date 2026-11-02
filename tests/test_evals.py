import importlib
import json

import pytest

from evals.common import REQUIRED_KEYS, write_results

# Real evals need cached data / network; they are tested through their pure score/compare
# functions in the component test files. Here: every eval has a main() and the shared
# results format is valid.
ALL_EVALS = [
    "filing_loader",
    "kpi_extractor",
    "indicator_engine",
    "risk_detector",
    "consistency_checker",
    "report_generator",
    "rag_chat",
]


@pytest.mark.parametrize("component", ALL_EVALS)
def test_eval_module_has_main(component):
    module = importlib.import_module(f"evals.{component}.run_eval")
    assert callable(module.main)


def test_write_results_format(tmp_path):
    path = write_results(
        "demo", metrics={"m": 1.0}, dataset={"name": "x", "n": 1}, results_root=tmp_path
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record.keys() >= REQUIRED_KEYS
    assert record["component"] == "demo"
    assert record["status"] == "ok"
    assert len(list(path.parent.glob("*.json"))) == 2  # latest + timestamped copy
