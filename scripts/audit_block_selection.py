# -*- coding: utf-8 -*-
"""Audit standard versus relaxed Block selection with gold evidence recall.

The audit treats compression as a cost metric, not a quality metric.  Quality
is measured by exact source Block/row recall on gold data, limit activation,
and a review queue of evidence admitted only by the relaxed configuration.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULT_TERMS = ("主要标的信息", "主要成交标的", "中标标的", "成交标的", "分项报价", "报价明细", "中标", "成交")
FIELD_TERMS = ("货物名称", "标的名称", "产品名称", "服务名称", "品牌", "规格型号", "型号", "单价", "数量", "总价", "合价")
NEGATIVE_TERMS = ("采购需求", "最高限价", "预算金额", "评分办法", "招标文件", "采购文件", "空白报价", "投标人须知")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_packages(directory: Path) -> dict[str, dict[str, Any]]:
    notice_dir = directory / "notices"
    return {path.stem: read_json(path) for path in sorted(notice_dir.glob("*.json"))}


def request_evidence(request: dict[str, Any]) -> dict[str, Any]:
    messages = ((request.get("api_payload") or {}).get("messages") or [])
    user = next((message for message in messages if message.get("role") == "user"), None)
    return (json.loads(user.get("content") or "") if user else {}).get("evidence") or {}


def selection_index(package: dict[str, Any]) -> tuple[set[str], set[tuple[str, int]], dict[str, dict[str, Any]]]:
    blocks: set[str] = set()
    rows: set[tuple[str, int]] = set()
    metadata: dict[str, dict[str, Any]] = {}
    for request in package.get("requests") or []:
        for block_id in request.get("source_block_ids") or []:
            block_id = str(block_id)
            blocks.add(block_id)
            prior = metadata.get(block_id)
            record = {
                "request_id": request.get("request_id"),
                "content_kind": request.get("content_kind"),
                "relevance_score": request.get("relevance_score"),
                "selection_reasons": request.get("selection_reasons") or [],
            }
            if prior is None or int(record["relevance_score"] or 0) > int(prior["relevance_score"] or 0):
                metadata[block_id] = record
        evidence = request_evidence(request)
        if evidence.get("kind") == "table" and evidence.get("block_id"):
            block_id = str(evidence["block_id"])
            for row in evidence.get("data_rows") or []:
                if isinstance(row.get("block_row"), int):
                    rows.add((block_id, int(row["block_row"])))
    return blocks, rows, metadata


def block_snippet(block: dict[str, Any], limit: int = 420) -> str:
    if block.get("type") == "table":
        text = " || ".join(" | ".join(" ".join(str(cell or "").split()) for cell in row) for row in (block.get("rows") or [])[:4])
    else:
        text = " ".join(str(block.get("text") or "").split())
    return text[:limit]


def risk_category(block: dict[str, Any], snippet: str) -> tuple[str, list[str]]:
    source = block.get("source") or {}
    source_text = f"{source.get('file_name', '')} {source.get('container_path', '')}"
    joined = f"{source_text} {snippet}"
    result_hits = [term for term in RESULT_TERMS if term in joined]
    field_hits = [term for term in FIELD_TERMS if term in snippet]
    negative_hits = [term for term in NEGATIVE_TERMS if term in joined]
    reasons: list[str] = []
    if result_hits:
        reasons.append("result_terms:" + ",".join(result_hits[:4]))
    if field_hits:
        reasons.append("field_terms:" + ",".join(field_hits[:5]))
    if negative_hits:
        reasons.append("negative_terms:" + ",".join(negative_hits[:4]))
    if result_hits and len(field_hits) >= 2 and not negative_hits:
        return "potential_result_evidence", reasons
    if negative_hits:
        return "likely_template_or_demand", reasons
    return "low_or_ambiguous_signal", reasons


def aggregate_limit_stats(packages: dict[str, dict[str, Any]]) -> dict[str, int]:
    counters: Counter[str] = Counter()
    for package in packages.values():
        stats = package.get("stats") or {}
        counters["table_source_limit_notice_count"] += int(bool(stats.get("table_source_limit_triggered")))
        counters["table_blocks_excluded_by_source_limit"] += int(stats.get("table_blocks_excluded_by_source_limit") or 0)
        counters["text_request_limit_notice_count"] += int(bool(stats.get("text_request_limit_triggered")))
        counters["text_groups_excluded_by_request_limit"] += int(stats.get("text_groups_excluded_by_request_limit") or 0)
    return dict(counters)


def build_audit(
    block_dir: Path,
    standard_dir: Path,
    loose_dir: Path,
    gold_dir: Path,
    *,
    review_limit: int = 100,
) -> dict[str, Any]:
    standard = load_packages(standard_dir)
    loose = load_packages(loose_dir)
    common_ids = sorted(set(standard) & set(loose))
    if not common_ids:
        raise ValueError("standard and loose directories have no notices in common")

    block_payloads = {notice_id: read_json(block_dir / f"{notice_id}.json") for notice_id in common_ids}
    block_indexes = {
        notice_id: {str(block.get("block_id")): block for block in payload.get("blocks") or []}
        for notice_id, payload in block_payloads.items()
    }
    standard_indexes = {notice_id: selection_index(standard[notice_id]) for notice_id in common_ids}
    loose_indexes = {notice_id: selection_index(loose[notice_id]) for notice_id in common_ids}

    gold_keys: list[dict[str, Any]] = []
    for path in sorted(gold_dir.glob("*.json")):
        gold = read_json(path)
        notice_id = str(gold.get("notice_id") or path.stem)
        if notice_id not in common_ids:
            continue
        for item in gold.get("items") or []:
            gold_keys.append({
                "notice_id": notice_id,
                "item_no": item.get("item_no"),
                "product_service_name": item.get("product_service_name"),
                "block_id": str(item.get("source_block_id") or ""),
                "block_row": item.get("source_block_row"),
            })

    format_counts: dict[str, Counter[str]] = defaultdict(Counter)
    content_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    missed_standard: list[dict[str, Any]] = []
    missed_loose: list[dict[str, Any]] = []
    standard_hits = loose_hits = 0
    for item in gold_keys:
        notice_id = item["notice_id"]
        key = (item["block_id"], item["block_row"])
        block = block_indexes[notice_id].get(item["block_id"], {})
        source_format = str((block.get("source") or {}).get("file_type") or "unknown").lower()
        content_type = str(block.get("type") or "unknown")
        standard_hit = key in standard_indexes[notice_id][1]
        loose_hit = key in loose_indexes[notice_id][1]
        format_counts[source_format]["gold"] += 1
        format_counts[source_format]["standard_retained"] += int(standard_hit)
        format_counts[source_format]["loose_retained"] += int(loose_hit)
        content_type_counts[content_type]["gold"] += 1
        content_type_counts[content_type]["standard_retained"] += int(standard_hit)
        content_type_counts[content_type]["loose_retained"] += int(loose_hit)
        standard_hits += int(standard_hit)
        loose_hits += int(loose_hit)
        if not standard_hit:
            missed_standard.append(item)
        if not loose_hit:
            missed_loose.append(item)

    review_queue: list[dict[str, Any]] = []
    loose_only_count = 0
    risk_counts: Counter[str] = Counter()
    per_notice: list[dict[str, Any]] = []
    for notice_id in common_ids:
        standard_blocks, _standard_rows, _standard_metadata = standard_indexes[notice_id]
        loose_blocks, _loose_rows, loose_metadata = loose_indexes[notice_id]
        loose_only = sorted(loose_blocks - standard_blocks)
        loose_only_count += len(loose_only)
        for block_id in loose_only:
            block = block_indexes[notice_id].get(block_id, {})
            snippet = block_snippet(block)
            category, reasons = risk_category(block, snippet)
            risk_counts[category] += 1
            source = block.get("source") or {}
            metadata = loose_metadata.get(block_id) or {}
            review_queue.append({
                "notice_id": notice_id,
                "block_id": block_id,
                "block_type": block.get("type"),
                "source_file_type": source.get("file_type"),
                "source_file": source.get("file_name"),
                "container_path": source.get("container_path"),
                "risk_category": category,
                "risk_reasons": reasons,
                **metadata,
                "snippet": snippet,
            })
        standard_stats = standard[notice_id].get("stats") or {}
        loose_stats = loose[notice_id].get("stats") or {}
        notice_gold = [item for item in gold_keys if item["notice_id"] == notice_id]
        per_notice.append({
            "notice_id": notice_id,
            "original_blocks": len(block_payloads[notice_id].get("blocks") or []),
            "standard_selected_blocks": len(standard_blocks),
            "loose_selected_blocks": len(loose_blocks),
            "loose_only_blocks": len(loose_only),
            "standard_requests": int(standard_stats.get("request_count") or 0),
            "loose_requests": int(loose_stats.get("request_count") or 0),
            "standard_input_chars": int(standard_stats.get("estimated_input_chars") or 0),
            "loose_input_chars": int(loose_stats.get("estimated_input_chars") or 0),
            "gold_items": len(notice_gold),
            "standard_gold_rows_retained": sum(
                (item["block_id"], item["block_row"]) in standard_indexes[notice_id][1] for item in notice_gold
            ),
            "loose_gold_rows_retained": sum(
                (item["block_id"], item["block_row"]) in loose_indexes[notice_id][1] for item in notice_gold
            ),
            "standard_table_source_limit_triggered": bool(standard_stats.get("table_source_limit_triggered")),
            "standard_text_request_limit_triggered": bool(standard_stats.get("text_request_limit_triggered")),
        })

    standard_report = read_json(standard_dir / "selection_report.json")
    loose_report = read_json(loose_dir / "selection_report.json")
    standard_chars = int(standard_report.get("estimated_input_chars") or 0)
    loose_chars = int(loose_report.get("estimated_input_chars") or 0)
    gold_total = len(gold_keys)
    review_queue.sort(key=lambda item: (
        item["risk_category"] != "potential_result_evidence",
        -int(item.get("relevance_score") or 0),
        item["notice_id"],
        item["block_id"],
    ))

    def dimension_report(values: dict[str, Counter[str]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for name, counts in sorted(values.items()):
            gold = counts["gold"]
            output[name] = {
                **dict(counts),
                "standard_recall": round(counts["standard_retained"] / gold, 4) if gold else 1.0,
                "loose_recall": round(counts["loose_retained"] / gold, 4) if gold else 1.0,
            }
        return output

    return {
        "audit_type": "gold_recall_and_relaxed_selection_counterfactual",
        "notice_count": len(common_ids),
        "standard": {
            "selector_version": standard_report.get("selector_version"),
            "selector_config": standard_report.get("selector_config"),
            "original_block_count": standard_report.get("original_block_count"),
            "selected_source_block_count": standard_report.get("selected_source_block_count"),
            "block_reduction_ratio": standard_report.get("block_reduction_ratio"),
            "api_request_count": standard_report.get("api_request_count"),
            "estimated_input_chars": standard_chars,
            "limit_activation": aggregate_limit_stats(standard),
        },
        "loose": {
            "selector_version": loose_report.get("selector_version"),
            "selector_config": loose_report.get("selector_config"),
            "original_block_count": loose_report.get("original_block_count"),
            "selected_source_block_count": loose_report.get("selected_source_block_count"),
            "block_reduction_ratio": loose_report.get("block_reduction_ratio"),
            "api_request_count": loose_report.get("api_request_count"),
            "estimated_input_chars": loose_chars,
            "limit_activation": aggregate_limit_stats(loose),
        },
        "cost_delta": {
            "additional_selected_blocks": loose_only_count,
            "additional_requests": int(loose_report.get("api_request_count") or 0) - int(standard_report.get("api_request_count") or 0),
            "additional_input_chars": loose_chars - standard_chars,
            "input_char_growth_ratio": round((loose_chars - standard_chars) / standard_chars, 4) if standard_chars else None,
        },
        "gold_evidence": {
            "gold_item_count": gold_total,
            "standard_retained": standard_hits,
            "standard_recall": round(standard_hits / gold_total, 4) if gold_total else 1.0,
            "loose_retained": loose_hits,
            "loose_recall": round(loose_hits / gold_total, 4) if gold_total else 1.0,
            "standard_missed": missed_standard,
            "loose_missed": missed_loose,
            "by_source_format": dimension_report(format_counts),
            "by_block_type": dimension_report(content_type_counts),
        },
        "loose_only_review": {
            "block_count": loose_only_count,
            "risk_category_counts": dict(risk_counts),
            "note": "风险分类仅用于安排人工复核，不等同于真实标签。",
            "candidates": review_queue[:review_limit],
            "candidate_output_truncated": len(review_queue) > review_limit,
        },
        "per_notice": per_notice,
        "interpretation_guardrails": [
            "金标召回率衡量已标注证据是否被保留；不能证明未标注公告不存在漏选。",
            "压缩率只是输入成本指标，不能单独用于判断筛选质量。",
            "宽松新增 Block 的风险分类是启发式复核队列，不是模型准确率。",
        ],
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    standard = report["standard"]
    loose = report["loose"]
    gold = report["gold_evidence"]
    delta = report["cost_delta"]
    risk = report["loose_only_review"]["risk_category_counts"]
    lines = [
        "# Block 预筛选召回审计", "",
        "> 本报告是金标证据召回与宽松参数反事实测试，不是模型准确率报告。", "",
        "## 核心结果", "",
        f"- 测试公告：{report['notice_count']} 篇；金标实体/证据行：{gold['gold_item_count']} 条。",
        f"- 标准筛选：压缩率 {float(standard.get('block_reduction_ratio') or 0):.2%}，金标证据召回 {gold['standard_recall']:.2%}。",
        f"- 宽松筛选：压缩率 {float(loose.get('block_reduction_ratio') or 0):.2%}，金标证据召回 {gold['loose_recall']:.2%}。",
        f"- 宽松配置额外保留 {delta['additional_selected_blocks']} 个 Blocks、{delta['additional_requests']} 个请求、{delta['additional_input_chars']} 个输入字符。",
        f"- 宽松新增 Block 风险队列：潜在结果证据 {risk.get('potential_result_evidence', 0)}，采购需求/模板 {risk.get('likely_template_or_demand', 0)}，低或不确定信号 {risk.get('low_or_ambiguous_signal', 0)}。", "",
        "## 限额触发", "",
        f"- 标准表格来源上限触发公告：{standard['limit_activation'].get('table_source_limit_notice_count', 0)}。",
        f"- 标准正文请求上限触发公告：{standard['limit_activation'].get('text_request_limit_notice_count', 0)}。",
        f"- 因表格来源上限未选 Block：{standard['limit_activation'].get('table_blocks_excluded_by_source_limit', 0)}。",
        f"- 因正文请求上限未选分组：{standard['limit_activation'].get('text_groups_excluded_by_request_limit', 0)}。", "",
        "## 解释边界", "",
    ]
    lines.extend(f"- {item}" for item in report["interpretation_guardrails"])
    lines.extend(["", "详细逐公告结果和宽松新增 Block 摘要见同目录 JSON。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block-dir", type=Path, required=True)
    parser.add_argument("--standard-dir", type=Path, required=True)
    parser.add_argument("--loose-dir", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "dataset_build" / "gold" / "notices")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-limit", type=int, default=100)
    args = parser.parse_args()
    report = build_audit(
        args.block_dir,
        args.standard_dir,
        args.loose_dir,
        args.gold_dir,
        review_limit=args.review_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, args.output.with_suffix(".md"))
    print(json.dumps({
        "notice_count": report["notice_count"],
        "standard_reduction": report["standard"]["block_reduction_ratio"],
        "standard_gold_recall": report["gold_evidence"]["standard_recall"],
        "loose_gold_recall": report["gold_evidence"]["loose_recall"],
        "additional_blocks": report["cost_delta"]["additional_selected_blocks"],
        "additional_input_chars": report["cost_delta"]["additional_input_chars"],
        "risk_counts": report["loose_only_review"]["risk_category_counts"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
