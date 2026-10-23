"""SEC EDGAR HTTP client. See .claude/skills/edgar-fetch/SKILL.md for the rules.

- User-Agent "Name email" from env var (settings.edgar.user_agent_env); refuse to run without it.
- Rate limited below SEC's 10 req/s.
- Every raw response is cached under data/raw/edgar/ and re-read instead of re-downloaded.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audit_agent.common.config import EdgarSettings, load_settings


class MissingUserAgentError(RuntimeError):
    """Raised when the EDGAR User-Agent env var is missing or has no email."""


def get_user_agent(env_var: str) -> str:
    value = os.getenv(env_var, "").strip()
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


class EdgarClient:
    def __init__(self, settings: EdgarSettings | None = None) -> None:
        self.settings = settings or load_settings().edgar
        self.rate_limiter = RateLimiter(self.settings.max_requests_per_second)

    def lookup_cik(self, ticker: str) -> str:
        """Ticker -> 10-digit CIK via company_tickers.json (cached)."""
        raise NotImplementedError

    def get_submissions(self, cik: str) -> dict[str, Any]:
        """Filing index for a company (data.sec.gov/submissions)."""
        raise NotImplementedError

    def get_companyfacts(self, cik: str) -> dict[str, Any]:
        """All XBRL facts for a company (data.sec.gov/api/xbrl/companyfacts)."""
        raise NotImplementedError

    def download_filing(self, cik: str, accession: str, document: str) -> Path:
        """Download a filing document from the Archives into the raw cache; return its path."""
        raise NotImplementedError
