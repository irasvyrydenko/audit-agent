"""filing_loader — fetch a 10-K from SEC EDGAR and split it into Items and tables.

Purpose: Locate the 10-K for (ticker, fiscal year), download the primary HTML document,
    and segment it into Item 1A (Risk Factors), Item 7 (MD&A) and Item 8 (Financial
    Statements) with stable paragraph ids, plus extracted tables.
Input: ticker (str), fiscal_year (int).
Output: `Filing` (see loader.py): metadata + sections{item -> paragraphs} + tables;
    cached as JSON in data/processed/.
Calls a model: no.
External tool: yes — SEC EDGAR submissions + Archives (via common.edgar_client).
Eval: evals/filing_loader — segmentation accuracy vs data/gold/filing_loader/.
"""
