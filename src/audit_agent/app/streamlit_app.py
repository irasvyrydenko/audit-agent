"""Streamlit entry point. Run: make app  (or: py scripts/tasks.py app)"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from pymongo.errors import PyMongoError

from audit_agent.app.pipeline import PipelineResult, run_pipeline
from audit_agent.common.citations import Citation
from audit_agent.common.config import load_companies, load_settings, resolve_path
from audit_agent.common.llm_client import LLMClient, LLMError
from audit_agent.common.tracing import JsonTracer
from audit_agent.rag_chat.agent import ChatAgent, ChatAnswer
from audit_agent.rag_chat.embeddings import FastEmbedder
from audit_agent.rag_chat.indexer import index_company
from audit_agent.rag_chat.retrieval import VectorRetriever
from audit_agent.rag_chat.store import MongoStore
from audit_agent.report_generator.evidence import format_indicator, money
from audit_agent.report_generator.generator import DISCLAIMER, ReportStatement

SECTION_TITLES = {
    "key_figures": "Key figures",
    "profitability": "Profitability",
    "liquidity_leverage": "Liquidity and leverage",
    "solvency": "Solvency",
    "red_flags": "Red flags",
    "risk_themes": "Risk themes (Item 1A)",
    "consistency": "MD&A consistency",
}


def filing_url(result: PipelineResult) -> str:
    ref = result.filing.ref
    return load_settings().edgar.archives_url.format(
        cik_int=int(ref.cik),
        accession_nodash=ref.accession.replace("-", ""),
        document=ref.primary_document,
    )


def citation_line(c: Citation) -> str:
    if c.source_type == "section":
        quote = f' — "{c.quote}"' if c.quote else ""
        return f"📄 `{c.ref}`{quote}"
    if c.source_type == "xbrl":
        return f"🔢 XBRL `{c.ref}` (accession {c.accession})"
    return f"🧮 `{c.ref}`"


def render_statement(st_: ReportStatement) -> None:
    ids = ", ".join(st_.evidence_ids)
    st.markdown(
        f"- {st_.text}  \n  <small>sources: {ids} · {len(st_.citations)} citations</small>",
        unsafe_allow_html=True,
    )
    with st.expander("citations", expanded=False):
        for c in st_.citations:
            st.markdown(citation_line(c))


def render_report(result: PipelineResult) -> None:
    report = result.report
    st.subheader("Summary")
    summary = report.section("summary")
    if summary:
        for s in summary:
            render_statement(s)
    else:
        st.info(f"LLM summary {report.summary_status}.")
    f = result.faithfulness
    st.caption(
        f"Faithfulness check: {f.n_supported}/{f.n_statements} statements supported, "
        f"{f.n_citation_errors} unresolved citations."
    )
    for key, title in SECTION_TITLES.items():
        items = report.section(key)
        if items:
            st.subheader(title)
            for s in items:
                render_statement(s)


def kpi_table(result: PipelineResult) -> pd.DataFrame:
    rows = []
    for name, kpi in result.kpis.values.items():
        prior = result.prior_kpis.values.get(name) if result.prior_kpis else None
        rows.append(
            {
                "KPI": name,
                f"FY{result.kpis.fiscal_year}": money(kpi.value) if kpi.value is not None else "—",
                f"FY{result.kpis.fiscal_year - 1}": money(prior.value)
                if prior and prior.value is not None
                else "—",
                "XBRL expression": kpi.expression or "not reported",
            }
        )
    return pd.DataFrame(rows)


def indicator_table(result: PipelineResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Indicator": i.name,
                "Value": format_indicator(i) if i.value is not None else "—",
                "Status": i.status,
                "Formula": i.formula,
            }
            for i in result.indicators
        ]
    )


def risk_table(result: PipelineResult) -> pd.DataFrame:
    text = (
        {p.id: p.text for p in result.filing.sections["1A"].paragraphs}
        if "1A" in result.filing.sections
        else {}
    )
    return pd.DataFrame(
        [
            {
                "Paragraph": r.paragraph_id,
                "Labels": ", ".join(r.labels),
                "Text": text.get(r.paragraph_id, "")[:300],
            }
            for r in result.risks
        ]
    )


def check_table(result: PipelineResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Paragraph": r.claim.paragraph_id,
                "Claim": r.claim.text,
                "Metric": r.claim.metric or "—",
                "Scope": r.claim.scope,
                "Verdict": r.verdict,
                "Rationale": r.rationale,
            }
            for r in result.checks
        ]
    )


@st.cache_resource
def chat_backend() -> tuple[MongoStore, FastEmbedder]:
    rag = load_settings().rag
    return MongoStore(rag), FastEmbedder(rag)


def render_answer(answer: ChatAnswer) -> None:
    if not answer.statements:
        st.info(f"No cited answer ({answer.status}).")
    for s in answer.statements:
        refs = ", ".join(s.evidence_ids)
        st.markdown(f"- {s.text}  \n  <small>sources: {refs}</small>", unsafe_allow_html=True)
        with st.expander("citations", expanded=False):
            for c in s.citations:
                st.markdown(citation_line(c))
    if answer.plan is not None:
        p = answer.plan
        items = ", ".join(p.items) or "all"
        st.caption(
            f'Plan ({p.source}): search "{p.search_query}" in Items {items}; figures '
            f"{'yes' if p.use_financials else 'no'} · attempts {answer.attempts} · "
            f"{answer.n_dropped} sentences dropped by the check"
        )


def render_chat(result: PipelineResult) -> None:
    """Questions about this 10-K: retrieval from MongoDB + cited answers (rag_chat)."""
    ticker, fy = result.company.ticker, result.filing.fiscal_year
    store, embedder = chat_backend()
    try:
        indexed = store.is_indexed(ticker, fy)
    except PyMongoError:
        st.warning("MongoDB is not reachable. Start it with `docker compose up -d`.")
        return
    if not indexed:
        st.info("This filing is not in the chat index yet.")
        if st.button("Build chat index"):
            with st.spinner("Embedding paragraphs (one-off, up to a few minutes)..."):
                index_company(ticker, fy, store, embedder)
            st.rerun()
        return
    history_key = f"chat_{ticker}_{fy}"
    history: list[ChatAnswer] = st.session_state.setdefault(history_key, [])
    with st.form("ask", clear_on_submit=True):
        question = st.text_input("Ask about this 10-K", placeholder="e.g. What drove margins?")
        asked = st.form_submit_button("Ask")
    if asked and question.strip():
        tracer = JsonTracer(resolve_path(load_settings().tracing.log_dir))
        agent = ChatAgent(
            VectorRetriever(store, embedder), store.financials, LLMClient(), tracer=tracer
        )
        with st.spinner("Searching the filing..."):
            history.insert(0, agent.ask(question, ticker, fy, result.company.name))
    for answer in history:
        st.markdown(f"**Q: {answer.question}**")
        render_answer(answer)
        st.divider()


def render_result(result: PipelineResult) -> None:
    ref = result.filing.ref
    st.header(f"{result.company.name} ({result.company.ticker}) — FY{result.filing.fiscal_year}")
    st.markdown(
        f"10-K for the period ending **{ref.report_date}**, filed {ref.filing_date} · "
        f"accession `{ref.accession}` · [open on EDGAR]({filing_url(result)})"
    )
    tabs = st.tabs(
        ["Report", "Chat", "KPIs", "Indicators & flags", "Risks", "MD&A checks", "Trace"]
    )
    with tabs[0]:
        render_report(result)
    with tabs[1]:
        render_chat(result)
    with tabs[2]:
        st.dataframe(kpi_table(result), hide_index=True, width="stretch")
    with tabs[3]:
        st.dataframe(indicator_table(result), hide_index=True, width="stretch")
        for flag in result.flags:
            icon = "🚩" if flag.triggered else "✅"
            st.markdown(f"{icon} **{flag.name}** — {flag.reason}")
    with tabs[4]:
        st.caption(f"Risk detector status: {result.risk_status}")
        if result.risks:
            counts = pd.Series([lab for r in result.risks for lab in r.labels]).value_counts()
            st.bar_chart(counts)
            st.dataframe(risk_table(result), hide_index=True, width="stretch")
    with tabs[5]:
        st.caption(f"Consistency checker status: {result.check_status}")
        if result.checks:
            st.dataframe(check_table(result), hide_index=True, width="stretch")
    with tabs[6]:
        log_path = resolve_path(load_settings().tracing.log_dir) / f"{result.run_id}.jsonl"
        st.markdown(f"Run id `{result.run_id}` · trace file `{log_path}`")
        if log_path.exists():
            st.code(log_path.read_text(encoding="utf-8"), language="json")


def main() -> None:
    st.set_page_config(page_title="10-K Analyzer", layout="wide")
    st.title("10-K Financial Report Analyzer")
    st.caption(DISCLAIMER)

    company_list = load_companies()
    with st.sidebar:
        ticker = st.selectbox("Company", [c.ticker for c in company_list.companies])
        fiscal_year = int(
            st.number_input(
                "Fiscal year",
                min_value=2010,
                max_value=2030,
                value=company_list.default_fiscal_year,
            )
        )
        summarize = st.checkbox(
            "LLM summary", value=True, help="One cached LLM call per company-year."
        )
        run = st.button("Analyze", type="primary")

    if run:
        tracer = JsonTracer(resolve_path(load_settings().tracing.log_dir))
        with st.spinner("Running pipeline (cached steps are instant)..."):
            try:
                st.session_state["result"] = run_pipeline(
                    ticker, fiscal_year, tracer, summarize=summarize
                )
            except (LLMError, RuntimeError, ValueError, LookupError) as exc:
                st.error(f"Pipeline failed: {exc}")
                return
    result = st.session_state.get("result")
    if result is not None:
        render_result(result)
    else:
        st.info("Pick a company and fiscal year, then press Analyze.")


if __name__ == "__main__":
    main()
