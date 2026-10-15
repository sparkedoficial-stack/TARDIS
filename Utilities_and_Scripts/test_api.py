import pytest
from starlette.testclient import TestClient
from server.api import app

from core.security import get_authorized_tokens

client = TestClient(app)
_tok = next(iter(get_authorized_tokens()), "test_fallback_tok")
AUTH_HEADERS = {"X-API-Key": _tok}

def test_health_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["model"], str) and data["model"]
    # num_ctx refleja el contexto real del servidor LLM cuando esta en linea
    assert isinstance(data["num_ctx"], int) and data["num_ctx"] > 0
    assert data["status"] in ("online", "degraded")
    assert isinstance(data["llm_online"], bool)
    assert data["status"] == ("online" if data["llm_online"] else "degraded")
    assert data["flash_attention"] is True

def test_status_authorized():
    resp = client.get("/api/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "active_tasks" in data

def test_chat_empty_prompt_400():
    resp = client.post("/api/chat", json={"message": "   "}, headers=AUTH_HEADERS)
    assert resp.status_code == 400

def test_chat_cancel():
    resp = client.post("/api/chat/cancel", json={"request_id": "test_req_none"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["cancelled"] is True

def test_sensors_face_emotion():
    resp = client.get("/api/sensors/face_emotion", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True

def test_rf_radar_status():
    resp = client.get("/api/rf_radar/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
