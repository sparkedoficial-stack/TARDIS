"""
tests/test_package_manager_and_buttons.py - Pruebas Unitarias para PackageManager y ButtonOrchestrator
GODWORKS SYSTEM v26.4
"""

import pytest
from starlette.testclient import TestClient
from server.api import app
from core.package_manager import get_package_manager, PackageManager
from core.button_orchestrator import get_button_orchestrator, ButtonOrchestrator
import omni_temporal_control

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "DiosDelTiempo01"}


def test_package_manager_singleton_and_env():
    mgr = get_package_manager()
    assert mgr is not None
    assert isinstance(mgr, PackageManager)
    env = mgr.get_environment_info()
    assert "python_executable" in env
    assert "pip_executable" in env
    assert "ram_budget_gb" in env
    assert env["ram_budget_gb"] == 18.0


def test_package_manager_list_packages():
    mgr = get_package_manager()
    pkgs = mgr.list_installed_packages()
    assert isinstance(pkgs, list)
    assert len(pkgs) > 0
    # Verificar que fastapi esté en la lista
    fastapi_pkg = [p for p in pkgs if p.get("name", "").lower() == "fastapi"]
    assert len(fastapi_pkg) == 1

    # Filtrado
    filtered = mgr.list_installed_packages(filter_term="fastapi")
    assert len(filtered) >= 1
    assert any("fastapi" in p["name"].lower() for p in filtered)


def test_package_manager_validation():
    mgr = get_package_manager()
    # Nombre vacío
    res = mgr.install_python_package("")
    assert res["ok"] is False
    assert "vacío" in res["error"].lower()

    # Caracteres ilegales
    res2 = mgr.install_python_package("pkg; rm -rf /")
    assert res2["ok"] is False
    assert "inválido" in res2["error"].lower()


def test_package_manager_auto_install_mapping():
    mgr = get_package_manager()
    # Comprobar que módulos estándar se mapean adecuadamente
    from core.package_manager import MODULE_TO_PYPI
    assert MODULE_TO_PYPI["PIL"] == "Pillow"
    assert MODULE_TO_PYPI["cv2"] == "opencv-python-headless"
    assert MODULE_TO_PYPI["yaml"] == "PyYAML"


def test_package_manager_history():
    mgr = get_package_manager()
    hist = mgr.get_history(limit=10)
    assert isinstance(hist, list)


def test_button_orchestrator_singleton_and_catalog():
    orch = get_button_orchestrator()
    assert orch is not None
    assert isinstance(orch, ButtonOrchestrator)

    catalog = orch.get_catalog()
    assert isinstance(catalog, dict)
    assert len(catalog) >= 50

    # Categorías clave presentes
    categories = {v.get("category") for v in catalog.values()}
    assert "view_modes" in categories
    assert "biometrics" in categories
    assert "physics" in categories
    assert "radar" in categories
    assert "temporal" in categories
    assert "voice" in categories
    assert "os_control" in categories
    assert "self_improve" in categories
    assert "network" in categories
    assert "memory" in categories


def test_button_orchestrator_trigger_actions():
    orch = get_button_orchestrator()

    # 1. Acción no destructiva de sistema (re_inhibit)
    r1 = orch.trigger_action("re_inhibit")
    assert r1.get("ok") is True

    # 2. Barrido de radar RF
    r2 = orch.trigger_action("scan_radar")
    assert r2.get("ok") is True

    # 3. Diagnóstico Antigravity
    r3 = orch.trigger_action("force_ag_diag")
    assert r3.get("ok") is True

    # 4. Acción UI despachada al cliente
    r4 = orch.trigger_action("mode_split")
    assert r4.get("ok") is True
    assert r4.get("dispatched_to_client") is True


def test_button_orchestrator_auto_activate_all():
    orch = get_button_orchestrator()
    res = orch.auto_activate_all()
    assert res.get("ok") is True
    assert res.get("status") == "ALL_SYSTEMS_ACTIVATED"
    assert res.get("activated_count") >= 5
    assert "subsystems_energized" in res
    assert "execution_details" in res


def test_api_system_packages_endpoints():
    # 1. Listar paquetes
    resp = client.get("/api/system/packages/list", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert data.get("count") > 0
    assert isinstance(data.get("packages"), list)

    # 2. Consultar entorno
    resp_env = client.get("/api/system/packages/env", headers=AUTH_HEADERS)
    assert resp_env.status_code == 200
    env_data = resp_env.json()
    assert env_data.get("ok") is True
    assert "environment" in env_data

    # 3. Consultar historial
    resp_hist = client.get("/api/system/packages/history", headers=AUTH_HEADERS)
    assert resp_hist.status_code == 200
    hist_data = resp_hist.json()
    assert hist_data.get("ok") is True
    assert isinstance(hist_data.get("history"), list)


def test_api_system_buttons_endpoints():
    # 1. Catálogo de botones
    resp_cat = client.get("/api/system/buttons/catalog", headers=AUTH_HEADERS)
    assert resp_cat.status_code == 200
    cat_data = resp_cat.json()
    assert cat_data.get("ok") is True
    assert cat_data.get("count") >= 50
    assert "catalog" in cat_data

    # 2. Trigger individual
    resp_trig = client.post("/api/system/buttons/trigger", json={"action": "mode_chat"}, headers=AUTH_HEADERS)
    assert resp_trig.status_code == 200
    trig_data = resp_trig.json()
    assert trig_data.get("ok") is True

    # 3. Auto-activación general
    resp_all = client.post("/api/system/buttons/auto_activate_all", headers=AUTH_HEADERS)
    assert resp_all.status_code == 200
    all_data = resp_all.json()
    assert all_data.get("ok") is True
    assert all_data.get("status") == "ALL_SYSTEMS_ACTIVATED"


def test_chat_intent_detection():
    # 1. Detección de auto-activación de botones en lenguaje natural
    intent_btn = omni_temporal_control.process_hardware_chat_intent("Por favor activa todos los botones del sistema")
    assert intent_btn is not None
    assert intent_btn.get("action") == "auto_activate_all_buttons"
    assert intent_btn.get("executed") is True
    assert "AUTO-ACTIVACIÓN UNIVERSAL" in intent_btn.get("system_feedback", "")

    # 2. Detección de comando de paqueterías en lenguaje natural
    intent_pkg = omni_temporal_control.process_hardware_chat_intent("instala el paquete colorama")
    assert intent_pkg is not None
    assert intent_pkg.get("action") == "package_install"
    assert "colorama" in intent_pkg.get("system_feedback", "")
