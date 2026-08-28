# -*- coding: utf-8 -*-
"""Combine manually reviewed project/bid relations with task-1 products.

The output is a ReplayBackend file for an offline full-pipeline pilot.  The
manual seed remains small and reviewable; verified task-1 items are mapped to
the first package without retyping product fields.  This is an engineering
replay artifact and must not be reported as model accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.relation.schema import ProjectRelationInput  # noqa: E402


def product_from_task1(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("product_service_name"),
        "category_code": item.get("category_code"),
        "brand": item.get("brand_supplier"),
        "spec_model": item.get("spec_model"),
        "supplier": None,
    }


def build(seed: dict[str, Any], task1_dir: Path) -> dict[str, Any]:
    projects = seed.get("projects")
    if not isinstance(projects, list) or not projects:
        raise ValueError("seed must contain a non-empty projects array")
    responses: dict[str, Any] = {}
    task1_item_count = 0
    per_notice: list[dict[str, Any]] = []
    for raw_project in projects:
        if not isinstance(raw_project, dict):
            raise ValueError("each project seed must be an object")
        notice_id = str(raw_project.get("notice_id") or "")
        task1_path = task1_dir / f"{notice_id}.json"
        if not task1_path.exists():
            raise FileNotFoundError(f"task-1 result missing for {notice_id}: {task1_path}")
        task1 = json.loads(task1_path.read_text(encoding="utf-8"))
        if task1.get("status") != "complete":
            raise ValueError(f"task-1 result is not complete for {notice_id}")
        packages = raw_project.get("packages") or []
        if not packages:
            raise ValueError(f"manual project has no package: {notice_id}")
        products = [product_from_task1(item) for item in task1.get("items") or []]
        packages[0]["products"] = products
        raw_project["packages"] = packages
        project = ProjectRelationInput.model_validate(raw_project).model_dump(mode="json")
        responses[f"{notice_id}:relation"] = project
        bidder_count = sum(len(package["bidders"]) for package in project["packages"])
        task1_item_count += len(products)
        per_notice.append({
            "notice_id": notice_id,
            "package_count": len(project["packages"]),
            "bidder_count": bidder_count,
            "product_count": len(products),
        })
    return {
        "schema_version": "1.0",
        "response_source": "codex_manual_relation_plus_verified_task1_products",
        "created_at": date.today().isoformat(),
        "annotation_note": (
            "项目、机构和竞标关系由 Codex 根据结果证据人工复核；产品来自已通过证据校验的任务一结果。"
            "本文件只用于离线回放和工程验收，不代表模型准确率。"
        ),
        "coverage": {
            "notice_count": len(per_notice),
            "task1_product_count": task1_item_count,
            "bidder_count": sum(item["bidder_count"] for item in per_notice),
            "per_notice": per_notice,
        },
        "responses": responses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--task1-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    payload = build(seed, args.task1_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["coverage"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
