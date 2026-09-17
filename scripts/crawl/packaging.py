# -*- coding: utf-8 -*-
"""赛题包装闸：只判断结果公告 + HTML/ZIP 配对，不调用现有抽取规则。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

TITLE_EXCLUDE_RE = re.compile(r"废标|流标|终止|更正|澄清|延期")
RESULT_SOURCE_KEYS = ("dfgg/zbgg", "zygg/zbgg", "dfgg/cjgg", "zygg/cjgg")
MANIFEST_SKIP_NAMES = {"_files_manifest.json"}


def is_excluded_title(title: str) -> bool:
    return bool(TITLE_EXCLUDE_RE.search(title or ""))


def is_result_source(source_key: str) -> bool:
    return source_key in RESULT_SOURCE_KEYS


def accept_list_item(item: dict[str, Any]) -> tuple[bool, str]:
    source_key = str(item.get("source_key") or "")
    if not is_result_source(source_key):
        return False, "not_result_column"
    if "/cggg/" not in str(item.get("url") or ""):
        return False, "not_cggg_url"
    if is_excluded_title(str(item.get("title") or "")):
        return False, "excluded_title"
    return True, "ok"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_html_title(html_path: Path) -> str:
    try:
        import lxml.html
    except ImportError:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        return " ".join((match.group(1) if match else "").split())
    root = lxml.html.fromstring(html_path.read_bytes())
    for xpath in (
        ".//div[contains(@class,'vF_detail_header')]//h2",
        ".//h1",
        ".//h2",
        ".//title",
    ):
        nodes = root.xpath(xpath)
        if nodes:
            title = " ".join(nodes[0].text_content().split())
            if title:
                return title
    return ""


def zip_attachment_names(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        names = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if name in MANIFEST_SKIP_NAMES or info.filename.endswith("/"):
                continue
            if ".." in Path(info.filename).parts:
                continue
            names.append(info.filename)
        return names


def zip_is_usable(zip_path: Path) -> tuple[bool, str, list[str]]:
    if not zip_path.is_file() or zip_path.stat().st_size <= 0:
        return False, "zip_missing_or_empty", []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad = archive.testzip()
            if bad:
                return False, f"zip_crc_error:{bad}", []
    except zipfile.BadZipFile as exc:
        return False, f"zip_open_error:{exc}", []
    names = zip_attachment_names(zip_path)
    if not names:
        return False, "zip_no_real_files", []
    return True, "ok", names


def html_is_usable(html_path: Path) -> tuple[bool, str, str]:
    if not html_path.is_file() or html_path.stat().st_size <= 0:
        return False, "html_missing_or_empty", ""
    title = resolve_html_title(html_path)
    if not title:
        return False, "html_no_title", ""
    if is_excluded_title(title):
        return False, "excluded_title", title
    return True, "ok", title


def pair_is_usable(html_path: Path, zip_path: Path) -> tuple[bool, str, dict[str, Any]]:
    html_ok, html_reason, title = html_is_usable(html_path)
    if not html_ok:
        return False, html_reason, {"title": title}
    zip_ok, zip_reason, names = zip_is_usable(zip_path)
    if not zip_ok:
        return False, zip_reason, {"title": title, "attachment_names": names}
    return True, "ok", {
        "title": title,
        "attachment_names": names,
        "html_bytes": html_path.stat().st_size,
        "zip_bytes": zip_path.stat().st_size,
        "html_sha256": sha256_file(html_path),
        "zip_sha256": sha256_file(zip_path),
    }


def source_bucket(source_key: str) -> str:
    return source_key if source_key in RESULT_SOURCE_KEYS else "other"


def interleave_by_source(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in RESULT_SOURCE_KEYS}
    for item in items:
        key = source_bucket(str(item.get("source_key") or ""))
        if key in buckets:
            buckets[key].append(item)
    ordered: list[dict[str, Any]] = []
    while any(buckets.values()):
        for key in RESULT_SOURCE_KEYS:
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered


def materialize_pair(
    notice_id: str,
    html_src: Path,
    zip_src: Path,
    notices_dir: Path,
    attachments_dir: Path,
    extra: dict[str, Any],
) -> dict[str, Any]:
    notices_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    html_dst = notices_dir / f"{notice_id}.html"
    zip_dst = attachments_dir / f"{notice_id}.zip"
    shutil.copy2(html_src, html_dst)
    shutil.copy2(zip_src, zip_dst)
    ok, reason, meta = pair_is_usable(html_dst, zip_dst)
    if not ok:
        html_dst.unlink(missing_ok=True)
        zip_dst.unlink(missing_ok=True)
        raise ValueError(f"{notice_id}: {reason}")
    record = {
        "notice_id": notice_id,
        "url": extra.get("url") or "",
        "source_type": extra.get("source_type") or "",
        "source_key": extra.get("source_key") or "",
        "title": extra.get("title") or meta.get("title") or "",
        "publish_time": extra.get("publish_time") or "",
        "html_sha256": meta["html_sha256"],
        "zip_sha256": meta["zip_sha256"],
        "attachment_names": [Path(name).name for name in meta["attachment_names"]],
        "byte_sizes": {
            "html": meta["html_bytes"],
            "zip": meta["zip_bytes"],
            "attachments": extra.get("attachment_bytes") or [],
        },
    }
    return record


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_rejects(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def quality_report(records: list[dict[str, Any]], rejects: list[dict[str, Any]]) -> str:
    sources = Counter(item.get("source_type") or "未知" for item in records)
    keys = Counter(item.get("source_key") or "未知" for item in records)
    reject_reasons = Counter(item.get("reason") or "unknown" for item in rejects)
    central = sum(1 for item in records if str(item.get("source_key") or "").startswith("zygg/"))
    local = sum(1 for item in records if str(item.get("source_key") or "").startswith("dfgg/"))
    zbgg = sum(1 for item in records if str(item.get("source_key") or "").endswith("/zbgg"))
    cjgg = sum(1 for item in records if str(item.get("source_key") or "").endswith("/cjgg"))
    lines = [
        "# fake_official_data 包装报告",
        "",
        "本目录是方法对照台的原始输入（HTML+ZIP），**不含**现有 Parser/Selector/Agent 结果。",
        "现有抽取流水线只是后续候选方法之一；新方法应另开 `run/` 目录输出，不要写回本目录。",
        "",
        f"- 入选配对：{len(records)}",
        f"- 剔除条目：{len(rejects)}",
        f"- 中央 / 地方：{central} / {local}",
        f"- 中标 / 成交：{zbgg} / {cjgg}",
        "",
        "## 栏目",
        "",
    ]
    for name, count in sources.most_common():
        lines.append(f"- {name}：{count}")
    lines += ["", "## source_key", ""]
    for name, count in keys.most_common():
        lines.append(f"- {name}：{count}")
    lines += ["", "## 剔除原因", ""]
    if reject_reasons:
        for name, count in reject_reasons.most_common():
            lines.append(f"- {name}：{count}")
    else:
        lines.append("- （无）")
    lines += [
        "",
        "## 后续用法",
        "",
        "```text",
        "--notice-dir dataset_build/fake_official_data/notices",
        "--attachment-dir dataset_build/fake_official_data/attachments",
        "```",
        "",
        "正式约 1000 条到达后，用 `scripts/adapt/official_adapter.py` 映射到同一对目录即可换输入，不必改抽取代码。",
        "外部 API 调用需另行授权次数与 Token 上限。",
        "",
    ]
    return "\n".join(lines)
