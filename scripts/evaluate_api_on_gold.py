# -*- coding: utf-8 -*-
"""Leave-one-out DeepSeek API evaluation on the 10 gold notices.

The gold notice being scored is removed from few-shot examples.
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_silver_labels as rules  # noqa: E402
from src.services import silver_labeler as api  # noqa: E402
from src.services.llm_client import UsageTracker, build_client, chat_json, load_config  # noqa: E402

BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
GOLD_NOTICE_DIR = ROOT / "dataset_build" / "gold" / "notices"
FIELDS = [
    "product_service_name", "category_name", "category_code", "brand_supplier",
    "spec_model", "unit_price", "quantity", "quantity_unit", "total_price",
]


def choose_gold_candidate(payload: dict, gold: dict, candidates: list[dict]):
    gold_sources = {(i["source_container_path"], i["source_file"]) for i in gold["items"]}
    for cand in candidates:
        src = cand["source"]
        if (src.get("container_path"), src.get("file_name")) in gold_sources:
            return cand
    return candidates[0] if candidates else None


def main() -> int:
    config = load_config()
    model = config["api"]["model"]
    client = build_client(config)
    tracker = UsageTracker(ROOT / "run" / "logs" / "llm_usage.jsonl")
    examples = api.build_few_shot_examples()

    metrics = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    per_notice = []
    for path in sorted(GOLD_NOTICE_DIR.glob("*.json")):
        gold = json.loads(path.read_text(encoding="utf-8"))
        nid = gold["notice_id"]
        payload = json.loads((BLOCK_DIR / f"{nid}.json").read_text(encoding="utf-8"))
        candidates = rules.table_candidates(payload)
        candidate = choose_gold_candidate(payload, gold, candidates)
        if candidate is None:
            per_notice.append({"notice_id": nid, "status": "no_candidate"})
            continue
        block = next(b for b in payload["blocks"] if b["block_id"] == candidate["block_id"])
        rows = block.get("rows") or []
        data_rows = [{"block_row": idx + 1, "cells": [str(c)[:500] for c in rows[idx]]}
                     for idx in range(candidate["header_idx"] + 1, len(rows))]
        use_examples = [e for e in examples if e.get("notice_id") != nid]
        parts = []
        for i, e in enumerate(use_examples, 1):
            parts.append(f"示例{i}输入：\n{json.dumps(e['input'], ensure_ascii=False)}")
            parts.append(f"示例{i}输出：\n{json.dumps(e['output'], ensure_ascii=False)}\n")
        user = {
            "notice_id": nid,
            "title": payload.get("title"),
            "source_file": candidate["source"].get("file_name"),
            "header_row": [str(c)[:200] for c in rows[candidate["header_idx"]]],
            "data_rows": data_rows,
        }
        parts.append("现在请对以下表格执行相同的抽取：\n" + json.dumps(user, ensure_ascii=False))
        messages = [{"role": "system", "content": api.SYSTEM_PROMPT},
                    {"role": "user", "content": "\n".join(parts)}]
        llm_status = "ok"
        try:
            data = chat_json(client, model, messages, temperature=0,
                             max_tokens=int(config["silver"].get("max_tokens", 8000)),
                             tracker=tracker, notice_id=nid)
            items = api.llm_items_to_silver_items(block, data.get("items", []), candidate["header_idx"])
            items = api.enforce_evidence_columns(items, candidate, block)
            items = api.finalize_api_items(items)
        except Exception as exc:
            items = api.fallback_items(payload, candidate)
            llm_status = f"fallback:{type(exc).__name__}"

        api_by_row = {i["source_block_row"]: i for i in items}
        matched = 0
        for g in gold["items"]:
            s = api_by_row.get(g["source_block_row"])
            if s is None:
                for f in FIELDS:
                    metrics[f]["fn"] += 1
                continue
            matched += 1
            for f in FIELDS:
                gv, sv = g.get(f), s.get(f)
                if gv is None and sv is None:
                    continue
                if gv is None and sv is not None:
                    metrics[f]["fp"] += 1
                elif gv is not None and sv is None:
                    metrics[f]["fn"] += 1
                elif str(gv) == str(sv):
                    metrics[f]["tp"] += 1
                else:
                    metrics[f]["fp"] += 1
                    metrics[f]["fn"] += 1
        per_notice.append({
            "notice_id": nid, "status": llm_status,
            "matched_items": matched, "gold_items": len(gold["items"]), "api_items": len(items),
        })
        time.sleep(0.2)

    summary = {}
    for f, m in metrics.items():
        p = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else 1.0
        r = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else 1.0
        summary[f] = {"precision": round(p, 4), "recall": round(r, 4),
                      "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0}
    out = {"model": model, "per_notice": per_notice, "field_metrics": summary,
           "usage": {"requests": tracker.requests, "prompt_tokens": tracker.total_prompt_tokens,
                     "completion_tokens": tracker.total_completion_tokens,
                     "estimated_cost_yuan": round(tracker.estimated_cost_yuan(), 4)}}
    out_path = ROOT / "run" / "deepseek_gold_lolo_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
