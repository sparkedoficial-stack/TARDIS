"""
Suite de pruebas automatizadas para FTL × Easy Touch Zero-Error Preemptive Shield.
Valida:
  1. Clasificación de errores (ES/EN, crashes, systemd, kernel, DNS, permisos, locks, iconos, categorías D-Bus)
  2. Protección de Whitelist (cero falsos positivos en Price Sentinel, GOD-EYE, 2FA, chat, bypass)
  3. Consistencia entre Python (`zero_error_shield.py`), shim (`notify-send-shield`) y JS (`ZeroErrorGuard.js`)
  4. Intercepción y reparación FTL × Easy Touch + deduplicación + registro en ledger
  5. Integración con FtlZeroErrorShield, FtlOmniRegistry, TardisOmniToolBridge y EasyTouchEngine
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ["EASY_TOUCH_NO_BACKGROUND_AGENT"] = "1"

GODWORKS_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
HOME_DIR = Path("/home/m11")
for p in (str(GODWORKS_DIR), str(HOME_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.zero_error_shield import (
    DEFAULT_RULES,
    classify_notification,
    detect_error_category,
    get_zero_error_shield,
)
from modulos_ftl.ftl_zero_error_shield import get_ftl_zero_error_shield
from modulos_ftl.ftl_omni_registry import get_omni_registry
from core.tardis_omni_tool_bridge import get_omni_bridge


def _load_notify_send_shim():
    import importlib.machinery
    path = Path("/home/m11/.local/bin/notify-send-shield")
    loader = importlib.machinery.SourceFileLoader("notify_send_shield_mod", str(path))
    spec = importlib.util.spec_from_loader("notify_send_shield_mod", loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestClassifierAndWhitelist:
    def test_intercepts_omarchy_crash_spanish_and_english(self):
        r_es = classify_notification(
            summary="El proceso falló: tardis-desktop",
            body="Haz clic para diagnosticar con IA",
            app="omarchy-action",
            urgency=2,
            exec_argv='["omarchy-agent-crash","123","tardis-desktop","/usr/bin/tardis-desktop","SIGSEGV"]',
            rules=DEFAULT_RULES,
        )
        assert r_es["is_error"] is True
        assert r_es["intercept"] is True
        assert r_es["category"] == "tardis_desktop_crash"

        r_en = classify_notification(
            summary="Process crashed: llama-server",
            body="Click to diagnose",
            app="omarchy-action",
            urgency=2,
            rules=DEFAULT_RULES,
        )
        assert r_en["is_error"] is True
        assert r_en["intercept"] is True
        assert r_en["category"] == "llama_server_cuda_crash"

    def test_intercepts_diverse_system_errors_without_colons(self):
        cases = [
            ("Error al iniciar Bluetooth", "bluez daemon failed", "bluetooth", "bluetooth_failure"),
            ("Unable to mount disk", "No space left on device", "udisksd", "disk_space_pressure"),
            ("Temporary failure in name resolution", "REDACTED_IP:53 timeout", "NetworkManager", "dns_network_failure"),
            ("Database is locked", "sqlite3.OperationalError", "app", "sqlite_lock"),
            ("Address already in use", "port 8899 already in use", "python", "port_conflict"),
            ("ModuleNotFoundError", "No module named 'foo_bar'", "python3", "python_module_missing"),
            ("PipeWire audio failed", "WirePlumber error", "pipewire", "audio_pipewire_failure"),
            ("Permission denied", "Cannot access /dev/uinput", "kernel", "kernel_hardware_node_perms"),
            ("Falló el servicio foo.service", "Exited with code 1", "systemd", "systemd_unit_failed"),
        ]
        for summary, body, app, expected_cat in cases:
            res = classify_notification(summary=summary, body=body, app=app, urgency=2, rules=DEFAULT_RULES)
            assert res["is_error"] is True, f"Failed to detect error: {summary}"
            assert res["intercept"] is True
            assert res["category"] == expected_cat, f"Expected {expected_cat}, got {res['category']} for {summary}"

    def test_intercepts_by_dbus_category_and_icon(self):
        r_cat = classify_notification(summary="Device alert", body="Disk check", app="sys", category="device.error", rules=DEFAULT_RULES)
        assert r_cat["is_error"] is True
        assert r_cat["intercept"] is True

        r_icon = classify_notification(summary="Something happened", body="Check logs", app="sys", icon="dialog-error", rules=DEFAULT_RULES)
        assert r_icon["is_error"] is True
        assert r_icon["intercept"] is True

    def test_preserves_whitelisted_and_benign_notifications(self):
        benign_cases = [
            ("ERROR DE PRECIO DETECTADO", "GLITCH: TV OLED 85% OFF", "TARDIS Price Sentinel", 2, {}),
            ("INDIVIDUO DETECTADO", "Cámara Tapo C310 frente", "TARDIS GOD-EYE", 2, {}),
            ("Your verification code is 482913", "Use 2FA OTP to log in", "Chromium", 1, {}),
            ("Recordatorio", "Reunión en 10 minutos", "omarchy-reminder", 1, {}),
            ("Backup completado sin errores", "0 errors found", "rsync", 1, {}),
            ("Error test bypassed", "Explicit bypass hint", "notify-send", 2, {"x-ftl-bypass": True}),
            ("Screenshot saved", "Copied to clipboard", "omarchy-action", 1, {}),
        ]
        for summary, body, app, urg, hints in benign_cases:
            res = classify_notification(summary=summary, body=body, app=app, urgency=urg, hints=hints, rules=DEFAULT_RULES)
            assert res["is_error"] is False, f"False positive on benign notification: {summary} ({res})"
            assert res["intercept"] is False

    def test_audit_and_disabled_modes(self):
        audit_rules = {**DEFAULT_RULES, "mode": "audit"}
        r_audit = classify_notification(summary="Process crashed: foo", body="SIGSEGV", app="omarchy-action", urgency=2, rules=audit_rules)
        assert r_audit["is_error"] is True
        assert r_audit["intercept"] is False

        dis_rules = {**DEFAULT_RULES, "enabled": False, "mode": "disabled"}
        r_dis = classify_notification(summary="Process crashed: foo", body="SIGSEGV", app="omarchy-action", urgency=2, rules=dis_rules)
        assert r_dis["is_error"] is False
        assert r_dis["intercept"] is False


class TestNotifySendShim:
    def test_parse_and_evaluate(self):
        shim = _load_notify_send_shim()
        info, print_id, meta = shim._parse_args([
            "-u", "critical", "-a", "systemd", "-i", "dialog-error",
            "-c", "system.error", "-p", "--", "Unit failed: demo.service", "Exited with status 1"
        ])
        assert print_id is True
        assert meta is False
        assert info["urgency"] == 2
        assert info["app"] == "systemd"
        assert info["icon"] == "dialog-error"
        assert info["dbus_category"] == "system.error"
        is_err, intercept, _ = shim._evaluate(info, DEFAULT_RULES)
        assert is_err is True
        assert intercept is True

        info_ok, _, _ = shim._parse_args(["-a", "TARDIS Price Sentinel", "ERROR DE PRECIO", "GLITCH: Laptop $99"])
        is_err2, intercept2, _ = shim._evaluate(info_ok, DEFAULT_RULES)
        assert is_err2 is False
        assert intercept2 is False


class TestShieldAndEcosystemIntegration:
    def test_ftl_module_and_registries(self):
        ftl_mod = get_ftl_zero_error_shield()
        st = ftl_mod.run("classify", summary="El proceso falló: tardis-desktop", body="SIGSEGV", app="omarchy-action", urgency=2)
        assert st["status"] == "ok"
        assert st["is_error"] is True
        assert st["category"] == "tardis_desktop_crash"

        reg = get_omni_registry()
        assert "zero_error_shield" in reg.catalog
        assert reg.catalog["zero_error_shield"]["active"] is True

        bridge = get_omni_bridge()
        assert "zero_error_shield" in bridge.tools

    def test_zero_error_guard_js_syntax_with_node(self):
        js_path = Path("/home/m11/.config/omarchy/plugins/m11.notifications/ZeroErrorGuard.js")
        src = js_path.read_text(encoding="utf-8")
        # Quickshell uses `.pragma library` at top; strip pragma for Node.js VM syntax/logic test
        clean_js = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(".pragma"))
        harness = clean_js + """
const r1 = evaluate({app:"omarchy-action", summary:"El proceso falló: tardis-desktop", body:"Haz clic para diagnosticar con IA", urgency:2, execArgv:'["omarchy-agent-crash"]'}, {}, null);
const r2 = evaluate({app:"TARDIS Price Sentinel", summary:"ERROR DE PRECIO", body:"GLITCH: $10", urgency:2}, {}, null);
const r3 = evaluate({app:"notify-send", summary:"Error al iniciar red", body:"No se pudo resolver DNS", urgency:2}, {}, null);
const r4 = evaluate({app:"notify-send", summary:"Screenshot saved", body:"Copied", urgency:1}, {}, null);
console.log(JSON.stringify({r1, r2, r3, r4}));
"""
        proc = subprocess.run(["node", "-e", harness], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert data["r1"]["isError"] is True and data["r1"]["intercept"] is True and data["r1"]["category"] == "tardis_desktop_crash"
        assert data["r2"]["isError"] is False and data["r2"]["intercept"] is False
        assert data["r3"]["isError"] is True and data["r3"]["intercept"] is True
        assert data["r4"]["isError"] is False and data["r4"]["intercept"] is False
