# -*- coding: utf-8 -*-
"""Run the task-2 controlled relation agent over unified Block notices."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_entity_agent import _build_backend as _build_configured_backend  # noqa: E402
from src.agents.backends import BudgetedBackend, OpenAICompatibleBackend, ReplayBackend  # noqa: E402
from src.relation.agent import RelationExtractionAgent  # noqa: E402
from src.relation.schema import ProjectRelationInput  # noqa: E402
from src.relation.store import RelationStore  # noqa: E402


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_state(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    state: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return state
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        state[(
            str(record.get("signature")),
            str(record.get("notice_id")),
            str(record.get("input_digest")),
        )] = record
    return state


def _load_success_any_signature(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    success: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return success
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if (record.get("outcome") or {}).get("status") == "success":
            success[(str(record.get("notice_id")), str(record.get("input_digest")))] = record
    return success


def _usage(outcomes: list[dict[str, Any]]) -> dict[str, int]:
    total = {key: 0 for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    for outcome in outcomes:
        for key in total:
            total[key] += int((outcome.get("usage") or {}).get(key) or 0)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks-dir", type=Path, default=ROOT / "dataset_build" / "blocks" / "notices")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dataset_build" / "relation_results" / "notices")
    parser.add_argument("--db", type=Path, default=ROOT / "run" / "data" / "application.db")
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--backend", choices=("rules", "replay", "local", "api"), default="rules")
    parser.add_argument("--replay-file", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("LOCAL_LLM_BASE_URL"))
    parser.add_argument("--model", default=os.environ.get("LOCAL_LLM_MODEL"))
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "llm_config.yaml")
    parser.add_argument("--allow-external-api", action="store_true")
    parser.add_argument("--max-model-calls", type=int, default=0)
    parser.add_argument("--max-total-tokens", type=int, default=0)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--commit", action="store_true", help="Write model-confirmed success results to SQLite")
    parser.add_argument("--commit-candidates", action="store_true", help="Explicitly write unconfirmed rule candidates to SQLite")
    args = parser.parse_args()

    if args.backend == "api" and not args.allow_external_api:
        parser.error("--backend api requires --allow-external-api")
    if args.backend == "api" and args.max_model_calls <= 0:
        parser.error("--backend api requires a positive --max-model-calls")
    backend = None
    if args.backend == "replay":
        if args.replay_file is None:
            parser.error("--backend replay requires --replay-file")
        backend = ReplayBackend.from_file(args.replay_file)
    elif args.backend in {"local", "api"}:
        backend = _build_configured_backend(args)
        if args.backend == "local" and isinstance(backend, OpenAICompatibleBackend):
            if args.base_url:
                local_url = str(args.base_url).rstrip("/")
                if not local_url.endswith("/v1"):
                    local_url += "/v1"
                backend.base_url = local_url
            if args.model:
                backend.model = str(args.model)
                backend.name = f"local:{args.model}"
    if backend is not None and (args.max_model_calls or args.max_total_tokens):
        backend = BudgetedBackend(
            backend,
            max_calls=args.max_model_calls,
            max_total_tokens=args.max_total_tokens,
        )
    agent = RelationExtractionAgent(backend)
    store = RelationStore(args.db) if args.commit or args.commit_candidates else None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = [args.blocks_dir / f"{notice_id}.json" for notice_id in args.ids] if args.ids else sorted(args.blocks_dir.glob("*.json"))
    if args.limit is not None:
        paths = paths[: max(0, args.limit)]
    state_file = args.state_file or args.output_dir.parent / "relation_state.jsonl"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if args.force and state_file.exists():
        state_file.write_text("", encoding="utf-8")
    state = {} if args.force else _load_state(state_file)
    prior_success = {} if args.force else _load_success_any_signature(state_file)
    signature = _digest(agent.run_signature())
    report = {
        "total": len(paths), "success": 0, "candidate_only": 0, "failed": 0,
        "committed": 0, "resumed": 0,
    }
    outcomes: list[dict[str, Any]] = []
    for index, path in enumerate(paths, 1):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            input_digest = _digest(payload)
            prior = state.get((signature, path.stem, input_digest))
            if prior is None:
                prior = prior_success.get((path.stem, input_digest))
            if prior and (prior.get("outcome") or {}).get("status") in {"success", "candidate_only"}:
                outcome = prior["outcome"]
                report["resumed"] += 1
            else:
                outcome = agent.process(payload)
                record = {
                    "signature": signature,
                    "notice_id": path.stem,
                    "input_digest": input_digest,
                    "outcome": outcome,
                }
                with state_file.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            outcome = {"notice_id": path.stem, "status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}
        status = str(outcome.get("status") or "failed")
        report[status if status in report else "failed"] += 1
        should_commit = status == "success" and args.commit or status == "candidate_only" and args.commit_candidates
        if should_commit and store:
            store.ingest(ProjectRelationInput.model_validate(outcome["project"]), refresh=False)
            report["committed"] += 1
        (args.output_dir / path.name).write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
        outcomes.append(outcome)
        print(f"[{index}/{len(paths)}] {path.stem} {status} {outcome.get('method')}", flush=True)
    if store and report["committed"]:
        store.refresh_aggregates()
    manifest = {
        **report,
        "usage": _usage(outcomes),
        "agent": agent.run_signature(),
        "run_signature": signature,
        "state_file": str(state_file),
        "model_budget": backend.budget_report() if isinstance(backend, BudgetedBackend) else {},
        "output_dir": str(args.output_dir),
    }
    manifest_path = args.output_dir.parent / "relation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not report["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
