"""indicator_engine tests. Replace the stub test with hand-calculated cases for every formula
(growth, margins, leverage, DSO, Altman Z, Beneish M) plus None on missing input / zero
denominator. Inputs are test fixtures, not real company numbers in src/."""

import pytest

from audit_agent.indicator_engine.indicators import growth_rate


def test_stub_not_implemented():
    with pytest.raises(NotImplementedError):
        growth_rate(110.0, 100.0)
