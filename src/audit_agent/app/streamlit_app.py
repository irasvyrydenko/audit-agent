"""Streamlit entry point. Run: make app"""

from __future__ import annotations

import streamlit as st

from audit_agent.common.config import load_companies
from audit_agent.report_generator.generator import DISCLAIMER


def main() -> None:
    st.set_page_config(page_title="10-K Analyzer", layout="wide")
    st.title("10-K Financial Report Analyzer")
    st.caption(DISCLAIMER)

    company_list = load_companies()
    tickers = [c.ticker for c in company_list.companies]
    ticker = st.selectbox("Company", tickers)
    fiscal_year = st.number_input(
        "Fiscal year", min_value=2010, max_value=2030, value=company_list.default_fiscal_year
    )

    if st.button("Analyze"):
        st.info(f"Pipeline for {ticker} FY{fiscal_year} is not implemented yet.")


if __name__ == "__main__":
    main()
