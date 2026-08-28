# -*- coding: utf-8 -*-
"""DeepSeek few-shot silver labeler.

Table *selection* still reuses the deterministic candidate prefilter (header
mapping + numeric-row check) so we do not send 300,000 blocks to the API.
Field *extraction* is performed by DeepSeek with few-shot gold examples; the
exact source row JSON and provenance are re-attached locally, never trusted
from the model.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_silver_labels as rules  # noqa: E402

BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
GOLD_DIR = ROOT / "dataset_build" / "gold"
GOLD_ITEMS_FILE = GOLD_DIR / "gold_items.jsonl"

SYSTEM_PROMPT = """你是政府采购招投标公告的标的物信息抽取专家。

任务：从给定表格中提取成交/中标标的物条目。目标字段固定为：
product_service_name（产品/服务名称）、category_name（品目名称）、category_code（品目编码）、
brand_supplier（品牌或产品供应商）、spec_model（规格型号）、unit_price（单价，元）、
quantity（数量）、quantity_unit（数量单位）、total_price（总价，元）。

规则：
1. 只提取表格中实际出现且有证据的值；没有证据的字段输出 null，禁止猜测、禁止补全。
2. brand_supplier 只填产品品牌/制造商/产品供应商，绝不把中标供应商、投标人自动当作品牌。
3. 金额统一转换为人民币“元”的数值；原文是万元时乘以 10000。数量拆成数值和单位，例如“1(项)”-> quantity=1, quantity_unit="项"。
4. category_code 只在原文明确出现品目编码时输出，否则为 null。
5. 跳过“合计/总计/小计/备注/废标”等汇总或非标的行；跳过“见附件/详见附件”等占位行中的占位字段（应填 null）。
6. 每个数据行最多输出一条；block_row 必须使用输入 data_rows 中给出的整数。
7. 只输出一个 JSON 对象，不要输出任何解释文字。

输出 JSON 结构：
{"items":[{"block_row":2,"product_service_name":"...","category_name":null,"category_code":null,"brand_supplier":"...","spec_model":"...","unit_price":123.0,"quantity":1,"quantity_unit":"项","total_price":123.0}]}
"""


def _num(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).replace(",", "").replace("元", "").strip()
    if text in {"", "null", "None"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    text = text.strip(" \t\r\n;；,，、。.：:")
    if text in {"", "null", "None", "/", "-", "—", "无", "不涉及", "见附件", "见附件清单", "详见附件"}:
        return None
    return text


def _find_gold_block(payload: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    target_container = item.get("source_container_path")
    target_table = None
    loc = item.get("source_location", "")
    m = re.search(r"table_index=(\d+)", loc)
    if m:
        target_table = int(m.group(1))
    for block in payload.get("blocks", []):
        src = block.get("source", {})
        if src.get("container_path") != target_container:
            continue
        if target_table is not None and src.get("table_index") != target_table:
            continue
        if block.get("type") == "table" and block.get("rows"):
            return block
    return None


def load_gold_items() -> dict[str, list[dict[str, Any]]]:
    by_notice: dict[str, list[dict[str, Any]]] = {}
    for line in GOLD_ITEMS_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        by_notice.setdefault(item["notice_id"], []).append(item)
    return by_notice


def build_few_shot_examples() -> list[dict[str, Any]]:
    """Pick one compact HTML, DOCX and PDF gold example."""
    gold_by_notice = load_gold_items()
    wanted = [
        ("20260813_27128600", 3),   # html, 1 row
        ("20260815_27141366", 2),   # pdf, 1 row
        ("20260814_27137567", 4),   # docx, show first 3 rows
    ]
    examples: list[dict[str, Any]] = []
    for nid, max_rows in wanted:
        items = gold_by_notice.get(nid)
        if not items:
            continue
        payload = json.loads((BLOCK_DIR / f"{nid}.json").read_text(encoding="utf-8"))
        block = _find_gold_block(payload, items[0])
        if block is None:
            continue
        rows = block.get("rows") or []
        chosen_rows = sorted({item["source_block_row"] for item in items})[:max_rows]
        data_rows = [
            {"block_row": row_no, "cells": [str(c) for c in rows[row_no - 1]]}
            for row_no in chosen_rows
            if 1 <= row_no <= len(rows)
        ]
        header_row = [str(c) for c in rows[0]]
        output_items = []
        for item in items:
            if item["source_block_row"] not in chosen_rows:
                continue
            output_items.append({
                "block_row": item["source_block_row"],
                "product_service_name": item.get("product_service_name"),
                "category_name": item.get("category_name"),
                "category_code": item.get("category_code"),
                "brand_supplier": item.get("brand_supplier"),
                "spec_model": item.get("spec_model"),
                "unit_price": item.get("unit_price"),
                "quantity": item.get("quantity"),
                "quantity_unit": item.get("quantity_unit"),
                "total_price": item.get("total_price"),
            })
        if data_rows and output_items:
            examples.append({
                "notice_id": nid,
                "input": {"header_row": header_row, "data_rows": data_rows},
                "output": {"items": output_items},
            })
    return examples


def build_messages(notice: dict[str, Any], candidate: dict[str, Any], examples: list[dict[str, Any]]) -> list[dict[str, str]]:
    source = candidate["source"]
    block = next(b for b in notice["blocks"] if b.get("block_id") == candidate["block_id"])
    rows = block.get("rows") or []
    header_idx = candidate["header_idx"]
    data_rows = []
    for idx in range(header_idx + 1, len(rows)):
        data_rows.append({"block_row": idx + 1, "cells": [str(c)[:500] for c in rows[idx]]})

    user = {
        "notice_id": notice.get("notice_id"),
        "title": notice.get("title"),
        "source_file": source.get("file_name"),
        "header_row": [str(c)[:200] for c in rows[header_idx]],
        "data_rows": data_rows,
    }

    content_parts = ["以下是金标示例。\n"]
    for i, example in enumerate(examples, 1):
        content_parts.append(f"示例{i}输入：\n{json.dumps(example['input'], ensure_ascii=False)}")
        content_parts.append(f"示例{i}输出：\n{json.dumps(example['output'], ensure_ascii=False)}\n")
    content_parts.append("现在请对以下表格执行相同的抽取：\n")
    content_parts.append(json.dumps(user, ensure_ascii=False))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(content_parts)},
    ]


def _find_candidate_block(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return next(b for b in payload["blocks"] if b.get("block_id") == candidate["block_id"])


def llm_items_to_silver_items(block: dict[str, Any], llm_items: list[dict[str, Any]], header_idx: int) -> list[dict[str, Any]]:
    rows = block.get("rows") or []
    source = block.get("source", {})
    seen_rows: set[int] = set()
    output: list[dict[str, Any]] = []
    for raw in llm_items:
        if not isinstance(raw, dict):
            continue
        block_row = raw.get("block_row")
        if isinstance(block_row, str) and block_row.isdigit():
            block_row = int(block_row)
        if not isinstance(block_row, int) or block_row <= header_idx or block_row > len(rows):
            continue
        if block_row in seen_rows:
            continue
        product = _str(raw.get("product_service_name"))
        if not product:
            continue
        seen_rows.add(block_row)
        row = [str(c) for c in rows[block_row - 1]]
        item = {
            "product_service_name": product,
            "category_name": _str(raw.get("category_name")),
            "category_code": _str(raw.get("category_code")),
            "brand_supplier": _str(raw.get("brand_supplier")),
            "spec_model": _str(raw.get("spec_model")),
            "unit_price": _num(raw.get("unit_price")),
            "quantity": _num(raw.get("quantity")),
            "quantity_unit": _str(raw.get("quantity_unit")),
            "total_price": _num(raw.get("total_price")),
            "source_block_row": block_row,
            "evidence_text": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        }
        item["silver_price_consistency"] = rules.price_consistency(item)
        output.append(item)
    output.sort(key=lambda item: item["source_block_row"])
    for item in output:
        item["source_block_id"] = block.get("block_id")
        item["source_document_id"] = source.get("document_id")
        item["source_file"] = source.get("file_name")
        item["source_container_path"] = source.get("container_path")
        item["source_location"] = rules.source_location(source, item["source_block_row"])
    return output


def finalize_api_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort merged chunk results by source row and assign sequential item_no."""
    items = sorted(items, key=lambda item: item["source_block_row"])
    for item_no, item in enumerate(items, start=1):
        item["item_no"] = item_no
    return items


def enforce_evidence_columns(items: list[dict[str, Any]], candidate: dict[str, Any],
                             block: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Do not trust model-inferred fields for columns that do not exist in the table.

    ``category_code`` is an exception: when a category_name column exists, the
    code is split locally from the exact source cell (same rule as gold), never
    from the model.
    """
    fields = set(candidate.get("fields", []))
    category_col = candidate.get("columns", {}).get("category_name")
    rows = (block or {}).get("rows") or []
    for item in items:
        if "category_name" not in fields:
            item["category_name"] = None
            item["category_code"] = None
        elif "category_code" not in fields:
            item["category_code"] = None
            if category_col is not None and 0 < item["source_block_row"] <= len(rows):
                cell = rows[item["source_block_row"] - 1][category_col] \
                    if category_col < len(rows[item["source_block_row"] - 1]) else None
                name, code = rules.split_category_safe(cell)
                if code:
                    item["category_code"] = code
                    item["category_name"] = name or item.get("category_name")
        for field in ("brand_supplier", "spec_model", "unit_price", "quantity"):
            if field not in fields:
                item[field] = None
        if "total_price" not in fields:
            item["total_price"] = None
        if "quantity" not in fields:
            item["quantity_unit"] = None
        item["silver_price_consistency"] = rules.price_consistency(item)
    return items


def fallback_items(payload: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    block = _find_candidate_block(payload, candidate)
    items, _warnings = rules.extract_items(block, candidate["columns"], candidate["header_idx"])
    for item_no, item in enumerate(items, start=1):
        item["item_no"] = item_no
        item["source_block_id"] = block.get("block_id")
        item["source_document_id"] = block["source"].get("document_id")
        item["source_file"] = block["source"].get("file_name")
        item["source_container_path"] = block["source"].get("container_path")
        item["source_location"] = rules.source_location(block["source"], item["source_block_row"])
        item["silver_price_consistency"] = item.pop("_price_consistency", "not_checkable")
        item.pop("_numeric_field_count", None)
    return items
