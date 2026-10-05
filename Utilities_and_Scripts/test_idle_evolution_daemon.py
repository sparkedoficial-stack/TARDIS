"""
tests/test_idle_evolution_daemon.py - Pruebas para Demonio de Conjeturas y Auto-Mejora por Inactividad
=====================================================================================================
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from core.idle_evolution_daemon import AutonomousConjecture, IdleEvolutionDaemon, get_idle_evolution_daemon
from server.api import app


def test_idle_daemon_tracking():
    daemon = IdleEvolutionDaemon(idle_threshold_seconds=2.0)
    daemon.record_user_activity()
    assert daemon.get_idle_seconds() >= 0.0
    assert daemon.is_idle() is False

    # Simular paso de tiempo
    daemon.last_user_activity_ts = time.time() - 3.0
    assert daemon.is_idle() is True


def test_conjecture_formulation_mock():
    daemon = IdleEvolutionDaemon()
    mock_api = MagicMock()
    mock_api.get_status.return_value = {"enabled": True, "has_key": True, "active_provider": "groq_deepseek"}
    mock_api.chat_completion.return_value = {
        "ok": True,
        "reply": """```json
{
  "title": "Optimización de Caching y Sintropía Temporal",
  "hypothesis": "La reducción de redundancias en I/O eleva la coherencia sistémica y reduce el jitter térmico.",
  "research_query": "cache memory latency python asyncio",
  "target_file": null,
  "code_improvement_goal": null
}
```""",
        "provider": "groq_deepseek",
        "model": "qwen/qwen3.8-27b",
    }

    with patch("core.chinese_cloud_api.get_chinese_cloud_api", return_value=mock_api):
        data = daemon._formulate_conjecture()
        assert data is not None
        assert "Optimización de Caching" in data.get("title", "")
        assert "research_query" in data


def test_execute_evolution_cycle_mock():
    daemon = IdleEvolutionDaemon()
    mock_conjecture = {
        "title": "Teoría Causal de Adaptabilidad Continua",
        "hypothesis": "Los bucles OODA enriquecidos con memoria akáshica aceleran la convergencia autónoma.",
        "research_query": "autonomous agents self-improvement machine learning",
        "target_file": None,
        "code_improvement_goal": None,
    }

    with patch.object(daemon, "_formulate_conjecture", return_value=mock_conjecture):
        mock_rep = MagicMock()
        mock_rep.synthesis = "Síntesis sintrópica de investigación autónoma."
        mock_rep.sources = [{"url": "https://example.org/study"}]

        with patch("core.web_research_engine.WebResearchEngine.deep_research", return_value=mock_rep):
            with patch("core.deep_memory_vault.DeepMemoryVault.record_contemplation", return_value=99):
                res = daemon.execute_evolution_cycle(force=True)
                assert res is not None
                assert res.title == "Teoría Causal de Adaptabilidad Continua"
                assert "https://example.org/study" in res.web_sources


def test_api_conjectures_endpoints():
    client = TestClient(app)
    auth = {"X-API-Key": "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"}

    # 1. Status
    r_st = client.get("/api/conjectures/status", headers=auth)
    assert r_st.status_code == 200
    d_st = r_st.json()
    assert d_st["ok"] is True
    assert "idle_seconds" in d_st
    assert "idle_threshold_seconds" in d_st

    # 2. History
    r_hist = client.get("/api/conjectures/history?limit=5", headers=auth)
    assert r_hist.status_code == 200
    d_hist = r_hist.json()
    assert d_hist["ok"] is True
    assert "history" in d_hist

    # 3. Trigger
    r_tr = client.post("/api/conjectures/trigger", headers=auth)
    assert r_tr.status_code == 200
    d_tr = r_tr.json()
    assert d_tr["ok"] is True
    assert d_tr["status"] == "DISPATCHED"
