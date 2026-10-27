"""Typed loader for config/settings.yaml and config/companies.yaml.

This is the only place model names, paths and thresholds are read from.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"


class LLMSettings(BaseModel):
    provider: str
    base_url: str
    model: str = Field(min_length=1)
    api_key_env: str
    temperature: float = 0.0
    max_tokens: int = 1024
    reasoning_enabled: bool = False
    seed: int | None = None
    cache_dir: Path


class EdgarSettings(BaseModel):
    user_agent_env: str
    max_requests_per_second: float = Field(gt=0, le=10)
    raw_dir: Path
    tickers_url: str
    submissions_url: str
    companyfacts_url: str
    archives_url: str


class PathSettings(BaseModel):
    raw: Path
    processed: Path
    gold: Path


class FilingSettings(BaseModel):
    items: list[str]


class KPIDefinition(BaseModel):
    name: str
    tags: list[str] = Field(min_length=1)
    taxonomy: str = "us-gaap"
    unit: str = "USD"
    period_type: Literal["duration", "instant"]
    aggregation: Literal["first", "sum"] = "first"


class ConsistencySettings(BaseModel):
    numeric_tolerance: float


class EvalSettings(BaseModel):
    kpi_relative_tolerance: float
    random_seed: int = 42


class TracingSettings(BaseModel):
    backend: Literal["json", "langfuse"] = "json"
    log_dir: Path


class Settings(BaseModel):
    llm: LLMSettings
    edgar: EdgarSettings
    paths: PathSettings
    filing: FilingSettings
    kpis: list[KPIDefinition]
    risk_labels: list[str]
    consistency: ConsistencySettings
    eval: EvalSettings
    tracing: TracingSettings


class Company(BaseModel):
    ticker: str
    name: str
    sector: str
    confirmed: bool = False
    cik: str | None = None  # override for ticker->CIK lookup (D-008)
    notes: str = ""


class CompanyList(BaseModel):
    default_fiscal_year: int
    companies: list[Company]


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=4)
def load_settings(path: Path = CONFIG_DIR / "settings.yaml") -> Settings:
    return Settings.model_validate(_read_yaml(path))


def load_companies(path: Path = CONFIG_DIR / "companies.yaml") -> CompanyList:
    return CompanyList.model_validate(_read_yaml(path))


def resolve_path(path: Path) -> Path:
    """Resolve a config-relative path against the project root."""
    return path if path.is_absolute() else PROJECT_ROOT / path
