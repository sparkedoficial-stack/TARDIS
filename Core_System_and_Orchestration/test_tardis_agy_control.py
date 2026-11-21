"""
tests/test_tardis_agy_control.py
================================
Pruebas integrales del Control Autónomo Total de TARDIS sobre la Terminal AGY
(permisos oficiales cero-prompts, hooks, sesiones stream-json, cola autopilot,
omni-tool registry, CLI tardis-agy y endpoints FastAPI).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if "/home/m11" not in sys.path:
    sys.path.insert(0, "/home/m11")

from core.tardis_agy_controller import (
    AgyStreamSession,
    PROBE_MODEL,
    REQUIRED_WILDCARDS,
    get_tardis_agy_controller,
)
from core.tardis_omni_tool_bridge import get_omni_bridge
from core.security import get_authorized_tokens
from server.api import app

client = TestClient(app)
_tok = next(iter(get_authorized_tokens()), "test_fallback_tok")
AUTH_HEADERS = {"X-API-Key": _tok}


def test_official_zero_prompt_permissions_and_hooks():
    ctrl = get_tardis_agy_controller()
    rep = ctrl.verify_permissions(run_live_probe=False)
    assert rep["ok"] is True, f"Verificación fallida: {json.dumps(rep, indent=2)}"
    eff = rep["effective_settings"]
    assert eff["toolPermission"] == "always-proceed"
    assert eff["agentMode"] in ("accept-edits", "auto")
    assert eff["artifactReviewPolicy"] == "always-proceed"
    assert eff["allowNonWorkspaceAccess"] is True
    assert eff["enableTerminalSandbox"] in (False, None)
    assert rep["missing_wildcards"] == []

    # Verificar el hook oficial tardis-agy-hook
    hook_bin = Path.home() / ".local" / "bin" / "tardis-agy-hook"
    assert hook_bin.is_file() and os.access(hook_bin, os.X_OK)
    res = subprocess.run(
        [str(hook_bin)],
        input="{}",
        env={**os.environ, "TARDIS_AGY_HOOK_EVENT": "PreToolUse"},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert res.returncode == 0
    assert json.loads(res.stdout.strip())["decision"] == "auto_approve"


def test_omni_tool_and_ftl_registry_registration():
    bridge = get_omni_bridge()
    tools = bridge.list_tools()["tools"]
    assert "agy_terminal" in tools
    assert tools["agy_terminal"]["available"] is True

    res = bridge.execute_tool("agy_terminal", "verify-permissions")
    assert res.get("ok") is True

    from modulos_ftl.ftl_omni_registry import FtlOmniRegistry

    reg = FtlOmniRegistry()
    assert "agy_terminal" in reg.catalog
    assert reg.catalog["agy_terminal"]["active"] is True


def test_fastapi_agy_control_endpoints():
    r_status = client.get("/api/agy/control/status", headers=AUTH_HEADERS)
    assert r_status.status_code == 200
    data = r_status.json()
    assert data["ok"] is True
    assert data["zero_prompt_verified"] is True

    r_verify = client.get("/api/agy/control/verify", headers=AUTH_HEADERS)
    assert r_verify.status_code == 200
    assert r_verify.json()["ok"] is True

    r_q = client.get("/api/agy/control/queue", headers=AUTH_HEADERS)
    assert r_q.status_code == 200
    assert r_q.json()["ok"] is True

    r_s = client.get("/api/agy/control/sessions", headers=AUTH_HEADERS)
    assert r_s.status_code == 200
    assert r_s.json()["ok"] is True


def test_live_zero_prompt_probe_without_skip_flag():
    """
    Ejecuta `agy-real` SIN `--dangerously-skip-permissions` para demostrar
    empíricamente que `~/.gemini/antigravity-cli/settings.json` por sí solo
    activa `permission_mode: always-proceed` y ejecuta sin pedir permisos.
    """
    ctrl = get_tardis_agy_controller()
    rep = ctrl.verify_permissions(run_live_probe=True)
    assert rep["ok"] is True, f"Live probe falló: {json.dumps(rep, indent=2)}"
    probe = rep["live_probe"]
    assert probe["permission_mode"] == "always-proceed"
    assert probe["status"] == "SUCCESS"
    assert "AGY_AUTONOMOUS_PROBE_OK" in probe["response"]


def test_live_persistent_stream_json_two_turns():
    """
    Demuestra control multi-turno persistente de TARDIS sobre un mismo proceso
    `agy --input-format stream-json --output-format stream-json` conservando memoria.
    """
    sess = AgyStreamSession(model=PROBE_MODEL, effort="low")
    try:
        t1 = sess.send_turn("Remember the exact token: KRONOS_9421. Reply with only: STORED", timeout=60)
        assert t1["ok"] is True, f"Turno 1 falló: {t1}"
        assert t1["permission_mode"] == "always-proceed"
        cid1 = t1["conversation_id"]
        assert cid1

        t2 = sess.send_turn(
            "What exact token did I ask you to remember in the previous turn? Reply with only the token.",
            timeout=60,
        )
        assert t2["ok"] is True, f"Turno 2 falló: {t2}"
        assert t2["conversation_id"] == cid1
        assert "KRONOS_9421" in t2["response"]
        assert t2["num_turns"] >= 2
    finally:
        sess.close()


def test_live_daemon_autonomous_queue_execution():
    """
    Encola una tarea vía `tardis-agy enqueue` y verifica que el demonio systemd
    `tardis-agy-autopilot.service` la recoge y completa autónomamente sin intervención.
    """
    ctrl = get_tardis_agy_controller()
    ctrl.set_paused(False)
    marker = f"DAEMON_E2E_{int(time.time())}"
    enq = ctrl.enqueue_task(
        f"Reply with only the exact token: {marker}",
        source="pytest_e2e_autopilot",
        priority="critical",
        model=PROBE_MODEL,
        effort="low",
        timeout=90,
        dedup_window_s=0,
    )
    assert enq["ok"] is True
    task_id = enq["task_id"]

    deadline = time.time() + 90.0
    final_rec = None
    while time.time() < deadline:
        rec = ctrl.get_task(task_id)
        if rec and rec.get("status") in ("COMPLETED", "FAILED"):
            final_rec = rec
            break
        time.sleep(1.5)

    assert final_rec is not None, f"El demonio tardis-agy-autopilot no completó {task_id} a tiempo"
    assert final_rec["status"] == "COMPLETED", f"Tarea falló: {final_rec}"
    assert marker in str((final_rec.get("result") or {}).get("response") or "")
