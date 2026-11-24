#!/usr/bin/env python3
"""
modulos_ftl/ftl_resource_governor.py - Módulo FTL para el Gobernador Soberano de Recursos Ring 0
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

GODWORKS_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_DIR) not in sys.path:
    sys.path.insert(0, str(GODWORKS_DIR))

from core.tardis_resource_governor import get_resource_governor


class FtlResourceGovernor:
    """Interfaz FTL Master Hub / Omni-Registry para TardisResourceGovernor."""

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        gov = get_resource_governor()
        act = (action or "status").lower().strip()
        if act == "status":
            return gov.collect_snapshot(persist=True)
        if act == "admit":
            return gov.admit(str(kwargs.get("task_class") or "heavy_learning"))
        if act == "reclaim":
            return gov.reclaim_resources(dry_run=bool(kwargs.get("dry_run", False)))
        if act == "history":
            return {"ok": True, "history": gov.history(limit=int(kwargs.get("limit", 20)))}
        return {"ok": False, "error": f"Acción '{action}' no soportada por FtlResourceGovernor."}

    execute = run
