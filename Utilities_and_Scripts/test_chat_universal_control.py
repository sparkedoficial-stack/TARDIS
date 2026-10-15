"""
tests/test_chat_universal_control.py - Suite de pruebas unitarias para el Motor Universal de Control por Chat
GODWORKS SYSTEM v26.4
"""

import time
import pytest
from omni_temporal_control import (
    process_hardware_chat_intent,
    process_agentic_chat,
    SYNC_HUB,
    CFG,
    HELP_CATALOG
)


# =========================================================================
# 1. PRUEBAS DE COMANDOS RÁPIDOS CON BARRA (SLASH COMMANDS)
# =========================================================================

def test_slash_lock_and_unlock():
    res_lock = process_hardware_chat_intent("/lock")
    assert res_lock is not None
    assert res_lock.get("action") == "lock_screen"
    assert res_lock.get("direct_return") is True
    assert "bloqueadas" in res_lock.get("system_feedback", "").lower()

    res_unlock = process_hardware_chat_intent("/unlock")
    assert res_unlock is not None
    assert res_unlock.get("action") == "unlock_screen"
    assert res_unlock.get("direct_return") is True
    assert "desbloqueadas" in res_unlock.get("system_feedback", "").lower()


def test_slash_reboot_and_screenshot():
    res_reb = process_hardware_chat_intent("/reboot")
    assert res_reb is not None
    assert res_reb.get("action") == "system_reboot"
    assert res_reb.get("direct_return") is True

    res_shot = process_hardware_chat_intent("/shot")
    assert res_shot is not None
    assert res_shot.get("action") == "screenshot"
    assert res_shot.get("direct_return") is True
    assert "screenshot_reciente.png" in res_shot.get("system_feedback", "")


def test_slash_volume_mute_keyboard_awake():
    res_vol = process_hardware_chat_intent("/vol 85")
    assert res_vol is not None
    assert res_vol.get("action") == "set_volume"
    assert res_vol.get("direct_return") is True
    assert "85%" in res_vol.get("system_feedback", "")

    res_mute = process_hardware_chat_intent("/mute")
    assert res_mute is not None
    assert res_mute.get("action") == "toggle_mute"
    assert res_mute.get("direct_return") is True

    res_kbd = process_hardware_chat_intent("/kbd 3")
    assert res_kbd is not None
    assert res_kbd.get("action") == "set_keyboard"
    assert res_kbd.get("direct_return") is True

    res_awake = process_hardware_chat_intent("/awake")
    assert res_awake is not None
    assert res_awake.get("action") == "keep_awake"
    assert res_awake.get("direct_return") is True


def test_slash_layout_switching():
    res_split = process_hardware_chat_intent("/split")
    assert res_split is not None
    assert res_split.get("action") == "set_layout"
    assert res_split.get("ui_action") == {"command": "set_view_mode", "params": {"mode": "split"}}
    assert res_split.get("direct_return") is True

    res_chat = process_hardware_chat_intent("/chat")
    assert res_chat is not None
    assert res_chat.get("action") == "set_layout"
    assert res_chat.get("ui_action") == {"command": "set_view_mode", "params": {"mode": "chat"}}
    assert res_chat.get("direct_return") is True

    res_avatar = process_hardware_chat_intent("/avatar")
    assert res_avatar is not None
    assert res_avatar.get("action") == "set_layout"
    assert res_avatar.get("ui_action") == {"command": "set_view_mode", "params": {"mode": "avatar"}}
    assert res_avatar.get("direct_return") is True


def test_slash_tab_and_clear():
    res_tab = process_hardware_chat_intent("/tab os")
    assert res_tab is not None
    assert res_tab.get("action") == "switch_tab"
    assert res_tab.get("ui_action") == {"command": "switch_tab", "params": {"tab": "tab-os"}}
    assert res_tab.get("direct_return") is True

    res_tab_radar = process_hardware_chat_intent("/tab radar")
    assert res_tab_radar is not None
    assert res_tab_radar.get("ui_action") == {"command": "switch_tab", "params": {"tab": "tab-radar"}}

    res_clear = process_hardware_chat_intent("/clear")
    assert res_clear is not None
    assert res_clear.get("action") == "clear_chat"
    assert res_clear.get("ui_action") == {"command": "clear_chat"}
    assert res_clear.get("direct_return") is True


def test_slash_cone_osc_eyes_emotions():
    assert process_hardware_chat_intent("/cone").get("ui_action") == {"command": "toggle_cone"}
    assert process_hardware_chat_intent("/osc").get("ui_action") == {"command": "toggle_oscilloscope"}
    assert process_hardware_chat_intent("/ojos").get("ui_action") == {"command": "toggle_eye_tracking"}
    assert process_hardware_chat_intent("/emociones").get("ui_action") == {"command": "toggle_vision_hud"}


def test_slash_terminals():
    res_sp = process_hardware_chat_intent("/term speak Test vocal remoto")
    assert res_sp.get("action") == "terminal_speak"
    assert res_sp.get("direct_return") is True
    assert "Test vocal remoto" in res_sp.get("system_feedback", "")

    res_vib = process_hardware_chat_intent("/term vibrate")
    assert res_vib.get("action") == "terminal_vibrate"
    assert res_vib.get("direct_return") is True

    res_gps = process_hardware_chat_intent("/term gps")
    assert res_gps.get("action") == "terminal_gps"
    assert res_gps.get("direct_return") is True

    res_rel = process_hardware_chat_intent("/term reload")
    assert res_rel.get("action") == "terminal_reload"
    assert res_rel.get("direct_return") is True

    res_list = process_hardware_chat_intent("/term list")
    assert res_list.get("action") == "terminal_master_control"
    assert res_list.get("direct_return") is True


def test_slash_packages_and_models():
    res_pkg_l = process_hardware_chat_intent("/pkg list")
    assert res_pkg_l.get("action") == "package_list"
    assert res_pkg_l.get("direct_return") is True

    res_mod_l = process_hardware_chat_intent("/model list")
    assert res_mod_l.get("action") == "model_list"
    assert res_mod_l.get("direct_return") is True

    res_mod_sw = process_hardware_chat_intent("/model hermes3:8b")
    assert res_mod_sw.get("action") == "switch_model"
    assert res_mod_sw.get("direct_return") is True
    assert CFG.get("model") == "hermes3:8b"


def test_slash_auto_and_vault():
    res_auto = process_hardware_chat_intent("/auto status")
    assert res_auto.get("action") == "autonomous_status"
    assert res_auto.get("direct_return") is True

    res_cyc = process_hardware_chat_intent("/auto ciclo")
    assert res_cyc.get("action") == "autonomous_cycle"
    assert res_cyc.get("direct_return") is True

    res_act = process_hardware_chat_intent("/autoactivate")
    assert res_act.get("action") == "auto_activate_all_buttons"
    assert res_act.get("direct_return") is True

    res_v = process_hardware_chat_intent("/vault")
    assert res_v.get("action") == "vault_status"
    assert res_v.get("direct_return") is True


def test_slash_help():
    res_help = process_hardware_chat_intent("/ayuda")
    assert res_help.get("action") == "help_catalog"
    assert res_help.get("direct_return") is True
    assert "CATÁLOGO SOBERANO DE CONTROL POR CHAT" in res_help.get("system_feedback", "")


# =========================================================================
# 2. PRUEBAS DE LENGUAJE NATURAL EN ESPAÑOL
# =========================================================================

def test_natural_language_os():
    assert process_hardware_chat_intent("bloquea la pantalla").get("action") == "lock_screen"
    assert process_hardware_chat_intent("desbloquea la pantalla").get("action") == "unlock_screen"
    assert process_hardware_chat_intent("toma una captura de pantalla").get("action") == "screenshot"
    assert process_hardware_chat_intent("sube el volumen al 75%").get("action") == "set_volume"
    assert process_hardware_chat_intent("silencia el audio").get("action") == "toggle_mute"
    assert process_hardware_chat_intent("no te duermas").get("action") == "keep_awake"


def test_natural_language_ui():
    assert process_hardware_chat_intent("modo dividido").get("ui_action") == {"command": "set_view_mode", "params": {"mode": "split"}}
    assert process_hardware_chat_intent("pantalla completa de chat").get("ui_action") == {"command": "set_view_mode", "params": {"mode": "chat"}}
    assert process_hardware_chat_intent("holograma completo").get("ui_action") == {"command": "set_view_mode", "params": {"mode": "avatar"}}
    assert process_hardware_chat_intent("abre la pestaña de control os").get("ui_action") == {"command": "switch_tab", "params": {"tab": "tab-os"}}
    assert process_hardware_chat_intent("limpia el chat").get("ui_action") == {"command": "clear_chat"}


def test_natural_language_networks_and_terminals():
    assert process_hardware_chat_intent("escanea redes wifi circundantes").get("action") == "wifi_scan"
    assert process_hardware_chat_intent("control absoluto de todas las terminales").get("action") == "terminal_master_control"
    assert process_hardware_chat_intent("habla en las terminales: Orden confirmada").get("action") == "terminal_speak"
    assert process_hardware_chat_intent("haz vibrar los teléfonos").get("action") == "terminal_vibrate"
    assert process_hardware_chat_intent("solicita gps").get("action") == "terminal_gps"


def test_natural_language_autonomy_vault_and_help():
    assert process_hardware_chat_intent("control autonomo").get("action") == "autonomous_controller_activate"
    assert process_hardware_chat_intent("fuerza un ciclo").get("action") == "autonomous_cycle"
    assert process_hardware_chat_intent("activa todos los botones").get("action") == "auto_activate_all_buttons"
    assert process_hardware_chat_intent("memoria profunda").get("action") == "vault_status"
    assert process_hardware_chat_intent("que comandos puedo pedirte").get("action") == "help_catalog"


# =========================================================================
# 3. PRUEBA DE EJECUCIÓN DIRECTA INSTANTÁNEA (< 0.2s) EN PROCESS_AGENTIC_CHAT
# =========================================================================

def test_instant_chat_execution():
    t0 = time.time()
    res = process_agentic_chat(message="/lock", history=[])
    elapsed = time.time() - t0

    assert res.get("ok") is True
    assert res.get("provider") == "GIA Direct Kernel"
    assert res.get("action") == "lock_screen"
    assert elapsed < 0.2, f"La ejecución directa tomó {elapsed}s, debería ser instantánea (<0.2s)"


def test_instant_chat_natural_language():
    t0 = time.time()
    res = process_agentic_chat(message="modo dividido", history=[])
    elapsed = time.time() - t0

    assert res.get("ok") is True
    assert res.get("provider") == "GIA Direct Kernel"
    assert res.get("action") == "set_layout"
    assert res.get("ui_action") == {"command": "set_view_mode", "params": {"mode": "split"}}
    assert elapsed < 0.2, f"La ejecución directa tomó {elapsed}s, debería ser instantánea (<0.2s)"
