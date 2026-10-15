"""
core/tardis_phone_harness_bridge.py - Puente Soberano TARDIS con Phone Harness
=============================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Vincula el núcleo cognitivo de TARDIS con la capa de hardware y emulación móvil
proporcionada por phone-harness a nivel de Kernel. Permite a los agentes TARDIS
inspeccionar, ver, pulsar, escribir y ejecutar tareas sobre dispositivos móviles
(Android vía ADB, iPhone/iPad vía USBMUXD/Mirroring, y Cloud Phones).
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

logger = logging.getLogger("godworks.phone_harness_bridge")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "phone_harness"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / "harness_history.jsonl"


class TardisPhoneHarnessBridge:
    """Puente unificado de control de dispositivos móviles para TARDIS."""

    _instance: Optional["TardisPhoneHarnessBridge"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisPhoneHarnessBridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._ensure_path()
        self.version = "0.3.2"
        self._cache_devices()

    def _ensure_path(self):
        local_bin = "/home/timemachine/.local/bin"
        if local_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

    def _cache_devices(self):
        self.last_scan_time = 0
        self.cached_devices = {}

    def get_telemetry(self) -> Dict[str, Any]:
        """Obtiene la telemetría completa de conectividad móvil del sistema."""
        now = time.time()
        if now - self.last_scan_time < 2.0:
            return self.cached_devices

        telemetry = {
            "timestamp": now,
            "version": self.version,
            "adb_server": self._check_adb_status(),
            "android_devices": self._get_android_devices(),
            "ios_devices": self._get_ios_devices(),
            "status": "online"
        }
        self.cached_devices = telemetry
        self.last_scan_time = now
        return telemetry

    def _check_adb_status(self) -> bool:
        try:
            res = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=2)
            return res.returncode == 0 or "device" in res.stdout or "unknown" in res.stderr
        except Exception:
            return False

    def _get_android_devices(self) -> List[Dict[str, str]]:
        devices = []
        try:
            res = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.strip().split("\n")[1:]:
                    if line.strip():
                        parts = line.strip().split()
                        serial = parts[0]
                        state = parts[1] if len(parts) > 1 else "unknown"
                        extra = " ".join(parts[2:]) if len(parts) > 2 else ""
                        devices.append({"serial": serial, "state": state, "details": extra})
        except Exception as e:
            logger.debug(f"Error escaneando Android ADB: {e}")
        return devices

    def _get_ios_devices(self) -> List[Dict[str, str]]:
        devices = []
        try:
            res = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                for line in res.stdout.strip().split("\n"):
                    udid = line.strip()
                    if udid:
                        devices.append({"udid": udid, "type": "ios_device"})
        except Exception as e:
            logger.debug(f"Error escaneando iOS USBMUXD: {e}")
        return devices

    def screen(self, min_confidence: float = 0.3) -> List[Dict[str, Any]]:
        """Lee el contenido visual de la pantalla en forma de cajas de texto."""
        from phone_harness import helpers
        res = helpers.screen(min_confidence=min_confidence)
        self._log_action("screen", {"boxes_count": len(res)})
        return res

    def screenshot(self, path: Optional[str] = None) -> str:
        """Captura un fotograma completo de la pantalla del dispositivo."""
        from phone_harness import helpers
        img_path = helpers.screenshot(path=path)
        self._log_action("screenshot", {"path": str(img_path)})
        return str(img_path)

    def find_text(self, query: str, exact: bool = False) -> List[Dict[str, Any]]:
        """Localiza elementos de texto en la pantalla actual."""
        from phone_harness import helpers
        return helpers.find_text(query, exact=exact)

    def tap_text(self, query: str, exact: bool = False, index: int = 0) -> bool:
        """Pulsa sobre el texto localizado en pantalla."""
        from phone_harness import helpers
        res = helpers.tap_text(query, index=index, exact=exact)
        self._log_action("tap_text", {"query": query, "success": bool(res)})
        return bool(res)

    def tap(self, x: int, y: int) -> None:
        """Pulsa en coordenadas de pantalla absolutas."""
        from phone_harness import helpers
        helpers.tap(x, y)
        self._log_action("tap", {"x": x, "y": y})

    def type_text(self, text: str) -> None:
        """Escribe texto en el componente enfocado."""
        from phone_harness import helpers
        helpers.type_text(text)
        self._log_action("type_text", {"text_len": len(text)})

    def open_app(self, name: str) -> str:
        """Inicia una aplicación en el dispositivo móvil."""
        from phone_harness import helpers
        app_id = helpers.open_app(name)
        self._log_action("open_app", {"name": name, "app_id": app_id})
        return app_id

    def home(self) -> None:
        """Navega a la pantalla de inicio."""
        from phone_harness import helpers
        helpers.home()
        self._log_action("home", {})

    def back(self) -> None:
        """Ejecuta el botón de regreso del sistema."""
        from phone_harness import helpers
        helpers.back()
        self._log_action("back", {})

    def run_script(self, code: str) -> Dict[str, Any]:
        """Ejecuta un script con los helpers del harness aislados."""
        try:
            res = subprocess.run(
                ["phone-harness"],
                input=code,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _log_action(self, action: str, details: Dict[str, Any]):
        """Persiste traza de telemetría de acciones."""
        record = {
            "timestamp": time.time(),
            "action": action,
            "details": details
        }
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass


def get_phone_harness_bridge() -> TardisPhoneHarnessBridge:
    return TardisPhoneHarnessBridge.get_instance()


if __name__ == "__main__":
    bridge = get_phone_harness_bridge()
    telemetry = bridge.get_telemetry()
    print("=== TARDIS PHONE HARNESS BRIDGE ===")
    print(json.dumps(telemetry, indent=2))
