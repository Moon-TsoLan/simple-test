# -*- coding: utf-8 -*-
"""把已抓取公告同步到官方同构镜像目录，并刷新 manifest.csv。

- mirror_task1/notices  ：每篇公告一个 html
- mirror_task1/attachments：每篇公告一个 zip
- mirror_task2/notices  ：任务二使用的 html（与任务一公告同源）
"""
import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "dataset_build" / "manifests" / "manifest.json"
MIRROR1_N = ROOT / "dataset_build" / "mirror_task1" / "notices"
MIRROR1_A = ROOT / "dataset_build" / "mirror_task1" / "attachments"
MIRROR2_N = ROOT / "dataset_build" / "mirror_task2" / "notices"

for d in (MIRROR1_N, MIRROR1_A, MIRROR2_N):
    d.mkdir(parents=True, exist_ok=True)


def copy_if_absent(src: Path, dst_dir: Path):
    if src.exists():
        dst = dst_dir / src.name
        if not dst.exists() or src.stat().st_size != dst.stat().st_size:
            shutil.copy2(src, dst)


def main():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    notices = m.get("notices", {})
    n_html = n_zip = n_t2 = 0
    for nid, n in notices.items():
        html_rel = n.get("html_file") or ""
        if html_rel:
            html = ROOT / html_rel
            if html.exists():
                copy_if_absent(html, MIRROR1_N)
                copy_if_absent(html, MIRROR2_N)
                n_html += 1
                n_t2 += 1
        zip_rel = n.get("zip_file") or ""
        if zip_rel:
            zipf = ROOT / zip_rel
            if zipf.exists():
                copy_if_absent(zipf, MIRROR1_A)
                n_zip += 1
    # 刷新 manifest.csv
    csv_path = ROOT / "dataset_build" / "manifests" / "manifest.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["notice_id", "title", "url", "source_type", "publish_time", "region", "buyer",
                    "html_file", "zip_file", "attachment_total", "attachment_ok", "status"])
        for nid, n in notices.items():
            w.writerow([nid, n.get("title", ""), n.get("url", ""), n.get("source_type", ""),
                        n.get("publish_time", ""), n.get("region", ""), n.get("buyer", ""),
                        n.get("html_file", ""), n.get("zip_file", ""),
                        n.get("attachment_total_count", 0), n.get("attachment_ok_count", 0),
                        n.get("status", "")])
    print(f"同步完成：HTML={n_html}，ZIP={n_zip}，任务二HTML={n_t2}，总条目={len(notices)}")


if __name__ == "__main__":
    main()
