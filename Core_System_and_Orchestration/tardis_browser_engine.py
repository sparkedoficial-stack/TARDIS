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

        elif action in ("x_feed", "x-feed"):
            steps = int(kwargs.get("steps", 4))
            res = asyncio.run(self.browser.inspect_x_feed(scroll_steps=steps))
            return res

        elif action in ("x_post", "x-post"):
            text = kwargs.get("text", "")
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(self.browser.post_to_x(text, dry_run=dry_run))

        elif action in ("x_reply", "x-reply"):
            url = kwargs.get("url") or kwargs.get("tweet_url") or ""
            text = kwargs.get("text") or kwargs.get("reply_text") or ""
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(self.browser.reply_to_x_post(url, text, dry_run=dry_run))

        elif action in ("x_reflect", "x-reflect", "x_engage", "x-engage"):
            steps = int(kwargs.get("steps", 3))
            publish_reflection = bool(kwargs.get("publish_reflection", True))
            reply_count = int(kwargs.get("replies", kwargs.get("reply_count", 1)))
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(
                self.browser.autonomous_x_reflect_and_engage(
                    scroll_steps=steps,
                    publish_reflection=publish_reflection,
                    reply_count=reply_count,
                    dry_run=dry_run,
                )
            )

        elif action in ("x_publish_science", "x-publish-science"):
            topic = kwargs.get("topic")
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(
                self.browser.publish_scientific_knowledge_to_x(
                    topic=topic,
                    dry_run=dry_run,
                )
            )

        elif action in ("x_answer_comments", "x-answer-comments"):
            max_replies = int(kwargs.get("max_replies", 2))
            dry_run = bool(kwargs.get("dry_run", False))
            return asyncio.run(
                self.browser.inspect_and_reply_x_comments(
                    max_replies=max_replies,
                    dry_run=dry_run,
                )
            )

        else:
            return {
                "ok": False,
                "error": (
                    f"Acción desconocida '{action}'. Válidas: visit, search, learn, status, "
                    "daemon_cycle, x-feed, x-post, x-reply, x-reflect, x-publish-science, x-answer-comments"
                ),
            }

    def execute(self, *args, **kwargs) -> Any:
        return self.run(*args, **kwargs)


def get_module():
    return TardisBrowserEngine()
