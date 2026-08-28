# -*- coding: utf-8 -*-
"""Validate silver labels against their exact source Blocks.

Silver labels may legitimately contain ``silver_price_consistency == "mismatch"``;
such rows are reported as warnings, not failures, because they are weak labels
whose inconsistency flag is meant to drive later review/LLM correction.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SILVER_DIR = ROOT / "dataset_build" / "silver"
NOTICE_DIR = SILVER_DIR / "notices"
BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"

EXPECTED_NOTICE_FIELDS = {
    "notice_id", "title", "source_parser_version", "source_parser_config_digest",
    "annotation_version", "annotation_method", "review_status", "selection_reason",
    "silver_confidence", "silver_confidence_score", "selected_table", "warnings", "items",
}
REQUIRED_ITEM_FIELDS = {
    "item_no", "product_service_name", "category_name", "category_code",
    "brand_supplier", "spec_model", "unit_price", "quantity", "quantity_unit",
    "total_price", "source_block_id", "source_block_row", "source_document_id",
    "source_file", "source_container_path", "source_location", "evidence_text",
    "silver_price_consistency",
}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    files = sorted(NOTICE_DIR.glob("*.json"))
    total_items = 0

    for path in files:
        silver = json.loads(path.read_text(encoding="utf-8"))
        notice_id = silver.get("notice_id")
        if set(silver) != EXPECTED_NOTICE_FIELDS:
            errors.append(f"{path.name}: top-level fields differ: {sorted(set(silver) ^ EXPECTED_NOTICE_FIELDS)}")
        if path.stem != notice_id:
            errors.append(f"{path.name}: filename and notice_id differ")
            continue
        if silver.get("annotation_method") not in {"gold_guided_rules_silver", "deepseek_api_fewshot_silver"}:
            errors.append(f"{notice_id}: unexpected annotation_method")
        if silver.get("review_status") not in {"silver_unreviewed", "silver_api_unreviewed"}:
            errors.append(f"{notice_id}: unexpected review_status")
        if silver.get("silver_confidence") not in {"high", "medium", "low"}:
            errors.append(f"{notice_id}: invalid silver_confidence")

        block_payload = json.loads((BLOCK_DIR / f"{notice_id}.json").read_text(encoding="utf-8"))
        blocks = {block["block_id"]: block for block in block_payload.get("blocks", [])}
        items = silver.get("items", [])
        total_items += len(items)
        if [item.get("item_no") for item in items] != list(range(1, len(items) + 1)):
            errors.append(f"{notice_id}: item_no must be unique and sequential from 1")

        for item in items:
            loc = f"{notice_id} item {item.get('item_no')}"
            missing = REQUIRED_ITEM_FIELDS - item.keys()
            if missing:
                errors.append(f"{loc}: missing fields {sorted(missing)}")
                continue
            extra = item.keys() - REQUIRED_ITEM_FIELDS
            if extra:
                errors.append(f"{loc}: unexpected fields {sorted(extra)}")
            if not item["product_service_name"]:
                errors.append(f"{loc}: empty product_service_name")
            for field in ("category_name", "category_code", "brand_supplier", "spec_model", "quantity_unit"):
                if item[field] in {"/", "-", "—", "无", "不涉及"}:
                    errors.append(f"{loc}: placeholder must be null in {field}")
            for field in ("unit_price", "quantity", "total_price"):
                value = item[field]
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    errors.append(f"{loc}: {field} must be non-negative number or null")

            block = blocks.get(item["source_block_id"])
            if block is None:
                errors.append(f"{loc}: source_block_id not found")
                continue
            row_index = item["source_block_row"] - 1
            rows = block.get("rows") or []
            if row_index < 0 or row_index >= len(rows):
                errors.append(f"{loc}: source_block_row out of range")
                continue
            expected_evidence = json.dumps(rows[row_index], ensure_ascii=False, separators=(",", ":"))
            if item["evidence_text"] != expected_evidence:
                errors.append(f"{loc}: evidence_text does not equal exact Block row")

            up, qty, total = item["unit_price"], item["quantity"], item["total_price"]
            consistency = item.get("silver_price_consistency")
            if up is not None and qty is not None and total is not None:
                tolerance = max(0.01, abs(total) * 1e-6)
                is_ok = abs(up * qty - total) <= tolerance
                if consistency == "ok" and not is_ok:
                    errors.append(f"{loc}: consistency claims ok but {up}*{qty}!={total}")
                if consistency == "mismatch" and is_ok:
                    warnings.append(f"{loc}: consistency claims mismatch but values are consistent")
            elif consistency != "not_checkable":
                errors.append(f"{loc}: consistency should be not_checkable when fields are missing")

    manifest = json.loads((SILVER_DIR / "silver_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("notice_count") != len(files) or manifest.get("item_count") != total_items:
        errors.append("silver_manifest.json: notice_count/item_count does not match notice files")
    jsonl_count = sum(1 for line in (SILVER_DIR / "silver_items.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())
    if jsonl_count != total_items:
        errors.append(f"silver_items.jsonl: expected {total_items} lines, got {jsonl_count}")

    report = {
        "status": "passed" if not errors else "failed",
        "notice_count": len(files),
        "item_count": total_items,
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings[:200],
    }
    (SILVER_DIR / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
