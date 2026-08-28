# -*- coding: utf-8 -*-
"""Minimal DeepSeek/OpenAI-compatible JSON chat client with usage logging."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
DEFAULT_CONFIG = ROOT / "config" / "llm_config.yaml"

# DeepSeek 官方定价（元/百万 token），仅用于本地估算。
DEEPSEEK_PRICE_PER_M = {"prompt": 2.0, "completion": 8.0}


def load_config(path: Path | None = None) -> dict[str, Any]:
    load_dotenv(ENV_FILE, override=False)
    config_path = path or DEFAULT_CONFIG
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def build_client(config: dict[str, Any]) -> OpenAI:
    import os

    api_cfg = config["api"]
    key = os.environ.get(api_cfg["api_key_env"], "")
    if not key:
        raise RuntimeError(f"Environment variable {api_cfg['api_key_env']} is empty; put the key in {ENV_FILE}")
    return OpenAI(api_key=key, base_url=api_cfg["base_url"], timeout=api_cfg["timeout_seconds"],
                  max_retries=api_cfg["max_retries"])


class UsageTracker:
    def __init__(self, usage_file: Path):
        self.usage_file = Path(usage_file)
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.requests = 0

    def record(self, model: str, usage: dict[str, Any] | None, elapsed: float, status: str, notice_id: str = ""):
        usage = usage or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.requests += 1
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "notice_id": notice_id,
            "status": status,
            "elapsed_seconds": round(elapsed, 3),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        }
        with self.usage_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")

    def estimated_cost_yuan(self) -> float:
        return (self.total_prompt_tokens / 1_000_000 * DEEPSEEK_PRICE_PER_M["prompt"]
                + self.total_completion_tokens / 1_000_000 * DEEPSEEK_PRICE_PER_M["completion"])


def chat_json(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 3000,
    tracker: UsageTracker | None = None,
    notice_id: str = "",
) -> dict[str, Any]:
    """Call DeepSeek chat with JSON response_format and return parsed object."""
    started = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        usage_dict = usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else None
        if tracker:
            tracker.record(model, usage_dict, time.time() - started, "ok", notice_id)
    except Exception as exc:
        if tracker:
            tracker.record(model, None, time.time() - started, f"error:{type(exc).__name__}", notice_id)
        raise

    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 尝试提取第一个 JSON 对象/数组。
        start = content.find("{")
        if start == -1:
            start = content.find("[")
        if start != -1:
            end = content.rfind("}") if content[start] == "{" else content.rfind("]")
            if end != -1:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    pass
        raise ValueError(f"Model returned non-JSON content: {content[:200]!r}")
