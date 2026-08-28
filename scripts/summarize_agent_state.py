# -*- coding: utf-8 -*-
"""Summarize every append-only agent-state record, including retries."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def summarize(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    usage = {key: 0 for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    status_counts: Counter[str] = Counter()
    request_counts: Counter[str] = Counter()
    for record in records:
        outcome = record.get("outcome") or {}
        status_counts[str(outcome.get("status") or "unknown")] += 1
        record_id = str(record.get("request_id") or record.get("notice_id") or "")
        request_counts[record_id] += 1
        for key in usage:
            usage[key] += int((outcome.get("usage") or {}).get(key) or 0)
    retried = {request_id: count for request_id, count in request_counts.items() if request_id and count > 1}
    return {
        "state_file": str(path),
        "record_count": len(records),
        "unique_request_count": len(request_counts),
        "repeated_request_count": len(retried),
        "repeated_requests": retried,
        "record_status_counts": dict(status_counts),
        "historical_usage": usage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.state_file)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
