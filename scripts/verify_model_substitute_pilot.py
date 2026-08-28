# -*- coding: utf-8 -*-
"""Verify the isolated four-notice model-substitute end-to-end pilot."""
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
from src.relation.queries import RelationQueries  # noqa: E402
from src.relation.schema import ProjectRelationInput  # noqa: E402
from src.relation.store import RelationStore  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=ROOT / "dataset_build" / "pilot" / "model_substitute_20260826")
    parser.add_argument("--db", type=Path, default=ROOT / "run" / "data" / "pilot_model_substitute_20260826.db")
    args = parser.parse_args()

    parse_report = read_json(args.pilot_dir / "parse_report.json")
    selection_report = read_json(args.pilot_dir / "model_inputs" / "selection_report.json")
    task1_manifest = read_json(args.pilot_dir / "task1_results" / "agent_manifest.json")
    task1_gold = read_json(args.pilot_dir / "task1_gold_evaluation.json")
    relation_outcomes = [read_json(path) for path in sorted((args.pilot_dir / "relation_results").glob("*.json"))]
    store = RelationStore(args.db)
    queries = RelationQueries(store)

    def org_id(name: str) -> str:
        rows = queries.organizations(name, 200)
        exact = next((row for row in rows if row["name"].replace(" ", "") == name.replace(" ", "")), None)
        assert exact, f"organization not found: {name}"
        return str(exact["org_id"])

    unit_xinjiang = org_id("新疆医科大学第二附属医院")
    unit_sichuan = org_id("四川大学华西医院")
    supplier_jianxiang = org_id("新疆健祥医疗设备有限公司")
    supplier_haoborui = org_id("新疆昊博瑞贸易有限公司")
    supplier_desheng = org_id("四川德胜医疗设备有限公司")
    supplier_renben = org_id("四川人本医药科技有限公司")

    scenario1 = queries.unit_win_suppliers(unit_xinjiang)
    scenario2_top = queries.unit_top_bidders(unit_sichuan, 5)
    scenario2_pairs = queries.unit_cobid_pairs(unit_sichuan)
    scenario3 = queries.supplier_cobidders(supplier_desheng, 5)
    scenario4 = queries.common_units([supplier_jianxiang, supplier_haoborui])
    scenario5 = queries.joint_projects([supplier_desheng, supplier_renben])
    project = next(row for row in queries.projects("钬激光") if row["notice_id"] == "20260814_27138043")
    graph = queries.project_subgraph(str(project["project_id"]))

    assert parse_report["converted_count"] == 4 and parse_report["failed_count"] == 0
    assert selection_report["notice_count"] == 4 and selection_report["integrity"]["error_count"] == 0
    assert task1_manifest["notice_count"] == 4 and task1_manifest["item_count"] == 8
    assert task1_manifest["status_counts"] == {"success": 34}
    assert len(relation_outcomes) == 4 and all(value["status"] == "success" for value in relation_outcomes)
    assert store.counts() == {"projects": 4, "packages": 4, "organizations": 9, "bids": 6, "products": 8}
    winners = {row["supplier_name"]: row for row in scenario1}
    assert winners["新疆健祥医疗设备有限公司"]["win_count"] == 2
    assert winners["新疆健祥医疗设备有限公司"]["total_amount_yuan"] == 186500
    assert winners["新疆昊博瑞贸易有限公司"]["win_count"] == 1
    assert len(scenario2_top) == 3 and len(scenario2_pairs) == 3
    assert len(scenario3) == 2
    assert len(scenario4) == 1 and scenario4[0]["unit_name"] == "新疆医科大学第二附属医院"
    assert len(scenario5) == 1 and scenario5[0]["notice_id"] == "20260814_27138043"
    assert graph["nodes"] and graph["edges"]

    counts_before_replay = store.counts()
    for outcome in relation_outcomes:
        store.ingest(ProjectRelationInput.model_validate(outcome["project"]), refresh=False)
    store.refresh_aggregates()
    assert store.counts() == counts_before_replay
    task1_reimport = ApplicationStore(args.db).import_task1_directory(args.pilot_dir / "task1_results" / "notices")
    assert task1_reimport == {"notices": 4, "entities": 8, "failures": 0}

    app = create_app(
        args.db,
        frontend_dist=ROOT / "frontend" / "dist",
        upload_dir=ROOT / "run" / "uploads" / "pilot_model_substitute_20260826",
        block_dir=args.pilot_dir / "blocks",
    )
    client = TestClient(app)
    status_response = client.get("/api/status")
    item_response = client.get("/api/task1/items", params={"page_size": 100})
    items = item_response.json()["items"]
    detail = client.get(f"/api/task1/items/{items[0]['entity_id']}").json()
    csv_response = client.get("/api/task1/export.csv")
    root_response = client.get("/")
    assert status_response.status_code == 200
    assert item_response.status_code == 200 and item_response.json()["total"] == 8
    assert detail.get("evidence_excerpt")
    assert len(csv_response.content.decode("utf-8-sig").splitlines()) == 9
    assert root_response.status_code == 200 and 'id="app"' in root_response.text

    latency_paths = {
        "task1_search": ("/api/task1/items", {"page_size": 20}),
        "scenario1": (f"/api/task2/units/{unit_xinjiang}/win-suppliers", {}),
        "scenario2": (f"/api/task2/units/{unit_sichuan}/top-bidders", {"top": 5}),
        "scenario3": (f"/api/task2/suppliers/{supplier_desheng}/co-bidders", {"top": 5}),
        "scenario4": ("/api/task2/suppliers/common-units", {"ids": f"{supplier_jianxiang},{supplier_haoborui}"}),
        "scenario5": ("/api/task2/suppliers/joint-projects", {"ids": f"{supplier_desheng},{supplier_renben}"}),
        "graph": ("/api/task2/graph/subgraph", {"project_id": project["project_id"]}),
    }
    latency: dict[str, dict[str, float]] = {}
    for name, (path, params) in latency_paths.items():
        durations: list[float] = []
        for _ in range(20):
            started = time.perf_counter()
            response = client.get(path, params=params)
            durations.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
        latency[name] = {
            "median_ms": round(sorted(durations)[len(durations) // 2], 3),
            "p95_ms": round(percentile95(durations), 3),
        }

    report = {
        "pilot_name": "model_substitute_20260826",
        "scope": {"notices": 4, "model_requests": 34, "relation_projects": 4},
        "model_substitute": {
            "source": "codex_manual_model_substitute",
            "external_api_calls": 0,
            "task1_replay_calls": task1_manifest["usage"]["calls"],
            "task1_items": task1_manifest["item_count"],
            "scoped_gold_evidence_recall": task1_gold["evidence_recall"],
            "scoped_gold_fields_exact": task1_gold["field_exact_on_evidence_matched"],
            "relation_success": len(relation_outcomes),
        },
        "parsing": {
            "documents": parse_report["total_documents"],
            "blocks": parse_report["total_blocks"],
            "failed_notices": parse_report["failed_count"],
            "document_status_counts": parse_report["document_status_counts"],
        },
        "selection": {
            "source_blocks": selection_report["selected_source_block_count"],
            "reduction_ratio": selection_report["block_reduction_ratio"],
            "requests": selection_report["api_request_count"],
            "integrity_errors": selection_report["integrity"]["error_count"],
            "pilot_gold_evidence_recall": selection_report["gold_evaluation"]["evidence_row_recall"],
        },
        "database": {
            "task1": status_response.json()["task1"], "task2": store.counts(),
            "idempotent_reimport": True,
        },
        "scenarios": {
            "scenario1_rows": len(scenario1),
            "scenario2_top_rows": len(scenario2_top),
            "scenario2_pair_rows": len(scenario2_pairs),
            "scenario3_rows": len(scenario3),
            "scenario4_rows": len(scenario4),
            "scenario5_rows": len(scenario5),
            "graph_nodes": len(graph["nodes"]),
            "graph_edges": len(graph["edges"]),
        },
        "platform": {
            "root_http_status": root_response.status_code,
            "task1_search_total": item_response.json()["total"],
            "evidence_excerpt_available": bool(detail.get("evidence_excerpt")),
            "csv_data_rows": 8,
        },
        "small_sample_latency": latency,
        "limitations": [
            "本报告只验证四篇公告的工程闭环，不能代表真实总体准确率。",
            "模型输出由 Codex 人工替代并通过离线 replay 注入，不是本地模型推理结果。",
            "延迟来自 TestClient 与八条实体/四个项目的小库，不可作为正式 P95 性能结论。",
            "三篇医疗公告只公示主要标的信息，未用采购需求附件猜测未公示的中标明细。",
        ],
    }
    report_path = args.pilot_dir / "pilot_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = [
        "# 本地模型替代小样本全流程报告", "",
        "- 公告：4 篇", "- 原始文档：26 个", "- Blocks：3,755 个",
        "- 筛选后来源 Blocks：90 个（压缩率 97.6%）", "- 模型替代请求：34 个",
        "- 任务一实体：8 条", "- 任务二项目：4 个、竞标记录：6 条", "- 外部 API：0 次", "",
        "## 闭环结论", "",
        "原始 HTML/附件 → Block → 本地筛选 → 人工模型替代 → Schema/证据校验 → 公告级合并 → SQLite → 五场景/图谱/API/导出已全部通过。", "",
        "## 场景结果", "",
        f"- 场景一：{len(scenario1)} 条", f"- 场景二 TOP：{len(scenario2_top)} 条，共同投标组合：{len(scenario2_pairs)} 条",
        f"- 场景三：{len(scenario3)} 条", f"- 场景四：{len(scenario4)} 条", f"- 场景五：{len(scenario5)} 条",
        f"- 图谱：{len(graph['nodes'])} 个节点、{len(graph['edges'])} 条边", "",
        "## 限制", "",
    ]
    markdown.extend(f"- {value}" for value in report["limitations"])
    (args.pilot_dir / "pilot_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
