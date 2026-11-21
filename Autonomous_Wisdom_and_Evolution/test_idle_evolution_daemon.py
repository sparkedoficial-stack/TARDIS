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


def test_conjecture_json_parser_resilient_edge_cases():
    # 1. JSON truncado al límite de tokens (Unterminated string)
    truncated = (
        '```json\n'
        '{\n'
        '  "title": "Compresión Adaptativa de Contexto Causal",\n'
        '  "hypothesis": "Segmentar la memoria por entropía reduce latencia en 40%.",\n'
        '  "research_query": "adaptive context compression llm latency",\n'
        '  "target_file": "core/deep_memory_vault.py",\n'
        '  "code_improvement_goal": "Implementar compactación incremental de embeddings sin terminar'
    )
    parsed_trunc = IdleEvolutionDaemon._parse_conjecture_json(truncated)
    assert parsed_trunc is not None
    assert parsed_trunc["title"] == "Compresión Adaptativa de Contexto Causal"
    assert "entropía" in parsed_trunc["hypothesis"]
    assert parsed_trunc["target_file"] == "core/deep_memory_vault.py"

    # 2. Bloque <think>, saltos de línea literales dentro de strings y coma final
    noisy = (
        '<think>Razonando paso a paso...</think>\n'
        'Aquí tienes el JSON:\n'
        '{\n'
        '  "title": "Telemetría Kernel PSI Predictiva",\n'
        '  "hypothesis": "Línea uno.\nLínea dos con control\tchar.",\n'
        '  "research_query": "linux psi memory stall prediction",\n'
        '  "target_file": null,\n'
        '  "code_improvement_goal": null,\n'
        '}\n'
        'Espero que sirva.'
    )
    parsed_noisy = IdleEvolutionDaemon._parse_conjecture_json(noisy)
    assert parsed_noisy is not None
    assert parsed_noisy["title"] == "Telemetría Kernel PSI Predictiva"
    assert "Línea dos" in parsed_noisy["hypothesis"]
    assert parsed_noisy["target_file"] is None


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
    from core.security import get_authorized_tokens
    auth = {"X-API-Key": next(iter(get_authorized_tokens()), "test_tok")}

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
