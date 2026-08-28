"""Pluggable search providers used by the verification graph."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        ...


class ReplaySearchProvider:
    """Deterministic offline search results for tests and evaluation."""

    name = "replay"

    def __init__(self, responses: dict[str, list[dict[str, Any]]]):
        self.responses = responses
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        values = self.responses.get(query, self.responses.get("*", []))
        return [SearchResult(
            title=str(value.get("title") or "")[:500],
            url=str(value.get("url") or value.get("href") or "")[:2000],
            snippet=str(value.get("snippet") or value.get("body") or "")[:3000],
            provider="replay",
        ) for value in values[:max_results] if value.get("url") or value.get("href")]


class DuckDuckGoSearchProvider:
    """No-key pilot provider. Production can replace it without graph changes."""

    name = "ddgs"

    def __init__(self, *, timeout_seconds: float = 20.0, region: str = "cn-zh"):
        self.timeout_seconds = timeout_seconds
        self.region = region

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        from ddgs import DDGS

        raw = DDGS(timeout=self.timeout_seconds).text(
            query,
            region=self.region,
            max_results=max_results,
        )
        output: list[SearchResult] = []
        for value in raw or []:
            url = str(value.get("href") or value.get("url") or "").strip()
            if not url:
                continue
            output.append(SearchResult(
                title=" ".join(str(value.get("title") or "").split())[:500],
                url=url[:2000],
                snippet=" ".join(str(value.get("body") or value.get("snippet") or "").split())[:3000],
                provider="ddgs",
            ))
        return output


class CachedSearchProvider:
    """Persistent JSONL cache wrapper that avoids repeated network searches."""

    def __init__(self, provider: SearchProvider, cache_path: Path):
        self.provider = provider
        self.cache_path = cache_path
        self.name = f"cached:{provider.name}"
        self._cache: dict[str, list[SearchResult]] = {}
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    self._cache[str(record["query"])] = [SearchResult(**item) for item in record["results"]]
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if query in self._cache:
            return self._cache[query][:max_results]
        results = self.provider.search(query, max_results=max_results)
        self._cache[query] = results
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({
                "query": query,
                "provider": self.provider.name,
                "results": [asdict(item) for item in results],
            }, ensure_ascii=False, separators=(",", ":")) + "\n")
        return results
