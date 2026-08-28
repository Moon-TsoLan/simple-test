# -*- coding: utf-8 -*-
"""Verify the isolated ten-gold-notice offline full-pipeline pilot."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import create_app  # noqa: E402
from src.api.database import ApplicationStore  # noqa: E402
from src.relation.agent import RelationAgentConfig, select_relation_evidence  # noqa: E402
from src.relation.queries import RelationQueries  # noqa: E402
from src.relation.schema import ProjectRelationInput  # noqa: E402
from src.relation.store import RelationStore  # noqa: E402


EXPECTED_RESULT_BLOCKS = {
    "20260629_26835308": "20260629_26835308:blk_91979a6486ed0e41ec2cef13",
    "20260813_27128600": "20260813_27128600:blk_d85dd3abf63fbdeca31f4ecf",
    "20260814_27137567": "20260814_27137567:blk_76949f978f960f7a1f040798",
    "20260814_27138043": "20260814_27138043:blk_38dea05cdf9eafc6b647258a",
    "20260814_27139636": "20260814_27139636:blk_6707871bfe3b0648d488fe0d",
    "20260814_27139691": "20260814_27139691:blk_d623a000ccf745585ee4ac8e",
    "20260815_27140933": "20260815_27140933:blk_e69ad7e2447b1b0351383d16",
    "20260815_27141366": "20260815_27141366:blk_b87589abad725892b95730aa",
    "20260815_27141623": "20260815_27141623:blk_36123d2bf886686eea92b5b3",
    "20260815_27141793": "20260815_27141793:blk_42b068e14934fbabd9b4c374",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pilot-dir",
        type=Path,
        default=ROOT / "dataset_build" / "pilot" / "model_substitute_gold10_20260826",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "run" / "data" / "pilot_model_substitute_gold10_20260826.db",
    )
    args = parser.parse_args()

    parse_report = read_json(args.pilot_dir / "parse_report.json")
    standard = read_json(args.pilot_dir / "model_inputs_standard" / "selection_report.json")
    loose = read_json(args.pilot_dir / "model_inputs_loose" / "selection_report.json")
    selection_audit = read_json(args.pilot_dir / "block_selection_audit.json")
    task1_manifest = read_json(args.pilot_dir / "task1_results" / "agent_manifest.json")
    task1_gold = read_json(args.pilot_dir / "task1_gold_evaluation.json")
    relation_outcomes = [read_json(path) for path in sorted((args.pilot_dir / "relation_results").glob("*.json"))]

    assert parse_report["converted_count"] == 10 and parse_report["failed_count"] == 0
    assert parse_report["total_blocks"] == 9394 and parse_report["document_errors"] == 0
    assert standard["notice_count"] == loose["notice_count"] == 10
    assert standard["integrity"]["error_count"] == loose["integrity"]["error_count"] == 0
    assert standard["gold_evaluation"]["evidence_row_recall"] == 1.0
    assert loose["gold_evaluation"]["evidence_row_recall"] == 1.0
    assert selection_audit["gold_evidence"]["standard_recall"] == 1.0
    assert task1_manifest["notice_count"] == 10 and task1_manifest["item_count"] == 90
    assert task1_manifest["status_counts"] == {"success": 44}
    assert task1_gold["evidence_recall"] == 1.0
    assert all(value == 1.0 for value in task1_gold["field_exact_on_evidence_matched"].values())
    assert len(relation_outcomes) == 10 and all(value["status"] == "success" for value in relation_outcomes)

    retained_relation_results: dict[str, bool] = {}
    for notice_id, result_block_id in EXPECTED_RESULT_BLOCKS.items():
        payload = read_json(args.pilot_dir / "blocks" / f"{notice_id}.json")
        evidence = select_relation_evidence(payload, RelationAgentConfig())
        retained_relation_results[notice_id] = result_block_id in {block["block_id"] for block in evidence}
    assert all(retained_relation_results.values())

    store = RelationStore(args.db)
    queries = RelationQueries(store)
    expected_counts = {"projects": 10, "packages": 10, "organizations": 38, "bids": 18, "products": 90}
    assert store.counts() == expected_counts

    def org_id(name: str) -> str:
        exact = next((row for row in queries.organizations(name, 200) if row["name"].replace(" ", "") == name.replace(" ", "")), None)
        assert exact, f"organization not found: {name}"
        return str(exact["org_id"])

    unit_liangshan = org_id("凉山彝族自治州水利局")
    supplier_lushun = org_id("四川绿顺科技有限公司")
    supplier_rongsheng = org_id("成都荣盛鑫利科技有限公司")
    scenario1 = queries.unit_win_suppliers(unit_liangshan)
    scenario2_top = queries.unit_top_bidders(unit_liangshan, 10)
    scenario2_pairs = queries.unit_cobid_pairs(unit_liangshan)
    scenario3 = queries.supplier_cobidders(supplier_lushun, 10)
    scenario4 = queries.common_units([supplier_lushun, supplier_rongsheng])
    scenario5 = queries.joint_projects([supplier_lushun, supplier_rongsheng])
    assert scenario1[0]["supplier_name"] == "四川绿顺科技有限公司"
    assert len(scenario2_top) == 7 and len(scenario2_pairs) == 21
    assert len(scenario3) == 6
    assert scenario4 == []  # 场景四只统计共同中标；第二家在本样本中是候选人。
    assert len(scenario5) == 1 and scenario5[0]["notice_id"] == "20260815_27140933"
    project = next(row for row in queries.projects("防汛物资") if row["notice_id"] == "20260815_27140933")
    graph = queries.project_subgraph(str(project["project_id"]))
    assert graph["nodes"] and graph["edges"]

    counts_before = store.counts()
    for outcome in relation_outcomes:
        store.ingest(ProjectRelationInput.model_validate(outcome["project"]), refresh=False)
    store.refresh_aggregates()
    assert store.counts() == counts_before
    task1_reimport = ApplicationStore(args.db).import_task1_directory(args.pilot_dir / "task1_results" / "notices")
    assert task1_reimport == {"notices": 10, "entities": 90, "failures": 0}

    app = create_app(
        args.db,
        frontend_dist=ROOT / "frontend" / "dist",
        upload_dir=ROOT / "run" / "uploads" / "pilot_model_substitute_gold10_20260826",
        block_dir=args.pilot_dir / "blocks",
    )
    client = TestClient(app)
    status_response = client.get("/api/status")
    items_response = client.get("/api/task1/items", params={"page_size": 100})
    items = items_response.json()["items"]
    detail_response = client.get(f"/api/task1/items/{items[0]['entity_id']}")
    csv_response = client.get("/api/task1/export.csv")
    xlsx_response = client.get("/api/task1/export.xlsx")
    root_response = client.get("/")
    assert status_response.status_code == 200
    assert items_response.status_code == 200 and items_response.json()["total"] == 90
    assert detail_response.status_code == 200 and detail_response.json().get("evidence_excerpt")
    assert len(csv_response.content.decode("utf-8-sig").splitlines()) == 91
    assert xlsx_response.status_code == 200 and xlsx_response.content.startswith(b"PK")
    assert root_response.status_code == 200 and 'id="app"' in root_response.text

    latency_paths = {
        "task1_search": ("/api/task1/items", {"page_size": 20}),
        "scenario1": (f"/api/task2/units/{unit_liangshan}/win-suppliers", {}),
        "scenario2": (f"/api/task2/units/{unit_liangshan}/top-bidders", {"top": 10}),
        "scenario3": (f"/api/task2/suppliers/{supplier_lushun}/co-bidders", {"top": 10}),
        "scenario4": ("/api/task2/suppliers/common-units", {"ids": f"{supplier_lushun},{supplier_rongsheng}"}),
        "scenario5": ("/api/task2/suppliers/joint-projects", {"ids": f"{supplier_lushun},{supplier_rongsheng}"}),
        "graph": ("/api/task2/graph/subgraph", {"project_id": project["project_id"]}),
    }
    latency: dict[str, dict[str, float]] = {}
    for name, (path, params) in latency_paths.items():
        durations: list[float] = []
        for _ in range(10):
            started = time.perf_counter()
            response = client.get(path, params=params)
            durations.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
        latency[name] = {
            "median_ms": round(sorted(durations)[len(durations) // 2], 3),
            "p95_ms": round(percentile95(durations), 3),
        }

    report = {
        "pilot_name": "model_substitute_gold10_20260826",
        "scope": {
            "notices": 10,
            "documents": parse_report["total_documents"],
            "blocks": parse_report["total_blocks"],
            "task1_requests": task1_manifest["request_count"],
            "task1_items": task1_manifest["item_count"],
            "relation_projects": 10,
            "relation_bids": 18,
            "relation_products": 90,
        },
        "model_substitute": {
            "mode": "gold_constrained_task1_and_codex_manual_relation_offline_replay",
            "external_api_calls": 0,
            "task1_replay_calls": task1_manifest["usage"]["calls"],
            "relation_replay_calls": 10,
            "accuracy_guardrail": "任务一结果由金标约束生成，只验证工程链路；不得作为模型准确率。",
        },
        "selection": {
            "standard": {
                "selector_version": standard["selector_version"],
                "selected_blocks": standard["selected_source_block_count"],
                "reduction_ratio": standard["block_reduction_ratio"],
                "requests": standard["api_request_count"],
                "input_chars": standard["estimated_input_chars"],
                "gold_evidence_recall": standard["gold_evaluation"]["evidence_row_recall"],
            },
            "loose": {
                "selected_blocks": loose["selected_source_block_count"],
                "reduction_ratio": loose["block_reduction_ratio"],
                "requests": loose["api_request_count"],
                "input_chars": loose["estimated_input_chars"],
                "gold_evidence_recall": loose["gold_evaluation"]["evidence_row_recall"],
            },
            "counterfactual_delta": selection_audit["cost_delta"],
            "loose_only_risk_counts": selection_audit["loose_only_review"]["risk_category_counts"],
            "standard_limit_activation": selection_audit["standard"]["limit_activation"],
        },
        "task1_validation": task1_gold,
        "relation_evidence": {
            "result_block_retained_count": sum(retained_relation_results.values()),
            "expected_result_block_count": len(retained_relation_results),
            "per_notice": retained_relation_results,
            "regression_fixed": (
                "招标/采购/评分模板曾占满关系证据字符预算；现已排除模板来源并优先结果公告和评审表。"
            ),
        },
        "database": {"counts": store.counts(), "idempotent_reimport": True},
        "scenarios": {
            "scenario1_rows": len(scenario1),
            "scenario2_top_rows": len(scenario2_top),
            "scenario2_pair_rows": len(scenario2_pairs),
            "scenario3_rows": len(scenario3),
            "scenario4_rows": len(scenario4),
            "scenario4_note": "本样本不存在两家共同中标供应商，正确返回空集。",
            "scenario5_rows": len(scenario5),
            "graph_nodes": len(graph["nodes"]),
            "graph_edges": len(graph["edges"]),
        },
        "platform": {
            "root_http_status": root_response.status_code,
            "task1_search_total": items_response.json()["total"],
            "evidence_excerpt_available": bool(detail_response.json().get("evidence_excerpt")),
            "csv_data_rows": 90,
            "xlsx_export_valid": True,
        },
        "small_sample_latency": latency,
        "limitations": [
            "10篇金标覆盖 HTML、DOCX、XLSX、PDF，但样本量仍不足以代表291篇总体召回。",
            "宽松新增Block的风险分类是启发式人工复核队列，不是真实负标签。",
            "任务一离线响应由金标约束生成，验证的是筛选、校验、合并和持久化，不是模型泛化能力。",
            "任务二关系由Codex人工复核后离线回放，不是本地模型推理结果。",
            "延迟来自TestClient和小型数据库，不是正式生产P95。",
        ],
    }
    (args.pilot_dir / "pilot_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    risk = report["selection"]["loose_only_risk_counts"]
    markdown = [
        "# 10篇金标扩展全流程测试报告", "",
        "> 任务一采用金标约束离线回放，任务二采用 Codex 人工复核关系离线回放；本报告不是模型准确率报告。", "",
        "## 结果", "",
        f"- 原始公告：10篇，文档：{parse_report['total_documents']}个，Blocks：{parse_report['total_blocks']}个。",
        f"- 标准筛选：{standard['selected_source_block_count']}个来源Blocks，压缩率{standard['block_reduction_ratio']:.2%}，90/90条金标证据保留。",
        f"- 宽松筛选：{loose['selected_source_block_count']}个来源Blocks，压缩率{loose['block_reduction_ratio']:.2%}，仍为90/90条金标证据保留。",
        f"- 宽松配置额外增加{selection_audit['cost_delta']['additional_selected_blocks']}个Blocks和{selection_audit['cost_delta']['additional_input_chars']}个输入字符；潜在结果证据风险项{risk.get('potential_result_evidence', 0)}个。",
        "- 任务一：44/44请求成功，90条结构化实体，证据及9字段全部精确一致。",
        "- 任务二：10/10项目成功，18条竞标记录、90个产品；10/10实际结果表进入关系证据窗口。",
        f"- 独立数据库：{store.counts()}。",
        f"- 图谱：{len(graph['nodes'])}个节点、{len(graph['edges'])}条边；CSV/XLSX/API/前端入口均通过。",
        "- 外部API调用：0次。", "",
        "## 筛选结论", "",
        "在这10篇已标注样本上，没有证据表明98.66%的压缩率排除了有效任务一证据。宽松配置显著增加输入量，却没有增加金标召回；新增内容主要是低信号正文或采购需求/模板。这个结论不能直接外推到291篇未标注数据，因此保留宽松差异复核队列作为后续抽样入口。", "",
        "## 已修复问题", "",
        "- 识别“合计/小计”为总价列，避免校验阶段清空正确金额。",
        "- 筛选报告新增表格来源上限、正文请求上限及被截断数量。",
        "- 关系证据排除招标/采购/评分模板，优先HTML结果表和评审情况表，修复实际中标表被字符预算挤出的情况。", "",
        "## 限制", "",
    ]
    markdown.extend(f"- {item}" for item in report["limitations"])
    (args.pilot_dir / "pilot_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
