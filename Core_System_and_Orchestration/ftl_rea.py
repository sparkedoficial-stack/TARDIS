"""
modulos_ftl/ftl_rea.py - Módulo FTL Soberano de Ingeniería Inversa (REA)
========================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Integra REA (Reverse Engineer Anything) a nivel de Kernel y Master Hub FTL
para descompilación, análisis estático/dinámico de binarios nativos (ELF, Mach-O, PE),
aplicaciones móviles (APK, IPA), arquitecturas JavaScript/Electron y firmwares.
"""

import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class FtlRea:
    """
    Módulo oficial FTL para análisis de ingeniería inversa y descompilación.
    Integrado en el Master Hub FTL y la red neuronal TARDIS.
    """

    def __init__(self):
        self.name = "rea"
        self.version = "6.4.0"
        self.bin_path = "/usr/local/bin/rea"

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada principal para Master Hub FTL.
        Acciones soportadas:
          - 'status': Verifica la disponibilidad y salud del servidor MCP y CLI.
          - 'providers': Lista los motores de descompilación y análisis configurados.
          - 'inspect_apk': Realiza inventario y proyección de una aplicación Android (APK).
          - 'inspect_ipa': Analiza una aplicación iOS/macOS (IPA / bundle).
          - 'inspect_js': Analiza una aplicación JavaScript/Electron.
          - 'decompile': Descompila una función o dirección en un binario.
          - 'disassemble': Obtiene las instrucciones desensambladas.
          - 'search': Busca cadenas, símbolos o procedimientos en el binario.
          - 'exec': Ejecuta cualquier subcomando de REA devolviendo JSON estructurado.
        """
        action = action.lower()
        try:
            if action in ("status", "telemetry"):
                return self.get_status()
            elif action == "providers":
                return self._run_rea_cmd(["providers"])
            elif action == "inspect_apk":
                target = kwargs.get("target") or kwargs.get("path")
                if not target:
                    return {"status": "error", "error": "Parámetro 'target' requerido."}
                return self._run_rea_cmd(["inventory-android-application", target])
            elif action == "inspect_ipa":
                target = kwargs.get("target") or kwargs.get("path")
                if not target:
                    return {"status": "error", "error": "Parámetro 'target' requerido."}
                return self._run_rea_cmd(["inventory-apple-application", target])
            elif action == "inspect_js":
                target = kwargs.get("target") or kwargs.get("path")
                if not target:
                    return {"status": "error", "error": "Parámetro 'target' requerido."}
                return self._run_rea_cmd(["inventory-javascript-application", target])
            elif action == "decompile":
                target = kwargs.get("target")
                symbol = kwargs.get("symbol") or kwargs.get("address")
                cmd = ["decompile", target]
                if symbol:
                    cmd.append(str(symbol))
                return self._run_rea_cmd(cmd)
            elif action == "search":
                target = kwargs.get("target")
                query = kwargs.get("query", "")
                return self._run_rea_cmd(["search", target, query])
            elif action == "exec":
                cmd = kwargs.get("cmd", [])
                if isinstance(cmd, str):
                    cmd = cmd.split()
                return self._run_rea_cmd(cmd)
            else:
                return {
                    "status": "error",
                    "message": f"Acción '{action}' no reconocida en FtlRea."
                }
        except Exception as e:
            logging.error(f"[FtlRea] Error en acción '{action}': {e}")
            return {"status": "error", "error": str(e)}

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        """Alias para execute_module del Master Hub."""
        action = args[0] if args else kwargs.get("action", "status")
        return self.run(action=action, **kwargs)

    def get_status(self) -> Dict[str, Any]:
        """Verifica la operatividad del motor REA y su doctor MCP."""
        status = {
            "version": self.version,
            "binary": self.bin_path,
            "exists": os.path.exists(self.bin_path),
            "mcp_healthy": False,
            "tools_count": 0,
            "status": "ready"
        }
        try:
            res = subprocess.run(
                [self.bin_path, "mcp", "doctor", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                status["mcp_healthy"] = data.get("healthy", False)
                status["tools_count"] = data.get("inventory", {}).get("tools", {}).get("observed", 0)
        except Exception as e:
            status["doctor_error"] = str(e)
        return status

    def _run_rea_cmd(self, args: List[str]) -> Dict[str, Any]:
        """Ejecuta una orden de REA con salida en formato JSON y envelope completo."""
        cmd = [self.bin_path] + args + ["--format", "json"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                try:
                    data = json.loads(res.stdout)
                    return {"status": "success", "data": data}
                except json.JSONDecodeError:
                    return {"status": "success", "raw": res.stdout.strip()}
            else:
                return {
                    "status": "error",
                    "returncode": res.returncode,
                    "error": res.stderr.strip() or res.stdout.strip()
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Instanciación para autocarga en FTL Master Hub
modulo_ftl_rea = FtlRea()
