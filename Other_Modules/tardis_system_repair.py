#!/usr/bin/env python3
"""
TARDIS SYSTEM REPAIR · AUTO-CURACIÓN SOBERANA
=============================================
Pasada de reparación integral del nodo:

  * Verifica unidades systemd de usuario y reinicia las fallidas.
  * Compila todos los módulos Python críticos (sintaxis).
  * Verifica puertos y endpoints de los servicios FTL/TARDIS.
  * Comprueba disco, memoria, swap y presión de kernel.
  * Ejecuta un ciclo de Easy Touch.
  * Deja un informe JSON en data/system_repair_report.json.

No requiere root. Las reparaciones privilegiadas se dejan preparadas en
~/.config/tardis/privileged/ para aplicarse con una sola autenticación.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HOME = Path.home()
BASE = HOME / "Escritorio" / "GODWORKS SYSTEM"
FTL = HOME / ".ftl"
REPORT = BASE / "data" / "system_repair_report.json"
PRIV_DIR = HOME / ".config" / "tardis" / "privileged"

CRITICAL_UNITS = [
    "tardis.service",
    "tardis-supervisor.service",
    "tardis-singularity-kernel.service",
    "ftl-web-terminal.service",
    "ftl-web-portal.service",
    "ftl-public-gateway.service",
    "ftl-public-tunnel.service",
    "tardis-chatter-agent.service",
    "tardis-savemode.service",
    "tardis-easy-touch.service",
    "tardis4ever.service",
    "tardis-visual-intelligence.service",
    "tardis-video-pensante.service",
]

ENDPOINTS = [
    ("tardis_hub", "http://127.0.0.1:8757/health"),
    ("ftl_portal", "http://127.0.0.1:8765/api/status"),
    ("ftl_gateway", "http://127.0.0.1:7690/health"),
    ("chatter", "http://127.0.0.1:8795/status"),
    ("savemode", "http://127.0.0.1:8796/status"),
]

PY_DIRS = [FTL, BASE / "core", BASE / "modulos_ftl", BASE / "server"]


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run(cmd: List[str], timeout: float = 30.0) -> Dict[str, Any]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": res.returncode == 0,
            "rc": res.returncode,
            "stdout": (res.stdout or "")[-3000:],
            "stderr": (res.stderr or "")[-1500:],
            "cmd": " ".join(cmd),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rc": 1, "stdout": "", "stderr": str(exc), "cmd": " ".join(cmd)}


def check_units() -> Dict[str, Any]:
    result: Dict[str, Any] = {"checked": [], "restarted": [], "failed": []}
    for unit in CRITICAL_UNITS:
        st = run(["systemctl", "--user", "is-active", unit], timeout=8)
        active = (st.get("stdout") or "").strip()
        entry = {"unit": unit, "active": active}
        if active not in {"active", "activating"}:
            entry["restart"] = run(["systemctl", "--user", "restart", unit], timeout=45)
            if entry["restart"].get("ok"):
                result["restarted"].append(unit)
            else:
                result["failed"].append(unit)
        result["checked"].append(entry)
    return result


def compile_python() -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": True, "checked": 0, "errors": []}
    for directory in PY_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if any(part in {".venv-linux", ".venv-whatsapp", "__pycache__", "_selfmod_backups"} for part in path.parts):
                continue
            result["checked"] += 1
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
                compile(source, str(path), "exec")
            except Exception as exc:
                result["ok"] = False
                result["errors"].append({"file": str(path), "error": str(exc)[:500]})
    return result


def check_endpoints() -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name, url in ENDPOINTS:
        started = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TARDIS-SystemRepair/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                body = resp.read(2048)
                result[name] = {
                    "ok": 200 <= resp.status < 400,
                    "status": resp.status,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "bytes": len(body),
                }
        except Exception as exc:
            result[name] = {
                "ok": False,
                "error": str(exc)[:300],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
    return result


def system_health() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        import psutil

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        data = {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_percent": mem.percent,
            "memory_available_mb": round(mem.available / (1024 * 1024)),
            "swap_percent": psutil.swap_memory().percent,
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 1),
            "load": list(os.getloadavg()),
        }
        try:
            data["psi"] = {
                "cpu": Path("/proc/pressure/cpu").read_text().strip(),
                "memory": Path("/proc/pressure/memory").read_text().strip(),
                "io": Path("/proc/pressure/io").read_text().strip(),
            }
        except Exception:
            pass
    except Exception as exc:
        data = {"error": str(exc)}
    return data


def easy_touch_cycle() -> Dict[str, Any]:
    script = BASE / "core" / "easy_touch_agent.py"
    if not script.exists():
        return {"ok": False, "error": "easy_touch_agent.py no encontrado"}
    return run([sys.executable, str(script), "--cycle"], timeout=120)


def stage_privileged_repairs() -> Dict[str, Any]:
    """Prepara reparaciones que requieren root, sin ejecutarlas."""
    PRIV_DIR.mkdir(parents=True, exist_ok=True)
    udev_fixed = PRIV_DIR / "99-phone-harness-sovereign.rules"
    udev_fixed.write_text(
        """# ==============================================================================
# PHONE-HARNESS & MOBILE SOVEREIGN HARDWARE INTERFACE (KERNEL RING 0)
# Reglas UDEV corregidas: globs válidos (sin regex) para udev.
# ==============================================================================

# Android ADB / Fastboot / MTP / USB Debugging (Todos los vendors)
SUBSYSTEM=="usb", ENV{adb_user}="yes", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="04e8", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="2717", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="12d1", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="22b8", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0e8d", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", MODE="0666", GROUP="plugdev", TAG+="uaccess"

# Apple iOS / iPadOS (USBMUXD, AFC, Developer, Mirroring)
SUBSYSTEM=="usb", ATTR{idVendor}=="05ac", MODE="0666", GROUP="plugdev", TAG+="uaccess"

# Desactivar Autosuspend USB en dispositivos móviles
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
""",
        encoding="utf-8",
    )
    install = PRIV_DIR / "install_privileged_repairs.sh"
    install.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
sudo install -m 0644 "$(dirname "$0")/99-phone-harness-sovereign.rules" /etc/udev/rules.d/99-phone-harness-sovereign.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "Reparaciones privilegiadas aplicadas."
""",
        encoding="utf-8",
    )
    os.chmod(install, 0o755)
    return {
        "staged": True,
        "directory": str(PRIV_DIR),
        "apply": str(install),
        "requires": "sudo interactivo",
    }


def main() -> None:
    started = time.perf_counter()
    report: Dict[str, Any] = {
        "ok": True,
        "started_at": now(),
        "units": check_units(),
        "python": compile_python(),
        "endpoints": check_endpoints(),
        "health": system_health(),
        "easy_touch": easy_touch_cycle(),
        "privileged": stage_privileged_repairs(),
    }
    report["elapsed_s"] = round(time.perf_counter() - started, 2)
    report["finished_at"] = now()
    report["ok"] = bool(
        report["python"].get("ok")
        and not report["units"].get("failed")
        and all(v.get("ok") for v in report["endpoints"].values())
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
