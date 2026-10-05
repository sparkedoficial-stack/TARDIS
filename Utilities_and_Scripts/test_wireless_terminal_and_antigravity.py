"""
tests/test_wireless_terminal_and_antigravity.py
Pruebas para Terminal Inalámbrica 24/7 y Auto-Inicio de Google Antigravity en GODWORKS SYSTEM.
"""

import os
import sys
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from server.api import app
import omni_temporal_control
from core.os_controller import get_os_controller

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "DiosDelTiempo01"}


def test_slash_sh_terminal_execution():
    """Prueba que el slash command /sh ejecute comandos bash inalámbricamente."""
    res = omni_temporal_control.process_hardware_chat_intent("/sh echo 'SOVEREIGN_WIRELESS_OK'")
    assert res is not None
    assert res.get("action") == "terminal_exec"
    assert res.get("executed") is True
    assert "SOVEREIGN_WIRELESS_OK" in res.get("system_feedback", "")
    assert res.get("raw", {}).get("returncode") == 0


def test_natural_language_terminal_execution():
    """Prueba que frases como 'ejecuta en terminal: whoami' se interpreten y ejecuten."""
    res = omni_temporal_control.process_hardware_chat_intent("ejecuta en terminal: echo 'NL_TEST_SUCCESS'")
    assert res is not None
    assert res.get("action") == "terminal_exec"
    assert res.get("executed") is True
    assert "NL_TEST_SUCCESS" in res.get("system_feedback", "")


def test_api_terminal_exec_endpoint():
    """Prueba el endpoint HTTP POST /api/terminal/exec."""
    resp = client.post(
        "/api/terminal/exec",
        headers=AUTH_HEADERS,
        json={"command": "echo 'HTTP_API_TEST'", "timeout": 10.0}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "HTTP_API_TEST" in data.get("stdout", "")
    assert data.get("returncode") == 0


def test_antigravity_status_slash_command():
    """Prueba que /agy status devuelva el estado de Google Antigravity."""
    res = omni_temporal_control.process_hardware_chat_intent("/agy status")
    assert res is not None
    assert res.get("action") == "antigravity_status"
    assert res.get("executed") is True
    assert "GOOGLE ANTIGRAVITY SOBERANO" in res.get("system_feedback", "")
    assert "snap_binary" in res.get("raw", {})


def test_antigravity_status_natural_language():
    """Prueba que 'estado de antigravity' devuelva telemetría del IDE."""
    res = omni_temporal_control.process_hardware_chat_intent("estado de antigravity")
    assert res is not None
    assert res.get("action") == "antigravity_status"
    assert res.get("executed") is True
    assert "GOOGLE ANTIGRAVITY SOBERANO" in res.get("system_feedback", "")


def test_antigravity_api_ide_status():
    """Prueba el endpoint HTTP GET /api/antigravity/ide/status."""
    resp = client.get("/api/antigravity/ide/status", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "running" in data
    assert "snap_binary" in data
    assert data.get("autostart_configured") is True


def test_antigravity_autostart_files_exist_and_safe():
    """Verifica que los archivos de autostart y scripts seguros de arranque existan."""
    autostart_path = os.path.expanduser("~/.config/autostart/antigravity.desktop")
    safe_script_path = os.path.expanduser("~/.local/bin/start_antigravity_safe.sh")
    boot_notifier_path = os.path.expanduser("~/.local/bin/godworks_boot_notifier.sh")

    assert os.path.isfile(autostart_path), f"Falta {autostart_path}"
    assert os.path.isfile(safe_script_path), f"Falta {safe_script_path}"
    assert os.access(safe_script_path, os.X_OK), f"No ejecutable: {safe_script_path}"

    content_desktop = open(autostart_path, "r", encoding="utf-8").read()
    assert "start_antigravity_safe.sh" in content_desktop

    content_safe = open(safe_script_path, "r", encoding="utf-8").read()
    assert "antigravity" in content_safe

    content_notifier = open(boot_notifier_path, "r", encoding="utf-8").read()
    assert "start_antigravity_safe.sh" in content_notifier
    assert "unlock_screen(password = "REDACTED")" in content_notifier
