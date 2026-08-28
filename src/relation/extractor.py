"""Deterministic task-2 candidates from unified Blocks.

This is intentionally a candidate extractor, not a claimed high-accuracy
relation model.  It recognizes common metadata and bidder tables and emits
warnings when the source is too weak.  A local/API model may later produce the
same :class:`ProjectRelationInput` contract.
"""
from __future__ import annotations

import re
from typing import Any

from .schema import BidInput, OrganizationInput, PackageInput, ProjectRelationInput


PROJECT_NO_RE = re.compile(r"(?:项目编号|采购编号|招标编号)\s*[：:]\s*([^\s，,；;]{3,80})")
UNIT_RE = re.compile(r"(?:采购人|采购单位)(?:信息)?\s*(?:名称)?\s*[：:]\s*([^\n；;]{2,200})")
AGENCY_RE = re.compile(r"(?:代理机构|采购代理机构)(?:信息)?\s*(?:名称)?\s*[：:]\s*([^\n；;]{2,200})")
PACKAGE_RE = re.compile(r"(?:第?\s*([一二三四五六七八九十\d]+)\s*(?:包|标段)|包号\s*[：:]?\s*([^\s，,]+))")
MONEY_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?")


def _compact(value: Any) -> str:
    return "".join(str(value or "").replace("（", "(").replace("）", ")").split())


def _text(payload: dict[str, Any]) -> str:
    return "\n".join(str(block.get("text") or "") for block in payload.get("blocks") or [])


def _number(value: Any) -> float | None:
    text = str(value or "")
    match = MONEY_RE.search(text)
    if not match:
        return None
    number = float(match.group(0).replace(",", "").replace("，", ""))
    if "万元" in text:
        number *= 10000
    return number if number >= 0 else None


def _review(value: Any) -> str:
    text = _compact(value)
    if any(token in text for token in ("不通过", "不合格", "否决", "无效")):
        return "不通过"
    if any(token in text for token in ("通过", "合格", "有效")):
        return "通过"
    return "未知"


def _result(value: Any, rank: int | None) -> str:
    text = _compact(value)
    if any(token in text for token in ("未中标", "未成交", "落标", "未入围")):
        return "未中标"
    if any(token in text for token in ("候选", "推荐")):
        return "候选"
    if "成交" in text:
        return "成交"
    if "中标" in text:
        return "中标"
    if rank == 1:
        return "候选"
    return "未知"


HEADER_ALIASES = {
    "org": ("供应商名称", "投标人名称", "投标单位名称", "投标供应商", "投标单位", "供应商", "投标人", "单位名称"),
    "amount": ("投标报价", "报价金额", "最终报价", "成交金额", "中标金额", "报价"),
    "score": ("评审得分", "综合得分", "得分"),
    "rank": ("排名", "排序", "名次"),
    "qualification": ("资格审查", "资格性审查"),
    "compliance": ("符合性审查", "响应性审查"),
    "result": ("中标情况", "成交情况", "评审结果", "结果", "备注"),
    "package": ("包号", "标包", "标段"),
}

EXCLUDED_SOURCE_TOKENS = (
    "招标文件", "采购文件", "磋商文件", "谈判文件", "询价文件",
    "采购需求", "需求书", "评分办法", "资格预审文件",
)
ORG_SUFFIXES = (
    "公司", "集团", "中心", "医院", "大学", "学院", "学校", "研究院", "研究所",
    "事务所", "合作社", "委员会", "管理局", "政府", "分局", "总队", "支队",
    "大队", "厂", "站", "馆", "所", "院", "联合体",
)
ORG_PROSE_TOKENS = (
    "根据", "本项目", "供应商应", "投标人应", "采购人", "采购包", "评分", "得分标准",
    "技术要求", "商务要求", "应当", "须提供", "需提供", "符合以下", "详见", "文件中",
    "不接受联合体", "保证金", "有效期", "最高限价", "现场考察", "答疑会", "评标方法",
)


def _source_is_candidate(block: dict[str, Any]) -> bool:
    file_name = str((block.get("source") or {}).get("file_name") or "")
    return not any(token in file_name for token in EXCLUDED_SOURCE_TOKENS)


def _valid_header_row(row: list[Any]) -> bool:
    compact = [_compact(cell) for cell in row]
    short_cells = sum(1 for cell in compact if 0 < len(cell) <= 40)
    return short_cells >= 2 and max((len(cell) for cell in compact), default=0) <= 120


def _valid_org_name(name: str) -> bool:
    compact = _compact(name)
    if not 2 <= len(compact) <= 120:
        return False
    if any(token in compact for token in ORG_PROSE_TOKENS):
        return False
    if MONEY_RE.fullmatch(compact) or compact in {"是", "否", "通过", "不通过", "合格", "不合格"}:
        return False
    base = re.sub(r"[（(](?:联合体|牵头人|成员|成员单位|个人独资|有限合伙|普通合伙).{0,40}[）)]$", "", compact)
    return base.endswith(ORG_SUFFIXES)


def _clean_org_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = re.split(r"(?:<br\s*/?>|\|\s*地址|地址\s*[：:]|联系方式\s*[：:]|联系电话\s*[：:])", text, maxsplit=1, flags=re.I)[0]
    return text.strip(" ：:，,；;|")


def _match_columns(row: list[Any]) -> dict[str, int]:
    output: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for index, value in enumerate(row):
            cell = _compact(value)
            if any(_compact(alias) in cell for alias in aliases):
                output[field] = index
                break
    return output


class RelationCandidateExtractor:
    def extract(self, payload: dict[str, Any]) -> ProjectRelationInput:
        text = _text(payload)
        title = str(payload.get("title") or payload.get("notice_id") or "未命名项目")
        project_no_match = PROJECT_NO_RE.search(text)
        unit_match = UNIT_RE.search(text)
        agency_match = AGENCY_RE.search(text)
        package_map: dict[str, PackageInput] = {}
        warnings: list[str] = []

        for block in payload.get("blocks") or []:
            if block.get("type") != "table" or not _source_is_candidate(block):
                continue
            rows = block.get("rows") or []
            best: tuple[int, dict[str, int]] | None = None
            for header_index in range(min(8, len(rows))):
                if not _valid_header_row(list(rows[header_index])):
                    continue
                columns = _match_columns(rows[header_index])
                relation_fields = {"amount", "score", "rank", "qualification", "compliance", "result"}
                if "org" in columns and relation_fields.intersection(columns) and (best is None or len(columns) > len(best[1])):
                    best = (header_index, columns)
            if best is None:
                continue
            header_index, columns = best
            header_cells = [_compact(cell) for cell in rows[header_index]]
            org_header = header_cells[columns["org"]]
            header_declares_winner = "中标" in org_header or "成交" in org_header
            source = block.get("source") or {}
            for row_index in range(header_index + 1, len(rows)):
                row = list(rows[row_index])

                def cell(name: str) -> Any:
                    index = columns.get(name)
                    return row[index] if isinstance(index, int) and index < len(row) else None

                org_name = " ".join(str(cell("org") or "").split())
                if (
                    not _valid_org_name(org_name)
                    or any(token in org_name for token in ("合计", "供应商名称", "投标人名称"))
                ):
                    continue
                package_no = " ".join(str(cell("package") or "默认包").split()) or "默认包"
                package = package_map.setdefault(package_no, PackageInput(package_no=package_no))
                rank_value = _number(cell("rank"))
                rank = int(rank_value) if rank_value and rank_value >= 1 else None
                result = _result(cell("result"), rank)
                if result == "未知" and header_declares_winner:
                    result = "成交" if "成交" in org_header and "中标" not in org_header else "中标"
                org_type = "中标供应商" if result in {"中标", "成交"} else "投标参与方"
                bid = BidInput(
                    org=OrganizationInput(name=org_name, org_type=org_type),
                    amount_yuan=_number(cell("amount")),
                    score=_number(cell("score")),
                    rank=rank,
                    qualification=_review(cell("qualification")),
                    compliance=_review(cell("compliance")),
                    result=result,
                    evidence_block_id=block.get("block_id"),
                    evidence_block_row=row_index + 1,
                )
                existing = next(
                    (value for value in package.bidders if _compact(value.org.name) == _compact(org_name)),
                    None,
                )
                if existing is None:
                    package.bidders.append(bid)
                else:
                    # Result-announcement rows are stronger than opening-table
                    # rows for winner status; otherwise only fill missing data.
                    if bid.result in {"中标", "成交"}:
                        existing.result = bid.result
                        existing.org.org_type = "中标供应商"
                        existing.evidence_block_id = bid.evidence_block_id
                        existing.evidence_block_row = bid.evidence_block_row
                    if existing.amount_yuan is None:
                        existing.amount_yuan = bid.amount_yuan
                    if existing.score is None:
                        existing.score = bid.score
                    if existing.rank is None:
                        existing.rank = bid.rank
                    if existing.qualification == "未知":
                        existing.qualification = bid.qualification
                    if existing.compliance == "未知":
                        existing.compliance = bid.compliance
        if not package_map:
            warnings.append("未识别到具有供应商及报价/得分/结果字段的竞标表")
        unit_name = _clean_org_name(unit_match.group(1)) if unit_match else ""
        agency_name = _clean_org_name(agency_match.group(1)) if agency_match else ""
        return ProjectRelationInput(
            notice_id=str(payload.get("notice_id") or ""),
            title=title,
            project_no=project_no_match.group(1) if project_no_match else None,
            procurement_unit=OrganizationInput(name=unit_name, org_type="采购单位") if _valid_org_name(unit_name) else None,
            agency=OrganizationInput(name=agency_name, org_type="代理机构") if _valid_org_name(agency_name) else None,
            packages=list(package_map.values()),
            extraction_method="deterministic_candidate_v1",
            warnings=warnings,
        )
