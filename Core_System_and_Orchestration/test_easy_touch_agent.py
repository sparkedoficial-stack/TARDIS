"""
Tests for Easy Touch Self-Improvement Agent
===========================================
TARDIS · GODWORKS SYSTEM v26.4
"""

import os
import sys
import time
from pathlib import Path

# Add .ftl to path
FTL_DIR = Path(__file__).resolve().parent
if str(FTL_DIR) not in sys.path:
    sys.path.insert(0, str(FTL_DIR))

from easy_touch import get_easy_touch_engine
from easy_touch_agent import (
    EasyTouchDynamicHealerRegistry,
    EasyTouchSelfImprovementAgent,
    UnresolvedIncident,
    get_easy_touch_agent,
)


def test_agent_singleton():
    """Verifica que el agente opere como singleton soberano."""
    agent1 = get_easy_touch_agent()
    agent2 = get_easy_touch_agent()
    assert agent1 is agent2
    assert isinstance(agent1, EasyTouchSelfImprovementAgent)


def test_dynamic_healer_registry(tmp_path):
    """Verifica el registro, serialización y despacho de sanadores dinámicos."""
    registry = EasyTouchDynamicHealerRegistry()
    registry.register_healer(
        name="test_healer",
        category="test_cat",
        pattern=r"test_error_pattern",
        action_desc="Sanador de prueba",
        code_snippet="x = 1"
    )
    healers = registry.get_healers()
    assert "test_healer" in healers
    assert healers["test_healer"]["category"] == "test_cat"

    registry.record_execution("test_healer", True)
    healers_after = registry.get_healers()
    assert healers_after["test_healer"]["executions_count"] >= 1
    assert healers_after["test_healer"]["success_count"] >= 1


def test_error_categorization():
    """Verifica la clasificación precisa de los distintos modos de fallo."""
    agent = get_easy_touch_agent()

    # CLI flag mismatch
    cat1 = agent.categorize_error('error: invalid model selection (--model "gemini-4-pro" --effort "high"): --effort is not supported for model "gemini-4-pro"')
    assert cat1 == "cli_flags_mismatch"

    # DNS / Network timeout
    cat2 = agent.categorize_error('error: Eligibility check failed: Post "https://daily-cloudcode-pa.googleapis.com/...": dial tcp: lookup daily-cloudcode-pa.googleapis.com on REDACTED_IP:53: read udp ...: i/o timeout')
    assert cat2 == "dns_resolution_timeout"

    # Cluster node timeout
    cat3 = agent.categorize_error('Fallo al contactar el clúster iMac: timed out')
    assert cat3 == "cluster_node_timeout"

    # Auth required
    cat4 = agent.categorize_error('Authentication required. Please visit the URL to log in: https://accounts.google.com/o/oauth2/auth...')
    assert cat4 == "auth_required"

    # Local daemon offline
    cat5 = agent.categorize_error('[Error de Inferencia Soberana: HTTP (No se pudo establecer conexión con ningún endpoint HTTP de Ollama.) | Pipe (Binario de Ollama no localizado para ejecución directa por tubería.)]')
    assert cat5 == "local_daemon_offline"


def test_audit_and_retroactive_resolution():
    """Verifica que el agente audite incidentes y aplique soluciones retroactivas."""
    agent = get_easy_touch_agent()
    incidents = agent.audit_all_unresolved()
    assert isinstance(incidents, list)

    # Simular o resolver incidentes
    res = agent.solve_all_unresolved()
    assert "solved" in res
    assert res["solved"] >= 0
    assert "success_rate_percent" in res


def test_cli_flag_auto_healing():
    """Verifica que Easy Touch sanee flags incompatibles como --effort."""
    engine = get_easy_touch_engine()
    raw_cmd = 'agy -p "test prompt" --model "gemini-4-pro" --effort "high"'
    sanitized = engine.auto_heal_cli_flags(raw_cmd, '--effort is not supported for model "gemini-4-pro"')
    assert '--effort "high"' not in sanitized
    assert '--effort' not in sanitized
    assert 'gemini-4-pro' in sanitized


def test_easy_touch_engine_integration():
    """Verifica la integración completa del agente en EasyTouchEngine."""
    engine = get_easy_touch_engine()
    assert hasattr(engine, "agent")
    assert engine.agent is not None

    status = engine.get_status()
    assert status["active"] is True
    assert "agent" in status
    agent_st = status["agent"]
    assert agent_st["name"] == "Easy Touch Self-Improvement Agent"
    assert agent_st["total_unresolved_found"] >= 0
