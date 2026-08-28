"""Pydantic contracts for task-2 relation data."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


OrgType = Literal["采购单位", "代理机构", "中标供应商", "投标参与方", "产品供应商", "未知"]
ReviewState = Literal["通过", "不通过", "未知"]
BidResult = Literal["中标", "成交", "未中标", "候选", "未知"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrganizationInput(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    org_type: OrgType = "未知"


class ProductInput(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    category_code: str | None = None
    brand: str | None = None
    spec_model: str | None = None
    supplier: OrganizationInput | None = None


class EvidenceRef(StrictModel):
    block_id: str = Field(min_length=1, max_length=300)
    block_row: int | None = Field(default=None, ge=1)
    supports: list[str] = Field(default_factory=list)


class BidInput(StrictModel):
    org: OrganizationInput
    amount_yuan: float | None = Field(default=None, ge=0)
    quote_value: float | None = Field(default=None, ge=0)
    quote_unit: str | None = Field(default=None, max_length=100)
    quote_text: str | None = Field(default=None, max_length=500)
    score: float | None = None
    rank: int | None = Field(default=None, ge=1)
    qualification: ReviewState = "未知"
    compliance: ReviewState = "未知"
    result: BidResult = "未知"
    evidence_block_id: str | None = None
    evidence_block_row: int | None = Field(default=None, ge=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class PackageInput(StrictModel):
    package_no: str = "默认包"
    name: str | None = None
    bidders: list[BidInput] = Field(default_factory=list)
    products: list[ProductInput] = Field(default_factory=list)

    @field_validator("package_no")
    @classmethod
    def default_blank_package(cls, value: str) -> str:
        return value or "默认包"


class ProjectRelationInput(StrictModel):
    notice_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    project_no: str | None = None
    procurement_method: str | None = None
    publish_date: str | None = None
    source_url: str | None = None
    procurement_unit: OrganizationInput | None = None
    agency: OrganizationInput | None = None
    packages: list[PackageInput] = Field(default_factory=list)
    extraction_method: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
