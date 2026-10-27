"""OpenRouter chat client (OpenAI-compatible API).

- Model name comes ONLY from settings.llm.model — callers cannot override it.
- Every call is cache-first via LLMCache, so evals are reproducible and cheap.
- Truncated or empty answers raise LLMError and are never cached.
- API key is read from the env var named in settings.llm.api_key_env; never logged.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from audit_agent.common.config import PROJECT_ROOT, LLMSettings, load_settings, resolve_path
from audit_agent.common.llm_cache import LLMCache

JSON_MODE = {"type": "json_object"}
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(RuntimeError):
    """Missing API key, empty/truncated answer, or unparsable JSON."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    cached: bool
    usage: dict[str, Any] = field(default_factory=dict)


def parse_json(text: str) -> Any:
    """Parse a model answer as JSON, tolerating ```json fences."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    if match:
        stripped = match.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model answer is not valid JSON: {stripped[:200]!r}") from exc


class LLMClient:
    def __init__(self, settings: LLMSettings | None = None, client: Any | None = None) -> None:
        self.settings = settings or load_settings().llm
        self.cache = LLMCache(resolve_path(self.settings.cache_dir))
        self._client = client

    def build_request(
        self, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "seed": self.settings.seed,
            "extra_body": {"reasoning": {"enabled": self.settings.reasoning_enabled}},
        }
        if response_format is not None:
            request["response_format"] = response_format
        return request

    def _openai(self) -> Any:
        if self._client is None:
            load_dotenv(PROJECT_ROOT / ".env")
            api_key = os.getenv(self.settings.api_key_env, "").strip()
            if not api_key:
                raise LLMError(f"Set {self.settings.api_key_env} in .env")
            self._client = OpenAI(
                base_url=self.settings.base_url, api_key=api_key, max_retries=3, timeout=120
            )
        return self._client

    def complete(
        self, messages: list[dict[str, str]], response_format: dict[str, Any] | None = None
    ) -> LLMResponse:
        """Return a completion, from cache if available."""
        request = self.build_request(messages, response_format)
        cached = self.cache.get(request)
        if cached is not None:
            return LLMResponse(cached["text"], cached["model"], True, cached.get("usage", {}))

        response = self._openai().chat.completions.create(**request)
        choice = response.choices[0]
        text = choice.message.content or ""
        if choice.finish_reason == "length":
            raise LLMError("Answer truncated (finish_reason=length); raise llm.max_tokens")
        if not text.strip():
            raise LLMError("Model returned an empty answer")

        usage = response.usage.model_dump() if response.usage else {}
        self.cache.put(request, {"text": text, "model": response.model, "usage": usage})
        return LLMResponse(text, response.model, False, usage)

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        """complete() in JSON mode, parsed."""
        return parse_json(self.complete(messages, response_format=JSON_MODE).text)
