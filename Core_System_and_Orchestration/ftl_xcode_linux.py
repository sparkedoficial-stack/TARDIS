"""
modulos_ftl/ftl_xcode_linux.py - Módulo FTL Soberano de Desarrollo y Control Apple iOS (Xcode para Linux)
========================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Todas las herramientas con las que tiene acceso agy, tardis, asi como ftl deben tener
control y saber de su conocimiento para poder emplearlas en sus sistemas de forma individual."

Este módulo integra el toolchain de Xcode para Linux (/usr/local/bin/xcode-linux, /opt/xcode-linux)
en el Master Hub FTL para:
1. Inspección de binarios Mach-O y paquetes IPA (usando el puente REA).
2. Detección y gestión de dispositivos Apple iOS / iPadOS por USB y Wi-Fi.
3. Despliegue, instalación y transferencia de archivos vía Apple File Conduit (AFC).
4. Compilación y firma de aplicaciones iOS directamente bajo entorno Linux.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("FTL.XcodeLinux")

XCODE_BIN = "/usr/local/bin/xcode-linux"
XCODE_ROOT = "/opt/xcode-linux"


class FtlXcodeLinux:
    """
    Módulo oficial FTL para desarrollo, análisis, firmado y despliegue iOS en Linux.
    Totalmente integrado en el Master Hub FTL y la arquitectura TARDIS.
    """

    def __init__(self):
        self.name = "xcode_linux"
        self.version = "1.0.0"
        self.bin_path = XCODE_BIN
        self.root_path = XCODE_ROOT

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada principal compatible con Master Hub FTL.
        Acciones soportadas:
          - 'status' o 'info': Estado del toolchain de desarrollo y dispositivos conectados.
          - 'devices': Lista detallada de dispositivos iOS/iPadOS conectados.
          - 'apps': Lista aplicaciones de usuario instaladas en el dispositivo.
          - 'inspect': Análisis estático y estructural REA de un IPA o binario Mach-O.
          - 'install': Despliega e instala un paquete IPA en el dispositivo.
          - 'push': Transfiere archivos al almacenamiento interno del dispositivo (AFC).
          - 'console': Captura logs del sistema del dispositivo (syslog).
          - 'build': Compila un proyecto iOS en paquete .ipa.
        """
        action = action.lower().strip()
        try:
            if action in ("status", "info"):
                return self.get_toolchain_status()
            elif action == "devices":
                return self.list_connected_devices()
            elif action == "apps":
                udid = kwargs.get("udid")
                return self.list_installed_apps(udid=udid)
            elif action == "inspect":
                target = kwargs.get("target") or kwargs.get("path")
                if not target:
                    return {"status": "error", "error": "Parámetro 'target' requerido."}
                return self.inspect_binary(target)
            elif action == "install":
                ipa = kwargs.get("ipa") or kwargs.get("path")
                udid = kwargs.get("udid")
                if not ipa:
                    return {"status": "error", "error": "Parámetro 'ipa' requerido."}
                return self.install_ipa(ipa, udid=udid)
            elif action == "push":
                src = kwargs.get("file") or kwargs.get("src")
                dst = kwargs.get("dest") or kwargs.get("remote") or "/Downloads"
                udid = kwargs.get("udid")
                if not src:
                    return {"status": "error", "error": "Parámetro 'file' requerido."}
                return self.push_file(src, dst, udid=udid)
            elif action == "build":
                project_dir = kwargs.get("project_dir") or kwargs.get("path")
                out_dir = kwargs.get("out") or kwargs.get("out_dir")
                if not project_dir:
                    return {"status": "error", "error": "Parámetro 'project_dir' requerido."}
                return self.build_app(project_dir, out_dir=out_dir)
            elif action == "console":
                udid = kwargs.get("udid")
                lines = int(kwargs.get("lines", 50))
                return self.get_console_logs(udid=udid, lines=lines)
            else:
                return {
                    "status": "error",
                    "error": f"Acción '{action}' no reconocida.",
                    "available_actions": ["status", "devices", "apps", "inspect", "install", "push", "console", "build"]
                }
        except Exception as e:
            logger.error(f"[XCODE-LINUX] Error ejecutando acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    # Alias para compatibilidad con Master Hub
    execute = run

    def _run_cli(self, args: List[str], timeout: float = 60.0) -> Tuple[int, str, str]:
        """Ejecuta xcode-linux de forma síncrona y segura."""
        cmd = [self.bin_path] + args
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Timeout ({timeout}s) ejecutando xcode-linux."
        except Exception as e:
            return 1, "", str(e)

    def get_toolchain_status(self) -> Dict[str, Any]:
        """Consulta el estado de los componentes y dispositivos mediante xcode-linux info."""
        rc, out, err = self._run_cli(["info"], timeout=15)
        if rc == 0:
            return {
                "status": "ok",
                "toolchain": "Xcode for Linux v1.0.0",
                "details": out
            }
        return {"status": "error", "rc": rc, "error": err or out}

    def list_connected_devices(self) -> Dict[str, Any]:
        """Obtiene la lista estructurada de dispositivos Apple conectados."""
        rc, out, err = self._run_cli(["devices"], timeout=15)
        return {
            "status": "ok" if rc == 0 else "error",
            "output": out or err
        }

    def list_installed_apps(self, udid: Optional[str] = None) -> Dict[str, Any]:
        """Lista las aplicaciones instaladas en el dispositivo."""
        args = ["apps"]
        if udid:
            args.extend(["--udid", udid])
        rc, out, err = self._run_cli(args, timeout=30)
        return {
            "status": "ok" if rc == 0 else "error",
            "output": out or err
        }

    def inspect_binary(self, path: str) -> Dict[str, Any]:
        """Analiza un paquete IPA o binario Mach-O con REA."""
        rc, out, err = self._run_cli(["inspect", path], timeout=45)
        return {
            "status": "ok" if rc == 0 else "error",
            "target": path,
            "report": out or err
        }

    def install_ipa(self, ipa_path: str, udid: Optional[str] = None) -> Dict[str, Any]:
        """Instala un archivo IPA firmado en el dispositivo."""
        args = ["install", ipa_path]
        if udid:
            args.extend(["--udid", udid])
        rc, out, err = self._run_cli(args, timeout=90)
        return {
            "status": "ok" if rc == 0 else "error",
            "output": out or err
        }

    def push_file(self, src: str, dst: str = "/Downloads", udid: Optional[str] = None) -> Dict[str, Any]:
        """Copia un archivo por bus de hardware AFC al almacenamiento interno del iPad."""
        args = ["push", src, dst]
        if udid:
            args.extend(["--udid", udid])
        rc, out, err = self._run_cli(args, timeout=60)
        return {
            "status": "ok" if rc == 0 else "error",
            "src": src,
            "dst": dst,
            "output": out or err
        }

    def build_app(self, project_dir: str, out_dir: Optional[str] = None) -> Dict[str, Any]:
        """Compila un proyecto de aplicación iOS."""
        args = ["build", project_dir]
        if out_dir:
            args.extend(["--out", out_dir])
        rc, out, err = self._run_cli(args, timeout=120)
        return {
            "status": "ok" if rc == 0 else "error",
            "project_dir": project_dir,
            "output": out or err
        }

    def get_console_logs(self, udid: Optional[str] = None, lines: int = 50) -> Dict[str, Any]:
        """Captura un fragmento del registro syslog del dispositivo."""
        # Se invoca pymobiledevice3 directamente con límite de tiempo
        try:
            cmd = ["pymobiledevice3", "syslog", "live"]
            if udid:
                cmd.extend(["--udid", udid])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            import time
            time.sleep(2.0)
            proc.terminate()
            out, err = proc.communicate(timeout=3.0)
            log_lines = out.splitlines()[-lines:] if out else []
            return {"status": "ok", "lines_count": len(log_lines), "logs": log_lines}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Instancia singleton
_xcode_instance: Optional[FtlXcodeLinux] = None

def get_xcode_linux() -> FtlXcodeLinux:
    global _xcode_instance
    if _xcode_instance is None:
        _xcode_instance = FtlXcodeLinux()
    return _xcode_instance


if __name__ == "__main__":
    xcode = FtlXcodeLinux()
    print("=== FTL XCODE LINUX :: ESTADO DEL TOOLCHAIN ===")
    res = xcode.get_toolchain_status()
    print(res.get("details"))
