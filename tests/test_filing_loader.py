"""filing_loader tests on small synthetic HTML (no network)."""

from datetime import date

import pytest

from audit_agent.common.edgar_client import EdgarError
from audit_agent.filing_loader.html_blocks import parse_blocks
from audit_agent.filing_loader.loader import Filing, FilingRef, Section, find_10k, split_filing
from audit_agent.filing_loader.segmenter import segment
from evals.filing_loader.run_eval import compare, score

ITEMS = ["1A", "7", "8"]


def para(text: str) -> str:
    return f"<p>{text}</p>"


def body(*parts: str) -> str:
    return "<html><body>" + "".join(parts) + "</body></html>"


TOC = (
    "<table><tr><td>Item 1A.</td><td>Risk Factors</td><td>5</td></tr>"
    "<tr><td>Item 7.</td><td>MD&amp;A</td><td>20</td></tr>"
    "<tr><td>Item 8.</td><td>Financial Statements</td><td>30</td></tr></table>"
)

STANDARD = body(
    TOC,
    para("Item 1. Business"),
    para("We sell things. See <a>Item 1A. Risk Factors</a> for risks."),
    para("Item 1A. Risk Factors"),
    para("Competition could hurt us."),
    para("Acme Corp | 2024 Form 10-K | 7"),
    para("Cyber attacks could hurt us."),
    para("Acme Corp | 2024 Form 10-K | 8"),
    para("Item 1B. Unresolved Staff Comments"),
    para("None."),
    para("Item 7. Management's Discussion and Analysis"),
    para("Revenue grew 8% in 2024."),
    para("Acme Corp | 2024 Form 10-K | 9"),
    "<table><tr><td>Revenue</td><td>1,000</td></tr>"
    "<tr><td>Net income</td><td>100</td></tr></table>",
    para("Item 8. Financial Statements and Supplementary Data"),
    para("The consolidated balance sheets follow."),
    para("Item 9. Changes in and Disagreements with Accountants"),
)


def test_inline_reference_is_not_a_heading():
    texts = [b.text for b in parse_blocks(STANDARD)]
    assert "We sell things. See Item 1A. Risk Factors for risks." in texts


def test_standard_layout_skips_toc_and_strips_footers():
    sections, tables = split_filing(STANDARD, ITEMS)
    assert set(sections) == set(ITEMS)
    risk = [p.text for p in sections["1A"].paragraphs]
    assert risk == ["Competition could hurt us.", "Cyber attacks could hurt us."]
    assert sections["1A"].paragraphs[0].id == "item_1A:p1"
    assert [p.text for p in sections["7"].paragraphs] == ["Revenue grew 8% in 2024."]
    assert tables[0].id == "item_7:t1"
    assert tables[0].rows == [["Revenue", "1,000"], ["Net income", "100"]]


def test_mixed_inline_and_block_content_is_kept():
    mixed = "<div>Loose text <span>here</span><p>Inner.</p></div>"
    html = body(para("Item 1A. Risk Factors"), mixed)
    texts = [b.text for b in parse_blocks(html)]
    assert texts == ["Item 1A. Risk Factors", "Loose text here", "Inner."]


POINTER = body(
    para("Item 1A. Risk Factors"),
    para("Oil prices are volatile."),
    "<table><tr><td>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS</td></tr></table>",
    para("Reference is made to the section entitled MD&amp;A in the Financial Section."),
    para("Item 8. Financial Statements and Supplementary Data"),
    para("Reference is made to the following in the Financial Section of this report."),
    para("Item 9. Changes in and Disagreements with Accountants"),
    para("None."),
    para("FINANCIAL SECTION"),
    para("MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS"),
    para("Earnings rose on higher volumes."),
    para("REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM"),
    para("We have audited the consolidated balance sheets."),
    para("SIGNATURES"),
)


def test_pointer_items_are_resolved_by_title():
    sections, _ = split_filing(POINTER, ITEMS)
    assert sections["7"].resolved_pointer
    assert [p.text for p in sections["7"].paragraphs] == ["Earnings rose on higher volumes."]
    assert [p.text for p in sections["8"].paragraphs] == [
        "We have audited the consolidated balance sheets."
    ]
    assert not sections["1A"].resolved_pointer


def test_segment_orders_items():
    spans = segment(parse_blocks(STANDARD))
    assert [s.item for s in spans] == ["1", "1A", "1B", "7", "8", "9"]


FILINGS = [
    {"form": "10-K", "reportDate": "2024-09-28", "filingDate": "2024-11-01",
     "accessionNumber": "a-2024", "primaryDocument": "x-2024.htm"},
    {"form": "10-K/A", "reportDate": "2024-09-28", "filingDate": "2025-01-10",
     "accessionNumber": "a-2024-amend", "primaryDocument": "x-2024a.htm"},
    {"form": "10-K", "reportDate": "2023-09-30", "filingDate": "2023-11-03",
     "accessionNumber": "a-2023", "primaryDocument": "x-2023.htm"},
    {"form": "8-K", "reportDate": "2024-05-01", "filingDate": "2024-05-02",
     "accessionNumber": "e", "primaryDocument": "e.htm"},
]  # fmt: skip


def test_find_10k_prefers_original_over_amendment():
    ref = find_10k(FILINGS, "0000000001", 2024)
    assert (ref.accession, ref.report_date) == ("a-2024", date(2024, 9, 28))


def test_find_10k_missing_year():
    with pytest.raises(EdgarError):
        find_10k(FILINGS, "0000000001", 2019)


def test_eval_scoring():
    sections, _ = split_filing(STANDARD, ITEMS)
    ref = FilingRef(
        cik="1", accession="a", form="10-K", filing_date=date(2025, 1, 1),
        report_date=date(2024, 12, 31), primary_document="x.htm",
    )  # fmt: skip
    filing = Filing(ticker="ACME", fiscal_year=2024, ref=ref, sections=sections, tables=[])
    filing.sections["8"] = Section(item="8", title="", paragraphs=[])
    gold = {
        "ticker": "ACME",
        "fiscal_year": 2024,
        "items": {
            "1A": {"first": "Competition could hurt us.", "last": "Cyber attacks could hurt us."},
            "7": {"first": "Revenue grew 8% in 2024.", "last": "Wrong last paragraph"},
            "8": {"first": "x", "last": "y"},
        },
    }
    metrics = score(compare(gold, filing))
    assert metrics["segmentation_accuracy"] == pytest.approx(1 / 3, abs=1e-4)
    assert metrics["start_accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["items_missing"] == 1
