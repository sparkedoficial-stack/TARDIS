"""
core/tardis_pocket_ota_manager.py - Gestor de Actualizaciones Inalámbricas OTA para TARDIS POCKET
=================================================================================================
Permite al nodo central de TARDIS desplegar actualizaciones de código, paquetes y
configuraciones de sistema hacia TARDIS POCKET de forma 100% inalámbrica (Over-The-Air)
sin requerir conexión física por cable:
  1. Conexión y auto-descubrimiento dinámico de IP sobre Wi-Fi (Hotspot 10.42.0.x o LAN).
  2. Sincronización completa de la suite autónoma local (demonio, scripts de arranque, UI offline).
  3. Despacho y ejecución de comandos remotos privilegiados vía ADB.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TardisPocketOTA")

BASE_DIR = Path(__file__).resolve().parent.parent
MOBILE_DIR = BASE_DIR / "mobile_terminal"
DIST_DIR = BASE_DIR / "tardis_custom_rom" / "dist"

ADB_BIN = "/tmp/platform-tools/adb" if os.path.exists("/tmp/platform-tools/adb") else "adb"


class TardisPocketOTAManager:
    """Gestor de despliegue inalámbrico OTA hacia TARDIS POCKET."""

    _instance: Optional[TardisPocketOTAManager] = None

    @classmethod
    def get_instance(cls) -> TardisPocketOTAManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, target_ip: str = "", target_port: int = 5555):
        self.target_ip = target_ip
        self.target_port = target_port

    def discover_device_ip(self) -> str:
        """Descubre automáticamente la IP actual de TARDIS POCKET."""
        # 1. Probar la última IP reportada por telemetría
        try:
            from core.tardis_pocket_tunnel_bridge import TardisPocketBridge
            bridge = TardisPocketBridge.get_instance()
            last_ip = bridge.last_telemetry.get("client_ip", "").strip()
            if last_ip and last_ip not in ("REDACTED_IP", "localhost"):
                return last_ip
        except Exception:
            pass

        # 2. Probar IPs de la tabla ARP en la interfaz hotspot o LAN
        candidates: List[str] = []
        try:
            res = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.splitlines():
                if "REACHABLE" in line or "DELAY" in line or "STALE" in line:
                    parts = line.split()
                    if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                        ip = parts[0]
                        if ip.startswith("10.42.0."):
                            # Prioridad máxima: clientes conectados al Hotspot TimeMachine
                            candidates.insert(0, ip)
                        elif ip.startswith("192.168."):
                            candidates.append(ip)
        except Exception:
            pass

        if candidates:
            return candidates[0]

        # 3. Fallback a dirección por defecto
        return self.target_ip or "REDACTED_IP"

    def is_device_connected(self) -> bool:
        """Comprueba si TARDIS POCKET ya está conectado por USB o Wi-Fi."""
        try:
            res = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, timeout=3)
            for line in res.stdout.splitlines():
                if "ZY222ZXWPP" in line and "device" in line:
                    return True
                if self.target_ip and self.target_ip in line and "device" in line:
                    return True
        except Exception:
            pass
        return False

    def connect_wireless(self, override_ip: Optional[str] = None) -> bool:
        """Establece conexión ADB inalámbrica con TARDIS POCKET."""
        if self.is_device_connected():
            return True
        ip = override_ip or self.discover_device_ip()
        target = f"{ip}:{self.target_port}"
        try:
            res = subprocess.run([ADB_BIN, "connect", target], capture_output=True, text=True, timeout=4)
            out = res.stdout.strip()
            logger.info(f"ADB wireless connect to {target}: {out}")
            if "connected" in out.lower() or self.is_device_connected():
                self.target_ip = ip
                return True
        except Exception as e:
            logger.error(f"Error conectando inalámbricamente a TARDIS POCKET ({target}): {e}")
        return False

    def deploy_full_autonomous_suite(self) -> Dict[str, Any]:
        """Despliega la suite completa autónoma (demonio + KAIJU-NANO + UI offline + configs) a TARDIS POCKET."""
        if not self.is_device_connected() and not self.connect_wireless():
            return {
                "success": False,
                "error": f"No se pudo conectar por ADB a TARDIS POCKET en {self.target_ip}:{self.target_port}"
            }

        files_to_push = [
            "tardis_kaiju_pocket_engine.py",
            "tardis_pocket_daemon.py",
            "tardis_pocket_daemon.sh",
            "tardis_pocket.html",
            "sw.js",
            "manifest.json",
            "tardis_terminal_config.json",
            "start_tardis_terminal.sh",
            "setup_termux_boot.sh"
        ]

        # Crear directorio destino en el teléfono
        subprocess.run([ADB_BIN, "shell", "mkdir -p /sdcard/tardis"], capture_output=True, text=True, timeout=5)

        deployed: List[str] = []
        errors: List[str] = []

        for fname in files_to_push:
            src = MOBILE_DIR / fname
            if src.exists():
                cmd = [ADB_BIN, "push", str(src), f"/sdcard/tardis/{fname}"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    deployed.append(fname)
                else:
                    errors.append(f"{fname}: {res.stderr.strip()}")

        # Dar permisos de ejecución a los scripts
        subprocess.run([ADB_BIN, "shell", "chmod +x /sdcard/tardis/*.sh 2>/dev/null || true"], capture_output=True, timeout=5)

        logger.info(f"✓ Suite autónoma desplegada a TARDIS POCKET: {len(deployed)} archivos sincronizados.")
        return {
            "success": len(errors) == 0,
            "deployed": deployed,
            "errors": errors,
            "target_ip": self.target_ip
        }

    def execute_remote_command(self, command: str) -> Dict[str, Any]:
        """Ejecuta un comando de administración remota en TARDIS POCKET."""
        if not self.connect_wireless():
            return {"success": False, "error": f"Dispositivo no alcanzable en {self.target_ip}"}
        try:
            cmd = [ADB_BIN, "shell", command]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
