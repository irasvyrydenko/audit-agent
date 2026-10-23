"""risk_detector tests. Replace with: baseline fits/predicts on a toy dataset, LLM output
is parsed and restricted to configured labels (mocked client), deterministic with seed."""

import pytest

from audit_agent.common.config import load_settings
from audit_agent.risk_detector.baseline import TfidfLogRegBaseline


def test_stub_not_implemented():
    model = TfidfLogRegBaseline(load_settings().risk_labels)
    with pytest.raises(NotImplementedError):
        model.fit(["text"], [["litigation"]])
