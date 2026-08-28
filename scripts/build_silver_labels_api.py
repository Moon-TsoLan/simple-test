# -*- coding: utf-8 -*-
"""Use DeepSeek API + few-shot gold examples to produce silver labels.

Pipeline:
  rules candidate prefilter (table selection only)
    -> DeepSeek JSON few-shot extraction (field values)
    -> local provenance re-attachment + numeric consistency flags
    -> dataset_build/silver/*

The previous rule-based silver set is archived to
``dataset_build/silver_rules_v1`` before this script overwrites ``silver/``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_silver_labels as rules  # noqa: E402
from src.services.llm_client import UsageTracker, build_client, chat_json, load_config  # noqa: E402
from src.services import silver_labeler as api_labeler  # noqa: E402

BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
GOLD_DIR = ROOT / "dataset_build" / "gold"
SILVER_DIR = ROOT / "dataset_build" / "silver"
NOTICE_DIR = SILVER_DIR / "notices"
ARCHIVE_DIR = ROOT / "dataset_build" / "silver_rules_v1"

VERSION = "2.0.0-deepseek"
ANNOTATION_METHOD = "deepseek_api_fewshot_silver"
REVIEW_STATUS = "silver_api_unreviewed"


def archive_previous_silver() -> None:
    if not SILVER_DIR.exists():
        return
    if ARCHIVE_DIR.exists():
        print(f"归档目录已存在，跳过备份：{ARCHIVE_DIR}", flush=True)
        return
    shutil.copytree(SILVER_DIR, ARCHIVE_DIR)
    print(f"已归档原规则银标：{ARCHIVE_DIR}", flush=True)


def clean_title(payload: dict[str, Any]) -> str:
    title = rules.clean(payload.get("title"))
    if title and not title.startswith("http"):
        return title
    for block in payload.get("blocks", []):
        if block.get("type") == "heading" and block.get("text"):
            title = rules.clean(block["text"])
            if title:
                return title
    return payload.get("notice_id") or ""


def build_api_notice(payload: dict[str, Any], candidate: dict[str, Any], items: list[dict[str, Any]],
                     llm_status: str, model: str) -> dict[str, Any]:
    level, score = rules.confidence_for(candidate, items) if items else ("low", 0.0)
    source = candidate["source"]
    return {
        "notice_id": payload.get("notice_id"),
        "title": clean_title(payload),
        "source_parser_version": payload.get("parser_version", "legacy-unversioned"),
        "source_parser_config_digest": payload.get("parser_config_digest"),
        "annotation_version": VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "review_status": REVIEW_STATUS,
        "selection_reason": (
            f"DeepSeek few-shot 抽取；候选表字段={', '.join(candidate['fields'])}；"
            f"来源={source.get('container_path')}；llm_status={llm_status}"
        ),
        "silver_confidence": level,
        "silver_confidence_score": score,
        "selected_table": {
            "block_id": candidate["block_id"],
            "source": source,
            "header": candidate["header_row"],
            "matched_fields": candidate["fields"],
            "score": candidate["score"],
            "llm_model": model,
            "llm_status": llm_status,
        },
        "warnings": [
            f"template_penalty={candidate['template_penalty']}",
            f"status_penalty={candidate['status_penalty']}",
            f"llm_status={llm_status}",
        ],
        "items": items,
    }


def chunk_data_rows(block_rows: list[list[str]], header_idx: int, max_rows: int) -> list[dict[str, Any]]:
    chunks = []
    current = []
    for idx in range(header_idx + 1, len(block_rows)):
        current.append({"block_row": idx + 1, "cells": [str(c)[:500] for c in block_rows[idx]]})
        if len(current) >= max_rows:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 篇非金标候选（0=全量）")
    ap.add_argument("--force", action="store_true", help="忽略状态文件重新打标")
    ap.add_argument("--dry-run", action="store_true", help="只打印配置与候选数，不调用 API")
    ap.add_argument("--output-dir", type=Path, default=SILVER_DIR, help="输出目录（测试时建议指定其他目录）")
    ap.add_argument("--clean", action="store_true", help="处理前清空输出 notices 目录")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_notice_dir = out_dir / "notices"

    config = load_config()
    api_cfg = config["api"]
    silver_cfg = config["silver"]
    model = api_cfg["model"]
    max_rows = int(silver_cfg.get("max_rows_per_request", 60))
    few_shot = api_labeler.build_few_shot_examples()
    if not few_shot:
        print("没有可用的金标 few-shot 示例", file=sys.stderr)
        return 2

    gold_ids = {path.stem for path in GOLD_DIR.joinpath("notices").glob("*.json")}
    examples = few_shot
    print(f"配置 provider={config.get('provider')} model={model} base_url={api_cfg['base_url']}", flush=True)
    print(f"few-shot 示例数={len(examples)}，max_rows_per_request={max_rows}", flush=True)

    # 候选预筛（规则只负责选表，字段值由 API 输出）
    block_paths = sorted(BLOCK_DIR.glob("*.json"))
    candidates_by_notice = {}
    for path in block_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        nid = payload.get("notice_id")
        if not nid or nid in gold_ids:
            continue
        candidates = rules.table_candidates(payload)
        if candidates:
            candidates_by_notice[nid] = (payload, candidates[0])
    ordered = sorted(candidates_by_notice.items())
    print(f"候选公告数={len(ordered)}", flush=True)
    if args.dry_run:
        return 0

    if out_dir == SILVER_DIR:
        archive_previous_silver()
    out_notice_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for old in out_notice_dir.glob("*.json"):
            old.unlink()

    state_file = ROOT / silver_cfg.get("state_file", "run/state/deepseek_silver_state.jsonl")
    usage_file = ROOT / silver_cfg.get("usage_file", "run/logs/llm_usage.jsonl")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    state_by_notice = {}
    if state_file.exists():
        for line in state_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                state_by_notice[rec["notice_id"]] = rec

    client = build_client(config)
    tracker = UsageTracker(usage_file)
    stats = Counter()
    manifest_notices = []

    for i, (nid, (payload, candidate)) in enumerate(ordered, 1):
        if args.limit and i > args.limit:
            break
        state = state_by_notice.get(nid, {})
        if not args.force and state.get("status") == "ok" and (out_notice_dir / f"{nid}.json").exists():
            stats["resume_skipped"] += 1
            print(f"[{i}/{len(ordered)}] SKIP {nid}", flush=True)
            continue

        block = next(b for b in payload["blocks"] if b.get("block_id") == candidate["block_id"])
        chunks = chunk_data_rows(block.get("rows") or [], candidate["header_idx"], max_rows)
        all_items: list[dict[str, Any]] = []
        llm_status = "ok"
        fallback_used = False
        start = time.time()
        try:
            for ci, data_rows in enumerate(chunks, 1):
                # 构造该 chunk 的候选副本：data_rows 只影响 prompt 不改变 block 回指
                messages = api_labeler.build_messages(payload, candidate, examples)
                # build_messages 默认把完整数据行放入；这里覆盖最后一段的用户内容数据范围。
                user_obj = {
                    "notice_id": payload.get("notice_id"),
                    "title": clean_title(payload),
                    "source_file": candidate["source"].get("file_name"),
                    "header_row": [str(c)[:200] for c in block["rows"][candidate["header_idx"]]],
                    "data_rows": data_rows,
                }
                parts = []
                for ex_i, example in enumerate(examples, 1):
                    parts.append(f"示例{ex_i}输入：\n{json.dumps(example['input'], ensure_ascii=False)}")
                    parts.append(f"示例{ex_i}输出：\n{json.dumps(example['output'], ensure_ascii=False)}\n")
                parts.append("现在请对以下表格执行相同的抽取：\n")
                parts.append(json.dumps(user_obj, ensure_ascii=False))
                msgs = [{"role": "system", "content": api_labeler.SYSTEM_PROMPT},
                        {"role": "user", "content": "\n".join(parts)}]
                data = chat_json(client, model, msgs,
                                 temperature=float(silver_cfg.get("temperature", 0.0)),
                                 max_tokens=int(silver_cfg.get("max_tokens", 3000)),
                                 tracker=tracker, notice_id=nid)
                raw_items = data.get("items", []) if isinstance(data, dict) else []
                if not isinstance(raw_items, list):
                    raw_items = []
                all_items.extend(api_labeler.llm_items_to_silver_items(block, raw_items, candidate["header_idx"]))
                time.sleep(0.2)
        except Exception as exc:
            stats["llm_error"] += 1
            llm_status = f"error:{type(exc).__name__}"
            print(f"[{i}/{len(ordered)}] LLM_ERROR {nid} {llm_status}", flush=True)

        all_items = api_labeler.enforce_evidence_columns(all_items, candidate, block)

        if not all_items:
            fallback_items = api_labeler.fallback_items(payload, candidate)
            if fallback_items:
                all_items = fallback_items
                fallback_used = True
                llm_status = "empty_result_fallback_rule"
        else:
            all_items = api_labeler.finalize_api_items(all_items)

        if not all_items:
            stats["no_items"] += 1
            state_by_notice[nid] = {"notice_id": nid, "status": "no_items", "elapsed": round(time.time() - start, 2)}
            with state_file.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(state_by_notice[nid], ensure_ascii=False, separators=(",", ":")) + "\n")
            continue

        notice = build_api_notice(payload, candidate, all_items, llm_status, model)
        (out_notice_dir / f"{nid}.json").write_text(
            json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stats["confidence_" + notice["silver_confidence"]] += 1
        stats["api_ok"] += 1
        if fallback_used:
            stats["fallback_rule"] += 1
        manifest_notices.append({
            "notice_id": nid,
            "title": notice["title"],
            "item_count": len(all_items),
            "confidence": notice["silver_confidence"],
            "confidence_score": notice["silver_confidence_score"],
            "matched_fields": candidate["fields"],
            "source_types": [str(candidate["source"].get("file_type"))],
            "llm_status": llm_status,
            "file": f"notices/{nid}.json",
        })
        state_by_notice[nid] = {"notice_id": nid, "status": "ok", "elapsed": round(time.time() - start, 2),
                                "llm_status": llm_status}
        with state_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(state_by_notice[nid], ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"[{i}/{len(ordered)}] OK {nid} items={len(all_items)} status={llm_status}", flush=True)

    # 从落盘文件重建 manifest，保证 --limit / --force 重跑后数量一致。
    manifest_notices = []
    for p in sorted(out_notice_dir.glob("*.json")):
        notice = json.loads(p.read_text(encoding="utf-8"))
        manifest_notices.append({
            "notice_id": notice["notice_id"],
            "title": notice["title"],
            "item_count": len(notice["items"]),
            "confidence": notice["silver_confidence"],
            "confidence_score": notice["silver_confidence_score"],
            "matched_fields": notice["selected_table"].get("matched_fields", []),
            "source_types": [str(notice["selected_table"]["source"].get("file_type"))],
            "llm_status": notice["selected_table"].get("llm_status", "ok"),
            "file": f"notices/{notice['notice_id']}.json",
        })

    manifest = {
        "annotation_version": VERSION,
        "annotation_method": ANNOTATION_METHOD,
        "review_status": REVIEW_STATUS,
        "notice_count": len(manifest_notices),
        "item_count": sum(n["item_count"] for n in manifest_notices),
        "gold_notice_count": len(gold_ids),
        "excluded_gold_notices": sorted(gold_ids),
        "notices": manifest_notices,
        "usage": {
            "requests": tracker.requests,
            "prompt_tokens": tracker.total_prompt_tokens,
            "completion_tokens": tracker.total_completion_tokens,
            "estimated_cost_yuan": round(tracker.estimated_cost_yuan(), 4),
        },
    }
    (out_dir / "silver_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (out_dir / "silver_items.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for entry in manifest_notices:
            notice = json.loads((out_dir / entry["file"]).read_text(encoding="utf-8"))
            for item in notice["items"]:
                handle.write(json.dumps(
                    {"notice_id": notice["notice_id"], "title": notice["title"], **item},
                    ensure_ascii=False, separators=(",", ":")
                ) + "\n")

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "silver_schema.json",
        "title": "招采标的物 DeepSeek API 银标公告",
        "type": "object",
        "properties": {
            "annotation_method": {"const": ANNOTATION_METHOD},
            "review_status": {"const": REVIEW_STATUS},
            "items": {"type": "array", "items": rules.SILVER_ITEM_SCHEMA},
        },
    }
    (out_dir / "silver_schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_lines = [
        "# DeepSeek API Silver 标注报告",
        "",
        f"- 模型：{model}",
        f"- 候选公告：{len(ordered)}",
        f"- 生成银标公告：{len(manifest_notices)}",
        f"- 银标条目：{manifest['item_count']}",
        f"- API 请求数：{tracker.requests}",
        f"- 输入 tokens：{tracker.total_prompt_tokens}",
        f"- 输出 tokens：{tracker.total_completion_tokens}",
        f"- 估算费用（元）：{manifest['usage']['estimated_cost_yuan']}",
        f"- 规则回退：{stats['fallback_rule']}",
        f"- LLM 错误：{stats['llm_error']}",
        "",
    ]
    (out_dir / "silver_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps({
        "candidate_notices": len(ordered),
        "silver_notices": len(manifest_notices),
        "silver_items": manifest["item_count"],
        "requests": tracker.requests,
        "prompt_tokens": tracker.total_prompt_tokens,
        "completion_tokens": tracker.total_completion_tokens,
        "estimated_cost_yuan": manifest["usage"]["estimated_cost_yuan"],
        "stats": dict(stats),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
