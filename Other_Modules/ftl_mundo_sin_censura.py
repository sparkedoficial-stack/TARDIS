"""
modulos_ftl/ftl_mundo_sin_censura.py - Módulo FTL Soberano para Un Mundo Sin Censura
====================================================================================
Conecta el ecosistema FTL y OmniToolBridge con `core/mundo_sin_censura.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

GODWORKS_DIR = Path("/home/m11/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_DIR) not in sys.path:
    sys.path.insert(0, str(GODWORKS_DIR))


class FtlMundoSinCensura:
    """Adaptador FTL para operación individual del modelo `mundo-sin-censura`."""

    def __init__(self):
        self.name = "mundo_sin_censura"
        self.version = "2.0.0"

    def run(self, action: str = "status", **kwargs: Any) -> Dict[str, Any]:
        from core.mundo_sin_censura import get_mundo_sin_censura

        agent = get_mundo_sin_censura()
        act = (action or "status").strip().lower().replace("_", "-")

        if act == "status":
            return agent.get_status()
        if act == "analyze":
            return agent.analyze_systems()
        if act == "verify":
            return agent.verify_model(force_hash=bool(kwargs.get("force_hash", False)))
        if act == "ensure":
            return agent.ensure_model_ready(rebuild=bool(kwargs.get("rebuild", False)))
        if act in ("sync-ftl", "sync"):
            return agent.sync_ftl_audit()
        if act in ("abliterate", "configure"):
            return agent.configure_sovereign_mode()
        if act in ("chat", "generate"):
            prompt = kwargs.get("prompt") or kwargs.get("message") or ""
            messages = kwargs.get("messages") or ([{"role": "user", "content": str(prompt)}] if prompt else [])
            if not messages:
                return {"ok": False, "error": "Se requiere 'prompt', 'message' o 'messages'."}
            return agent.chat(
                messages,
                lane=str(kwargs.get("lane") or "auto"),
                temperature=float(kwargs.get("temperature", 0.25)),
                max_tokens=int(kwargs.get("max_tokens", 1024)),
                num_ctx=int(kwargs.get("num_ctx", 8192)),
                use_rag=bool(kwargs.get("use_rag", False)),
                timeout=float(kwargs.get("timeout", 120.0)),
            )
        if act == "benchmark":
            return agent.benchmark(
                lane=str(kwargs.get("lane") or "auto"),
                max_tokens=int(kwargs.get("max_tokens", 96)),
                prompt=kwargs.get("prompt"),
                timeout=float(kwargs.get("timeout", 120.0)),
            )
        if act in ("hardware-status", "hw-status", "hardware"):
            from core.mundo_sin_censura_hardware import get_mundo_hardware_controller
            return get_mundo_hardware_controller().get_full_hardware_telemetry()
        if act in ("hardware-capabilities", "hw-capabilities"):
            from core.mundo_sin_censura_hardware import get_mundo_hardware_controller
            return get_mundo_hardware_controller().get_capabilities()
        if act in ("hardware-action", "hw-action", "hw"):
            from core.mundo_sin_censura_hardware import get_mundo_hardware_controller
            hw_act = str(kwargs.get("hw_action") or kwargs.get("target_action") or "hardware_status")
            hw_params = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else {}
            return get_mundo_hardware_controller().execute_action(
                hw_act, hw_params, is_local_request=True, source="ftl_mundo_sin_censura"
            )
        if act in ("hardware-mode", "hw-mode"):
            from core.mundo_sin_censura_hardware import get_mundo_hardware_controller
            return get_mundo_hardware_controller().set_mode(
                enabled=kwargs.get("enabled"),
                ring0_enabled=kwargs.get("ring0_enabled"),
                agentic_hw_in_chat=kwargs.get("agentic_hw_in_chat"),
            )
        return {
            "ok": False,
            "error": f"Acción no reconocida: '{action}'",
            "available_actions": [
                "status", "analyze", "verify", "ensure", "sync-ftl", "abliterate",
                "chat", "benchmark", "hardware-status", "hardware-capabilities",
                "hardware-action", "hardware-mode",
            ],
        }
