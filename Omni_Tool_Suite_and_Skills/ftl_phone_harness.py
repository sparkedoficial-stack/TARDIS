"""
modulos_ftl/ftl_phone_harness.py - Módulo FTL Soberano de Control de Dispositivos Móviles
========================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Integra phone-harness a nivel de Kernel y Master Hub FTL para control bidireccional
de teléfonos (Android vía ADB, iOS/iPadOS vía USBMUXD/Mirroring, y Cloud Phones).
"""

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class FtlPhoneHarness:
    """
    Módulo oficial FTL para control autónomo y por voz de dispositivos móviles.
    Integrado directamente en el Master Hub FTL y la red neuronal TARDIS.
    """

    def __init__(self):
        self.name = "phone_harness"
        self.version = "0.3.2"
        self._ensure_environment()

    def _ensure_environment(self):
        """Verifica que el entorno de ejecución tenga acceso a phone-harness y ADB."""
        local_bin = "/home/timemachine/.local/bin"
        if local_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada principal compatible con Master Hub FTL.
        Acciones soportadas:
          - 'status' / 'telemetry': Escanea y reporta estado de teléfonos conectados.
          - 'ensure_device': Valida conexión activa con el dispositivo.
          - 'screen': Lee textos visibles en pantalla (OCR o Accessibility tree).
          - 'screenshot': Captura la pantalla a un archivo PNG.
          - 'tap': Pulsa coordenadas (x, y).
          - 'tap_text': Busca un texto y pulsa sobre él.
          - 'type_text': Escribe texto en el campo activo.
          - 'open_app': Abre una app por nombre.
          - 'home': Vuelve a la pantalla principal.
          - 'back': Ejecuta retroceso.
          - 'doctor': Ejecuta diagnóstico de subsistemas.
          - 'exec_code': Ejecuta código Python interactivo en el harness.
        """
        action = action.lower()
        try:
            if action in ("status", "telemetry"):
                return self.get_status()
            elif action == "doctor":
                return self.run_doctor(kwargs.get("platform"))
            elif action == "ensure_device":
                return self._call_helper("ensure_device")
            elif action == "screen":
                min_conf = kwargs.get("min_confidence", 0.3)
                return self._call_helper("screen", min_confidence=min_conf)
            elif action == "screenshot":
                path = kwargs.get("path")
                return self._call_helper("screenshot", path=path)
            elif action == "tap":
                x = kwargs.get("x")
                y = kwargs.get("y")
                return self._call_helper("tap", x=x, y=y)
            elif action == "tap_text":
                query = kwargs.get("query")
                exact = kwargs.get("exact", False)
                return self._call_helper("tap_text", query=query, exact=exact)
            elif action == "type_text":
                text = kwargs.get("text", "")
                return self._call_helper("type_text", text=text)
            elif action == "open_app":
                name = kwargs.get("name", "")
                return self._call_helper("open_app", name=name)
            elif action == "home":
                return self._call_helper("home")
            elif action == "back":
                return self._call_helper("back")
            elif action == "exec_code":
                code = kwargs.get("code", "")
                return self.execute_code(code)
            else:
                return {
                    "status": "error",
                    "message": f"Acción '{action}' no reconocida en FtlPhoneHarness."
                }
        except Exception as e:
            logging.error(f"[FtlPhoneHarness] Error en acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """Alias para execute_module de Master Hub."""
        action = args[0] if args else kwargs.get("action", "status")
        return self.run(action=action, **kwargs)

    def get_status(self) -> Dict[str, Any]:
        """Escanea dispositivos USB (Android ADB, Apple iOS) y estado del harness."""
        status = {
            "harness_version": self.version,
            "adb_daemon": "inactivo",
            "android_devices": [],
            "ios_devices": [],
            "status": "ready"
        }

        # 1. Comprobar ADB
        try:
            res_adb = subprocess.run(
                ["adb", "devices", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res_adb.returncode == 0:
                status["adb_daemon"] = "activo"
                lines = [l.strip() for l in res_adb.stdout.strip().split("\n")[1:] if l.strip()]
                status["android_devices"] = lines
        except Exception as e_adb:
            status["adb_error"] = str(e_adb)

        # 2. Comprobar iOS / usbmuxd
        try:
            res_ios = subprocess.run(
                ["idevice_id", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res_ios.returncode == 0:
                udids = [u.strip() for u in res_ios.stdout.strip().split("\n") if u.strip()]
                status["ios_devices"] = udids
        except Exception:
            pass

        return status

    def run_doctor(self, platform: Optional[str] = None) -> Dict[str, Any]:
        """Ejecuta el chequeo de salud oficial de phone-harness."""
        cmd = ["phone-harness", "--doctor"]
        if platform:
            cmd.append(platform)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return {
                "returncode": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr
            }
        except Exception as e:
            return {"error": str(e)}

    def execute_code(self, python_code: str) -> Dict[str, Any]:
        """Ejecuta un script con los helpers pre-importados de phone-harness."""
        try:
            res = subprocess.run(
                ["phone-harness"],
                input=python_code,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "returncode": res.returncode,
                "output": res.stdout,
                "error": res.stderr
            }
        except Exception as e:
            return {"error": str(e)}

    def _call_helper(self, helper_name: str, **kwargs) -> Dict[str, Any]:
        """Invoca directamente los helpers de Python de phone_harness."""
        try:
            from phone_harness import helpers
            if hasattr(helpers, helper_name):
                fn = getattr(helpers, helper_name)
                # Filtrar argumentos None
                filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
                result = fn(**filtered_kwargs)
                return {"status": "success", "result": result}
            else:
                return {"status": "error", "error": f"Helper '{helper_name}' no existe en phone_harness."}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Instanciación para autocarga FTL
modulo_ftl_phone_harness = FtlPhoneHarness()
