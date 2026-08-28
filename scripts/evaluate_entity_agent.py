# -*- coding: utf-8 -*-
"""Evaluate agent evidence and exact field values on the manual gold seed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "product_service_name", "category_name", "category_code", "brand_supplier",
    "spec_model", "unit_price", "quantity", "quantity_unit", "total_price",
)


def evaluate(gold_dir: Path, result_dir: Path, *, scope_to_results: bool = False) -> dict:
    total = 0
    evidence_matched = 0
    predicted_item_count = 0
    predicted_items_with_gold_evidence = 0
    strict_exact_item_matches = 0
    field_counts = {field: {"exact": 0, "compared": 0} for field in FIELDS}
    per_notice = []
    for gold_path in sorted(gold_dir.glob("*.json")):
        result_path = result_dir / gold_path.name
        if scope_to_results and not result_path.exists():
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        if not result_path.exists():
            per_notice.append({"notice_id": gold_path.stem, "gold_items": len(gold.get("items") or []), "evidence_matched": 0, "status": "missing"})
            total += len(gold.get("items") or [])
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        gold_evidence_keys = {
            (item.get("source_block_id"), item.get("source_block_row"))
            for item in gold.get("items") or []
        }
        result_items = list(result.get("items") or [])
        predicted_item_count += len(result_items)
        predicted_items_with_gold_evidence += sum(
            any((ref.get("block_id"), ref.get("block_row")) in gold_evidence_keys for ref in item.get("evidence_refs") or [])
            for item in result_items
        )
        by_evidence = {}
        for item in result_items:
            for ref in item.get("evidence_refs") or []:
                by_evidence[(ref.get("block_id"), ref.get("block_row"))] = item
        notice_hits = 0
        for gold_item in gold.get("items") or []:
            total += 1
            agent_item = by_evidence.get((gold_item.get("source_block_id"), gold_item.get("source_block_row")))
            if agent_item is None:
                continue
            evidence_matched += 1
            notice_hits += 1
            for field in FIELDS:
                field_counts[field]["compared"] += 1
                if gold_item.get(field) == agent_item.get(field):
                    field_counts[field]["exact"] += 1
            if all(gold_item.get(field) == agent_item.get(field) for field in FIELDS):
                strict_exact_item_matches += 1
        per_notice.append({
            "notice_id": gold_path.stem,
            "gold_items": len(gold.get("items") or []),
            "predicted_items": len(result_items),
            "evidence_matched": notice_hits,
            "status": result.get("status"),
        })
    return {
        "gold_notice_count": len(per_notice),
        "gold_item_count": total,
        "evidence_matched": evidence_matched,
        "evidence_recall": round(evidence_matched / total, 4) if total else 1.0,
        "predicted_item_count_on_gold_notices": predicted_item_count,
        "predicted_items_with_gold_evidence": predicted_items_with_gold_evidence,
        "evidence_precision_against_gold_seed": (
            round(predicted_items_with_gold_evidence / predicted_item_count, 4)
            if predicted_item_count else 1.0
        ),
        "strict_exact_item_matches": strict_exact_item_matches,
        "strict_exact_recall": round(strict_exact_item_matches / total, 4) if total else 1.0,
        "metric_warning": (
            "The gold set is a single-annotator seed. Precision treats every prediction without a gold evidence "
            "coordinate as unmatched and is only valid if each gold notice was exhaustively annotated."
        ),
        "field_exact_on_evidence_matched": {
            field: round(values["exact"] / values["compared"], 4) if values["compared"] else None
            for field, values in field_counts.items()
        },
        "per_notice": per_notice,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path, default=ROOT / "dataset_build" / "gold" / "notices")
    parser.add_argument("--result-dir", type=Path, default=ROOT / "dataset_build" / "agent_results" / "notices")
    parser.add_argument("--output", type=Path, default=ROOT / "dataset_build" / "agent_results" / "gold_evaluation.json")
    parser.add_argument(
        "--scope-to-results", action="store_true",
        help="evaluate only gold notices present in result-dir (for an explicitly scoped pilot)",
    )
    args = parser.parse_args()
    report = evaluate(args.gold_dir, args.result_dir, scope_to_results=args.scope_to_results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
