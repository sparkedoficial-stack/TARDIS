# -*- coding: utf-8 -*-
"""
modulos_ftl/ftl_agy_terminal.py - Módulo FTL de Control Soberano de la Terminal AGY
===================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Expone a FTL, al Master Hub y al Omni-Tool Bridge control directo, individual y
100% autónomo sobre la terminal Antigravity CLI (`agy`) del dispositivo.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict

GODWORKS_PATH = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if not GODWORKS_PATH.is_dir():
    GODWORKS_PATH = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_PATH) not in sys.path:
    sys.path.insert(0, str(GODWORKS_PATH))

from core.tardis_agy_controller import get_tardis_agy_controller


class FtlAgyTerminal:
    """Módulo FTL para control total y autónomo de la terminal Antigravity CLI (`agy`)."""

    def __init__(self):
        self.controller = get_tardis_agy_controller()
        self.name = "ftl_agy_terminal"
        self.created_at = time.time()

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        act = (action or "status").lower().strip().replace("_", "-")

        if act == "status":
            return self.controller.get_status()
        if act in ("verify-permissions", "verify"):
            return self.controller.verify_permissions(run_live_probe=bool(kwargs.get("live", False)))
        if act in ("run", "exec", "task"):
            prompt = str(kwargs.get("prompt") or kwargs.get("text") or "").strip()
            return self.controller.run_task(
                prompt,
                cwd=kwargs.get("cwd"),
                model=kwargs.get("model"),
                effort=kwargs.get("effort"),
                conversation_id=kwargs.get("conversation_id"),
                continue_recent=bool(kwargs.get("continue_recent", False)),
                add_dirs=kwargs.get("add_dirs"),
                json_schema=kwargs.get("json_schema"),
                timeout=int(kwargs.get("timeout", 900)),
                source=str(kwargs.get("source") or "ftl_agy_terminal"),
                fallback_to_local=bool(kwargs.get("fallback_to_local", True)),
            )
        if act == "turn":
            prompt = str(kwargs.get("prompt") or kwargs.get("text") or "").strip()
            return self.controller.send_turn(
                prompt,
                cwd=kwargs.get("cwd"),
                model=kwargs.get("model"),
                effort=kwargs.get("effort"),
                conversation_id=kwargs.get("conversation_id"),
                timeout=float(kwargs.get("timeout", 600)),
                source=str(kwargs.get("source") or "ftl_agy_stream"),
            )
        if act == "continue":
            prompt = str(kwargs.get("prompt") or kwargs.get("text") or "").strip()
            return self.controller.continue_session(
                prompt,
                conversation_id=kwargs.get("conversation_id"),
                cwd=kwargs.get("cwd"),
                model=kwargs.get("model"),
                effort=kwargs.get("effort"),
                timeout=int(kwargs.get("timeout", 900)),
                source=str(kwargs.get("source") or "ftl_agy_continue"),
            )
        if act == "enqueue":
            prompt = str(kwargs.get("prompt") or kwargs.get("text") or "").strip()
            return self.controller.enqueue_task(
                prompt,
                source=str(kwargs.get("source") or "ftl_agy_queue"),
                priority=str(kwargs.get("priority") or "normal"),
                cwd=kwargs.get("cwd"),
                model=kwargs.get("model"),
                effort=kwargs.get("effort"),
                conversation_id=kwargs.get("conversation_id"),
                continue_recent=bool(kwargs.get("continue_recent", False)),
                use_stream_session=bool(kwargs.get("use_stream_session", False)),
                timeout=int(kwargs.get("timeout", 900)),
                meta=kwargs.get("meta"),
            )
        if act == "queue":
            return self.controller.list_queue(limit_history=int(kwargs.get("limit", 20)))
        if act == "sessions":
            return {"ok": True, "sessions": self.controller.list_sessions(limit=int(kwargs.get("limit", 20)))}
        if act == "transcript":
            cid = str(kwargs.get("conversation_id") or "").strip()
            return self.controller.get_session_transcript(cid, tail=int(kwargs.get("tail", 30)))
        if act == "pause":
            return self.controller.set_paused(True)
        if act == "resume":
            return self.controller.set_paused(False)
        if act == "reset-session":
            return self.controller.reset_stream_session()

        return {
            "ok": False,
            "error": (
                f"Acción '{action}' no reconocida. Válidas: status, verify-permissions, run, "
                "turn, continue, enqueue, queue, sessions, transcript, pause, resume, reset-session"
            ),
        }

    execute = run


def get_module() -> FtlAgyTerminal:
    return FtlAgyTerminal()
