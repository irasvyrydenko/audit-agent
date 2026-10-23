"""Disk cache for LLM calls.

Key = sha256 of the canonical JSON of the full request (model, messages, params), so any
change to prompt or model is a cache miss. Entries live in <cache_dir>/<key[:2]>/<key>.json.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class LLMCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    @staticmethod
    def make_key(request: Mapping[str, Any]) -> str:
        canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def get(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        path = self._path(self.make_key(request))
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["response"]

    def put(self, request: Mapping[str, Any], response: Mapping[str, Any]) -> Path:
        path = self._path(self.make_key(request))
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"request": dict(request), "response": dict(response)}
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
