"""
tests/test_self_improve_loop.py - Validación del Bucle de Auto-Mejora y Retroalimentación
========================================================================================
Verifica que el sistema sea capaz de:
1. Analizar telemetría, errores y señales operativas del nodo soberano.
2. Formular propuestas de mejora estructuradas y accionables (archivo objetivo, problema, propuesta, verificación).
3. Guardar las directivas en la cola persistente (improvement_queue) y el buzón (.agents/antigravity_bridge).
4. Exponer endpoints API REST para inspección y ejecución de ciclos (/api/self_improve/status, /cycle, /proposals, /api/antigravity/pending_directives).
"""
import json
import pytest
from starlette.testclient import TestClient
import antigravity_bridge
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "REDACTED_MISTRAL"}


class TestSelfImproveLoopCore:
    """Pruebas del núcleo de auto-mejora en OmniFeedbackBridge."""

    def test_gather_deep_signals(self):
        bridge = antigravity_bridge.get_bridge()
        sig = bridge._gather_deep_signals()
        assert isinstance(sig, dict)
        assert "health_score" in sig
        assert "cpu_percent" in sig
        assert "ram_percent" in sig
        assert "codebase_top" in sig
        assert "existing_slugs" in sig
        assert isinstance(sig["codebase_top"], list)

    def test_parse_proposal_text(self):
        bridge = antigravity_bridge.get_bridge()
        raw_md = (
            "# Optimización de Buffers Asíncronos\n\n"
            "## Archivo Objetivo: `server/api.py`\n\n"
            "## Severidad: ALTA\n\n"
            "## Problema:\n"
            "Cuellos de botella en la serialización JSON de logs extensos.\n\n"
            "## Propuesta Técnica:\n"
            "Implementar streaming chunks con orjson o ujson para reducir latencia a < 5ms.\n\n"
            "## Verificación:\n"
            "```bash\n"
            ".venv-linux/bin/pytest tests/test_api.py -v\n"
            "```\n"
        )
        parsed = bridge._parse_proposal_text(raw_md)
        assert parsed is not None
        assert parsed["title"] == "Optimización de Buffers Asíncronos"
        assert parsed["target_file"] == "server/api.py"
        assert parsed["severity"] == "ALTA"
        assert "Cuellos de botella" in parsed["problem"]
        assert "streaming chunks" in parsed["proposed_action"]
        assert "test_api.py" in parsed["verification_cmd"]
        assert parsed["slug"] == "optimizacion_de_buffers_asincronos"

    def test_synthesize_heuristic_proposal(self):
        bridge = antigravity_bridge.get_bridge()
        sig = {
            "health_score": 90,
            "recent_blocks": 2,
            "recent_errors": 0,
            "ram_percent": 40.0,
            "cpu_percent": 30.0,
            "instructions": []
        }
        prop = bridge._synthesize_heuristic_proposal(sig)
        assert prop is not None
        assert "agent_safety.py" in prop["target_file"]
        assert prop["severity"] == "MEDIA"
        assert "bloqueos" in prop["problem"]
        assert len(prop["verification_cmd"]) > 0

    def test_save_proposal_markdown_and_directives(self, tmp_path, monkeypatch):
        bridge = antigravity_bridge.get_bridge()
        monkeypatch.setattr(antigravity_bridge, "QUEUE_DIR", tmp_path / "queue")
        monkeypatch.setattr(antigravity_bridge, "WORKSPACE_QUEUE_DIR", tmp_path / "ws_queue")
        monkeypatch.setattr(antigravity_bridge, "DIRECTIVES_QUEUE", tmp_path / "pending_directives.json")
        antigravity_bridge.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        antigravity_bridge.WORKSPACE_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

        sample_proposal = {
            "title": "Test de Validación Sintrópica",
            "target_file": "geon_causal_engine.py",
            "severity": "BAJA",
            "problem": "Verificar consistencia causal.",
            "proposed_action": "Validar reloj de Lamport.",
            "verification_cmd": ".venv-linux/bin/pytest tests/ -q",
            "slug": "test_de_validacion_sintropica"
        }

        main_path, ws_path = bridge._save_proposal_markdown(sample_proposal)
        assert main_path.exists()
        assert ws_path.exists()
        assert "Test de Validación Sintrópica" in main_path.read_text(encoding="utf-8")

        bridge._update_pending_directives(sample_proposal, main_path)
        assert antigravity_bridge.DIRECTIVES_QUEUE.exists()
        directives_data = json.loads(antigravity_bridge.DIRECTIVES_QUEUE.read_text(encoding="utf-8"))
        assert "directives" in directives_data
        assert len(directives_data["directives"]) >= 1
        assert directives_data["directives"][0]["title"] == "Test de Validación Sintrópica"

    def test_trigger_self_improvement_cycle(self, monkeypatch):
        bridge = antigravity_bridge.get_bridge()
        monkeypatch.setattr(bridge, "_generate_improvement_proposal", bridge._synthesize_heuristic_proposal)
        res = bridge.trigger_self_improvement_cycle(force=True, reason="Test unitario automatizado")
        assert res["ok"] is True
        assert "proposal" in res
        assert "file" in res
        assert len(res["proposal"]["target_file"]) > 0


class TestSelfImproveAPI:
    """Pruebas de los endpoints REST de auto-mejora."""

    def test_api_status(self):
        resp = client.get("/api/self_improve/status", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "health_score" in data
        assert "self_improve" in data
        assert isinstance(data["self_improve"], dict)
        assert "queue_count" in data["self_improve"]

    def test_api_pending_directives(self):
        resp = client.get("/api/antigravity/pending_directives", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "directives" in data
        assert isinstance(data["directives"], list)

    def test_api_proposals_list(self):
        resp = client.get("/api/self_improve/proposals", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "proposals" in data
        assert isinstance(data["proposals"], list)

    def test_api_trigger_cycle(self, monkeypatch):
        bridge = antigravity_bridge.get_bridge()
        monkeypatch.setattr(bridge, "_generate_improvement_proposal", bridge._synthesize_heuristic_proposal)
        payload = {"force": True, "reason": "Test de ciclo desde API"}
        resp = client.post("/api/self_improve/cycle", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data.get("generated") is True or "proposal" in data

