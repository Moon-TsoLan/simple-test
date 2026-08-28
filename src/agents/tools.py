"""Deterministic tools used by the entity extraction agent.

The functions in this module never call a model.  They parse the selected
evidence package, provide a conservative structured-table fast path, and keep
all provenance tied to the original Block rows.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .source_policy import evidence_is_non_result


ENTITY_FIELDS = (
    "product_service_name",
    "category_name",
    "category_code",
    "brand_supplier",
    "spec_model",
    "unit_price",
    "quantity",
    "quantity_unit",
    "total_price",
)
NUMERIC_FIELDS = ("unit_price", "quantity", "total_price")
PLACEHOLDERS = {
    "", "/", "-", "—", "无", "不涉及", "null", "none", "见附件", "详见附件",
    "见附件清单", "详见清单", "详见报价明细", "详见采购文件", "详见招标文件",
    "参数较多详见分项报价明细表", "以附件为准",
}
SUMMARY_TERMS = (
    "合计", "总计", "小计", "总价", "投标报价", "报价合计", "总报价",
    "备注", "废标", "流标",
)
QUANTITY_UNITS = (
    "平方米", "立方米", "人月", "人天", "公里", "千米", "万元", "小时",
    "台", "套", "个", "件", "批", "项", "人", "辆", "册", "只", "支",
    "组", "月", "年", "次", "吨", "米", "份", "包", "箱", "门", "宗",
)
NUMBER_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?")
CATEGORY_CODE_RE = re.compile(r"\b([A-Z]\d{6,8}|\d{6,8})\b", re.IGNORECASE)


def compact(value: Any) -> str:
    return "".join(str(value or "").lower().replace("（", "(").replace("）", ")").split())


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).replace("\u3000", " ").split()).strip(" \t\r\n;；,，、。.：:")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    normalized = compact(text)
    punctuation_free = re.sub(r"[，,。；;：:、]", "", normalized)
    if (
        normalized in PLACEHOLDERS
        or punctuation_free in PLACEHOLDERS
        or normalized.startswith("详见附件")
        or normalized.startswith("见附件")
        or "详见公告附件" in normalized
        or "详见分项报价" in normalized
        or "参数较多详见" in punctuation_free
    ):
        return None
    return text or None


def parse_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number < 0:
            return None
        return int(number) if number.is_integer() else number
    text = re.sub(r"(?<=\d)\s+(?=\d)", "", str(value).strip())
    match = NUMBER_RE.search(text)
    if not match:
        return None
    try:
        number = Decimal(match.group(0).replace(",", "").replace("，", ""))
    except InvalidOperation:
        return None
    if number < 0:
        return None
    if "万元" in text:
        number *= Decimal(10000)
    return int(number) if number == number.to_integral_value() else float(number)


def parse_quantity(value: Any, explicit_unit: Any = None) -> tuple[int | float | None, str | None]:
    quantity = parse_number(value)
    unit = clean_text(explicit_unit)
    text = str(value or "")
    if unit is None and quantity is not None:
        generic = re.search(
            r"\d(?:[\d,.，]*)(?:\.\d+)?\s*\(?\s*([A-Za-z]+\d?|[\u4e00-\u9fff]{1,6})\s*\)?",
            text,
        )
        if generic:
            unit = clean_text(generic.group(1))
    if unit is None and quantity is not None:
        for candidate in QUANTITY_UNITS:
            if re.search(rf"\d(?:[\d,.，]*)(?:\([^)]*\))?\s*{re.escape(candidate)}", text):
                unit = candidate
                break
    return quantity, unit


def split_category(value: Any) -> tuple[str | None, str | None]:
    text = clean_text(value)
    if text is None:
        return None, None
    match = CATEGORY_CODE_RE.search(text)
    if not match:
        return text, None
    code = match.group(1)
    name = clean_text((text[: match.start()] + " " + text[match.end() :]).strip(" -—（）()"))
    return name, code


def normalize_category_code(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    match = CATEGORY_CODE_RE.search(text)
    return match.group(1) if match else None


def parse_request_evidence(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(user_input, evidence)`` from a selector request."""
    messages = (request.get("api_payload") or {}).get("messages") or []
    user_messages = [message for message in messages if message.get("role") == "user"]
    if not user_messages:
        raise ValueError(f"request {request.get('request_id')} has no user message")
    content = user_messages[-1].get("content")
    if isinstance(content, dict):
        user_input = content
    else:
        user_input = json.loads(str(content or ""))
    evidence = user_input.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError(f"request {request.get('request_id')} has no evidence object")
    return user_input, evidence


def can_use_table_fast_path(evidence: dict[str, Any]) -> bool:
    if evidence.get("kind") != "table" or not evidence.get("data_rows"):
        return False
    if evidence_is_non_result(evidence)[0]:
        return False
    fields = set(evidence.get("matched_fields") or [])
    signals = fields & {"brand_supplier", "spec_model", "unit_price", "quantity", "total_price"}
    return "product_service_name" in fields and len(signals) >= 2


def _field_cell(cells: list[Any], columns: dict[str, Any], field: str) -> Any:
    index = columns.get(field)
    if isinstance(index, int) and 0 <= index < len(cells):
        return cells[index]
    return None


def _enrich_columns(evidence: dict[str, Any]) -> dict[str, Any]:
    """Recover obvious columns that the high-recall selector did not map.

    OCR-noisy PDF headers commonly turn ``品牌（如涉及）`` into strings with
    stray digits.  Exact index recovery here remains deterministic and avoids
    losing a clearly labelled brand column.
    """
    columns = dict(evidence.get("field_columns") or {})
    header = list(evidence.get("header") or [])
    used = {value for value in columns.values() if isinstance(value, int)}
    recovery_terms = {
        "brand_supplier": ("品牌", "制造商", "生产厂家"),
        "category_code": ("品目编码", "品目代码"),
        "total_price": ("合计", "小计金额"),
    }
    for field_name, terms in recovery_terms.items():
        if field_name in columns:
            continue
        for index, cell in enumerate(header):
            normalized = compact(cell)
            if index not in used and any(term in normalized for term in terms):
                if field_name == "brand_supplier" and "供应商名称" in normalized:
                    continue
                columns[field_name] = index
                used.add(index)
                break
    # ``采购标的`` is often the repeated project name while an adjacent
    # ``设备名称/货物名称`` column is the real row-level entity.
    specific_product_terms = ("设备名称", "货物名称", "产品名称", "服务名称", "标的名称")
    current_product = columns.get("product_service_name")
    current_header = compact(header[current_product]) if isinstance(current_product, int) and current_product < len(header) else ""
    if "采购标的" in current_header or current_product is None:
        for index, cell in enumerate(header):
            normalized = compact(cell)
            if any(term in normalized for term in specific_product_terms):
                columns["product_service_name"] = index
                break
    evidence["field_columns"] = columns
    evidence["matched_fields"] = sorted(set(evidence.get("matched_fields") or []) | set(columns))
    return columns


def extract_structured_table(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservatively extract rows from a strongly mapped table.

    A row is emitted only when it has a product name plus a genuine product
    attribute or numeric signal.  Section titles and attachment placeholders
    therefore fall through to the model route instead of becoming entities.
    """
    columns = _enrich_columns(evidence)
    block_id = str(evidence.get("block_id") or "")
    output: list[dict[str, Any]] = []
    for row_entry in evidence.get("data_rows") or []:
        cells = list(row_entry.get("cells") or [])
        placeholder_cell_count = sum(
            any(token in compact(cell) for token in ("详见附件", "详见公告附件", "详见分项报价", "参数较多详见"))
            for cell in cells
        )
        if placeholder_cell_count >= 2:
            continue
        product = clean_text(_field_cell(cells, columns, "product_service_name"))
        if product is None or any(term in compact(product) for term in SUMMARY_TERMS):
            continue

        category_name, embedded_code = split_category(_field_cell(cells, columns, "category_name"))
        category_code = normalize_category_code(_field_cell(cells, columns, "category_code")) or embedded_code
        brand = clean_text(_field_cell(cells, columns, "brand_supplier"))
        spec = clean_text(_field_cell(cells, columns, "spec_model"))
        unit_price = parse_number(_field_cell(cells, columns, "unit_price"))
        quantity, quantity_unit = parse_quantity(
            _field_cell(cells, columns, "quantity"),
            _field_cell(cells, columns, "quantity_unit"),
        )
        total_price = parse_number(_field_cell(cells, columns, "total_price"))
        repeated_semantic_values = [
            compact(value)
            for value in (product, brand, spec, quantity_unit)
            if compact(value)
        ]
        if (
            repeated_semantic_values
            and max(repeated_semantic_values.count(value) for value in set(repeated_semantic_values)) >= 3
        ):
            continue
        spec_is_meaningful = bool(spec) and (
            any(token in spec for token in ("型号", "规格", "参数", "配置"))
            or bool(re.search(r"[A-Za-z][A-Za-z0-9_-]{2,}", spec))
        )
        if not any(value is not None for value in (brand, unit_price, quantity, total_price)) and not spec_is_meaningful:
            continue

        output.append({
            "product_service_name": product,
            "category_name": category_name,
            "category_code": category_code,
            "brand_supplier": brand,
            "spec_model": spec,
            "unit_price": unit_price,
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "total_price": total_price,
            "evidence_refs": [{"block_id": block_id, "block_row": row_entry.get("block_row")}],
        })
    return output


def source_for_evidence(evidence: dict[str, Any], block_id: str) -> dict[str, Any]:
    if evidence.get("kind") == "table" and evidence.get("block_id") == block_id:
        return dict(evidence.get("source") or {})
    for block in evidence.get("blocks") or []:
        if block.get("block_id") == block_id:
            return dict(block.get("source") or {})
    return {}
