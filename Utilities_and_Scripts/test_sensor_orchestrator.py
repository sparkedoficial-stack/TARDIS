"""
GODWORKS SYSTEM v26.4 - Unit Tests for Absolute Local Sensor Orchestrator
Verifica:
1. Ingesta y abstracción multi-sensorial unificada (biometría, hardware, RF, cuántico).
2. Generación de síntesis situacional densa en lenguaje natural.
3. Despacho y soberanía local absoluta con failover inmediato ante caída de modelos externos.
4. Endpoints REST (/api/orchestrator/status, /api/orchestrator/abstract_reality, /api/orchestrator/mode).
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient

from core.sensor_orchestrator import SensorOrchestrator, get_sensor_orchestrator
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"Authorization": "Bearer DiosDelTiempo01"}


@pytest.fixture
def temp_orchestrator():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "test_orch_state.json"
        orch = SensorOrchestrator(state_path=state_file)
        yield orch


def test_abstract_situation_generation(temp_orchestrator):
    abstract = temp_orchestrator.get_abstract_situation(force_refresh=True)
    assert "dense_summary" in abstract
    assert "people" in abstract
    assert "biometrics" in abstract
    assert "hardware" in abstract
    assert "electromagnetic" in abstract
    assert "quantum_temporal" in abstract

    summary = abstract["dense_summary"]
    assert "Conciencia de Presencia" in summary
    assert "Vitalidad de Hardware" in summary
    assert "Espectro EM" in summary
    assert "Coherencia Sintrópica" in summary


def test_sovereign_failover_when_cloud_fails(temp_orchestrator):
    # Función de inferencia local que siempre responde
    def mock_local():
        return {"ok": True, "reply": "Respuesta generada soberanamente por Dolphin 3.0 en GPU local."}

    # Función de cloud que falla arrojando excepción
    def mock_failing_cloud():
        raise ConnectionError("Timeout 504 Gateway Timeout hacia clúster externo")

    res = temp_orchestrator.dispatch_with_sovereign_fallback(
        messages=[{"role": "user", "content": "Explica la teoría sintrópica"}],
        local_chat_fn=mock_local,
        cloud_chat_fn=mock_failing_cloud,
        should_use_cloud=True
    )

    assert res["ok"] is True
    assert "Dolphin 3.0" in res["reply"]
    assert res["orchestrator"]["mode"] == "absolute_local"
    assert res["orchestrator"]["status"] == "sovereign_executed"
    assert len(temp_orchestrator._failover_events) == 1
    assert temp_orchestrator._failover_events[0]["trigger"] == "cloud_exception"


def test_sovereign_orchestration_when_cloud_succeeds(temp_orchestrator):
    def mock_local():
        return {"ok": True, "reply": "Local"}

    def mock_good_cloud():
        return {"ok": True, "reply": "Respuesta rápida de DeepSeek-R1 (95 tok/s)."}

    res = temp_orchestrator.dispatch_with_sovereign_fallback(
        messages=[{"role": "user", "content": "Optimiza este algoritmo"}],
        local_chat_fn=mock_local,
        cloud_chat_fn=mock_good_cloud,
        should_use_cloud=True
    )

    assert res["ok"] is True
    assert "DeepSeek-R1" in res["reply"]
    assert res["orchestrator"]["mode"] == "hybrid_assisted"
    assert res["orchestrator"]["status"] == "cloud_success"


def test_orchestrator_rest_api():
    resp_status = client.get("/api/orchestrator/status", headers=AUTH_HEADERS)
    assert resp_status.status_code == 200
    st_data = resp_status.json()
    assert st_data["ok"] is True
    assert "sovereign_node" in st_data

    resp_abs = client.get("/api/orchestrator/abstract_reality", headers=AUTH_HEADERS)
    assert resp_abs.status_code == 200
    abs_data = resp_abs.json()
    assert abs_data["ok"] is True
    assert "dense_summary" in abs_data["data"]

    resp_mode = client.post("/api/orchestrator/mode", json={"mode": "absolute_local"}, headers=AUTH_HEADERS)
    assert resp_mode.status_code == 200
    assert resp_mode.json()["governance_mode"] == "absolute_local"
