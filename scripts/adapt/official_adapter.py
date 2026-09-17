# -*- coding: utf-8 -*-
"""Map an official (or fake-official) dump onto notices/ + attachments/.

Layouts:
- split_dir: html/zip live in two directories with the same stem
- paired: html and zip sit in the same directory with the same stem
- per_folder: each notice is a folder containing one html and one zip
- auto: try the three in that order
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crawl.packaging import pair_is_usable, write_json  # noqa: E402

HTML_SUFFIXES = {".html", ".htm"}
ZIP_SUFFIXES = {".zip"}


@dataclass(frozen=True)
class Pair:
    notice_id: str
    html: Path
    zip_path: Path
    source_dir: str


def _stem_id(path: Path) -> str:
    return path.stem


def _stable_id(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return "id_" + hashlib.sha256(payload).hexdigest()[:16]


def detect_layout(root: Path) -> str:
    split = _detect_split_dir(root)
    if split:
        return "split_dir"
    paired = _detect_paired(root)
    if paired:
        return "paired"
    folders = _detect_per_folder(root)
    if folders:
        return "per_folder"
    raise ValueError(f"cannot detect html+zip layout under {root}")


def _split_candidates(root: Path) -> list[tuple[Path, Path]]:
    named = {path.name.lower(): path for path in root.iterdir() if path.is_dir()}
    html_dirs = [named[key] for key in ("notices", "html", "htm") if key in named]
    zip_dirs = [named[key] for key in ("attachments", "zips", "zip", "attach") if key in named]
    pairs = []
    if html_dirs and zip_dirs:
        pairs.append((html_dirs[0], zip_dirs[0]))
    children = [path for path in root.iterdir() if path.is_dir()]
    if len(children) == 2:
        left, right = sorted(children, key=lambda item: item.name.lower())
        left_html = any(p.suffix.lower() in HTML_SUFFIXES for p in left.glob("*"))
        right_zip = any(p.suffix.lower() in ZIP_SUFFIXES for p in right.glob("*"))
        left_zip = any(p.suffix.lower() in ZIP_SUFFIXES for p in left.glob("*"))
        right_html = any(p.suffix.lower() in HTML_SUFFIXES for p in right.glob("*"))
        if left_html and right_zip:
            pairs.append((left, right))
        elif left_zip and right_html:
            pairs.append((right, left))
    return pairs


def _detect_split_dir(root: Path) -> list[Pair]:
    for html_dir, zip_dir in _split_candidates(root):
        html_map = {_stem_id(path): path for path in html_dir.glob("*") if path.suffix.lower() in HTML_SUFFIXES}
        zip_map = {_stem_id(path): path for path in zip_dir.glob("*") if path.suffix.lower() in ZIP_SUFFIXES}
        common = sorted(set(html_map) & set(zip_map))
        if common:
            return [
                Pair(notice_id=stem, html=html_map[stem], zip_path=zip_map[stem], source_dir=str(html_dir))
                for stem in common
            ]
    return []


def _detect_paired(root: Path) -> list[Pair]:
    found: list[Pair] = []
    for directory in [root, *sorted(path for path in root.iterdir() if path.is_dir())]:
        html_map = {_stem_id(path): path for path in directory.glob("*") if path.suffix.lower() in HTML_SUFFIXES}
        zip_map = {_stem_id(path): path for path in directory.glob("*") if path.suffix.lower() in ZIP_SUFFIXES}
        common = sorted(set(html_map) & set(zip_map))
        for stem in common:
            found.append(Pair(stem, html_map[stem], zip_map[stem], str(directory)))
        if found and directory == root:
            break
    # de-duplicate by notice_id keeping first
    uniq: dict[str, Pair] = {}
    for item in found:
        uniq.setdefault(item.notice_id, item)
    return list(uniq.values())


def _detect_per_folder(root: Path) -> list[Pair]:
    found: list[Pair] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        htmls = [path for path in directory.glob("*") if path.suffix.lower() in HTML_SUFFIXES]
        zips = [path for path in directory.glob("*") if path.suffix.lower() in ZIP_SUFFIXES]
        if len(htmls) == 1 and len(zips) == 1:
            notice_id = directory.name if directory.name != htmls[0].stem else htmls[0].stem
            found.append(Pair(notice_id, htmls[0], zips[0], str(directory)))
    return found


def collect_pairs(root: Path, layout: str) -> list[Pair]:
    if layout == "auto":
        layout = detect_layout(root)
    detectors = {
        "split_dir": _detect_split_dir,
        "paired": _detect_paired,
        "per_folder": _detect_per_folder,
    }
    if layout not in detectors:
        raise ValueError(f"unknown layout: {layout}")
    pairs = detectors[layout](root)
    if not pairs:
        raise ValueError(f"no html+zip pairs found with layout={layout} under {root}")
    return pairs


def adapt_official_dataset(
    source: Path,
    output: Path,
    *,
    layout: str = "auto",
    overwrite: bool = False,
) -> dict:
    source = source.resolve()
    output = output.resolve()
    pairs = collect_pairs(source, layout)
    notices_dir = output / "notices"
    attachments_dir = output / "attachments"
    notices_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)

    records = []
    id_map = []
    used_ids: set[str] = set()
    skipped = 0
    for pair in pairs:
        notice_id = pair.notice_id
        if notice_id in used_ids:
            notice_id = _stable_id(pair.notice_id, str(pair.html), str(pair.zip_path))
        used_ids.add(notice_id)
        html_dst = notices_dir / f"{notice_id}.html"
        zip_dst = attachments_dir / f"{notice_id}.zip"
        if html_dst.exists() or zip_dst.exists():
            if not overwrite:
                skipped += 1
                continue
        shutil.copy2(pair.html, html_dst)
        shutil.copy2(pair.zip_path, zip_dst)
        ok, reason, meta = pair_is_usable(html_dst, zip_dst)
        if not ok:
            html_dst.unlink(missing_ok=True)
            zip_dst.unlink(missing_ok=True)
            skipped += 1
            id_map.append({
                "notice_id": notice_id,
                "source_html": str(pair.html),
                "source_zip": str(pair.zip_path),
                "status": "rejected",
                "reason": reason,
            })
            continue
        records.append({
            "notice_id": notice_id,
            "url": "",
            "source_type": "",
            "source_key": "",
            "title": meta.get("title") or "",
            "publish_time": "",
            "html_sha256": meta["html_sha256"],
            "zip_sha256": meta["zip_sha256"],
            "attachment_names": [Path(name).name for name in meta["attachment_names"]],
            "byte_sizes": {"html": meta["html_bytes"], "zip": meta["zip_bytes"], "attachments": []},
        })
        id_map.append({
            "notice_id": notice_id,
            "source_html": str(pair.html),
            "source_zip": str(pair.zip_path),
            "status": "ok",
            "reason": "ok",
        })

    manifest = {
        "version": 1,
        "layout": layout if layout != "auto" else detect_layout(source),
        "source": str(source),
        "notice_count": len(records),
        "notices": {item["notice_id"]: item for item in records},
    }
    write_json(output / "manifest.json", manifest)
    csv_path = output / "id_map.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["notice_id", "source_html", "source_zip", "status", "reason"])
        writer.writeheader()
        writer.writerows(id_map)
    return {
        "output": str(output),
        "copied": len(records),
        "skipped": skipped,
        "layout": manifest["layout"],
        "manifest": str(output / "manifest.json"),
        "id_map": str(csv_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="官方压缩包解压根目录，或已是 notices+attachments 的目录")
    parser.add_argument("--output", type=Path, required=True, help="输出根目录，将写入 notices/ 与 attachments/")
    parser.add_argument("--layout", choices=("auto", "paired", "split_dir", "per_folder"), default="auto")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = adapt_official_dataset(args.source, args.output, layout=args.layout, overwrite=args.overwrite)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["copied"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
