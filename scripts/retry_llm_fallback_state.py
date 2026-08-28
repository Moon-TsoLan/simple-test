# -*- coding: utf-8 -*-
"""Remove fallback/error silver state entries so the next run retries them."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "run" / "state" / "deepseek_silver_state.jsonl"
NOTICE_DIR = ROOT / "dataset_build" / "silver" / "notices"


def main() -> int:
    rows = []
    retry = []
    for line in STATE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") == "ok" and rec.get("llm_status") == "ok":
            rows.append(rec)
        else:
            retry.append(rec["notice_id"])
    STATE.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows),
                     encoding="utf-8")
    for nid in retry:
        p = NOTICE_DIR / f"{nid}.json"
        if p.exists():
            p.unlink()
    print(json.dumps({"kept": len(rows), "retry": retry}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
