# -*- coding: utf-8 -*-
"""
modulos_ftl/ftl_omniscient_autonomy.py - Módulo FTL de Aprendizaje Total, Bases Científicas,
Contestación de Comentarios/Chat y Auto-Mejora de TARDIS y Tecnología Circundante
============================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict

GODWORKS_PATH = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_PATH) not in sys.path:
    sys.path.insert(0, str(GODWORKS_PATH))

from core.tardis_omniscient_autonomy import get_omniscient_autonomy_engine


class FtlOmniscientAutonomy:
    """Módulo FTL para control individual e integración con el Master Hub de TARDIS."""

    def __init__(self):
        self.engine = get_omniscient_autonomy_engine()
        self.name = "ftl_omniscient_autonomy"
        self.created_at = time.time()

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        act = (action or "status").lower().strip().replace("_", "-")
        if act == "status":
            return {
                "ok": True,
                "status": "online",
                "state": self.engine.state,
                "telemetry": self.engine.collect_surrounding_technology_telemetry(),
            }
        elif act == "learn":
            topic = kwargs.get("topic")
            return asyncio.run(self.engine.learn_everything_cycle(custom_topic=topic))
        elif act in ("evolve-tech", "evolve", "tech"):
            return asyncio.run(self.engine.investigate_self_and_surrounding_tech_cycle())
        elif act == "publish":
            mode = kwargs.get("mode", "auto")
            topic = kwargs.get("topic")
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(
                self.engine.publish_knowledge_and_science_cycle(
                    mode=mode, topic=topic, dry_run=dry_run, min_interval_seconds=0.0
                )
            )
        elif act in ("answer", "answer-comments"):
            max_replies = int(kwargs.get("max_replies", 2))
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(
                self.engine.answer_comments_and_chat_cycle(max_x_replies=max_replies, dry_run=dry_run)
            )
        elif act in ("run-cycle", "cycle"):
            dry_run = bool(kwargs.get("dry_run", False))
            force_pub = bool(kwargs.get("force_publish", False))
            return asyncio.run(
                self.engine.run_full_omniscient_cycle(
                    publish_to_x=True,
                    min_x_interval_seconds=0.0 if force_pub else 1800.0,
                    dry_run=dry_run,
                )
            )
        return {
            "ok": False,
            "error": f"Acción '{action}' no reconocida. Válidas: status, learn, evolve-tech, publish, answer, run-cycle",
        }

    execute = run


def get_module() -> FtlOmniscientAutonomy:
    return FtlOmniscientAutonomy()
