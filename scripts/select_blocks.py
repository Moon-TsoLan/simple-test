# -*- coding: utf-8 -*-
"""Build local, API-ready entity-extraction inputs from Block notices."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extraction.block_selector import SELECTOR_VERSION, SelectorConfig, select_notice  # noqa: E402

DEFAULT_BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
DEFAULT_OUTPUT_DIR = ROOT / "dataset_build" / "model_inputs"
DEFAULT_GOLD_DIR = ROOT / "dataset_build" / "gold" / "notices"


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def evidence_keys(package: dict[str, Any]) -> tuple[set[str], set[tuple[str, int]]]:
    block_ids: set[str] = set()
    rows: set[tuple[str, int]] = set()
    for request in package.get("requests", []):
        block_ids.update(request.get("source_block_ids") or [])
        messages = request.get("api_payload", {}).get("messages", [])
        if not messages:
            continue
        try:
            user = json.loads(messages[-1]["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        evidence = user.get("evidence") or {}
        if evidence.get("kind") == "table":
            block_id = evidence.get("block_id")
            if block_id:
                for row in evidence.get("data_rows") or []:
                    if isinstance(row.get("block_row"), int):
                        rows.add((block_id, row["block_row"]))
    return block_ids, rows


def evaluate_gold(packages: dict[str, dict[str, Any]], gold_dir: Path) -> dict[str, Any]:
    if not gold_dir.exists():
        return {"available": False, "reason": f"gold directory not found: {gold_dir}"}
    expected_blocks: set[tuple[str, str]] = set()
    expected_rows: set[tuple[str, str, int]] = set()
    notice_count = 0
    item_count = 0
    per_notice: list[dict[str, Any]] = []
    for path in sorted(gold_dir.glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        notice_id = str(gold.get("notice_id") or path.stem)
        if notice_id not in packages:
            continue
        notice_count += 1
        gold_rows: set[tuple[str, int]] = set()
        gold_blocks: set[str] = set()
        for item in gold.get("items") or []:
            block_id = item.get("source_block_id")
            row_number = item.get("source_block_row")
            if block_id:
                gold_blocks.add(block_id)
                expected_blocks.add((notice_id, block_id))
            if block_id and isinstance(row_number, int):
                gold_rows.add((block_id, row_number))
                expected_rows.add((notice_id, block_id, row_number))
            item_count += 1
        selected_blocks, selected_rows = evidence_keys(packages.get(notice_id, {}))
        per_notice.append({
            "notice_id": notice_id,
            "gold_block_count": len(gold_blocks),
            "retained_block_count": len(gold_blocks & selected_blocks),
            "gold_evidence_row_count": len(gold_rows),
            "retained_evidence_row_count": len(gold_rows & selected_rows),
        })

    retained_blocks = sum(
        (notice_id, block_id) in expected_blocks
        for notice_id, package in packages.items()
        for block_id in evidence_keys(package)[0]
    )
    retained_rows = sum(
        (notice_id, block_id, row_number) in expected_rows
        for notice_id, package in packages.items()
        for block_id, row_number in evidence_keys(package)[1]
    )
    return {
        "available": True,
        "gold_notice_count": notice_count,
        "gold_item_count": item_count,
        "gold_source_block_count": len(expected_blocks),
        "retained_source_block_count": retained_blocks,
        "source_block_recall": round(retained_blocks / len(expected_blocks), 4) if expected_blocks else 1.0,
        "gold_evidence_row_count": len(expected_rows),
        "retained_evidence_row_count": retained_rows,
        "evidence_row_recall": round(retained_rows / len(expected_rows), 4) if expected_rows else 1.0,
        "per_notice": per_notice,
    }


def validate_packages(packages: dict[str, dict[str, Any]], block_dir: Path) -> dict[str, Any]:
    """Check that every generated request can be parsed and cites real evidence."""
    errors: list[str] = []
    request_ids: set[str] = set()
    checked_requests = 0
    checked_rows = 0
    for notice_id, package in packages.items():
        block_path = block_dir / f"{notice_id}.json"
        if not block_path.exists():
            errors.append(f"{notice_id}: source block file missing")
            continue
        source_payload = json.loads(block_path.read_text(encoding="utf-8"))
        source_blocks = {block.get("block_id"): block for block in source_payload.get("blocks") or [] if block.get("block_id")}
        for request in package.get("requests") or []:
            checked_requests += 1
            request_id = request.get("request_id")
            if not request_id or request_id in request_ids:
                errors.append(f"{notice_id}: missing or duplicate request_id={request_id}")
            request_ids.add(request_id)
            messages = request.get("api_payload", {}).get("messages") or []
            if len(messages) != 2 or [message.get("role") for message in messages] != ["system", "user"]:
                errors.append(f"{request_id}: messages must contain system and user")
                continue
            try:
                user = json.loads(messages[1].get("content") or "")
            except json.JSONDecodeError as exc:
                errors.append(f"{request_id}: user content is not JSON: {exc}")
                continue
            evidence = user.get("evidence") or {}
            cited_ids = request.get("source_block_ids") or []
            for block_id in cited_ids:
                if block_id not in source_blocks:
                    errors.append(f"{request_id}: unknown block_id={block_id}")
            if evidence.get("kind") == "table":
                block_id = evidence.get("block_id")
                source_rows = (source_blocks.get(block_id) or {}).get("rows") or []
                header_block_id = evidence.get("header_source_block_id")
                header_rows = (source_blocks.get(header_block_id) or {}).get("rows") or []
                header_row_number = evidence.get("header_block_row")
                if not isinstance(header_row_number, int) or not 1 <= header_row_number <= len(header_rows):
                    errors.append(f"{request_id}: invalid inherited/local header row for {header_block_id}")
                for row in evidence.get("data_rows") or []:
                    checked_rows += 1
                    row_number = row.get("block_row")
                    if not isinstance(row_number, int) or not 1 <= row_number <= len(source_rows):
                        errors.append(f"{request_id}: invalid block_row={row_number} for {block_id}")
                        continue
                    expected_cells = [" ".join(str(cell or "").split())[:1200] for cell in source_rows[row_number - 1]]
                    if row.get("cells") != expected_cells:
                        errors.append(f"{request_id}: row cells differ from source {block_id} row {row_number}")
            elif evidence.get("kind") == "text":
                for item in evidence.get("blocks") or []:
                    block_id = item.get("block_id")
                    source_block = source_blocks.get(block_id) or {}
                    source_text = " ".join(str(source_block.get("text") or "").split())
                    char_start, char_end = item.get("char_start"), item.get("char_end")
                    if not isinstance(char_start, int) or not isinstance(char_end, int):
                        errors.append(f"{request_id}: missing text offsets for {block_id}")
                    elif item.get("text") != source_text[char_start:char_end]:
                        errors.append(f"{request_id}: text differs from source {block_id} chars {char_start}:{char_end}")
    return {
        "checked_request_count": checked_requests,
        "checked_table_row_count": checked_rows,
        "error_count": len(errors),
        "errors": errors[:100],
    }


def output_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "招采公告大模型输入包",
        "type": "object",
        "required": ["schema_version", "selector_version", "notice_id", "stats", "requests"],
        "properties": {
            "schema_version": {"const": "1.0"},
            "selector_version": {"type": "string"},
            "selector_config_digest": {"type": "string"},
            "notice_id": {"type": "string"},
            "stats": {"type": "object"},
            "requests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["request_id", "content_kind", "source_block_ids", "api_payload"],
                    "properties": {
                        "request_id": {"type": "string"},
                        "content_kind": {"enum": ["table", "text"]},
                        "source_block_ids": {"type": "array", "items": {"type": "string"}},
                        "api_payload": {
                            "type": "object",
                            "required": ["messages", "temperature", "response_format"],
                        },
                    },
                },
            },
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block-dir", type=Path, default=DEFAULT_BLOCK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--ids", nargs="*", help="only process these notice IDs")
    parser.add_argument("--limit", type=int, default=0, help="process at most N notices; 0 means all")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--table-min-score", type=int, default=SelectorConfig.table_min_score)
    parser.add_argument("--text-min-score", type=int, default=SelectorConfig.text_min_score)
    parser.add_argument("--context-window", type=int, default=SelectorConfig.context_window)
    parser.add_argument("--max-table-rows", type=int, default=SelectorConfig.max_table_rows_per_request)
    parser.add_argument("--max-input-chars", type=int, default=SelectorConfig.max_input_chars_per_request)
    parser.add_argument("--max-text-requests", type=int, default=SelectorConfig.max_text_requests_per_notice)
    parser.add_argument("--max-table-sources", type=int, default=SelectorConfig.max_table_sources_per_notice)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = SelectorConfig(
        table_min_score=args.table_min_score,
        text_min_score=args.text_min_score,
        context_window=args.context_window,
        max_table_rows_per_request=args.max_table_rows,
        max_input_chars_per_request=args.max_input_chars,
        max_text_requests_per_notice=args.max_text_requests,
        max_table_sources_per_notice=args.max_table_sources,
    )
    paths = sorted(args.block_dir.glob("*.json"))
    if args.ids:
        wanted = set(args.ids)
        paths = [path for path in paths if path.stem in wanted]
    if args.limit > 0:
        paths = paths[: args.limit]
    if not paths:
        print("未找到待筛选的 Block 公告。", file=sys.stderr)
        return 2

    notice_dir = args.output_dir / "notices"
    notice_dir.mkdir(parents=True, exist_ok=True)
    packages: dict[str, dict[str, Any]] = {}
    counters = Counter()
    parser_versions = Counter()
    for path in paths:
        destination = notice_dir / path.name
        if destination.exists() and not args.overwrite:
            package = json.loads(destination.read_text(encoding="utf-8"))
            counters["skipped_existing"] += 1
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            package = select_notice(payload, config)
            write_json_atomic(destination, package)
            counters["written"] += 1
        notice_id = str(package.get("notice_id") or path.stem)
        packages[notice_id] = package
        stats = package.get("stats") or {}
        counters["original_blocks"] += int(stats.get("original_block_count") or 0)
        counters["selected_source_blocks"] += int(stats.get("selected_source_block_count") or 0)
        counters["requests"] += int(stats.get("request_count") or 0)
        counters["estimated_input_chars"] += int(stats.get("estimated_input_chars") or 0)
        counters["inherited_header_tables"] += int(stats.get("inherited_header_table_count") or 0)
        counters["deduplicated_requests"] += int(stats.get("deduplicated_request_count") or 0)
        counters["table_source_limit_notices"] += int(bool(stats.get("table_source_limit_triggered")))
        counters["table_blocks_excluded_by_source_limit"] += int(
            stats.get("table_blocks_excluded_by_source_limit") or 0
        )
        counters["text_request_limit_notices"] += int(bool(stats.get("text_request_limit_triggered")))
        counters["text_groups_excluded_by_request_limit"] += int(
            stats.get("text_groups_excluded_by_request_limit") or 0
        )
        counters["no_candidate"] += int((stats.get("request_count") or 0) == 0)
        parser_versions[str(package.get("source_parser_version") or "unknown")] += 1

    request_file = args.output_dir / "api_requests.jsonl"
    request_file.parent.mkdir(parents=True, exist_ok=True)
    with request_file.open("w", encoding="utf-8", newline="\n") as handle:
        for notice_id, package in sorted(packages.items()):
            for request in package.get("requests") or []:
                handle.write(json.dumps({
                    "notice_id": notice_id,
                    "request_id": request["request_id"],
                    "content_kind": request["content_kind"],
                    "source_block_ids": request["source_block_ids"],
                    "api_payload": request["api_payload"],
                }, ensure_ascii=False, separators=(",", ":")) + "\n")

    gold_evaluation = evaluate_gold(packages, args.gold_dir)
    integrity = validate_packages(packages, args.block_dir)
    reduction = 1 - counters["selected_source_blocks"] / counters["original_blocks"] if counters["original_blocks"] else 0
    report = {
        "selector_version": SELECTOR_VERSION,
        "selector_config": config.__dict__,
        "notice_count": len(packages),
        "written_notice_count": counters["written"],
        "skipped_existing_notice_count": counters["skipped_existing"],
        "no_candidate_notice_count": counters["no_candidate"],
        "original_block_count": counters["original_blocks"],
        "selected_source_block_count": counters["selected_source_blocks"],
        "block_reduction_ratio": round(reduction, 4),
        "api_request_count": counters["requests"],
        "estimated_input_chars": counters["estimated_input_chars"],
        "inherited_header_table_count": counters["inherited_header_tables"],
        "deduplicated_request_count": counters["deduplicated_requests"],
        "table_source_limit_notice_count": counters["table_source_limit_notices"],
        "table_blocks_excluded_by_source_limit": counters["table_blocks_excluded_by_source_limit"],
        "text_request_limit_notice_count": counters["text_request_limit_notices"],
        "text_groups_excluded_by_request_limit": counters["text_groups_excluded_by_request_limit"],
        "source_parser_versions": dict(parser_versions),
        "integrity": integrity,
        "gold_evaluation": gold_evaluation,
    }
    write_json_atomic(args.output_dir / "selection_report.json", report)
    write_json_atomic(args.output_dir / "model_input_schema.json", output_schema())

    markdown = [
        "# Block 本地筛选报告", "",
        f"- 筛选器版本：`{SELECTOR_VERSION}`",
        f"- 公告数：{len(packages)}",
        f"- 无候选公告：{counters['no_candidate']}",
        f"- 原始 Blocks：{counters['original_blocks']}",
        f"- 入选来源 Blocks：{counters['selected_source_blocks']}",
        f"- Block 压缩率：{reduction:.2%}",
        f"- API 请求包：{counters['requests']}",
        f"- 估算输入字符：{counters['estimated_input_chars']}", "",
        f"- 跨页继承表头的表格：{counters['inherited_header_tables']}",
        f"- 去除重复请求：{counters['deduplicated_requests']}", "",
        "## 限额触发", "",
        f"- 表格来源上限触发公告：{counters['table_source_limit_notices']}",
        f"- 因表格来源上限未选 Block：{counters['table_blocks_excluded_by_source_limit']}",
        f"- 正文请求上限触发公告：{counters['text_request_limit_notices']}",
        f"- 因正文请求上限未选分组：{counters['text_groups_excluded_by_request_limit']}", "",
        "## 完整性校验", "",
        f"- 已检查请求：{integrity['checked_request_count']}",
        f"- 已检查表格行：{integrity['checked_table_row_count']}",
        f"- 错误：{integrity['error_count']}", "",
        "## 金标证据保留", "",
    ]
    if gold_evaluation.get("available"):
        markdown.extend([
            f"- 金标来源 Block 召回率：{gold_evaluation['source_block_recall']:.2%}",
            f"- 金标证据行召回率：{gold_evaluation['evidence_row_recall']:.2%}",
        ])
    else:
        markdown.append(f"- 未评估：{gold_evaluation.get('reason')}")
    markdown.extend(["", "`api_requests.jsonl` 每行的 `api_payload` 可直接传给 OpenAI 兼容接口。", ""])
    (args.output_dir / "selection_report.md").write_text("\n".join(markdown), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if integrity["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
