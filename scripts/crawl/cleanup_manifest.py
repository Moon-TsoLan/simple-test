# -*- coding: utf-8 -*-
"""清理清单与状态中非 /cggg/ 栏目的误抓条目（新闻/法规边栏）。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = ROOT / "dataset_build" / "manifests"
STATE_DIR = ROOT / "dataset_build" / "crawl" / "state"


def load(p):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(p, data):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def main():
    manifest = load(MANIFEST_DIR / "manifest.json")
    seen = load(STATE_DIR / "seen.json")
    failed = load(STATE_DIR / "failed.json")
    notices = manifest.get("notices", {})
    bad = [nid for nid, n in notices.items() if "/cggg/" not in n.get("url", "")]
    print("总条目", len(notices), "非政采公告", len(bad))
    for nid in bad:
        n = notices.pop(nid, None)
        seen.pop(nid, None)
        failed.pop(nid, None)
        print("移除", nid, n.get("title", "")[:50] if n else "")
    save(MANIFEST_DIR / "manifest.json", manifest)
    save(STATE_DIR / "seen.json", seen)
    save(STATE_DIR / "failed.json", failed)
    print("剩余", len(manifest.get("notices", {})), "条")


if __name__ == "__main__":
    main()
