"""Controlled task-2 relation extraction agent.

The agent deliberately separates deterministic candidate discovery from model
decisions.  With no backend configured it returns an auditable candidate and
never writes it as a confirmed relation result.  A local OpenAI-compatible
server can later be attached without changing the storage or API contracts.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError

from src.agents.backends import BackendResponse, ExtractionBackend

from .extractor import RelationCandidateExtractor
from .schema import ProjectRelationInput


RELATION_AGENT_VERSION = "1.4.0"
RELATION_OUTPUT_SCHEMA = ProjectRelationInput.model_json_schema()
RELATION_KEYWORDS = (
    "采购人", "采购单位", "代理机构", "项目编号", "采购编号", "招标编号", "采购方式",
    "供应商", "投标人", "中标", "成交", "候选", "报价", "得分", "排名",
    "资格审查", "符合性审查", "响应性审查", "包号", "标段",
)
RELATION_EXCLUDED_SOURCE_TOKENS = (
    "招标文件", "采购文件", "磋商文件", "谈判文件", "询价文件",
    "采购需求", "需求书", "评分办法", "资格预审文件",
)
RELATION_LOW_VALUE_SOURCE_TOKENS = (
    "中小企业声明", "本国产品", "授权委托", "资格声明", "承诺函",
)
RELATION_RESULT_SOURCE_TOKENS = ("评审情况", "采购结果", "中标", "成交", "结果公告", "结果公示")
RELATION_STRONG_TEXT_TOKENS = (
    "供应商名称", "投标人名称", "中标供应商", "成交供应商",
    "中标（成交）金额", "评审总得分", "评审结果", "第一中标候选人", "第一成交候选人",
)
RELATION_BLANK_TEMPLATE_TEXT_TOKENS = (
    "xxxxxx供应商", "由供应商填写", "投标人名称：____________",
    "投标人名称:____________",
)

SYSTEM_PROMPT = """你是政府采购结果公告的关系抽取助手。请只根据 evidence 输出一个符合 JSON Schema 的项目关系对象。

必须遵守：
1. 只抽取实际采购结果及真实参与投标的主体；采购需求、模板、预算和评分办法不是竞标结果。
2. 未出现的字段填 null 或保留“未知”，不得猜测机构、金额、得分、排名和审查结果。
3. 中标/成交只能由原文结果或明确排名证据支持，不得仅因报价最低自动判断。
4. 金额统一为元，万元乘以 10000。
5. 同一主体在同一包件只输出一次；联合体成员有独立证据时可分别输出。
6. evidence_block_id 必须来自 evidence 的真实 block_id；表格行号为 1 起始。
7. 只输出 JSON 对象，不要输出解释或 Markdown。

必须使用以下字段骨架；禁止输出 address、contact、package_id、package_name、winner、other_bidders、row 等额外字段：
{"notice_id":"...","title":"...","project_no":null,"procurement_method":null,"publish_date":null,"source_url":null,"procurement_unit":{"name":"...","org_type":"采购单位"},"agency":{"name":"...","org_type":"代理机构"},"packages":[{"package_no":"默认包","name":null,"bidders":[{"org":{"name":"...","org_type":"投标参与方"},"amount_yuan":null,"quote_value":null,"quote_unit":null,"quote_text":null,"score":null,"rank":null,"qualification":"未知","compliance":"未知","result":"未知","evidence_block_id":"...","evidence_block_row":null,"evidence_refs":[{"block_id":"...","block_row":null,"supports":[]}]}],"products":[]}],"extraction_method":"model","warnings":[]}
"""


@dataclass(frozen=True)
class RelationAgentConfig:
    max_evidence_chars: int = 24000
    max_blocks: int = 40
    max_repair_attempts: int = 1
    large_table_bypass_bidders: int = 80


def _compact_block(block: dict[str, Any], remaining: int) -> tuple[dict[str, Any] | None, int]:
    block_id = str(block.get("block_id") or "")
    if not block_id or remaining <= 0:
        return None, remaining
    value: dict[str, Any] = {
        "block_id": block_id,
        "type": block.get("type"),
        "source": block.get("source") or {},
    }
    if block.get("type") == "table" and block.get("rows"):
        rows: list[list[str]] = []
        used = 0
        for row in block.get("rows") or []:
            normalized = [str(cell or "") for cell in row]
            cost = len(json.dumps(normalized, ensure_ascii=False))
            if rows and used + cost > remaining:
                break
            rows.append(normalized)
            used += cost
        value["rows"] = rows
        value["text"] = str(block.get("text") or "")[: max(0, remaining - used)]
        used += len(value["text"])
    else:
        value["text"] = str(block.get("text") or "")[:remaining]
        used = len(value["text"])
    return value, max(0, remaining - used)


def select_relation_evidence(payload: dict[str, Any], config: RelationAgentConfig) -> list[dict[str, Any]]:
    """Select relation-bearing Blocks deterministically and within a hard budget."""
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, block in enumerate(payload.get("blocks") or []):
        text = str(block.get("text") or "")
        source = block.get("source") or {}
        source_text = f"{source.get('file_name', '')} {source.get('container_path', '')}"
        # Procurement documents contain dense repetitions of relation words in
        # instructions and scoring rules.  They previously exhausted the hard
        # character budget before the actual HTML result table was reached.
        if any(token in source_text for token in RELATION_EXCLUDED_SOURCE_TOKENS):
            continue
        if any(token in source_text for token in RELATION_LOW_VALUE_SOURCE_TOKENS):
            continue
        if any(token in text for token in RELATION_BLANK_TEMPLATE_TEXT_TOKENS):
            continue
        score = sum(1 for keyword in RELATION_KEYWORDS if keyword in text)
        if block.get("type") == "table":
            score += 3
        if str(source.get("file_type") or "").lower() == "html":
            score += 8
        if any(token in source_text for token in RELATION_RESULT_SOURCE_TOKENS):
            score += 8
        score += 3 * sum(1 for token in RELATION_STRONG_TEXT_TOKENS if token in text)
        if score:
            ranked.append((score, -index, block))
    ranked.sort(reverse=True, key=lambda value: (value[0], value[1]))
    selected: list[dict[str, Any]] = []
    remaining = config.max_evidence_chars
    for _score, _index, block in ranked[: config.max_blocks]:
        compact, remaining = _compact_block(block, remaining)
        if compact:
            selected.append(compact)
        if remaining <= 0:
            break
    return selected


def _organization(value: Any, default_type: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"name": value, "org_type": default_type}
    if not isinstance(value, dict):
        return None
    name = value.get("name") or value.get("org_name") or value.get("supplier_name") or value.get("company_name")
    if not name:
        return None
    org_type = value.get("org_type") or default_type
    if org_type not in {"采购单位", "代理机构", "中标供应商", "投标参与方", "产品供应商", "未知"}:
        org_type = default_type
    return {"name": str(name), "org_type": org_type}


def _review_state(value: Any) -> str:
    text = str(value or "未知")
    if any(token in text for token in ("不通过", "不合格", "否决", "无效")):
        return "不通过"
    if any(token in text for token in ("通过", "合格", "有效")):
        return "通过"
    return "未知"


def _bid_result(value: Any, *, winner: bool = False) -> str:
    if winner:
        return "中标"
    text = str(value or "未知")
    if "成交" in text:
        return "成交"
    if "未中标" in text or "未成交" in text or "落标" in text:
        return "未中标"
    if "中标" in text:
        return "中标"
    if "候选" in text:
        return "候选"
    return "未知"


def _normalize_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    block_id = value.get("block_id") or value.get("evidence_block_id")
    if not block_id:
        return None
    block_row = value.get("block_row", value.get("row"))
    return {
        "block_id": str(block_id),
        "block_row": block_row,
        "supports": list(value.get("supports") or []),
    }


def _normalize_bid(value: Any, *, winner: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    org_value = (
        value.get("org") or value.get("organization") or value.get("supplier")
        or value.get("bidder") or value.get("company")
    )
    if org_value is None and any(key in value for key in ("name", "org_name", "supplier_name", "company_name")):
        org_value = value
    org = _organization(org_value, "中标供应商" if winner else "投标参与方")
    if org is None:
        return None
    refs = [ref for raw in value.get("evidence_refs") or [] if (ref := _normalize_ref(raw))]
    return {
        "org": org,
        "amount_yuan": value.get("amount_yuan", value.get("amount")),
        "quote_value": value.get("quote_value"),
        "quote_unit": value.get("quote_unit"),
        "quote_text": value.get("quote_text"),
        "score": value.get("score"),
        "rank": value.get("rank"),
        "qualification": _review_state(value.get("qualification")),
        "compliance": _review_state(value.get("compliance")),
        "result": _bid_result(value.get("result") or value.get("outcome"), winner=winner),
        "evidence_block_id": value.get("evidence_block_id"),
        "evidence_block_row": value.get("evidence_block_row", value.get("row")),
        "evidence_refs": refs,
    }


def _normalize_model_shape(value: dict[str, Any]) -> dict[str, Any]:
    packages: list[dict[str, Any]] = []
    for raw_package in value.get("packages") or []:
        if not isinstance(raw_package, dict):
            continue
        bidders: list[dict[str, Any]] = []
        winner = _normalize_bid(raw_package.get("winner"), winner=True)
        if winner:
            bidders.append(winner)
        for raw_bid in [
            *(raw_package.get("bidders") or []),
            *(raw_package.get("other_bidders") or []),
        ]:
            bid = _normalize_bid(raw_bid)
            if bid and not any(existing["org"]["name"] == bid["org"]["name"] for existing in bidders):
                bidders.append(bid)
        packages.append({
            "package_no": str(raw_package.get("package_no") or raw_package.get("package_id") or "默认包"),
            "name": raw_package.get("name", raw_package.get("package_name")),
            "bidders": bidders,
            "products": list(raw_package.get("products") or []),
        })
    return {
        "notice_id": value.get("notice_id"),
        "title": value.get("title"),
        "project_no": value.get("project_no"),
        "procurement_method": value.get("procurement_method"),
        "publish_date": value.get("publish_date"),
        "source_url": value.get("source_url"),
        "procurement_unit": _organization(value.get("procurement_unit"), "采购单位"),
        "agency": _organization(value.get("agency"), "代理机构"),
        "packages": packages,
        "extraction_method": str(value.get("extraction_method") or "model"),
        "warnings": list(value.get("warnings") or []),
    }


def _match_text(value: Any) -> str:
    """Normalize names for deterministic recovery of model-provided row refs."""
    return re.sub(r"[\W_]", "", unicodedata.normalize("NFKC", str(value or "")), flags=re.UNICODE).lower()


def _recover_bid_row(block: dict[str, Any], org_name: str) -> int | None:
    """Return the unique 1-based row containing the bidder name, if any."""
    needle = _match_text(org_name)
    if len(needle) < 2:
        return None
    matches: list[int] = []
    for row_index, row in enumerate(block.get("rows") or [], 1):
        for cell in row:
            candidate = _match_text(cell)
            if candidate and (candidate == needle or (len(needle) >= 4 and needle in candidate)):
                matches.append(row_index)
                break
    return matches[0] if len(matches) == 1 else None


def _validate_model_output(value: Any, *, notice_id: str, evidence: list[dict[str, Any]]) -> tuple[ProjectRelationInput | None, list[str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            return None, [f"invalid JSON: {exc}"]
    if isinstance(value, dict):
        value = _normalize_model_shape(value)
    try:
        project = ProjectRelationInput.model_validate(value)
    except ValidationError as exc:
        return None, [f"schema error: {error['loc']}: {error['msg']}" for error in exc.errors()]
    errors: list[str] = []
    if project.notice_id != notice_id:
        errors.append("notice_id differs from input")
    evidence_by_id = {str(block["block_id"]): block for block in evidence}
    rows_by_block = {block_id: len(block.get("rows") or []) for block_id, block in evidence_by_id.items()}
    normalized_rows = 0
    for package_index, package in enumerate(project.packages):
        for bid_index, bid in enumerate(package.bidders):
            if bid.evidence_block_id in rows_by_block:
                row_count = rows_by_block[bid.evidence_block_id]
                if row_count == 0:
                    if bid.evidence_block_row is not None:
                        normalized_rows += 1
                    bid.evidence_block_row = None
                elif bid.evidence_block_row is not None and not 1 <= bid.evidence_block_row <= row_count:
                    recovered = _recover_bid_row(evidence_by_id[bid.evidence_block_id], bid.org.name)
                    bid.evidence_block_row = recovered
                    normalized_rows += 1
            for reference in bid.evidence_refs:
                if reference.block_id in rows_by_block:
                    row_count = rows_by_block[reference.block_id]
                    if row_count == 0:
                        if reference.block_row is not None:
                            normalized_rows += 1
                        reference.block_row = None
                    elif reference.block_row is not None and not 1 <= reference.block_row <= row_count:
                        recovered = _recover_bid_row(evidence_by_id[reference.block_id], bid.org.name)
                        reference.block_row = recovered
                        normalized_rows += 1
            references = list(bid.evidence_refs)
            if bid.evidence_block_id:
                references.append(type("LegacyRef", (), {"block_id": bid.evidence_block_id, "block_row": bid.evidence_block_row})())
            for reference in references:
                if reference.block_id not in rows_by_block:
                    errors.append(f"packages[{package_index}].bidders[{bid_index}] references unknown block")
                if reference.block_row is not None:
                    row_count = rows_by_block.get(str(reference.block_id), 0)
                    if not 1 <= reference.block_row <= row_count:
                        errors.append(f"packages[{package_index}].bidders[{bid_index}] references invalid row")
    if normalized_rows:
        project.warnings.append(f"已确定性归一化 {normalized_rows} 个模型证据行号")
    return (project if not errors else None), errors


class RelationExtractionAgent:
    version = RELATION_AGENT_VERSION

    def __init__(self, backend: ExtractionBackend | None = None, config: RelationAgentConfig | None = None):
        self.backend = backend
        self.config = config or RelationAgentConfig()
        self.candidate_extractor = RelationCandidateExtractor()

    def run_signature(self) -> dict[str, Any]:
        return {
            "agent_version": self.version,
            "backend": self.backend.name if self.backend else "none",
            "config": asdict(self.config),
        }

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        notice_id = str(payload.get("notice_id") or "")
        candidate = self.candidate_extractor.extract(payload)
        evidence = select_relation_evidence(payload, self.config)
        base: dict[str, Any] = {
            "notice_id": notice_id,
            "status": "candidate_only",
            "method": "deterministic_candidate_v1",
            "project": candidate.model_dump(mode="json"),
            "candidate_warnings": candidate.warnings,
            "errors": [],
            "repair_attempts": 0,
            "usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "agent": self.run_signature(),
        }
        bidder_count = sum(len(package.bidders) for package in candidate.packages)
        # Large, strongly structured opening tables can exceed the model's
        # completion-token limit merely by echoing every bidder.  The rule
        # extractor has already bound each row to a real Block and is safer
        # than accepting a truncated JSON response in this narrow case.
        if bidder_count >= self.config.large_table_bypass_bidders:
            candidate.extraction_method = "deterministic_large_table_v1"
            candidate.warnings.append(
                f"检测到 {bidder_count} 条强结构化投标记录，已跳过模型复述以避免输出截断"
            )
            base.update(
                status="success",
                method="deterministic_large_table",
                project=candidate.model_dump(mode="json"),
            )
            return base
        if self.backend is None:
            return base
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "notice_id": notice_id,
                "title": payload.get("title") or notice_id,
                "rule_candidate": base["project"],
                "evidence": evidence,
            }, ensure_ascii=False)},
        ]
        previous: Any = None
        errors: list[str] | None = None
        for attempt in range(self.config.max_repair_attempts + 1):
            try:
                response: BackendResponse = self.backend.complete(
                    messages=messages,
                    schema=RELATION_OUTPUT_SCHEMA,
                    request_id=f"{notice_id}:relation",
                    repair_errors=errors,
                    previous_output=previous,
                )
            except Exception as exc:
                base.update(status="failed", method=self.backend.name, errors=[f"backend error: {type(exc).__name__}: {exc}"])
                return base
            base["usage"]["calls"] += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                base["usage"][key] += int(response.usage.get(key) or 0)
            previous = response.output
            project, validation_errors = _validate_model_output(previous, notice_id=notice_id, evidence=evidence)
            if project:
                base.update(
                    status="success", method="model_repaired" if attempt else "model",
                    project=project.model_dump(mode="json"), errors=[], repair_attempts=attempt,
                )
                return base
            errors = validation_errors
        base.update(status="failed", method=self.backend.name, errors=errors or ["unknown validation error"], repair_attempts=self.config.max_repair_attempts)
        return base
