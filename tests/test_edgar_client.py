import json
from dataclasses import dataclass

import pytest

from audit_agent.common.config import load_settings
from audit_agent.common.edgar_client import EdgarClient, EdgarError

UA = "Test Student test@example.com"


@dataclass
class FakeResponse:
    status_code: int
    content: bytes


class FakeSession:
    def __init__(self, routes: dict[str, list[FakeResponse]]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        return self.routes[url].pop(0)


def ok(payload) -> FakeResponse:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return FakeResponse(200, body)


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR_USER_AGENT", UA)

    def _make(routes):
        session = FakeSession(routes)
        client = EdgarClient(session=session, raw_dir=tmp_path, sleep=lambda s: None)
        return client, session

    return _make


SETTINGS = load_settings().edgar
TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


def test_lookup_cik_sends_user_agent_and_caches(make_client):
    client, session = make_client({SETTINGS.tickers_url: [ok(TICKERS)]})
    assert client.lookup_cik("aapl") == "0000320193"
    assert client.lookup_cik("AAPL") == "0000320193"  # second call served from cache
    assert len(session.calls) == 1
    assert session.calls[0][1]["User-Agent"] == UA


def test_lookup_unknown_ticker(make_client):
    client, _ = make_client({SETTINGS.tickers_url: [ok(TICKERS)]})
    with pytest.raises(EdgarError):
        client.lookup_cik("ZZZZ")


def test_resolve_cik_prefers_companies_yaml_override(make_client):
    client, session = make_client({})
    assert client.resolve_cik("XOM") == "0000034088"  # override set in companies.yaml (D-008)
    assert session.calls == []


def test_retries_on_429_then_succeeds(make_client):
    client, session = make_client(
        {SETTINGS.tickers_url: [FakeResponse(429, b""), FakeResponse(503, b""), ok(TICKERS)]}
    )
    assert client.lookup_cik("AAPL") == "0000320193"
    assert len(session.calls) == 3


def test_no_retry_on_403(make_client):
    client, session = make_client({SETTINGS.tickers_url: [FakeResponse(403, b"")]})
    with pytest.raises(EdgarError, match="403"):
        client.lookup_cik("AAPL")
    assert len(session.calls) == 1


def test_iter_filings_merges_recent_and_older_pages(make_client):
    sub_url = SETTINGS.submissions_url.format(cik="0000320193")
    older_url = sub_url.rsplit("/", 1)[0] + "/CIK0000320193-submissions-001.json"
    submissions = {
        "filings": {
            "recent": {"form": ["10-K", "8-K"], "accessionNumber": ["a1", "a2"]},
            "files": [{"name": "CIK0000320193-submissions-001.json"}],
        }
    }
    older = {"form": ["10-K"], "accessionNumber": ["a0"]}
    client, _ = make_client({sub_url: [ok(submissions)], older_url: [ok(older)]})
    rows = list(client.iter_filings("320193"))
    assert [r["accessionNumber"] for r in rows] == ["a1", "a2", "a0"]
    assert rows[0] == {"form": "10-K", "accessionNumber": "a1"}


def test_download_filing_path_and_url(make_client, tmp_path):
    url = SETTINGS.archives_url.format(
        cik_int="320193", accession_nodash="000032019324000123", document="aapl-20240928.htm"
    )
    client, _ = make_client({url: [ok(b"<html>10-K</html>")]})
    path = client.download_filing("0000320193", "0000320193-24-000123", "aapl-20240928.htm")
    assert path == tmp_path / "filings" / "320193" / "000032019324000123" / "aapl-20240928.htm"
    assert path.read_bytes() == b"<html>10-K</html>"
