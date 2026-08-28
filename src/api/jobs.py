"""Lightweight upload staging and resumable job state."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from .database import ApplicationStore


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")
ALLOWED_SUFFIXES = {".html", ".htm", ".zip", ".json", ".jsonl"}


def safe_file_name(value: str) -> str:
    name = Path(value).name
    cleaned = SAFE_NAME_RE.sub("_", name).strip("._")
    if not cleaned:
        raise ValueError("empty file name")
    return cleaned[:240]


def finalize_staged_job(store: ApplicationStore, job_id: str, files: Iterable[Path]) -> None:
    errors = []
    success = 0
    store.update_job(job_id, status="running", stage="validate", progress=0.4, message="正在校验上传文件")
    for path in files:
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            error = "unsupported suffix"
            errors.append({"file": path.name, "error": error})
            store.update_job_file(job_id, path.name, status="failed", error=error)
        elif not path.exists() or path.stat().st_size == 0:
            error = "empty or missing file"
            errors.append({"file": path.name, "error": error})
            store.update_job_file(job_id, path.name, status="failed", error=error)
        else:
            success += 1
            store.update_job_file(job_id, path.name, status="ready", error=None)
    status = "staged" if success else "failed"
    message = "文件已暂存；模型与完整流水线就绪后可继续处理" if success else "没有可处理文件"
    store.update_job(
        job_id, status=status, stage="ready_for_pipeline", progress=1.0,
        success_count=success, failure_count=len(errors), message=message,
        errors_json=json.dumps(errors, ensure_ascii=False),
    )
