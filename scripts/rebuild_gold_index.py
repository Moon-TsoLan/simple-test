# -*- coding: utf-8 -*-
"""Rebuild gold_manifest.json and gold_items.jsonl from notice JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def source_type(item: dict[str, Any]) -> str:
    location = str(item.get("source_location") or "")
    if location:
        return location.split(",", 1)[0].lower()
    suffix = Path(str(item.get("source_file") or "")).suffix.lower().lstrip(".")
    return suffix or "unknown"


def rebuild_indexes(gold_dir: Path) -> dict[str, Any]:
    notice_dir = gold_dir / "notices"
    notices = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(notice_dir.glob("*.json"))]
    manifest = {
        "annotation_version": "1.1.0",
        "notice_count": len(notices),
        "item_count": sum(len(notice.get("items") or []) for notice in notices),
        "notices": [
            {
                "notice_id": notice["notice_id"],
                "title": notice["title"],
                "item_count": len(notice.get("items") or []),
                "source_parser_version": notice.get("source_parser_version"),
                "source_parser_config_digest": notice.get("source_parser_config_digest"),
                "source_types": sorted({source_type(item) for item in notice.get("items") or []}),
                "file": f"notices/{notice['notice_id']}.json",
            }
            for notice in notices
        ],
    }
    (gold_dir / "gold_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (gold_dir / "gold_items.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for notice in notices:
            for item in notice.get("items") or []:
                handle.write(json.dumps(
                    {"notice_id": notice["notice_id"], "title": notice["title"], **item},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "dataset_build" / "gold")
    args = parser.parse_args()
    manifest = rebuild_indexes(args.gold_dir)
    print(json.dumps({
        "notice_count": manifest["notice_count"],
        "item_count": manifest["item_count"],
        "manifest": str(args.gold_dir / "gold_manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
