"""SEC EDGAR HTTP client. See .claude/skills/edgar-fetch/SKILL.md for the rules.

- User-Agent "Name email" from env var (settings.edgar.user_agent_env); refuse to run without it.
- Rate limited below SEC's 10 req/s.
- Every raw response is cached under data/raw/edgar/ and re-read instead of re-downloaded.
  Cached files never expire: delete them to pick up newly published filings.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

import requests
from dotenv import load_dotenv

from audit_agent.common.config import (
    PROJECT_ROOT,
    EdgarSettings,
    load_companies,
    load_settings,
    resolve_path,
)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30


class MissingUserAgentError(RuntimeError):
    """Raised when the EDGAR User-Agent env var is missing or has no email."""


class EdgarError(RuntimeError):
    """Raised when EDGAR returns an unexpected response or a lookup fails."""


class HttpResponse(Protocol):
    status_code: int
    content: bytes


class HttpSession(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse: ...


def get_user_agent(env_var: str) -> str:
    value = os.getenv(env_var, "").strip().strip('"')
    if not value or "@" not in value:
        raise MissingUserAgentError(
            f"Set {env_var}='Your Name your.email@example.com' in .env (SEC requires it)."
        )
    return value


def format_cik(cik: str | int) -> str:
    """Zero-pad a CIK to the 10 digits used by data.sec.gov URLs."""
    return f"{int(cik):010d}"


class RateLimiter:
    """Enforces a minimum interval between calls (single-threaded)."""

    def __init__(
        self,
        max_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.min_interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now += remaining
        self._last = now


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


class EdgarClient:
    def __init__(
        self,
        settings: EdgarSettings | None = None,
        session: HttpSession | None = None,
        raw_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        load_dotenv(PROJECT_ROOT / ".env")
        self.settings = settings or load_settings().edgar
        self.raw_dir = raw_dir or resolve_path(self.settings.raw_dir)
        self.session: HttpSession = session or requests.Session()
        self.rate_limiter = RateLimiter(self.settings.max_requests_per_second)
        self._sleep = sleep

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": get_user_agent(self.settings.user_agent_env),
            "Accept-Encoding": "gzip, deflate",
        }

    def _download(self, url: str) -> bytes:
        headers = self._headers()
        for attempt in range(MAX_ATTEMPTS):
            self.rate_limiter.wait()
            response = self.session.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
            if response.status_code == 200:
                return response.content
            if response.status_code not in RETRY_STATUSES:
                break
            self._sleep(2**attempt)
        raise EdgarError(f"EDGAR returned HTTP {response.status_code} for {url}")

    def fetch(self, url: str, cache_path: Path) -> bytes:
        """Return the body of `url`, reading/writing the raw cache at `cache_path`."""
        if cache_path.exists():
            return cache_path.read_bytes()
        data = self._download(url)
        _write_atomic(cache_path, data)
        return data

    def fetch_json(self, url: str, cache_path: Path) -> dict[str, Any]:
        return json.loads(self.fetch(url, cache_path))

    def lookup_cik(self, ticker: str) -> str:
        """Ticker -> 10-digit CIK via company_tickers.json (cached)."""
        table = self.fetch_json(self.settings.tickers_url, self.raw_dir / "company_tickers.json")
        wanted = ticker.strip().upper()
        for row in table.values():
            if str(row.get("ticker", "")).upper() == wanted:
                return format_cik(row["cik_str"])
        raise EdgarError(f"Ticker '{ticker}' not found in EDGAR company_tickers.json")

    def resolve_cik(self, ticker: str) -> str:
        """CIK for a ticker: the `cik` override in companies.yaml if set, else lookup_cik."""
        for company in load_companies().companies:
            if company.ticker.upper() == ticker.strip().upper() and company.cik:
                return format_cik(company.cik)
        return self.lookup_cik(ticker)

    def get_submissions(self, cik: str) -> dict[str, Any]:
        """Filing index for a company (data.sec.gov/submissions)."""
        cik10 = format_cik(cik)
        url = self.settings.submissions_url.format(cik=cik10)
        return self.fetch_json(url, self.raw_dir / "submissions" / f"CIK{cik10}.json")

    def iter_filings(self, cik: str) -> Iterator[dict[str, Any]]:
        """All filings (recent + older pages) as one dict per filing."""
        submissions = self.get_submissions(cik)
        yield from _rows(submissions["filings"]["recent"])
        base_url = self.settings.submissions_url.rsplit("/", 1)[0]
        for page in submissions["filings"].get("files", []):
            name = page["name"]
            yield from _rows(
                self.fetch_json(f"{base_url}/{name}", self.raw_dir / "submissions" / name)
            )

    def get_companyfacts(self, cik: str) -> dict[str, Any]:
        """All XBRL facts for a company (data.sec.gov/api/xbrl/companyfacts)."""
        cik10 = format_cik(cik)
        url = self.settings.companyfacts_url.format(cik=cik10)
        return self.fetch_json(url, self.raw_dir / "companyfacts" / f"CIK{cik10}.json")

    def download_filing(self, cik: str, accession: str, document: str) -> Path:
        """Download a filing document from the Archives into the raw cache; return its path."""
        cik_int = str(int(cik))
        accession_nodash = accession.replace("-", "")
        url = self.settings.archives_url.format(
            cik_int=cik_int, accession_nodash=accession_nodash, document=document
        )
        path = self.raw_dir / "filings" / cik_int / accession_nodash / document
        self.fetch(url, path)
        return path


def _rows(columns: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    """Turn EDGAR's column-oriented filing table into row dicts."""
    keys = list(columns)
    for values in zip(*(columns[k] for k in keys), strict=True):
        yield dict(zip(keys, values, strict=True))
