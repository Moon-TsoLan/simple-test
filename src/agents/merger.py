"""Notice-level entity merge and conflict preservation."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .source_policy import canonical_product_name, item_is_non_result, source_tier
from .tools import ENTITY_FIELDS, compact


POSTPROCESS_VERSION = "1.0.0"


def _value_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return compact(value)


def _exact_key(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_value_key(item.get(field)) for field in ENTITY_FIELDS)


def _evidence_key(item: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((ref.get("block_id"), ref.get("block_row")) for ref in item.get("evidence_refs") or []))


def _merge_refs(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    refs = target.setdefault("evidence_refs", [])
    for ref in incoming.get("evidence_refs") or []:
        if ref not in refs:
            refs.append(ref)


def _compatible_business_item(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if canonical_product_name(left.get("product_service_name")) != canonical_product_name(
        right.get("product_service_name")
    ):
        return False
    numeric_matches = 0
    for field in ("unit_price", "quantity", "total_price"):
        old, new = left.get(field), right.get(field)
        if old is not None and new is not None:
            if _value_key(old) != _value_key(new):
                return False
            numeric_matches += 1
    # OCR can turn individual Chinese radicals into compatibility characters
    # and split ASCII model names.  Matching product plus at least two numeric
    # fields is stronger evidence of a duplicate than noisy brand/model text.
    tolerant_ocr_duplicate = numeric_matches >= 2
    for field in ("brand_supplier", "spec_model", "quantity_unit"):
        old, new = left.get(field), right.get(field)
        if (
            old is not None
            and new is not None
            and _value_key(old) != _value_key(new)
            and not tolerant_ocr_duplicate
        ):
            return False
    return True


def _item_quality(item: dict[str, Any]) -> tuple[int, int, float]:
    completeness = sum(item.get(field) is not None for field in ENTITY_FIELDS)
    return (
        source_tier(item.get("source")),
        completeness,
        float(item.get("confidence") or 0.0),
    )


def _merge_business_item(preferred: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(preferred)
    _merge_refs(result, secondary)
    request_ids = result.setdefault("request_ids", [])
    for request_id in secondary.get("request_ids") or []:
        if request_id not in request_ids:
            request_ids.append(request_id)
    for field in ENTITY_FIELDS:
        if result.get(field) is None and secondary.get(field) is not None:
            result[field] = secondary[field]
    return result


def curate_notice_items(
    items: list[dict[str, Any]],
    *,
    notice_id: str,
    title: str,
) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    """Remove non-result rows and merge compatible cross-source duplicates."""
    warnings: list[str] = []
    filtered: list[dict[str, Any]] = []
    removed_by_reason: dict[str, int] = {}
    for item in items:
        excluded, reason = item_is_non_result(item)
        if excluded:
            key = reason or "non_result"
            removed_by_reason[key] = removed_by_reason.get(key, 0) + 1
            continue
        filtered.append(item)

    best_tier_by_product: dict[str, int] = {}
    for item in filtered:
        key = canonical_product_name(item.get("product_service_name"))
        best_tier_by_product[key] = max(best_tier_by_product.get(key, 0), source_tier(item.get("source")))
    low_priority_duplicate_count = 0
    source_prioritized: list[dict[str, Any]] = []
    for item in filtered:
        key = canonical_product_name(item.get("product_service_name"))
        tier = source_tier(item.get("source"))
        if tier <= 1 and best_tier_by_product.get(key, tier) >= 3:
            low_priority_duplicate_count += 1
            continue
        source_prioritized.append(item)

    deduplicated: list[dict[str, Any]] = []
    duplicate_count = 0
    for item in source_prioritized:
        match_index = next(
            (index for index, existing in enumerate(deduplicated) if _compatible_business_item(existing, item)),
            None,
        )
        if match_index is None:
            deduplicated.append(item)
            continue
        duplicate_count += 1
        existing = deduplicated[match_index]
        if _item_quality(item) > _item_quality(existing):
            deduplicated[match_index] = _merge_business_item(item, existing)
        else:
            deduplicated[match_index] = _merge_business_item(existing, item)

    detailed_count = sum(
        any(item.get(field) is not None for field in ("brand_supplier", "spec_model", "unit_price", "quantity"))
        for item in deduplicated
    )
    title_key = canonical_product_name(title)
    final: list[dict[str, Any]] = []
    generic_summary_count = 0
    for item in deduplicated:
        product_key = canonical_product_name(item.get("product_service_name"))
        generic_name = bool(
            product_key
            and title_key
            and len(product_key) >= 8
            and (product_key in title_key or title_key in product_key)
        )
        has_detail = any(
            item.get(field) is not None
            for field in ("brand_supplier", "spec_model", "unit_price")
        )
        if detailed_count >= 2 and generic_name and not has_detail:
            generic_summary_count += 1
            continue
        final.append(item)

    if removed_by_reason:
        reason_text = ", ".join(f"{key}={value}" for key, value in sorted(removed_by_reason.items()))
        warnings.append(f"{notice_id} local postprocess removed non-result items: {reason_text}")
    if duplicate_count:
        warnings.append(f"{notice_id} local postprocess merged {duplicate_count} compatible cross-source duplicates")
    if low_priority_duplicate_count:
        warnings.append(
            f"{notice_id} local postprocess removed {low_priority_duplicate_count} lower-priority duplicate items"
        )
    if generic_summary_count:
        warnings.append(f"{notice_id} local postprocess removed {generic_summary_count} generic project summary items")
    for item_no, item in enumerate(final, 1):
        item["item_no"] = item_no
    return final, warnings, {
        "input_item_count": len(items),
        "removed_non_result_count": sum(removed_by_reason.values()),
        "removed_low_priority_duplicate_count": low_priority_duplicate_count,
        "merged_duplicate_count": duplicate_count,
        "removed_generic_summary_count": generic_summary_count,
        "output_item_count": len(final),
    }


def merge_notice(
    notice_id: str,
    title: str,
    outcomes: list[dict[str, Any]],
    *,
    agent_version: str,
) -> dict[str, Any]:
    """Merge request results without silently overwriting conflicting values."""
    merged: list[dict[str, Any]] = []
    warnings: list[str] = []
    exact_index: dict[tuple[str, ...], int] = {}
    evidence_index: dict[tuple[tuple[str, Any], ...], int] = {}
    for outcome in outcomes:
        warnings.extend(outcome.get("warnings") or [])
        for raw_item in outcome.get("items") or []:
            item = deepcopy(raw_item)
            item["extraction_method"] = outcome.get("method")
            item["confidence"] = outcome.get("confidence")
            item["request_ids"] = [outcome.get("request_id")]
            exact_key = _exact_key(item)
            evidence_key = _evidence_key(item)
            if exact_key in exact_index:
                target = merged[exact_index[exact_key]]
                _merge_refs(target, item)
                if outcome.get("request_id") not in target["request_ids"]:
                    target["request_ids"].append(outcome.get("request_id"))
                continue
            if evidence_key and evidence_key in evidence_index:
                target = merged[evidence_index[evidence_key]]
                conflicts = target.setdefault("field_conflicts", [])
                for field_name in ENTITY_FIELDS:
                    old, new = target.get(field_name), item.get(field_name)
                    if old is None and new is not None:
                        target[field_name] = new
                    elif old is not None and new is not None and _value_key(old) != _value_key(new):
                        conflict = {
                            "field": field_name,
                            "kept": old,
                            "alternative": new,
                            "request_id": outcome.get("request_id"),
                        }
                        if conflict not in conflicts:
                            conflicts.append(conflict)
                            warnings.append(
                                f"{notice_id} same evidence has conflicting {field_name}; kept both in field_conflicts"
                            )
                _merge_refs(target, item)
                if outcome.get("request_id") not in target["request_ids"]:
                    target["request_ids"].append(outcome.get("request_id"))
                exact_index[_exact_key(target)] = evidence_index[evidence_key]
                continue
            index = len(merged)
            merged.append(item)
            exact_index[exact_key] = index
            if evidence_key:
                evidence_index[evidence_key] = index

    for item in merged:
        if not item.get("field_conflicts"):
            item.pop("field_conflicts", None)
    merged, postprocess_warnings, postprocess_stats = curate_notice_items(
        merged,
        notice_id=notice_id,
        title=title,
    )
    warnings.extend(postprocess_warnings)
    status_counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    needs_model = sum(1 for outcome in outcomes if outcome.get("status") == "needs_model")
    failures = sum(1 for outcome in outcomes if outcome.get("status") == "failed")
    return {
        "schema_version": "1.0",
        "agent_version": agent_version,
        "postprocess_version": POSTPROCESS_VERSION,
        "notice_id": notice_id,
        "title": title,
        "status": "partial" if needs_model or failures else "complete",
        "request_count": len(outcomes),
        "status_counts": status_counts,
        "needs_model_request_count": needs_model,
        "failed_request_count": failures,
        "item_count": len(merged),
        "warnings": list(dict.fromkeys(warnings)),
        "postprocess": postprocess_stats,
        "items": merged,
    }
