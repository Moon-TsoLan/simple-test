from __future__ import annotations

from src.agents.backends import BackendResponse, FakeBackend
from src.agents.verification import ReplaySearchProvider, TemporalEntityVerificationAgent, VerificationConfig


def test_langgraph_tool_call_searches_and_validates_returned_url() -> None:
    query = "华三 2014 公司 品牌 历史"
    url = "https://example.gov.cn/h3c-history"
    backend = FakeBackend([
        BackendResponse(
            output="",
            tool_calls=[{
                "name": "web_search",
                "args": {"query": query},
                "id": "call_1",
                "type": "tool_call",
            }],
            usage={"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
        ),
        {
            "candidate": "华三",
            "candidate_type": "brand",
            "as_of_date": "2014-06-20",
            "canonical_name": "华三",
            "verification_status": "verified_brand_at_date",
            "valid_at_date": True,
            "relations": [],
            "evidence_urls": [url],
            "reasoning_summary": "权威历史材料支持该日期存在。",
            "warnings": [],
        },
    ])
    search = ReplaySearchProvider({query: [{
        "title": "品牌历史",
        "url": url,
        "snippet": "历史材料",
    }]})
    result = TemporalEntityVerificationAgent(
        backend, search, VerificationConfig(max_search_rounds=1)
    ).verify(
        "华三", as_of_date="2014-06-20", request_id="n1:verify:1", candidate_type="brand"
    )

    assert result["status"] == "success"
    assert result["search_queries"] == [query]
    assert result["decision"]["evidence"][0]["url"] == url
    assert result["decision"]["evidence_quality"] == "high"
    assert result["usage"]["calls"] == 2
    assert "web_search_tool" in result["workflow_trace"]
    assert "auto_force_final_after_tools" in result["workflow_trace"]


def test_verifier_rejects_url_not_returned_by_search_tool() -> None:
    query = "测试公司 2020 历史"
    backend = FakeBackend([
        BackendResponse(output="", tool_calls=[{
            "name": "web_search", "args": {"query": query}, "id": "call_1", "type": "tool_call",
        }]),
        {
            "candidate": "测试公司",
            "candidate_type": "company",
            "as_of_date": "2020-01-01",
            "canonical_name": "测试公司",
            "verification_status": "verified_exact_at_date",
            "valid_at_date": True,
            "relations": [],
            "evidence_urls": ["https://invented.example/evidence"],
            "reasoning_summary": "测试",
            "warnings": [],
        },
        {
            "candidate": "测试公司",
            "candidate_type": "company",
            "as_of_date": "2020-01-01",
            "canonical_name": None,
            "verification_status": "insufficient_evidence",
            "valid_at_date": None,
            "relations": [],
            "evidence_urls": [],
            "reasoning_summary": "没有可回指证据。",
            "warnings": ["需人工复核"],
        },
    ])
    search = ReplaySearchProvider({query: []})
    result = TemporalEntityVerificationAgent(backend, search).verify(
        "测试公司", as_of_date="2020-01-01", request_id="n1:verify:2", candidate_type="company"
    )

    assert result["status"] == "success"
    assert result["decision"]["verification_status"] == "insufficient_evidence"
    assert result["decision"]["review_required"] is True
    assert "request_verification_repair" in result["workflow_trace"]


def test_deterministic_tool_mode_supports_model_without_tool_calls() -> None:
    query = '"新华三" 2024 公司 品牌 历史 更名 收购'
    url = "https://example.gov.cn/company"
    backend = FakeBackend([{
        "candidate": "新华三",
        "candidate_type": "company",
        "as_of_date": "2024-01-01",
        "canonical_name": "新华三集团",
        "verification_status": "verified_exact_at_date",
        "valid_at_date": True,
        "relations": [],
        "evidence_urls": [url],
        "reasoning_summary": "控制器搜索后由模型总结。",
        "warnings": [],
    }])
    search = ReplaySearchProvider({query: [{
        "title": "企业信息", "url": url, "snippet": "登记信息",
    }]})
    verifier = TemporalEntityVerificationAgent(
        backend,
        search,
        VerificationConfig(tool_mode="deterministic"),
    )

    result = verifier.verify(
        "新华三", as_of_date="2024-01-01", request_id="n1:verify:3"
    )

    assert result["status"] == "success"
    assert result["usage"]["calls"] == 1
    assert result["search_queries"] == [query]
    assert "deterministic_search_plan" in result["workflow_trace"]
