import pytest
from starlette.testclient import TestClient
from server.api import app

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "Imznu9ZNtdbFl2ebIGSzpYqe7A3OS4Y5"}

def test_health_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["model"] in ("dolphin3:latest", "hermes3:8b")
    assert data["num_ctx"] in (4096, 16384, 32768)
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
