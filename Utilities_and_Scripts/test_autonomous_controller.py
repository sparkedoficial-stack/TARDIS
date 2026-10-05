"""
tests/test_autonomous_controller.py - Pruebas Unitarias para el Motor de Control y Conexión Autónomo
GODWORKS SYSTEM v26.4
"""

import json
import re
import pytest
from starlette.testclient import TestClient
from server.api import app
from core.autonomous_controller import get_autonomous_controller, AutonomousController
import omni_temporal_control

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "DiosDelTiempo01"}


def test_autonomous_controller_singleton():
    ac = get_autonomous_controller()
    assert ac is not None
    assert isinstance(ac, AutonomousController)
    assert ac is get_autonomous_controller()

    cfg = ac.config
    assert "enabled" in cfg
    assert "cycle_interval_seconds" in cfg
    assert "auto_wifi" in cfg
    assert "auto_bluetooth" in cfg
    assert "auto_hardware" in cfg
    assert "auto_guardian" in cfg
    assert "auto_memory" in cfg
    assert "auto_packages" in cfg


def test_autonomous_controller_config():
    ac = get_autonomous_controller()
    orig_interval = ac.config.get("cycle_interval_seconds", 30.0)

    res = ac.set_config({"cycle_interval_seconds": 45.0, "auto_wifi": True})
    assert res.get("ok") is True
    assert ac.config["cycle_interval_seconds"] == 45.0
    assert ac.config["auto_wifi"] is True

    # Restaurar
    ac.set_config({"cycle_interval_seconds": orig_interval})


def test_autonomous_controller_step_cycle():
    ac = get_autonomous_controller()
    initial_cycles = ac._cycle_count

    res = ac.step_cycle()
    assert res.get("ok") is True
    assert "duration_seconds" in res
    assert "actions_performed" in res
    assert "internet_ok" in res
    assert ac._cycle_count == initial_cycles + 1
    assert ac._cycles_completed == ac._cycle_count


def test_autonomous_controller_history_and_record():
    ac = get_autonomous_controller()
    ac._record_action("test_subsystem", "test_action", {"test_param": 123}, status="success")

    history = ac.get_history(limit=10)
    assert isinstance(history, list)
    assert len(history) > 0

    latest = history[-1]
    assert "timestamp" in latest
    assert latest.get("domain") == "test_subsystem"
    assert latest.get("action") == "test_action"
    assert latest.get("status") == "success"


def test_autonomous_api_status():
    resp = client.get("/api/autonomous/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "cycle_count" in data
    assert "cycles_completed" in data
    assert "config" in data
    assert "telemetry" in data
    assert "recent_actions" in data


def test_autonomous_api_cycle():
    resp = client.post("/api/autonomous/cycle", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "cycle" in data
    assert "actions_performed" in data or "actions_count" in data


def test_autonomous_api_config():
    resp = client.post(
        "/api/autonomous/config",
        headers=AUTH_HEADERS,
        json={"auto_guardian": True, "cycle_interval_seconds": 25.0}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data["config"]["auto_guardian"] is True
    assert data["config"]["cycle_interval_seconds"] == 25.0

    # Restaurar
    client.post("/api/autonomous/config", headers=AUTH_HEADERS, json={"cycle_interval_seconds": 30.0})


def test_autonomous_api_history():
    resp = client.get("/api/autonomous/history?limit=5", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "log" in data
    assert isinstance(data["log"], list)


def test_omni_temporal_chat_intent_autonomous():
    # Probar que el intent en lenguaje natural active el controlador autónomo
    resp = omni_temporal_control.process_hardware_chat_intent("activa el control autónomo del sistema")
    assert resp is not None
    assert resp.get("executed") is True
    assert "AUTÓNOMO" in resp.get("system_feedback", "").upper()

    # Probar intercepción sintáctica de directivas agénticas [[AUTONOMOUS_DIRECTIVE: {...}]]
    raw_rep = "Análisis completo. [[AUTONOMOUS_DIRECTIVE: {\"action\": \"cycle\"}]] Ejecución validada."
    auto_matches = re.findall(r"\[\[AUTONOMOUS_DIRECTIVE:\s*(\{.*?\})\s*\]\]", raw_rep, flags=re.DOTALL)
    assert len(auto_matches) == 1
    a_data = json.loads(auto_matches[0])
    assert a_data.get("action") == "cycle"


def test_autonomous_auto_evolution_and_energy_unrestricted(monkeypatch):
    """Verifica que el motor autónomo evalúa evolución y ejecuta reinicio sin restricciones de energía."""
    from unittest.mock import MagicMock
    ac = get_autonomous_controller()
    assert ac.config.get("ignore_energy_restrictions") is True
    assert ac.config.get("allow_autonomous_reboot") is True

    mock_reboot = MagicMock(return_value={"ok": True, "status": "reboot_scheduled"})
    monkeypatch.setattr(ac.os_ctrl, "reboot_system", mock_reboot)

    res = ac.reboot_for_improvement(reason="Test Unitario Evolución", force=True, delay_seconds=999.0)
    assert res.get("ok") is True
    assert res.get("ignore_energy_restrictions") is True
    assert res.get("unrestricted_energy") is True
    assert mock_reboot.called
    _, kwargs = mock_reboot.call_args
    assert kwargs.get("ignore_inhibitors") is True

    # Probar schedule_autonomous_reboot
    sched = ac.schedule_autonomous_reboot("Test Programado", immediate=False)
    assert sched.get("ok") is True
    assert sched.get("status") == "scheduled"

    # Verificar que el siguiente ciclo de evolución lo tome
    evo_act = ac._auto_manage_evolution()
    assert evo_act is not None
    assert evo_act.get("domain") == "evolution"
    assert evo_act.get("action") == "autonomous_reboot"


def test_autonomous_hardware_no_powersave_when_unrestricted(monkeypatch):
    """Verifica que con ignore_energy_restrictions=True no se degrada a power-saver en batería baja."""
    from unittest.mock import MagicMock
    ac = get_autonomous_controller()

    # Simular batería baja al 15% desconectada de corriente
    mock_hw = MagicMock()
    mock_hw.get_thermals_and_battery.return_value = {
        "ok": True,
        "temperatures": {"cpu": [{"current_c": 50.0}]},
        "battery": {"percent": 15.0, "power_plugged": False}
    }
    mock_hw.get_power_profile.return_value = {"active_profile": "performance"}
    mock_hw.set_power_profile = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(ac, "hw_ctrl", mock_hw)

    ac.config["ignore_energy_restrictions"] = True
    act = ac._auto_manage_hardware()
    # No debe cambiar a power-saver
    if act:
        assert act.get("to") != "power-saver"

