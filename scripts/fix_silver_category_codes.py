# -*- coding: utf-8 -*-
"""Backfill category_code from the exact category_name source cell in API silver files."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_silver_labels as rules  # noqa: E402

SILVER_DIR = ROOT / "dataset_build" / "silver" / "notices"
BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"


def main() -> int:
    fixed = 0
    for path in sorted(SILVER_DIR.glob("*.json")):
        notice = json.loads(path.read_text(encoding="utf-8"))
        selected = notice.get("selected_table", {})
        fields = set(selected.get("matched_fields", []))
        if "category_name" not in fields or "category_code" in fields:
            continue
        block_payload = json.loads((BLOCK_DIR / f"{notice['notice_id']}.json").read_text(encoding="utf-8"))
        block = next(b for b in block_payload["blocks"] if b.get("block_id") == selected.get("block_id"))
        rows = block.get("rows") or []
        columns = rules.match_columns(selected.get("header", []))
        idx = columns.get("category_name")
        if idx is None:
            continue
        changed = 0
        for item in notice["items"]:
            row_no = item["source_block_row"]
            if not (0 < row_no <= len(rows)):
                continue
            row = rows[row_no - 1]
            cell = row[idx] if idx < len(row) else None
            name, code = rules.split_category_safe(cell)
            if code:
                item["category_code"] = code
                item["category_name"] = name or item.get("category_name")
                changed += 1
        if changed:
            path.write_text(json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            fixed += 1
    print(f"fixed {fixed} notice files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
