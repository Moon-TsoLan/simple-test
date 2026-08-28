# -*- coding: utf-8 -*-
"""Compare archived rule silver with DeepSeek API silver for the same notices."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "dataset_build" / "silver_rules_v1" / "notices"
API_DIR = ROOT / "dataset_build" / "silver" / "notices"

FIELDS = [
    "product_service_name", "category_name", "category_code", "brand_supplier",
    "spec_model", "unit_price", "quantity", "quantity_unit", "total_price",
]


def norm(value):
    if value is None:
        return None
    return str(value).strip()


def main() -> int:
    rules_files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in RULES_DIR.glob("*.json")}
    api_files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in API_DIR.glob("*.json")}
    common = sorted(set(rules_files) & set(api_files))

    per_field = {f: {"agree": 0, "total": 0, "rules_only": 0, "api_only": 0} for f in FIELDS}
    item_pairs = 0
    api_extra = 0
    rules_only = 0
    notice_rows = []
    for nid in common:
        rule_items = {i["source_block_row"]: i for i in rules_files[nid]["items"]}
        api_items = {i["source_block_row"]: i for i in api_files[nid]["items"]}
        rows = sorted(set(rule_items) | set(api_items))
        matched_rows = len(set(rule_items) & set(api_items))
        item_pairs += matched_rows
        api_extra += len(set(api_items) - set(rule_items))
        rules_only += len(set(rule_items) - set(api_items))
        for row_no in rows:
            r = rule_items.get(row_no)
            a = api_items.get(row_no)
            if r is None or a is None:
                continue
            for f in FIELDS:
                rv, av = norm(r.get(f)), norm(a.get(f))
                per_field[f]["total"] += 1
                if rv == av:
                    per_field[f]["agree"] += 1
        notice_rows.append({
            "notice_id": nid,
            "rules_items": len(rule_items),
            "api_items": len(api_items),
            "matched_rows": matched_rows,
            "api_extra": len(set(api_items) - set(rule_items)),
            "rules_only": len(set(rule_items) - set(api_items)),
        })

    field_summary = {
        f: {
            "agreement": round(m["agree"] / m["total"], 4) if m["total"] else None,
            "compared": m["total"],
        }
        for f, m in per_field.items()
    }
    report = {
        "compared_notices": len(common),
        "matched_item_rows": item_pairs,
        "api_extra_rows": api_extra,
        "rules_only_rows": rules_only,
        "field_agreement": field_summary,
        "per_notice": notice_rows,
    }
    out = ROOT / "run" / "silver_api_vs_rules_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "compared_notices": report["compared_notices"],
        "matched_item_rows": report["matched_item_rows"],
        "api_extra_rows": report["api_extra_rows"],
        "rules_only_rows": report["rules_only_rows"],
        "field_agreement": field_summary,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
