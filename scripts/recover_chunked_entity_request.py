# -*- coding: utf-8 -*-
"""Recover an oversized text request by bounded per-Block API calls."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_entity_agent import _build_backend, load_jsonl  # noqa: E402
from src.agents.backends import BudgetedBackend  # noqa: E402
from src.agents.entity_extraction_agent import AgentConfig, EntityExtractionAgent  # noqa: E402
from src.agents.tools import parse_request_evidence  # noqa: E402


def _split_request(request: dict[str, Any]) -> list[dict[str, Any]]:
    user_input, evidence = parse_request_evidence(request)
    if evidence.get("kind") != "text" or len(evidence.get("blocks") or []) <= 1:
        return [request]
    parts: list[dict[str, Any]] = []
    for index, block in enumerate(evidence.get("blocks") or [], 1):
        part = deepcopy(request)
        part["request_id"] = f"{request['request_id']}:part_{index:03d}"
        part["source_block_ids"] = [block.get("block_id")]
        part_user = deepcopy(user_input)
        part_user["instruction"] = (
            "这是超长证据拆分后的单个来源Block。只抽取本Block中可直接证明的实际中标/成交条目；"
            "跳过小计、合计、说明和预留费用。"
        )
        part_user["evidence"] = {"kind": "text", "blocks": [block]}
        for message in part["api_payload"]["messages"]:
            if message.get("role") == "user":
                message["content"] = json.dumps(part_user, ensure_ascii=False, separators=(",", ":"))
        parts.append(part)
    return parts


def _usage_sum(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "estimated_cost_yuan": 0.0,
    }
    for outcome in outcomes:
        for key in total:
            total[key] += (outcome.get("usage") or {}).get(key, 0) or 0
    total["estimated_cost_yuan"] = round(float(total["estimated_cost_yuan"]), 6)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "dataset_build" / "model_inputs" / "api_requests.jsonl")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "llm_config.yaml")
    parser.add_argument("--allow-external-api", action="store_true")
    parser.add_argument("--max-model-calls", type=int, required=True)
    parser.add_argument("--max-total-tokens", type=int, default=200000)
    args = parser.parse_args()
    args.backend = "api"
    if not args.allow_external_api:
        parser.error("external API recovery requires --allow-external-api")

    matches = [record for record in load_jsonl(args.input) if record.get("request_id") == args.request_id]
    if len(matches) != 1:
        parser.error(f"request-id must match exactly one request, found {len(matches)}")
    parts = _split_request(matches[0])
    backend = BudgetedBackend(
        _build_backend(args),
        max_calls=args.max_model_calls,
        max_total_tokens=args.max_total_tokens,
    )
    agent = EntityExtractionAgent(
        backend,
        AgentConfig(enable_rule_fast_path=False, max_repair_attempts=1, skip_text_when_covered_by_strong_table=False),
    )
    outcomes: list[dict[str, Any]] = []
    for index, part in enumerate(parts, 1):
        outcome = agent.process_request(part)
        outcomes.append(outcome)
        print(f"[{index}/{len(parts)}] {part['request_id']} {outcome['status']} {outcome.get('method')}", flush=True)

    errors = [error for outcome in outcomes for error in outcome.get("errors") or []]
    failed_parts = [outcome["request_id"] for outcome in outcomes if outcome.get("status") != "success"]
    combined = {
        "request_id": args.request_id,
        "notice_id": str(matches[0].get("notice_id") or args.request_id.split(":", 1)[0]),
        "content_kind": "text",
        "status": "success" if not failed_parts else "failed",
        "method": "model_chunked_recovery" if not failed_parts else "model_chunked_recovery_failed",
        "confidence": 0.78 if not failed_parts else 0.0,
        "confidence_basis": "validated_per_source_block_after_output_overflow" if not failed_parts else None,
        "repair_attempts": sum(int(outcome.get("repair_attempts") or 0) for outcome in outcomes),
        "warnings": [
            "oversized text evidence was recovered with one bounded model request per source Block",
            *[warning for outcome in outcomes for warning in outcome.get("warnings") or []],
        ],
        "errors": errors,
        "items": [item for outcome in outcomes for item in outcome.get("items") or []],
        "usage": _usage_sum(outcomes),
        "workflow_trace": ["chunk_text_evidence", "process_parts", "combine_validated_parts"],
        "failed_parts": failed_parts,
    }
    payload = {
        "schema_version": "1.0",
        "source_request_id": args.request_id,
        "part_count": len(parts),
        "budget": backend.budget_report(),
        "outcomes": {args.request_id: combined},
        "parts": outcomes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "request_id": args.request_id,
        "status": combined["status"],
        "part_count": len(parts),
        "item_count": len(combined["items"]),
        "usage": combined["usage"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0 if combined["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())

