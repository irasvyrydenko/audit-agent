"""Structured JSON-lines tracing (default backend; Langfuse optional later).

One line per event in logs/<run_id>.jsonl: ts, run_id, component, event, payload.
Payload keys that look like secrets are redacted before writing.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("key", "token", "secret", "password", "authorization", "user_agent")
REDACTED = "***"


def redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in SECRET_MARKERS):
            clean[key] = REDACTED
        elif isinstance(value, Mapping):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


class JsonTracer:
    def __init__(self, log_dir: Path, run_id: str | None = None) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.path = log_dir / f"{self.run_id}.jsonl"

    def log(self, component: str, event: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "component": component,
            "event": event,
            "payload": redact(payload),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def span(self, component: str, name: str, **payload: Any) -> Iterator[None]:
        start = time.perf_counter()
        self.log(component, f"{name}.start", **payload)
        try:
            yield
        except Exception as exc:
            self.log(component, f"{name}.error", error=repr(exc))
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            self.log(component, f"{name}.end", elapsed_ms=elapsed_ms)
