# -*- coding: utf-8 -*-
"""Generate silver (weak) labels for task-1 procurement item extraction.

Strategy
--------
1. Read every converted unified Block notice under
   ``dataset_build/blocks/notices/*.json``.
2. Use the ten manually curated gold notices as a reference for:
   * field/header alias coverage,
   * expected evidence shape (source block + row + exact row JSON),
   * quality thresholds (the same rules that reproduce gold tables get high
     confidence).
3. For every non-gold notice, find row-oriented tables whose headers map to
   the seven target fields.  Only tables that contain a product/service name
   column and at least two product-level columns (brand / spec / unit price /
   quantity / total price) are accepted; bidder/supplier result tables are
   deliberately rejected.
4. Extract one item per data row, preserving source provenance and exact
   evidence text.  Numeric consistency between unit price * quantity and total
   price is recorded as a quality flag.
5. Write:
   * ``dataset_build/silver/notices/{notice_id}.json``
   * ``dataset_build/silver/silver_items.jsonl``
   * ``dataset_build/silver/silver_manifest.json``
   * ``dataset_build/silver/silver_schema.json``
   * ``dataset_build/silver/silver_report.md``
6. Report how well the same rule set reproduces the ten gold notices
   (gold-retention diagnostic), so low precision patterns can be spotted
   before silver labels are trusted downstream.

This is a deterministic, gold-guided weak labeler.  It is not a substitute for
the manual gold set and must not be used to overwrite gold labels.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_gold_seed import clean, entity_text, number, quantity, source_location, split_category  # noqa: E402

BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
GOLD_DIR = ROOT / "dataset_build" / "gold"
GOLD_NOTICE_DIR = GOLD_DIR / "notices"
SILVER_DIR = ROOT / "dataset_build" / "silver"
SILVER_NOTICE_DIR = SILVER_DIR / "notices"

VERSION = "1.0.0-silver"
ANNOTATION_METHOD = "gold_guided_rules_silver"
REVIEW_STATUS = "silver_unreviewed"

# Order matters: first alias list, first matching column wins.
FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "product_service_name": (
        "货物名称", "标的名称", "产品名称", "设备名称", "服务名称", "采购标的",
        "标的物名称", "品名", "名称", "项目名称", "分项名称", "清单名称", "报价项目",
    ),
    "category_name": ("品目名称", "品目分类", "品目", "采购品目"),
    "category_code": ("品目号", "品目编码", "品目代码", "采购品目编码"),
    "brand_supplier": ("品牌", "货物品牌", "产品品牌", "制造商", "生产厂家", "产品供应商", "厂家"),
    "spec_model": ("规格型号", "规格", "型号", "货物型号", "产品型号", "技术规格", "配置"),
    "unit_price": ("单价", "单价(元)", "单价（元）", "货物单价", "产品单价", "成交单价", "投标单价"),
    "quantity": ("数量", "数量(单位)", "数量（单位）", "货物数量", "采购数量", "工程数量"),
    "quantity_unit": ("单位", "计量单位", "货物单位"),
    "total_price": (
        "总价", "总价(元)", "总价（元）", "合价", "货物合价", "金额", "金额(元)",
        "报价", "成交金额", "中标金额",
    ),
}

# These are enough to identify a product item table and reject supplier tables.
PRODUCT_TABLE_FIELDS = {"brand_supplier", "spec_model", "unit_price", "quantity", "total_price"}

SOURCE_BONUS = {
    "报价": 18,
    "明细": 18,
    "成交": 10,
    "中标": 10,
    "结果": 10,
    "公示": 6,
    "清单": 8,
}

TEMPLATE_PENALTY_TOKENS = ("招标文件", "采购文件", "磋商文件", "谈判文件", "询价文件", "单一来源文件", "文件集")
TEMPLATE_RELIEF_TOKENS = ("报价", "明细", "分项", "清单", "成交", "中标", "结果")

SILVER_ITEM_SCHEMA = {
    "type": "object",
    "required": [
        "item_no", "product_service_name", "category_name", "category_code",
        "brand_supplier", "spec_model", "unit_price", "quantity", "quantity_unit",
        "total_price", "source_block_id", "source_block_row", "source_document_id",
        "source_file", "source_container_path", "source_location", "evidence_text",
        "silver_price_consistency",
    ],
    "properties": {
        "item_no": {"type": "integer", "minimum": 1},
        "product_service_name": {"type": "string", "minLength": 1},
        "category_name": {"type": ["string", "null"]},
        "category_code": {"type": ["string", "null"]},
        "brand_supplier": {"type": ["string", "null"]},
        "spec_model": {"type": ["string", "null"]},
        "unit_price": {"type": ["number", "null"], "minimum": 0},
        "quantity": {"type": ["number", "null"], "minimum": 0},
        "quantity_unit": {"type": ["string", "null"]},
        "total_price": {"type": ["number", "null"], "minimum": 0},
        "source_block_id": {"type": "string", "minLength": 1},
        "source_block_row": {"type": "integer", "minimum": 1},
        "source_document_id": {"type": "string", "minLength": 1},
        "source_file": {"type": "string", "minLength": 1},
        "source_container_path": {"type": "string", "minLength": 1},
        "source_location": {"type": "string", "minLength": 1},
        "evidence_text": {"type": "string", "minLength": 1},
        "silver_price_consistency": {"enum": ["ok", "mismatch", "not_checkable"]},
    },
    "additionalProperties": False,
}


def norm(value: Any) -> str:
    text = "".join(str(value or "").split()).lower()
    text = text.replace("（", "(").replace("）", ")")
    return text


def silver_entity_text(value: Any) -> str | None:
    """Like gold entity_text, plus common ``see attachment`` placeholders."""
    text = entity_text(value)
    if text is None:
        return None
    compact = norm(text)
    if compact in {"见附件", "见附件清单", "详见附件", "详见清单", "详见报价明细", "详见招标文件",
                   "详见采购文件", "以附件为准", "详见分项报价表"}:
        return None
    if compact.startswith("详见附件") or compact.startswith("见附件"):
        return None
    return text


def norm_alias(value: str) -> str:
    return norm(value)


def field_candidates(field: str) -> tuple[str, ...]:
    return FIELD_GROUPS[field]


def contains_match(cell: str, alias: str, field: str) -> bool:
    """Exact match is preferred; field-specific substring rules handle
    punctuation variants such as ``规格、型号`` or ``金额（元）``."""
    c = norm_alias(cell)
    a = norm_alias(alias)
    if c == a:
        return True
    if field == "product_service_name":
        # ``名称`` alone is too ambiguous; only long product aliases may match
        # by inclusion, and supplier/winner tables are explicitly excluded.
        if len(a) < 4:
            return False
        return a in c and "供应商" not in c and "采购人" not in c and "项目编号" not in c
    if field == "category_name":
        return "品目" in c
    if field == "category_code":
        return ("品目号" in c or "品目编码" in c or ("品目" in c and "编码" in c))
    if field == "brand_supplier":
        return ("品牌" in c or "厂家" in c or "制造商" in c) and "供应商" not in c
    if field == "spec_model":
        return "规格" in c or "型号" in c or "配置" in c
    if field == "unit_price":
        return "单价" in c and "总" not in c
    if field == "quantity":
        return "数量" in c and "金额" not in c and "单价" not in c
    if field == "quantity_unit":
        return ("单位" in c or "计量" in c) and "数量" not in c
    if field == "total_price":
        if "总价" in c or "合价" in c:
            return True
        if "金额" in c and "单价" not in c and "数量" not in c:
            return True
        return False
    # Generic long-alias inclusion as a final fallback.
    if len(a) < 3:
        return False
    return a in c


def match_columns(header_row: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    used: set[int] = set()

    def assign(field: str, alias: str, loose: bool) -> None:
        for idx, cell in enumerate(header_row):
            if idx in used or not cell:
                continue
            c = norm_alias(str(cell))
            a = norm_alias(alias)
            if loose:
                hit = contains_match(str(cell), alias, field)
            else:
                hit = c == a
            if hit:
                columns[field] = idx
                used.add(idx)
                return

    # First pass: exact normalized header matches win over substring matches.
    for field, aliases in FIELD_GROUPS.items():
        for alias in aliases:
            assign(field, alias, loose=False)
            if field in columns:
                break
    # Second pass: tolerant matches only fill still-missing fields.
    for field, aliases in FIELD_GROUPS.items():
        if field in columns:
            continue
        for alias in aliases:
            assign(field, alias, loose=True)
            if field in columns:
                break
    return columns


def is_header_repeat(rows: list[list[str]], row_idx: int, header_idx: int) -> bool:
    header = norm("|".join(str(c) for c in rows[header_idx]))
    candidate = norm("|".join(str(c) for c in rows[row_idx]))
    return bool(header) and header == candidate


def looks_like_summary_row(row: list[str], product: str | None) -> bool:
    if not product:
        return True
    text = norm(product)
    if text in {"/", "-", "—", "无", "不涉及", "null", "none"}:
        return True
    if any(token in text for token in ("合计", "总计", "小计", "备注", "废标", "流标")):
        return True
    joined = norm("|".join(str(c) for c in row))
    if len(joined) < 2:
        return True
    return False


def parse_quantity_safe(value: Any, explicit_unit: Any = None) -> tuple[int | float | None, str | None]:
    try:
        return quantity(value, explicit_unit)
    except (ValueError, InvalidOperation, TypeError):
        qty = safe_number(value)
        return qty, clean(explicit_unit)


def safe_number(value: Any) -> int | float | None:
    try:
        return number(value)
    except (ValueError, InvalidOperation, TypeError):
        return None


def split_category_safe(value: Any) -> tuple[str | None, str | None]:
    try:
        return split_category(value)
    except Exception:
        return clean(value), None


def extract_items(block: dict[str, Any], columns: dict[str, int], header_idx: int) -> tuple[list[dict[str, Any]], list[str]]:
    rows = block.get("rows") or []
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    def col(name: str, row: list[str]) -> Any:
        idx = columns.get(name)
        return row[idx] if idx is not None and idx < len(row) else None

    for row_idx in range(header_idx + 1, len(rows)):
        row = [str(c) for c in rows[row_idx]]
        if is_header_repeat(rows, row_idx, header_idx):
            continue
        product = silver_entity_text(col("product_service_name", row))
        if looks_like_summary_row(row, product):
            continue
        # Must carry at least one product-level numeric/attribute signal.
        numeric_cells = [clean(col(f, row)) for f in ("unit_price", "quantity", "total_price")]
        if not any(numeric_cells):
            if not (silver_entity_text(col("brand_supplier", row)) or silver_entity_text(col("spec_model", row))):
                continue

        category_name, category_code = split_category_safe(col("category_name", row))
        explicit_code = clean(col("category_code", row))
        if category_code is None and explicit_code:
            category_code = explicit_code
        if category_name is None and explicit_code:
            category_name, category_code = split_category_safe(explicit_code)

        qty_value, qty_unit = parse_quantity_safe(col("quantity", row), col("quantity_unit", row))

        item: dict[str, Any] = {
            "product_service_name": product,
            "category_name": silver_entity_text(category_name),
            "category_code": silver_entity_text(category_code),
            "brand_supplier": silver_entity_text(col("brand_supplier", row)),
            "spec_model": silver_entity_text(col("spec_model", row)),
            "unit_price": safe_number(col("unit_price", row)),
            "quantity": qty_value,
            "quantity_unit": silver_entity_text(qty_unit),
            "total_price": safe_number(col("total_price", row)),
            "source_block_row": row_idx + 1,
            "evidence_text": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        }
        item["_price_consistency"] = price_consistency(item)
        item["_numeric_field_count"] = sum(v is not None for v in (item["unit_price"], item["quantity"], item["total_price"]))
        items.append(item)

    return items, warnings


def price_consistency(item: dict[str, Any]) -> str:
    up, qty, total = item.get("unit_price"), item.get("quantity"), item.get("total_price")
    if up is None or qty is None or total is None:
        return "not_checkable"
    expected = float(up) * float(qty)
    if expected == 0:
        return "ok" if abs(float(total)) < 0.01 else "mismatch"
    ratio = abs(expected - float(total)) / max(abs(expected), abs(float(total)), 1.0)
    return "ok" if ratio <= 0.02 else "mismatch"


def table_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return table-level candidates with field mapping and score."""
    candidates: list[dict[str, Any]] = []
    doc_status = {d.get("document_id"): d.get("status", "ok") for d in payload.get("documents", [])}
    for block in payload.get("blocks", []):
        if block.get("type") != "table":
            continue
        rows = block.get("rows") or []
        if len(rows) < 2:
            continue

        best_header_idx = -1
        best_columns: dict[str, int] = {}
        best_fields: set[str] = set()
        # Some XLSX/PDF parsers emit a merged title row and blank rows before the
        # real header; search the first 10 rows for the best field mapping.
        for header_idx in range(min(10, len(rows))):
            columns = match_columns([str(c) for c in rows[header_idx]])
            fields = set(columns)
            if "product_service_name" not in fields:
                continue
            product_fields = fields & PRODUCT_TABLE_FIELDS
            if len(product_fields) < 2:
                # Require product + at least two product-level signals.
                continue
            if len(fields) > len(best_fields):
                best_header_idx, best_columns, best_fields = header_idx, columns, fields
        if best_header_idx < 0 or "product_service_name" not in best_fields:
            continue

        source = block.get("source", {})
        container = str(source.get("container_path", ""))
        source_bonus = sum(points for token, points in SOURCE_BONUS.items() if token in container)
        template_penalty = 0
        for token in TEMPLATE_PENALTY_TOKENS:
            if token in container:
                template_penalty = 50
                break
        if template_penalty and any(token in container for token in TEMPLATE_RELIEF_TOKENS):
            template_penalty = max(0, template_penalty - 25)

        # Count rows that will actually be emitted.
        preview_items, _warnings = extract_items(block, best_columns, best_header_idx)
        numeric_rows = sum(1 for item in preview_items if item.get("_numeric_field_count", 0) > 0)
        if numeric_rows == 0:
            continue

        doc_status_value = doc_status.get(source.get("document_id"), "ok")
        status_penalty = {"error": 90, "unsupported": 70, "partial": 25}.get(doc_status_value, 0)

        field_count = len(best_fields)
        score = field_count * 30 + min(numeric_rows, 60) + source_bonus - template_penalty - status_penalty

        candidates.append({
            "block_id": block.get("block_id"),
            "source": source,
            "fields": sorted(best_fields),
            "field_count": field_count,
            "columns": best_columns,
            "header_idx": best_header_idx,
            "header_row": [str(c) for c in rows[best_header_idx]],
            "preview_item_count": len(preview_items),
            "numeric_rows": numeric_rows,
            "score": score,
            "status_penalty": status_penalty,
            "template_penalty": template_penalty,
            "source_bonus": source_bonus,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def confidence_for(candidate: dict[str, Any], items: list[dict[str, Any]]) -> tuple[str, float]:
    field_count = candidate["field_count"]
    checkable = [i for i in items if i.get("_price_consistency", "not_checkable") != "not_checkable"]
    consistent = [i for i in checkable if i.get("_price_consistency") == "ok"]
    consistency_rate = (len(consistent) / len(checkable)) if checkable else 1.0
    score = candidate["score"] / 220.0
    score += consistency_rate * 0.5
    score += min(candidate["numeric_rows"], 50) / 100.0
    score += field_count / 14.0
    score = min(1.0, score)
    if field_count >= 6 and consistency_rate >= 0.8 and candidate["status_penalty"] == 0:
        level = "high"
    elif field_count >= 5 or (field_count >= 4 and consistency_rate >= 0.8):
        level = "medium"
    else:
        level = "low"
    return level, round(score, 3)


def build_notice(payload: dict[str, Any], candidate: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    block_rows = payload["blocks"]
    first_block_text = clean(block_rows[0].get("text")) if block_rows else None
    title = clean(payload.get("title")) or first_block_text
    # Some parsed notices store the URL as title; fall back to the first heading.
    if not title or title.startswith("http"):
        for block in payload.get("blocks", []):
            if block.get("type") == "heading" and block.get("text"):
                title = clean(block["text"])
                break
    if not title:
        title = payload.get("notice_id")

    source = candidate["source"]
    for item_no, item in enumerate(items, start=1):
        item["item_no"] = item_no
        item["source_block_id"] = candidate["block_id"]
        item["source_document_id"] = source.get("document_id")
        item["source_file"] = source.get("file_name")
        item["source_container_path"] = source.get("container_path")
        item["source_location"] = source_location(source, item["source_block_row"])
        item["silver_price_consistency"] = item.pop("_price_consistency", "not_checkable")
        item.pop("_numeric_field_count", None)

    level, confidence = confidence_for(candidate, items)
    return {
        "notice_id": payload.get("notice_id"),
        "title": title,
        "source_parser_version": payload.get("parser_version", "legacy-unversioned"),
        "source_parser_config_digest": payload.get("parser_config_digest"),
        "annotation_version": VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "review_status": REVIEW_STATUS,
        "selection_reason": (
            f"统一Block表头映射：{', '.join(candidate['fields'])}；"
            f"来源={source.get('container_path')}；评分={candidate['score']}"
        ),
        "silver_confidence": level,
        "silver_confidence_score": confidence,
        "selected_table": {
            "block_id": candidate["block_id"],
            "source": source,
            "header": candidate["header_row"],
            "matched_fields": candidate["fields"],
            "score": candidate["score"],
        },
        "warnings": [
            f"template_penalty={candidate['template_penalty']}",
            f"status_penalty={candidate['status_penalty']}",
        ],
        "items": items,
    }


def load_gold_reference() -> dict[str, dict[str, Any]]:
    gold: dict[str, dict[str, Any]] = {}
    for path in sorted(GOLD_NOTICE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        gold[data["notice_id"]] = data
    return gold


def gold_diagnostic(gold_reference: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run the same rule labeler over gold notices and compare to manual gold."""
    rows: list[dict[str, Any]] = []
    field_metric = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    same_source = 0
    total_items_gold = 0
    total_items_silver = 0
    for nid, gold in sorted(gold_reference.items()):
        block_path = BLOCK_DIR / f"{nid}.json"
        if not block_path.exists():
            rows.append({"notice_id": nid, "status": "missing_block", "note": block_path.name})
            continue
        payload = json.loads(block_path.read_text(encoding="utf-8"))
        candidates = table_candidates(payload)
        if not candidates:
            rows.append({"notice_id": nid, "status": "no_candidate", "gold_items": len(gold["items"]), "silver_items": 0})
            continue
        # Prefer a candidate whose source matches one of the gold item sources.
        gold_source_keys = {
            (item["source_container_path"], item.get("source_location", "").split(", block_row=")[0])
            for item in gold["items"]
        }
        chosen = candidates[0]
        for cand in candidates:
            src = cand["source"]
            key = (src.get("container_path", ""), source_location(src, 1).split(", block_row=")[0])
            if key in gold_source_keys or src.get("container_path") in {i["source_container_path"] for i in gold["items"]}:
                chosen = cand
                same_source += 1
                break
        else:
            if any(
                gold["items"][0]["source_container_path"] == cand["source"].get("container_path")
                for cand in candidates[:5]
            ):
                same_source += 1

        items = extract_items(
            next(b for b in payload["blocks"] if b.get("block_id") == chosen["block_id"]),
            chosen["columns"], chosen["header_idx"],
        )[0]
        chosen_container = chosen["source"].get("container_path", "")
        for it in items:
            it["source_container_path"] = chosen_container
        total_items_gold += len(gold["items"])
        total_items_silver += len(items)

        # Match gold items to silver items by source block row within same container.
        silver_by_row = {(i["source_container_path"], i["source_block_row"]): i for i in items}
        matched = 0
        for g in gold["items"]:
            s = silver_by_row.get((g["source_container_path"], g["source_block_row"]))
            if s is None:
                for f in ("product_service_name", "category_name", "brand_supplier", "spec_model",
                          "unit_price", "quantity", "total_price"):
                    field_metric[f]["fn"] += 1
                continue
            matched += 1
            for f in ("product_service_name", "category_name", "category_code", "brand_supplier",
                      "spec_model", "unit_price", "quantity", "quantity_unit", "total_price"):
                gv, sv = g.get(f), s.get(f)
                if gv is None and sv is None:
                    continue
                if gv is not None and sv is None:
                    field_metric[f]["fn"] += 1
                elif gv is None and sv is not None:
                    field_metric[f]["fp"] += 1
                elif str(gv) == str(sv):
                    field_metric[f]["tp"] += 1
                else:
                    field_metric[f]["fp"] += 1
                    field_metric[f]["fn"] += 1
        rows.append({
            "notice_id": nid,
            "status": "matched" if matched else "partial_match",
            "matched_items": matched,
            "gold_items": len(gold["items"]),
            "silver_items": len(items),
            "selected_block": chosen["block_id"],
            "candidate_score": chosen["score"],
            "fields": chosen["fields"],
        })

    metrics = {}
    for f, m in field_metric.items():
        p = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else 1.0
        r = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else 1.0
        metrics[f] = {"precision": round(p, 4), "recall": round(r, 4),
                      "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0}
    return {
        "gold_notices": len(gold_reference),
        "notices_with_candidate": sum(1 for r in rows if r["status"] in ("matched", "partial_match")),
        "same_source_selected": same_source,
        "gold_items": total_items_gold,
        "silver_items_on_gold": total_items_silver,
        "per_notice": rows,
        "field_metrics": metrics,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--block-dir", type=Path, default=BLOCK_DIR)
    ap.add_argument("--output-dir", type=Path, default=SILVER_DIR)
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--include-gold", action="store_true", help="also emit silver files for gold notices")
    args = ap.parse_args()

    block_paths = sorted(args.block_dir.glob("*.json"))
    if not block_paths:
        print("No block files found", file=sys.stderr)
        return 2

    gold_reference = load_gold_reference()
    gold_ids = set(gold_reference)
    diagnostic = gold_diagnostic(gold_reference)

    notice_dir = args.output_dir / "notices"
    notice_dir.mkdir(parents=True, exist_ok=True)
    for old in notice_dir.glob("*.json"):
        old.unlink()

    manifest_notices: list[dict[str, Any]] = []
    stats = Counter()
    field_coverage = Counter()
    source_type_counter = Counter()
    total_items = 0

    for path in block_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        nid = payload.get("notice_id")
        if not nid:
            continue
        candidates = table_candidates(payload)
        eligible = [c for c in candidates if c["score"] >= args.min_score]
        if not eligible:
            stats["no_candidate"] += 1
            continue
        candidate = eligible[0]
        block = next(b for b in payload["blocks"] if b.get("block_id") == candidate["block_id"])
        items, warnings = extract_items(block, candidate["columns"], candidate["header_idx"])
        if not items:
            stats["no_items"] += 1
            continue

        notice = build_notice(payload, candidate, items)

        if nid not in gold_ids or args.include_gold:
            stats["confidence_" + notice["silver_confidence"]] += 1
            source_type_counter[str(candidate["source"].get("file_type", "unknown"))] += 1
            total_items += len(items)
            for item in items:
                for f in ("product_service_name", "category_name", "category_code", "brand_supplier",
                          "spec_model", "unit_price", "quantity", "quantity_unit", "total_price"):
                    if item.get(f) is not None:
                        field_coverage[f] += 1
            (notice_dir / f"{nid}.json").write_text(
                json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            manifest_notices.append({
                "notice_id": nid,
                "title": notice["title"],
                "item_count": len(items),
                "confidence": notice["silver_confidence"],
                "confidence_score": notice["silver_confidence_score"],
                "matched_fields": candidate["fields"],
                "source_types": [str(candidate["source"].get("file_type"))],
                "file": f"notices/{nid}.json",
            })
        else:
            stats["excluded_gold"] += 1

    manifest = {
        "annotation_version": VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "review_status": REVIEW_STATUS,
        "notice_count": len(manifest_notices),
        "item_count": total_items,
        "gold_notice_count": len(gold_ids),
        "excluded_gold_notices": sorted(gold_ids),
        "notices": manifest_notices,
        "diagnostic": diagnostic,
    }
    (args.output_dir / "silver_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (args.output_dir / "silver_items.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for entry in manifest_notices:
            notice = json.loads((args.output_dir / entry["file"]).read_text(encoding="utf-8"))
            for item in notice["items"]:
                handle.write(json.dumps(
                    {"notice_id": notice["notice_id"], "title": notice["title"], **item},
                    ensure_ascii=False, separators=(",", ":")
                ) + "\n")

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "silver_schema.json",
        "title": "招采标的物银标公告",
        "type": "object",
        "required": ["notice_id", "title", "source_parser_version", "annotation_version",
                     "annotation_method", "review_status", "selection_reason", "silver_confidence",
                     "silver_confidence_score", "items"],
        "properties": {
            "notice_id": {"type": "string"},
            "title": {"type": "string"},
            "source_parser_version": {"type": "string"},
            "source_parser_config_digest": {"type": ["string", "null"]},
            "annotation_version": {"type": "string"},
            "annotation_method": {"const": ANNOTATION_METHOD},
            "review_status": {"const": REVIEW_STATUS},
            "selection_reason": {"type": "string"},
            "silver_confidence": {"enum": ["high", "medium", "low"]},
            "silver_confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "items": {"type": "array", "items": SILVER_ITEM_SCHEMA},
        },
    }
    (args.output_dir / "silver_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report_lines = [
        "# Silver 标注报告",
        "",
        f"- 处理 Block 公告：{len(block_paths)}",
        f"- 金标公告：{len(gold_ids)}",
        f"- 生成银标公告：{len(manifest_notices)}",
        f"- 银标条目：{total_items}",
        f"- 无候选表：{stats['no_candidate']}",
        f"- 无有效条目：{stats['no_items']}",
        f"- 排除金标公告：{stats['excluded_gold']}",
        "",
        "## 置信度分布",
        "",
    ]
    for level in ("high", "medium", "low"):
        report_lines.append(f"- {level}: {stats['confidence_' + level]}")
    report_lines += ["", "## 字段覆盖", ""]
    for f in ("product_service_name", "category_name", "category_code", "brand_supplier",
              "spec_model", "unit_price", "quantity", "quantity_unit", "total_price"):
        report_lines.append(f"- {f}: {field_coverage[f]}")
    report_lines += ["", "## 来源文件类型", ""]
    for k, v in source_type_counter.most_common():
        report_lines.append(f"- {k}: {v}")
    report_lines += ["", "## 金标复现诊断（同一规则跑金标公告）", ""]
    for k, v in diagnostic.items():
        if k != "per_notice" and k != "field_metrics":
            report_lines.append(f"- {k}: {v}")
    report_lines += ["", "### 字段级 P/R/F1", "", "| 字段 | P | R | F1 |", "|---|---:|---:|---:|"]
    for f, m in diagnostic.get("field_metrics", {}).items():
        report_lines.append(f"| {f} | {m['precision']} | {m['recall']} | {m['f1']} |")
    report_lines.append("")
    (args.output_dir / "silver_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps({
        "block_notices": len(block_paths),
        "gold_notices": len(gold_ids),
        "silver_notices": len(manifest_notices),
        "silver_items": total_items,
        "no_candidate": stats["no_candidate"],
        "no_items": stats["no_items"],
        "confidence": {level: stats["confidence_" + level] for level in ("high", "medium", "low")},
        "gold_diagnostic_summary": {k: v for k, v in diagnostic.items() if k != "per_notice" and k != "field_metrics"},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
