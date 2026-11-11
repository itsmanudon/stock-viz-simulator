"""The parts of the Aegis read contract v1 that StockViz reads.

Mirrors ``aegis/contracts/feed.py`` in aegis-news (checked at ``f3539f4``).
Unknown fields are ignored: adding an optional field is not a breaking change
under the contract's versioning rule, so the client must not fail on one.
Fields StockViz does not store are left out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class FeedSource(_Lenient):
    source_id: str
    name: str
    kind: str
    url: str | None = None


class FeedDocument(_Lenient):
    document_id: str
    source_id: str
    title: str = Field(min_length=1)
    url: str | None = None
    language: str | None = None
    published_at: AwareDatetime | None = None
    first_seen_at: AwareDatetime
    created_at: AwareDatetime
    available_at: AwareDatetime
    last_signed_at: AwareDatetime
    revision: int = Field(ge=1)


class FeedAnalysis(_Lenient):
    analysis_id: str
    document_id: str
    analysis_type: str
    provider: str
    model_name: str
    model_version: str
    configuration_hash: str
    available_at: AwareDatetime
    outputs: list[dict[str, Any]] = Field(min_length=1)


class FeedEntity(_Lenient):
    entity_id: str
    canonical_name: str
    kind: str
    resolution_analysis_id: str
    confidence: float


class FeedEvent(_Lenient):
    event_id: str
    revision: int = Field(ge=1)
    event_type: str | None = None
    confidence: float | None = None
    occurred_at: AwareDatetime | None = None
    available_at: AwareDatetime
    evidence_kind: str
    analysis_id: str | None = None


class FeedManifest(_Lenient):
    manifest_hash: str
    key_id: str
    signed_at: AwareDatetime


class FeedWithdrawal(_Lenient):
    withdrawn_at: AwareDatetime
    reason: str


class FeedItem(_Lenient):
    document: FeedDocument
    source: FeedSource
    analyses: list[FeedAnalysis] = []
    entities: list[FeedEntity] = []
    events: list[FeedEvent] = []
    manifests: list[FeedManifest] = []
    withdrawal: FeedWithdrawal | None = None


class Pagination(_Lenient):
    has_more: bool
    next_cursor: str | None = None


class FeedPage(_Lenient):
    data: list[FeedItem]
    as_of: AwareDatetime
    pagination: Pagination
    resume_cursor: str = Field(min_length=1)


class AssetMapping(_Lenient):
    mapping_id: str
    entity_id: str
    scheme: Literal["exchange_symbol", "isin", "provider_id"] | str
    identifier: str
    venue: str | None = None
    created_at: datetime


class MappingsPage(_Lenient):
    data: list[AssetMapping]
    pagination: Pagination
