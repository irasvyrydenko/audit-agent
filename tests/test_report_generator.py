"""report_generator tests. Replace with: every statement has >=1 citation that resolves to an
existing paragraph / XBRL tag / indicator; faithfulness check flags a planted false statement."""

from audit_agent.report_generator.generator import DISCLAIMER, Report


def test_report_has_disclaimer():
    report = Report(ticker="AAPL", fiscal_year=2024, statements=[])
    assert report.disclaimer == DISCLAIMER
    assert "not investment advice" in DISCLAIMER.lower()
