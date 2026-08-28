# -*- coding: utf-8 -*-
"""根据 manifest.csv/manifest.json 核对 HTML 与附件是否真实落盘。

检查项：
1. manifest 每个 notice 的 html_file 是否存在、大小 > 0、可解析出标题；
2. manifest 记录的 url 是否与 notice_id 来源路径一致；
3. 每个 attachment.file_name 是否在 attachments/{notice_id}/ 中；
4. 每个 zip_file 是否存在且能打开。
"""
import json
import zipfile
from pathlib import Path

import lxml.html

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "dataset_build" / "manifests" / "manifest.json"
ATTACH_DIR = ROOT / "dataset_build" / "crawl" / "attachments"
OUT = ROOT / "dataset_build" / "manifests" / "verify_report.md"


def main():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    notices = m.get("notices", {})
    problems = []
    html_ok = 0
    zip_ok = 0
    att_ok = 0
    att_total = 0

    for nid, n in notices.items():
        html_rel = n.get("html_file") or ""
        html = ROOT / html_rel if html_rel else None
        if not html or not html.exists() or html.stat().st_size == 0:
            problems.append((nid, "html_missing_or_empty", html_rel))
            continue
        try:
            root = lxml.html.fromstring(html.read_bytes())
            title_node = root.xpath("//title") or root.xpath("//h2")
            title = " ".join(title_node[0].text_content().split()) if title_node else ""
        except Exception as exc:
            problems.append((nid, "html_parse_error", str(exc)))
            title = ""
        if title:
            html_ok += 1
        else:
            problems.append((nid, "html_no_title", html_rel))

        # URL 路径中的 notice_id 应与条目 id 一致
        if nid not in (n.get("url") or ""):
            problems.append((nid, "url_notice_id_mismatch", n.get("url", "")))

        for a in (n.get("attachments") or []):
            att_total += 1
            fname = a.get("file_name")
            if not fname:
                continue
            p = ATTACH_DIR / nid / fname
            if p.exists() and p.stat().st_size > 0:
                att_ok += 1
            else:
                problems.append((nid, "attachment_file_missing", fname))

        zip_rel = n.get("zip_file") or ""
        zip_p = ROOT / zip_rel if zip_rel else None
        if zip_p and zip_p.exists():
            try:
                with zipfile.ZipFile(zip_p) as zf:
                    bad = zf.testzip()
                if bad:
                    problems.append((nid, "zip_crc_error", bad))
                else:
                    zip_ok += 1
            except Exception as exc:
                problems.append((nid, "zip_open_error", str(exc)))

    lines = [
        "# 数据集落盘核对报告",
        "",
        f"- 清单条目：{len(notices)}",
        f"- HTML 可解析且有标题：{html_ok}",
        f"- ZIP 可正常打开：{zip_ok}",
        f"- 附件文件落盘：{att_ok}/{att_total}",
        f"- 异常数：{len(problems)}",
        "",
    ]
    if problems:
        lines.append("## 异常明细")
        lines.append("")
        lines.append("| notice_id | 类型 | 详情 |")
        lines.append("|---|---|---|")
        for p in problems:
            lines.append(f"| {p[0]} | {p[1]} | {p[2]} |")
    lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
