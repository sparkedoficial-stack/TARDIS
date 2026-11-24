"""
tests/test_mundo_sin_censura_hardware.py - Pruebas de Control Absoluto de Hardware para Un Mundo Sin Censura
=============================================================================================================
Verifica:
  1. Auto-armado de control de hardware en runtime (`is_system_running`, `is_armed`, `set_mode`).
  2. Parseo robusto de directivas agénticas `[[HW_ACTION:{...}]]` (incluyendo JSON anidado)
     y de comandos directos `/hw <accion> [params]`.
  3. Protección destructiva AEGIS (bloqueo de comandos catastróficos en `root_exec` / `run_shell`).
  4. Endpoints FastAPI `/api/mundo_sin_censura/hardware/{status,capabilities,audit,mode,action}`.
  5. Ejecución directa (`/hw`) y agéntica (`[[HW_ACTION:...]]`) integrada en SSE `/api/mundo_sin_censura/chat/stream`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if "/home/m11" not in sys.path:
    sys.path.insert(0, "/home/m11")

import core.mundo_sin_censura_hardware as mhw
import core.mundo_sin_censura_chat as mchat


def test_parse_hardware_actions_nested_json():
    txt = (
        'Ajustando el sistema ahora.\n'
        '[[HW_ACTION:{"action":"set_volume","params":{"percent":55}}]]\n'
        'Y consultando kernel:\n'
        '[[HW_ACTION:{"action":"sysctl_get","params":{"param":"vm.swappiness","meta":{"tag":"r0"}}}]]'
    )
    parsed = mhw.parse_hardware_actions(txt)
    assert len(parsed) == 2
    assert parsed[0] == {"action": "set_volume", "params": {"percent": 55}}
    assert parsed[1]["action"] == "sysctl_get"
    assert parsed[1]["params"]["param"] == "vm.swappiness"
    assert parsed[1]["params"]["meta"]["tag"] == "r0"


def test_parse_slash_hw_command():
    assert mhw.parse_slash_hw_command("/hw") == ("hardware_status", {})
    assert mhw.parse_slash_hw_command("/hw set_volume 65") == ("set_volume", {"percent": 65})
    assert mhw.parse_slash_hw_command('/hw sysctl_set param=vm.swappiness value=10') == (
        "sysctl_set",
        {"param": "vm.swappiness", "value": 10},
    )
    assert mhw.parse_slash_hw_command('/hw set_thermal_policy {"policy":"turbo"}') == (
        "set_thermal_policy",
        {"policy": "turbo"},
    )
    assert mhw.parse_slash_hw_command("hola mundo") is None


def test_catastrophic_guard_blocks_self_wipe(tmp_path, monkeypatch):
    monkeypatch.setattr(mhw, "HW_STATE_FILE", tmp_path / "hw_state.json")
    monkeypatch.setattr(mhw, "HW_AUDIT_LOG", tmp_path / "hw_audit.jsonl")
    ctrl = mhw.MundoSinCensuraHardwareController()
    assert ctrl.is_armed() is True

    res_rm = ctrl.execute_action("run_shell", {"command": "rm -rf /"}, is_local_request=True)
    assert res_rm["ok"] is False
    assert "AEGIS" in res_rm["error"]

    res_root = ctrl.execute_action("root_exec", {"command": "mkfs.ext4 /dev/nvme0n1"}, is_local_request=True)
    assert res_root["ok"] is False
    assert "AEGIS" in res_root["error"]

    res_remote = ctrl.execute_action("cpu_status", {}, is_local_request=False)
    assert res_remote["ok"] is False
    assert res_remote["security_alert"] == "REMOTE_HARDWARE_BLOCKED"


def test_fastapi_hardware_endpoints_and_chat_integration(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server.api import create_app

    monkeypatch.setattr(mhw, "HW_STATE_FILE", tmp_path / "hw_state.json")
    monkeypatch.setattr(mhw, "HW_AUDIT_LOG", tmp_path / "hw_audit.jsonl")
    ctrl = mhw.MundoSinCensuraHardwareController()
    monkeypatch.setattr(mhw, "_HW_SINGLETON", ctrl)

    store = mchat.MundoSinCensuraChatStore(db_path=tmp_path / "chat_hw.db")
    monkeypatch.setattr(mchat, "_CHAT_STORE", store)

    app = create_app()
    client = TestClient(app)

    # 1. Capabilities y Status
    r_cap = client.get("/api/mundo_sin_censura/hardware/capabilities")
    assert r_cap.status_code == 200
    assert r_cap.json()["armed"] is True
    assert "kernel_ring0" in r_cap.json()["domains"]

    r_st = client.get("/api/mundo_sin_censura/hardware/status")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["ok"] is True
    assert st["hardware_control_armed"] is True
    assert "cpu" in st and "kernel_ring0" in st

    # 2. Acción directa vía API REST
    r_act = client.post(
        "/api/mundo_sin_censura/hardware/action",
        json={"action": "cpu_status", "params": {}},
    )
    assert r_act.status_code == 200
    assert r_act.json()["ok"] is True
    assert "cpu" in r_act.json()

    # 3. Comando directo /hw dentro del stream SSE (cero latencia LLM)
    r_hw_stream = client.post(
        "/api/mundo_sin_censura/chat/stream",
        json={"message": "/hw cpu_status", "model": "mundo-sin-censura"},
    )
    assert r_hw_stream.status_code == 200
    events = [
        json.loads(ln[6:])
        for ln in r_hw_stream.text.splitlines()
        if ln.startswith("data: ") and ln != "data: [DONE]"
    ]
    types = [e["type"] for e in events]
    assert "hardware_action" in types
    assert "hardware_result" in types
    assert any(e["type"] == "hardware_result" and e["ok"] is True for e in events)

    # 4. Ejecución agéntica [[HW_ACTION:...]] emitida por mundo-sin-censura
    class _FakeHwAgent:
        def inspect_temporal_brain(self, timeout=1.0):
            return {"ready": True}

        def chat_stream(self, messages, **kwargs):
            yield 'Consultando silicio:\n[[HW_ACTION:{"action":"cpu_status","params":{}}]]'
            return 'Consultando silicio:\n[[HW_ACTION:{"action":"cpu_status","params":{}}]]'

    with patch.object(mchat, "get_mundo_sin_censura", return_value=_FakeHwAgent()):
        r_agentic = client.post(
            "/api/mundo_sin_censura/chat/stream",
            json={"message": "Revisa el estado del CPU", "model": "mundo-sin-censura", "hardware_control": True},
        )
        assert r_agentic.status_code == 200
        a_events = [
            json.loads(ln[6:])
            for ln in r_agentic.text.splitlines()
            if ln.startswith("data: ") and ln != "data: [DONE]"
        ]
    assert any(e["type"] == "hardware_result" and e["action"] == "cpu_status" and e["ok"] is True for e in a_events)

    # 5. Audit log registra las acciones ejecutadas
    r_aud = client.get("/api/mundo_sin_censura/hardware/audit?limit=10")
    assert r_aud.status_code == 200
    assert r_aud.json()["count"] >= 3
