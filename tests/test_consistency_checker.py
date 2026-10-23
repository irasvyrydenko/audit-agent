"""consistency_checker tests. Replace with: supported / contradicted / unverifiable cases on
fixture KPIs, tolerance edges, and perturbed claims flipping to contradicted."""

import pytest

from audit_agent.consistency_checker.checker import Claim, perturb_claim


def test_stub_not_implemented():
    claim = Claim(id="c1", paragraph_id="item_7:p1", text="Revenue grew.", metric="revenue")
    with pytest.raises(NotImplementedError):
        perturb_claim(claim, seed=0)
