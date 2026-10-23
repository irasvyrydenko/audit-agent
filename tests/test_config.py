from audit_agent.common.config import load_companies, load_settings


def test_settings_load():
    s = load_settings()
    assert s.llm.model
    assert s.llm.temperature == 0.0
    assert s.edgar.max_requests_per_second <= 10
    assert set(s.filing.items) == {"1A", "7", "8"}


def test_required_kpis_defined():
    names = {k.name for k in load_settings().kpis}
    required = {"revenue", "net_income", "operating_cash_flow", "total_debt", "cash"}
    assert required <= names


def test_risk_labels_include_required():
    labels = set(load_settings().risk_labels)
    assert {"going_concern", "litigation", "customer_concentration", "cybersecurity"} <= labels


def test_companies_placeholder_list():
    companies = load_companies().companies
    assert len(companies) == 5
    assert len({c.ticker for c in companies}) == 5
    assert len({c.sector for c in companies}) == 5
