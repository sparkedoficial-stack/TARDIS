"""
tests/test_zero_error_shield.py — Suite de verificación integral para FTL × Easy Touch Zero-Error Shield.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
for p in (str(BASE_DIR), "/home/m11"):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.zero_error_shield import (
    DEFAULT_RULES,
    SHIELD_UNIX_SOCKET,
    classify_notification,
    detect_error_category,
    get_zero_error_shield,
)


def test_classify_system_errors_intercepted():
    cases = [
        ("El proceso falló: tardis-desktop", "Haz clic para diagnosticar con IA", "omarchy-action", 2, "", "", "tardis_desktop_crash"),
        ("Process crashed: llama-server", "SIGSEGV in ggml-cuda", "omarchy-action", 2, "", "", "llama_server_cuda_crash"),
        ("Failed to start foo.service", "Main process exited, status=203/EXEC", "systemd", 2, "", "", "systemd_unit_failed"),
        ("Out of memory", "OOM-killer invoked on worker", "kernel", 2, "", "", "oom_memory_pressure"),
        ("Network error", "Temporary failure in name resolution REDACTED_IP:53", "NetworkManager", 1, "network.error", "network-error", "dns_network_failure"),
        ("Disk Full", "No space left on device /", "udisksd", 2, "device.error", "dialog-error", "disk_space_pressure"),
        ("Permission denied", "EACCES: /dev/uinput", "notify-send", 1, "", "", "kernel_hardware_node_perms"),
        ("Database is locked", "sqlite3.OperationalError: database is locked", "app", 1, "", "", "sqlite_lock"),
        ("PipeWire audio failed", "wireplumber connection error", "pipewire", 1, "", "", "audio_pipewire_failure"),
        ("Pacman error", "unable to lock database /var/lib/pacman/db.lck", "pacman", 1, "", "", "pacman_lock"),
    ]
    for summary, body, app, urg, dcat, icon, expected_cat in cases:
        res = classify_notification(
            summary=summary, body=body, app=app, urgency=urg,
            category=dcat, icon=icon, rules=DEFAULT_RULES
        )
        assert res["is_error"] is True, f"Debió clasificar como error: {summary}"
        assert res["intercept"] is True, f"Debió interceptar: {summary}"
        assert res["category"] == expected_cat, f"Esperado {expected_cat}, obtenido {res['category']}"


def test_whitelist_prevents_false_positives():
    benign_cases = [
        ("🚨 ERROR DE PRECIO / GLITCH: Liverpool", "Stellar Blade $699 MXN", "TARDIS Price Sentinel", 2),
        ("🚨 INDIVIDUO DETECTADO · GOD-EYE", "Cámara Tapo C310 detectó 1 individuo", "TARDIS GOD-EYE", 2),
        ("Your verification code", "Use code 482913 to sign in", "Signal", 1),
        ("Recordatorio", "Reunión en 15 minutos", "omarchy-reminder", 1),
        ("Nueva canción", "Reproduciendo soundtrack synthwave", "TARDIS Music Maestro", 0),
        ("Compilación completada", "0 errors, 12 tests passed", "cargo", 1),
        ("Error de prueba con bypass", "Permitiendo paso explícito", "notify-send", 2),
    ]
    for idx, (summary, body, app, urg) in enumerate(benign_cases):
        hints = {"x-ftl-bypass": True} if idx == len(benign_cases) - 1 else {}
        res = classify_notification(
            summary=summary, body=body, app=app, urgency=urg, hints=hints, rules=DEFAULT_RULES
        )
        assert res["intercept"] is False, f"Falso positivo en notificación legítima: {summary} -> {res}"


def test_real_permission_healing_end_to_end():
    shield = get_zero_error_shield()
    with tempfile.NamedTemporaryFile(prefix="zes_perm_", suffix=".sh", delete=False) as tf:
        tpath = Path(tf.name)
    try:
        os.chmod(tpath, 0o000)
        res = shield.handle_event(
            {
                "summary": f"Permission denied: {tpath}",
                "body": f"PermissionError executing {tpath}",
                "app": "pytest",
                "urgency": 2,
                "force_repair": True,
            },
            source="pytest_e2e",
            suppressed_before_display=True,
            async_repair=False,
        )
        assert res["ok"] is True
        assert res["healed"] is True
        assert res["verified"] is True
        mode = oct(tpath.stat().st_mode)[-3:]
        assert mode == "755", f"Se esperaba permiso 755 reparado, obtenido {mode}"
    finally:
        tpath.unlink(missing_ok=True)


def test_daemon_ipc_unix_and_ftl_module():
    # Verifica el módulo FTL directamente y el socket UNIX si el demonio está corriendo
    from modulos_ftl.ftl_zero_error_shield import get_ftl_zero_error_shield

    mod = get_ftl_zero_error_shield()
    st = mod.run("status")
    assert st["status"] == "ok"

    if SHIELD_UNIX_SOCKET.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(SHIELD_UNIX_SOCKET))
            s.sendall(json.dumps({"action": "ping"}).encode("utf-8"))
            s.shutdown(socket.SHUT_WR)
            data = json.loads(s.recv(4096).decode("utf-8"))
            assert data["ok"] is True
            assert data["mode"] == "enforce"


def test_notify_send_shim_blocks_error_before_dbus():
    shim = Path("/usr/local/bin/notify-send")
    if not shim.exists():
        return
    # Invocar notify-send con un error real de prueba y verificar que devuelve 0 con print-id=0 (interceptado pre-D-Bus)
    proc = subprocess.run(
        [str(shim), "-p", "-u", "critical", "-a", "systemd", "Failed to start synthetic-test.service", "Unit synthetic-test.service failed"],
        capture_output=True, text=True, timeout=5,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "0", f"El shim debió interceptar pre-D-Bus y devolver id 0, devolvió: {proc.stdout!r}"
