# -*- coding: utf-8 -*-
"""
modulos_ftl/ftl_terminal_continuator.py - Módulo FTL de Continuación Autónoma Multi-Terminal
=============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Expone a FTL, Master Hub y TARDIS el motor unificado para escanear, reconciliar y
continuar de inicio a fin cualquier proceso pausado o interrumpido en las terminales
`agy`, `FTL` y `opencode`.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

GODWORKS_PATH = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if not GODWORKS_PATH.is_dir():
    GODWORKS_PATH = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_PATH) not in sys.path:
    sys.path.insert(0, str(GODWORKS_PATH))

from core.ftl_terminal_continuator import get_ftl_terminal_continuator


class FtlTerminalContinuatorModule:
    """Módulo FTL para continuación autónoma unificada de `agy`, `FTL` y `opencode`."""

    def __init__(self):
        self.engine = get_ftl_terminal_continuator()
        self.name = "ftl_terminal_continuator"
        self.created_at = time.time()

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        act = (action or "status").lower().strip().replace("_", "-")

        if act == "status":
            return self.engine.get_status()
        if act == "verify":
            return self.engine.verify_all_terminals()
        if act == "scan":
            return self.engine.scan_all_terminals(
                max_age_hours=float(kwargs.get("hours", 48.0)),
                include_tracked=bool(kwargs.get("include_tracked", False)),
                reconcile_first=bool(kwargs.get("reconcile_first", True)),
            )
        if act == "reconcile":
            return self.engine.reconcile_ftl_continuity(
                max_age_hours=float(kwargs.get("hours", 720.0)),
            )
        if act in ("run", "continue-all", "continue"):
            terms = kwargs.get("terminals") or ("agy", "opencode", "ftl")
            if isinstance(terms, str):
                terms = [t.strip() for t in terms.split(",") if t.strip()]
            return self.engine.continue_all(
                terminals=terms,
                max_age_hours=float(kwargs.get("hours", 48.0)),
                max_items=int(kwargs.get("max_items", 5)),
                dry_run=bool(kwargs.get("dry_run", False)),
                enqueue=bool(kwargs.get("enqueue", False)),
            )
        if act == "continue-agy":
            return self.engine.continue_agy_session(
                str(kwargs.get("conversation_id") or ""),
                prompt=str(kwargs.get("prompt") or ""),
                cwd=kwargs.get("cwd"),
                model=kwargs.get("model"),
                timeout=int(kwargs.get("timeout", 900)),
                force_handoff=bool(kwargs.get("force_handoff", False)),
                enqueue=bool(kwargs.get("enqueue", False)),
            )
        if act == "continue-opencode":
            return self.engine.continue_opencode_session(
                str(kwargs.get("session_id") or ""),
                prompt=str(kwargs.get("prompt") or ""),
                model=str(kwargs.get("model") or ""),
                timeout=int(kwargs.get("timeout", 420)),
                allow_agy_fallback=bool(kwargs.get("allow_agy_fallback", True)),
            )
        if act == "continue-ftl":
            return self.engine.continue_ftl_request(
                int(kwargs.get("request_id") or 0),
                timeout=int(kwargs.get("timeout", 900)),
                enqueue=bool(kwargs.get("enqueue", False)),
            )
        if act == "sweep":
            return self.engine.sweep_and_enqueue(
                max_age_hours=kwargs.get("hours"),
                max_items=int(kwargs.get("max_items", 3)),
            )
        if act == "pause":
            return self.engine.set_paused(True)
        if act == "resume":
            return self.engine.set_paused(False)

        return {
            "ok": False,
            "error": (
                f"Acción '{action}' no reconocida. Válidas: status, verify, scan, reconcile, "
                "run, continue-agy, continue-opencode, continue-ftl, sweep, pause, resume"
            ),
        }

    execute = run


def get_module() -> FtlTerminalContinuatorModule:
    return FtlTerminalContinuatorModule()
