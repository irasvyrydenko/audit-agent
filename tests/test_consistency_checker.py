"""consistency_checker tests on fixture KPIs (made-up numbers): verdicts, rounding-aware
tolerance, ratio claims, perturbations, LLM extraction parsing (fake client)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from audit_agent.common.citations import Citation
from audit_agent.common.config import ConsistencySettings
from audit_agent.common.llm_client import LLMRateLimitError
from audit_agent.consistency_checker.checker import (
    Claim,
    half_unit,
    metric_value,
    perturb_claim,
    verify_claim,
)
from audit_agent.consistency_checker.extractor import (
    build_messages,
    extract_claims,
    parse_claims,
    select_candidates,
)
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.kpi_extractor.extractor import KPISet, KPIValue

B = 1e9


def kset(values: dict[str, float], fy: int) -> KPISet:
    end = date(fy, 12, 31)
    return KPISet(
        ticker="T",
        fiscal_year=fy,
        period_end=end,
        accession="acc",
        values={
            k: KPIValue(
                name=k,
                value=v,
                unit="USD",
                period_end=end,
                citations=[Citation(source_type="xbrl", ref=f"us-gaap:{k}@{end}")],
            )
            for k, v in values.items()
        },
    )


CUR = kset({"revenue": 177.556 * B, "net_income": 58.471 * B, "cost_of_revenue": 100 * B}, 2024)
PRIOR = kset({"revenue": 158.104 * B, "net_income": 49.552 * B, "cost_of_revenue": 92 * B}, 2023)


def claim(**kw: Any) -> Claim:
    base = {"id": "c1", "paragraph_id": "item_7:p19", "text": "quote", "metric": "net_income"}
    return Claim(**{**base, **kw})


def verdict(c: Claim) -> str:
    return verify_claim(c, CUR, PRIOR, tolerance=0.005).verdict


# --- tolerance -------------------------------------------------------------------------------


def test_half_unit() -> None:
    assert half_unit("$58.5 billion") == pytest.approx(0.05e9)
    assert half_unit("$812 million") == pytest.approx(0.5e6)
    assert half_unit("18%") == pytest.approx(0.005)
    assert half_unit("4.3 percent") == pytest.approx(0.0005)
    assert half_unit("27 basis points") == pytest.approx(0.5e-4)
    assert half_unit("1.5 percentage points") == pytest.approx(0.0005)
    assert half_unit(None) is None
    assert half_unit("no number") is None


# --- verdicts --------------------------------------------------------------------------------


def test_level_claims_respect_written_precision() -> None:
    assert verdict(claim(kind="level", value=58.5 * B, as_written="$58.5 billion")) == "supported"
    assert (
        verdict(claim(kind="level", value=58.6 * B, as_written="$58.6 billion")) == "contradicted"
    )
    # without wording only the relative tolerance (0.5%) applies
    assert verdict(claim(kind="level", value=58.7 * B)) == "supported"
    assert verdict(claim(kind="level", value=59.0 * B)) == "contradicted"


def test_percent_change_and_direction_sign() -> None:
    up18 = claim(kind="change_pct", value=0.18, direction="up", as_written="18%")
    assert verdict(up18) == "supported"  # computed +18.0%
    assert verdict(up18.model_copy(update={"direction": "down"})) == "contradicted"
    rev = claim(metric="revenue", kind="change_pct", value=0.12, direction="up", as_written="12%")
    assert verdict(rev) == "supported"  # computed 12.3%, within half a percent
    assert verdict(rev.model_copy(update={"as_written": "12.0%"})) == "contradicted"


def test_absolute_change_and_direction_only() -> None:
    change = 58.471 - 49.552
    assert (
        verdict(claim(kind="change_abs", value=8.9 * B, direction="up", as_written="$8.9 billion"))
        == "supported"
    )
    assert verdict(claim(kind="change_abs", value=change * B, direction="down")) == "contradicted"
    assert verdict(claim(kind="direction", direction="up")) == "supported"
    assert verdict(claim(kind="direction", direction="flat")) == "contradicted"
    assert verdict(claim(kind="direction")) == "unverifiable"


def test_ratio_metrics_level_and_pp_change() -> None:
    gm_cur = (177.556 - 100) / 177.556
    gm_prior = (158.104 - 92) / 158.104
    assert metric_value(CUR, "gross_margin") == pytest.approx(gm_cur)
    ok = claim(
        metric="gross_margin",
        kind="level",
        value=round(gm_cur, 3),
        as_written=f"{gm_cur * 100:.1f}%",
    )
    assert verdict(ok) == "supported"
    bp = round((gm_cur - gm_prior) * 1e4)
    pp_claim = claim(
        metric="gross_margin",
        kind="change_pp",
        value=bp * 1e-4,
        direction="up",
        as_written=f"{bp} basis points",
    )
    assert verdict(pp_claim) == ("supported" if gm_cur > gm_prior else "contradicted")


def test_unverifiable_cases() -> None:
    assert verdict(claim(kind="level", value=1.0, scope="segment")) == "unverifiable"
    assert verdict(claim(metric="eps", kind="level", value=19.75)) == "unverifiable"
    assert verdict(claim(metric=None, kind="direction", direction="up")) == "unverifiable"
    assert (
        verdict(claim(kind="change_pct", value=0.1, direction="up", fiscal_year=2023))
        == "unverifiable"
    )
    assert verdict(claim(metric="operating_cash_flow", kind="level", value=1.0)) == "unverifiable"


def test_prior_year_level_and_evidence() -> None:
    result = verify_claim(
        claim(kind="level", value=49.6 * B, as_written="$49.6 billion", fiscal_year=2023),
        CUR,
        PRIOR,
        0.005,
    )
    assert result.verdict == "supported"
    refs = [c.ref for c in result.evidence]
    assert refs[0] == "item_7:p19"
    assert "us-gaap:net_income@2023-12-31" in refs
    assert result.computed == pytest.approx(49.552 * B)


def test_perturbed_claims_become_contradicted() -> None:
    supported = [
        claim(kind="level", value=58.5 * B, as_written="$58.5 billion"),
        claim(kind="change_pct", value=0.18, direction="up", as_written="18%"),
        claim(kind="change_abs", value=8.9 * B, direction="up", as_written="$8.9 billion"),
        claim(kind="direction", direction="up"),
    ]
    for seed in range(5):
        for c in supported:
            assert verdict(c) == "supported"
            perturbed = perturb_claim(c, seed)
            assert perturbed.id != c.id
            assert verdict(perturbed) == "contradicted", (seed, perturbed)


# --- extraction ------------------------------------------------------------------------------

PARAS = [
    Paragraph(id="item_7:p1", item="7", index=1, text="Net income was $58.5 billion, up 18%."),
    Paragraph(id="item_7:p2", item="7", index=2, text="We opened new offices in several cities."),
    Paragraph(id="item_7:p3", item="1A", index=3, text="Net income may fall by 10%."),
    Paragraph(id="item_7:p4", item="7", index=4, text="Total net revenue was $177.6 billion."),
]
SETTINGS = ConsistencySettings(
    numeric_tolerance=0.005, items=["7"], max_candidates=10, batch_size=1
)


def test_select_candidates() -> None:
    assert [p.id for p in select_candidates(PARAS, SETTINGS)] == ["item_7:p1", "item_7:p4"]


def test_build_messages_mentions_year_and_metrics() -> None:
    user = build_messages(PARAS[:1], 2024)[-1]["content"]
    assert "fiscal year 2024" in user and "net_income_incl_nci" in user and "[1] Net income" in user


def test_parse_claims_scales_units_and_drops_bad_quotes() -> None:
    answer = {
        "claims": [
            {
                "paragraph": 1,
                "quote": "Net income was $58.5 billion",
                "metric": "net_income",
                "scope": "company",
                "fiscal_year": 2024,
                "kind": "level",
                "direction": None,
                "number": 58.5,
                "unit": "usd_billion",
            },
            {
                "paragraph": 1,
                "quote": "up 18%",
                "metric": "net_income",
                "scope": "company",
                "fiscal_year": 2024,
                "kind": "change_pct",
                "direction": "up",
                "number": 18,
                "unit": "percent",
            },
            {"paragraph": 1, "quote": "invented sentence", "metric": "net_income", "kind": "level"},
            {"paragraph": 9, "quote": "Net income", "metric": "net_income", "kind": "level"},
            {"paragraph": 1, "quote": "Net income", "metric": "made_up", "kind": "weird"},
        ]
    }
    claims = parse_claims(answer, PARAS[:1], prefix="c")
    assert [c.id for c in claims] == ["c1", "c2", "c3"]
    assert claims[0].value == pytest.approx(58.5e9)
    assert claims[0].as_written == "58.5 billion"
    assert claims[1].value == pytest.approx(0.18) and claims[1].direction == "up"
    assert claims[2].metric is None and claims[2].kind == "direction"
    assert verify_claim(claims[0], CUR, PRIOR, 0.005).verdict == "supported"


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "claims": [
                {"paragraph": 1, "quote": "Net income", "metric": "net_income", "kind": "direction"}
            ]
        }


def test_extract_claims_batches_and_reraises_rate_limit() -> None:
    client = FakeClient()
    claims, failed = extract_claims(PARAS, 2024, client, SETTINGS)  # type: ignore[arg-type]
    assert client.calls == 2 and failed == 0  # batch_size=1; p4 has no "Net income" quote
    assert [c.paragraph_id for c in claims] == ["item_7:p1"]
    with pytest.raises(LLMRateLimitError):
        extract_claims(PARAS, 2024, FakeClient(LLMRateLimitError("quota")), SETTINGS)  # type: ignore[arg-type]


def test_eval_scoring() -> None:
    from evals.consistency_checker.run_eval import score

    rows = [
        {"expected": "supported", "predicted": "supported", "perturbed": False},
        {"expected": "supported", "predicted": "contradicted", "perturbed": False},
        {"expected": "contradicted", "predicted": "contradicted", "perturbed": True},
        {"expected": "unverifiable", "predicted": "unverifiable", "perturbed": False},
    ]
    m = score(rows)
    assert m["verdict_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["perturbed_detection_rate"] == 1.0
    assert m["confusion_matrix"]["supported"]["contradicted"] == 1
    assert m["per_verdict"]["contradicted"]["precision"] == 0.5
