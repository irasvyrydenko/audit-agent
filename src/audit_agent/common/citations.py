"""Citation types shared by all components. Every generated statement must carry >= 1 citation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """Pointer to evidence.

    source_type:
      - "section":  a filing paragraph, ref like "item_7:p12"
      - "xbrl":     an XBRL fact, ref like "us-gaap:NetIncomeLoss@2024-09-28"
      - "computed": an indicator, ref like "indicator:net_margin" (its inputs cite XBRL)
    """

    source_type: Literal["section", "xbrl", "computed"]
    ref: str = Field(min_length=1)
    accession: str | None = None
    quote: str | None = None


class CitedStatement(BaseModel):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
