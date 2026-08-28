# -*- coding: utf-8 -*-
"""Run the controlled entity extraction agent on selected Block requests.

The default ``rules`` backend is fully local and never calls an external API.
Use ``local`` for an OpenAI-compatible local server.  The ``api`` backend is
guarded by ``--allow-external-api`` so an accidental invocation cannot incur
cost.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.backends import BudgetedBackend, OpenAICompatibleBackend, ReplayBackend  # noqa: E402
from src.agents.entity_extraction_agent import AgentConfig, EntityExtractionAgent  # noqa: E402
from src.agents.merger import merge_notice  # noqa: E402
from src.agents.source_policy import (  # noqa: E402
    evidence_can_cover_notice,
    evidence_document_ids,
    infer_excluded_document_ids,
)
from src.agents.tools import parse_request_evidence  # noqa: E402
from src.agents.verification import (  # noqa: E402
    CachedSearchProvider,
    DuckDuckGoSearchProvider,
    ReplaySearchProvider,
    TemporalEntityVerificationAgent,
    VerificationConfig,
    notice_date_from_id,
)


DEFAULT_INPUT = ROOT / "dataset_build" / "model_inputs" / "api_requests.jsonl"
DEFAULT_OUTPUT = ROOT / "dataset_build" / "agent_results"
DEFAULT_CONFIG = ROOT / "config" / "llm_config.yaml"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no} is invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} root must be an object")
        records.append(value)
    return records


def _signature(agent: EntityExtractionAgent) -> str:
    payload = json.dumps(agent.run_signature(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _payload_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_state(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    state: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return state
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        state[(
            str(record.get("signature")),
            str(record.get("request_id")),
            str(record.get("input_digest")),
        )] = record
    return state


def _load_verification_state(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    state: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return state
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        state[(
            str(record.get("signature")),
            str(record.get("candidate")),
            str(record.get("as_of_date")),
        )] = record
    return state


def _build_backend(args: argparse.Namespace) -> OpenAICompatibleBackend | ReplayBackend | None:
    if args.backend == "rules":
        return None
    if args.backend == "replay":
        if args.replay_file is None:
            raise ValueError("replay backend requires --replay-file")
        return ReplayBackend.from_file(args.replay_file)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    if args.backend == "api":
        if not args.allow_external_api:
            raise ValueError("api backend requires --allow-external-api")
        api = config.get("api") or {}
        key_name = str(api.get("api_key_env") or "LLM_API_KEY")
        key = os.environ.get(key_name, "")
        if not key:
            # Load only the named value without ever printing it.
            env_path = ROOT / ".env"
            if env_path.exists():
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    name, sep, value = line.partition("=")
                    if sep and name.strip() == key_name:
                        key = value.strip().strip('"\'')
                        break
        if not key:
            raise ValueError(f"environment variable {key_name} is empty")
        return OpenAICompatibleBackend(
            base_url=str(api.get("base_url")),
            model=str(api.get("model")),
            api_key=key,
            timeout_seconds=float(api.get("timeout_seconds", 120)),
            max_retries=int(api.get("max_retries", 2)),
            strict_schema=bool(api.get("structured_outputs", False)),
            input_price_per_million_yuan=float(api.get("input_price_per_million_yuan", 0)),
            output_price_per_million_yuan=float(api.get("output_price_per_million_yuan", 0)),
            name=f"api:{config.get('provider', 'openai-compatible')}:{api.get('model')}",
        )
    local = config.get("local") or {}
    local_url = str(local.get("server_url", "http://127.0.0.1:1234")).rstrip("/")
    if not local_url.endswith("/v1"):
        local_url += "/v1"
    model_name = str(local.get("model") or local.get("gguf_model") or "local-model")
    max_tokens_raw = local.get("max_tokens")
    return OpenAICompatibleBackend(
        base_url=local_url,
        model=model_name,
        api_key="local-no-key",
        timeout_seconds=float(local.get("timeout_seconds", 900)),
        max_retries=int(local.get("max_retries", 0)),
        strict_schema=bool(local.get("structured_outputs", False)),
        json_object=bool(local.get("json_object", False)),
        max_tokens=int(max_tokens_raw) if max_tokens_raw else None,
        disable_thinking=bool(local.get("disable_thinking", False)),
        name=f"local:{Path(model_name).name}",
    )


def _build_verifier(
    args: argparse.Namespace,
    backend: Any,
) -> TemporalEntityVerificationAgent | None:
    if not getattr(args, "verify_web", False):
        return None
    if backend is None:
        raise ValueError("--verify-web requires a local, replay, or API model backend")
    provider_name = str(getattr(args, "search_provider", "ddgs"))
    if provider_name == "replay":
        replay_file = getattr(args, "search_replay_file", None)
        if replay_file is None:
            raise ValueError("replay search provider requires --search-replay-file")
        payload = json.loads(Path(replay_file).read_text(encoding="utf-8"))
        responses = payload.get("responses") if isinstance(payload, dict) else None
        if not isinstance(responses, dict):
            raise ValueError("search replay file must contain an object-valued 'responses' field")
        provider: Any = ReplaySearchProvider(responses)
    else:
        if not getattr(args, "allow_web_search", False):
            raise ValueError("ddgs search requires --allow-web-search")
        provider = DuckDuckGoSearchProvider(
            timeout_seconds=float(getattr(args, "search_timeout_seconds", 20.0))
        )
    provider = CachedSearchProvider(
        provider,
        Path(args.output) / "verification_search_cache.jsonl",
    )
    return TemporalEntityVerificationAgent(
        backend,
        provider,
        VerificationConfig(
            max_search_rounds=int(getattr(args, "verify_max_search_rounds", 2)),
            max_search_queries=int(getattr(args, "verify_max_search_queries", 2)),
            max_results_per_query=int(getattr(args, "verify_max_results", 5)),
            max_repair_attempts=int(getattr(args, "max_repair_attempts", 1)),
            tool_mode=str(getattr(args, "verification_tool_mode", "auto")),
        ),
    )


def _blank_usage() -> dict[str, Any]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_yuan": 0.0}


def _accumulate_usage(total: dict[str, Any], addition: dict[str, Any]) -> None:
    for key in total:
        total[key] += addition.get(key, 0) or 0


def _write_outputs(
    output_dir: Path,
    requests: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    agent: EntityExtractionAgent,
    *,
    verifier: TemporalEntityVerificationAgent | None = None,
    verify_max_entities: int = 0,
    force_verification: bool = False,
    budget_backend: BudgetedBackend | None = None,
) -> dict[str, Any]:
    notice_dir = output_dir / "notices"
    notice_dir.mkdir(parents=True, exist_ok=True)
    request_by_id = {record.get("request_id"): record for record in requests}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for outcome in outcomes:
        grouped[str(outcome.get("notice_id"))].append(outcome)

    verification_usage = _blank_usage()
    verification_summary: dict[str, Any] = {
        "enabled": verifier is not None,
        "new_candidate_count": 0,
        "reused_candidate_count": 0,
        "skipped_candidate_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "usage": verification_usage,
    }
    verification_state_file = output_dir / "verification_state.jsonl"
    if force_verification and verification_state_file.exists():
        verification_state_file.write_text("", encoding="utf-8")
    verifier_signature = _payload_signature(verifier.run_signature()) if verifier is not None else ""
    verification_state = (
        {} if force_verification else _load_verification_state(verification_state_file)
    )
    decision_cache: dict[tuple[str, str], dict[str, Any]] = {}

    notice_entries: list[dict[str, Any]] = []
    for notice_id, notice_outcomes in sorted(grouped.items()):
        first_request = request_by_id.get(notice_outcomes[0].get("request_id"), {})
        title = str(first_request.get("title") or "")
        if not title:
            try:
                user_input, _evidence = parse_request_evidence(first_request)
                title = str(user_input.get("title") or notice_id)
            except Exception:
                title = notice_id
        notice = merge_notice(notice_id, title, notice_outcomes, agent_version=agent.version)
        if verifier is not None:
            as_of_date = notice_date_from_id(notice_id)
            verification_results: list[dict[str, Any]] = []
            result_ids: dict[str, str] = {}
            candidates = list(dict.fromkeys(
                str(item.get("brand_supplier") or "").strip()
                for item in notice["items"]
                if str(item.get("brand_supplier") or "").strip()
                and len(str(item.get("brand_supplier") or "").strip()) <= 100
            ))
            for candidate in candidates:
                if as_of_date is None:
                    verification_summary["skipped_candidate_count"] += 1
                    continue
                cache_key = (candidate, as_of_date)
                result = decision_cache.get(cache_key)
                if result is None:
                    prior = verification_state.get((verifier_signature, candidate, as_of_date))
                    if prior and prior.get("result", {}).get("status") == "success":
                        result = verifier.refresh_result(prior["result"])
                        verification_summary["reused_candidate_count"] += 1
                    elif verify_max_entities and verification_summary["new_candidate_count"] >= verify_max_entities:
                        verification_summary["skipped_candidate_count"] += 1
                        continue
                    else:
                        result = verifier.verify(
                            candidate,
                            as_of_date=as_of_date,
                            request_id=f"{notice_id}:verify:{verification_summary['new_candidate_count'] + 1}",
                            candidate_type="unknown",
                        )
                        verification_summary["new_candidate_count"] += 1
                        _accumulate_usage(verification_usage, result.get("usage") or {})
                        record = {
                            "signature": verifier_signature,
                            "candidate": candidate,
                            "as_of_date": as_of_date,
                            "result": result,
                        }
                        with verification_state_file.open("a", encoding="utf-8", newline="\n") as handle:
                            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    decision_cache[cache_key] = result
                result_id = f"{notice_id}:ext_{len(verification_results) + 1:03d}"
                result_ids[candidate] = result_id
                verification_results.append({"verification_id": result_id, **result})
                verification_summary[f"{result.get('status', 'failed')}_count"] += 1
            for item in notice["items"]:
                candidate = str(item.get("brand_supplier") or "").strip()
                if candidate in result_ids:
                    item["external_verification_id"] = result_ids[candidate]
            notice["external_verification"] = {
                "enabled": True,
                "as_of_date": as_of_date,
                "as_of_date_source": "notice_id_prefix" if as_of_date else None,
                "candidate_count": len(candidates),
                "verified_candidate_count": len(verification_results),
                "results": verification_results,
            }
        notice_path = notice_dir / f"{notice_id}.json"
        notice_path.write_text(json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        notice_entries.append({
            "notice_id": notice_id,
            "title": title,
            "status": notice["status"],
            "request_count": notice["request_count"],
            "item_count": notice["item_count"],
            "needs_model_request_count": notice["needs_model_request_count"],
            "failed_request_count": notice["failed_request_count"],
            "file": f"notices/{notice_id}.json",
        })

    usage = _blank_usage()
    status_counts: dict[str, int] = defaultdict(int)
    method_counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        status_counts[str(outcome.get("status"))] += 1
        method_counts[str(outcome.get("method"))] += 1
        for key in usage:
            usage[key] += outcome.get("usage", {}).get(key, 0) or 0
    usage["estimated_cost_yuan"] = round(float(usage["estimated_cost_yuan"]), 6)
    verification_usage["estimated_cost_yuan"] = round(float(verification_usage["estimated_cost_yuan"]), 6)
    combined_usage = _blank_usage()
    _accumulate_usage(combined_usage, usage)
    _accumulate_usage(combined_usage, verification_usage)
    combined_usage["estimated_cost_yuan"] = round(float(combined_usage["estimated_cost_yuan"]), 6)
    manifest = {
        "schema_version": "1.0",
        "agent_version": agent.version,
        "backend": agent.backend_name,
        "run_signature": _signature(agent),
        "notice_count": len(notice_entries),
        "request_count": len(outcomes),
        "item_count": sum(entry["item_count"] for entry in notice_entries),
        "status_counts": dict(status_counts),
        "method_counts": dict(method_counts),
        "usage": usage,
        "verification": verification_summary,
        "combined_usage": combined_usage,
        "model_budget": budget_backend.budget_report() if budget_backend is not None else {},
        "notices": notice_entries,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "agent_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "agent_items.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for entry in notice_entries:
            notice = json.loads((output_dir / entry["file"]).read_text(encoding="utf-8"))
            for item in notice["items"]:
                handle.write(json.dumps({"notice_id": notice["notice_id"], "title": notice["title"], **item}, ensure_ascii=False, separators=(",", ":")) + "\n")
    report = [
        "# 实体抽取智能体运行报告", "",
        f"- 后端：{agent.backend_name}",
        f"- 公告：{manifest['notice_count']}",
        f"- 请求：{manifest['request_count']}",
        f"- 实体：{manifest['item_count']}",
        f"- 模型调用：{usage['calls']}",
        f"- 输入 Token：{usage['prompt_tokens']}",
        f"- 输出 Token：{usage['completion_tokens']}",
        f"- 估算费用（元）：{usage['estimated_cost_yuan']}", "",
        "## 请求状态", "",
    ]
    report.extend(f"- {key}: {value}" for key, value in sorted(status_counts.items()))
    report.extend(["", "## 抽取方式", ""])
    report.extend(f"- {key}: {value}" for key, value in sorted(method_counts.items()))
    report.extend([
        "", "## 联网时序核验", "",
        f"- 是否启用：{verification_summary['enabled']}",
        f"- 新核验候选：{verification_summary['new_candidate_count']}",
        f"- 复用候选：{verification_summary['reused_candidate_count']}",
        f"- 跳过候选：{verification_summary['skipped_candidate_count']}",
        f"- 核验模型调用：{verification_usage['calls']}",
        f"- 核验 Token：{verification_usage['total_tokens']}",
    ])
    (output_dir / "agent_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return manifest


def run(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "backend", "rules") == "api" and int(getattr(args, "max_model_calls", 0) or 0) <= 0:
        raise ValueError("api backend requires a positive --max-model-calls safety limit")
    requests = load_jsonl(args.input)
    requested_ids = set(getattr(args, "request_id", None) or [])
    if requested_ids:
        requests = [request for request in requests if str(request.get("request_id")) in requested_ids]
        missing = requested_ids - {str(request.get("request_id")) for request in requests}
        if missing:
            raise ValueError(f"requested IDs not found: {sorted(missing)}")
    if args.limit_notices:
        allowed: list[str] = []
        for request in requests:
            notice_id = str(request.get("notice_id"))
            if notice_id not in allowed:
                allowed.append(notice_id)
            if len(allowed) >= args.limit_notices:
                break
        requests = [request for request in requests if str(request.get("notice_id")) in set(allowed)]
    if args.limit_requests:
        requests = requests[: args.limit_requests]

    backend = _build_backend(args)
    max_model_calls = int(getattr(args, "max_model_calls", 0) or 0)
    max_total_tokens = int(getattr(args, "max_total_tokens", 0) or 0)
    if backend is not None and (max_model_calls or max_total_tokens):
        backend = BudgetedBackend(
            backend,
            max_calls=max_model_calls,
            max_total_tokens=max_total_tokens,
        )
    agent = EntityExtractionAgent(backend=backend, config=AgentConfig(
        enable_rule_fast_path=not args.model_only,
        max_repair_attempts=args.max_repair_attempts,
        skip_text_when_covered_by_strong_table=not args.keep_covered_text,
    ))
    verifier = _build_verifier(args, backend)
    signature = _signature(agent)
    state_file = args.output / "agent_state.jsonl"
    if args.force and state_file.exists():
        state_file.write_text("", encoding="utf-8")
    state = {} if args.force else _load_state(state_file)
    args.output.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    strongly_covered_notices: set[str] = set()
    excluded_document_ids = infer_excluded_document_ids(requests)
    for index, request in enumerate(requests, 1):
        request_id = str(request.get("request_id"))
        notice_id = str(request.get("notice_id") or request_id.split(":", 1)[0])
        input_digest = _payload_signature(request)
        prior = state.get((signature, request_id, input_digest))
        if prior and prior.get("outcome", {}).get("status") in {"success", "needs_model"}:
            outcome = prior["outcome"]
        else:
            try:
                _user_input, request_evidence = parse_request_evidence(request)
            except Exception:
                request_evidence = {}
            request_document_ids = evidence_document_ids(request_evidence)
            if request_document_ids and request_document_ids <= excluded_document_ids:
                outcome = agent.excluded_document_outcome(request)
            elif (
                agent.config.skip_text_when_covered_by_strong_table
                and request.get("content_kind") == "text"
                and notice_id in strongly_covered_notices
            ):
                outcome = agent.covered_text_outcome(request)
            else:
                outcome = agent.process_request(request)
            record = {
                "signature": signature,
                "request_id": request_id,
                "input_digest": input_digest,
                "outcome": outcome,
            }
            with state_file.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        outcomes.append(outcome)
        if outcome.get("method") == "rules" and float(outcome.get("confidence") or 0) >= 0.94 and outcome.get("items"):
            try:
                _user_input, coverage_evidence = parse_request_evidence(request)
            except Exception:
                coverage_evidence = {}
            if evidence_can_cover_notice(coverage_evidence):
                strongly_covered_notices.add(notice_id)
        print(f"[{index}/{len(requests)}] {request_id} {outcome['status']} {outcome.get('method')}", flush=True)
    return _write_outputs(
        args.output,
        requests,
        outcomes,
        agent,
        verifier=verifier,
        verify_max_entities=int(getattr(args, "verify_max_entities", 0) or 0),
        force_verification=bool(getattr(args, "force", False)),
        budget_backend=backend if isinstance(backend, BudgetedBackend) else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--backend", choices=("rules", "replay", "local", "api"), default="rules")
    parser.add_argument("--replay-file", type=Path, help="request-id keyed offline responses for a human/model substitute run")
    parser.add_argument("--allow-external-api", action="store_true", help="明确允许外部 API 调用及可能产生的费用")
    parser.add_argument("--max-model-calls", type=int, default=0, help="模型调用硬上限；API后端必须显式设置正数")
    parser.add_argument("--max-total-tokens", type=int, default=0, help="已完成调用的累计Token达到此值后禁止下一次调用")
    parser.add_argument("--verify-web", action="store_true", help="公告合并后启用公司/品牌时序联网核验子图")
    parser.add_argument("--allow-web-search", action="store_true", help="明确允许联网搜索；使用ddgs提供方时必须设置")
    parser.add_argument("--search-provider", choices=("ddgs", "replay"), default="ddgs")
    parser.add_argument("--search-replay-file", type=Path, help="离线搜索回放JSON，用于无网络测试")
    parser.add_argument("--search-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--verify-max-entities", type=int, default=3, help="本次最多新核验的去重公司/品牌数")
    parser.add_argument("--verify-max-search-rounds", type=int, default=2, choices=(1, 2))
    parser.add_argument("--verify-max-search-queries", type=int, default=2, choices=(1, 2, 3))
    parser.add_argument("--verify-max-results", type=int, default=5, choices=range(1, 9))
    parser.add_argument(
        "--verification-tool-mode",
        choices=("auto", "model", "deterministic"),
        default="auto",
        help="本地模型不支持原生tool calling时使用deterministic",
    )
    parser.add_argument("--model-only", action="store_true", help="关闭本地规则快速通道")
    parser.add_argument("--keep-covered-text", action="store_true", help="强表已抽取实体后仍处理正文请求（召回优先，调用更多）")
    parser.add_argument("--max-repair-attempts", type=int, default=1, choices=(0, 1))
    parser.add_argument("--limit-requests", type=int, default=0)
    parser.add_argument("--limit-notices", type=int, default=0)
    parser.add_argument("--request-id", action="append", help="只处理指定request_id；可重复设置")
    parser.add_argument("--force", action="store_true", help="忽略同配置的断点状态，重新处理")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.input.exists():
        print(f"input does not exist: {args.input}", file=sys.stderr)
        return 2
    try:
        manifest = run(args)
    except Exception as exc:
        print(f"entity agent failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "notice_count": manifest["notice_count"],
        "request_count": manifest["request_count"],
        "item_count": manifest["item_count"],
        "status_counts": manifest["status_counts"],
        "method_counts": manifest["method_counts"],
        "usage": manifest["usage"],
        "manifest": str(args.output / "agent_manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
