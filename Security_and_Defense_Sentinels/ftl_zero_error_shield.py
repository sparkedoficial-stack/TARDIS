"""
modulos_ftl/ftl_zero_error_shield.py - Módulo FTL Soberano para Zero-Error Preemptive Shield
============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL AUTOMATION SUITE · EASY TOUCH
Arquitecto: El Arquitecto (₪)

Expone el sistema Zero-Error Preemptive Shield directamente al FTL Master Hub,
Omni-Tool Registry y agentes autónomos (AGY / TARDIS / Easy Touch).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

GODWORKS_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_DIR) not in sys.path:
    sys.path.insert(0, str(GODWORKS_DIR))

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SHIELD_UNIX_SOCKET = RUNTIME_DIR / "ftl-zero-error-shield.sock"


class FtlZeroErrorShield:
    """
    Puente FTL de control sobre el Escudo Zero-Error Preemptivo (intercepción pre-notificación
    + auto-reparación preventiva Kernel Ring 0 + Easy Touch + AutonomousErrorFixer).
    """

    def __init__(self) -> None:
        self.name = "ftl_zero_error_shield"
        self.version = "26.4.1"

    def _ipc_call(self, req: Dict[str, Any], timeout: float = 4.0) -> Dict[str, Any]:
        if SHIELD_UNIX_SOCKET.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    s.connect(str(SHIELD_UNIX_SOCKET))
                    s.sendall(json.dumps(req, ensure_ascii=False).encode("utf-8"))
                    s.shutdown(socket.SHUT_WR)
                    chunks = []
                    while True:
                        buf = s.recv(65536)
                        if not buf:
                            break
                        chunks.append(buf)
                    raw = b"".join(chunks).decode("utf-8", errors="ignore").strip()
                    if raw:
                        return json.loads(raw)
            except Exception:
                pass
        return {}

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        """
        Acciones soportadas:
          - status: Telemetría completa del escudo y servicio systemd
          - precheck / heal: Barrido preemptivo completo y auto-reparación inmediata
          - intercept: Intercepta y repara un evento/error específico
          - classify: Clasifica una notificación sin disparar reparación
          - history: Historial de incidentes interceptados y prevenidos
          - rules: Reglas activas y whitelist
          - mode: Cambia modo (enforce | audit | disabled)
          - purge: Purga notificaciones de error viejas en Omarchy Shell
          - daemon_status: Estado systemd de tardis-zero-error-shield.service
        """
        act = (action or "status").lower().strip()
        from core.zero_error_shield import get_zero_error_shield, classify_notification, load_rules

        if act in ("status", "estado"):
            res = self._ipc_call({"action": "status"})
            if not res:
                res = get_zero_error_shield().get_status()
            res["systemd_active"] = self._systemd_active()
            return {"status": "ok", **res}

        if act in ("precheck", "heal", "reparar", "sweep"):
            res = self._ipc_call({"action": "precheck"}, timeout=20.0)
            if not res:
                res = get_zero_error_shield().run_preemptive_check()
            return {"status": "ok", **res}

        if act == "intercept":
            payload = kwargs.get("payload") or {
                "summary": kwargs.get("summary", ""),
                "body": kwargs.get("body", ""),
                "app": kwargs.get("app", "ftl"),
                "urgency": int(kwargs.get("urgency", 2)),
                "category": kwargs.get("category", "auto"),
            }
            res = self._ipc_call({
                "action": "intercept",
                "payload": payload,
                "source": kwargs.get("source", "ftl_module"),
                "suppressed_before_display": bool(kwargs.get("suppressed_before_display", True)),
                "async": bool(kwargs.get("async_repair", False)),
            }, timeout=15.0)
            if not res:
                res = get_zero_error_shield().handle_event(
                    payload,
                    source=kwargs.get("source", "ftl_module"),
                    suppressed_before_display=bool(kwargs.get("suppressed_before_display", True)),
                    async_repair=bool(kwargs.get("async_repair", False)),
                )
            return {"status": "ok", **res}

        if act == "classify":
            return {
                "status": "ok",
                **classify_notification(
                    summary=str(kwargs.get("summary", "")),
                    body=str(kwargs.get("body", "")),
                    app=str(kwargs.get("app", "")),
                    urgency=int(kwargs.get("urgency", 1)),
                    category=str(kwargs.get("dbus_category", "")),
                    icon=str(kwargs.get("icon", "")),
                    rules=load_rules(),
                ),
            }

        if act in ("history", "historial"):
            limit = int(kwargs.get("limit", 25))
            res = self._ipc_call({"action": "history", "limit": limit})
            if not res:
                res = {"ok": True, "events": get_zero_error_shield().get_history(limit)}
            return {"status": "ok", **res}

        if act in ("rules", "reglas"):
            return {"status": "ok", "rules": load_rules()}

        if act in ("mode", "modo"):
            mode = str(kwargs.get("mode", "enforce")).lower()
            res = self._ipc_call({"action": "mode", "mode": mode})
            if not res:
                res = get_zero_error_shield()._dispatch_ipc_request({"action": "mode", "mode": mode})
            return {"status": "ok" if res.get("ok") else "error", **res}

        if act in ("purge", "purgar", "clear-stale"):
            return {"status": "ok", **get_zero_error_shield().purge_stale_error_notifications()}

        if act == "daemon_status":
            return {"status": "ok", "service": "tardis-zero-error-shield.service", "active": self._systemd_active()}

        return {
            "status": "error",
            "error": f"Acción '{action}' no reconocida.",
            "available_actions": ["status", "precheck", "heal", "intercept", "classify", "history", "rules", "mode", "purge", "daemon_status"],
        }

    execute = run

    @staticmethod
    def _systemd_active() -> str:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "tardis-zero-error-shield.service"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=4,
            )
            return (r.stdout or "").strip() or "inactive"
        except Exception:
            return "unknown"


_shield_ftl_instance = None


def get_ftl_zero_error_shield() -> FtlZeroErrorShield:
    global _shield_ftl_instance
    if _shield_ftl_instance is None:
        _shield_ftl_instance = FtlZeroErrorShield()
    return _shield_ftl_instance


if __name__ == "__main__":
    act = sys.argv[1] if len(sys.argv) > 1 else "status"
    print(json.dumps(get_ftl_zero_error_shield().run(act), indent=2, ensure_ascii=False))
