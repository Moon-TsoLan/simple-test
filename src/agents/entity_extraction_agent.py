"""LangGraph-controlled entity extraction from selected Blocks."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .backends import BackendResponse, ExtractionBackend
from .source_policy import evidence_is_non_result
from .tools import can_use_table_fast_path, extract_structured_table, parse_request_evidence
from .validators import ENTITY_OUTPUT_SCHEMA, ValidationResult, validate_output


AGENT_VERSION = "2.1.0"


@dataclass(frozen=True)
class AgentConfig:
    enable_rule_fast_path: bool = True
    max_repair_attempts: int = 1
    amount_tolerance: float = 0.02
    skip_text_when_covered_by_strong_table: bool = True


class _ExtractionState(TypedDict, total=False):
    request: dict[str, Any]
    evidence: dict[str, Any]
    outcome: dict[str, Any]
    raw_output: Any
    validation: ValidationResult


class EntityExtractionAgent:
    """A bounded LangGraph state machine for one selector request.

    The graph owns deterministic routing, local extraction, evidence
    validation, one bounded repair and accounting. A model may propose JSON,
    but it cannot bypass provenance or retry limits. This remains compatible
    with any OpenAI-compatible local or external backend.
    """

    version = AGENT_VERSION

    def __init__(self, backend: ExtractionBackend | None = None, config: AgentConfig | None = None):
        self.backend = backend
        self.config = config or AgentConfig()
        self.graph = self._build_graph()

    @property
    def backend_name(self) -> str:
        return self.backend.name if self.backend is not None else "none"

    def run_signature(self) -> dict[str, Any]:
        return {
            "agent_version": self.version,
            "orchestrator": "langgraph",
            "backend": self.backend_name,
            "config": asdict(self.config),
        }

    @staticmethod
    def _usage(response: BackendResponse | None) -> dict[str, Any]:
        if response is None:
            return {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_yuan": 0.0,
            }
        return {
            "calls": 1,
            "prompt_tokens": int(response.usage.get("prompt_tokens") or 0),
            "completion_tokens": int(response.usage.get("completion_tokens") or 0),
            "total_tokens": int(response.usage.get("total_tokens") or 0),
            "estimated_cost_yuan": float(response.estimated_cost_yuan or 0.0),
        }

    @staticmethod
    def _add_usage(total: dict[str, Any], addition: dict[str, Any]) -> None:
        for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens"):
            total[key] = int(total.get(key) or 0) + int(addition.get(key) or 0)
        total["estimated_cost_yuan"] = (
            float(total.get("estimated_cost_yuan") or 0.0)
            + float(addition.get("estimated_cost_yuan") or 0.0)
        )

    def _base_outcome(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        notice_id = str(request.get("notice_id") or request_id.split(":", 1)[0])
        return {
            "request_id": request_id,
            "notice_id": notice_id,
            "content_kind": request.get("content_kind"),
            "status": "failed",
            "method": None,
            "confidence": 0.0,
            "confidence_basis": None,
            "repair_attempts": 0,
            "warnings": [],
            "errors": [],
            "items": [],
            "usage": self._usage(None),
            "workflow_trace": [],
        }

    def _build_graph(self):
        builder = StateGraph(_ExtractionState)
        builder.add_node("prepare", self._prepare)
        builder.add_node("rule_extract", self._rule_extract)
        builder.add_node("skip_non_result", self._skip_non_result)
        builder.add_node("defer", self._defer)
        builder.add_node("model_extract", self._model_extract)
        builder.add_node("repair", self._repair)
        builder.add_node("accept_model", self._accept_model)
        builder.add_node("reject_model", self._reject_model)

        builder.add_edge(START, "prepare")
        builder.add_conditional_edges(
            "prepare",
            self._route_after_prepare,
            {
                "rule": "rule_extract", "skip": "skip_non_result",
                "model": "model_extract", "defer": "defer", "end": END,
            },
        )
        builder.add_edge("skip_non_result", END)
        builder.add_conditional_edges(
            "rule_extract",
            self._route_after_rule,
            {"done": END, "model": "model_extract", "defer": "defer"},
        )
        builder.add_edge("defer", END)
        builder.add_conditional_edges(
            "model_extract",
            self._route_after_model,
            {"accept": "accept_model", "repair": "repair", "reject": "reject_model", "end": END},
        )
        builder.add_conditional_edges(
            "repair",
            self._route_after_repair,
            {"accept": "accept_model", "reject": "reject_model", "end": END},
        )
        builder.add_edge("accept_model", END)
        builder.add_edge("reject_model", END)
        return builder.compile()

    def _prepare(self, state: _ExtractionState) -> _ExtractionState:
        request = state["request"]
        outcome = self._base_outcome(request)
        outcome["workflow_trace"].append("prepare")
        try:
            _user_input, evidence = parse_request_evidence(request)
        except Exception as exc:
            outcome["errors"].append(f"invalid request package: {exc}")
            return {"outcome": outcome}
        return {"outcome": outcome, "evidence": evidence}

    def _route_after_prepare(self, state: _ExtractionState) -> str:
        if "evidence" not in state:
            return "end"
        evidence = state["evidence"]
        if evidence_is_non_result(evidence)[0]:
            return "skip"
        if self.config.enable_rule_fast_path and can_use_table_fast_path(evidence):
            return "rule"
        return "model" if self.backend is not None else "defer"

    def _skip_non_result(self, state: _ExtractionState) -> _ExtractionState:
        outcome = state["outcome"]
        _is_non_result, reason = evidence_is_non_result(state["evidence"])
        outcome["workflow_trace"].append("skip_non_result")
        outcome.update({
            "status": "success",
            "method": "local_non_result_filter",
            "confidence": 0.99,
            "confidence_basis": reason or "deterministic_non_result_evidence",
            "warnings": [f"evidence skipped locally: {reason or 'non_result'}"],
            "errors": [],
            "items": [],
        })
        return {"outcome": outcome}

    def _rule_extract(self, state: _ExtractionState) -> _ExtractionState:
        evidence = state["evidence"]
        outcome = state["outcome"]
        outcome["workflow_trace"].append("rule_extract")
        rule_items = extract_structured_table(evidence)
        if not rule_items:
            return {"outcome": outcome}
        validated = validate_output(
            {"items": rule_items, "warnings": []},
            evidence,
            amount_tolerance=self.config.amount_tolerance,
        )
        if validated.items and not validated.errors:
            mapped_field_count = len(evidence.get("matched_fields") or [])
            confidence = 0.94 if mapped_field_count >= 5 else 0.88
            outcome.update({
                "status": "success",
                "method": "rules",
                "confidence": confidence,
                "confidence_basis": f"rule_table_mapped_fields:{mapped_field_count}",
                "warnings": validated.warnings,
                "items": validated.items,
            })
        return {"outcome": outcome, "validation": validated}

    def _route_after_rule(self, state: _ExtractionState) -> str:
        if state["outcome"].get("status") == "success":
            return "done"
        return "model" if self.backend is not None else "defer"

    def _defer(self, state: _ExtractionState) -> _ExtractionState:
        outcome = state["outcome"]
        outcome["workflow_trace"].append("defer")
        outcome.update({
            "status": "needs_model",
            "method": "deferred",
            "confidence_basis": "no_safe_rule_path_and_no_model_backend",
            "warnings": [
                "evidence is not safe for the local rule fast path; configure a local or API model backend"
            ],
            "errors": [],
        })
        return {"outcome": outcome}

    def _model_extract(self, state: _ExtractionState) -> _ExtractionState:
        request = state["request"]
        evidence = state["evidence"]
        outcome = state["outcome"]
        outcome["workflow_trace"].append("model_extract")
        messages = list((request.get("api_payload") or {}).get("messages") or [])
        try:
            response = self.backend.complete(
                messages=messages,
                schema=ENTITY_OUTPUT_SCHEMA,
                request_id=str(outcome["request_id"]),
            )
            self._add_usage(outcome["usage"], self._usage(response))
            validation = validate_output(
                response.output,
                evidence,
                amount_tolerance=self.config.amount_tolerance,
            )
            return {"outcome": outcome, "raw_output": response.output, "validation": validation}
        except Exception as exc:
            outcome["errors"].append(f"backend error: {type(exc).__name__}: {exc}")
            outcome["method"] = self.backend_name
            return {"outcome": outcome}

    def _route_after_model(self, state: _ExtractionState) -> str:
        if "validation" not in state:
            return "end"
        if not state["validation"].errors:
            return "accept"
        if self.config.max_repair_attempts > 0:
            return "repair"
        return "reject"

    def _repair(self, state: _ExtractionState) -> _ExtractionState:
        request = state["request"]
        evidence = state["evidence"]
        outcome = state["outcome"]
        outcome["workflow_trace"].append("repair")
        outcome["repair_attempts"] = 1
        messages = list((request.get("api_payload") or {}).get("messages") or [])
        try:
            response = self.backend.complete(
                messages=messages,
                schema=ENTITY_OUTPUT_SCHEMA,
                request_id=str(outcome["request_id"]),
                repair_errors=state["validation"].errors,
                previous_output=state.get("raw_output"),
            )
            self._add_usage(outcome["usage"], self._usage(response))
            validation = validate_output(
                response.output,
                evidence,
                amount_tolerance=self.config.amount_tolerance,
            )
            return {"outcome": outcome, "raw_output": response.output, "validation": validation}
        except Exception as exc:
            outcome["errors"].append(f"backend repair error: {type(exc).__name__}: {exc}")
            outcome["method"] = self.backend_name
            return {"outcome": outcome}

    @staticmethod
    def _route_after_repair(state: _ExtractionState) -> str:
        if "validation" not in state:
            return "end"
        return "accept" if not state["validation"].errors else "reject"

    def _accept_model(self, state: _ExtractionState) -> _ExtractionState:
        outcome = state["outcome"]
        validation = state["validation"]
        outcome["workflow_trace"].append("accept_model")
        outcome["warnings"].extend(validation.warnings)
        repaired = bool(outcome["repair_attempts"])
        outcome.update({
            "status": "success",
            "method": "model_repaired" if repaired else "model",
            "confidence": 0.78 if repaired else 0.84,
            "confidence_basis": "validated_after_repair" if repaired else "validated_model_output",
            "items": validation.items,
        })
        return {"outcome": outcome}

    def _reject_model(self, state: _ExtractionState) -> _ExtractionState:
        outcome = state["outcome"]
        validation = state["validation"]
        outcome["workflow_trace"].append("reject_model")
        outcome["warnings"].extend(validation.warnings)
        outcome["errors"].extend(validation.errors)
        outcome["method"] = self.backend_name
        return {"outcome": outcome}

    def process_request(self, request: dict[str, Any]) -> dict[str, Any]:
        final_state = self.graph.invoke({"request": request})
        return final_state["outcome"]

    def covered_text_outcome(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return a recorded no-call outcome for text skipped at notice level."""
        outcome = self._base_outcome(request)
        outcome.update({
            "status": "success",
            "method": "covered_by_strong_table",
            "confidence": 0.9,
            "confidence_basis": "notice_has_rule_table_score_at_least_0.94",
            "warnings": [
                "text request skipped because a strong structured result table already covered this notice"
            ],
            "errors": [],
            "workflow_trace": ["covered_by_strong_table"],
        })
        return outcome

    def excluded_document_outcome(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return a no-call result for a document identified as a procurement template."""
        outcome = self._base_outcome(request)
        outcome.update({
            "status": "success",
            "method": "local_non_result_document_filter",
            "confidence": 0.99,
            "confidence_basis": "sibling_evidence_identified_procurement_or_template_document",
            "warnings": ["source document skipped because sibling evidence proves it is not award-result evidence"],
            "errors": [],
            "workflow_trace": ["excluded_document_filter"],
        })
        return outcome
