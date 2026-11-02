"""Tests for the LangGraph pipeline wiring (no EDGAR or LLM calls)."""

from __future__ import annotations

import json
from typing import Any

from audit_agent.app.pipeline import STEPS, _traced, build_graph
from audit_agent.common.config import load_settings
from audit_agent.common.tracing import JsonTracer


def _edges(tmp_path) -> set[tuple[str, str]]:
    tracer = JsonTracer(tmp_path)
    graph = build_graph(load_settings(), object(), object(), tracer)  # clients unused at build
    return {(e.source, e.target) for e in graph.get_graph().edges}


def test_graph_runs_components_in_order(tmp_path) -> None:
    names = ["__start__"] + [component for component, _ in STEPS] + ["__end__"]
    assert _edges(tmp_path) == set(zip(names, names[1:], strict=False))


def test_graph_has_one_node_per_component(tmp_path) -> None:
    assert [c for c, _ in STEPS] == [
        "filing_loader",
        "kpi_extractor",
        "indicator_engine",
        "risk_detector",
        "consistency_checker",
        "report_generator",
    ]


def test_traced_node_writes_span_and_returns_update(tmp_path) -> None:
    tracer = JsonTracer(tmp_path, run_id="t")
    seen: list[Any] = []

    def node(state: dict[str, Any]) -> dict[str, Any]:
        seen.append(state)
        return {"x": 1}

    assert _traced("kpi_extractor", "extract", node, tracer)({"fiscal_year": 2024}) == {"x": 1}
    assert seen == [{"fiscal_year": 2024}]
    events = [json.loads(line) for line in tracer.path.read_text(encoding="utf-8").splitlines()]
    assert {e["component"] for e in events} == {"kpi_extractor"}
