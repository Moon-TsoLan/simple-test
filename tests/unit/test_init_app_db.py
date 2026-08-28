from __future__ import annotations

import json

import pytest

from scripts.init_app_db import load_relation_inputs


def test_relation_loader_accepts_success_agent_envelope(tmp_path) -> None:
    path = tmp_path / "relation.json"
    path.write_text(json.dumps({
        "notice_id": "N-1", "status": "success", "project": {
            "notice_id": "N-1", "title": "测试项目", "packages": [],
        },
    }, ensure_ascii=False), encoding="utf-8")
    projects = load_relation_inputs(path)
    assert len(projects) == 1 and projects[0].notice_id == "N-1"


def test_relation_loader_rejects_unconfirmed_agent_envelope(tmp_path) -> None:
    path = tmp_path / "relation.json"
    path.write_text(json.dumps({
        "notice_id": "N-1", "status": "candidate_only", "project": {
            "notice_id": "N-1", "title": "测试项目", "packages": [],
        },
    }, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to import"):
        load_relation_inputs(path)


def test_relation_loader_accepts_notice_file_from_relation_directory(tmp_path) -> None:
    path = tmp_path / "N-002.json"
    path.write_text(json.dumps({
        "status": "success",
        "project": {"notice_id": "N-002", "title": "目录导入测试", "packages": []},
    }, ensure_ascii=False), encoding="utf-8")
    projects = load_relation_inputs(path)
    assert len(projects) == 1
    assert projects[0].notice_id == "N-002"
