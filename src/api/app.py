"""FastAPI application factory for the local single-port platform."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook

from src.relation.queries import RelationQueries
from src.relation.extractor import RelationCandidateExtractor
from src.relation.schema import ProjectRelationInput
from src.relation.store import RelationStore

from .database import ApplicationStore
from .jobs import finalize_staged_job, safe_file_name


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "run" / "data" / "application.db"
DEFAULT_UPLOAD = ROOT / "run" / "uploads"
DEFAULT_BLOCK_DIR = ROOT / "dataset_build" / "blocks" / "notices"
MAX_UPLOAD_FILE_BYTES = 200 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 500 * 1024 * 1024


def _parse_ids(ids: str) -> list[str]:
    return [value.strip() for value in ids.split(",") if value.strip()]


@lru_cache(maxsize=128)
def _load_block_notice(block_dir: str, notice_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", notice_id):
        return {}
    path = Path(block_dir) / f"{notice_id}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _evidence_excerpt(item: dict, block_dir: Path) -> str | None:
    payload = _load_block_notice(str(block_dir.resolve()), str(item.get("notice_id") or ""))
    block_id = item.get("source_block_id")
    block = next((value for value in payload.get("blocks") or [] if value.get("block_id") == block_id), None)
    if not block:
        return None
    row_number = item.get("source_block_row")
    rows = block.get("rows") or []
    if isinstance(row_number, int) and 1 <= row_number <= len(rows):
        return " ｜ ".join(str(cell or "") for cell in rows[row_number - 1])
    text_value = str(block.get("text") or "").strip()
    return text_value[:4000] or None


def create_app(
    db_path: Path | str = DEFAULT_DB, *, frontend_dist: Path | None = None,
    upload_dir: Path = DEFAULT_UPLOAD, block_dir: Path = DEFAULT_BLOCK_DIR,
) -> FastAPI:
    app_store = ApplicationStore(db_path)
    relation_store = RelationStore(db_path)
    queries = RelationQueries(relation_store)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="招采标讯分析平台", version="0.1.0")
    app.state.app_store = app_store
    app.state.relation_store = relation_store
    app.state.relation_queries = queries
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "database": str(Path(db_path).name), "model_status": "not_configured"}

    @app.get("/api/status")
    def status() -> dict:
        return {
            "task1": app_store.task1_counts(),
            "task2": relation_store.counts(),
            "jobs": app_store.recent_jobs(),
            "model": {"status": "not_configured", "message": "本地模型仍在准备中"},
        }

    @app.post("/api/admin/import-task1")
    def import_task1(path: str | None = None) -> dict:
        notice_dir = Path(path) if path else ROOT / "dataset_build" / "agent_results" / "notices"
        if not notice_dir.is_dir():
            raise HTTPException(404, "task1 notice directory not found")
        return app_store.import_task1_directory(notice_dir)

    @app.get("/api/task1/items")
    def task1_items(
        q: str = "", notice_id: str = "", product: str = "", brand: str = "",
        category: str = "", source_file: str = "", page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return app_store.search_task1(
            q=q, notice_id=notice_id, product=product, brand=brand, category=category,
            source_file=source_file, page=page, page_size=page_size,
        )

    @app.get("/api/task1/items/{entity_id}")
    def task1_detail(entity_id: str) -> dict:
        item = app_store.get_task1(entity_id)
        if item is None:
            raise HTTPException(404, "entity not found")
        item["evidence_excerpt"] = _evidence_excerpt(item, block_dir)
        return item

    def export_rows(q: str, notice_id: str, product: str, brand: str, category: str) -> list[dict]:
        return app_store.export_task1(q=q, notice_id=notice_id, product=product, brand=brand, category=category)

    @app.get("/api/task1/export.csv")
    def task1_export_csv(q: str = "", notice_id: str = "", product: str = "", brand: str = "", category: str = "") -> StreamingResponse:
        rows = export_rows(q, notice_id, product, brand, category)
        buffer = io.StringIO()
        fields = ["notice_id", "title", "product_service_name", "category_name", "category_code", "brand_supplier", "spec_model", "unit_price", "quantity", "quantity_unit", "total_price", "source_file"]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
        content = "\ufeff" + buffer.getvalue()
        return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=task1_entities.csv"})

    @app.get("/api/task1/export.xlsx")
    def task1_export_xlsx(q: str = "", notice_id: str = "", product: str = "", brand: str = "", category: str = "") -> StreamingResponse:
        rows = export_rows(q, notice_id, product, brand, category)
        fields = ["notice_id", "title", "product_service_name", "category_name", "category_code", "brand_supplier", "spec_model", "unit_price", "quantity", "quantity_unit", "total_price", "source_file"]
        workbook = Workbook(); sheet = workbook.active; sheet.title = "实体"
        sheet.append(fields)
        for row in rows: sheet.append([row.get(field) for field in fields])
        payload = io.BytesIO(); workbook.save(payload); payload.seek(0)
        return StreamingResponse(payload, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=task1_entities.xlsx"})

    @app.post("/api/task2/projects")
    def ingest_project(project: ProjectRelationInput) -> dict:
        project_id = relation_store.ingest(project)
        return {"project_id": project_id, "counts": relation_store.counts()}

    @app.get("/api/task2/projects")
    def projects(q: str = "", limit: int = Query(50, ge=1, le=5000)) -> list[dict]:
        return queries.projects(q, limit)

    @app.post("/api/task2/extract-candidate")
    def extract_relation_candidate(block_notice: dict) -> dict:
        """Run the deterministic candidate layer without contacting a model."""
        try:
            return RelationCandidateExtractor().extract(block_notice).model_dump(mode="json")
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"invalid Block notice: {exc}") from exc

    @app.get("/api/task2/organizations")
    def organizations(q: str = "", limit: int = Query(50, ge=1, le=5000)) -> list[dict]:
        return queries.organizations(q, limit)

    @app.get("/api/task2/aliases/review")
    def alias_review_queue(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
        return queries.alias_review_queue(limit)

    @app.get("/api/task2/units/{unit_id}/win-suppliers")
    def unit_win_suppliers(unit_id: str) -> list[dict]: return queries.unit_win_suppliers(unit_id)

    @app.get("/api/task2/units/{unit_id}/top-bidders")
    def unit_top_bidders(unit_id: str, top: int = Query(5, ge=1, le=100)) -> list[dict]: return queries.unit_top_bidders(unit_id, top)

    @app.get("/api/task2/units/{unit_id}/co-bid-pairs")
    def unit_cobid_pairs(unit_id: str) -> list[dict]: return queries.unit_cobid_pairs(unit_id)

    @app.get("/api/task2/suppliers/{supplier_id}/co-bidders")
    def supplier_cobidders(supplier_id: str, top: int = Query(5, ge=1, le=100)) -> list[dict]: return queries.supplier_cobidders(supplier_id, top)

    @app.get("/api/task2/suppliers/common-units")
    def common_units(ids: str) -> list[dict]: return queries.common_units(_parse_ids(ids))

    @app.get("/api/task2/suppliers/joint-projects")
    def joint_projects(ids: str) -> list[dict]: return queries.joint_projects(_parse_ids(ids))

    @app.get("/api/task2/graph/subgraph")
    def subgraph(project_id: str) -> dict: return queries.project_subgraph(project_id)

    @app.post("/api/jobs/upload")
    async def upload_job(
        background_tasks: BackgroundTasks,
        kind: Annotated[str, Form(pattern="^(task1|task2)$")],
        files: Annotated[list[UploadFile], File()],
    ) -> dict:
        if not files:
            raise HTTPException(400, "no files")
        normalized_names: list[str] = []
        for upload in files:
            try:
                normalized_names.append(safe_file_name(upload.filename or ""))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if len(set(normalized_names)) != len(normalized_names):
            raise HTTPException(400, "duplicate file names after normalization")

        job_id = uuid.uuid4().hex
        job_dir = upload_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        app_store.create_job(job_id, kind, len(files))
        stored: list[Path] = []
        total_size = 0
        for upload, name in zip(files, normalized_names, strict=True):
            target = job_dir / name
            file_size = 0
            with target.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    file_size += len(chunk)
                    total_size += len(chunk)
                    if file_size > MAX_UPLOAD_FILE_BYTES:
                        raise HTTPException(413, f"file too large: {name}")
                    if total_size > MAX_UPLOAD_TOTAL_BYTES:
                        raise HTTPException(413, "upload batch is too large")
                    output.write(chunk)
            await upload.close()
            app_store.add_job_file(job_id, name, str(target))
            stored.append(target)
        background_tasks.add_task(finalize_staged_job, app_store, job_id, stored)
        return app_store.get_job(job_id) or {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str) -> dict:
        job = app_store.get_job(job_id)
        if job is None: raise HTTPException(404, "job not found")
        return job

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str, background_tasks: BackgroundTasks) -> dict:
        job = app_store.get_job(job_id)
        if job is None: raise HTTPException(404, "job not found")
        with app_store.connect() as connection:
            paths = [Path(row[0]) for row in connection.execute("SELECT stored_path FROM job_files WHERE job_id=?", (job_id,))]
        app_store.update_job(job_id, status="queued", stage="retry", progress=0, message="已进入重试队列")
        background_tasks.add_task(finalize_staged_job, app_store, job_id, paths)
        return app_store.get_job(job_id) or {}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        async def stream():
            previous = None
            for _ in range(300):
                job = app_store.get_job(job_id)
                if job is None:
                    yield "event: error\ndata: {\"error\":\"not found\"}\n\n"; return
                payload = json.dumps(job, ensure_ascii=False)
                if payload != previous:
                    yield f"data: {payload}\n\n"; previous = payload
                if job["status"] in {"staged", "failed", "completed"}: return
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream")

    dist = frontend_dist or ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app(
    Path(os.environ.get("APP_DB_PATH", DEFAULT_DB)),
    block_dir=Path(os.environ.get("APP_BLOCK_DIR", DEFAULT_BLOCK_DIR)),
)
