"""Build the first ten manually curated gold notices from verified Block rows.

This is intentionally not a generic auto-labeler.  The notice/block choices,
column mappings, row filters, and duplicate handling below are human-reviewed
annotation decisions.  Reading values back from Blocks avoids transcription
errors while keeping every label tied to an exact source row.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
GOLD_DIR = ROOT / "dataset_build" / "gold"
NOTICE_DIR = GOLD_DIR / "notices"
VERSION = "1.0.0"


SELECTIONS: dict[str, dict[str, Any]] = {
    "20260814_27137567": {
        "source": {"container_path": "20260814_27137567.zip/成交公示.docx", "table_index": 1},
        "mapper": "docx_instruments",
        "reason": "成交公示 DOCX 的完整设备明细，含品目、品牌、型号、数量、单价和总价。",
    },
    "20260629_26835308": {
        "source": {"container_path": "20260629_26835308.zip/附件-主要标的信息.xlsx", "sheet": "分部分项工程项目清单计价表", "row_start": 1, "row_end": 45},
        "mapper": "xlsx_network",
        "reason": "中标结果附件 XLSX 的主要标的信息；人工剔除重复表头、重复第1项和重复第38项。",
    },
    "20260815_27141793": {
        "source": {"container_path": "20260815_27141793.html", "table_index": 3},
        "mapper": "html_full_category",
        "reason": "结果公告 HTML 的完整货物表，七字段齐全并带官方品目编码。",
    },
    "20260813_27128600": {
        "source": {"container_path": "20260813_27128600.html", "table_index": 3},
        "mapper": "html_category_name",
        "reason": "成交结果 HTML 的单项完整货物表，品目只提供名称、不臆造编码。",
    },
    "20260815_27141366": {
        "source": {"container_path": "20260815_27141366.zip/分项报价表.pdf", "page": 1, "table_index": 1},
        "mapper": "pdf_yak",
        "reason": "成交报价 PDF 的完整分项报价行，数量、单价和合价可相互校验。",
    },
    "20260815_27140933": {
        "source": {"container_path": "20260815_27140933.html", "table_index": 3},
        "mapper": "html_category_no_total",
        "reason": "结果公告 HTML 的十项防汛物资，保留官方品目编码；原表无总价则标 null。",
    },
    "20260815_27141623": {
        "source": {"container_path": "20260815_27141623.html", "table_index": 4},
        "mapper": "html_plain_no_total",
        "reason": "结果公告 HTML 的六项实验设备；原表未给数量单位和总价，均不推断。",
    },
    "20260814_27139636": {
        "source": {"container_path": "20260814_27139636.html", "table_index": 2},
        "mapper": "html_ccgp_no_total",
        "reason": "中标公告 HTML 的主要货物信息，避免采用招标文件中的空白报价模板。",
    },
    "20260814_27138043": {
        "source": {"container_path": "20260814_27138043.html", "table_index": 2},
        "mapper": "html_ccgp_no_total",
        "reason": "中标公告 HTML 的实际中标货物行，避开附件中的空白分项报价模板。",
    },
    "20260814_27139691": {
        "source": {"container_path": "20260814_27139691.html", "table_index": 2},
        "mapper": "html_ccgp_no_total",
        "reason": "中标公告 HTML 的超高速相机主要标的信息。",
    },
}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", "").replace("\n", "")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text or None


def entity_text(value: Any) -> str | None:
    text = clean(value)
    return None if text in {None, "/", "-", "—", "无", "不涉及"} else text


def number(value: Any) -> int | float | None:
    text = clean(value)
    if text is None or text in {"/", "-", "—"}:
        return None
    text = text.replace(",", "").replace("元", "").strip()
    parsed = Decimal(text)
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def quantity(value: Any, explicit_unit: Any = None) -> tuple[int | float | None, str | None]:
    text = clean(value)
    if text is None:
        return None, clean(explicit_unit)
    match = re.fullmatch(r"([\d,.]+)\s*(?:\(([^)]+)\)|([^\d\s.]+))?", text)
    if not match:
        raise ValueError(f"Unrecognised quantity: {value!r}")
    unit = clean(explicit_unit) or clean(match.group(2)) or clean(match.group(3))
    return number(match.group(1)), unit


def split_category(value: Any) -> tuple[str | None, str | None]:
    text = clean(value)
    if text is None:
        return None, None
    match = re.fullmatch(r"([A-Z]\d{8})\s+(.+)", text)
    if match:
        return match.group(2).strip(), match.group(1)
    return text, None


def base_item(
    row: list[str],
    block_row: int,
    *,
    product: Any,
    category_name: Any = None,
    category_code: Any = None,
    brand: Any = None,
    model: Any = None,
    unit_price: Any = None,
    quantity_value: Any = None,
    quantity_unit: Any = None,
    total_price: Any = None,
) -> dict[str, Any]:
    return {
        "product_service_name": entity_text(product),
        "category_name": entity_text(category_name),
        "category_code": entity_text(category_code),
        "brand_supplier": entity_text(brand),
        "spec_model": entity_text(model),
        "unit_price": number(unit_price),
        "quantity": number(quantity_value),
        "quantity_unit": entity_text(quantity_unit),
        "total_price": number(total_price),
        "source_block_row": block_row,
        "evidence_text": json.dumps(row, ensure_ascii=False, separators=(",", ":")),
    }


def map_docx_instruments(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        qty, unit = quantity(row[6])
        result.append(base_item(row, block_row, product=row[3], category_name=row[1], brand=row[4],
                                model=row[5], unit_price=row[7], quantity_value=qty,
                                quantity_unit=unit, total_price=row[8]))
    return result


def map_xlsx_network(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    seen_item_numbers: set[int] = set()
    for block_row, row in enumerate(rows, start=1):
        if not row or not re.fullmatch(r"\d+", clean(row[0]) or ""):
            continue
        source_no = int(clean(row[0]) or "0")
        if source_no in seen_item_numbers:
            continue
        seen_item_numbers.add(source_no)
        qty, unit = quantity(row[3], row[2])
        result.append(base_item(row, block_row, product=row[1], brand=row[4], model=row[5],
                                unit_price=row[6], quantity_value=qty, quantity_unit=unit,
                                total_price=row[8]))
    if seen_item_numbers != set(range(1, 40)):
        raise ValueError(f"Unexpected XLSX item numbers: {sorted(seen_item_numbers)}")
    return result


def map_html_full_category(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        category_name, category_code = split_category(row[1])
        qty, unit = quantity(row[5])
        result.append(base_item(row, block_row, product=row[2], category_name=category_name,
                                category_code=category_code, brand=row[3], model=row[4],
                                unit_price=row[6], quantity_value=qty, quantity_unit=unit,
                                total_price=row[7]))
    return result


def map_html_category_name(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        qty, unit = quantity(row[5])
        result.append(base_item(row, block_row, product=row[2], category_name=row[1], brand=row[3],
                                model=row[4], unit_price=row[6], quantity_value=qty,
                                quantity_unit=unit, total_price=row[7]))
    return result


def map_pdf_yak(rows: list[list[str]]) -> list[dict[str, Any]]:
    row = rows[1]
    qty, unit = quantity(row[5])
    # PDF line wrapping split numeric bounds from their labels.  This is a
    # hand-normalised transcription of the same cell, with no facts added.
    model = ("1、年龄4-5岁；2、体高（cm）：106-114；3、体斜长（cm）：118-128；"
             "4、胸围（cm）：152-159；5、管围（cm）：13.5-15；6、体重（kg）：193-232")
    return [base_item(row, 2, product=row[1], brand=row[2], model=model, unit_price=row[6],
                      quantity_value=qty, quantity_unit=unit, total_price=row[7])]


def map_html_category_no_total(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        category_name, category_code = split_category(row[1])
        qty, unit = quantity(row[5])
        result.append(base_item(row, block_row, product=row[2], category_name=category_name,
                                category_code=category_code, brand=row[3], model=row[4],
                                unit_price=row[6], quantity_value=qty, quantity_unit=unit))
    return result


def map_html_plain_no_total(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        qty, unit = quantity(row[5])
        result.append(base_item(row, block_row, product=row[2], brand=row[3], model=row[4],
                                unit_price=row[6], quantity_value=qty, quantity_unit=unit))
    return result


def map_html_ccgp_no_total(rows: list[list[str]]) -> list[dict[str, Any]]:
    result = []
    for block_row, row in enumerate(rows[1:], start=2):
        qty, unit = quantity(row[5])
        result.append(base_item(row, block_row, product=row[2], brand=row[3], model=row[4],
                                unit_price=row[6], quantity_value=qty, quantity_unit=unit))
    return result


MAPPERS: dict[str, Callable[[list[list[str]]], list[dict[str, Any]]]] = {
    "docx_instruments": map_docx_instruments,
    "xlsx_network": map_xlsx_network,
    "html_full_category": map_html_full_category,
    "html_category_name": map_html_category_name,
    "pdf_yak": map_pdf_yak,
    "html_category_no_total": map_html_category_no_total,
    "html_plain_no_total": map_html_plain_no_total,
    "html_ccgp_no_total": map_html_ccgp_no_total,
}


def source_location(source: dict[str, Any], block_row: int) -> str:
    parts = [source.get("file_type", "file").upper()]
    for key in ("page", "sheet", "table_index", "row_start", "row_end"):
        if source.get(key) is not None:
            parts.append(f"{key}={source[key]}")
    parts.append(f"block_row={block_row}")
    return ", ".join(parts)


def build_notice(notice_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads((BLOCK_DIR / f"{notice_id}.json").read_text(encoding="utf-8"))
    matches = [
        block
        for block in payload["blocks"]
        if block.get("type") == "table"
        and all(block.get("source", {}).get(key) == value for key, value in spec["source"].items())
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one gold source table for {notice_id}, found {len(matches)}: {spec['source']}")
    block = matches[0]
    if block.get("type") != "table" or not block.get("rows"):
        raise ValueError(f"Gold source is not a non-empty table: {block.get('block_id')}")
    title = clean(payload["blocks"][0].get("text")) or clean(payload.get("title"))
    items = MAPPERS[spec["mapper"]](block["rows"])
    source = block["source"]
    for item_no, item in enumerate(items, start=1):
        item["item_no"] = item_no
        item["source_block_id"] = block["block_id"]
        item["source_document_id"] = source.get("document_id")
        item["source_file"] = source.get("file_name")
        item["source_container_path"] = source.get("container_path")
        item["source_location"] = source_location(source, item["source_block_row"])
    return {
        "notice_id": notice_id,
        "title": title,
        "source_parser_version": payload.get("parser_version", "legacy-unversioned"),
        "source_parser_config_digest": payload.get("parser_config_digest"),
        "annotation_version": VERSION,
        "annotation_method": "manual_curated_from_verified_blocks",
        "review_status": "single_annotator_gold_seed",
        "selection_reason": spec["reason"],
        "items": items,
    }


def main() -> int:
    NOTICE_DIR.mkdir(parents=True, exist_ok=True)
    notices = [build_notice(notice_id, spec) for notice_id, spec in SELECTIONS.items()]
    for notice in notices:
        path = NOTICE_DIR / f"{notice['notice_id']}.json"
        path.write_text(json.dumps(notice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "annotation_version": VERSION,
        "notice_count": len(notices),
        "item_count": sum(len(notice["items"]) for notice in notices),
        "notices": [
            {
                "notice_id": notice["notice_id"],
                "title": notice["title"],
                "item_count": len(notice["items"]),
                "source_parser_version": notice["source_parser_version"],
                "source_parser_config_digest": notice["source_parser_config_digest"],
                "source_types": sorted({item["source_location"].split(",", 1)[0].lower()
                                        for item in notice["items"]}),
                "file": f"notices/{notice['notice_id']}.json",
            }
            for notice in notices
        ],
    }
    (GOLD_DIR / "gold_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (GOLD_DIR / "gold_items.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for notice in notices:
            for item in notice["items"]:
                handle.write(json.dumps({"notice_id": notice["notice_id"], "title": notice["title"], **item},
                                        ensure_ascii=False, separators=(",", ":")) + "\n")
    # Preserve independently curated extensions when the original seed is
    # rebuilt; the directory contents, not this first-batch list, are the
    # authoritative index input.
    from rebuild_gold_index import rebuild_indexes

    manifest = rebuild_indexes(GOLD_DIR)
    print(f"Built/reindexed {manifest['notice_count']} notices and {manifest['item_count']} gold items in {GOLD_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
