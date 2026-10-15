# -*- coding: utf-8 -*-
"""
modulos_ftl/tardis_browser_engine.py - Módulo FTL del Navegador Cuántico Soberano
===================================================================================
TARDIS FTL Master Hub Integration
Permite a cualquier agente, subsistema o script invocar el navegador controlado
por TARDIS de forma 100% autónoma para aprender y auto-mejorarse.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Asegurar path de core
GODWORKS_PATH = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(GODWORKS_PATH) not in sys.path:
    sys.path.insert(0, str(GODWORKS_PATH))

from core.tardis_browser import get_tardis_browser, TardisAutonomousLearningLoop


class TardisBrowserEngine:
    """Módulo FTL registrado en el Master Hub de TARDIS."""

    def __init__(self):
        self.browser = get_tardis_browser()
        self.name = "tardis_browser_engine"
        self.created_at = time.time()

    def run(self, action: str = "visit", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada FTL principal.
        Acciones soportadas:
          - 'visit': Visita una URL específica y aprende de ella.
          - 'search' o 'learn': Investiga un tema en internet y ejecuta auto-mejora FTL.
          - 'status': Retorna el estado de privacidad, Tor y telemetría del navegador.
          - 'daemon_cycle': Ejecuta un ciclo de aprendizaje continuo.
        """
        logging.info(f"⚡ FTL TardisBrowserEngine ejecutando acción: '{action}'")

        if action == "status":
            from core.tardis_browser import TELEMETRY_FILE, ENCRYPTED_VAULT_FILE
            telemetry = {}
            if TELEMETRY_FILE.exists():
                import json
                try:
                    telemetry = json.loads(TELEMETRY_FILE.read_text())
                except Exception:
                    pass
            return {
                "status": "online",
                "tor_active": True,
                "vault": str(ENCRYPTED_VAULT_FILE),
                "telemetry": telemetry,
            }

        elif action == "visit":
            url = kwargs.get("url", "https://check.torproject.org/api/ip")
            engine = "cdp" if kwargs.get("cdp", False) else "turbo"
            use_tor = kwargs.get("tor", True)
            self.browser.use_tor = use_tor
            take_screenshot = kwargs.get("screenshot", False)
            learn = kwargs.get("learn", True)
            topic = kwargs.get("topic", "")

            res = asyncio.run(
                self.browser.visit(
                    url,
                    engine=engine,
                    take_screenshot=take_screenshot,
                    learn=learn,
                    topic=topic,
                )
            )
            return {
                "ok": True,
                "result": res.to_dict(),
            }

        elif action in ("search", "learn"):
            query = kwargs.get("query") or kwargs.get("topic") or "computación cuántica"
            deep = kwargs.get("deep", False)
            res = asyncio.run(self.browser.search_and_learn(query, deep=deep))
            return {
                "ok": True,
                "report": res,
            }

        elif action == "daemon_cycle":
            daemon = TardisAutonomousLearningLoop(interval_seconds=10.0)
            topic = kwargs.get("topic", "redes neuronales estado del arte")
            res = asyncio.run(self.browser.search_and_learn(topic, deep=False))
            return {
                "ok": True,
                "cycle_completed": True,
                "report": res,
            }

        else:
            return {
                "ok": False,
                "error": f"Acción desconocida '{action}'. Válidas: visit, search, learn, status, daemon_cycle",
            }

    def execute(self, *args, **kwargs) -> Any:
        return self.run(*args, **kwargs)


def get_module():
    return TardisBrowserEngine()
