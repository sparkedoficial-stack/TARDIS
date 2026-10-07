import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from server.api import app
from core.os_controller import get_os_controller

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "REDACTED_MISTRAL"}


def test_reboot_requires_authentication():
    """El endpoint /api/os/reboot debe requerir autenticación."""
    resp = client.post("/api/os/reboot", json={"confirm": True})
    assert resp.status_code == 401


def test_reboot_rejected_without_confirmation():
    """El endpoint /api/os/reboot debe rechazar con 400 si confirm es False o falta."""
    # Sin el campo confirm
    resp = client.post("/api/os/reboot", json={}, headers=AUTH_HEADERS)
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"].lower()

    # Con confirm: False
    resp2 = client.post("/api/os/reboot", json={"confirm": False}, headers=AUTH_HEADERS)
    assert resp2.status_code == 400
    assert "confirm" in resp2.json()["detail"].lower()


def test_reboot_accepted_with_confirmation(monkeypatch):
    """Verifica que /api/os/reboot acepta la orden con confirm: True sin ejecutar comando real."""
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    resp = client.post(
        "/api/os/reboot",
        json={"confirm": True, "delay_seconds": 999.0, "reason": "Test unitario"},
        headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "reboot_scheduled"
    assert data["delay_seconds"] == 999.0
    assert "Test unitario" in data["reason"]


def test_unlock_screen_endpoint(monkeypatch):
    """Verifica que /api/os/unlock responde adecuadamente."""
    resp = client.post("/api/os/unlock", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data
    assert "locked" in data


def test_os_controller_reboot_audit(monkeypatch):
    """Verifica que reboot_system genera auditoría en agent_safety."""
    import agent_safety
    audit_calls = []

    def mock_audit(action, details):
        audit_calls.append((action, details))

    monkeypatch.setattr(agent_safety, "audit", mock_audit)

    ctrl = get_os_controller()
    res = ctrl.reboot_system(delay_seconds=999.0, reason="Auditoría de prueba")
    assert res["ok"] is True
    assert any(call[0] == "system_reboot" and "Auditoría de prueba" in call[1] for call in audit_calls)


def test_reboot_unrestricted_energy_ignore_inhibitors(monkeypatch):
    """Verifica que reboot_system invoca systemctl reboot con --ignore-inhibitors cuando ignore_inhibitors=True."""
    import time
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("subprocess.run", mock_run)

    ctrl = get_os_controller()
    res = ctrl.reboot_system(delay_seconds=0.01, reason="Test desinhibido", ignore_inhibitors=True)
    assert res["ok"] is True
    assert res["ignore_inhibitors"] is True
    assert res["unrestricted_energy"] is True

    # Dar margen al hilo para ejecutar _do_reboot
    time.sleep(0.08)
    assert mock_run.called
    args, _ = mock_run.call_args
    cmd = args[0]
    assert "systemctl" in cmd
    assert "reboot" in cmd
    assert "--ignore-inhibitors" in cmd


def test_api_reboot_with_energy_unrestricted(monkeypatch):
    """Verifica que el endpoint /api/os/reboot responde con el modo de energía irrestricto."""
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    resp = client.post(
        "/api/os/reboot",
        json={
            "confirm": True,
            "delay_seconds": 999.0,
            "reason": "Test Energía Soberana",
            "ignore_energy_restrictions": True
        },
        headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ignore_inhibitors"] is True
    assert data["unrestricted_energy"] is True


def test_api_autonomous_reboot_endpoint(monkeypatch):
    """Verifica que /api/autonomous/reboot programa el reinicio sin fallar."""
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    resp = client.post(
        "/api/autonomous/reboot?reason=TestAuto&immediate=false",
        headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "scheduled"

