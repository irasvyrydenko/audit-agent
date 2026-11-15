from audit_agent.app.streamlit_app import citation_line, md_escape
from audit_agent.common.citations import Citation

VIEWER = "https://www.sec.gov/ix?doc=/Archives/edgar/data/1/x/doc.htm"


def test_md_escape_stops_latex_between_dollar_amounts():
    assert md_escape("from $97.00B to $93.74B") == "from \\$97.00B to \\$93.74B"


def test_xbrl_and_paragraph_citations_link_to_filing_viewer():
    xbrl = Citation(source_type="xbrl", ref="us-gaap:NetIncomeLoss@2024-09-28", accession="a")
    para = Citation(source_type="section", ref="item_7:p68", quote="totaled $140.8 billion")
    assert f"[`us-gaap:NetIncomeLoss@2024-09-28`]({VIEWER})" in citation_line(xbrl, VIEWER, {})
    line = citation_line(para, VIEWER, {})
    assert f"[`item_7:p68`]({VIEWER})" in line and "\\$140.8" in line


def test_indicator_citation_shows_formula():
    c = Citation(source_type="computed", ref="indicator:net_margin")
    line = citation_line(c, VIEWER, {"indicator:net_margin": "net_income / revenue"})
    assert line == "🧮 `indicator:net_margin` = `net_income / revenue`"
    assert citation_line(c, VIEWER, {}) == "🧮 `indicator:net_margin`"
