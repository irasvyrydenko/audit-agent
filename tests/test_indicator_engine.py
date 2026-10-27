"""indicator_engine tests: every formula vs hand calculations, None / zero-denominator cases,
bank "not applicable" handling and anomaly flags. All numbers are made-up fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from audit_agent.common.citations import Citation
from audit_agent.common.config import (
    AltmanZones,
    AnomalyThresholds,
    IndicatorSettings,
    load_settings,
)
from audit_agent.indicator_engine.indicators import (
    altman_z2,
    altman_zone,
    anomaly_flags,
    build_specs,
    cash_conversion,
    compute_all,
    dso,
    gross_margin,
    growth_rate,
    leverage,
    margin,
    safe_div,
)
from audit_agent.kpi_extractor.extractor import KPISet, KPIValue

END = date(2024, 12, 31)
PRIOR_END = date(2023, 12, 31)

SETTINGS = IndicatorSettings(
    days_in_year=365,
    altman_z2_zones=AltmanZones(distress_below=1.1, safe_above=2.6),
    not_applicable_for_banks=["current_ratio", "altman_z2", "negative_operating_cash_flow"],
    anomaly=AnomalyThresholds(
        revenue_decline_below=0.0,
        cash_conversion_below=0.8,
        receivables_growth_gap_above=0.10,
        debt_to_equity_above=2.0,
        current_ratio_below=1.0,
    ),
)


def kset(values: dict[str, float | None], end: date = END, fy: int = 2024) -> KPISet:
    def kv(name: str, value: float | None) -> KPIValue:
        cites = (
            [Citation(source_type="xbrl", ref=f"us-gaap:{name}@{end}")] if value is not None else []
        )
        return KPIValue(name=name, value=value, unit="USD", period_end=end, citations=cites)

    return KPISet(
        ticker="T",
        fiscal_year=fy,
        period_end=end,
        accession="acc",
        values={k: kv(k, v) for k, v in values.items()},
    )


# --- formulas vs hand calculations ----------------------------------------------------------


def test_safe_div() -> None:
    assert safe_div(1, 4) == 0.25
    assert safe_div(1, 0) is None
    assert safe_div(None, 4) is None
    assert safe_div(1, None) is None


def test_growth_rate() -> None:
    assert growth_rate(110, 100) == pytest.approx(0.10)
    assert growth_rate(90, 100) == pytest.approx(-0.10)
    assert growth_rate(-50, -100) == pytest.approx(0.50)  # loss shrank: positive growth
    assert growth_rate(10, 0) is None
    assert growth_rate(None, 100) is None
    assert growth_rate(100, None) is None


def test_margins() -> None:
    assert margin(25, 200) == pytest.approx(0.125)
    assert margin(25, 0) is None
    assert gross_margin(200, 150) == pytest.approx(0.25)
    assert gross_margin(200, None) is None
    assert gross_margin(0, 0) is None


def test_leverage() -> None:
    assert leverage(150, 100) == pytest.approx(1.5)
    assert leverage(150, -10) is None  # negative equity -> meaningless ratio
    assert leverage(150, 0) is None
    assert leverage(None, 100) is None


def test_dso() -> None:
    assert dso(50, 365) == pytest.approx(50.0)
    assert dso(30, 360, days=360) == pytest.approx(30.0)
    assert dso(50, 0) is None
    assert dso(None, 365) is None


def test_cash_conversion() -> None:
    assert cash_conversion(120, 100) == pytest.approx(1.2)
    assert cash_conversion(120, -100) is None
    assert cash_conversion(120, 0) is None


def test_altman_z2_hand_calculation() -> None:
    # TA=1000, CA=400, CL=200, RE=300, EBIT=100, equity=500, TL=500
    # X1=0.2, X2=0.3, X3=0.1, X4=1.0
    # Z'' = 6.56*0.2 + 3.26*0.3 + 6.72*0.1 + 1.05*1.0 = 1.312 + 0.978 + 0.672 + 1.05 = 4.012
    assert altman_z2(400, 200, 300, 100, 1000, 500, 500) == pytest.approx(4.012)


@pytest.mark.parametrize(
    "args",
    [
        (None, 200, 300, 100, 1000, 500, 500),
        (400, 200, 300, None, 1000, 500, 500),
        (400, 200, 300, 100, 0, 500, 500),
        (400, 200, 300, 100, 1000, 500, 0),
    ],
)
def test_altman_z2_none_cases(args: tuple) -> None:
    assert altman_z2(*args) is None


def test_altman_zone() -> None:
    assert altman_zone(0.5, 1.1, 2.6) == "distress"
    assert altman_zone(2.0, 1.1, 2.6) == "grey"
    assert altman_zone(4.0, 1.1, 2.6) == "safe"
    assert altman_zone(None, 1.1, 2.6) is None


# --- compute_all ----------------------------------------------------------------------------

CURRENT = {
    "revenue": 1000.0,
    "cost_of_revenue": 600.0,
    "operating_income": 150.0,
    "net_income": 100.0,
    "operating_cash_flow": 60.0,
    "current_assets": 400.0,
    "current_liabilities": 500.0,
    "total_debt": 900.0,
    "stockholders_equity": 300.0,
    "total_liabilities": 700.0,
    "total_assets": 1000.0,
    "accounts_receivable": 200.0,
    "retained_earnings": 100.0,
    "ebit": 150.0,
}
PRIOR = {
    "revenue": 1100.0,
    "net_income": 80.0,
    "operating_cash_flow": 50.0,
    "accounts_receivable": 160.0,
}


def _by_name(is_bank: bool = False) -> dict:
    inds = compute_all(kset(CURRENT), kset(PRIOR, PRIOR_END, 2023), SETTINGS, is_bank=is_bank)
    return {i.name: i for i in inds}


def test_compute_all_values() -> None:
    ind = _by_name()
    assert ind["revenue_growth"].value == pytest.approx(-100 / 1100)
    assert ind["net_income_growth"].value == pytest.approx(0.25)
    assert ind["gross_margin"].value == pytest.approx(0.4)
    assert ind["operating_margin"].value == pytest.approx(0.15)
    assert ind["net_margin"].value == pytest.approx(0.1)
    assert ind["current_ratio"].value == pytest.approx(0.8)
    assert ind["debt_to_equity"].value == pytest.approx(3.0)
    assert ind["liabilities_to_assets"].value == pytest.approx(0.7)
    assert ind["cash_conversion"].value == pytest.approx(0.6)
    assert ind["dso"].value == pytest.approx(73.0)
    assert ind["accounts_receivable_growth"].value == pytest.approx(0.25)
    # X1=-0.1, X2=0.1, X3=0.15, X4=300/700
    expected_z = 6.56 * -0.1 + 3.26 * 0.1 + 6.72 * 0.15 + 1.05 * 300 / 700
    assert ind["altman_z2"].value == pytest.approx(expected_z)


def test_indicator_citations_and_inputs() -> None:
    nm = _by_name()["net_margin"]
    assert nm.status == "ok"
    assert nm.citation.ref == "indicator:net_margin"
    assert {c.ref for c in nm.citations} == {
        f"us-gaap:net_income@{END}",
        f"us-gaap:revenue@{END}",
    }
    growth = _by_name()["revenue_growth"]
    assert growth.inputs == {"revenue": 1000.0, "revenue@prior": 1100.0}
    assert len(growth.citations) == 2


def test_missing_input_and_no_prior() -> None:
    values = dict(CURRENT, cost_of_revenue=None)
    inds = {i.name: i for i in compute_all(kset(values), None, SETTINGS)}
    assert inds["gross_margin"].status == "missing"
    assert inds["gross_margin"].citations == []
    assert inds["revenue_growth"].status == "missing"
    assert inds["revenue_growth"].inputs["revenue@prior"] is None


def test_bank_not_applicable() -> None:
    ind = _by_name(is_bank=True)
    assert ind["current_ratio"].status == "not_applicable"
    assert ind["current_ratio"].value is None
    assert ind["altman_z2"].status == "not_applicable"
    assert ind["net_margin"].status == "ok"


def test_spec_names_unique_and_config_na_names_exist() -> None:
    names = [s.name for s in build_specs(SETTINGS)]
    assert len(names) == len(set(names))
    flag_names = {
        "revenue_decline",
        "weak_cash_conversion",
        "high_leverage",
        "low_liquidity",
        "altman_distress",
        "receivables_outpace_revenue",
        "negative_equity",
        "negative_operating_cash_flow",
    }
    assert set(load_settings().indicators.not_applicable_for_banks) <= set(names) | flag_names


# --- anomaly flags --------------------------------------------------------------------------


def _flags(values: dict, is_bank: bool = False) -> dict:
    current = kset(values)
    inds = compute_all(current, kset(PRIOR, PRIOR_END, 2023), SETTINGS, is_bank=is_bank)
    return {f.name: f for f in anomaly_flags(current, inds, SETTINGS, is_bank=is_bank)}


def test_anomaly_flags_triggered() -> None:
    flags = _flags(CURRENT)
    assert flags["revenue_decline"].triggered
    assert flags["weak_cash_conversion"].triggered  # 0.6 < 0.8
    assert flags["high_leverage"].triggered  # 3.0 > 2.0
    assert flags["low_liquidity"].triggered  # 0.8 < 1.0
    assert not flags["altman_distress"].triggered  # z ~ 1.13 > 1.1
    assert flags["receivables_outpace_revenue"].triggered  # 25% vs -9.1%
    assert not flags["negative_equity"].triggered
    assert not flags["negative_operating_cash_flow"].triggered


def test_anomaly_flags_cite_indicator_and_facts() -> None:
    flag = _flags(CURRENT)["high_leverage"]
    refs = {c.ref for c in flag.citations}
    assert "indicator:debt_to_equity" in refs
    assert f"us-gaap:total_debt@{END}" in refs


def test_anomaly_flags_omitted_when_missing_or_bank() -> None:
    flags = _flags(dict(CURRENT, current_assets=None, operating_cash_flow=-5.0))
    assert "low_liquidity" not in flags
    assert flags["negative_operating_cash_flow"].triggered
    bank = _flags(dict(CURRENT, operating_cash_flow=-5.0), is_bank=True)
    assert "negative_operating_cash_flow" not in bank
    assert "altman_distress" not in bank
    assert "low_liquidity" not in bank


def test_negative_equity_flag() -> None:
    flags = _flags(dict(CURRENT, stockholders_equity=-10.0))
    assert flags["negative_equity"].triggered
    assert "high_leverage" not in flags  # leverage undefined for negative equity
