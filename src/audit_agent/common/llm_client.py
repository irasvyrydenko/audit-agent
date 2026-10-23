"""OpenRouter chat client (OpenAI-compatible API).

- Model name comes ONLY from settings.llm.model — callers cannot override it.
- Every call is cache-first via LLMCache, so evals are reproducible and cheap.
- API key is read from the env var named in settings.llm.api_key_env; never logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audit_agent.common.config import LLMSettings, load_settings, resolve_path
from audit_agent.common.llm_cache import LLMCache


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    cached: bool
    usage: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or load_settings().llm
        self.cache = LLMCache(resolve_path(self.settings.cache_dir))

    def build_request(
        self, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "seed": self.settings.seed,
        }
        if response_format is not None:
            request["response_format"] = response_format
        return request

    def complete(
        self, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None
    ) -> LLMResponse:
        """Return a completion, from cache if available.

        TODO: on cache miss call OpenRouter with openai.OpenAI(base_url=..., api_key=...),
        retry on 429/5xx with backoff, store the raw response in the cache.
        """
        raise NotImplementedError("LLMClient.complete is not implemented yet")
