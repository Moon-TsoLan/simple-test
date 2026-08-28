from __future__ import annotations

import json
from pathlib import Path

from src.relation.extractor import RelationCandidateExtractor
from src.relation.queries import RelationQueries
from src.relation.schema import ProjectRelationInput
from src.relation.store import RelationStore


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "task2_synthetic.json"


def _seed(tmp_path: Path) -> tuple[RelationStore, RelationQueries, list[ProjectRelationInput]]:
    store = RelationStore(tmp_path / "relations.db")
    projects = [ProjectRelationInput.model_validate(value) for value in json.loads(FIXTURE.read_text(encoding="utf-8"))]
    for project in projects:
        store.ingest(project, refresh=False)
    store.refresh_aggregates()
    return store, RelationQueries(store), projects


def _org_id(queries: RelationQueries, name: str) -> str:
    return next(value["org_id"] for value in queries.organizations(name) if value["name"].replace(" ", "") == name.replace(" ", ""))


def test_six_aggregates_and_five_scenarios(tmp_path: Path) -> None:
    store, queries, _projects = _seed(tmp_path)
    unit_a = _org_id(queries, "测试采购单位甲")
    supplier_a = _org_id(queries, "甲供应商有限公司")
    supplier_b = _org_id(queries, "乙供应商有限公司")

    counts = store.counts()
    assert counts == {"projects": 3, "packages": 3, "organizations": 8, "bids": 8, "products": 1}

    winners = queries.unit_win_suppliers(unit_a)
    assert {value["supplier_name"]: value["win_count"] for value in winners} == {
        "甲 供应商有限公司": 1,
        "乙供应商有限公司": 1,
    }

    top = queries.unit_top_bidders(unit_a, 5)
    assert top[0]["bid_count"] == 2
    assert {top[0]["bidder_name"].replace(" ", ""), top[1]["bidder_name"].replace(" ", "")} == {
        "甲供应商有限公司", "乙供应商有限公司",
    }

    pairs = queries.unit_cobid_pairs(unit_a)
    pair_ab = next(value for value in pairs if {value["bidder_a"], value["bidder_b"]} == {supplier_a, supplier_b})
    assert pair_ab["project_count"] == 2

    cobidders = queries.supplier_cobidders(supplier_a, 5)
    supplier_b_row = next(value for value in cobidders if value["cobidder_id"] == supplier_b)
    assert supplier_b_row["project_count"] == 2

    common_units = queries.common_units([supplier_a, supplier_b])
    assert {value["unit_name"] for value in common_units} == {"测试采购单位甲", "测试采购单位乙"}
    joint_projects = queries.joint_projects([supplier_a, supplier_b])
    assert {value["notice_id"] for value in joint_projects} == {"SYN-001", "SYN-002", "SYN-003"}

    with store.connect() as connection:
        for table in (
            "unit_win_stats", "unit_bidder_stats", "unit_cobid_pairs",
            "supplier_cobid", "supplier_common_units", "supplier_joint_projects",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0


def test_ingest_is_idempotent_and_org_normalization_is_conservative(tmp_path: Path) -> None:
    store, queries, projects = _seed(tmp_path)
    before = store.counts()
    store.ingest(projects[0])
    assert store.counts() == before
    matches = [value for value in queries.organizations("甲供应商") if "供应商有限公司" in value["name"]]
    assert len(matches) == 1


def test_empty_database_and_candidate_extractor(tmp_path: Path) -> None:
    store = RelationStore(tmp_path / "empty.db")
    queries = RelationQueries(store)
    assert queries.organizations() == []
    assert queries.common_units(["a", "b"]) == []
    assert queries.project_subgraph("missing") == {"nodes": [], "edges": []}

    candidate = RelationCandidateExtractor().extract({
        "notice_id": "B-001",
        "title": "候选抽取测试",
        "blocks": [
            {"type": "paragraph", "text": "项目编号：T-01\n采购人名称：测试学校"},
            {
                "type": "table",
                "block_id": "B-001:blk_table",
                "source": {"file_name": "notice.html"},
                "rows": [
                    ["投标人名称", "投标报价", "排名", "评审结果"],
                    ["样例公司", "12万元", "1", "中标"],
                ],
            },
        ],
    })
    assert candidate.project_no == "T-01"
    assert candidate.procurement_unit and candidate.procurement_unit.name == "测试学校"
    assert candidate.packages[0].bidders[0].amount_yuan == 120000
    assert candidate.packages[0].bidders[0].evidence_block_row == 2


def test_candidate_extractor_rejects_procurement_templates_and_handles_negative_result() -> None:
    candidate = RelationCandidateExtractor().extract({
        "notice_id": "B-002",
        "title": "结果判定测试",
        "blocks": [
            {
                "type": "table", "block_id": "B-002:template",
                "source": {"file_name": "项目招标文件.docx"},
                "rows": [["供应商", "评分"], ["供应商应当提供符合要求的证明材料", "10分"]],
            },
            {
                "type": "table", "block_id": "B-002:result",
                "source": {"file_name": "notice.html"},
                "rows": [
                    ["投标人名称", "报价", "评审结果"],
                    ["甲测试有限公司", "100元", "未中标"],
                    ["现场考察", "0元", "中标"],
                ],
            },
        ],
    })
    assert len(candidate.packages) == 1
    assert len(candidate.packages[0].bidders) == 1
    assert candidate.packages[0].bidders[0].org.name == "甲测试有限公司"
    assert candidate.packages[0].bidders[0].result == "未中标"

    candidate_only = RelationCandidateExtractor().extract({
        "notice_id": "B-003", "title": "候选人不是中标人", "blocks": [{
            "type": "table", "block_id": "B-003:result", "source": {"file_name": "评审结果.xls"},
            "rows": [
                ["供应商名称", "报价", "评审结果"],
                ["重庆样例科技中心(个人独资)", "10万元", "第一中标候选人"],
            ],
        }],
    })
    assert candidate_only.packages[0].bidders[0].result == "候选"
