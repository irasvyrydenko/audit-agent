import importlib

import pytest

COMPONENTS = [
    "filing_loader",
    "kpi_extractor",
    "indicator_engine",
    "risk_detector",
    "consistency_checker",
    "report_generator",
    "app",
]

MODULES = [
    "audit_agent.common.config",
    "audit_agent.common.llm_cache",
    "audit_agent.common.llm_client",
    "audit_agent.common.edgar_client",
    "audit_agent.common.tracing",
    "audit_agent.common.citations",
    "audit_agent.filing_loader.loader",
    "audit_agent.kpi_extractor.extractor",
    "audit_agent.indicator_engine.indicators",
    "audit_agent.risk_detector.labels",
    "audit_agent.risk_detector.baseline",
    "audit_agent.risk_detector.llm_classifier",
    "audit_agent.consistency_checker.checker",
    "audit_agent.report_generator.generator",
    "audit_agent.app.pipeline",
    "audit_agent.app.streamlit_app",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)


@pytest.mark.parametrize("component", COMPONENTS)
def test_component_docstring_contract(component):
    """Each component documents purpose, input, output and model/tool usage."""
    doc = importlib.import_module(f"audit_agent.{component}").__doc__ or ""
    for field in ("Purpose:", "Input:", "Output:", "Calls a model:", "External tool:", "Eval:"):
        assert field in doc, f"{component} docstring missing '{field}'"
