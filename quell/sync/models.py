"""Pydantic schemas for the cloud sync payload.

The schema defines exactly what is safe to transmit. Nothing outside these
models may be included in a sync payload.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class WrittenTestMeta(BaseModel):
    """Metadata for a single WRITTEN test — no test body, no source code."""

    name: str
    confidence: int = Field(ge=0, le=100)
    tier: str  # HIGH / MEDIUM / LOW
    file: str
    edge_case_type: str
    spec_source: str


class ScaffoldedMeta(BaseModel):
    """Metadata for a SCAFFOLDED stub."""

    stub_file: str
    reason: str
    age_days: int = Field(ge=0)


class FlaggedMeta(BaseModel):
    """Metadata for a FLAGGED item."""

    location: str  # "src/billing.py:42"
    reason: str
    edge_case_type: str


class EdgeCaseCounts(BaseModel):
    total: int = Field(ge=0)
    written: int = Field(ge=0)
    scaffolded: int = Field(ge=0)
    flagged: int = Field(ge=0)


class SyncPayload(BaseModel):
    """The complete privacy-safe payload pushed to api.quelltest.com/v1/sync.

    Published schema: https://quelltest.com/docs/sync-payload
    This is the canonical definition. The sanitizer enforces it.
    """

    project_id: str  # sha256 of git remote URL (or cwd)
    project_alias: str
    run_at: datetime.datetime
    quell_version: str
    prs: int = Field(ge=0, le=100)
    prs_delta: int  # may be negative
    edge_cases: EdgeCaseCounts
    written_tests: list[WrittenTestMeta] = Field(default_factory=list)
    scaffolded_items: list[ScaffoldedMeta] = Field(default_factory=list)
    flagged_items: list[FlaggedMeta] = Field(default_factory=list)
