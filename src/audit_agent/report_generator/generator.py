"""Cited report: LLM summary over code-built evidence + deterministic faithfulness check (D-014).

- Details = evidence items (built by code, cited by construction).
- Summary = one LLM call; each sentence must reference evidence ids. Sentences with no valid
  id are dropped (never shown uncited). If the LLM is unavailable the report has no summary.
- Faithfulness (no LLM): every citation resolves to an existing paragraph / XBRL fact /
  indicator, and every number in a statement appears in the evidence it cites.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from audit_agent.common.citations import Citation, CitedStatement
from audit_agent.common.llm_client import LLMClient, LLMError, LLMRateLimitError
from audit_agent.filing_loader.loader import Filing
from audit_agent.indicator_engine.indicators import Indicator
from audit_agent.kpi_extractor.extractor import KPISet
from audit_agent.report_generator.evidence import Evidence

DISCLAIMER = "Automated analysis of public filings. Not investment advice."
MAX_SUMMARY_SENTENCES = 5
NUMBER_TOLERANCE = 0.005  # relative, for numbers rounded by the LLM
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

SUMMARY_SYSTEM = (
    "You write short, neutral summaries of a company's 10-K for financial analysts. "
    "You use only the evidence provided and answer with JSON only."
)


class ReportStatement(CitedStatement):
    section: str
    origin: Literal["template", "llm"]
    evidence_ids: list[str] = []


class Report(BaseModel):
    ticker: str
    fiscal_year: int
    statements: list[ReportStatement]
    summary_status: str = "not requested"
    disclaimer: str = DISCLAIMER

    def section(self, name: str) -> list[ReportStatement]:
        return [s for s in self.statements if s.section == name]


class FaithfulnessResult(BaseModel):
    n_statements: int
    n_supported: int
    n_citation_errors: int  # cited ref does not exist / wrong source
    unsupported_ids: list[int]
    reasons: dict[int, str] = {}


# --- summary -------------------------------------------------------------------------------


def build_summary_messages(
    company: str, fiscal_year: int, evidence: list[Evidence]
) -> list[dict[str, str]]:
    lines = "\n".join(f"{e.id} [{e.section}] {e.text}" for e in evidence)
    user = (
        f"Evidence about {company}, fiscal year {fiscal_year}:\n{lines}\n\n"
        f"Write a summary of 3 to {MAX_SUMMARY_SENTENCES} sentences covering performance, "
        "financial health, red flags and the main risk themes.\n"
        "Rules:\n"
        "- Every sentence must cite 1 to 3 evidence ids that support all of its content.\n"
        "- Copy numbers exactly as written in the evidence; do not compute new numbers.\n"
        "- No investment advice, no predictions, no information that is not in the evidence.\n\n"
        'Output format: {"statements": [{"text": "...", "evidence": ["E1", "E4"]}]}'
    )
    return [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": user}]


def parse_summary(answer: Any, evidence: list[Evidence]) -> tuple[list[ReportStatement], int]:
    """Valid summary statements and the number of dropped (uncited / malformed) ones."""
    by_id = {e.id: e for e in evidence}
    raw = answer.get("statements") if isinstance(answer, dict) else None
    if not isinstance(raw, list):
        raise LLMError("summary answer has no 'statements' list")
    statements: list[ReportStatement] = []
    dropped = 0
    for item in raw[:MAX_SUMMARY_SENTENCES]:
        text = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
        ids = item.get("evidence", []) if isinstance(item, dict) else []
        valid = [
            i for i in dict.fromkeys(map(str, ids if isinstance(ids, list) else [])) if i in by_id
        ]
        if not text or not valid:
            dropped += 1
            continue
        citations = _dedupe([c for i in valid for c in by_id[i].citations])
        statements.append(
            ReportStatement(
                text=text, citations=citations, section="summary", origin="llm", evidence_ids=valid
            )
        )
    return statements, dropped


def summarize(
    company: str, fiscal_year: int, evidence: list[Evidence], client: LLMClient
) -> tuple[list[ReportStatement], str]:
    try:
        answer = client.complete_json(build_summary_messages(company, fiscal_year, evidence))
        statements, dropped = parse_summary(answer, evidence)
    except LLMRateLimitError:
        return [], "skipped: LLM daily quota exhausted (details below are unaffected)"
    except LLMError as exc:
        return [], f"skipped: {exc}"[:300]
    return statements, f"ok ({len(statements)} sentences, {dropped} dropped as uncited)"


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: dict[tuple[str, str | None], Citation] = {}
    for c in citations:
        seen.setdefault((c.ref, c.accession), c)
    return list(seen.values())


def generate_report(
    ticker: str,
    fiscal_year: int,
    evidence: list[Evidence],
    client: LLMClient | None = None,
    company_name: str | None = None,
) -> Report:
    """Summary (if a client is given) followed by the evidence details."""
    details = [
        ReportStatement(
            text=e.text,
            citations=e.citations,
            section=e.section,
            origin="template",
            evidence_ids=[e.id],
        )
        for e in evidence
    ]
    summary: list[ReportStatement] = []
    status = "not requested"
    if client is not None and evidence:
        summary, status = summarize(company_name or ticker, fiscal_year, evidence, client)
    return Report(
        ticker=ticker, fiscal_year=fiscal_year, statements=summary + details, summary_status=status
    )


# --- faithfulness --------------------------------------------------------------------------


def numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUMBER.findall(text)]


def number_supported(value: float, allowed: list[float]) -> bool:
    return any(abs(value - a) <= NUMBER_TOLERANCE * max(abs(a), 1.0) for a in allowed)


def known_refs(filing: Filing, kpi_sets: list[KPISet], indicators: list[Indicator]) -> set[str]:
    refs = {p.id for s in filing.sections.values() for p in s.paragraphs}
    refs |= {c.ref for k in kpi_sets for v in k.values.values() for c in v.citations}
    refs |= {i.citation.ref for i in indicators}
    return refs


def check_faithfulness(
    report: Report,
    evidence: list[Evidence],
    filing: Filing,
    kpi_sets: list[KPISet],
    indicators: list[Indicator],
) -> FaithfulnessResult:
    """Deterministic check: citations resolve; numbers come from the cited evidence."""
    refs = known_refs(filing, kpi_sets, indicators)
    by_id = {e.id: e for e in evidence}
    citation_errors = 0
    unsupported: list[int] = []
    reasons: dict[int, str] = {}
    for idx, st in enumerate(report.statements):
        bad = [c.ref for c in st.citations if c.ref not in refs]
        citation_errors += len(bad)
        cited_text = " ".join(by_id[i].text for i in st.evidence_ids if i in by_id)
        allowed = numbers_in(cited_text)
        missing = [n for n in numbers_in(st.text) if not number_supported(n, allowed)]
        if not st.citations or bad or missing:
            unsupported.append(idx)
            reasons[idx] = (
                f"unresolved refs {bad}"
                if bad
                else f"numbers not in evidence {missing}"
                if missing
                else "uncited"
            )
    n = len(report.statements)
    return FaithfulnessResult(
        n_statements=n,
        n_supported=n - len(unsupported),
        n_citation_errors=citation_errors,
        unsupported_ids=unsupported,
        reasons=reasons,
    )
