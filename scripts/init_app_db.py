# -*- coding: utf-8 -*-
"""Initialize the application database and optionally import current results."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from src.api.database import ApplicationStore  # noqa: E402
from src.relation.schema import ProjectRelationInput  # noqa: E402
from src.relation.store import RelationStore  # noqa: E402


def load_relation_inputs(path: Path) -> list[ProjectRelationInput]:
    """Accept a direct project, a relation-agent outcome, or a list of either."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload if isinstance(payload, list) else [payload]
    projects: list[ProjectRelationInput] = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: relation entry must be an object")
        if isinstance(value.get("project"), dict):
            if value.get("status") not in {None, "success"}:
                raise ValueError(f"{path}: refusing to import relation outcome with status={value.get('status')}")
            value = value["project"]
        projects.append(ProjectRelationInput.model_validate(value))
    return projects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "run" / "data" / "application.db")
    parser.add_argument("--import-task1", action="store_true")
    parser.add_argument("--task1-dir", type=Path, default=ROOT / "dataset_build" / "agent_results" / "notices")
    parser.add_argument("--relation-json", type=Path, action="append", default=[])
    parser.add_argument(
        "--relation-dir", type=Path, action="append", default=[],
        help="Import every successful relation-agent JSON outcome in this directory",
    )
    args = parser.parse_args()
    app_store = ApplicationStore(args.db); relation_store = RelationStore(args.db)
    report = {
        "db": str(args.db), "task1": None, "task2_imported": 0,
        "task2_failed": 0, "task2_errors": [],
    }
    if args.import_task1: report["task1"] = app_store.import_task1_directory(args.task1_dir)
    relation_paths = list(args.relation_json)
    for directory in args.relation_dir:
        relation_paths.extend(sorted(directory.glob("*.json")))
    for path in relation_paths:
        try:
            for project in load_relation_inputs(path):
                relation_store.ingest(project, refresh=False)
                report["task2_imported"] += 1
        except Exception as exc:
            report["task2_failed"] += 1
            report["task2_errors"].append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    if relation_paths: relation_store.refresh_aggregates()
    report["task2_counts"] = relation_store.counts()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["task2_failed"] else 0


if __name__ == "__main__": raise SystemExit(main())
