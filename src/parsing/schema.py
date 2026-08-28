"""Stable JSON-serialisable models used by the parsing pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "1.1"
PARSER_VERSION = "2.1.0"


@dataclass
class Block:
    """One model-ready content unit with evidence provenance."""

    type: str
    text: str
    source: dict[str, Any]
    rows: list[list[str]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    block_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep a compact schema without making consumers handle meaningless nulls.
        if self.rows is None:
            data.pop("rows")
        return data


@dataclass
class DocumentRecord:
    document_id: str
    file_name: str
    container_path: str
    file_type: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str = "ok"
    block_count: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
