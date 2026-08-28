"""Rank parsed notices for manual gold annotation.

The ranker does not create labels. It only finds notices containing row-oriented
tables that cover many of the seven target fields and have reliable provenance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


HEADER_GROUPS = {
    "product_service_name": ("货物名称", "标的名称", "产品名称", "设备名称", "服务名称", "采购标的", "名称"),
    "category": ("品目", "品目名称", "品目分类"),
    "brand_supplier": ("品牌", "制造商", "生产厂家", "供应商"),
    "spec_model": ("规格型号", "规格", "型号", "配置"),
    "unit_price": ("单价", "单价(元)", "单价（元）"),
    "quantity": ("数量", "数量（单位）", "数量(单位)"),
    "total_price": ("总价", "合价", "金额", "报价"),
}

SOURCE_BONUS = {
    "报价": 15,
    "明细": 15,
    "成交": 8,
    "中标": 8,
    "结果": 8,
    "公示": 5,
}


def normalise(value: str) -> str:
    return "".join(value.lower().replace("\n", "").replace(" ", "").split())


def matched_groups(rows: list[list[str]]) -> list[str]:
    header = normalise("|".join(cell for row in rows[:3] for cell in row))
    return [
        field
        for field, aliases in HEADER_GROUPS.items()
        if any(normalise(alias) in header for alias in aliases)
    ]


def rank_notice(path: Path) -> dict[str, Any] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    useful_tables: list[dict[str, Any]] = []
    for block in payload.get("blocks", []):
        rows = block.get("rows")
        if block.get("type") != "table" or not rows or len(rows) < 2:
            continue
        fields = matched_groups(rows)
        if len(fields) < 3:
            continue
        source_path = block.get("source", {}).get("container_path", "")
        source_bonus = sum(points for token, points in SOURCE_BONUS.items() if token in source_path)
        data_rows = max(0, len(rows) - 1)
        score = len(fields) * 25 + min(data_rows, 80) + source_bonus
        useful_tables.append(
            {
                "block_id": block.get("block_id"),
                "source": block.get("source"),
                "fields": fields,
                "row_count": len(rows),
                "header": rows[0],
                "score": score,
            }
        )
    if not useful_tables:
        return None
    useful_tables.sort(key=lambda item: item["score"], reverse=True)
    status_counts = payload.get("stats", {}).get("document_status_counts", {})
    error_penalty = status_counts.get("error", 0) * 80 + status_counts.get("unsupported", 0) * 40
    score = useful_tables[0]["score"] + min(len(useful_tables), 5) * 8 - error_penalty
    return {
        "notice_id": payload.get("notice_id"),
        "title": payload.get("title"),
        "score": score,
        "status_counts": status_counts,
        "candidate_table_count": len(useful_tables),
        "tables": useful_tables[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank notices for gold annotation")
    parser.add_argument("--block-dir", type=Path, default=Path("dataset_build/blocks/notices"))
    parser.add_argument("--output", type=Path, default=Path("run/gold_candidate_ranking.json"))
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    candidates = [item for path in sorted(args.block_dir.glob("*.json")) if (item := rank_notice(path))]
    candidates.sort(key=lambda item: item["score"], reverse=True)
    result = {"candidate_count": len(candidates), "candidates": candidates[: args.top]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

