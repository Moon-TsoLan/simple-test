"""Text, table, file-identification, and archive-safety helpers."""

from __future__ import annotations

import hashlib
import html
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


WHITESPACE_RE = re.compile(r"[\t\x0b\x0c\r ]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalise_text(value: Any, *, preserve_lines: bool = True) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\u00a0", " ").replace("\u3000", " ")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    if not preserve_lines:
        return " ".join(part for part in lines if part).strip()
    return BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def trim_table(rows: Iterable[Iterable[Any]]) -> list[list[str]]:
    clean = [[normalise_text(cell) for cell in row] for row in rows]
    while clean and not any(clean[-1]):
        clean.pop()
    while clean and not any(clean[0]):
        clean.pop(0)
    if not clean:
        return []
    last_nonempty = max((i for row in clean for i, value in enumerate(row) if value), default=-1)
    if last_nonempty < 0:
        return []
    return [row[: last_nonempty + 1] + [""] * max(0, last_nonempty + 1 - len(row)) for row in clean]


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def esc(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    output = ["| " + " | ".join(esc(v) for v in padded[0]) + " |"]
    output.append("| " + " | ".join("---" for _ in range(width)) + " |")
    output.extend("| " + " | ".join(esc(v) for v in row) + " |" for row in padded[1:])
    return "\n".join(output)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_file_type(path: Path) -> tuple[str, str]:
    """Return (logical type, MIME), prioritising signatures over suffixes."""

    suffix = path.suffix.lower().lstrip(".")
    try:
        with path.open("rb") as handle:
            head = handle.read(8192)
    except OSError:
        head = b""

    if head.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff", "image/tiff"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar", "application/vnd.rar"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            if "word/document.xml" in names:
                return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if "xl/workbook.xml" in names:
                return "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        except (OSError, zipfile.BadZipFile):
            pass
        return "zip", "application/zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        if suffix in {"xls", "xlt"}:
            return "xls", "application/vnd.ms-excel"
        return "doc", "application/msword"

    lowered = head.lower().lstrip()
    if suffix in {"html", "htm"} or any(tag in lowered[:1024] for tag in (b"<!doctype html", b"<html", b"<body")):
        return "html", "text/html"
    suffix_types = {
        "doc": ("doc", "application/msword"),
        "docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "xls": ("xls", "application/vnd.ms-excel"),
        "xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "pdf": ("pdf", "application/pdf"),
        "jpg": ("jpg", "image/jpeg"),
        "jpeg": ("jpg", "image/jpeg"),
        "png": ("png", "image/png"),
        "tif": ("tiff", "image/tiff"),
        "tiff": ("tiff", "image/tiff"),
        "rar": ("rar", "application/vnd.rar"),
        "zip": ("zip", "application/zip"),
        "json": ("json", "application/json"),
        "txt": ("txt", "text/plain"),
    }
    return suffix_types.get(suffix, (suffix or "binary", "application/octet-stream"))


def safe_archive_name(name: str) -> str:
    """Validate and normalise a member path, rejecting traversal and absolutes."""

    normal = name.replace("\\", "/")
    path = PurePosixPath(normal)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe archive path: {name!r}")
    if path.parts and re.match(r"^[A-Za-z]:$", path.parts[0]):
        raise ValueError(f"absolute archive path: {name!r}")
    return str(path)


def decode_bytes(raw: bytes) -> str:
    """Decode Chinese web/text content without turning a missing detector into a failure."""

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    for encoding in ("utf-8-sig", "gb18030", "big5", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")
