"""Source and evidence policy for award-entity extraction.

The selector is deliberately recall-oriented, so model requests may still
contain procurement specifications, blank quotation forms, and duplicated
result attachments.  This module provides conservative, deterministic gates
shared by the agent fast path and the notice merger.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


RESULT_SOURCE_TERMS = (
    "分项报价", "报价明细", "报价要求响应", "投标报价", "开标一览",
    "主要标的", "中标清单", "成交清单", "中标结果", "成交结果", "采购结果",
    "评审情况", "响应文件", "投标文件",
)
EXCLUDED_SOURCE_TERMS = (
    "招标文件", "采购文件", "磋商文件", "谈判文件", "询价文件",
    "采购需求", "需求书", "技术需求", "评分办法", "资格预审文件",
)
LOW_VALUE_SOURCE_TERMS = (
    "中小企业声明", "本国产品说明", "授权委托", "资格声明", "承诺函",
)
PROCUREMENT_DRAFT_PATTERNS = (
    "公开招标--", "公开招标-", "竞争性磋商--", "竞争性谈判--",
)
DRAFT_SOURCE_TERMS = ("最终稿", "定稿")
SUMMARY_PRODUCT_PREFIXES = (
    "合计", "总计", "小计", "总价", "投标报价", "报价合计", "总报价",
)
TEMPLATE_ROW_TERMS = (
    "佰拾万仟", "佰拾万", "大写)￥(小写", "大写￥小写",
    "投标人名称(盖章)", "法定代表人(负责人)",
)
REQUIREMENT_TEXT_TERMS = (
    "投标文件中须提供", "投标人须提供", "投标时须提供", "供应商须提供",
    "采购人有权要求", "否则按无效投标", "否则作无效投标",
)
TEMPLATE_TEXT_TERMS = (
    "投标日期:xxxx", "由供应商填写", "严格按照招标文件要求", "此表不作为评审内容",
)
PLACEHOLDER_TERMS = (
    "详见附件", "见附件", "详见公告附件", "详见分项报价", "由供应商填写",
)


def compact(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return "".join(
        normalized
        .lower()
        .replace("（", "(")
        .replace("）", ")")
        .replace("：", ":")
        .split()
    )


def source_text(source: dict[str, Any] | None) -> str:
    source = source or {}
    return f"{source.get('file_name', '')} {source.get('container_path', '')}"


def source_tier(source: dict[str, Any] | None) -> int:
    """Return an ordinal source quality tier (0 excluded, 4 strongest)."""
    source = source or {}
    text = source_text(source)
    file_name = str(source.get("file_name") or "")
    normalized = compact(text)
    normalized_file_name = compact(file_name)
    file_type = str(source.get("file_type") or "").lower()
    has_result_term = any(compact(term) in normalized_file_name for term in RESULT_SOURCE_TERMS)
    has_excluded_term = any(compact(term) in normalized_file_name for term in EXCLUDED_SOURCE_TERMS)
    draft_like = any(compact(term) in normalized_file_name for term in PROCUREMENT_DRAFT_PATTERNS)
    draft_like = draft_like or any(compact(term) in normalized_file_name for term in DRAFT_SOURCE_TERMS)
    if any(compact(term) in normalized_file_name for term in LOW_VALUE_SOURCE_TERMS):
        return 1
    if has_excluded_term or draft_like:
        # A clearly named response/result attachment can legitimately live in
        # a larger archive whose path also contains a procurement-file name.
        return 3 if has_result_term else 0
    if file_type in {"html", "htm"}:
        return 4
    if has_result_term:
        return 4
    return 2


def _table_text(evidence: dict[str, Any]) -> tuple[str, str]:
    header = "|".join(str(cell or "") for cell in evidence.get("header") or [])
    row_text = "|".join(
        str(cell or "")
        for row in evidence.get("data_rows") or []
        for cell in row.get("cells") or []
    )
    return compact(header), compact(row_text)


def evidence_is_non_result(evidence: dict[str, Any]) -> tuple[bool, str | None]:
    """Identify evidence that cannot establish an actual award item."""
    if evidence.get("kind") != "table":
        blocks = list(evidence.get("blocks") or [])
        if blocks and all(source_tier(block.get("source")) == 0 for block in blocks):
            return True, "procurement_source"
        block_text = compact("|".join(str(block.get("text") or "") for block in blocks))
        if any(compact(term) in block_text for term in TEMPLATE_TEXT_TERMS):
            return True, "blank_procurement_form_text"
        return False, None

    if source_tier(evidence.get("source")) == 0:
        return True, "procurement_source"
    header_text, rows_text = _table_text(evidence)
    if any(compact(term) in rows_text for term in REQUIREMENT_TEXT_TERMS):
        return True, "procurement_requirement_text"
    if any(term in header_text for term in ("最高限价", "预算金额", "采购预算")):
        return True, "budget_or_price_ceiling_table"
    if any(compact(term) in rows_text for term in TEMPLATE_ROW_TERMS):
        return True, "blank_quotation_template"

    columns = evidence.get("field_columns") or {}
    product_index = columns.get("product_service_name")
    data_rows = list(evidence.get("data_rows") or [])
    if data_rows and isinstance(product_index, int):
        products: list[str] = []
        placeholder_rows = 0
        for row in data_rows:
            cells = list(row.get("cells") or [])
            product = compact(cells[product_index]) if product_index < len(cells) else ""
            products.append(product)
            placeholder_count = sum(
                any(compact(term) in compact(cell) for term in PLACEHOLDER_TERMS)
                for cell in cells
            )
            if placeholder_count >= 2:
                placeholder_rows += 1
        if products and all(
            not product
            or any(product.startswith(compact(prefix)) for prefix in SUMMARY_PRODUCT_PREFIXES)
            or any(compact(term) in product for term in PLACEHOLDER_TERMS)
            for product in products
        ):
            return True, "no_concrete_product_rows"
        if placeholder_rows == len(data_rows):
            return True, "attachment_placeholder_rows"

    if "技术参数及要求" in header_text and "所属行业" in header_text:
        return True, "procurement_requirement_table"
    return False, None


def evidence_document_ids(evidence: dict[str, Any]) -> set[str]:
    if evidence.get("kind") == "table":
        value = str((evidence.get("source") or {}).get("document_id") or "")
        return {value} if value else set()
    return {
        str((block.get("source") or {}).get("document_id") or "")
        for block in evidence.get("blocks") or []
        if str((block.get("source") or {}).get("document_id") or "")
    }


def infer_excluded_document_ids(requests: list[dict[str, Any]]) -> set[str]:
    """Infer procurement/template documents from any decisive request evidence."""
    excluded: set[str] = set()
    for request in requests:
        messages = (request.get("api_payload") or {}).get("messages") or []
        user_messages = [message for message in messages if message.get("role") == "user"]
        if not user_messages:
            continue
        try:
            import json

            content = user_messages[-1].get("content")
            user_input = content if isinstance(content, dict) else json.loads(str(content or ""))
            evidence = user_input.get("evidence") or {}
        except (TypeError, ValueError):
            continue
        is_non_result, reason = evidence_is_non_result(evidence)
        if not is_non_result or reason == "no_concrete_product_rows":
            continue
        sources = (
            [evidence.get("source") or {}]
            if evidence.get("kind") == "table"
            else [block.get("source") or {} for block in evidence.get("blocks") or []]
        )
        for source in sources:
            document_id = str(source.get("document_id") or "")
            if document_id and source_tier(source) < 4:
                excluded.add(document_id)
    return excluded


def evidence_can_cover_notice(evidence: dict[str, Any]) -> bool:
    """A rule table may suppress later text only when it is result evidence."""
    non_result, _reason = evidence_is_non_result(evidence)
    return not non_result and source_tier(evidence.get("source")) >= 3


def item_is_non_result(item: dict[str, Any]) -> tuple[bool, str | None]:
    if source_tier(item.get("source")) == 0:
        return True, "procurement_source"
    product = compact(item.get("product_service_name"))
    if not product:
        return True, "missing_product_name"
    if any(product.startswith(compact(prefix)) for prefix in SUMMARY_PRODUCT_PREFIXES):
        return True, "summary_or_total_row"
    if any(compact(term) in product for term in TEMPLATE_ROW_TERMS):
        return True, "blank_quotation_template"
    repeated = [
        compact(item.get(field))
        for field in ("product_service_name", "brand_supplier", "spec_model", "quantity_unit")
        if compact(item.get(field))
    ]
    if repeated and max(repeated.count(value) for value in set(repeated)) >= 3:
        return True, "same_template_text_mapped_to_multiple_fields"
    return False, None


def canonical_product_name(value: Any) -> str:
    text = compact(value)
    text = re.sub(r"^[▲■★●◆·•]+", "", text)
    text = re.sub(r"[▲■★●◆·•]", "", text)
    text = re.sub(r"\((?:核心产品|核心标的)\)", "", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text
