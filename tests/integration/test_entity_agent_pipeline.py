from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_entity_agent import run


def test_rules_cli_pipeline_and_resume(tmp_path: Path) -> None:
    evidence = {
        "kind": "table",
        "block_id": "n1:block",
        "source": {"document_id": "doc", "file_name": "报价表.xlsx", "container_path": "n1/报价表.xlsx"},
        "matched_fields": ["product_service_name", "quantity", "unit_price", "total_price"],
        "field_columns": {"product_service_name": 0, "quantity": 1, "unit_price": 2, "total_price": 3},
        "header": ["名称", "数量", "单价", "合价"],
        "data_rows": [{"block_row": 2, "cells": ["服务器", "1台", "12000", "12000"]}],
    }
    user = {"notice_id": "n1", "title": "测试成交公告", "evidence": evidence}
    request = {
        "notice_id": "n1",
        "title": "测试成交公告",
        "request_id": "n1:req_001",
        "content_kind": "table",
        "api_payload": {"messages": [
            {"role": "system", "content": "只输出JSON"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]},
    }
    input_path = tmp_path / "requests.jsonl"
    input_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    output_path = tmp_path / "result"
    args = argparse.Namespace(
        input=input_path,
        output=output_path,
        config=tmp_path / "unused.yaml",
        backend="rules",
        allow_external_api=False,
        model_only=False,
        keep_covered_text=False,
        max_repair_attempts=1,
        limit_requests=0,
        limit_notices=0,
        force=False,
    )
    first = run(args)
    second = run(args)
    assert first["item_count"] == 1
    assert first["usage"]["calls"] == 0
    assert second["item_count"] == 1
    assert len((output_path / "agent_state.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    notice = json.loads((output_path / "notices" / "n1.json").read_text(encoding="utf-8"))
    assert notice["items"][0]["quantity_unit"] == "台"


def test_replay_tool_verification_is_persisted_and_resumed(tmp_path: Path) -> None:
    evidence = {
        "kind": "table",
        "block_id": "20240101_n1:block",
        "source": {"document_id": "doc", "file_name": "报价表.xlsx", "container_path": "n1/报价表.xlsx"},
        "matched_fields": [
            "product_service_name", "brand_supplier", "spec_model", "quantity",
            "quantity_unit", "unit_price", "total_price",
        ],
        "field_columns": {
            "product_service_name": 0, "brand_supplier": 1, "spec_model": 2,
            "quantity": 3, "quantity_unit": 4, "unit_price": 5, "total_price": 6,
        },
        "header": ["名称", "品牌", "型号", "数量", "单位", "单价", "合价"],
        "data_rows": [{"block_row": 2, "cells": ["交换机", "华三", "S5130", "2", "台", "1000", "2000"]}],
    }
    user = {"notice_id": "20240101_n1", "title": "测试中标公告", "evidence": evidence}
    request = {
        "notice_id": "20240101_n1",
        "request_id": "20240101_n1:req_001",
        "content_kind": "table",
        "api_payload": {"messages": [
            {"role": "system", "content": "只输出JSON"},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ]},
    }
    input_path = tmp_path / "requests.jsonl"
    input_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    query = "华三 2024 历史"
    source_url = "https://example.gov.cn/h3c"
    model_replay = tmp_path / "model_replay.json"
    model_replay.write_text(json.dumps({"responses": {"20240101_n1:verify:1": [
        {"_backend_response": {"output": "", "tool_calls": [{
            "name": "web_search", "args": {"query": query}, "id": "call_1", "type": "tool_call",
        }]}},
        {
            "candidate": "华三", "candidate_type": "brand", "as_of_date": "2024-01-01",
            "canonical_name": "华三", "verification_status": "verified_brand_at_date",
            "valid_at_date": True, "relations": [], "evidence_urls": [source_url],
            "reasoning_summary": "回放证据支持。", "warnings": [],
        },
    ]}}, ensure_ascii=False), encoding="utf-8")
    search_replay = tmp_path / "search_replay.json"
    search_replay.write_text(json.dumps({"responses": {query: [{
        "title": "历史", "url": source_url, "snippet": "历史证据",
    }]}}, ensure_ascii=False), encoding="utf-8")
    output_path = tmp_path / "result"
    args = argparse.Namespace(
        input=input_path, output=output_path, config=tmp_path / "unused.yaml",
        backend="replay", replay_file=model_replay, allow_external_api=False,
        model_only=False, keep_covered_text=False, max_repair_attempts=1,
        limit_requests=0, limit_notices=0, force=False,
        max_model_calls=3, max_total_tokens=1000,
        verify_web=True, allow_web_search=False, search_provider="replay",
        search_replay_file=search_replay, search_timeout_seconds=1,
        verify_max_entities=1, verify_max_search_rounds=1, verify_max_results=3,
    )

    first = run(args)
    second = run(args)
    assert first["verification"]["new_candidate_count"] == 1
    assert first["model_budget"]["calls"] == 2
    assert second["verification"]["new_candidate_count"] == 0
    assert second["verification"]["reused_candidate_count"] == 1
    assert second["model_budget"]["calls"] == 0
    notice = json.loads((output_path / "notices" / "20240101_n1.json").read_text(encoding="utf-8"))
    assert notice["external_verification"]["results"][0]["status"] == "success"
    assert notice["items"][0]["external_verification_id"].endswith("ext_001")
