"""Strict schemas for temporal entity verification decisions."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


VerificationStatus = Literal[
    "verified_exact_at_date",
    "verified_brand_at_date",
    "verified_historical_alias",
    "anachronistic_name",
    "brand_company_mismatch",
    "conflicting_evidence",
    "insufficient_evidence",
]


class EntityRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: Literal[
        "alias_of", "brand_of", "former_name_of", "renamed_to",
        "acquired_by", "subsidiary_of", "unknown",
    ]
    target_name: str
    valid_from: str | None = None
    valid_to: str | None = None


class TemporalVerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str
    candidate_type: Literal["company", "brand", "manufacturer", "unknown"]
    as_of_date: str
    canonical_name: str | None = None
    verification_status: VerificationStatus
    valid_at_date: bool | None = None
    relations: list[EntityRelation] = Field(default_factory=list, max_length=8)
    evidence_urls: list[str] = Field(default_factory=list, max_length=8)
    reasoning_summary: str = Field(max_length=1000)
    warnings: list[str] = Field(default_factory=list, max_length=8)


VERIFICATION_OUTPUT_SCHEMA = TemporalVerificationDecision.model_json_schema()
