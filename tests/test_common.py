import json

import pytest
from pydantic import ValidationError

from audit_agent.common.citations import Citation, CitedStatement
from audit_agent.common.edgar_client import (
    MissingUserAgentError,
    RateLimiter,
    format_cik,
    get_user_agent,
)
from audit_agent.common.llm_cache import LLMCache
from audit_agent.common.tracing import REDACTED, JsonTracer, redact


def test_llm_cache_roundtrip(tmp_path):
    cache = LLMCache(tmp_path)
    request = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    assert cache.get(request) is None
    cache.put(request, {"text": "hello"})
    assert cache.get(request) == {"text": "hello"}


def test_llm_cache_key_ignores_dict_order():
    assert LLMCache.make_key({"a": 1, "b": 2}) == LLMCache.make_key({"b": 2, "a": 1})


def test_format_cik():
    assert format_cik(320193) == "0000320193"
    assert format_cik("320193") == "0000320193"


def test_user_agent_required(monkeypatch):
    monkeypatch.delenv("EDGAR_UA_TEST", raising=False)
    with pytest.raises(MissingUserAgentError):
        get_user_agent("EDGAR_UA_TEST")
    monkeypatch.setenv("EDGAR_UA_TEST", "No Email")
    with pytest.raises(MissingUserAgentError):
        get_user_agent("EDGAR_UA_TEST")
    monkeypatch.setenv("EDGAR_UA_TEST", "Student s@example.com")
    assert get_user_agent("EDGAR_UA_TEST") == "Student s@example.com"


def test_rate_limiter_enforces_interval():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(max_per_second=10, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    limiter.wait()
    assert slept == [pytest.approx(0.1)]


def test_redact_secrets():
    clean = redact({"api_key": "x", "nested": {"token": "y"}, "ticker": "AAPL"})
    assert clean == {"api_key": REDACTED, "nested": {"token": REDACTED}, "ticker": "AAPL"}


def test_tracer_writes_jsonl(tmp_path):
    tracer = JsonTracer(tmp_path, run_id="t1")
    with tracer.span("filing_loader", "load", ticker="AAPL"):
        pass
    lines = [json.loads(line) for line in tracer.path.read_text().splitlines()]
    assert [r["event"] for r in lines] == ["load.start", "load.end"]


def test_cited_statement_requires_citation():
    with pytest.raises(ValidationError):
        CitedStatement(text="Revenue grew.", citations=[])
    ok = CitedStatement(
        text="Revenue grew.", citations=[Citation(source_type="xbrl", ref="us-gaap:Revenues")]
    )
    assert ok.citations[0].ref == "us-gaap:Revenues"
