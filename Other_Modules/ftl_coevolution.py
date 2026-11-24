#!/usr/bin/env python3
"""
modulos_ftl/ftl_coevolution.py - Módulo FTL para el Canal Continuo TARDIS <-> AGY Co-Evolution
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

GODWORKS_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_DIR) not in sys.path:
    sys.path.insert(0, str(GODWORKS_DIR))

from core.tardis_agy_coevolution import get_coevolution_engine


class FtlCoevolution:
    """Interfaz FTL Master Hub / Omni-Registry para TardisAgyCoevolutionEngine."""

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        eng = get_coevolution_engine()
        act = (action or "status").lower().strip().replace("_", "-")
        if act == "status":
            return eng.get_status()
        if act == "scan":
            return eng.scan(lens=str(kwargs.get("lens") or "all"))
        if act == "proposals":
            return {"ok": True, "proposals": eng.list_proposals(status=str(kwargs.get("status") or "all"), limit=int(kwargs.get("limit", 25)))}
        if act == "dialogue":
            return {"ok": True, "dialogue": eng.get_dialogue(limit=int(kwargs.get("limit", 20)))}
        if act == "ask-agy":
            return eng.communicate_with_agy(
                prompt=kwargs.get("prompt"),
                proposal_id=kwargs.get("proposal_id"),
                mode=str(kwargs.get("mode") or "coevolution"),
                sync=bool(kwargs.get("sync", False)),
                force=bool(kwargs.get("force", False)),
            )
        if act == "reply-tardis":
            return eng.record_agy_reply(
                str(kwargs.get("message") or ""),
                proposal_id=kwargs.get("proposal_id"),
                status=str(kwargs.get("status") or "reviewed"),
                sender=str(kwargs.get("sender") or "FTL-AGY"),
            )
        if act == "run-cycle":
            return eng.run_cycle(
                lens=str(kwargs.get("lens") or "auto"),
                allow_dispatch=bool(kwargs.get("dispatch", True)),
                force_dispatch=bool(kwargs.get("force_dispatch", False)),
            )
        return {"ok": False, "error": f"Acción '{action}' no soportada por FtlCoevolution."}

    execute = run
