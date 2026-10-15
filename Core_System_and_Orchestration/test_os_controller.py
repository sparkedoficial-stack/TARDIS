import pytest
from starlette.testclient import TestClient
from server.api import app
from core.os_controller import get_os_controller

from core.security import get_authorized_tokens

client = TestClient(app)
_tok = next(iter(get_authorized_tokens()), "test_fallback_tok")
AUTH_HEADERS = {"X-API-Key": _tok}

def test_os_unauthorized():
    resp = client.get("/api/os/status")
    assert resp.status_code == 401

def test_os_status():
    resp = client.get("/api/os/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "screen" in data
    assert "mouse" in data
    assert "volume" in data
    assert "locked" in data
    assert "status_label" in data

def test_os_screenshot():
    resp = client.get("/api/os/screenshot?max_width=320", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "data_uri" in data
    assert data["data_uri"].startswith("data:image/")

def test_os_media():
    resp = client.post("/api/os/media", json={"action": "get"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "level" in data
    assert "percent" in data

def test_os_shell():
    resp = client.post("/api/os/shell", json={"command": "echo 'GODWORKS_SOVEREIGN'"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "GODWORKS_SOVEREIGN" in data.get("stdout", "")

def test_os_inhibit():
    resp = client.post("/api/os/inhibit", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["inhibited"] is True

def test_os_shell_remote_rejected():
    remote_headers = dict(AUTH_HEADERS)
    remote_headers["X-Forwarded-For"] = "REDACTED_IP"
    resp = client.post("/api/os/shell", json={"command": "echo 'HACK'"}, headers=remote_headers)
    assert resp.status_code == 403
    data = resp.json()
    assert data["ok"] is False
    assert data["security_alert"] == "REMOTE_TERMINAL_EXEC_BLOCKED"
