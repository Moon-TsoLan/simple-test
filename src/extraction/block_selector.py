# -*- coding: utf-8 -*-
"""Select high-recall evidence from unified Block notices for LLM extraction.

The module is deliberately local and deterministic.  It does not call an API:
it ranks table/text blocks, expands paragraph context, splits oversized tables,
and emits OpenAI-compatible request payloads whose evidence retains the source
``block_id`` and table row number.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

SELECTOR_VERSION = "1.3.0"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "product_service_name": (
        "货物名称", "标的名称", "产品名称", "设备名称", "服务名称", "采购标的",
        "标的物名称", "品名", "分项名称", "清单名称", "报价项目", "服务内容",
        "工程名称", "项目内容", "名称",
    ),
    "category_name": ("品目名称", "品目分类", "采购品目", "品目"),
    "category_code": ("品目编码", "品目代码", "采购品目编码", "品目号"),
    "brand_supplier": ("货物品牌", "产品品牌", "品牌", "制造商", "生产厂家", "厂家"),
    "spec_model": ("规格型号", "货物型号", "产品型号", "技术规格", "型号", "规格", "配置"),
    "unit_price": ("成交单价", "投标单价", "含税单价", "货物单价", "产品单价", "单价"),
    "quantity": ("采购数量", "成交数量", "货物数量", "工程数量", "数量"),
    "quantity_unit": ("计量单位", "货物单位", "单位"),
    "total_price": (
        "成交金额", "中标金额", "投标总价", "货物合价", "合计金额",
        "小计金额", "总价", "合价", "合计", "小计", "金额",
    ),
}

PRODUCT_SIGNAL_FIELDS = {"brand_supplier", "spec_model", "unit_price", "quantity", "total_price"}

# Service and construction result tables often contain no brand, model,
# quantity, or item-level price.  These columns establish that a name column
# belongs to an actual result-detail table rather than a supplier summary.
SERVICE_DETAIL_ALIASES: dict[str, tuple[str, ...]] = {
    "service_scope": ("服务范围", "施工范围"),
    "service_requirements": ("服务要求",),
    "service_time": ("服务时间", "施工工期", "服务期限"),
    "service_standard": ("服务标准",),
    "project_manager": ("项目经理",),
    "certificate": ("执业证书信息", "执业证书"),
}

STRONG_PHRASES = (
    "主要标的信息", "主要成交标的", "中标标的", "成交标的", "分项报价",
    "报价明细", "开标一览", "中标产品", "成交产品", "货物清单", "产品清单",
)
OUTCOME_TERMS = ("中标", "成交", "结果公告", "结果公示", "中选", "报价")
FIELD_TERMS = (
    "货物名称", "标的名称", "产品名称", "服务名称", "品目", "品牌", "制造商",
    "规格型号", "型号", "单价", "数量", "总价", "合价", "金额",
)
SOURCE_BONUS: dict[str, int] = {
    "分项报价": 12, "报价明细": 12, "主要标的": 12, "开标一览": 10,
    "中标": 6, "成交": 6, "结果": 5, "报价": 5, "明细": 5,
    "清单": 4, "公示": 3,
}
NEGATIVE_SOURCE_TERMS = (
    "中小企业声明", "授权委托", "资格声明", "廉洁承诺", "评分办法", "合同模板",
)
TEMPLATE_SOURCE_TERMS = ("招标文件", "采购文件", "磋商文件", "谈判文件", "询价文件")
TEMPLATE_RELIEF_TERMS = ("报价", "明细", "分项", "清单", "成交", "中标", "结果")
TEMPLATE_ROW_TERMS = ("佰拾万仟", "投标报价(大写)", "投标报价(小写)")
BOILERPLATE_TERMS = ("打印", "关闭窗口", "版权所有", "网站标识码", "ICP备案")

MONEY_RE = re.compile(r"(?:人民币|￥|¥)?\s*\d[\d,]*(?:\.\d+)?\s*(?:万元|元)")
QUANTITY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:台|套|个|件|批|项|人|辆|册|只|支|组|月|年|次)")
NUMBER_RE = re.compile(r"\d+(?:[,.]\d+)*")

SYSTEM_PROMPT = """你是政府采购中标/成交公告的标的物信息抽取助手。

请只根据用户消息中的 evidence 提取实际中标或成交的产品/服务条目。概念字段为：产品服务名称、品目、品牌或产品供应商、规格型号、单价、数量、总价。为便于计算，品目拆为 category_name/category_code，数量拆为 quantity/quantity_unit。

必须遵守：
1. 没有原文证据的字段填 null，禁止猜测、补全或使用常识生成。
2. brand_supplier 只填产品品牌、制造商或产品供应商，不得把中标供应商/投标人自动当品牌。
3. 只抽取实际结果；采购需求、最高限价、预算、空白报价模板、评分办法中的项目不要当成中标结果。
4. 跳过合计、总计、小计、备注、废标、流标及纯说明行。
5. 金额统一换算为元；万元乘以10000。数量拆分数值和单位。
6. evidence_refs 必须引用输入中真实存在的 block_id；表格证据还必须填写真实 block_row。
7. 表格的 header 可能通过 header_inherited=true 从前页继承；data_rows 中每一行仍以当前 block_id 和自己的 block_row 为证据。不要把无名称、无价格的跨页说明残片单独当成产品。
8. 只输出一个JSON对象，不要输出解释、Markdown或代码围栏。

输出格式：
{"items":[{"product_service_name":"...","category_name":null,"category_code":null,"brand_supplier":null,"spec_model":null,"unit_price":null,"quantity":null,"quantity_unit":null,"total_price":null,"evidence_refs":[{"block_id":"...","block_row":2}]}],"warnings":[]}
"""


@dataclass(frozen=True)
class SelectorConfig:
    table_min_score: int = 22
    text_min_score: int = 12
    context_window: int = 2
    max_table_rows_per_request: int = 40
    max_input_chars_per_request: int = 9000
    max_text_requests_per_notice: int = 4
    max_table_sources_per_notice: int = 8
    fallback_text_blocks: int = 5
    fallback_text_min_score: int = 4


def _compact(value: Any) -> str:
    return "".join(str(value or "").lower().replace("（", "(").replace("）", ")").split())


def _clean_cell(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _source_text(block: dict[str, Any]) -> str:
    source = block.get("source") or {}
    return f"{source.get('file_name', '')} {source.get('container_path', '')}"


def _source_bonus(block: dict[str, Any]) -> tuple[int, list[str]]:
    source_text = _source_text(block)
    score = 0
    reasons: list[str] = []
    matched_source_terms: list[str] = []
    for term, points in sorted(SOURCE_BONUS.items(), key=lambda item: len(item[0]), reverse=True):
        if term in source_text:
            # Do not count both “分项报价” and its substring “报价”.
            if any(term in longer for longer in matched_source_terms):
                continue
            score += points
            reasons.append(f"source:{term}")
            matched_source_terms.append(term)
    if any(term in source_text for term in NEGATIVE_SOURCE_TERMS):
        score -= 18
        reasons.append("source:declaration_or_template")
    if any(term in source_text for term in TEMPLATE_SOURCE_TERMS):
        penalty = 5 if any(term in source_text for term in TEMPLATE_RELIEF_TERMS) else 25
        score -= penalty
        reasons.append("source:procurement_template")
    return score, reasons


def _cell_matches(field: str, cell: Any) -> bool:
    text = _compact(cell)
    if not text:
        return False
    if field == "product_service_name" and any(token in text for token in ("供应商", "投标人", "采购人")):
        return False
    if field == "brand_supplier" and "供应商名称" in text:
        return False
    for alias in FIELD_ALIASES[field]:
        candidate = _compact(alias)
        if text == candidate:
            return True
        if len(candidate) >= 3 and candidate in text:
            return True
    if field == "category_code":
        return "品目" in text and ("编码" in text or "代码" in text)
    if field == "spec_model":
        return "规格" in text or "型号" in text
    if field == "unit_price":
        return "单价" in text and "总" not in text
    if field == "quantity":
        return "数量" in text and "金额" not in text and "单价" not in text
    if field == "total_price":
        return "总价" in text or "合价" in text or ("金额" in text and "单价" not in text)
    return False


def match_header_fields(row: Iterable[Any]) -> dict[str, int]:
    cells = list(row)
    mapped: dict[str, int] = {}
    used: set[int] = set()
    for field in FIELD_ALIASES:
        exact_hits = [
            index for index, cell in enumerate(cells)
            if index not in used and _compact(cell) in {_compact(alias) for alias in FIELD_ALIASES[field]}
        ]
        hits = exact_hits or [
            index for index, cell in enumerate(cells)
            if index not in used and _cell_matches(field, cell)
        ]
        if hits:
            mapped[field] = hits[0]
            used.add(hits[0])
    return mapped


def match_service_detail_fields(row: Iterable[Any]) -> dict[str, int]:
    cells = list(row)
    mapped: dict[str, int] = {}
    for field, aliases in SERVICE_DETAIL_ALIASES.items():
        for index, cell in enumerate(cells):
            text = _compact(cell)
            if any(text == _compact(alias) or _compact(alias) in text for alias in aliases):
                mapped[field] = index
                break
    return mapped


def _meaningful_rows(
    rows: list[list[Any]],
    header_idx: int | None,
    header: list[str] | None = None,
) -> list[tuple[int, list[str]]]:
    header_cells = header if header is not None else (
        [_clean_cell(cell) for cell in rows[header_idx]] if rows and header_idx is not None else []
    )
    header_norm = _compact("|".join(header_cells))
    output: list[tuple[int, list[str]]] = []
    start = header_idx + 1 if header_idx is not None else 0
    for index in range(start, len(rows)):
        cells = [_clean_cell(cell) for cell in rows[index]]
        joined = "|".join(cells)
        compact = _compact(joined)
        if not compact or compact == header_norm:
            continue
        output.append((index + 1, cells))
    return output


def _best_local_header(rows: list[list[Any]]) -> tuple[int, dict[str, int], list[str]]:
    best_idx = 0
    best_fields: dict[str, int] = {}
    for index in range(min(12, len(rows))):
        fields = match_header_fields(rows[index])
        if len(fields) > len(best_fields):
            best_idx, best_fields = index, fields
    header = [_clean_cell(cell) for cell in rows[best_idx]] if rows else []
    return best_idx, best_fields, header


def _is_strong_header(fields: dict[str, int], service_details: dict[str, int]) -> bool:
    return "product_service_name" in fields and bool(
        (set(fields) & PRODUCT_SIGNAL_FIELDS) or service_details
    )


def score_table(block: dict[str, Any], inherited_header: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = block.get("rows") or []
    if len(rows) < 2:
        return None
    local_idx, local_fields, local_header = _best_local_header(rows)
    local_service_details = match_service_detail_fields(local_header)
    header_text = _compact("|".join(local_header))
    supplier_identity_table = any(token in header_text for token in ("供应商名称", "中标供应商", "成交供应商", "投标人名称"))
    if supplier_identity_table and not (
        {"brand_supplier", "spec_model", "unit_price", "quantity"} & set(local_fields)
        or local_service_details
    ):
        return None

    strong_local_header = _is_strong_header(local_fields, local_service_details)
    use_inherited = bool(inherited_header) and not strong_local_header
    if use_inherited:
        best_idx: int | None = None
        best_fields = dict(inherited_header.get("field_columns") or {})
        best_service_details = dict(inherited_header.get("service_detail_columns") or {})
        header = list(inherited_header.get("header") or [])
        data_rows = _meaningful_rows(rows, None, header)
        header_block_row = inherited_header.get("header_block_row")
        header_source_block_id = inherited_header.get("header_source_block_id")
        header_source = inherited_header.get("header_source") or {}
    else:
        best_idx = local_idx
        best_fields = local_fields
        best_service_details = local_service_details
        header = local_header
        data_rows = _meaningful_rows(rows, best_idx, header)
        header_block_row = best_idx + 1
        header_source_block_id = block.get("block_id")
        header_source = block.get("source") or {}
    if not data_rows:
        return None
    normalized_data_text = _compact("|".join(cell for _row, cells in data_rows for cell in cells))
    if any(_compact(term) in normalized_data_text for term in TEMPLATE_ROW_TERMS):
        return None

    source_score, reasons = _source_bonus(block)
    if use_inherited:
        reasons.append("table:inherited_header")
    text = str(block.get("text") or "")
    strong_hits = [term for term in STRONG_PHRASES if term in text]
    signal_columns = [best_fields[field] for field in PRODUCT_SIGNAL_FIELDS if field in best_fields]
    signal_columns.extend(best_service_details.values())
    signal_columns = list(dict.fromkeys(signal_columns))

    def signal_values(cells: list[str]) -> list[str]:
        values = [cells[index].strip() for index in signal_columns if index < len(cells)]
        return [value for value in values if value and _compact(value) not in {"/", "-", "—", "详见采购文件", "详见附件"}]

    filled_signal_rows = sum(bool(signal_values(cells)) for _, cells in data_rows)
    numeric_rows = sum(bool(NUMBER_RE.search("|".join(signal_values(cells)))) for _, cells in data_rows)
    money_rows = sum(bool(MONEY_RE.search("|".join(cells))) for _, cells in data_rows)
    product_signals = set(best_fields) & PRODUCT_SIGNAL_FIELDS
    service_result = "product_service_name" in best_fields and bool(best_service_details)
    structured = "product_service_name" in best_fields and bool(product_signals or service_result)

    score = 2 + source_score + len(best_fields) * 4
    if structured:
        score += 10
        reasons.append("table:product_header")
    if service_result:
        score += min(10, 4 + 2 * len(best_service_details))
        reasons.append("table:service_result_header")
    if len(product_signals) >= 2:
        score += 7
        reasons.append("table:multi_field_header")
    if numeric_rows:
        score += min(6, 2 + numeric_rows // 3)
        reasons.append("table:numeric_rows")
    if money_rows:
        score += 4
        reasons.append("table:money_rows")
    if strong_hits:
        score += min(12, 6 * len(strong_hits))
        reasons.extend(f"phrase:{term}" for term in strong_hits)

    # A complete-looking but entirely blank quotation form is not evidence.
    if structured and filled_signal_rows == 0:
        return None
    # Weak/headerless and vertical key-value tables are safer as text evidence;
    # treating a product row as a header would silently drop that product.
    if not structured:
        return None
    return {
        "block": block,
        "score": score,
        "reasons": sorted(set(reasons)),
        "header_idx": best_idx,
        "header": header,
        "header_block_row": header_block_row,
        "header_source_block_id": header_source_block_id,
        "header_source": header_source,
        "header_inherited": use_inherited,
        "strong_local_header": strong_local_header,
        "field_columns": best_fields,
        "service_detail_columns": best_service_details,
        "matched_fields": sorted(best_fields),
        "matched_service_details": sorted(best_service_details),
        "data_rows": data_rows,
    }


def score_text(block: dict[str, Any]) -> dict[str, Any] | None:
    block_type = block.get("type")
    if block_type not in {"heading", "paragraph", "ocr_text", "table"}:
        return None
    text = " ".join(str(block.get("text") or "").split())
    if len(text) < 4 or (len(text) < 120 and any(term in text for term in BOILERPLATE_TERMS)):
        return None
    source_score, reasons = _source_bonus(block)
    strong_hits = [term for term in STRONG_PHRASES if term in text]
    field_hits = [term for term in FIELD_TERMS if term in text]
    outcome_hits = [term for term in OUTCOME_TERMS if term in text]
    score = source_score
    if strong_hits:
        score += min(20, 9 * len(strong_hits))
        reasons.extend(f"phrase:{term}" for term in strong_hits)
    if field_hits:
        score += min(14, 2 * len(field_hits))
        reasons.append(f"fields:{len(field_hits)}")
    if outcome_hits:
        score += min(6, 2 * len(outcome_hits))
        reasons.append("text:outcome_context")
    if MONEY_RE.search(text):
        score += 4
        reasons.append("text:money")
    if QUANTITY_RE.search(text):
        score += 3
        reasons.append("text:quantity")
    if block.get("type") == "heading" and strong_hits:
        score += 3
    if not (strong_hits or field_hits or MONEY_RE.search(text)):
        return None
    return {"block": block, "score": score, "reasons": sorted(set(reasons))}


def _source_key(block: dict[str, Any]) -> tuple[str, str]:
    source = block.get("source") or {}
    return (
        str(source.get("container_path") or source.get("file_name") or ""),
        str(source.get("sheet") or ""),
    )


def _table_evidence_chunks(candidate: dict[str, Any], config: SelectorConfig) -> list[dict[str, Any]]:
    block = candidate["block"]
    header = candidate["header"]
    data_rows = candidate["data_rows"]
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = len(json.dumps(header, ensure_ascii=False))

    def flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        chunks.append({
            "kind": "table",
            "block_id": block.get("block_id"),
            "source": block.get("source") or {},
            "matched_fields": candidate["matched_fields"],
            "field_columns": candidate["field_columns"],
            "matched_service_details": candidate["matched_service_details"],
            "service_detail_columns": candidate["service_detail_columns"],
            "header_block_row": candidate["header_block_row"],
            "header_source_block_id": candidate["header_source_block_id"],
            "header_source": candidate["header_source"],
            "header_inherited": candidate["header_inherited"],
            "header": header,
            "data_rows": current,
        })
        current = []
        current_chars = len(json.dumps(header, ensure_ascii=False))

    for row_number, cells in data_rows:
        entry = {"block_row": row_number, "cells": cells}
        entry_chars = len(json.dumps(entry, ensure_ascii=False))
        if current and (
            len(current) >= config.max_table_rows_per_request
            or current_chars + entry_chars > config.max_input_chars_per_request
        ):
            flush()
        current.append(entry)
        current_chars += entry_chars
    flush()
    return chunks


def _text_groups(payload: dict[str, Any], scored: list[dict[str, Any]], config: SelectorConfig) -> list[dict[str, Any]]:
    blocks = payload.get("blocks") or []
    positions = {id(block): index for index, block in enumerate(blocks)}
    selected_positions: set[int] = set()
    score_by_position: dict[int, int] = {}
    reasons_by_position: dict[int, list[str]] = {}
    for candidate in scored:
        block = candidate["block"]
        position = positions.get(id(block))
        if position is None:
            continue
        score_by_position[position] = candidate["score"]
        reasons_by_position[position] = candidate["reasons"]
        document_id = (block.get("source") or {}).get("document_id")
        for neighbor in range(max(0, position - config.context_window), min(len(blocks), position + config.context_window + 1)):
            other = blocks[neighbor]
            if (other.get("source") or {}).get("document_id") != document_id:
                continue
            is_seed = neighbor in score_by_position
            text_like_table = other.get("type") == "table" and len(other.get("rows") or []) <= 1
            if (other.get("type") in {"heading", "paragraph", "ocr_text"} or text_like_table or is_seed) and str(other.get("text") or "").strip():
                selected_positions.add(neighbor)

    groups: list[list[int]] = []
    for position in sorted(selected_positions):
        if not groups:
            groups.append([position])
            continue
        previous = groups[-1][-1]
        same_document = (blocks[previous].get("source") or {}).get("document_id") == (blocks[position].get("source") or {}).get("document_id")
        if same_document and position <= previous + 1:
            groups[-1].append(position)
        else:
            groups.append([position])

    output: list[dict[str, Any]] = []
    for positions_in_group in groups:
        evidence = []
        total_chars = 0
        seed_scores = [score_by_position[position] for position in positions_in_group if position in score_by_position]
        # A context-only fragment can become separated from its seed by a table
        # block.  It is not independently useful and must not create a request.
        if not seed_scores:
            continue
        group_score = max(seed_scores)
        group_reasons = sorted({reason for position in positions_in_group for reason in reasons_by_position.get(position, [])})
        for position in positions_in_group:
            block = blocks[position]
            text = " ".join(str(block.get("text") or "").split())
            segment_size = max(1000, config.max_input_chars_per_request - 1200)
            for char_start in range(0, len(text), segment_size):
                segment = text[char_start : char_start + segment_size]
                entry = {
                    "block_id": block.get("block_id"),
                    "type": block.get("type"),
                    "source": block.get("source") or {},
                    "char_start": char_start,
                    "char_end": char_start + len(segment),
                    "text": segment,
                }
                entry_chars = len(json.dumps(entry, ensure_ascii=False))
                if evidence and total_chars + entry_chars > config.max_input_chars_per_request:
                    output.append({"kind": "text", "score": group_score, "reasons": group_reasons, "blocks": evidence})
                    evidence, total_chars = [], 0
                evidence.append(entry)
                total_chars += entry_chars
        if evidence:
            output.append({"kind": "text", "score": group_score, "reasons": group_reasons, "blocks": evidence})
    return output


def _request_payload(notice: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    user_input = {
        "notice_id": notice.get("notice_id"),
        "title": _notice_title(notice),
        "instruction": "从evidence中抽取实际中标/成交标的物；若没有实际结果，items返回空数组。",
        "evidence": evidence,
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }


def _config_digest(config: SelectorConfig) -> str:
    encoded = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _notice_title(payload: dict[str, Any]) -> str:
    title = " ".join(str(payload.get("title") or "").split())
    if title and not title.lower().startswith(("http://", "https://")):
        return title
    for block in payload.get("blocks") or []:
        if block.get("type") == "heading" and str(block.get("text") or "").strip():
            return " ".join(str(block["text"]).split())
    return title or str(payload.get("notice_id") or "")


def _build_table_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Score tables in source order and inherit headers across PDF pages."""
    candidates: list[dict[str, Any]] = []
    pdf_headers: dict[str, dict[str, Any]] = {}
    for block_order, block in enumerate(payload.get("blocks") or []):
        if block.get("type") != "table":
            continue
        rows = block.get("rows") or []
        if len(rows) < 2:
            continue
        source = block.get("source") or {}
        column_count = max((len(row) for row in rows), default=0)
        registry_key = str(source.get("document_id") or "")
        inherited = None
        if source.get("file_type") == "pdf":
            inherited = pdf_headers.get(registry_key)
            if inherited:
                required_columns = max(inherited.get("field_columns", {}).values(), default=-1) + 1
                header_columns = int(inherited.get("column_count") or 0)
                if column_count < required_columns or abs(header_columns - column_count) > 2:
                    inherited = None
            if inherited:
                prior_page = inherited.get("header_source", {}).get("page")
                current_page = source.get("page")
                if isinstance(prior_page, int) and isinstance(current_page, int):
                    if current_page <= prior_page or current_page - prior_page > 40:
                        inherited = None
        candidate = score_table(block, inherited)
        if candidate is None:
            continue
        candidate["block_order"] = block_order
        candidates.append(candidate)
        if source.get("file_type") == "pdf" and candidate["strong_local_header"]:
            pdf_headers[registry_key] = {
                "field_columns": candidate["field_columns"],
                "service_detail_columns": candidate["service_detail_columns"],
                "header": candidate["header"],
                "header_block_row": candidate["header_block_row"],
                "header_source_block_id": candidate["header_source_block_id"],
                "header_source": candidate["header_source"],
                "column_count": column_count,
            }
    return candidates


def _evidence_fingerprint(evidence: dict[str, Any]) -> str:
    if evidence.get("kind") == "table":
        content = {
            "kind": "table",
            "header": evidence.get("header") or [],
            "rows": [row.get("cells") or [] for row in evidence.get("data_rows") or []],
        }
    else:
        content = {
            "kind": "text",
            "texts": [_compact(block.get("text")) for block in evidence.get("blocks") or []],
        }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_notice(payload: dict[str, Any], config: SelectorConfig | None = None) -> dict[str, Any]:
    """Return a complete, API-ready model-input package for one notice."""
    config = config or SelectorConfig()
    table_candidates = _build_table_candidates(payload)
    table_candidates.sort(key=lambda item: item["score"], reverse=True)

    # Limit distinct low-value sources while retaining every split block from a
    # selected source.  This preserves all rows of a large workbook/PDF table.
    selected_source_keys: list[tuple[str, str]] = []
    selected_tables: list[dict[str, Any]] = []
    table_blocks_excluded_by_source_limit = 0
    for candidate in table_candidates:
        if candidate["score"] < config.table_min_score:
            continue
        key = _source_key(candidate["block"])
        if key not in selected_source_keys:
            if len(selected_source_keys) >= config.max_table_sources_per_notice:
                table_blocks_excluded_by_source_limit += 1
                continue
            selected_source_keys.append(key)
        selected_tables.append(candidate)
    selected_tables.sort(key=lambda candidate: candidate.get("block_order", 0))

    selected_table_ids = {candidate["block"].get("block_id") for candidate in selected_tables}
    text_candidates = [
        candidate
        for block in payload.get("blocks", [])
        if block.get("block_id") not in selected_table_ids and (candidate := score_text(block))
    ]
    text_candidates.sort(key=lambda item: item["score"], reverse=True)
    selected_text = [candidate for candidate in text_candidates if candidate["score"] >= config.text_min_score]
    fallback_used = False
    if not selected_tables and not selected_text and text_candidates:
        selected_text = [
            candidate for candidate in text_candidates
            if candidate["score"] >= config.fallback_text_min_score
        ][: config.fallback_text_blocks]
        fallback_used = bool(selected_text)

    request_evidence: list[tuple[int, list[str], dict[str, Any]]] = []
    for candidate in selected_tables:
        for evidence in _table_evidence_chunks(candidate, config):
            request_evidence.append((candidate["score"], candidate["reasons"], evidence))

    text_groups = _text_groups(payload, selected_text, config)
    text_groups.sort(key=lambda item: item["score"], reverse=True)
    selected_text_groups = text_groups[: config.max_text_requests_per_notice]
    for group in selected_text_groups:
        evidence = {"kind": "text", "blocks": group["blocks"]}
        request_evidence.append((group["score"], group["reasons"], evidence))

    deduplicated_evidence: list[tuple[int, list[str], dict[str, Any]]] = []
    seen_fingerprints: set[str] = set()
    for item in request_evidence:
        fingerprint = _evidence_fingerprint(item[2])
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        deduplicated_evidence.append(item)
    duplicate_request_count = len(request_evidence) - len(deduplicated_evidence)
    request_evidence = deduplicated_evidence

    requests = []
    selected_block_ids: set[str] = set()
    for request_number, (score, reasons, evidence) in enumerate(request_evidence, 1):
        if evidence["kind"] == "table":
            source_ids = [evidence.get("block_id"), evidence.get("header_source_block_id")]
        else:
            source_ids = [item.get("block_id") for item in evidence.get("blocks", [])]
        source_ids = list(dict.fromkeys(str(item) for item in source_ids if item))
        selected_block_ids.update(source_ids)
        api_payload = _request_payload(payload, evidence)
        requests.append({
            "request_id": f"{payload.get('notice_id')}:req_{request_number:03d}",
            "content_kind": evidence["kind"],
            "relevance_score": score,
            "selection_reasons": reasons,
            "source_block_ids": source_ids,
            "estimated_input_chars": sum(len(message["content"]) for message in api_payload["messages"]),
            "api_payload": api_payload,
        })

    original_blocks = payload.get("blocks") or []
    return {
        "schema_version": "1.0",
        "selector_version": SELECTOR_VERSION,
        "selector_config_digest": _config_digest(config),
        "selector_config": asdict(config),
        "notice_id": payload.get("notice_id"),
        "title": _notice_title(payload),
        "source_parser_version": payload.get("parser_version", "legacy-unversioned"),
        "source_parser_config_digest": payload.get("parser_config_digest"),
        "stats": {
            "original_block_count": len(original_blocks),
            "table_candidate_count": len(table_candidates),
            "table_above_threshold_count": sum(
                candidate["score"] >= config.table_min_score for candidate in table_candidates
            ),
            "selected_table_block_count": len(selected_tables),
            "selected_table_source_count": len(selected_source_keys),
            "table_blocks_excluded_by_source_limit": table_blocks_excluded_by_source_limit,
            "table_source_limit_triggered": table_blocks_excluded_by_source_limit > 0,
            "text_candidate_count": len(text_candidates),
            "text_above_threshold_count": len(selected_text),
            "text_group_count_before_limit": len(text_groups),
            "selected_text_group_count": len(selected_text_groups),
            "text_groups_excluded_by_request_limit": max(0, len(text_groups) - len(selected_text_groups)),
            "text_request_limit_triggered": len(text_groups) > len(selected_text_groups),
            "selected_source_block_count": len(selected_block_ids),
            "request_count": len(requests),
            "deduplicated_request_count": duplicate_request_count,
            "inherited_header_table_count": sum(bool(candidate["header_inherited"]) for candidate in selected_tables),
            "estimated_input_chars": sum(request["estimated_input_chars"] for request in requests),
            "fallback_used": fallback_used,
        },
        "requests": requests,
    }
