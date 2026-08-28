# -*- coding: utf-8 -*-
"""Re-number silver items sequentially by source_block_row (chunk-merge fix)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE_DIR = ROOT / "dataset_build" / "silver" / "notices"


def main() -> int:
    fixed = 0
    for path in sorted(NOTICE_DIR.glob("*.json")):
        notice = json.loads(path.read_text(encoding="utf-8"))
        items = sorted(notice.get("items", []), key=lambda item: item["source_block_row"])
        expected = list(range(1, len(items) + 1))
        if [i.get("item_no") for i in items] == expected:
            continue
        for no, item in enumerate(items, 1):
            item["item_no"] = no
        notice["items"] = items
        path.write_text(json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fixed += 1
    print(f"fixed {fixed} notice files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
