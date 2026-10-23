"""filing_loader tests. Replace the stub test with fixture-based tests on a cached 10-K
(tests/fixtures/), e.g. Item boundaries, paragraph ids stable across runs, 10-K vs 10-K/A."""

import pytest

from audit_agent.filing_loader.loader import load_filing


def test_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        load_filing("AAPL", 2024)
