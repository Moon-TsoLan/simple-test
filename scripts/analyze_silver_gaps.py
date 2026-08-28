# -*- coding: utf-8 -*-
"""Explain why some converted notices did not receive silver labels."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_silver_labels as silver  # noqa: E402
from build_silver_labels import BLOCK_DIR, SILVER_DIR  # noqa: E402


def main() -> int:
    manifest = json.loads((SILVER_DIR / "silver_manifest.json").read_text(encoding="utf-8"))
    labeled = {n["notice_id"] for n in manifest["notices"]} | set(manifest.get("excluded_gold_notices", []))
    unlabeled_rows = []
    file_types = Counter()
    reason = Counter()
    for path in sorted(BLOCK_DIR.glob("*.json")):
        nid = path.stem
        if nid in labeled:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidates = silver.table_candidates(payload)
        tables = [b for b in payload.get("blocks", []) if b.get("type") == "table"]
        # Best effort header coverage of the most promising table.
        best = None
        for block in tables:
            table_rows = block.get("rows") or []
            if not table_rows:
                continue
            columns = silver.match_columns([str(c) for c in table_rows[0]])
            fields = sorted(columns)
            if best is None or len(fields) > len(best["fields"]):
                best = {"block_id": block.get("block_id"), "fields": fields,
                        "header": [str(c) for c in table_rows[0]], "source": block.get("source", {})}
        if best is None:
            reason["no_table"] += 1
        elif "product_service_name" not in best["fields"]:
            reason["no_product_column"] += 1
        elif len(set(best["fields"]) & silver.PRODUCT_TABLE_FIELDS) < 2:
            reason["too_few_product_fields"] += 1
        elif candidates:
            reason["score_or_item_filter"] += 1
        else:
            reason["other"] += 1
        file_types[str(best["source"].get("file_type") if best else "none")] += 1
        unlabeled_rows.append({
            "notice_id": nid,
            "title": payload.get("title"),
            "table_count": len(tables),
            "best_table": best,
        })
    out = {
        "unlabeled_notice_count": len(unlabeled_rows),
        "reason_counts": dict(reason),
        "file_type_counts": dict(file_types),
        "notices": unlabeled_rows,
    }
    out_path = SILVER_DIR / "unlabeled_notice_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"unlabeled": len(unlabeled_rows), "reason_counts": dict(reason),
                      "file_type_counts": dict(file_types), "report": str(out_path)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
