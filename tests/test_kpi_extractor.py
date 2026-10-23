"""kpi_extractor tests. Replace the stub test with tests on a small companyfacts fixture:
tag fallback order, 10-K/FY filtering, duration vs instant, sum aggregation for total_debt."""

import pytest

from audit_agent.common.config import load_settings
from audit_agent.kpi_extractor.extractor import extract_from_xbrl


def test_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        extract_from_xbrl({}, 2024, load_settings().kpis)
