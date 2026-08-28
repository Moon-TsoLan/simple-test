# -*- coding: utf-8 -*-
"""生成自建数据集统计报告（manifest 必须已更新）。"""
import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "dataset_build" / "manifests" / "manifest.json"
OUT = ROOT / "dataset_build" / "manifests" / "data_report.md"


def main():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    notices = m.get("notices", {})
    fmt = Counter()
    sizes = Counter()
    with_att = without_att = html_ok = zip_ok = failed = 0
    source_counter = Counter()
    region_counter = Counter()

    for nid, n in notices.items():
        source_counter[n.get("source_type", "未知")] += 1
        region_counter[n.get("region", "未知")] += 1
        if n.get("html_ok"):
            html_ok += 1
        if n.get("zip_file"):
            zip_ok += 1
        if n.get("status") == "failed":
            failed += 1
        atts = n.get("attachments") or []
        ok_atts = [a for a in atts if a.get("file_name")]
        if ok_atts:
            with_att += 1
        else:
            without_att += 1
        for a in ok_atts:
            ext = Path(a["file_name"]).suffix.lower()
            fmt[ext] += 1
            sizes[ext] += a.get("bytes", 0)

    lines = [
        "# 自建数据集统计报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 公告总数：{len(notices)}",
        f"- HTML 下载成功：{html_ok}",
        f"- 已打包附件 zip：{zip_ok}",
        f"- 含附件公告：{with_att}",
        f"- 无附件公告：{without_att}",
        f"- 失败条目：{failed}",
        "",
        "## 公告来源",
        "",
    ]
    for k, v in source_counter.most_common():
        lines.append(f"- {k}：{v}")
    lines += ["", "## 地域分布", ""]
    for k, v in region_counter.most_common(15):
        lines.append(f"- {k}：{v}")
    lines += ["", "## 附件格式", "", "| 扩展名 | 文件数 | 总字节数 |", "|---|---:|---:|"]
    for ext, cnt in fmt.most_common():
        lines.append(f"| {ext or '无'} | {cnt} | {sizes[ext]} |")
    lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
