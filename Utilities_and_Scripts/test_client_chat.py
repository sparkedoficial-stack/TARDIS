"""
tests/test_client_chat.py - Pruebas de Interfaz y Aislamiento de Seguridad para Clientes
=======================================================================================
Verifica que la interfaz de clientes esté desprovista de controles administrativos,
que la función get_client_html_page sirva el contenido adecuado y que process_agentic_chat
con is_client_mode=True desactive completamente cualquier ejecución de comandos del sistema.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from omni_temporal_control import get_client_html_page, process_agentic_chat, process_hardware_chat_intent


def test_client_html_file_exists_and_clean():
    """Verifica que client_chat.html existe y carece de controles administrativos o sensores."""
    html_file = PROJECT_ROOT / "client_chat.html"
    assert html_file.exists()
    content = html_file.read_text(encoding="utf-8")

    # Debe contener elementos clave del chat cliente
    assert "Asistente Virtual" in content
    assert "Modo Cliente" in content
    assert "client_mode" in content

    # NO debe contener botones ni paneles administrativos
    forbidden_terms = [
        "tab-sensors",
        "tab-radar",
        "tab-safety",
        "tab-packages",
        "tab-autonomous",
        "ejecuta en terminal",
        "lock_screen",
        "reboot",
        "rf_presence_radar",
        "admin_key",
    ]
    for term in forbidden_terms:
        assert term not in content, f"Término prohibido '{term}' encontrado en la interfaz cliente"


def test_get_client_html_page():
    """Verifica que la función servidora de la página de cliente responde correctamente."""
    html = get_client_html_page()
    assert isinstance(html, str)
    assert "<!DOCTYPE html>" in html
    assert "Asistente Virtual" in html


def test_client_mode_bypasses_hardware_intent():
    """Verifica que en modo cliente, los comandos slash y de hardware no se ejecutan."""
    # En modo normal / local, /lock o /vol activan un intent
    normal_intent = process_hardware_chat_intent("/lock", is_local_request=True)
    assert normal_intent is not None
    assert normal_intent.get("action") == "lock_screen"

    # Verificamos que si pasamos is_client_mode=True a process_agentic_chat, no hay bypass de seguridad
    # Usamos un mensaje de comando de sistema
    res = process_agentic_chat(
        message="/lock",
        is_local_request=True,
        is_client_mode=True,
    )
    assert res.get("ok") is True
    # La acción no debe ser lock_screen
    assert res.get("action") != "lock_screen"


def test_fastapi_client_route():
    """Verifica que la ruta /client sea pública y sirva client_chat.html en FastAPI."""
    from starlette.testclient import TestClient
    from server.api import app
    client = TestClient(app)
    resp = client.get("/client")
    assert resp.status_code == 200
    assert "Asistente Virtual" in resp.text
    assert "Modo Cliente" in resp.text


def test_fastapi_chat_client_mode_bypasses_tools():
    """Verifica que /api/chat con client_mode=True desactive acciones de hardware en FastAPI."""
    from starlette.testclient import TestClient
    from server.api import app
    client = TestClient(app)
    resp = client.post("/api/chat", json={"message": "/lock", "client_mode": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("action") != "lock_screen"
