"""
cognitivo_core.py - Núcleo Coordinador del Sistema Cognitivo Soberano
====================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Punto de anclaje maestro que integra:
  - Telemetría y control de bajo nivel a nivel Kernel (Linux /proc, /sys, CPU, GPU).
  - Investigación web multi-fuente autónoma (DuckDuckGo, Wikipedia, ArXiv).
  - Auto-programación de software con validación AST y auto-reparación.
  - Motor de simulación para arte, física no-lineal y morfogénesis.
  - Proyecto propio paralelo e independiente con Diario Cognitivo Akáshico.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognitivo_sistema.config import (
    SYSTEM_ROOT,
    SOFTWARE_DIR,
    SIMULATION_DIR,
    KNOWLEDGE_DIR,
    PROJECT_DIR,
    DIARIO_COGNITIVO_PATH,
    ESTADO_SISTEMA_PATH,
)
from cognitivo_sistema.kernel_controller import get_kernel_controller, KernelController
from cognitivo_sistema.web_researcher import get_web_researcher, WebResearcher
from cognitivo_sistema.autoprogrammer import get_auto_programmer, AutoProgrammer
from cognitivo_sistema.simulation_engine import get_simulation_engine, SimulationEngine
from cognitivo_sistema.parallel_project import get_parallel_project_manager, ParallelProjectManager
from cognitivo_sistema.curiosity_engine import get_curiosity_engine, CuriosityEngine

logger = logging.getLogger("Cognitivo.Core")


class CognitivoCore:
    """
    Núcleo Central del Sistema Cognitivo TARDIS.
    """

    _instance: Optional[CognitivoCore] = None

    def __init__(self):
        self.kernel = get_kernel_controller()
        self.researcher = get_web_researcher()
        self.autoprogrammer = get_auto_programmer()
        self.simulation = get_simulation_engine()
        self.project_manager = get_parallel_project_manager()
        self.curiosity = get_curiosity_engine()
        logger.info("[COGNITIVO-CORE] ⚡ Sistema Cognitivo Soberano inicializado y anclado.")

    @classmethod
    def get_instance(cls) -> CognitivoCore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def learn_topic(self, topic: str) -> Dict[str, Any]:
        """Investiga un tema específico, programa herramientas, ejecuta simulaciones y aprende."""
        return self.curiosity.execute_cognitive_cycle(explicit_topic=topic)

    def auto_program(self, goal: str, topic: Optional[str] = None) -> Dict[str, Any]:
        """Crea directamente una herramienta o software validado por AST y sandbox."""
        resolved_topic = topic or goal
        artifact = self.autoprogrammer.generate_software_for_topic(
            topic=resolved_topic,
            specific_goal=goal
        )
        return artifact.to_dict()

    def simulate(self, sim_type: str, **kwargs) -> Dict[str, Any]:
        """Ejecuta una simulación con aceleración de hardware."""
        result = self.simulation.run_simulation(sim_type, **kwargs)
        return result.to_dict()

    def run_parallel_cycle(self) -> Dict[str, Any]:
        """Ejecuta un ciclo de investigación y creación para su proyecto propio paralelo."""
        return self.curiosity.execute_cognitive_cycle()

    def get_system_status(self) -> Dict[str, Any]:
        """Reporte integral del sistema: kernel, proyecto propio, software y memoria."""
        telemetry = self.kernel.get_telemetry()
        project_state = self.project_manager.get_project_state()
        recent_diary = self.project_manager.get_cognitive_diary(limit=3)

        generated_modules = list(SOFTWARE_DIR.glob("*.py"))
        simulation_files = list(SIMULATION_DIR.glob("*.*"))

        return {
            "kernel": telemetry.to_dict(),
            "parallel_project": {
                "name": project_state.get("project_name"),
                "mission": project_state.get("mission"),
                "cycles_completed": project_state.get("total_cycles_completed", 0),
                "syntropy_index": project_state.get("syntropy_index", 0.88),
                "mastered_domains": project_state.get("mastered_domains", []),
                "milestones": project_state.get("milestones", []),
                "gallery_count": len(project_state.get("gallery_catalog", [])),
            },
            "generated_software_count": len(generated_modules),
            "simulations_count": len(simulation_files),
            "recent_diary_entries": recent_diary
        }


def get_cognitivo_core() -> CognitivoCore:
    return CognitivoCore.get_instance()
