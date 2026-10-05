"""
tests/test_terminal_control.py - Pruebas Unitarias de Gobernanza y Control Soberano de Terminales Externas
GODWORKS SYSTEM v26.4
"""

import json
import re
import pytest
from starlette.testclient import TestClient
from server.api import app
import omni_temporal_control

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "DiosDelTiempo01"}


def test_global_sync_hub_dispatch_broadcast():
    hub = omni_temporal_control.SYNC_HUB
    res = hub.dispatch_client_command(
        command="speak",
        params={"text": "Alerta soberana del sistema"},
        target_client_id="ALL"
    )
    assert res.get("ok") is True
    assert "command_id" in res
    assert res.get("target") == "ALL"

    # Terminal A consulta sync
    st_a = hub.get_sync_state(since_rev=0, client_id="test_client_alpha")
    assert "commands" in st_a
    cmd_ids_a = [c["id"] for c in st_a["commands"]]
    assert res["command_id"] in cmd_ids_a

    # Segunda consulta de Terminal A no debe repetir el comando ya entregado
    st_a2 = hub.get_sync_state(since_rev=st_a["revision"], client_id="test_client_alpha")
    cmd_ids_a2 = [c["id"] for c in st_a2.get("commands", [])]
    assert res["command_id"] not in cmd_ids_a2

    # Terminal B consulta sync y debe recibir el comando broadcast
    st_b = hub.get_sync_state(since_rev=0, client_id="test_client_beta")
    assert "commands" in st_b
    cmd_ids_b = [c["id"] for c in st_b["commands"]]
    assert res["command_id"] in cmd_ids_b


def test_global_sync_hub_dispatch_targeted():
    hub = omni_temporal_control.SYNC_HUB
    target_id = "test_phone_specific_42"
    res = hub.dispatch_client_command(
        command="vibrate",
        params={"pattern": [200, 100, 200]},
        target_client_id=target_id
    )
    assert res.get("ok") is True

    # Otro cliente no debe recibirlo
    st_other = hub.get_sync_state(since_rev=0, client_id="test_client_gamma")
    other_cmds = [c["id"] for c in st_other.get("commands", [])]
    assert res["command_id"] not in other_cmds

    # El cliente objetivo sí debe recibirlo
    st_target = hub.get_sync_state(since_rev=0, client_id=target_id)
    target_cmds = [c["id"] for c in st_target.get("commands", [])]
    assert res["command_id"] in target_cmds


def test_terminals_api_list():
    resp = client.get("/api/terminals/list", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "nodes" in data
    assert "total_nodes" in data
    assert "active_nodes" in data

    # Mismo resultado en /api/telemetry/nodes
    resp2 = client.get("/api/telemetry/nodes", headers=AUTH_HEADERS)
    assert resp2.status_code == 200
    assert resp2.json().get("ok") is True


def test_terminals_api_command():
    resp = client.post(
        "/api/terminals/command",
        headers=AUTH_HEADERS,
        json={
            "command": "switch_tab",
            "target": "ALL",
            "params": {"tab": "tab-nodes"}
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "command_id" in data
    assert data["target"] == "ALL"
    assert data["command"] == "switch_tab"


def test_terminals_api_broadcast():
    resp = client.post(
        "/api/terminals/broadcast",
        headers=AUTH_HEADERS,
        json={
            "command": "toast",
            "params": {"message": "Directiva Central"}
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data["command"] == "toast"


def test_chat_intent_terminal_absolute_control():
    resp = omni_temporal_control.process_hardware_chat_intent(
        "el sistema tiene control absoluto de todas las terminales externas al sistema"
    )
    assert resp is not None
    assert resp.get("executed") is True
    assert "GOBERNANZA Y CONTROL ABSOLUTO DE TERMINALES" in resp.get("system_feedback", "").upper()
    assert "raw" in resp
    assert "active_clients" in resp["raw"]


def test_chat_tag_terminal_command():
    raw_rep = "Directiva confirmada. [[TERMINAL_COMMAND: {\"command\": \"speak\", \"target\": \"ALL\", \"params\": {\"text\": \"Orden general\"}}]] Fin."
    term_matches = re.findall(r"\[\[TERMINAL_COMMAND:\s*(\{.*?\})\s*\]\]", raw_rep, flags=re.DOTALL)
    assert len(term_matches) == 1
    t_data = json.loads(term_matches[0])
    assert t_data["command"] == "speak"
    assert t_data["target"] == "ALL"
    assert t_data["params"]["text"] == "Orden general"
