"""
modulos_ftl/ftl_tardis4ever.py - Módulo FTL del Agente Soberano Tardis4Ever
===========================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU · FTL MASTER HUB INTEGRATION
Arquitecto: El Arquitecto (₪)

Directiva Soberana:
"Crea un agente que se llame Tardis4Ever y tendra la unica rutina de subir,
las actualizaciones de mis proyectos cada 24 horas de forma automatica,
pero cuando note un avance importante o llamativo lo suba y publique de forma inmediata.
Obvio con la seguridad de mi información personal."
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any

# Añadir core al path para importar el agente
CORE_DIR = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/core")
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

logger = logging.getLogger("FTL.Tardis4Ever")


class FtlTardis4Ever:
    """
    Puente de interoperabilidad FTL para el Agente Tardis4Ever.
    Permite invocar, verificar y despachar al agente desde el Master Hub FTL.
    """

    def __init__(self):
        self.name = "tardis4ever"
        self.version = "1.0.0"
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            try:
                from tardis4ever_agent import get_tardis4ever_agent
                self._agent = get_tardis4ever_agent()
            except Exception as e:
                logger.error(f"[FTL-TARDIS4EVER] Error cargando agente Tardis4Ever: {e}")
        return self._agent

    def run(self, action: str = "status", **kwargs) -> Dict[str, Any]:
        """
        Punto de entrada para el FTL Master Hub.
        Acciones:
          - 'status': Métricas y estado del agente.
          - 'check': Evalúa cambios en el ecosistema y dispara publicación si detecta hito o 24h.
          - 'sync': Fuerza una publicación y sincronización manual inmediata.
          - 'daemon_status': Verifica si el servicio systemd está activo.
        """
        action = action.lower().strip()
        if not self.agent:
            return {"status": "error", "error": "No se pudo inicializar Tardis4EverAgent"}

        if action == "status":
            return self.agent.get_status()
        elif action == "check":
            return self.agent.run_check_cycle()
        elif action == "sync":
            reasons = kwargs.get("reasons", ["Sincronización manual forzada desde Master Hub FTL"])
            score = int(kwargs.get("score", 100))
            return self.agent.execute_sovereign_publish("ftl_master_hub_override", score, reasons)
        elif action == "daemon_status":
            import subprocess
            res = subprocess.run(["systemctl", "--user", "is-active", "tardis4ever.service"],
                                 capture_output=True, text=True)
            return {
                "service": "tardis4ever.service",
                "active": res.stdout.strip() == "active",
                "state": res.stdout.strip()
            }
        else:
            return {
                "status": "error",
                "error": f"Acción '{action}' no reconocida.",
                "available_actions": ["status", "check", "sync", "daemon_status"]
            }

    # Alias de compatibilidad
    execute = run


_ftl_tardis4ever_instance = None

def get_module() -> FtlTardis4Ever:
    global _ftl_tardis4ever_instance
    if _ftl_tardis4ever_instance is None:
        _ftl_tardis4ever_instance = FtlTardis4Ever()
    return _ftl_tardis4ever_instance


if __name__ == "__main__":
    mod = get_module()
    print("=== FTL TARDIS4EVER :: ESTADO ===")
    print(json.dumps(mod.run("status"), indent=2))
