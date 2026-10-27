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
    tags: list[str] = Field(min_length=1)  # candidate expressions, tried in order (D-011)
    taxonomy: str = "us-gaap"
    unit: str = "USD"
    period_type: Literal["duration", "instant"]


class AltmanZones(BaseModel):
    distress_below: float
    safe_above: float


class AnomalyThresholds(BaseModel):
    revenue_decline_below: float
    cash_conversion_below: float
    receivables_growth_gap_above: float
    debt_to_equity_above: float
    current_ratio_below: float


class IndicatorSettings(BaseModel):
    days_in_year: int = 365
    altman_z2_zones: AltmanZones
    not_applicable_for_banks: list[str] = []
    anomaly: AnomalyThresholds


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
    indicators: IndicatorSettings
    risk_labels: list[str]
    consistency: ConsistencySettings
    eval: EvalSettings
    tracing: TracingSettings


class Company(BaseModel):
    ticker: str
    name: str
    sector: str
    confirmed: bool = False
    bank: bool = False  # bank-specific "not applicable" indicators (D-012)
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
