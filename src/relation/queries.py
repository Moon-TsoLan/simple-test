"""Five task-2 business scenarios and graph projection."""
from __future__ import annotations

from typing import Any

from .normalization import normalize_org_name
from .store import RelationStore


def _rows(cursor: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


class RelationQueries:
    def __init__(self, store: RelationStore):
        self.store = store

    def organizations(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        normalized = normalize_org_name(query)
        with self.store.connect() as connection:
            return _rows(connection.execute(
                "SELECT org_id,name,org_type FROM organizations WHERE name LIKE ? OR name_norm LIKE ? ORDER BY name LIMIT ?",
                (f"%{query}%", f"%{normalized}%", max(1, min(limit, 200))),
            ))

    def projects(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute(
                "SELECT project_id,notice_id,title,project_no,publish_date FROM projects "
                "WHERE title LIKE ? OR notice_id LIKE ? OR COALESCE(project_no,'') LIKE ? "
                "ORDER BY COALESCE(publish_date,'') DESC,title LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", max(1, min(limit, 200))),
            ))

    def alias_review_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute("""
                SELECT q.review_id,q.similarity,q.status,q.reason,
                       q.left_org_id,l.name AS left_name,q.right_org_id,r.name AS right_name
                FROM alias_review_queue q
                JOIN organizations l ON l.org_id=q.left_org_id
                JOIN organizations r ON r.org_id=q.right_org_id
                WHERE q.status='pending' ORDER BY q.similarity DESC,q.created_at LIMIT ?
            """, (max(1, min(limit, 500)),)))

    def unit_win_suppliers(self, unit_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute("""
                SELECT s.supplier_id,o.name AS supplier_name,s.win_count,s.total_amount_yuan,s.last_date
                FROM unit_win_stats s JOIN organizations o ON o.org_id=s.supplier_id
                WHERE s.unit_id=? ORDER BY s.win_count DESC,s.total_amount_yuan DESC
            """, (unit_id,)))

    def unit_top_bidders(self, unit_id: str, top: int = 5) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute("""
                SELECT s.bidder_id,o.name AS bidder_name,s.bid_count,s.win_count,s.total_win_amount_yuan
                FROM unit_bidder_stats s JOIN organizations o ON o.org_id=s.bidder_id
                WHERE s.unit_id=? ORDER BY s.bid_count DESC,s.win_count DESC LIMIT ?
            """, (unit_id, max(1, min(top, 100)))))

    def unit_cobid_pairs(self, unit_id: str) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute("""
                SELECT p.bidder_a,a.name AS bidder_a_name,p.bidder_b,b.name AS bidder_b_name,p.project_count
                FROM unit_cobid_pairs p JOIN organizations a ON a.org_id=p.bidder_a
                JOIN organizations b ON b.org_id=p.bidder_b WHERE p.unit_id=? ORDER BY p.project_count DESC
            """, (unit_id,)))

    def supplier_cobidders(self, supplier_id: str, top: int = 5) -> list[dict[str, Any]]:
        with self.store.connect() as connection:
            return _rows(connection.execute("""
                SELECT s.cobidder_id,o.name AS cobidder_name,s.project_count
                FROM supplier_cobid s JOIN organizations o ON o.org_id=s.cobidder_id
                WHERE s.supplier_id=? ORDER BY s.project_count DESC LIMIT ?
            """, (supplier_id, max(1, min(top, 100)))))

    def common_units(self, supplier_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(supplier_ids))
        if len(ids) < 2:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT pu.org_id AS unit_id,o.name AS unit_name,COUNT(DISTINCT b.org_id) AS matched_suppliers,
                   COUNT(DISTINCT p.project_id) AS project_count,
                   COALESCE(SUM(CASE WHEN b.result IN ('中标','成交') THEN b.amount_yuan ELSE 0 END),0) AS total_amount_yuan
            FROM project_units pu JOIN organizations o ON o.org_id=pu.org_id
            JOIN packages p ON p.project_id=pu.project_id JOIN bids b ON b.package_id=p.package_id
            WHERE pu.role='采购单位' AND b.result IN ('中标','成交') AND b.org_id IN ({placeholders})
            GROUP BY pu.org_id,o.name HAVING COUNT(DISTINCT b.org_id)=? ORDER BY project_count DESC
        """
        with self.store.connect() as connection:
            return _rows(connection.execute(sql, (*ids, len(ids))))

    def joint_projects(self, supplier_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(supplier_ids))
        if len(ids) < 2:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"""
            SELECT pr.project_id,pr.notice_id,pr.title,p.package_id,p.package_no,
                   COUNT(DISTINCT b.org_id) AS matched_suppliers,
                   COALESCE(SUM(b.amount_yuan),0) AS participant_amount_yuan,
                   GROUP_CONCAT(DISTINCT b.result) AS results
            FROM projects pr JOIN packages p ON p.project_id=pr.project_id JOIN bids b ON b.package_id=p.package_id
            WHERE b.org_id IN ({placeholders}) GROUP BY p.package_id
            HAVING COUNT(DISTINCT b.org_id)=? ORDER BY pr.publish_date DESC,pr.title
        """
        with self.store.connect() as connection:
            return _rows(connection.execute(sql, (*ids, len(ids))))

    def project_subgraph(self, project_id: str) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        with self.store.connect() as connection:
            project = connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
            if project is None:
                return {"nodes": [], "edges": []}
            nodes[project_id] = {"id": project_id, "name": project["title"], "type": "项目"}
            for row in connection.execute("""
                SELECT pu.org_id,o.name,pu.role FROM project_units pu JOIN organizations o ON o.org_id=pu.org_id
                WHERE pu.project_id=?
            """, (project_id,)):
                nodes[row["org_id"]] = {"id": row["org_id"], "name": row["name"], "type": row["role"]}
                edges.append({"source": project_id, "target": row["org_id"], "type": row["role"]})
            for package in connection.execute("SELECT * FROM packages WHERE project_id=?", (project_id,)):
                package_id = package["package_id"]
                nodes[package_id] = {"id": package_id, "name": package["name"] or package["package_no"], "type": "包件"}
                edges.append({"source": project_id, "target": package_id, "type": "包含包件"})
                for row in connection.execute("""
                    SELECT b.org_id,o.name,b.result,b.amount_yuan,b.quote_value,b.quote_unit,b.quote_text,b.score,b.rank
                    FROM bids b JOIN organizations o ON o.org_id=b.org_id
                    WHERE b.package_id=?
                """, (package_id,)):
                    node_type = "中标供应商" if row["result"] in {"中标", "成交"} else "投标参与方"
                    nodes[row["org_id"]] = {"id": row["org_id"], "name": row["name"], "type": node_type}
                    edges.append({
                        "source": row["org_id"], "target": package_id, "type": row["result"],
                        "amount_yuan": row["amount_yuan"], "quote_value": row["quote_value"],
                        "quote_unit": row["quote_unit"], "quote_text": row["quote_text"],
                        "score": row["score"], "rank": row["rank"],
                    })
                for row in connection.execute("""
                    SELECT pr.* FROM package_products pp JOIN products pr ON pr.product_id=pp.product_id WHERE pp.package_id=?
                """, (package_id,)):
                    nodes[row["product_id"]] = {"id": row["product_id"], "name": row["name"], "type": "产品"}
                    edges.append({"source": package_id, "target": row["product_id"], "type": "包含产品"})
                    if row["supplier_org_id"]:
                        supplier = connection.execute(
                            "SELECT org_id,name FROM organizations WHERE org_id=?", (row["supplier_org_id"],),
                        ).fetchone()
                        if supplier:
                            nodes[supplier["org_id"]] = {
                                "id": supplier["org_id"], "name": supplier["name"], "type": "产品供应商",
                            }
                            edges.append({"source": supplier["org_id"], "target": row["product_id"], "type": "供应"})
        return {"nodes": list(nodes.values()), "edges": edges}
