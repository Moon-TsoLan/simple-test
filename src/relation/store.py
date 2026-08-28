"""SQLite authority store and precomputation for task 2."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator

from .normalization import normalize_org_name, stable_id
from .schema import OrganizationInput, ProjectRelationInput


SCHEMA_SQL = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organizations (
  org_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_norm TEXT NOT NULL UNIQUE,
  org_type TEXT NOT NULL DEFAULT '未知', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS org_aliases (
  alias_norm TEXT PRIMARY KEY, alias_name TEXT NOT NULL, org_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'approved', evidence TEXT,
  FOREIGN KEY(org_id) REFERENCES organizations(org_id)
);
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY, notice_id TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
  project_no TEXT, procurement_method TEXT, publish_date TEXT, source_url TEXT,
  extraction_method TEXT, warnings_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_units (
  project_id TEXT NOT NULL, org_id TEXT NOT NULL, role TEXT NOT NULL,
  PRIMARY KEY(project_id, org_id, role),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
  FOREIGN KEY(org_id) REFERENCES organizations(org_id)
);
CREATE TABLE IF NOT EXISTS packages (
  package_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, package_no TEXT NOT NULL, name TEXT,
  UNIQUE(project_id, package_no),
  FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS bids (
  bid_id TEXT PRIMARY KEY, package_id TEXT NOT NULL, org_id TEXT NOT NULL,
  amount_yuan REAL, quote_value REAL, quote_unit TEXT, quote_text TEXT,
  score REAL, rank INTEGER, qualification TEXT NOT NULL,
  compliance TEXT NOT NULL, result TEXT NOT NULL, evidence_block_id TEXT,
  evidence_block_row INTEGER, evidence_json TEXT NOT NULL DEFAULT '[]', UNIQUE(package_id, org_id),
  FOREIGN KEY(package_id) REFERENCES packages(package_id) ON DELETE CASCADE,
  FOREIGN KEY(org_id) REFERENCES organizations(org_id)
);
CREATE TABLE IF NOT EXISTS products (
  product_id TEXT PRIMARY KEY, name TEXT NOT NULL, category_code TEXT, brand TEXT,
  spec_model TEXT, supplier_org_id TEXT,
  FOREIGN KEY(supplier_org_id) REFERENCES organizations(org_id)
);
CREATE TABLE IF NOT EXISTS package_products (
  package_id TEXT NOT NULL, product_id TEXT NOT NULL,
  PRIMARY KEY(package_id, product_id),
  FOREIGN KEY(package_id) REFERENCES packages(package_id) ON DELETE CASCADE,
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
CREATE TABLE IF NOT EXISTS alias_review_queue (
  review_id TEXT PRIMARY KEY, left_org_id TEXT NOT NULL, right_org_id TEXT NOT NULL,
  similarity REAL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS unit_win_stats (
  unit_id TEXT NOT NULL, supplier_id TEXT NOT NULL, win_count INTEGER NOT NULL,
  total_amount_yuan REAL NOT NULL, last_date TEXT,
  PRIMARY KEY(unit_id, supplier_id)
);
CREATE TABLE IF NOT EXISTS unit_bidder_stats (
  unit_id TEXT NOT NULL, bidder_id TEXT NOT NULL, bid_count INTEGER NOT NULL,
  win_count INTEGER NOT NULL, total_win_amount_yuan REAL NOT NULL,
  PRIMARY KEY(unit_id, bidder_id)
);
CREATE TABLE IF NOT EXISTS unit_cobid_pairs (
  unit_id TEXT NOT NULL, bidder_a TEXT NOT NULL, bidder_b TEXT NOT NULL,
  project_count INTEGER NOT NULL, PRIMARY KEY(unit_id, bidder_a, bidder_b)
);
CREATE TABLE IF NOT EXISTS supplier_cobid (
  supplier_id TEXT NOT NULL, cobidder_id TEXT NOT NULL, project_count INTEGER NOT NULL,
  PRIMARY KEY(supplier_id, cobidder_id)
);
CREATE TABLE IF NOT EXISTS supplier_common_units (
  supplier_a TEXT NOT NULL, supplier_b TEXT NOT NULL, unit_id TEXT NOT NULL,
  joint_win_count INTEGER NOT NULL, total_amount_yuan REAL NOT NULL,
  PRIMARY KEY(supplier_a, supplier_b, unit_id)
);
CREATE TABLE IF NOT EXISTS supplier_joint_projects (
  supplier_a TEXT NOT NULL, supplier_b TEXT NOT NULL, project_id TEXT NOT NULL,
  package_id TEXT NOT NULL, total_amount_yuan REAL NOT NULL,
  PRIMARY KEY(supplier_a, supplier_b, package_id)
);
CREATE INDEX IF NOT EXISTS idx_projects_notice ON projects(notice_id);
CREATE INDEX IF NOT EXISTS idx_project_units_org_role ON project_units(org_id, role, project_id);
CREATE INDEX IF NOT EXISTS idx_packages_project ON packages(project_id);
CREATE INDEX IF NOT EXISTS idx_bids_org_result ON bids(org_id, result, package_id);
CREATE INDEX IF NOT EXISTS idx_bids_package ON bids(package_id, org_id);
"""

ALIAS_REVIEW_THRESHOLD = 0.88


class RelationStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
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
            connection.executescript(SCHEMA_SQL)
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(bids)")}
            for name, definition in (
                ("quote_value", "REAL"),
                ("quote_unit", "TEXT"),
                ("quote_text", "TEXT"),
                ("evidence_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE bids ADD COLUMN {name} {definition}")

    def _ensure_org(self, connection: sqlite3.Connection, value: OrganizationInput) -> str:
        norm = normalize_org_name(value.name)
        if not norm:
            raise ValueError("organization name is empty after normalization")
        row = connection.execute(
            "SELECT o.org_id,o.org_type FROM organizations o LEFT JOIN org_aliases a ON a.org_id=o.org_id WHERE o.name_norm=? OR a.alias_norm=? LIMIT 1",
            (norm, norm),
        ).fetchone()
        if row:
            priority = {"未知": 0, "投标参与方": 1, "产品供应商": 2, "代理机构": 2, "采购单位": 3, "中标供应商": 4}
            if priority.get(value.org_type, 0) > priority.get(str(row["org_type"]), 0):
                connection.execute("UPDATE organizations SET org_type=? WHERE org_id=?", (value.org_type, row["org_id"]))
            return str(row["org_id"])
        org_id = stable_id("org", norm)
        connection.execute(
            "INSERT INTO organizations(org_id,name,name_norm,org_type) VALUES(?,?,?,?)",
            (org_id, value.name, norm, value.org_type),
        )
        if len(norm) >= 4:
            for candidate in connection.execute(
                "SELECT org_id,name,name_norm FROM organizations WHERE org_id<>?", (org_id,),
            ):
                similarity = SequenceMatcher(None, norm, str(candidate["name_norm"])).ratio()
                if ALIAS_REVIEW_THRESHOLD <= similarity < 1:
                    left_id, right_id = sorted((org_id, str(candidate["org_id"])))
                    review_id = stable_id("alias", left_id, right_id)
                    connection.execute(
                        "INSERT OR IGNORE INTO alias_review_queue(review_id,left_org_id,right_org_id,similarity,reason) VALUES(?,?,?,?,?)",
                        (review_id, left_id, right_id, similarity, "名称高度相似，需人工确认；系统未自动合并"),
                    )
        return org_id

    def ingest(self, project: ProjectRelationInput, *, refresh: bool = True) -> str:
        project_id = stable_id("prj", project.notice_id)
        with self.connect() as connection:
            old = connection.execute("SELECT project_id FROM projects WHERE notice_id=?", (project.notice_id,)).fetchone()
            if old:
                connection.execute("DELETE FROM projects WHERE project_id=?", (old["project_id"],))
            connection.execute(
                "INSERT INTO projects(project_id,notice_id,title,project_no,procurement_method,publish_date,source_url,extraction_method,warnings_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (project_id, project.notice_id, project.title, project.project_no, project.procurement_method,
                 project.publish_date, project.source_url, project.extraction_method,
                 json.dumps(project.warnings, ensure_ascii=False)),
            )
            for value, role in ((project.procurement_unit, "采购单位"), (project.agency, "代理机构")):
                if value:
                    org_id = self._ensure_org(connection, value)
                    connection.execute("INSERT INTO project_units(project_id,org_id,role) VALUES(?,?,?)", (project_id, org_id, role))
            for package in project.packages:
                package_id = stable_id("pkg", project_id, package.package_no)
                connection.execute(
                    "INSERT INTO packages(package_id,project_id,package_no,name) VALUES(?,?,?,?)",
                    (package_id, project_id, package.package_no, package.name),
                )
                for bid in package.bidders:
                    org_id = self._ensure_org(connection, bid.org)
                    bid_id = stable_id("bid", package_id, org_id)
                    evidence_refs = [value.model_dump(mode="json") for value in bid.evidence_refs]
                    if not evidence_refs and bid.evidence_block_id:
                        evidence_refs = [{"block_id": bid.evidence_block_id, "block_row": bid.evidence_block_row, "supports": []}]
                    connection.execute(
                        "INSERT INTO bids(bid_id,package_id,org_id,amount_yuan,quote_value,quote_unit,quote_text,score,rank,qualification,compliance,result,evidence_block_id,evidence_block_row,evidence_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bid_id, package_id, org_id, bid.amount_yuan, bid.quote_value, bid.quote_unit, bid.quote_text,
                         bid.score, bid.rank, bid.qualification, bid.compliance, bid.result,
                         bid.evidence_block_id, bid.evidence_block_row, json.dumps(evidence_refs, ensure_ascii=False)),
                    )
                for product in package.products:
                    supplier_id = self._ensure_org(connection, product.supplier) if product.supplier else None
                    product_id = stable_id("prd", product.name, product.category_code, product.brand, product.spec_model, supplier_id)
                    connection.execute(
                        "INSERT OR IGNORE INTO products(product_id,name,category_code,brand,spec_model,supplier_org_id) VALUES(?,?,?,?,?,?)",
                        (product_id, product.name, product.category_code, product.brand, product.spec_model, supplier_id),
                    )
                    connection.execute("INSERT OR IGNORE INTO package_products(package_id,product_id) VALUES(?,?)", (package_id, product_id))
            connection.execute(
                "DELETE FROM products WHERE NOT EXISTS (SELECT 1 FROM package_products pp WHERE pp.product_id=products.product_id)"
            )
        if refresh:
            self.refresh_aggregates()
        return project_id

    def refresh_aggregates(self) -> None:
        with self.connect() as connection:
            for table in ("unit_win_stats", "unit_bidder_stats", "unit_cobid_pairs", "supplier_cobid", "supplier_common_units", "supplier_joint_projects"):
                connection.execute(f"DELETE FROM {table}")
            connection.execute("""
                INSERT INTO unit_win_stats
                SELECT pu.org_id,b.org_id,COUNT(DISTINCT p.package_id),COALESCE(SUM(b.amount_yuan),0),MAX(pr.publish_date)
                FROM project_units pu JOIN packages p ON p.project_id=pu.project_id
                JOIN projects pr ON pr.project_id=p.project_id JOIN bids b ON b.package_id=p.package_id
                WHERE pu.role='采购单位' AND b.result IN ('中标','成交') GROUP BY pu.org_id,b.org_id
            """)
            connection.execute("""
                INSERT INTO unit_bidder_stats
                SELECT pu.org_id,b.org_id,COUNT(DISTINCT p.package_id),
                       SUM(CASE WHEN b.result IN ('中标','成交') THEN 1 ELSE 0 END),
                       COALESCE(SUM(CASE WHEN b.result IN ('中标','成交') THEN b.amount_yuan ELSE 0 END),0)
                FROM project_units pu JOIN packages p ON p.project_id=pu.project_id JOIN bids b ON b.package_id=p.package_id
                WHERE pu.role='采购单位' GROUP BY pu.org_id,b.org_id
            """)
            connection.execute("""
                INSERT INTO unit_cobid_pairs
                SELECT pu.org_id,CASE WHEN a.org_id<c.org_id THEN a.org_id ELSE c.org_id END,
                       CASE WHEN a.org_id<c.org_id THEN c.org_id ELSE a.org_id END,COUNT(DISTINCT p.project_id)
                FROM project_units pu JOIN packages p ON p.project_id=pu.project_id
                JOIN bids a ON a.package_id=p.package_id JOIN bids c ON c.package_id=p.package_id AND a.org_id<c.org_id
                WHERE pu.role='采购单位' GROUP BY pu.org_id,2,3
            """)
            connection.execute("""
                INSERT INTO supplier_cobid
                SELECT w.org_id,c.org_id,COUNT(DISTINCT p.project_id)
                FROM packages p JOIN bids w ON w.package_id=p.package_id AND w.result IN ('中标','成交')
                JOIN bids c ON c.package_id=p.package_id AND c.org_id<>w.org_id GROUP BY w.org_id,c.org_id
            """)
            connection.execute("""
                INSERT INTO supplier_common_units
                WITH supplier_unit AS (
                  SELECT pu.org_id AS unit_id,b.org_id AS supplier_id,
                         COUNT(DISTINCT p.package_id) AS win_count,
                         COALESCE(SUM(b.amount_yuan),0) AS total_amount_yuan
                  FROM project_units pu
                  JOIN packages p ON p.project_id=pu.project_id
                  JOIN bids b ON b.package_id=p.package_id AND b.result IN ('中标','成交')
                  WHERE pu.role='采购单位'
                  GROUP BY pu.org_id,b.org_id
                )
                SELECT a.supplier_id,b.supplier_id,a.unit_id,
                       a.win_count+b.win_count,a.total_amount_yuan+b.total_amount_yuan
                FROM supplier_unit a
                JOIN supplier_unit b ON b.unit_id=a.unit_id AND a.supplier_id<b.supplier_id
            """)
            connection.execute("""
                INSERT INTO supplier_joint_projects
                SELECT CASE WHEN a.org_id<b.org_id THEN a.org_id ELSE b.org_id END,
                       CASE WHEN a.org_id<b.org_id THEN b.org_id ELSE a.org_id END,p.project_id,p.package_id,
                       COALESCE(a.amount_yuan,0)+COALESCE(b.amount_yuan,0)
                FROM packages p JOIN bids a ON a.package_id=p.package_id
                JOIN bids b ON b.package_id=p.package_id AND a.org_id<b.org_id
            """)

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("projects", "packages", "organizations", "bids", "products")
            }
