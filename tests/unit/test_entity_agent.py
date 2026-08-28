from __future__ import annotations

import json

from src.agents.backends import FakeBackend
from src.agents.entity_extraction_agent import AgentConfig, EntityExtractionAgent
from src.agents.merger import merge_notice


def make_request(evidence: dict, request_id: str = "n1:req_001") -> dict:
    user = {"notice_id": "n1", "title": "测试中标公告", "evidence": evidence}
    return {
        "notice_id": "n1",
        "title": "测试中标公告",
        "request_id": request_id,
        "content_kind": evidence["kind"],
        "api_payload": {
            "messages": [
                {"role": "system", "content": "只输出JSON"},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ]
        },
    }


def table_evidence(rows: list[dict] | None = None) -> dict:
    return {
        "kind": "table",
        "block_id": "n1:blk_table",
        "source": {
            "document_id": "doc1",
            "file_name": "分项报价表.pdf",
            "container_path": "n1.zip/分项报价表.pdf",
            "file_type": "pdf",
            "page": 1,
            "table_index": 1,
        },
        "matched_fields": [
            "product_service_name", "brand_supplier", "spec_model", "quantity",
            "quantity_unit", "unit_price", "total_price",
        ],
        "field_columns": {
            "product_service_name": 0,
            "brand_supplier": 1,
            "spec_model": 2,
            "quantity": 3,
            "quantity_unit": 4,
            "unit_price": 5,
            "total_price": 6,
        },
        "header": ["名称", "品牌", "型号", "数量", "单位", "单价", "合价"],
        "data_rows": rows or [
            {"block_row": 2, "cells": ["交换机", "华三", "S5130", "2", "台", "1000.00", "2000.00"]}
        ],
    }


def test_rule_fast_path_extracts_and_binds_evidence() -> None:
    agent = EntityExtractionAgent()
    result = agent.process_request(make_request(table_evidence()))
    assert result["status"] == "success"
    assert result["method"] == "rules"
    assert result["usage"]["calls"] == 0
    assert result["items"][0]["product_service_name"] == "交换机"
    assert result["items"][0]["total_price"] == 2000
    assert result["items"][0]["price_consistency"] == "ok"
    assert result["items"][0]["source_block_row"] == 2
    assert result["workflow_trace"] == ["prepare", "rule_extract"]
    assert result["confidence_basis"].startswith("rule_table_mapped_fields:")


def test_blank_total_template_is_filtered_without_model_call() -> None:
    evidence = table_evidence([{
        "block_row": 2,
        "cells": [
            "总价：佰拾万仟佰拾元角分（大写）￥（小写）",
            "总价：佰拾万仟佰拾元角分（大写）￥（小写）",
            "总价：佰拾万仟佰拾元角分（大写）￥（小写）",
            "", "", "", "",
        ],
    }])
    backend = FakeBackend([])
    result = EntityExtractionAgent(backend).process_request(make_request(evidence))
    assert result["status"] == "success"
    assert result["method"] == "local_non_result_filter"
    assert result["items"] == []
    assert result["usage"]["calls"] == 0


def test_think_wrapped_json_is_accepted_without_repair() -> None:
    from src.agents.validators import parse_json_output

    wrapped = (
        "<think>先看表格再输出</think>\n"
        '{"items":[{"product_service_name":"交换机","category_name":null,'
        '"category_code":null,"brand_supplier":"华三","spec_model":"S5130",'
        '"unit_price":1000,"quantity":2,"quantity_unit":"台","total_price":2000,'
        '"evidence_refs":[{"block_id":"n1:blk_text","block_row":null}]}],'
        '"warnings":[]}'
    )
    parsed = parse_json_output(wrapped)
    assert parsed["items"][0]["product_service_name"] == "交换机"

    evidence = {
        "kind": "text",
        "blocks": [{
            "block_id": "n1:blk_text",
            "type": "paragraph",
            "source": {"document_id": "doc1", "file_name": "n1.html", "container_path": "n1.html"},
            "text": "主要标的信息：交换机，成交价2000元。",
        }],
    }
    backend = FakeBackend([wrapped])
    result = EntityExtractionAgent(backend).process_request(make_request(evidence))
    assert result["status"] == "success"
    assert result["method"] == "model"
    assert result["repair_attempts"] == 0
    assert result["usage"]["calls"] == 1
    assert result["items"][0]["product_service_name"] == "交换机"


def test_non_json_is_repaired_once() -> None:
    evidence = {
        "kind": "text",
        "blocks": [{
            "block_id": "n1:blk_text",
            "type": "paragraph",
            "source": {"document_id": "doc1", "file_name": "n1.html", "container_path": "n1.html"},
            "text": "主要标的信息：交换机，成交价2000元。",
        }],
    }
    backend = FakeBackend([
        "not-json",
        {"items": [{
            "product_service_name": "交换机",
            "total_price": 2000,
            "evidence_refs": [{"block_id": "n1:blk_text", "block_row": None}],
        }], "warnings": []},
    ])
    result = EntityExtractionAgent(backend).process_request(make_request(evidence))
    assert result["status"] == "success"
    assert result["method"] == "model_repaired"
    assert result["repair_attempts"] == 1
    assert result["usage"]["calls"] == 2
    assert len(backend.calls) == 2
    assert backend.calls[1]["repair_errors"]


def test_invalid_table_row_is_rejected() -> None:
    backend = FakeBackend([{"items": [{
        "product_service_name": "交换机",
        "evidence_refs": [{"block_id": "n1:blk_table", "block_row": 99}],
    }], "warnings": []}])
    agent = EntityExtractionAgent(
        backend,
        AgentConfig(enable_rule_fast_path=False, max_repair_attempts=0),
    )
    result = agent.process_request(make_request(table_evidence()))
    assert result["status"] == "failed"
    assert not result["items"]
    assert any("valid evidence_refs" in error for error in result["errors"])


def test_amount_conflict_is_reported() -> None:
    rows = [{"block_row": 2, "cells": ["交换机", "华三", "S5130", "2", "台", "1000", "5000"]}]
    result = EntityExtractionAgent().process_request(make_request(table_evidence(rows)))
    assert result["items"][0]["price_consistency"] == "mismatch"
    assert any("amount mismatch" in warning for warning in result["warnings"])


def test_notice_merge_deduplicates_and_preserves_conflict() -> None:
    base_item = {
        "product_service_name": "交换机",
        "category_name": None,
        "category_code": None,
        "brand_supplier": "华三",
        "spec_model": "S5130",
        "unit_price": 1000,
        "quantity": 2,
        "quantity_unit": "台",
        "total_price": 2000,
        "evidence_refs": [{"block_id": "b1", "block_row": 2}],
    }
    exact_duplicate = {**base_item, "evidence_refs": [{"block_id": "b2", "block_row": 3}]}
    conflict = {**base_item, "total_price": 2100}
    outcomes = [
        {"request_id": "n1:r1", "status": "success", "method": "rules", "confidence": 0.9, "warnings": [], "items": [base_item]},
        {"request_id": "n1:r2", "status": "success", "method": "model", "confidence": 0.8, "warnings": [], "items": [exact_duplicate]},
        {"request_id": "n1:r3", "status": "success", "method": "model", "confidence": 0.8, "warnings": [], "items": [conflict]},
    ]
    notice = merge_notice("n1", "测试", outcomes, agent_version="test")
    assert notice["item_count"] == 1
    assert len(notice["items"][0]["evidence_refs"]) == 2
    assert notice["items"][0]["field_conflicts"][0]["field"] == "total_price"
    assert notice["warnings"]


def test_notice_merge_removes_procurement_source_and_merges_result_duplicates() -> None:
    html_item = {
        "product_service_name": "交换机（核心产品）",
        "category_name": None,
        "category_code": None,
        "brand_supplier": "华三",
        "spec_model": "S5130",
        "unit_price": 1000,
        "quantity": 2,
        "quantity_unit": "台",
        "total_price": 2000,
        "evidence_refs": [{"block_id": "html", "block_row": 2}],
        "source": {"file_name": "结果公告.html", "file_type": "html"},
    }
    quote_duplicate = {
        **html_item,
        "product_service_name": "▲交换机（核心产品）",
        "evidence_refs": [{"block_id": "quote", "block_row": 3}],
        "source": {"file_name": "分项报价表.pdf", "file_type": "pdf"},
    }
    requirement = {
        **html_item,
        "product_service_name": "采购需求交换机",
        "evidence_refs": [{"block_id": "requirement", "block_row": 4}],
        "source": {"file_name": "项目招标文件.docx", "file_type": "docx"},
    }
    outcomes = [{
        "request_id": "n1:r1", "status": "success", "method": "model", "confidence": 0.84,
        "warnings": [], "items": [html_item, quote_duplicate, requirement],
    }]
    notice = merge_notice("n1", "交换机采购项目中标公告", outcomes, agent_version="test")
    assert notice["item_count"] == 1
    assert len(notice["items"][0]["evidence_refs"]) == 2
    assert notice["postprocess"]["removed_non_result_count"] == 1
    assert notice["postprocess"]["merged_duplicate_count"] == 1
