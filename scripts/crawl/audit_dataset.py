# -*- coding: utf-8 -*-
"""审计已下载数据集：完整性、附件失败明细、zip 重名。"""
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "dataset_build" / "manifests" / "manifest.json"
MIRROR_N = ROOT / "dataset_build" / "mirror_task1" / "notices"
MIRROR_A = ROOT / "dataset_build" / "mirror_task1" / "attachments"


def main():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    notices = m["notices"]
    incomplete = []
    missing = []
    dup_zip = []
    err_counter = Counter()
    for nid, n in notices.items():
        html_rel = n.get("html_file") or ""
        html = Path(html_rel)
        if not html.is_absolute():
            html = ROOT / html
        if not html_rel or not html.exists():
            missing.append((nid, "html"))
        zip_rel = n.get("zip_file") or ""
        zip_p = Path(zip_rel)
        if not zip_p.is_absolute():
            zip_p = ROOT / zip_p
        if zip_rel and zip_p.exists():
            names = zipfile.ZipFile(zip_p).namelist()
            dups = [k for k, v in Counter(names).items() if v > 1]
            if dups:
                dup_zip.append((nid, dups))
        elif n.get("attachment_total_count", 0) > 0:
            missing.append((nid, "zip"))
        atts = n.get("attachments") or []
        ok = [a for a in atts if a.get("file_name")]
        if len(ok) < len(atts):
            incomplete.append((nid, len(ok), len(atts), [(a.get("source_name"), a.get("error")) for a in atts if not a.get("file_name")]))
            for a in atts:
                if not a.get("file_name"):
                    err_counter[str(a.get("error", "unknown"))[:60]] += 1
    mirror_missing = []
    for p in MIRROR_N.glob("*.html"):
        nid = p.stem
        if nid not in notices:
            mirror_missing.append((nid, "notice-not-in-manifest"))
    for p in MIRROR_A.glob("*.zip"):
        nid = p.stem
        if nid not in notices:
            mirror_missing.append((nid, "zip-not-in-manifest"))

    print("总条目", len(notices))
    print("文件缺失", len(missing), missing[:10])
    print("附件未下全", len(incomplete))
    for nid, okc, total, errs in incomplete:
        print(" INCOMPLETE", nid, f"{okc}/{total}", errs)
    print("zip 内重名", len(dup_zip))
    for nid, dups in dup_zip:
        print(" DUP", nid, dups)
    print("镜像多余文件", len(mirror_missing), mirror_missing[:10])
    print("错误类型", dict(err_counter))


if __name__ == "__main__":
    main()
