from __future__ import annotations

from src.agents.backends import FakeBackend
from src.relation.agent import RelationAgentConfig, RelationExtractionAgent, select_relation_evidence


def _payload() -> dict:
    return {
        "notice_id": "AGENT-001",
        "title": "关系智能体测试",
        "blocks": [{
            "type": "table", "block_id": "AGENT-001:b1",
            "rows": [["供应商名称", "投标报价", "排名", "结果"], ["甲公司", "10万元", "1", "中标"]],
            "text": "供应商名称 投标报价 排名 结果 甲公司 10万元 1 中标",
        }],
    }


def _valid_project() -> dict:
    return {
        "notice_id": "AGENT-001", "title": "关系智能体测试",
        "packages": [{"package_no": "默认包", "bidders": [{
            "org": {"name": "甲公司", "org_type": "中标供应商"},
            "amount_yuan": 100000, "rank": 1, "result": "中标",
            "evidence_block_id": "AGENT-001:b1", "evidence_block_row": 2,
        }]}],
        "extraction_method": "local_model",
    }


def test_without_model_returns_candidate_only() -> None:
    outcome = RelationExtractionAgent().process(_payload())
    assert outcome["status"] == "candidate_only"
    assert outcome["usage"]["calls"] == 0
    assert outcome["project"]["packages"][0]["bidders"][0]["amount_yuan"] == 100000


def test_model_output_is_validated_against_evidence() -> None:
    backend = FakeBackend([_valid_project()])
    outcome = RelationExtractionAgent(backend).process(_payload())
    assert outcome["status"] == "success"
    assert outcome["usage"]["calls"] == 1
    assert outcome["project"]["packages"][0]["bidders"][0]["evidence_block_row"] == 2


def test_common_model_aliases_are_normalized_before_strict_validation() -> None:
    aliased = {
        "notice_id": "AGENT-001",
        "title": "关系智能体测试",
        "procurement_unit": {"name": "采购人", "org_type": "采购单位", "address": "不入库"},
        "packages": [{
            "package_id": "包1",
            "package_name": "测试包",
            "winner": {
                "supplier": {"name": "甲公司", "org_type": "中标供应商", "contact": "不入库"},
                "amount_yuan": 100000,
                "evidence_refs": [{"block_id": "AGENT-001:b1", "row": 2}],
            },
            "other_bidders": [],
        }],
    }
    outcome = RelationExtractionAgent(FakeBackend([aliased])).process(_payload())
    assert outcome["status"] == "success"
    package = outcome["project"]["packages"][0]
    assert package["package_no"] == "包1"
    assert package["bidders"][0]["result"] == "中标"
    assert package["bidders"][0]["evidence_refs"][0]["block_row"] == 2


def test_bad_reference_gets_one_bounded_repair() -> None:
    invalid = _valid_project()
    invalid["packages"][0]["bidders"][0]["evidence_block_id"] = "invented"
    backend = FakeBackend([invalid, _valid_project()])
    outcome = RelationExtractionAgent(backend).process(_payload())
    assert outcome["status"] == "success"
    assert outcome["method"] == "model_repaired"
    assert outcome["repair_attempts"] == 1
    assert len(backend.calls) == 2


def test_text_evidence_row_is_normalized_to_null() -> None:
    payload = {
        "notice_id": "TEXT-001",
        "title": "正文关系公告",
        "blocks": [{
            "type": "paragraph",
            "block_id": "TEXT-001:b1",
            "text": "中标供应商：甲公司；中标金额：10万元。",
        }],
    }
    project = {
        "notice_id": "TEXT-001",
        "title": "正文关系公告",
        "packages": [{"package_no": "默认包", "bidders": [{
            "org": {"name": "甲公司", "org_type": "中标供应商"},
            "amount_yuan": 100000,
            "result": "中标",
            "evidence_block_id": "TEXT-001:b1",
            "evidence_block_row": 2,
        }]}],
    }
    outcome = RelationExtractionAgent(FakeBackend([project])).process(payload)
    assert outcome["status"] == "success"
    assert outcome["project"]["packages"][0]["bidders"][0]["evidence_block_row"] is None


def test_invalid_table_row_is_recovered_from_unique_bidder_name() -> None:
    project = _valid_project()
    project["packages"][0]["bidders"][0]["evidence_block_row"] = 99
    project["packages"][0]["bidders"][0]["evidence_refs"] = [{
        "block_id": "AGENT-001:b1", "block_row": 99, "supports": ["供应商名称"],
    }]
    outcome = RelationExtractionAgent(FakeBackend([project])).process(_payload())
    assert outcome["status"] == "success"
    bidder = outcome["project"]["packages"][0]["bidders"][0]
    assert bidder["evidence_block_row"] == 2
    assert bidder["evidence_refs"][0]["block_row"] == 2


def test_invalid_table_row_falls_back_to_block_level_reference() -> None:
    project = _valid_project()
    project["packages"][0]["bidders"][0]["org"]["name"] = "乙公司"
    project["packages"][0]["bidders"][0]["evidence_block_row"] = 99
    outcome = RelationExtractionAgent(FakeBackend([project])).process(_payload())
    assert outcome["status"] == "success"
    assert outcome["project"]["packages"][0]["bidders"][0]["evidence_block_row"] is None


def test_large_structured_bidder_table_uses_deterministic_bypass() -> None:
    rows = [["序号", "投标单位名称", "投标报价(元)"]]
    rows.extend([[str(index), f"测试{index}有限公司", str(100000 + index)] for index in range(1, 81)])
    payload = {
        "notice_id": "LARGE-001", "title": "大型开标记录",
        "blocks": [{"type": "table", "block_id": "LARGE-001:b1", "rows": rows, "text": "投标单位名称 投标报价"}],
    }
    backend = FakeBackend([])
    outcome = RelationExtractionAgent(backend).process(payload)
    assert outcome["status"] == "success"
    assert outcome["method"] == "deterministic_large_table"
    assert outcome["usage"]["calls"] == 0
    assert len(outcome["project"]["packages"][0]["bidders"]) == 80


def test_relation_evidence_prioritizes_result_over_procurement_template() -> None:
    template = {
        "type": "table", "block_id": "AGENT-001:template",
        "source": {"file_name": "采购文件.pdf", "file_type": "pdf"},
        "rows": [["供应商名称", "投标报价", "评审结果"], ["投标人填写", "", ""]],
        "text": "供应商名称 投标报价 评审结果 中标候选人 评分办法",
    }
    result = {
        "type": "table", "block_id": "AGENT-001:result",
        "source": {"file_name": "AGENT-001.html", "file_type": "html"},
        "rows": [["供应商名称", "中标（成交）金额"], ["甲公司", "10万元"]],
        "text": "供应商名称 中标（成交）金额 甲公司 10万元",
    }
    evidence = select_relation_evidence(
        {"blocks": [template, result]},
        RelationAgentConfig(max_evidence_chars=200, max_blocks=1),
    )
    assert [block["block_id"] for block in evidence] == ["AGENT-001:result"]
