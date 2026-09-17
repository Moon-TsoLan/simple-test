# -*- coding: utf-8 -*-
"""从 CCGP 按赛题包装抓取 fake_official_data（HTML+ZIP），不跑现有抽取流程。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crawl import download_ccgp as crawl  # noqa: E402
from scripts.crawl.packaging import (  # noqa: E402
    accept_list_item,
    html_is_usable,
    interleave_by_source,
    materialize_pair,
    pair_is_usable,
    quality_report,
    write_json,
    write_rejects,
    zip_is_usable,
)

DEFAULT_OUT = ROOT / "dataset_build" / "fake_official_data"
DEFAULT_CRAWL = DEFAULT_OUT / "_crawl"


def _abs(path: str | None) -> Path | None:
    if not path:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _html_path(notice_id: str, entry: dict[str, Any]) -> Path | None:
    rel = entry.get("html_file")
    if rel:
        path = Path(rel)
        return path if path.is_absolute() else ROOT / path
    date_dir = crawl.HTML_DIR / notice_id[:8]
    candidate = date_dir / f"{notice_id}.html"
    return candidate if candidate.exists() else None


def _zip_path(notice_id: str, entry: dict[str, Any]) -> Path | None:
    rel = entry.get("zip_file")
    if rel:
        path = Path(rel)
        return path if path.is_absolute() else ROOT / path
    candidate = crawl.ATTACH_DIR / f"{notice_id}.zip"
    return candidate if candidate.exists() else None


def materialize_from_crawl(
    crawl_manifest: dict[str, Any],
    output_dir: Path,
    *,
    target: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    notices_dir = output_dir / "notices"
    attachments_dir = output_dir / "attachments"
    records: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for notice_id, entry in crawl_manifest.get("notices", {}).items():
        html_src = _html_path(notice_id, entry)
        zip_src = _zip_path(notice_id, entry)
        extra = {
            "url": entry.get("url") or "",
            "source_type": entry.get("source_type") or "",
            "source_key": entry.get("source_key") or "",
            "title": entry.get("title") or "",
            "publish_time": entry.get("publish_time") or "",
            "attachment_bytes": [
                {"name": item.get("file_name"), "bytes": item.get("bytes")}
                for item in (entry.get("attachments") or [])
                if item.get("file_name")
            ],
        }
        if html_src is None or zip_src is None:
            rejects.append({"notice_id": notice_id, "reason": "missing_html_or_zip", **extra})
            continue
        ok, reason, _meta = pair_is_usable(html_src, zip_src)
        if not ok:
            rejects.append({"notice_id": notice_id, "reason": reason, **extra})
            continue
        if len(records) >= target:
            rejects.append({"notice_id": notice_id, "reason": "over_target", **extra})
            continue
        records.append(materialize_pair(notice_id, html_src, zip_src, notices_dir, attachments_dir, extra))
    keep = {item["notice_id"] for item in records}
    if notices_dir.exists():
        for path in notices_dir.glob("*.html"):
            if path.stem not in keep:
                path.unlink(missing_ok=True)
                (attachments_dir / f"{path.stem}.zip").unlink(missing_ok=True)
    return records, rejects


def verify_output(output_dir: Path) -> dict[str, Any]:
    notices = sorted((output_dir / "notices").glob("*.html"))
    problems = []
    ok = 0
    for html_path in notices:
        zip_path = output_dir / "attachments" / f"{html_path.stem}.zip"
        usable, reason, _ = pair_is_usable(html_path, zip_path)
        if usable:
            ok += 1
        else:
            problems.append({"notice_id": html_path.stem, "reason": reason})
    return {"paired_ok": ok, "html_count": len(notices), "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--crawl-root", type=Path, default=DEFAULT_CRAWL)
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=4, help="每个栏目列表页数，约 20 条/页")
    parser.add_argument("--max-notices", type=int, default=0, help="列表候选上限，0 表示该页数内全部")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--materialize-only", action="store_true", help="只从已有 _crawl 清单落盘，不访问网络")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    crawl_root = args.crawl_root if args.crawl_root.is_absolute() else ROOT / args.crawl_root

    crawl.configure_paths(crawl_root, enable_mirror=False)

    if args.materialize_only:
        manifest = crawl.load_manifest()
        records, rejects = materialize_from_crawl(manifest, output_dir, target=args.target)
        write_json(output_dir / "manifest.json", {"version": 1, "notice_count": len(records), "notices": {r["notice_id"]: r for r in records}})
        write_rejects(output_dir / "REJECTS.jsonl", rejects)
        (output_dir / "quality_report.md").write_text(quality_report(records, rejects), encoding="utf-8")
        report = verify_output(output_dir)
        print(json.dumps({"materialized": len(records), "rejects": len(rejects), **report}, ensure_ascii=False, indent=2))
        return 0 if report["paired_ok"] else 2

    class _Args:
        mode = "all"
        sources = "dfgg/zbgg,zygg/zbgg,dfgg/cjgg,zygg/cjgg"
        max_pages = args.max_pages
        max_notices = args.max_notices
        list_delay_min = 3.0
        list_delay_max = 5.0
        att_delay_min = 0.8
        att_delay_max = 1.6
        backoff = 30.0
        retries = 3
        force = args.force
        skip_incomplete = False

    list_args = _Args()
    candidates = crawl.collect_notices(list_args)
    kept: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    for item in candidates:
        ok, reason = accept_list_item(item)
        if ok:
            kept.append(item)
        else:
            rejects.append({"notice_id": item.get("notice_id"), "reason": reason, "title": item.get("title"), "url": item.get("url")})
    ordered = interleave_by_source(kept)
    if args.list_only:
        print(json.dumps({"candidates": len(candidates), "kept": len(ordered), "rejects": len(rejects)}, ensure_ascii=False, indent=2))
        return 0

    session = crawl.SafeSession(retries=list_args.retries, backoff=list_args.backoff)
    manifest = crawl.load_manifest()
    seen = crawl.load_state("seen.json")
    failed = crawl.load_state("failed.json")
    paired = 0
    for index, item in enumerate(ordered, 1):
        already = sum(1 for n in manifest.get("notices", {}).values() if n.get("html_ok") and n.get("zip_file"))
        if already >= args.target:
            crawl.log(f"[STOP] 清单已有 {already} 对，停止下载")
            break
        nid = item["notice_id"]
        prev = seen.get(nid, {})
        if not args.force and prev.get("html_ok") and prev.get("zip_file"):
            crawl.log(f"[SKIP] {index}/{len(ordered)} {nid} 已成对")
            continue
        crawl.log(f"[START] {index}/{len(ordered)} {nid} {(item.get('title') or '')[:60]}")
        crawl.process_notice(session, item, list_args, manifest, seen, failed)
        html_src = _html_path(nid, manifest["notices"].get(nid, {}))
        zip_src = _zip_path(nid, manifest["notices"].get(nid, {}))
        if html_src and zip_src and pair_is_usable(html_src, zip_src)[0]:
            paired += 1
            crawl.log(f"[PAIR] {paired}/{args.target} {nid}")
        elif html_src and (zip_src is None or not zip_is_usable(zip_src)[0]):
            rejects.append({"notice_id": nid, "reason": "no_usable_zip", "title": item.get("title"), "url": item.get("url")})
        elif html_src and not html_is_usable(html_src)[0]:
            rejects.append({"notice_id": nid, "reason": "html_unusable", "title": item.get("title"), "url": item.get("url")})
        if paired >= args.target:
            break
        crawl.random_sleep(1.5, 3.0)

    records, materialize_rejects = materialize_from_crawl(manifest, output_dir, target=args.target)
    rejects.extend(materialize_rejects)
    write_json(output_dir / "manifest.json", {"version": 1, "notice_count": len(records), "notices": {r["notice_id"]: r for r in records}})
    write_rejects(output_dir / "REJECTS.jsonl", rejects)
    (output_dir / "quality_report.md").write_text(quality_report(records, rejects), encoding="utf-8")
    report = verify_output(output_dir)
    print(json.dumps({
        "candidates": len(candidates),
        "list_kept": len(ordered),
        "materialized": len(records),
        "rejects": len(rejects),
        **report,
        "output": str(output_dir),
    }, ensure_ascii=False, indent=2))
    return 0 if report["paired_ok"] >= min(args.target, 1) else 2


if __name__ == "__main__":
    raise SystemExit(main())
