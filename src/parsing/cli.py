"""Command-line batch converter for notice HTML and attachment archives."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .pipeline import NoticeParser, ParserConfig, parser_config_digest
from .schema import PARSER_VERSION, SCHEMA_VERSION


def _load_manifest(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("notices", payload)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _convert_one(task: dict[str, Any]) -> dict[str, Any]:
    parser = NoticeParser(ParserConfig(**task["config"]))
    payload = parser.parse_notice(
        task["notice_id"],
        task["html_path"],
        task.get("attachment_path"),
        title=task.get("title"),
        notice_metadata=task.get("metadata"),
    )
    output_path = Path(task["output_path"])
    _write_json_atomic(output_path, payload)
    errors = payload["stats"]["document_status_counts"].get("error", 0)
    issues = [
        {
            "container_path": document["container_path"],
            "status": document["status"],
            "warnings": document["warnings"],
        }
        for document in payload["documents"]
        if document["status"] != "ok" or document["warnings"]
    ]
    return {
        "notice_id": task["notice_id"],
        "output": str(output_path),
        "documents": payload["stats"]["document_count"],
        "blocks": payload["stats"]["block_count"],
        "errors": errors,
        "document_status_counts": payload["stats"]["document_status_counts"],
        "block_type_counts": payload["stats"]["block_type_counts"],
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert notices and attachments to unified JSON blocks")
    parser.add_argument("--notice-dir", type=Path, default=Path("dataset_build/mirror_task1/notices"))
    parser.add_argument("--attachment-dir", type=Path, default=Path("dataset_build/mirror_task1/attachments"))
    parser.add_argument("--output-dir", type=Path, default=Path("dataset_build/blocks/notices"))
    parser.add_argument("--manifest", type=Path, default=Path("dataset_build/manifests/manifest.json"))
    parser.add_argument("--ids", nargs="*", help="Only convert these notice IDs")
    parser.add_argument("--max-notices", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--ocr", choices=("auto", "rapidocr", "tesseract", "none"), default="auto")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-archive-depth", type=int, default=3)
    parser.add_argument("--max-uncompressed-gb", type=float, default=2.0)
    parser.add_argument(
        "--max-ocr-pages-per-pdf",
        type=int,
        default=20,
        help="OCR at most this many scan pages per PDF; 0 means all pages",
    )
    parser.add_argument(
        "--pdf-table-text-overlap-threshold",
        type=float,
        default=0.5,
        help="Suppress native PDF paragraph blocks covered by a detected table by at least this ratio; 0 disables",
    )
    parser.add_argument(
        "--no-pdf-watermark-filter",
        dest="pdf_filter_native_watermarks",
        action="store_false",
        help="Disable conservative native PDF watermark filtering for diagnostic comparison",
    )
    parser.add_argument(
        "--skip-ocr-if-scan-pages-over",
        type=int,
        default=0,
        help="Skip OCR for PDFs with more scan pages than this; 0 disables this baseline shortcut",
    )
    parser.add_argument(
        "--legacy-office-backend",
        choices=("auto", "libreoffice", "ms-office", "none"),
        default="libreoffice",
        help="Converter for binary DOC/XLS; MS Office is explicit because COM is less batch-safe",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = _load_manifest(args.manifest)
    selected = set(args.ids or [])
    html_files = sorted(args.notice_dir.glob("*.html"))
    if selected:
        html_files = [path for path in html_files if path.stem in selected]
    if args.max_notices is not None:
        html_files = html_files[: args.max_notices]

    config = ParserConfig(
        ocr=args.ocr,
        max_archive_depth=args.max_archive_depth,
        max_uncompressed_bytes=int(args.max_uncompressed_gb * 1024**3),
        pdf_table_text_overlap_threshold=args.pdf_table_text_overlap_threshold,
        pdf_filter_native_watermarks=args.pdf_filter_native_watermarks,
        max_ocr_pages_per_pdf=args.max_ocr_pages_per_pdf,
        skip_ocr_if_scan_pages_over=args.skip_ocr_if_scan_pages_over,
        legacy_office_backend=args.legacy_office_backend,
    )
    tasks: list[dict[str, Any]] = []
    skipped = 0
    for html_path in html_files:
        notice_id = html_path.stem
        output_path = args.output_dir / f"{notice_id}.json"
        if output_path.exists() and not args.overwrite:
            skipped += 1
            continue
        attachment = args.attachment_dir / f"{notice_id}.zip"
        record = manifest.get(notice_id, {})
        metadata = {
            key: record.get(key)
            for key in ("url", "source_type", "publish_time", "region", "buyer")
            if record.get(key) is not None
        }
        tasks.append(
            {
                "notice_id": notice_id,
                "html_path": str(html_path),
                "attachment_path": str(attachment) if attachment.exists() else None,
                "output_path": str(output_path),
                "title": record.get("title"),
                "metadata": metadata,
                "config": asdict(config),
            }
        )

    results: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    if args.workers <= 1:
        for task in tasks:
            try:
                results.append(_convert_one(task))
            except Exception as exc:
                failed.append({"notice_id": task["notice_id"], "error": f"{type(exc).__name__}: {exc}"})
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(_convert_one, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    failed.append({"notice_id": task["notice_id"], "error": f"{type(exc).__name__}: {exc}"})

    aggregate_status: dict[str, int] = {}
    aggregate_types: dict[str, int] = {}
    issues: list[dict[str, Any]] = []
    for result in results:
        for status, count in result["document_status_counts"].items():
            aggregate_status[status] = aggregate_status.get(status, 0) + count
        for block_type, count in result["block_type_counts"].items():
            aggregate_types[block_type] = aggregate_types.get(block_type, 0) + count
        issues.extend({"notice_id": result["notice_id"], **issue} for issue in result["issues"])

    report = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "parser_config_digest": parser_config_digest(config),
        "parser_config": asdict(config),
        "input_count": len(html_files),
        "converted_count": len(results),
        "skipped_count": skipped,
        "failed_count": len(failed),
        "total_documents": sum(item["documents"] for item in results),
        "total_blocks": sum(item["blocks"] for item in results),
        "document_errors": sum(item["errors"] for item in results),
        "document_status_counts": aggregate_status,
        "block_type_counts": aggregate_types,
        "issues": issues,
        "failed": failed,
        "results": sorted(results, key=lambda item: item["notice_id"]),
    }
    _write_json_atomic(args.output_dir.parent / "parse_report.json", report)
    # Keep conda's Windows stdout relay safe even when paths contain Chinese.
    # The persisted JSON remains ensure_ascii=False and therefore human-readable.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
