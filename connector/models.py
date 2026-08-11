"""Pydantic schemas used by the connector MCP server.

These mirror quell/sync/models.py but are defined separately so the connector
can be deployed independently without depending on the quelltest library.
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class WrittenTestMeta(BaseModel):
    name: str
    confidence: int = Field(ge=0, le=100)
    tier: str
    file: str
    edge_case_type: str
    spec_source: str


class ScaffoldedMeta(BaseModel):
    stub_file: str
    reason: str
    age_days: int = Field(ge=0)


class FlaggedMeta(BaseModel):
    location: str
    reason: str
    edge_case_type: str


class EdgeCaseCounts(BaseModel):
    total: int
    written: int
    scaffolded: int
    flagged: int


class SyncReport(BaseModel):
    """Full sync payload as stored on the dashboard API."""

    project_id: str
    project_alias: str
    run_at: datetime.datetime
    quell_version: str
    prs: int
    prs_delta: int
    edge_cases: EdgeCaseCounts
    written_tests: list[WrittenTestMeta] = Field(default_factory=list)
    scaffolded_items: list[ScaffoldedMeta] = Field(default_factory=list)
    flagged_items: list[FlaggedMeta] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    id: str
    alias: str
    last_run: datetime.datetime
    prs: int
    prs_tier: str


class PRSHistoryEntry(BaseModel):
    run_at: datetime.datetime
    prs: int
    delta: int


class TokenClaims(BaseModel):
    """Decoded Bearer token claims — produced by validate_token middleware."""

    user_id: str
    email: str
    tier: str  # free | pro | team
    scopes: list[str]
