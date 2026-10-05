"""
tests/test_inter_ai_protocol.py - Pruebas Unitarias del Protocolo Inter-IA Ultradenso (DMSP v1.0)
Verifica:
1. Construcción y serialización de mensajes DMSPMessage (Micro-AST / S-Expression).
2. Compresión semántica desde directivas conversacionales hacia símbolos de alta densidad.
3. Métricas de eficiencia y ahorro de tokens (> 70% de reducción).
4. Endpoints REST (/api/inter_ai/status y /api/inter_ai/dispatch).
"""

import pytest
from starlette.testclient import TestClient

from core.inter_ai_protocol import DMSPMessage, DMSPProtocolEngine, get_dmsp_engine
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"Authorization": "Bearer DiosDelTiempo01"}


def test_dmsp_message_serialization():
    msg = DMSPMessage(
        op="SYNC_STATE",
        src="ANTIGRAVITY",
        dst="GIA_LOCAL",
        payload={"action": "recalibrate", "target": "sensors"},
        syntropy_psi=0.95,
        lamport_clock=42
    )

    sexpr = msg.to_dense_sexpr()
    assert "(:DMSP/1.0" in sexpr
    assert ':OP "SYNC_STATE"' in sexpr
    assert ':SRC "ANTIGRAVITY"' in sexpr
    assert ':DST "GIA_LOCAL"' in sexpr
    assert ':PSI 0.95' in sexpr
    assert ':L 42' in sexpr
    assert '"action":"recalibrate"' in sexpr

    d = msg.to_dict()
    assert d["protocol"] == "DMSP/1.0"
    assert d["op"] == "SYNC_STATE"
    assert d["syntropy_psi"] == 0.95


def test_compress_prompt_to_dense_ast():
    engine = DMSPProtocolEngine()

    res_video = engine.compress_prompt_to_dense_ast("por favor manda un video por telegram hablando")
    assert res_video["op"] == "SET_TELEGRAM_VIDEO_MODE"
    assert res_video["params"].get("telegram_video") is True

    res_sov = engine.compress_prompt_to_dense_ast("activa el modo soberano air-gap local")
    assert res_sov["op"] == "SET_SOVEREIGN_GOVERNANCE"
    assert res_sov["params"].get("governance") == "absolute_local"

    res_sensors = engine.compress_prompt_to_dense_ast("dame la abstraccion de sensores y telemetria")
    assert res_sensors["op"] == "REFRESH_REALITY_ABSTRACTION"

    res_bench = engine.compress_prompt_to_dense_ast("ejecuta un benchmark de velocidad inter-ia")
    assert res_bench["op"] == "BENCHMARK_INTER_AI_THROUGHPUT"


def test_protocol_engine_dispatch_and_token_savings():
    engine = DMSPProtocolEngine()
    initial_packets = engine.packets_transmitted

    msg = DMSPMessage(
        op="QUERY_SENSOR_ABSTRACTION",
        src="GIA_SOVEREIGN",
        dst="SENSOR_ORCHESTRATOR",
        payload={"scope": "hardware_em_quantum", "temporal_depth": 5}
    )

    prompt_equiv = (
        "Hola querido subagente, por favor podrías revisar y consolidar todas las lecturas "
        "sensoriales disponibles del hardware, espectro electromagnético y coherencia cuántica "
        "con una profundidad temporal de 5 pasos y luego devolverme un resumen detallado?"
    )

    result = engine.dispatch_packet(msg, raw_prompt_equiv=prompt_equiv)
    assert result["ok"] is True
    assert engine.packets_transmitted == initial_packets + 1
    assert result["savings_pct"] >= 70.0

    metrics = engine.get_metrics()
    assert metrics["ok"] is True
    assert metrics["savings_percentage"] >= 70.0
    assert len(metrics["active_nodes"]) >= 4
    assert len(metrics["recent_packets"]) >= 1


def test_api_inter_ai_status():
    resp = client.get("/api/inter_ai/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["protocol"] == "DMSP/1.0"
    assert "savings_percentage" in data
    assert "active_nodes" in data
    assert len(data["active_nodes"]) > 0


def test_api_inter_ai_dispatch():
    payload = {
        "op": "DISPATCH_ACTION",
        "target": "SENSOR_ORCHESTRATOR",
        "source": "ANTIGRAVITY",
        "data": {"action": "heartbeat_ping", "code": 100},
        "raw_prompt": "Por favor realiza un ping al orquestador sensorial para comprobar su latencia y estado activo."
    }
    resp = client.post("/api/inter_ai/dispatch", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "packet" in data
    assert data["packet"]["ok"] is True
    assert "metrics" in data
