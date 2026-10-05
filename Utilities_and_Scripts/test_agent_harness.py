"""
tests/test_agent_harness.py - Unit Tests for Agent Harness and Autonomous Evolution
===================================================================================
Valida la integridad del ToolRegistry, la conversión de esquemas a formato estándar
OpenAI / Ollama, la auditoría de seguridad y la introspección de subsistemas.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_harness import (
    ToolRegistry,
    ToolDefinition,
    AutonomousEvolutionEngine,
    AgentHarness,
    get_agent_harness,
    get_autonomous_evolution_engine,
)


class TestToolRegistry:
    """Pruebas del registro central de herramientas."""

    def test_singleton_and_tool_count(self):
        reg = ToolRegistry.get_instance()
        assert reg is not None
        tools = reg.list_tools()
        assert len(tools) >= 40, f"Se esperaban al menos 40 herramientas, se encontraron {len(tools)}"

    def test_schemas_compatibility(self):
        reg = ToolRegistry.get_instance()
        schemas = reg.get_schemas()
        assert len(schemas) == len(reg.list_tools())
        for s in schemas:
            assert s.get("type") == "function"
            fn = s.get("function", {})
            assert "name" in fn and len(fn["name"]) > 0
            assert "description" in fn
            params = fn.get("parameters", {})
            assert params.get("type") == "object"
            assert "properties" in params

    def test_catalog_categories(self):
        reg = ToolRegistry.get_instance()
        catalog = reg.get_catalog_by_category()
        expected_cats = {
            "HARDWARE_OS",
            "SENSORS_RF",
            "VISION_CCTV",
            "COMMS",
            "MODELING_3D",
            "NETWORK_SECURITY",
            "AKASHA_MEMORY",
            "RESEARCH_CODE",
            "SELF_EVOLUTION",
        }
        for cat in expected_cats:
            assert cat in catalog, f"Falta la categoría {cat} en el catálogo"
            assert len(catalog[cat]) > 0

    def test_execute_unknown_tool(self):
        reg = ToolRegistry.get_instance()
        res = reg.execute("non_existent_tool_xyz_123")
        assert res.get("ok") is False
        assert "Herramienta desconocida" in res.get("error", "")

    def test_execute_missing_required_args(self):
        reg = ToolRegistry.get_instance()
        # set_system_volume requires 'volume_percent'
        res = reg.execute("set_system_volume", {})
        assert res.get("ok") is False
        assert "Falta argumento requerido" in res.get("error", "")

    def test_execute_safe_read_tool(self):
        reg = ToolRegistry.get_instance()
        res = reg.execute("get_hardware_telemetry", {})
        assert res.get("ok") is True
        assert "audio" in res or "keyboard" in res

    def test_execute_3d_catalog(self):
        reg = ToolRegistry.get_instance()
        res = reg.execute("get_3d_models_catalog", {})
        assert res.get("ok") is True
        assert "catalog" in res


class TestAutonomousEvolutionEngine:
    """Pruebas del motor de auto-exploración e introspección de subsistemas."""

    def test_explore_subsystems_health(self):
        engine = get_autonomous_evolution_engine()
        assert engine is not None
        report = engine.explore_subsystems()
        assert isinstance(report, dict)
        assert "timestamp" in report
        assert "subsystems" in report
        assert "overall_health_score" in report
        assert 0.0 <= report["overall_health_score"] <= 100.0

        # Verificar que cubre subsistemas vitales
        subsystems = report["subsystems"]
        vital_keys = ["hardware_controller", "rf_presence_radar", "render_3d_engine", "traffic_monitor", "deep_memory_vault"]
        for k in vital_keys:
            assert k in subsystems, f"Falta el subsistema {k} en la exploración"

    def test_evolution_journal(self):
        engine = get_autonomous_evolution_engine()
        journal = engine.get_journal(limit=5)
        assert isinstance(journal, list)


class TestAgentHarness:
    """Pruebas del orquestador unificado."""

    def test_harness_initialization(self):
        harness = get_agent_harness()
        assert harness is not None
        assert harness.registry is not None
        assert harness.evolution_engine is not None

    def test_extract_tool_calls_directive(self):
        harness = get_agent_harness()
        sample_text = 'Analizando sistema. [[TOOL_CALL: {"tool": "get_hardware_telemetry", "params": {}}]] Listo.'
        extracted = harness._extract_tool_directives(sample_text)
        assert len(extracted) == 1
        tool_name, params = extracted[0]
        assert tool_name == "get_hardware_telemetry"
        assert params == {}

    def test_extract_tool_calls_json_block(self):
        harness = get_agent_harness()
        sample_text = '```json\n{"tool": "get_3d_models_catalog", "params": {}}\n```'
        extracted = harness._extract_tool_directives(sample_text)
        assert len(extracted) == 1
        tool_name, params = extracted[0]
        assert tool_name == "get_3d_models_catalog"
