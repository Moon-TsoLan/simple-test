"""Schema, provenance, and arithmetic validation for agent outputs."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .tools import ENTITY_FIELDS, NUMERIC_FIELDS, clean_text, parse_number, source_for_evidence


ENTITY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_service_name": {"type": ["string", "null"]},
                    "category_name": {"type": ["string", "null"]},
                    "category_code": {"type": ["string", "null"]},
                    "brand_supplier": {"type": ["string", "null"]},
                    "spec_model": {"type": ["string", "null"]},
                    "unit_price": {"type": ["number", "null"], "minimum": 0},
                    "quantity": {"type": ["number", "null"], "minimum": 0},
                    "quantity_unit": {"type": ["string", "null"]},
                    "total_price": {"type": ["number", "null"], "minimum": 0},
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "block_id": {"type": "string"},
                                "block_row": {"type": ["integer", "null"], "minimum": 1},
                            },
                            "required": ["block_id", "block_row"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [*ENTITY_FIELDS, "evidence_refs"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["items", "warnings"],
    "additionalProperties": False,
}


@dataclass
class ValidationResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parsed: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return not self.errors


def price_consistency(item: dict[str, Any], tolerance: float = 0.02) -> str:
    unit_price, quantity, total_price = (item.get(name) for name in NUMERIC_FIELDS)
    if unit_price is None or quantity is None or total_price is None:
        return "not_checkable"
    expected = float(unit_price) * float(quantity)
    actual = float(total_price)
    ratio = abs(expected - actual) / max(abs(expected), abs(actual), 1.0)
    return "ok" if ratio <= tolerance else "mismatch"


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_UNCLOSED_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)


def strip_thinking_markup(text: str) -> str:
    """Remove Qwen/LM Studio thinking traces so JSON extraction sees the final answer."""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_UNCLOSED_RE.sub("", cleaned)
    return cleaned.strip()


def parse_json_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = strip_thinking_markup(str(raw or "")).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if len(lines) >= 3 else lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("backend returned non-JSON content")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("backend returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("backend output root must be an object")
    return value


def _allowed_evidence(evidence: dict[str, Any]) -> dict[str, set[int] | None]:
    if evidence.get("kind") == "table":
        block_id = str(evidence.get("block_id") or "")
        return {block_id: {int(row["block_row"]) for row in evidence.get("data_rows") or [] if isinstance(row.get("block_row"), int)}}
    return {str(block.get("block_id") or ""): None for block in evidence.get("blocks") or []}


def validate_output(raw: Any, evidence: dict[str, Any], *, amount_tolerance: float = 0.02) -> ValidationResult:
    result = ValidationResult()
    try:
        data = parse_json_output(raw)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result
    result.parsed = data
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        result.errors.append("items must be an array")
        return result
    raw_warnings = data.get("warnings", [])
    if isinstance(raw_warnings, list):
        result.warnings.extend(str(value) for value in raw_warnings if value is not None)
    else:
        result.warnings.append("backend warnings was not an array and was ignored")

    allowed = _allowed_evidence(evidence)
    table_fields = set(evidence.get("matched_fields") or []) if evidence.get("kind") == "table" else None
    for item_index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            result.errors.append(f"items[{item_index}] is not an object")
            continue
        item: dict[str, Any] = {}
        for field_name in ENTITY_FIELDS:
            value = raw_item.get(field_name)
            if field_name in NUMERIC_FIELDS:
                parsed = parse_number(value)
                if value is not None and parsed is None:
                    result.warnings.append(f"items[{item_index}].{field_name} is invalid and was set to null")
                item[field_name] = parsed
            else:
                item[field_name] = clean_text(value)
        if not item["product_service_name"]:
            result.errors.append(f"items[{item_index}] has no product_service_name")
            continue

        if table_fields is not None:
            derived_fields = set(table_fields)
            if "category_name" in table_fields:
                derived_fields.add("category_code")
            if "quantity" in table_fields:
                derived_fields.add("quantity_unit")
            for field_name in ENTITY_FIELDS:
                if field_name == "product_service_name":
                    continue
                if field_name not in derived_fields and item.get(field_name) is not None:
                    item[field_name] = None
                    result.warnings.append(
                        f"items[{item_index}].{field_name} had no mapped evidence column and was cleared"
                    )

        valid_refs: list[dict[str, Any]] = []
        refs = raw_item.get("evidence_refs")
        if not isinstance(refs, list):
            refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            block_id = str(ref.get("block_id") or "")
            if block_id not in allowed:
                continue
            allowed_rows = allowed[block_id]
            block_row = ref.get("block_row")
            if isinstance(block_row, str) and block_row.isdigit():
                block_row = int(block_row)
            if allowed_rows is not None:
                if not isinstance(block_row, int) or block_row not in allowed_rows:
                    continue
            else:
                block_row = None
            normalized_ref = {"block_id": block_id, "block_row": block_row}
            if normalized_ref not in valid_refs:
                valid_refs.append(normalized_ref)
        if not valid_refs:
            result.errors.append(f"items[{item_index}] has no valid evidence_refs")
            continue

        item["evidence_refs"] = valid_refs
        primary_ref = valid_refs[0]
        source = source_for_evidence(evidence, primary_ref["block_id"])
        item["source_block_id"] = primary_ref["block_id"]
        item["source_block_row"] = primary_ref["block_row"]
        item["source_document_id"] = source.get("document_id")
        item["source_file"] = source.get("file_name")
        item["source_container_path"] = source.get("container_path")
        item["source"] = source
        item["price_consistency"] = price_consistency(item, tolerance=amount_tolerance)
        if item["price_consistency"] == "mismatch":
            result.warnings.append(
                f"items[{item_index}] amount mismatch: unit_price*quantity != total_price"
            )
        result.items.append(item)
    return result
