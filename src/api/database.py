"""Application SQLite store for jobs and task-1 entities."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.relation.normalization import stable_id


APP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task1_entities (
  entity_id TEXT PRIMARY KEY, notice_id TEXT NOT NULL, title TEXT NOT NULL,
  item_no INTEGER, product_service_name TEXT, category_name TEXT, category_code TEXT,
  brand_supplier TEXT, spec_model TEXT, unit_price REAL, quantity REAL,
  quantity_unit TEXT, total_price REAL, source_file TEXT, source_block_id TEXT,
  source_block_row INTEGER, evidence_json TEXT NOT NULL, raw_json TEXT NOT NULL,
  search_text TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task1_notice ON task1_entities(notice_id,item_no);
CREATE INDEX IF NOT EXISTS idx_task1_product ON task1_entities(product_service_name);
CREATE INDEX IF NOT EXISTS idx_task1_brand ON task1_entities(brand_supplier);
CREATE INDEX IF NOT EXISTS idx_task1_category ON task1_entities(category_code,category_name);
CREATE INDEX IF NOT EXISTS idx_task1_source ON task1_entities(source_file);
CREATE TABLE IF NOT EXISTS processing_jobs (
  job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
  stage TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, file_count INTEGER NOT NULL DEFAULT 0,
  success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0,
  message TEXT, errors_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS job_files (
  job_id TEXT NOT NULL, file_name TEXT NOT NULL, stored_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'staged', error TEXT,
  PRIMARY KEY(job_id,file_name), FOREIGN KEY(job_id) REFERENCES processing_jobs(job_id) ON DELETE CASCADE
);
"""


class ApplicationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(APP_SCHEMA_SQL)

    def import_task1_notice(self, notice: dict[str, Any]) -> int:
        notice_id = str(notice.get("notice_id") or "")
        title = str(notice.get("title") or notice_id)
        if not notice_id:
            return 0
        with self.connect() as connection:
            connection.execute("DELETE FROM task1_entities WHERE notice_id=?", (notice_id,))
            count = 0
            for index, item in enumerate(notice.get("items") or [], 1):
                item_no = int(item.get("item_no") or index)
                entity_id = stable_id("ent", notice_id, item_no, item.get("source_block_id"), item.get("source_block_row"))
                fields = [
                    title, item.get("product_service_name"), item.get("category_name"), item.get("category_code"),
                    item.get("brand_supplier"), item.get("spec_model"), item.get("source_file"),
                ]
                evidence = item.get("evidence_refs") or []
                connection.execute("""
                    INSERT INTO task1_entities(entity_id,notice_id,title,item_no,product_service_name,category_name,
                      category_code,brand_supplier,spec_model,unit_price,quantity,quantity_unit,total_price,
                      source_file,source_block_id,source_block_row,evidence_json,raw_json,search_text)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    entity_id, notice_id, title, item_no, item.get("product_service_name"), item.get("category_name"),
                    item.get("category_code"), item.get("brand_supplier"), item.get("spec_model"), item.get("unit_price"),
                    item.get("quantity"), item.get("quantity_unit"), item.get("total_price"), item.get("source_file"),
                    item.get("source_block_id"), item.get("source_block_row"),
                    json.dumps(evidence, ensure_ascii=False), json.dumps(item, ensure_ascii=False),
                    " ".join(str(value or "") for value in fields),
                ))
                count += 1
        return count

    def import_task1_directory(self, notice_dir: Path) -> dict[str, int]:
        notices = entities = failures = 0
        for path in sorted(notice_dir.glob("*.json")):
            try:
                entities += self.import_task1_notice(json.loads(path.read_text(encoding="utf-8")))
                notices += 1
            except Exception:
                failures += 1
        return {"notices": notices, "entities": entities, "failures": failures}

    def search_task1(
        self, *, q: str = "", notice_id: str = "", product: str = "", brand: str = "",
        category: str = "", source_file: str = "", page: int = 1, page_size: int = 20,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("search_text", q), ("notice_id", notice_id), ("product_service_name", product),
            ("brand_supplier", brand), ("category_name || ' ' || COALESCE(category_code,'')", category),
            ("source_file", source_file),
        ):
            if value:
                clauses.append(f"COALESCE({column},'') LIKE ?")
                values.append(f"%{value}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        with self.connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM task1_entities{where}", values).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM task1_entities{where} ORDER BY notice_id,item_no LIMIT ? OFFSET ?",
                (*values, page_size, (page - 1) * page_size),
            ).fetchall()
        return {"total": total, "page": page, "page_size": page_size, "items": [self._entity_row(row) for row in rows]}

    def export_task1(
        self, *, q: str = "", notice_id: str = "", product: str = "", brand: str = "",
        category: str = "", source_file: str = "",
    ) -> list[dict[str, Any]]:
        """Return every matching entity for an explicit export operation.

        Interactive searches stay capped at 100 rows per page.  Exports use a
        separate query so a large result set is never silently truncated.
        """
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("search_text", q), ("notice_id", notice_id), ("product_service_name", product),
            ("brand_supplier", brand), ("category_name || ' ' || COALESCE(category_code,'')", category),
            ("source_file", source_file),
        ):
            if value:
                clauses.append(f"COALESCE({column},'') LIKE ?")
                values.append(f"%{value}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM task1_entities{where} ORDER BY notice_id,item_no", values,
            ).fetchall()
        return [self._entity_row(row) for row in rows]

    @staticmethod
    def _entity_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["evidence_refs"] = json.loads(value.pop("evidence_json"))
        value.pop("raw_json", None)
        value.pop("search_text", None)
        return value

    def get_task1(self, entity_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM task1_entities WHERE entity_id=?", (entity_id,)).fetchone()
        return self._entity_row(row) if row else None

    def task1_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) entities,COUNT(DISTINCT notice_id) notices FROM task1_entities").fetchone()
            return {"entities": int(row["entities"]), "notices": int(row["notices"])}

    def create_job(self, job_id: str, kind: str, file_count: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO processing_jobs(job_id,kind,status,stage,progress,file_count,message) VALUES(?,?, 'queued','upload',0,?,?)",
                (job_id, kind, file_count, "文件已接收，等待流水线"),
            )

    def add_job_file(self, job_id: str, file_name: str, stored_path: str) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO job_files(job_id,file_name,stored_path) VALUES(?,?,?)", (job_id, file_name, stored_path))

    def update_job_file(self, job_id: str, file_name: str, *, status: str, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE job_files SET status=?,error=? WHERE job_id=? AND file_name=?",
                (status, error, job_id, file_name),
            )

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "stage", "progress", "success_count", "failure_count", "message", "errors_json"}
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        assignments = ",".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE processing_jobs SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (*values.values(), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM processing_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["errors"] = json.loads(result.pop("errors_json"))
            result["files"] = [dict(value) for value in connection.execute("SELECT file_name,status,error FROM job_files WHERE job_id=? ORDER BY file_name", (job_id,))]
            return result

    def recent_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM processing_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        output = []
        for row in rows:
            value = dict(row)
            value["errors"] = json.loads(value.pop("errors_json"))
            output.append(value)
        return output
