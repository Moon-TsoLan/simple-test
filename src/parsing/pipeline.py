"""Secure recursive parsing pipeline for one notice and all its attachments."""

from __future__ import annotations

import os
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .extractors import (
    OCRBackend,
    convert_legacy_office,
    parse_docx,
    parse_html,
    parse_image,
    parse_json_or_text,
    parse_pdf,
    parse_xls,
    parse_xlsx,
)
from .schema import Block, DocumentRecord, PARSER_VERSION, SCHEMA_VERSION
from .utils import detect_file_type, safe_archive_name, sha256_file


@dataclass(frozen=True)
class ParserConfig:
    ocr: str = "auto"
    max_archive_depth: int = 3
    max_archive_files: int = 5000
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_zip_ratio: int = 300
    pdf_scan_text_threshold: int = 50
    pdf_table_text_overlap_threshold: float = 0.5
    pdf_filter_native_watermarks: bool = True
    max_ocr_pages_per_pdf: int = 20
    skip_ocr_if_scan_pages_over: int = 0
    min_embedded_image_pixels: int = 40_000
    legacy_office_backend: str = "libreoffice"


def parser_config_digest(config: ParserConfig) -> str:
    """Return a reproducible digest of every output-affecting parser option."""

    canonical = json.dumps(asdict(config), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_MULTIPART_RAR = re.compile(r"^(?P<prefix>.+)\.part(?P<number>\d+)\.rar$", re.IGNORECASE)


def group_archive_payloads(files: list[Path], root: Path) -> list[tuple[Path, str]]:
    """Return parseable archive payloads, collapsing each multipart RAR to its first volume."""

    ordinary: list[tuple[Path, str]] = []
    groups: dict[tuple[str, str], list[tuple[int, Path, str]]] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        match = _MULTIPART_RAR.match(path.name)
        if not match:
            ordinary.append((path, relative))
            continue
        parent = path.parent.relative_to(root).as_posix().lower()
        key = (parent, match.group("prefix").lower())
        groups.setdefault(key, []).append((int(match.group("number")), path, relative))

    for volumes in groups.values():
        _, path, relative = min(volumes, key=lambda item: (item[0], item[2].lower()))
        ordinary.append((path, relative))
    return sorted(ordinary, key=lambda item: item[1].lower())


class NoticeParser:
    """Parse an HTML notice plus its optional attachment archive into blocks."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig()
        self.ocr = OCRBackend(self.config.ocr)
        self._blocks: list[Block] = []
        self._documents: list[DocumentRecord] = []

    def parse_notice(
        self,
        notice_id: str,
        html_path: Path | str,
        attachment_path: Path | str | None = None,
        *,
        title: str | None = None,
        notice_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._blocks = []
        self._documents = []
        html_path = Path(html_path)
        attachment = Path(attachment_path) if attachment_path else None

        # A third-party Office/OCR process can briefly retain a Windows handle.
        # A cleanup race must not turn a fully parsed notice into a batch failure.
        with tempfile.TemporaryDirectory(
            prefix=f"notice_{notice_id}_", ignore_cleanup_errors=True
        ) as temporary:
            temp_dir = Path(temporary)
            self._parse_file(html_path, container_path=html_path.name, temp_dir=temp_dir, depth=0)
            if attachment and attachment.exists():
                self._parse_file(
                    attachment,
                    container_path=attachment.name,
                    temp_dir=temp_dir,
                    depth=0,
                )
            elif attachment:
                self._add_error(
                    attachment,
                    attachment.name,
                    "attachment_archive_missing",
                    f"Attachment archive does not exist: {attachment}",
                )

        self._assign_stable_block_ids(notice_id)

        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for document in self._documents:
            status_counts[document.status] = status_counts.get(document.status, 0) + 1
        for block in self._blocks:
            type_counts[block.type] = type_counts.get(block.type, 0) + 1

        return {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "parser_config_digest": parser_config_digest(self.config),
            "parser_config": asdict(self.config),
            "notice_id": notice_id,
            "title": title or self._infer_title(),
            "notice_metadata": notice_metadata or {},
            "documents": [document.to_dict() for document in self._documents],
            "blocks": [block.to_dict() for block in self._blocks],
            "stats": {
                "document_count": len(self._documents),
                "block_count": len(self._blocks),
                "document_status_counts": status_counts,
                "block_type_counts": type_counts,
                "ocr_backend": self.ocr.name,
            },
        }

    def _assign_stable_block_ids(self, notice_id: str) -> None:
        """Assign content-addressed IDs independent of document traversal order.

        Sequential source coordinates such as ``document_id``, ``table_index``
        and ``paragraph_index`` are deliberately excluded.  Page/Sheet/row
        coordinates and the actual content remain part of the identity.
        """

        used: dict[str, int] = {}
        excluded_source_keys = {"document_id", "paragraph_index", "table_index"}
        for block in self._blocks:
            stable_source = {
                key: value
                for key, value in block.source.items()
                if key not in excluded_source_keys
            }
            identity = {
                "notice_id": notice_id,
                "type": block.type,
                "source": stable_source,
                "text": block.text,
                "rows": block.rows,
            }
            canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
            base = f"{notice_id}:blk_{digest}"
            occurrence = used.get(base, 0) + 1
            used[base] = occurrence
            block.block_id = base if occurrence == 1 else f"{base}_{occurrence:02d}"

    def _infer_title(self) -> str:
        for block in self._blocks:
            if block.type == "heading" and block.text:
                return block.text
        return ""

    def _source_factory(self, document: DocumentRecord):
        def build(**location: Any) -> dict[str, Any]:
            source: dict[str, Any] = {
                "document_id": document.document_id,
                "file_name": document.file_name,
                "container_path": document.container_path,
                "file_type": document.file_type,
            }
            source.update({key: value for key, value in location.items() if value is not None})
            return source

        return build

    def _new_document(self, path: Path, container_path: str, file_type: str, media_type: str) -> DocumentRecord:
        digest = sha256_file(path)
        document = DocumentRecord(
            document_id=f"f{len(self._documents) + 1:04d}_{digest[:12]}",
            file_name=path.name,
            container_path=container_path.replace("\\", "/"),
            file_type=file_type,
            media_type=media_type,
            size_bytes=path.stat().st_size,
            sha256=digest,
        )
        self._documents.append(document)
        return document

    def _parse_file(
        self,
        path: Path,
        *,
        container_path: str,
        temp_dir: Path,
        depth: int,
    ) -> None:
        file_type, media_type = detect_file_type(path)
        document = self._new_document(path, container_path, file_type, media_type)
        source = self._source_factory(document)
        before = len(self._blocks)
        try:
            if file_type == "html":
                blocks, warnings = parse_html(path, source)
            elif file_type == "docx":
                blocks, warnings = parse_docx(
                    path,
                    source,
                    self.ocr,
                    temp_dir,
                    min_embedded_image_pixels=self.config.min_embedded_image_pixels,
                )
            elif file_type == "xlsx":
                blocks, warnings = parse_xlsx(path, source)
            elif file_type == "xls":
                converted, backend, conversion_error = convert_legacy_office(
                    path, temp_dir, "xlsx", self.config.legacy_office_backend
                )
                if converted:
                    blocks, warnings = parse_xlsx(converted, source)
                    document.metadata["conversion_backend"] = backend
                else:
                    blocks, warnings = parse_xls(path, source)
                    if conversion_error:
                        warnings.append(f"legacy_xls_conversion_skipped:{conversion_error}")
            elif file_type == "doc":
                converted, backend, conversion_error = convert_legacy_office(
                    path, temp_dir, "docx", self.config.legacy_office_backend
                )
                if converted:
                    blocks, warnings = parse_docx(
                        converted,
                        source,
                        self.ocr,
                        temp_dir,
                        min_embedded_image_pixels=self.config.min_embedded_image_pixels,
                    )
                    document.metadata["conversion_backend"] = backend
                else:
                    raise RuntimeError(
                        "legacy DOC needs LibreOffice or Microsoft Office conversion; "
                        "binary text fallback is disabled because it is not label-quality. "
                        f"Converter detail: {conversion_error}"
                    )
            elif file_type == "pdf":
                blocks, warnings = parse_pdf(
                    path,
                    source,
                    self.ocr,
                    temp_dir,
                    scan_text_threshold=self.config.pdf_scan_text_threshold,
                    table_text_overlap_threshold=self.config.pdf_table_text_overlap_threshold,
                    max_ocr_pages=self.config.max_ocr_pages_per_pdf,
                    skip_ocr_if_scan_pages_over=self.config.skip_ocr_if_scan_pages_over,
                    filter_native_watermarks=self.config.pdf_filter_native_watermarks,
                )
            elif file_type in {"jpg", "png", "tiff"}:
                blocks, warnings = parse_image(path, source, self.ocr)
            elif file_type in {"json", "txt"}:
                blocks, warnings = parse_json_or_text(path, source, file_type)
            elif file_type == "zip":
                blocks, warnings = [], []
                self._extract_zip(path, container_path, temp_dir, depth)
            elif file_type == "rar":
                blocks, warnings = [], []
                self._extract_rar(path, container_path, temp_dir, depth)
            else:
                blocks, warnings = [], [f"unsupported_file_type:{file_type}"]
                document.status = "unsupported"

            self._blocks.extend(blocks)
            document.warnings.extend(warnings)
            if document.status == "ok" and warnings:
                document.status = "partial"
        except Exception as exc:
            document.status = "error"
            message = f"{type(exc).__name__}: {exc}"
            document.warnings.append(message)
            self._blocks.append(
                Block(
                    type="error",
                    text="",
                    source=source(),
                    metadata={"error_code": "parse_failed", "message": message, "recoverable": True},
                )
            )
        document.block_count = len(self._blocks) - before

    def _extract_zip(self, path: Path, container_path: str, temp_dir: Path, depth: int) -> None:
        if depth >= self.config.max_archive_depth:
            raise ValueError(f"archive nesting exceeds {self.config.max_archive_depth}")
        extract_root = temp_dir / f"zip_{len(self._documents):04d}"
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if len(members) > self.config.max_archive_files:
                raise ValueError(f"archive has too many files: {len(members)}")
            total = sum(info.file_size for info in members)
            if total > self.config.max_uncompressed_bytes:
                raise ValueError(f"archive expands to {total} bytes, above configured limit")
            extracted_files: list[Path] = []
            for info in members:
                safe_name = safe_archive_name(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"archive symlink is not allowed: {info.filename}")
                if info.flag_bits & 0x1:
                    self._add_error(path, f"{container_path}/{safe_name}", "encrypted_archive_member", safe_name)
                    continue
                if info.compress_size and info.file_size / info.compress_size > self.config.max_zip_ratio:
                    self._add_error(path, f"{container_path}/{safe_name}", "suspicious_compression_ratio", safe_name)
                    continue
                destination = extract_root.joinpath(*safe_name.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source_handle, destination.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                extracted_files.append(destination)
            self._parse_extracted_files(extracted_files, extract_root, container_path, temp_dir, depth)

    def _parse_extracted_files(
        self,
        files: list[Path],
        extract_root: Path,
        container_path: str,
        temp_dir: Path,
        depth: int,
    ) -> None:
        for candidate, relative in group_archive_payloads(files, extract_root):
            self._parse_file(
                candidate,
                container_path=f"{container_path}/{relative}",
                temp_dir=temp_dir,
                depth=depth + 1,
            )

    def _extract_rar(self, path: Path, container_path: str, temp_dir: Path, depth: int) -> None:
        if depth >= self.config.max_archive_depth:
            raise ValueError(f"archive nesting exceeds {self.config.max_archive_depth}")
        known_7z = [
            Path(__file__).resolve().parents[2] / "third_party" / "7zip" / "7z.exe",
            Path(r"C:\Program Files\7-Zip\7z.exe"),
            Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
            Path(r"C:\Program Files\NVIDIA Corporation\NVIDIA GeForce Experience\7z.exe"),
        ]
        executable = shutil.which("7z") or next((str(item) for item in known_7z if item.exists()), None)
        executable = executable or shutil.which("tar")
        if not executable:
            raise RuntimeError("RAR extraction needs 7z or bsdtar")
        is_7z = Path(executable).stem.lower() == "7z"
        list_command = [executable, "l", "-slt", str(path)] if is_7z else [executable, "-tf", str(path)]
        process_encoding = "gb18030" if os.name == "nt" else "utf-8"
        listed = subprocess.run(
            list_command,
            capture_output=True,
            text=True,
            encoding=process_encoding,
            errors="ignore",
            timeout=60,
            check=False,
        )
        if listed.returncode != 0:
            raise RuntimeError(f"RAR listing failed: {listed.stderr.strip() or listed.stdout.strip()}")
        if is_7z:
            records: list[dict[str, str]] = []
            current: dict[str, str] = {}
            in_members = False
            for raw_line in listed.stdout.splitlines():
                line = raw_line.strip()
                if line == "----------":
                    in_members = True
                    continue
                if not in_members:
                    continue
                if not line:
                    if current:
                        records.append(current)
                        current = {}
                    continue
                if " = " in line:
                    key, value = line.split(" = ", 1)
                    current[key] = value
            if current:
                records.append(current)
            file_records = [record for record in records if record.get("Folder") != "+"]
            if any(record.get("Encrypted") == "+" for record in file_records):
                raise ValueError("encrypted RAR members are not supported")
            if any(record.get("Symbolic Link") or record.get("Hard Link") for record in file_records):
                raise ValueError("RAR links are not allowed")
            listed_size = sum(int(record.get("Size", "0") or 0) for record in file_records)
            if listed_size > self.config.max_uncompressed_bytes:
                raise ValueError(f"RAR expands to {listed_size} bytes, above configured limit")
            for record in file_records:
                size = int(record.get("Size", "0") or 0)
                packed = int(record.get("Packed Size", "0") or 0)
                if packed and size / packed > self.config.max_zip_ratio:
                    raise ValueError(f"suspicious RAR compression ratio: {record.get('Path', '')}")
            names = [record["Path"] for record in file_records if record.get("Path")]
        else:
            names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        names = [safe_archive_name(name) for name in names]
        if len(names) > self.config.max_archive_files:
            raise ValueError(f"RAR has too many files: {len(names)}")

        extract_root = temp_dir / f"rar_{len(self._documents):04d}"
        extract_root.mkdir(parents=True, exist_ok=True)
        command = (
            [executable, "x", "-y", f"-o{extract_root}", str(path)]
            if is_7z
            else [executable, "-xf", str(path), "-C", str(extract_root)]
        )
        extracted = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=process_encoding,
            errors="ignore",
            timeout=180,
            check=False,
        )
        if extracted.returncode != 0:
            raise RuntimeError(f"RAR extraction failed: {extracted.stderr.strip() or extracted.stdout.strip()}")
        files = [candidate for candidate in extract_root.rglob("*") if candidate.is_file() and not candidate.is_symlink()]
        total = sum(candidate.stat().st_size for candidate in files)
        if total > self.config.max_uncompressed_bytes:
            raise ValueError(f"RAR expands to {total} bytes, above configured limit")
        self._parse_extracted_files(files, extract_root, container_path, temp_dir, depth)

    def _add_error(self, path: Path, container_path: str, error_code: str, message: str) -> None:
        file_type, media_type = detect_file_type(path)
        document = DocumentRecord(
            document_id=f"f{len(self._documents) + 1:04d}_error",
            file_name=Path(container_path).name,
            container_path=container_path.replace("\\", "/"),
            file_type=file_type,
            media_type=media_type,
            size_bytes=path.stat().st_size if path.exists() else 0,
            sha256=sha256_file(path) if path.exists() else "",
            status="error",
            block_count=1,
            warnings=[message],
        )
        self._documents.append(document)
        self._blocks.append(
            Block(
                type="error",
                text="",
                source=self._source_factory(document)(),
                metadata={"error_code": error_code, "message": message, "recoverable": True},
            )
        )
