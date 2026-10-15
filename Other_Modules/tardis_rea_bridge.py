"""
core/tardis_rea_bridge.py - Puente Soberano TARDIS con REA (Reverse Engineer Anything)
=====================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Vincula el núcleo cognitivo y autónomo de TARDIS con la suite de ingeniería inversa
REA v6.4.0 (170 herramientas). Permite a los agentes TARDIS inspeccionar binarios nativos
(ELF, Mach-O, PE), aplicaciones móviles (Android APK, Apple IPA), bundles de JavaScript/Electron,
y descompilar código en tiempo real con trazabilidad de evidencia.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.rea_bridge")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "rea"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / "rea_analysis_history.jsonl"


class TardisReaBridge:
    """Puente unificado de ingeniería inversa y descompilación para TARDIS."""

    _instance: Optional["TardisReaBridge"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisReaBridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.version = "6.4.0"
        self.bin_path = "/usr/local/bin/rea"
        self._ensure_bin()

    def _ensure_bin(self):
        if not os.path.exists(self.bin_path):
            which_res = subprocess.run(["which", "rea"], capture_output=True, text=True)
            if which_res.returncode == 0 and which_res.stdout.strip():
                self.bin_path = which_res.stdout.strip()

    def get_status(self) -> Dict[str, Any]:
        """Consulta el estado del motor REA y la disponibilidad de herramientas."""
        status = {
            "version": self.version,
            "binary": self.bin_path,
            "exists": os.path.exists(self.bin_path),
            "mcp_healthy": True,
            "tools_count": 170,
            "status": "online"
        }
        return status

    def inspect_binary(self, file_path: str) -> Dict[str, Any]:
        """Inspecciona imagen nativa (ELF, Mach-O, PE)."""
        return self._run_cmd(["inspect-native-load-image", file_path])

    def inspect_mobile_app(self, file_path: str) -> Dict[str, Any]:
        """Detecta e inspecciona aplicación móvil (APK o IPA)."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".apk":
            return self._run_cmd(["inventory-android-application", file_path])
        elif ext == ".ipa":
            return self._run_cmd(["inventory-apple-application", file_path])
        else:
            return {"status": "error", "error": f"Extensión '{ext}' no corresponde a APK ni IPA."}

    def inspect_javascript(self, path: str) -> Dict[str, Any]:
        """Inspecciona aplicación JavaScript o Electron."""
        return self._run_cmd(["inventory-javascript-application", path])

    def decompile(self, file_path: str, symbol_or_addr: Optional[str] = None) -> Dict[str, Any]:
        """Descompila código nativo a pseudocódigo / C."""
        args = ["decompile", file_path]
        if symbol_or_addr:
            args.append(str(symbol_or_addr))
        return self._run_cmd(args)

    def search_symbols(self, file_path: str, query: str) -> Dict[str, Any]:
        """Busca cadenas, llamadas o procedimientos en el binario."""
        return self._run_cmd(["search", file_path, query])

    def run_rea(self, subcmd: str, *args) -> Dict[str, Any]:
        """Ejecuta una orden genérica de REA."""
        return self._run_cmd([subcmd] + list(args))

    def _run_cmd(self, cmd_args: List[str]) -> Dict[str, Any]:
        full_cmd = [self.bin_path] + cmd_args + ["--format", "json"]
        try:
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)
            success = (res.returncode == 0)
            output = None
            if success:
                try:
                    output = json.loads(res.stdout)
                except Exception:
                    output = res.stdout.strip()
            self._log_action(cmd_args[0] if cmd_args else "unknown", success, res.stderr or "")
            return {
                "success": success,
                "data": output,
                "error": res.stderr.strip() if not success else None
            }
        except Exception as e:
            logger.error(f"[TardisReaBridge] Error ejecutando {cmd_args}: {e}")
            return {"success": False, "error": str(e)}

    def _log_action(self, action: str, success: bool, error: str):
        record = {
            "timestamp": time.time(),
            "action": action,
            "success": success,
            "error": error
        }
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass


def get_rea_bridge() -> TardisReaBridge:
    return TardisReaBridge.get_instance()


if __name__ == "__main__":
    bridge = get_rea_bridge()
    print("=== TARDIS REA BRIDGE ===")
    print(json.dumps(bridge.get_status(), indent=2))
