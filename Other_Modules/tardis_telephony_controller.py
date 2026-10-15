"""
core/tardis_telephony_controller.py - Controlador Soberano de Telefonía Móvil TARDIS
=====================================================================================
Orquesta las capacidades móviles y celulares provistas por TARDIS POCKET (Motorola Moto X Play):
  1. Realización, respuesta y corte de llamadas de voz celulares nativas.
  2. Envío y recepción de mensajes SMS con multi-partes y normalización internacional E.164.
  3. Control y monitorización de datos móviles (4G/LTE/3G) y anclaje USB Tethering (RNDIS).
  4. Telemetría de tarjeta SIM, operador de red, tipo de red y estado de señal.
  5. Mantenimiento del túnel bidireccional host <-> pocket (puertos 8080 y 8757).
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

from core.sms_bridge import SMSBridge, normalize_phone_number
from core.tardis_pocket_tunnel_bridge import TardisPocketBridge, get_tardis_pocket_bridge

logger = logging.getLogger("godworks.telephony_controller")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "telephony"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CALLS_HISTORY_FILE = DATA_DIR / "calls_history.json"


class TardisTelephonyController:
    """Controlador unificado de telefonía y conectividad móvil para TARDIS."""

    _instance: Optional["TardisTelephonyController"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisTelephonyController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.bridge = get_tardis_pocket_bridge()
        self.sms_bridge = SMSBridge.get_instance()
        self.calls_history: List[Dict[str, Any]] = self._load_calls_history()
        self._ensure_connectivity_thread = None

    def _load_calls_history(self) -> List[Dict[str, Any]]:
        if CALLS_HISTORY_FILE.exists():
            try:
                return json.loads(CALLS_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Error leyendo historial de llamadas: {e}")
        return []

    def _save_calls_history(self):
        try:
            CALLS_HISTORY_FILE.write_text(json.dumps(self.calls_history[-200:], indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando historial de llamadas: {e}")

    def ensure_connected(self) -> Dict[str, Any]:
        """Asegura la conectividad completa entre el nodo central y TARDIS POCKET."""
        return self.bridge.ensure_bridge_connected()

    def get_status(self) -> Dict[str, Any]:
        """Obtiene el diagnóstico completo del subsistema móvil y celular."""
        conn = self.ensure_connected()
        telemetry = self.bridge.get_telephony_status()
        pocket_status = self.bridge.get_status()

        return {
            "ok": True,
            "device": "TARDIS POCKET (Motorola Moto X Play)",
            "serial": "ZY222ZXWPP",
            "connection": conn,
            "telephony": telemetry,
            "pocket": pocket_status,
            "sms_provider_active": "tardis_pocket",
            "timestamp": int(time.time()),
        }

    def make_call(self, phone_number: str) -> Dict[str, Any]:
        """Realiza una llamada de voz a través de la tarjeta SIM de TARDIS POCKET."""
        self.ensure_connected()
        norm_number = normalize_phone_number(phone_number)
        res = self.bridge.make_call(norm_number)

        record = {
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "call",
            "number": norm_number,
            "status": "dialing" if res.get("ok") else "failed",
            "details": res,
        }
        self.calls_history.append(record)
        self._save_calls_history()

        logger.info(f"📞 [TELEFONÍA] Llamada despachada a {norm_number}: {res}")
        return {
            "ok": res.get("ok", False),
            "action": "call",
            "number": norm_number,
            "result": res,
        }

    def hangup(self) -> Dict[str, Any]:
        """Corta la llamada activa o entrante."""
        res = self.bridge.hangup_call()
        record = {
            "timestamp": time.time(),
            "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "hangup",
            "status": "hung_up" if res.get("ok") else "failed",
            "details": res,
        }
        self.calls_history.append(record)
        self._save_calls_history()

        logger.info(f"📴 [TELEFONÍA] Llamada finalizada: {res}")
        return {"ok": res.get("ok", False), "action": "hangup", "result": res}

    def answer(self) -> Dict[str, Any]:
        """Contesta una llamada entrante."""
        res = self.bridge._call_pocket_api("/api/local/calls/answer", method="POST")
        if not res or not res.get("ok"):
            res = self.bridge._run_adb_telephony(["answer"])
        logger.info(f"📲 [TELEFONÍA] Llamada contestada: {res}")
        return {"ok": res.get("ok", False), "action": "answer", "result": res}

    def send_sms(self, to_number: str, message: str) -> Dict[str, Any]:
        """Envía un SMS estandarizado a través de TARDIS POCKET."""
        self.ensure_connected()
        return self.sms_bridge.send_sms(to_number=to_number, message=message, provider="tardis_pocket")

    def set_mobile_data(self, enabled: bool = True) -> Dict[str, Any]:
        """Activa o desactiva la conexión de datos móviles."""
        self.ensure_connected()
        res = self.bridge.set_mobile_data(enabled)
        logger.info(f"📶 [TELEFONÍA] Datos móviles {'activados' if enabled else 'desactivados'}: {res}")
        return {"ok": res.get("ok", False), "mobile_data": enabled, "result": res}

    def set_usb_tether(self, enabled: bool = True) -> Dict[str, Any]:
        """Activa o desactiva el anclaje USB Tethering para suministrar internet móvil al equipo local."""
        self.ensure_connected()
        res = self.bridge.set_usb_tether(enabled)
        logger.info(f"🔄 [TELEFONÍA] USB Tethering {'activado' if enabled else 'desactivado'}: {res}")
        return {"ok": res.get("ok", False), "usb_tether": enabled, "result": res}


def get_tardis_telephony_controller() -> TardisTelephonyController:
    return TardisTelephonyController.get_instance()
