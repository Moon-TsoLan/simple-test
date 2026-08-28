"""Validate gold labels against their exact source Blocks."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "dataset_build" / "gold"
NOTICE_DIR = GOLD_DIR / "notices"
BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
MIN_EXPECTED_NOTICE_COUNT = 10
EXPECTED_NOTICE_FIELDS = {
    "notice_id", "title", "source_parser_version", "source_parser_config_digest",
    "annotation_version", "annotation_method",
    "review_status", "selection_reason", "items",
}
REQUIRED_ITEM_FIELDS = {
    "item_no", "product_service_name", "category_name", "category_code",
    "brand_supplier", "spec_model", "unit_price", "quantity", "quantity_unit",
    "total_price", "source_block_id", "source_block_row", "source_document_id",
    "source_file", "source_container_path", "source_location", "evidence_text",
}


def fail(errors: list[str], location: str, message: str) -> None:
    errors.append(f"{location}: {message}")


def main() -> int:
    errors: list[str] = []
    files = sorted(NOTICE_DIR.glob("*.json"))
    if len(files) < MIN_EXPECTED_NOTICE_COUNT:
        fail(errors, "gold/notices", f"expected at least {MIN_EXPECTED_NOTICE_COUNT} JSON files, got {len(files)}")
    total_items = 0

    for path in files:
        gold = json.loads(path.read_text(encoding="utf-8"))
        notice_id = gold.get("notice_id")
        if set(gold) != EXPECTED_NOTICE_FIELDS:
            fail(errors, path.name,
                 f"top-level fields differ from Schema: {sorted(set(gold) ^ EXPECTED_NOTICE_FIELDS)}")
        if gold.get("annotation_method") != "manual_curated_from_verified_blocks":
            fail(errors, path.name, "unexpected annotation_method")
        if gold.get("review_status") != "single_annotator_gold_seed":
            fail(errors, path.name, "unexpected review_status")
        if str(gold.get("source_parser_version", "")).startswith("2."):
            digest = gold.get("source_parser_config_digest")
            if not isinstance(digest, str) or len(digest) != 64:
                fail(errors, path.name, "v2 gold source must carry a 64-character parser_config_digest")
        if path.stem != notice_id:
            fail(errors, path.name, "filename and notice_id differ")
            continue
        block_payload = json.loads((BLOCK_DIR / f"{notice_id}.json").read_text(encoding="utf-8"))
        if gold.get("source_parser_version") != block_payload.get("parser_version"):
            fail(errors, notice_id, "source_parser_version differs from current Block source")
        if gold.get("source_parser_config_digest") != block_payload.get("parser_config_digest"):
            fail(errors, notice_id, "source_parser_config_digest differs from current Block source")
        blocks = {block["block_id"]: block for block in block_payload.get("blocks", [])}
        items = gold.get("items", [])
        total_items += len(items)
        item_numbers = [item.get("item_no") for item in items]
        if item_numbers != list(range(1, len(items) + 1)):
            fail(errors, notice_id, "item_no must be unique and sequential from 1")

        for item in items:
            location = f"{notice_id} item {item.get('item_no')}"
            missing = REQUIRED_ITEM_FIELDS - item.keys()
            if missing:
                fail(errors, location, f"missing fields: {sorted(missing)}")
                continue
            extra = item.keys() - REQUIRED_ITEM_FIELDS
            if extra:
                fail(errors, location, f"fields outside Schema: {sorted(extra)}")
            if not item["product_service_name"]:
                fail(errors, location, "product_service_name is empty")
            for field in ("category_name", "category_code", "brand_supplier", "spec_model", "quantity_unit"):
                if item[field] in {"/", "-", "—", "无", "不涉及"}:
                    fail(errors, location, f"placeholder {item[field]!r} must be normalised to null in {field}")
            for field in ("unit_price", "quantity", "total_price"):
                value = item[field]
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    fail(errors, location, f"{field} must be a non-negative number or null")

            block = blocks.get(item["source_block_id"])
            if block is None:
                fail(errors, location, "source_block_id does not exist")
                continue
            row_index = item["source_block_row"] - 1
            rows = block.get("rows") or []
            if row_index < 0 or row_index >= len(rows):
                fail(errors, location, "source_block_row is out of range")
                continue
            expected_evidence = json.dumps(rows[row_index], ensure_ascii=False, separators=(",", ":"))
            if item["evidence_text"] != expected_evidence:
                fail(errors, location, "evidence_text is not the exact referenced Block row")

            unit_price, qty, total = item["unit_price"], item["quantity"], item["total_price"]
            if unit_price is not None and qty is not None and total is not None:
                tolerance = max(0.01, abs(total) * 1e-6)
                if abs(unit_price * qty - total) > tolerance:
                    fail(errors, location,
                         f"amount mismatch: {unit_price} * {qty} != {total} (tol={tolerance})")

    manifest = json.loads((GOLD_DIR / "gold_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("notice_count") != len(files) or manifest.get("item_count") != total_items:
        fail(errors, "gold_manifest.json", "notice_count/item_count does not match notice files")
    jsonl_count = sum(1 for line in (GOLD_DIR / "gold_items.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())
    if jsonl_count != total_items:
        fail(errors, "gold_items.jsonl", f"expected {total_items} lines, got {jsonl_count}")

    report = {
        "status": "passed" if not errors else "failed",
        "notice_count": len(files),
        "item_count": total_items,
        "checks": [
            "at least 10 notice JSON files",
            "required fields and sequential item numbers",
            "non-negative numeric values",
            "unit_price * quantity ~= total_price when all are present",
            "source_block_id/source_block_row existence",
            "evidence_text exact match to referenced Block row",
            "manifest and JSONL counts",
        ],
        "errors": errors,
    }
    (GOLD_DIR / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
