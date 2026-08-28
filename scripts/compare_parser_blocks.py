# -*- coding: utf-8 -*-
"""Compare two Parser output directories without modifying either tree."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


def _load_notice(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _block_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(block.get("block_id")): block
        for block in payload.get("blocks") or []
        if block.get("block_id")
    }


def _table_signature(block: dict[str, Any]) -> str:
    return json.dumps(block.get("rows") or [], ensure_ascii=False, separators=(",", ":"))


def _watermark_stats(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    filtered = [block for block in blocks if (block.get("metadata") or {}).get("watermark_filtered")]
    char_count = sum(int((block.get("metadata") or {}).get("watermark_char_count") or 0) for block in filtered)
    patterns: Counter[str] = Counter()
    for block in filtered:
        for pattern in (block.get("metadata") or {}).get("watermark_patterns") or []:
            patterns[str(pattern)] += 1
    return {
        "filtered_block_count": len(filtered),
        "watermark_char_count": char_count,
        "patterns": dict(patterns.most_common(20)),
        "block_ids": [str(block.get("block_id")) for block in filtered],
        "files": sorted({
            str((block.get("source") or {}).get("container_path") or (block.get("source") or {}).get("file_name") or "")
            for block in filtered
        }),
    }


def _pdf_table_count(payload: dict[str, Any]) -> int:
    return sum(
        1
        for block in payload.get("blocks") or []
        if block.get("type") == "table"
        and str((block.get("source") or {}).get("file_type") or "").lower() == "pdf"
    )


def compare_notice(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_blocks = _block_map(old)
    new_blocks = _block_map(new)
    old_ids = set(old_blocks)
    new_ids = set(new_blocks)
    shared = old_ids & new_ids
    changed_shared = []
    changed_tables = []
    for block_id in sorted(shared):
        old_block = old_blocks[block_id]
        new_block = new_blocks[block_id]
        if (old_block.get("text") or "") != (new_block.get("text") or "") or _table_signature(old_block) != _table_signature(new_block):
            changed_shared.append(block_id)
            if old_block.get("type") == "table" or new_block.get("type") == "table":
                changed_tables.append({
                    "block_id": block_id,
                    "file": (new_block.get("source") or old_block.get("source") or {}).get("container_path"),
                    "old_chars": len(_table_signature(old_block)),
                    "new_chars": len(_table_signature(new_block)),
                    "watermark_filtered": bool((new_block.get("metadata") or {}).get("watermark_filtered")),
                })
    watermark = _watermark_stats(list(new_blocks.values()))
    return {
        "notice_id": new.get("notice_id") or old.get("notice_id"),
        "old_parser_version": old.get("parser_version"),
        "new_parser_version": new.get("parser_version"),
        "old_digest": old.get("parser_config_digest"),
        "new_digest": new.get("parser_config_digest"),
        "old_block_count": len(old.get("blocks") or []),
        "new_block_count": len(new.get("blocks") or []),
        "old_document_count": len(old.get("documents") or []),
        "new_document_count": len(new.get("documents") or []),
        "pdf_table_count": _pdf_table_count(new),
        "added_block_count": len(new_ids - old_ids),
        "removed_block_count": len(old_ids - new_ids),
        "changed_shared_block_count": len(changed_shared),
        "changed_table_count": len(changed_tables),
        "changed_tables": changed_tables[:20],
        "content_changed": bool(
            (new_ids - old_ids) or (old_ids - new_ids) or changed_shared
        ),
        "watermark": watermark,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-dir", type=Path, default=ROOT / "dataset_build" / "blocks" / "notices")
    parser.add_argument("--new-dir", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "dataset_build" / "gold" / "notices")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    old_files = {path.stem: path for path in args.old_dir.glob("*.json")}
    new_files = {path.stem: path for path in args.new_dir.glob("*.json")}
    gold_ids = {path.stem for path in args.gold_dir.glob("*.json")} if args.gold_dir.exists() else set()
    shared_ids = sorted(set(old_files) & set(new_files))

    notices: list[dict[str, Any]] = []
    for notice_id in shared_ids:
        notices.append(compare_notice(_load_notice(old_files[notice_id]), _load_notice(new_files[notice_id])))

    watermarked = [item for item in notices if item["watermark"]["filtered_block_count"]]
    content_changed = [item for item in notices if item["content_changed"]]
    gold_changed = [item for item in content_changed if item["notice_id"] in gold_ids]
    gold_watermarked = [item for item in watermarked if item["notice_id"] in gold_ids]

    report = {
        "old_dir": str(args.old_dir),
        "new_dir": str(args.new_dir),
        "compared_notice_count": len(notices),
        "only_old_count": len(set(old_files) - set(new_files)),
        "only_new_count": len(set(new_files) - set(old_files)),
        "only_old": sorted(set(old_files) - set(new_files)),
        "only_new": sorted(set(new_files) - set(old_files)),
        "watermark_notice_count": len(watermarked),
        "watermark_block_count": sum(item["watermark"]["filtered_block_count"] for item in watermarked),
        "watermark_char_count": sum(item["watermark"]["watermark_char_count"] for item in watermarked),
        "content_changed_notice_count": len(content_changed),
        "gold_notice_count": len(gold_ids),
        "gold_content_changed_count": len(gold_changed),
        "gold_watermark_notice_count": len(gold_watermarked),
        "gold_content_changed": [item["notice_id"] for item in gold_changed],
        "gold_watermark_notices": [item["notice_id"] for item in gold_watermarked],
        "watermark_notices": [
            {
                "notice_id": item["notice_id"],
                "filtered_block_count": item["watermark"]["filtered_block_count"],
                "watermark_char_count": item["watermark"]["watermark_char_count"],
                "patterns": item["watermark"]["patterns"],
                "files": item["watermark"]["files"],
                "added_block_count": item["added_block_count"],
                "removed_block_count": item["removed_block_count"],
                "changed_shared_block_count": item["changed_shared_block_count"],
                "is_gold": item["notice_id"] in gold_ids,
            }
            for item in sorted(watermarked, key=lambda item: (-item["watermark"]["watermark_char_count"], item["notice_id"]))
        ],
        "content_changed_notices": [
            {
                "notice_id": item["notice_id"],
                "added_block_count": item["added_block_count"],
                "removed_block_count": item["removed_block_count"],
                "changed_shared_block_count": item["changed_shared_block_count"],
                "changed_table_count": item["changed_table_count"],
                "watermark_filtered_block_count": item["watermark"]["filtered_block_count"],
                "is_gold": item["notice_id"] in gold_ids,
            }
            for item in content_changed
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown = [
        "# Parser 2.0 vs 2.1 隔离对比",
        "",
        f"- 旧目录：`{args.old_dir}`",
        f"- 新目录：`{args.new_dir}`",
        f"- 对比公告：{report['compared_notice_count']}",
        f"- 仅旧/仅新：{report['only_old_count']} / {report['only_new_count']}",
        f"- 记录到水印过滤的公告：{report['watermark_notice_count']}",
        f"- 过滤表格块 / 字符：{report['watermark_block_count']} / {report['watermark_char_count']}",
        f"- 内容或 Block ID 变化的公告：{report['content_changed_notice_count']}",
        f"- 金标范围内内容变化：{report['gold_content_changed_count']}",
        f"- 金标范围内有水印过滤：{report['gold_watermark_notice_count']}",
        "",
        "## 水印过滤公告",
        "",
    ]
    if not watermarked:
        markdown.append("无。")
    else:
        markdown.extend([
            "| 公告 | 过滤块 | 字符 | 金标 | 主要文件 |",
            "|---|---:|---:|---|---|",
        ])
        for item in report["watermark_notices"]:
            files = "、".join(item["files"][:3])
            markdown.append(
                f"| `{item['notice_id']}` | {item['filtered_block_count']} | {item['watermark_char_count']} | "
                f"{'是' if item['is_gold'] else '否'} | {files} |"
            )
    markdown.extend(["", "## 金标内容变化", ""])
    if not gold_changed:
        markdown.append("金标 20 篇的 Block 内容/ID 相对 Parser 2.0 无变化。")
    else:
        markdown.extend(f"- `{notice_id}`" for notice_id in report["gold_content_changed"])
    markdown_path = args.output.with_suffix(".md")
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps({
        "compared_notice_count": report["compared_notice_count"],
        "watermark_notice_count": report["watermark_notice_count"],
        "watermark_block_count": report["watermark_block_count"],
        "watermark_char_count": report["watermark_char_count"],
        "content_changed_notice_count": report["content_changed_notice_count"],
        "gold_content_changed_count": report["gold_content_changed_count"],
        "gold_watermark_notice_count": report["gold_watermark_notice_count"],
        "report": str(args.output),
        "markdown": str(markdown_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
