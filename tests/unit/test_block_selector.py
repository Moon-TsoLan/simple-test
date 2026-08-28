from __future__ import annotations

import json

from src.extraction.block_selector import SelectorConfig, match_header_fields, score_table, select_notice


def _source(document_id: str = "f1", **extra):
    return {
        "document_id": document_id,
        "file_name": "分项报价表.xlsx",
        "container_path": "附件.zip/分项报价表.xlsx",
        "file_type": "xlsx",
        **extra,
    }


def _notice(blocks):
    return {
        "notice_id": "N001",
        "title": "测试项目成交公告",
        "parser_version": "2.0.0",
        "parser_config_digest": "abc",
        "blocks": blocks,
    }


def test_header_mapping_does_not_treat_supplier_name_as_product():
    mapped = match_header_fields(["供应商名称", "地址", "中标金额"])
    assert "product_service_name" not in mapped
    assert "brand_supplier" not in mapped


def test_header_mapping_accepts_heji_as_total_price():
    mapped = match_header_fields(["序号", "产品名称", "数量及单位", "单价", "合计"])
    assert mapped["product_service_name"] == 1
    assert mapped["quantity"] == 2
    assert mapped["unit_price"] == 3
    assert mapped["total_price"] == 4


def test_table_is_split_and_api_payload_retains_exact_rows():
    block = {
        "block_id": "N001:blk_table",
        "type": "table",
        "source": _source(sheet="报价明细"),
        "rows": [
            ["货物名称", "品牌", "规格型号", "单价", "数量", "总价"],
            ["服务器", "浪潮", "NF5180M6", "35000元", "2台", "70000元"],
            ["交换机", "华为", "S5735", "5000元", "3台", "15000元"],
            ["合计", "", "", "", "", "85000元"],
        ],
        "text": "主要标的信息 分项报价",
    }
    result = select_notice(_notice([block]), SelectorConfig(max_table_rows_per_request=2))
    assert result["stats"]["selected_table_block_count"] == 1
    assert result["stats"]["request_count"] == 2
    first = result["requests"][0]
    assert first["api_payload"]["response_format"] == {"type": "json_object"}
    user = json.loads(first["api_payload"]["messages"][1]["content"])
    assert user["evidence"]["block_id"] == "N001:blk_table"
    assert [row["block_row"] for row in user["evidence"]["data_rows"]] == [2, 3]


def test_supplier_result_table_is_not_a_table_candidate():
    block = {
        "block_id": "N001:blk_supplier",
        "type": "table",
        "source": {
            "document_id": "f1",
            "file_name": "中标结果.html",
            "container_path": "中标结果.html",
            "file_type": "html",
        },
        "rows": [["供应商名称", "地址", "中标金额"], ["某某公司", "北京市", "100万元"]],
        "text": "供应商名称 地址 中标金额",
    }
    assert score_table(block) is None


def test_relevant_paragraph_expands_neighbor_context():
    blocks = [
        {
            "block_id": "N001:blk_1",
            "type": "heading",
            "source": _source("f2"),
            "text": "四、主要标的信息",
        },
        {
            "block_id": "N001:blk_2",
            "type": "paragraph",
            "source": _source("f2"),
            "text": "产品名称：台式计算机",
        },
        {
            "block_id": "N001:blk_3",
            "type": "paragraph",
            "source": _source("f2"),
            "text": "品牌：联想；规格型号：启天M450；单价：4980元；数量：120台",
        },
    ]
    result = select_notice(_notice(blocks), SelectorConfig(table_min_score=999, context_window=1))
    text_requests = [request for request in result["requests"] if request["content_kind"] == "text"]
    assert text_requests
    user = json.loads(text_requests[0]["api_payload"]["messages"][1]["content"])
    ids = [item["block_id"] for item in user["evidence"]["blocks"]]
    assert ids == ["N001:blk_1", "N001:blk_2", "N001:blk_3"]


def test_single_cell_html_table_is_treated_as_relevant_text():
    block = {
        "block_id": "N001:blk_flat_table",
        "type": "table",
        "source": {
            "document_id": "f1",
            "file_name": "结果公告.html",
            "container_path": "结果公告.html",
            "file_type": "html",
        },
        "rows": [["四、主要标的信息 名称：食材配送服务 服务时间：一年 成交金额：53万元"]],
        "text": "四、主要标的信息 名称：食材配送服务 服务时间：一年 成交金额：53万元",
    }
    result = select_notice(_notice([block]))
    assert result["stats"]["request_count"] == 1
    assert result["requests"][0]["content_kind"] == "text"


def test_blank_quotation_template_is_rejected():
    block = {
        "block_id": "N001:blk_blank",
        "type": "table",
        "source": {
            "document_id": "f1",
            "file_name": "采购文件.pdf",
            "container_path": "附件.zip/采购文件.pdf",
            "file_type": "pdf",
        },
        "rows": [
            ["名称", "品牌", "规格型号", "数量", "单价", "总价"],
            ["主机", "", "", "", "", ""],
            ["配套品", "", "", "", "", ""],
        ],
        "text": "报价表模板",
    }
    assert score_table(block) is None


def test_filled_looking_total_placeholder_template_is_not_selected():
    repeated = "总价：佰 拾 万 仟 佰 拾 元 角 分（大写） ￥（小写）"
    block = {
        "block_id": "N001:blk_total_template",
        "type": "table",
        "source": {
            "document_id": "f1",
            "file_name": "项目招标文件.docx",
            "container_path": "附件.zip/项目招标文件.docx",
            "file_type": "docx",
        },
        "rows": [
            ["序号", "产品名称", "品牌", "规格型号", "数量", "单位", "单价", "总价"],
            [repeated] * 8,
        ],
        "text": repeated,
    }
    result = select_notice(_notice([block]))
    assert result["stats"]["selected_table_block_count"] == 0
    assert result["stats"]["request_count"] == 0


def test_html_service_result_table_is_selected():
    block = {
        "block_id": "N001:blk_service",
        "type": "table",
        "source": {
            "document_id": "html1",
            "file_name": "结果公告.html",
            "container_path": "结果公告.html",
            "file_type": "html",
        },
        "rows": [
            ["序号", "供应商名称", "服务名称", "服务范围", "服务要求", "服务时间", "服务标准"],
            ["1", "某公司", "智慧消防服务", "项目现场", "符合磋商文件", "一年", "验收合格"],
        ],
        "text": "服务类主要标的信息",
    }
    result = select_notice(_notice([block]))
    table_requests = [request for request in result["requests"] if request["content_kind"] == "table"]
    assert len(table_requests) == 1
    user = json.loads(table_requests[0]["api_payload"]["messages"][1]["content"])
    assert user["evidence"]["field_columns"]["product_service_name"] == 2
    assert user["evidence"]["service_detail_columns"]["service_scope"] == 3
    assert "table:service_result_header" in table_requests[0]["selection_reasons"]


def test_html_construction_result_table_is_selected():
    block = {
        "block_id": "N001:blk_construction",
        "type": "table",
        "source": {
            "document_id": "html1",
            "file_name": "中选公告.html",
            "container_path": "中选公告.html",
            "file_type": "html",
        },
        "rows": [
            ["序号", "供应商名称", "工程名称", "施工范围", "施工工期", "项目经理", "执业证书"],
            ["1", "某建设公司", "卫生间改造工程", "按询比文件", "45日历天", "张三", "粤123"],
        ],
        "text": "工程类主要标的信息",
    }
    result = select_notice(_notice([block]))
    assert result["stats"]["selected_table_block_count"] == 1
    request = next(request for request in result["requests"] if request["content_kind"] == "table")
    assert request["relevance_score"] >= SelectorConfig.table_min_score


def test_procurement_file_service_template_is_not_selected_even_by_fallback():
    block = {
        "block_id": "N001:blk_service_template",
        "type": "table",
        "source": {
            "document_id": "pdf1",
            "file_name": "竞争性磋商文件.pdf",
            "container_path": "附件.zip/竞争性磋商文件.pdf",
            "file_type": "pdf",
        },
        "rows": [
            ["序号", "服务名称", "服务范围", "服务要求", "服务时间", "服务标准"],
            ["1", "由供应商填写", "由供应商填写", "响应采购要求", "合同期内", "验收合格"],
        ],
        "text": "服务报价响应表模板",
    }
    result = select_notice(_notice([block]))
    assert result["stats"]["selected_table_block_count"] == 0
    assert result["stats"]["request_count"] == 0
    assert result["stats"]["fallback_used"] is False


def test_pdf_continuation_inherits_header_and_keeps_first_data_row():
    header_block = {
        "block_id": "N001:blk_page1",
        "type": "table",
        "source": {
            "document_id": "pdf1",
            "file_name": "分项报价表.pdf",
            "container_path": "附件.zip/分项报价表.pdf",
            "file_type": "pdf",
            "page": 1,
            "table_index": 1,
        },
        "rows": [
            ["序号", "名称", "规格型号", "品牌", "数量", "单位", "单价", "合价"],
            ["1", "训练设施", "TZJ-01", "拓之迹", "1", "套", "1000", "1000"],
        ],
        "text": "分项报价表",
    }
    continuation = {
        "block_id": "N001:blk_page2",
        "type": "table",
        "source": {
            "document_id": "pdf1",
            "file_name": "分项报价表.pdf",
            "container_path": "附件.zip/分项报价表.pdf",
            "file_type": "pdf",
            "page": 2,
            "table_index": 1,
        },
        "rows": [
            ["2", "排风机", "型号：GXF-6#", "方青", "2", "套", "6200", "12400"],
            ["3", "配套设施", "TZJ-SX01", "拓之迹", "1", "项", "11900", "11900"],
        ],
        "text": "排风机 型号：GXF-6# 6200 12400",
    }
    result = select_notice(_notice([header_block, continuation]), SelectorConfig(max_table_sources_per_notice=1))
    request = next(
        request for request in result["requests"]
        if "N001:blk_page2" in request["source_block_ids"] and request["content_kind"] == "table"
    )
    user = json.loads(request["api_payload"]["messages"][1]["content"])
    evidence = user["evidence"]
    assert evidence["header_inherited"] is True
    assert evidence["header_source_block_id"] == "N001:blk_page1"
    assert evidence["header"][1] == "名称"
    assert [row["block_row"] for row in evidence["data_rows"]] == [1, 2]
    assert request["source_block_ids"] == ["N001:blk_page2", "N001:blk_page1"]
    assert "source:分项报价" in request["selection_reasons"]
    assert "source:报价" not in request["selection_reasons"]


def test_unstructured_key_value_table_can_be_sent_as_text():
    block = {
        "block_id": "N001:blk_kv",
        "type": "table",
        "source": {
            "document_id": "html1",
            "file_name": "中标公告.html",
            "container_path": "中标公告.html",
            "file_type": "html",
        },
        "rows": [
            ["主要标的信息", ""],
            ["服务名称", "食材配送服务"],
            ["成交金额", "53万元"],
        ],
        "text": "主要标的信息 服务名称 食材配送服务 成交金额 53万元",
    }
    result = select_notice(_notice([block]))
    assert any(request["content_kind"] == "text" for request in result["requests"])
