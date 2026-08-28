# -*- coding: utf-8 -*-
"""Rebuild curated notice outputs from append-only agent state without API calls."""
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

from scripts.run_entity_agent import _payload_signature, _write_outputs, load_jsonl  # noqa: E402
from scripts.summarize_agent_state import summarize  # noqa: E402
from src.agents.entity_extraction_agent import EntityExtractionAgent  # noqa: E402
from src.agents.source_policy import (  # noqa: E402
    evidence_document_ids,
    evidence_is_non_result,
    infer_excluded_document_ids,
)
from src.agents.tools import parse_request_evidence  # noqa: E402


def _latest_state(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        latest[(str(record.get("request_id")), str(record.get("input_digest")))] = record
    return latest


def _load_overrides(paths: list[Path]) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values = payload.get("outcomes") if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            raise ValueError(f"{path}: expected object-valued outcomes")
        overrides.update({str(key): value for key, value in values.items() if isinstance(value, dict)})
    return overrides


def _resolve_non_result_outcome(
    request: dict[str, Any],
    outcome: dict[str, Any],
    *,
    excluded_document_ids: set[str],
) -> dict[str, Any]:
    _user, evidence = parse_request_evidence(request)
    document_ids = evidence_document_ids(evidence)
    inferred_document_filter = bool(document_ids and document_ids <= excluded_document_ids)
    is_non_result, reason = evidence_is_non_result(evidence)
    if inferred_document_filter:
        is_non_result = True
        reason = "sibling_evidence_identified_non_result_document"
    if not is_non_result:
        return outcome
    resolved = deepcopy(outcome)
    resolved.update({
        "status": "success",
        "method": "local_non_result_filter_after_api",
        "confidence": 0.99,
        "confidence_basis": reason,
        "warnings": [
            *(outcome.get("warnings") or []),
            f"prior extraction was safely suppressed as non-result evidence: {reason}",
        ],
        "errors": [],
        "items": [],
        "workflow_trace": [*(outcome.get("workflow_trace") or []), "local_non_result_resolution"],
    })
    return resolved


def _add_usage(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    keys = ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_yuan")
    return {key: (left.get(key, 0) or 0) + (right.get(key, 0) or 0) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "dataset_build" / "model_inputs" / "api_requests.jsonl")
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--override", type=Path, action="append", default=[])
    args = parser.parse_args()

    requests = load_jsonl(args.input)
    state = _latest_state(args.state_file)
    overrides = _load_overrides(args.override)
    excluded_document_ids = infer_excluded_document_ids(requests)
    outcomes: list[dict[str, Any]] = []
    missing: list[str] = []
    applied_overrides = 0
    local_resolutions = 0
    recovery_usage = {key: 0 for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    for request in requests:
        request_id = str(request.get("request_id"))
        record = state.get((request_id, _payload_signature(request)))
        if record is None:
            missing.append(request_id)
            continue
        original = deepcopy(record["outcome"])
        if request_id in overrides:
            replacement = deepcopy(overrides[request_id])
            replacement["usage"] = _add_usage(original.get("usage") or {}, replacement.get("usage") or {})
            for key in recovery_usage:
                recovery_usage[key] += int((overrides[request_id].get("usage") or {}).get(key) or 0)
            outcome = replacement
            applied_overrides += 1
        else:
            outcome = _resolve_non_result_outcome(
                request,
                original,
                excluded_document_ids=excluded_document_ids,
            )
            if outcome.get("method") == "local_non_result_filter_after_api":
                local_resolutions += 1
        outcomes.append(outcome)
    if missing:
        raise ValueError(f"state is missing {len(missing)} current requests; first={missing[:5]}")

    agent = EntityExtractionAgent()
    manifest = _write_outputs(args.output, requests, outcomes, agent)
    historical = summarize(args.state_file)["historical_usage"]
    historical_with_recovery = {
        key: int(historical.get(key) or 0) + int(recovery_usage.get(key) or 0)
        for key in historical
    }
    manifest.update({
        "backend": "reused_api_state+local_postprocess",
        "rebuild_mode": "no_api_state_reuse",
        "source_state_file": str(args.state_file),
        "applied_override_count": applied_overrides,
        "local_non_result_resolution_count": local_resolutions,
        "historical_api_usage": historical_with_recovery,
    })
    (args.output / "agent_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "notice_count": manifest["notice_count"],
        "request_count": manifest["request_count"],
        "item_count": manifest["item_count"],
        "status_counts": manifest["status_counts"],
        "applied_override_count": applied_overrides,
        "local_non_result_resolution_count": local_resolutions,
        "historical_api_usage": historical_with_recovery,
        "manifest": str(args.output / "agent_manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
