"""Build the second, fixed-seed batch of manually curated gold notices.

This is not an automatic labeler.  The sampled notices, accepted result
tables, row splits, field values, and null decisions were reviewed manually.
The script only copies source metadata and the exact evidence row from the
current Block files so that labels cannot silently drift away from evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build_gold_seed import entity_text, number, source_location
from rebuild_gold_index import rebuild_indexes


ROOT = Path(__file__).resolve().parents[1]
BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
CRAWL_HTML_DIR = ROOT / "dataset_build" / "crawl" / "html"
GOLD_DIR = ROOT / "dataset_build" / "gold"
NOTICE_DIR = GOLD_DIR / "notices"
EXPANSION_DIR = GOLD_DIR / "expansion_20260826"
ANNOTATION_VERSION = "1.1.0"
RANDOM_SEED = 20260826


SAMPLE_IDS = [
    "20260815_27141638",
    "20260815_27141779",
    "20260814_27137208",
    "20260814_27138005",
    "20260815_27141343",
    "20260814_27139568",
    "20260815_27141727",
    "20260815_27140892",
    "20260814_27139211",
    "20260814_27138985",
]

EXCLUDED_EXISTING_GOLD_IDS = [
    "20260629_26835308",
    "20260813_27128600",
    "20260814_27137567",
    "20260814_27138043",
    "20260814_27139636",
    "20260814_27139691",
    "20260815_27140933",
    "20260815_27141366",
    "20260815_27141623",
    "20260815_27141793",
]


def item(
    block_id: str,
    block_row: int,
    product_service_name: str,
    *,
    category_name: str | None = None,
    category_code: str | None = None,
    brand_supplier: str | None = None,
    spec_model: str | None = None,
    unit_price: int | float | None = None,
    quantity: int | float | None = None,
    quantity_unit: str | None = None,
    total_price: int | float | None = None,
) -> dict[str, Any]:
    """Declare one reviewed label before attaching source metadata."""
    return {
        "source_block_id": block_id,
        "source_block_row": block_row,
        "product_service_name": product_service_name,
        "category_name": category_name,
        "category_code": category_code,
        "brand_supplier": brand_supplier,
        "spec_model": spec_model,
        "unit_price": unit_price,
        "quantity": quantity,
        "quantity_unit": quantity_unit,
        "total_price": total_price,
    }


SPECS: dict[str, dict[str, Any]] = {
    "20260815_27141638": {
        "reason": "随机样本中的工程类实际成交结果表；仅标工程名称，不把施工范围或项目经理误填到实体字段。",
        "items": [
            item("20260815_27141638:blk_d535abeef2ac310792a86d97", 2,
                 "塔城边境管理支队2026年基层单位零星维修项目（三次）（额敏片区）"),
        ],
    },
    "20260815_27141779": {
        "reason": "随机样本中的完整货物结果表；逐行标注品牌、原始规格、数量和单价，原表无总价则保留 null。",
        "items": [
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 2, "化学杀虫剂",
                 brand_supplier="陕西先农生物科技有限公司", spec_model="型号:200g/瓶规格:200g/瓶",
                 unit_price=140, quantity=2000, quantity_unit="kg"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 3, "植物生长调节剂",
                 brand_supplier="山东润扬化学有限公司", spec_model="型号:100ml/瓶规格:100ml/瓶",
                 unit_price=34, quantity=2000, quantity_unit="L"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 4, "有机水溶肥料（含植物免疫蛋白）",
                 brand_supplier="康尔特生物科技(云南)有限公司", spec_model="型号1kg*12瓶 规格:1kg/瓶",
                 unit_price=40, quantity=15000, quantity_unit="kg"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 5, "生物杀虫剂",
                 brand_supplier="邦农达(潍坊)作物科学有限公司", spec_model="型号:500g/瓶规格:500g/瓶",
                 unit_price=260, quantity=150, quantity_unit="kg"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 6, "液体微生物菌剂",
                 brand_supplier="新疆天物生态环保股份有限公司", spec_model="型号:20Kg/桶规格:20Kg/桶",
                 unit_price=5.37, quantity=140300, quantity_unit="kg"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 7, "杀虫真菌等微生物菌剂",
                 brand_supplier="重庆聚立信生物工程有限公司", spec_model="型号:200g*20瓶规格:200g/瓶",
                 unit_price=148, quantity=200, quantity_unit="kg"),
            item("20260815_27141779:blk_e0a72fbff540db23d727c0ec", 8, "农用助剂",
                 brand_supplier="成都绿金生物科技有限责任公司", spec_model="型号:1000g/瓶规格:1000g/瓶",
                 unit_price=90, quantity=2000, quantity_unit="kg"),
        ],
    },
    "20260814_27137208": {
        "reason": "随机样本中的服务类实际成交结果表；中标供应商不是产品品牌，其余无同一行证据字段均标 null。",
        "items": [
            item("20260814_27137208:blk_9e027a3d82787f2397ef604b", 2,
                 "乌海市海南区消防救援大队2026年乌海市海南区“智慧消防”项目"),
        ],
    },
    "20260814_27138005": {
        "reason": "随机样本中的货物主要标的信息表；品牌、型号、数量和单价均可从同一结果行直接回指。",
        "items": [
            item("20260814_27138005:blk_75521381663504492b42e7c4", 2, "液相氧电极",
                 brand_supplier="Hansatech Instruments Ltd", spec_model="Oxytherm+",
                 unit_price=324900, quantity=1, quantity_unit="台"),
        ],
    },
    "20260815_27141343": {
        "reason": "随机样本中的服务类主要标的信息表；仅保留实际成交服务名称，不把服务范围、期限或供应商迁入其他实体字段。",
        "items": [
            item("20260815_27141343:blk_5794da251ca090694221469d", 2,
                 "新疆哈纳斯国家级自然保护区2026年第二批中央财政林业草原生态保护恢复资金（国家级自然保护区能力提升）项目-生物多样性保护"),
        ],
    },
    "20260814_27139568": {
        "reason": "随机样本中的工程类实际中选结果表；不把成交供应商、施工范围、工期或项目经理当成目标实体。",
        "items": [
            item("20260814_27139568:blk_904c47d5b7a9a73a0d2e29e5", 2,
                 "暨南大学石牌校区2026年卫生间改造工程"),
        ],
    },
    "20260815_27141727": {
        "reason": "随机样本中的已填写中标报价响应 PDF；22项合计3180000元，与公告中标总价一致，斜杠占位规范化为 null。",
        "items": [
            item("20260815_27141727:blk_f9dbb71ef36e573ceeaab968", 2, "洁净室系统集成工程（工程部分）",
                 unit_price=450000, quantity=1, quantity_unit="项", total_price=450000),
            item("20260815_27141727:blk_f9dbb71ef36e573ceeaab968", 3, "数模混合ATE测试机（核心产品）",
                 brand_supplier="HYC", spec_model="T60", unit_price=358000, quantity=2,
                 quantity_unit="套", total_price=716000),
            item("20260815_27141727:blk_f9dbb71ef36e573ceeaab968", 4, "成品芯片测试智能转塔式分选一体机",
                 brand_supplier="杰锐思", spec_model="TS2020", unit_price=320000, quantity=1,
                 quantity_unit="套", total_price=320000),
            item("20260815_27141727:blk_f9dbb71ef36e573ceeaab968", 5, "成品芯片测试重力式自动分选机",
                 brand_supplier="派利德", spec_model="PH-212P", unit_price=150000, quantity=1,
                 quantity_unit="套", total_price=150000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 1, "车规级大芯片平移分选机",
                 brand_supplier="艾方芯动自动化", spec_model="CRH8508", unit_price=820000, quantity=1,
                 quantity_unit="套", total_price=820000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 2, "自动智能编带机",
                 brand_supplier="纳斯丹", spec_model="ZZSRXBDJ01", unit_price=72000, quantity=1,
                 quantity_unit="套", total_price=72000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 3, "风冷模块主机空气净化机组",
                 brand_supplier="欧博",
                 spec_model="风冷热泵模块1号机组：欧博 FLM-WX-65H 风冷热泵模块2号机组：欧博 FLM-WX-130H 双层保温不锈钢水箱：2T不锈钢定制 水泵：2T125KQL100-32-15/4 AHU空调机组：欧博-40000CMH定制 其他配套材料：定制",
                 unit_price=460000, quantity=1, quantity_unit="套", total_price=460000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 4, "风淋净化机组",
                 brand_supplier="柏本", spec_model="定制：W1300*D1500*H2150(mm)", unit_price=18000,
                 quantity=1, quantity_unit="套", total_price=18000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 5, "自动烘干洗手机",
                 brand_supplier="柏本", spec_model="定制", unit_price=6000, quantity=1,
                 quantity_unit="套", total_price=6000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 6, "货淋净化机组",
                 brand_supplier="柏本", spec_model="定制：W1300*D1500*H2150(mm)", unit_price=17200,
                 quantity=1, quantity_unit="套", total_price=17200),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 7, "无油螺杆空压机",
                 brand_supplier="艾美丹", spec_model="定制", unit_price=30000, quantity=1,
                 quantity_unit="套", total_price=30000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 8, "储气罐",
                 brand_supplier="艾美丹", spec_model="定制", unit_price=2000, quantity=1,
                 quantity_unit="套", total_price=2000),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 9, "干燥机",
                 brand_supplier="艾美丹", spec_model="定制", unit_price=7800, quantity=1,
                 quantity_unit="套", total_price=7800),
            item("20260815_27141727:blk_53bec99546ce32cd45dba6ce", 10, "无油活塞真空泵",
                 brand_supplier="藤原", spec_model="V1500", unit_price=6000, quantity=1,
                 quantity_unit="套", total_price=6000),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 1, "动力电源配电电柜",
                 brand_supplier="国标", spec_model="定制", unit_price=16000, quantity=1,
                 quantity_unit="套", total_price=16000),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 2, "空调系统配电柜",
                 brand_supplier="速电自动化", spec_model="定制", unit_price=30000, quantity=1,
                 quantity_unit="套", total_price=30000),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 3, "高清枪型摄像机",
                 brand_supplier="海康", spec_model="海康-DS-2CD2245SW-YQ", unit_price=400,
                 quantity=10, quantity_unit="套", total_price=4000),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 4, "交换机",
                 brand_supplier="锐捷", spec_model="锐捷-RG-NBS5100-24GT4SFP", unit_price=1500,
                 quantity=1, quantity_unit="套", total_price=1500),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 5, "存储设备",
                 brand_supplier="海康", spec_model="海康-DS-7916N-R4(C)", unit_price=2200,
                 quantity=1, quantity_unit="套", total_price=2200),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 6, "机柜",
                 brand_supplier="韩电", spec_model="韩电-KEG.G265-12H", unit_price=1500,
                 quantity=1, quantity_unit="套", total_price=1500),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 7, "显示屏",
                 brand_supplier="希沃", spec_model="希沃-FH86EC", unit_price=10000,
                 quantity=2, quantity_unit="块", total_price=20000),
            item("20260815_27141727:blk_67ba37c98ea1788696d5f098", 8, "信息化生产软件",
                 brand_supplier="积元", spec_model="积元-定制", unit_price=29800,
                 quantity=1, quantity_unit="套", total_price=29800),
        ],
    },
    "20260815_27140892": {
        "reason": "随机样本中的工程类成交结果表；品目名称和项目金额有同一行证据，施工范围不作为规格型号。",
        "items": [
            item("20260815_27140892:blk_cac068041a5acb3734a97e57", 2, "东院区血液透析室改扩建",
                 category_name="医疗卫生用房施工", total_price=1006000),
        ],
    },
    "20260814_27139211": {
        "reason": "随机样本的一行多产品结果表；按原文分号对齐关系人工拆为两条，二者共同引用同一来源行。",
        "items": [
            item("20260814_27139211:blk_cb004de290bd5f4c8f6567dc", 2, "生物型无标记拉曼成像仪",
                 brand_supplier="堀场仪器", spec_model="LabRAM Odyssey", unit_price=4799000, quantity=1),
            item("20260814_27139211:blk_cb004de290bd5f4c8f6567dc", 2, "正置荧光显微镜",
                 brand_supplier="蔡司", spec_model="AxioImagerM2", unit_price=1299000, quantity=1),
        ],
    },
    "20260814_27138985": {
        "reason": "随机样本中的服务类实际成交结果表；供应商仅表示中标主体，不作为品牌字段。",
        "items": [
            item("20260814_27138985:blk_a9f274105c3c3274cbbf4327", 2,
                 "广东省江门市台山市消防救援大队2026年食品配送采购项目"),
        ],
    },
}


def crawl_title(notice_id: str) -> str:
    path = CRAWL_HTML_DIR / notice_id.split("_", 1)[0] / f"{notice_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    title = entity_text(payload.get("title"))
    if not title:
        raise ValueError(f"Missing source title for {notice_id}: {path}")
    return title


def build_notice(notice_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads((BLOCK_DIR / f"{notice_id}.json").read_text(encoding="utf-8"))
    blocks = {block.get("block_id"): block for block in payload.get("blocks") or []}
    output_items: list[dict[str, Any]] = []
    for item_no, declared in enumerate(spec["items"], start=1):
        block = blocks.get(declared["source_block_id"])
        if not block or block.get("type") != "table":
            raise ValueError(f"Missing table Block for {notice_id} item {item_no}")
        row_number = declared["source_block_row"]
        rows = block.get("rows") or []
        if not 1 <= row_number <= len(rows):
            raise ValueError(f"Invalid row {row_number} for {block['block_id']}")
        source = block.get("source") or {}
        reviewed = {
            "item_no": item_no,
            "product_service_name": entity_text(declared["product_service_name"]),
            "category_name": entity_text(declared["category_name"]),
            "category_code": entity_text(declared["category_code"]),
            "brand_supplier": entity_text(declared["brand_supplier"]),
            "spec_model": entity_text(declared["spec_model"]),
            "unit_price": number(declared["unit_price"]),
            "quantity": number(declared["quantity"]),
            "quantity_unit": entity_text(declared["quantity_unit"]),
            "total_price": number(declared["total_price"]),
            "source_block_id": block["block_id"],
            "source_block_row": row_number,
            "source_document_id": source.get("document_id"),
            "source_file": source.get("file_name"),
            "source_container_path": source.get("container_path"),
            "source_location": source_location(source, row_number),
            "evidence_text": json.dumps(rows[row_number - 1], ensure_ascii=False, separators=(",", ":")),
        }
        output_items.append(reviewed)
    return {
        "notice_id": notice_id,
        "title": crawl_title(notice_id),
        "source_parser_version": payload.get("parser_version", "legacy-unversioned"),
        "source_parser_config_digest": payload.get("parser_config_digest"),
        "annotation_version": ANNOTATION_VERSION,
        "annotation_method": "manual_curated_from_verified_blocks",
        "review_status": "single_annotator_gold_seed",
        "selection_reason": spec["reason"],
        "items": output_items,
    }


def main() -> int:
    if set(SAMPLE_IDS) != set(SPECS) or len(SAMPLE_IDS) != len(set(SAMPLE_IDS)):
        raise ValueError("Sample manifest and annotation specs differ or contain duplicates")
    NOTICE_DIR.mkdir(parents=True, exist_ok=True)
    EXPANSION_DIR.mkdir(parents=True, exist_ok=True)
    notices = [build_notice(notice_id, SPECS[notice_id]) for notice_id in SAMPLE_IDS]
    for notice in notices:
        (NOTICE_DIR / f"{notice['notice_id']}.json").write_text(
            json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    sample_manifest = {
        "batch_id": "gold_expansion_20260826",
        "sampling_method": "simple_random_without_replacement_after_excluding_existing_gold_notices",
        "sampling_runtime": "Python random.Random(20260826).sample(sorted(population_notice_ids), 10)",
        "population_order": "notice_id_lexicographic_ascending",
        "random_seed": RANDOM_SEED,
        "source_notice_count": 291,
        "excluded_existing_gold_notice_count": len(EXCLUDED_EXISTING_GOLD_IDS),
        "excluded_existing_gold_notice_ids": EXCLUDED_EXISTING_GOLD_IDS,
        "sampling_population_count": 281,
        "sample_count": len(SAMPLE_IDS),
        "sample_notice_ids": SAMPLE_IDS,
        "annotation_date": "2026-08-26",
        "annotation_version": ANNOTATION_VERSION,
        "annotation_method": "manual_curated_from_verified_blocks",
        "review_status": "single_annotator_gold_seed",
        "item_count": sum(len(notice["items"]) for notice in notices),
        "quality_controls": [
            "only actual winning/transaction-result evidence is labelled",
            "missing fields remain null",
            "winning supplier is not automatically treated as product brand",
            "each item cites an exact Block and table row",
            "evidence_text is copied byte-for-text from the cited Block row",
        ],
    }
    (EXPANSION_DIR / "random_sample_manifest.json").write_text(
        json.dumps(sample_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = rebuild_indexes(GOLD_DIR)
    print(json.dumps({
        "built_notice_count": len(notices),
        "built_item_count": sample_manifest["item_count"],
        "total_gold_notice_count": manifest["notice_count"],
        "total_gold_item_count": manifest["item_count"],
        "sample_manifest": str(EXPANSION_DIR / "random_sample_manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
