# -*- coding: utf-8 -*-
"""Build deterministic offline agent responses from verified gold evidence.

This utility does not estimate model accuracy.  It converts the manually
verified gold seed into request-id keyed responses so the real validation,
merge and persistence pipeline can be tested without a model or network call.
Every gold item must be present in exactly one selected evidence request.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "product_service_name",
    "category_name",
    "category_code",
    "brand_supplier",
    "spec_model",
    "unit_price",
    "quantity",
    "quantity_unit",
    "total_price",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            records.append(value)
    return records


def parse_evidence(request: dict[str, Any]) -> dict[str, Any]:
    messages = ((request.get("api_payload") or {}).get("messages") or [])
    user_messages = [message for message in messages if message.get("role") == "user"]
    if len(user_messages) != 1:
        raise ValueError(f"{request.get('request_id')}: expected exactly one user message")
    payload = json.loads(user_messages[0].get("content") or "")
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError(f"{request.get('request_id')}: evidence is not an object")
    return evidence


def evidence_keys(request: dict[str, Any]) -> set[tuple[str, int | None]]:
    evidence = parse_evidence(request)
    if evidence.get("kind") == "table":
        block_id = str(evidence.get("block_id") or "")
        return {
            (block_id, int(row["block_row"]))
            for row in evidence.get("data_rows") or []
            if block_id and isinstance(row.get("block_row"), int)
        }
    return {
        (str(block.get("block_id")), None)
        for block in evidence.get("blocks") or []
        if block.get("block_id")
    }


def build_replay(
    requests: list[dict[str, Any]],
    gold_paths: list[Path],
    *,
    allow_missing: bool = False,
) -> dict[str, Any]:
    request_by_id: dict[str, dict[str, Any]] = {}
    requests_by_notice: dict[str, list[str]] = defaultdict(list)
    coverage_index: dict[tuple[str, int | None], list[str]] = defaultdict(list)
    responses: dict[str, dict[str, Any]] = {}

    for request in requests:
        request_id = str(request.get("request_id") or "")
        notice_id = str(request.get("notice_id") or request_id.split(":", 1)[0])
        if not request_id or request_id in request_by_id:
            raise ValueError(f"missing or duplicate request_id={request_id!r}")
        request_by_id[request_id] = request
        requests_by_notice[notice_id].append(request_id)
        for key in evidence_keys(request):
            coverage_index[key].append(request_id)
        responses[request_id] = {
            "items": [],
            "warnings": ["金标范围内该 evidence 不含需抽取的实际中标条目"],
        }

    selected_notice_ids = set(requests_by_notice)
    gold_notice_count = 0
    gold_item_count = 0
    assigned_item_count = 0
    missing: list[dict[str, Any]] = []
    duplicated: list[dict[str, Any]] = []
    assigned_by_request: dict[str, int] = defaultdict(int)

    for gold_path in gold_paths:
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        notice_id = str(gold.get("notice_id") or gold_path.stem)
        if notice_id not in selected_notice_ids:
            continue
        gold_notice_count += 1
        for item in gold.get("items") or []:
            gold_item_count += 1
            block_id = str(item.get("source_block_id") or "")
            block_row = item.get("source_block_row")
            key = (block_id, int(block_row) if isinstance(block_row, int) else None)
            hits = coverage_index.get(key, [])
            # A text gold item has no row and is matched to the selected text
            # block.  Table gold items require their exact source row.
            if not hits and key[1] is None:
                hits = coverage_index.get((block_id, None), [])
            diagnostic = {
                "notice_id": notice_id,
                "item_no": item.get("item_no"),
                "product_service_name": item.get("product_service_name"),
                "source_block_id": block_id,
                "source_block_row": block_row,
            }
            if not hits:
                missing.append(diagnostic)
                continue
            if len(hits) != 1:
                duplicated.append({**diagnostic, "request_ids": hits})
                continue
            request_id = hits[0]
            replay_item = {field: item.get(field) for field in FIELDS}
            ref: dict[str, Any] = {"block_id": block_id}
            if isinstance(block_row, int):
                ref["block_row"] = block_row
            replay_item["evidence_refs"] = [ref]
            responses[request_id]["items"].append(replay_item)
            responses[request_id]["warnings"] = []
            assigned_by_request[request_id] += 1
            assigned_item_count += 1

    if (missing or duplicated) and not allow_missing:
        raise ValueError(json.dumps({
            "message": "gold evidence is not covered exactly once by selected requests",
            "missing": missing,
            "duplicated": duplicated,
        }, ensure_ascii=False, indent=2))

    return {
        "schema_version": "1.0",
        "response_source": "gold_constrained_offline_replay",
        "created_at": date.today().isoformat(),
        "annotation_note": (
            "由人工核验金标按 source_block_id/source_block_row 映射生成，仅用于验证筛选、"
            "Schema校验、合并和入库链路；不得作为模型准确率。"
        ),
        "notice_ids": sorted(selected_notice_ids),
        "coverage": {
            "gold_notice_count": gold_notice_count,
            "request_count": len(requests),
            "gold_item_count": gold_item_count,
            "assigned_item_count": assigned_item_count,
            "missing_item_count": len(missing),
            "duplicate_item_count": len(duplicated),
            "requests_with_items": sum(bool(response["items"]) for response in responses.values()),
            "assigned_items_by_request": dict(sorted(assigned_by_request.items())),
            "missing": missing,
            "duplicated": duplicated,
        },
        "responses": responses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="selected api_requests.jsonl")
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "dataset_build" / "gold" / "notices")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-missing", action="store_true", help="write diagnostics even if gold evidence is absent")
    args = parser.parse_args()
    try:
        payload = build_replay(
            load_jsonl(args.input),
            sorted(args.gold_dir.glob("*.json")),
            allow_missing=args.allow_missing,
        )
    except Exception as exc:
        print(f"failed to build gold replay: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["coverage"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
