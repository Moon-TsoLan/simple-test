"""Pluggable model backends for :class:`EntityExtractionAgent`."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .validators import strip_thinking_markup


@dataclass
class BackendResponse:
    output: Any
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    estimated_cost_yuan: float = 0.0
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class ExtractionBackend(Protocol):
    name: str

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        request_id: str,
        repair_errors: list[str] | None = None,
        previous_output: Any = None,
        tools: list[dict[str, Any]] | None = None,
        json_response: bool = True,
    ) -> BackendResponse:
        ...


class ModelCallBudgetExceeded(RuntimeError):
    """Raised before a model call would exceed the configured pilot budget."""


class BudgetedBackend:
    """Shared hard call/token guard for extraction and verification graphs."""

    def __init__(
        self,
        backend: ExtractionBackend,
        *,
        max_calls: int = 0,
        max_total_tokens: int = 0,
    ):
        self.backend = backend
        self.max_calls = max(0, int(max_calls))
        self.max_total_tokens = max(0, int(max_total_tokens))
        self.calls = 0
        self.total_tokens = 0
        self.name = f"budgeted:{backend.name}"

    def complete(self, **kwargs: Any) -> BackendResponse:
        if self.max_calls and self.calls >= self.max_calls:
            raise ModelCallBudgetExceeded(f"model call limit reached ({self.max_calls})")
        if self.max_total_tokens and self.total_tokens >= self.max_total_tokens:
            raise ModelCallBudgetExceeded(f"model token limit reached ({self.max_total_tokens})")
        response = self.backend.complete(**kwargs)
        self.calls += 1
        self.total_tokens += int(response.usage.get("total_tokens") or 0)
        return response

    def budget_report(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "total_tokens": self.total_tokens,
            "max_calls": self.max_calls,
            "max_total_tokens": self.max_total_tokens,
        }


class FakeBackend:
    """Queue-backed test backend.  It never performs network I/O."""

    name = "fake"

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> BackendResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError("FakeBackend response queue is empty")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, BackendResponse):
            return value
        return BackendResponse(output=value, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})


class ReplayBackend:
    """Deterministic request-id keyed backend for human/model substitute runs.

    Replay files exercise the same validation, repair, merging and persistence
    path as a live model without network access.  They are intentionally
    labelled as replay outputs and must not be presented as live-model usage.
    """

    def __init__(self, responses: dict[str, Any], *, name: str = "replay"):
        self.name = name
        self.responses = dict(responses)
        self.calls: list[str] = []

    @classmethod
    def from_file(cls, path: Any) -> "ReplayBackend":
        from pathlib import Path

        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        responses = payload.get("responses") if isinstance(payload, dict) else None
        if not isinstance(responses, dict):
            raise ValueError("replay file must contain an object-valued 'responses' field")
        return cls(responses, name=f"replay:{source.stem}")

    def complete(self, **kwargs: Any) -> BackendResponse:
        request_id = str(kwargs.get("request_id") or "")
        self.calls.append(request_id)
        if request_id not in self.responses:
            raise KeyError(f"replay response not found for request_id={request_id}")
        value = self.responses[request_id]
        if isinstance(value, list):
            if not value:
                raise ValueError(f"replay response queue is empty for request_id={request_id}")
            output = value.pop(0)
        else:
            output = value
        if isinstance(output, dict) and isinstance(output.get("_backend_response"), dict):
            envelope = output["_backend_response"]
            return BackendResponse(
                output=envelope.get("output", ""),
                tool_calls=list(envelope.get("tool_calls") or []),
                usage=dict(envelope.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
                raw_metadata={"request_id": request_id, "source": "offline_replay"},
            )
        return BackendResponse(
            output=output,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            raw_metadata={"request_id": request_id, "source": "offline_replay"},
        )


class OpenAICompatibleBackend:
    """OpenAI-compatible Chat Completions backend.

    Client construction is lazy, so importing or creating the agent never
    contacts an external service.  ``strict_schema`` should be enabled only
    for providers/models that implement JSON Schema structured outputs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 120,
        max_retries: int = 2,
        strict_schema: bool = False,
        json_object: bool = True,
        max_tokens: int | None = None,
        disable_thinking: bool = False,
        input_price_per_million_yuan: float = 0.0,
        output_price_per_million_yuan: float = 0.0,
        name: str = "openai-compatible",
    ):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key or "local-no-key"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.strict_schema = strict_schema
        self.json_object = json_object
        self.max_tokens = int(max_tokens) if max_tokens else None
        self.disable_thinking = disable_thinking
        self.input_price = input_price_per_million_yuan
        self.output_price = output_price_per_million_yuan
        self.name = name
        self._client: Any = None

    @staticmethod
    def _message_text(message: Any) -> str:
        content = str(getattr(message, "content", None) or "")
        if strip_thinking_markup(content):
            return content
        for attr in ("reasoning_content", "reasoning"):
            extra = getattr(message, attr, None)
            if extra:
                return str(extra)
        return content

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
            )
        return self._client

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        request_id: str,
        repair_errors: list[str] | None = None,
        previous_output: Any = None,
        tools: list[dict[str, Any]] | None = None,
        json_response: bool = True,
    ) -> BackendResponse:
        call_messages = [dict(message) for message in messages]
        if repair_errors:
            call_messages.append({
                "role": "user",
                "content": (
                    "上一次输出未通过本地校验。请只根据原 evidence 修复 JSON；不得新增证据。\n"
                    f"校验错误：{json.dumps(repair_errors, ensure_ascii=False)}\n"
                    f"上一次输出：{str(previous_output)[:4000]}"
                ),
            })
        if self.disable_thinking:
            for index in range(len(call_messages) - 1, -1, -1):
                if call_messages[index].get("role") == "user":
                    content = str(call_messages[index].get("content") or "")
                    if "/no_think" not in content:
                        call_messages[index]["content"] = content.rstrip() + "\n/no_think"
                    break
        if self.strict_schema and json_response:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "entity_extraction", "strict": True, "schema": schema},
            }
        elif json_response and self.json_object:
            response_format = {"type": "json_object"}
        else:
            response_format = None
        started = time.time()
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": call_messages,
            "temperature": 0,
        }
        if self.max_tokens:
            request_kwargs["max_tokens"] = self.max_tokens
        if response_format is not None:
            request_kwargs["response_format"] = response_format
        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"
        if self.disable_thinking:
            request_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        response = self._get_client().chat.completions.create(
            **request_kwargs,
        )
        elapsed = time.time() - started
        usage_obj = getattr(response, "usage", None)
        usage = usage_obj.model_dump() if usage_obj is not None and hasattr(usage_obj, "model_dump") else {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = prompt_tokens / 1_000_000 * self.input_price + completion_tokens / 1_000_000 * self.output_price
        message = response.choices[0].message
        normalized_tool_calls: list[dict[str, Any]] = []
        for call in getattr(message, "tool_calls", None) or []:
            arguments = getattr(call.function, "arguments", "{}")
            try:
                parsed_arguments = json.loads(arguments)
            except (TypeError, json.JSONDecodeError):
                parsed_arguments = {"_malformed_arguments": str(arguments)}
            normalized_tool_calls.append({
                "name": str(call.function.name),
                "args": parsed_arguments,
                "id": str(call.id),
                "type": "tool_call",
            })
        raw_text = self._message_text(message)
        return BackendResponse(
            output=raw_text,
            tool_calls=normalized_tool_calls,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
            },
            elapsed_seconds=elapsed,
            estimated_cost_yuan=cost,
            raw_metadata={"model": self.model, "request_id": request_id},
        )
