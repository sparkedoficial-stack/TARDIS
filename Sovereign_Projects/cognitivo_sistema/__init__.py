"""
__init__.py - Inicialización del Paquete Sistema Cognitivo Soberano
===================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4
"""

from cognitivo_sistema.cognitivo_core import CognitivoCore, get_cognitivo_core
from cognitivo_sistema.kernel_controller import KernelController, get_kernel_controller
from cognitivo_sistema.web_researcher import WebResearcher, get_web_researcher
from cognitivo_sistema.autoprogrammer import AutoProgrammer, get_auto_programmer
from cognitivo_sistema.simulation_engine import SimulationEngine, get_simulation_engine
from cognitivo_sistema.parallel_project import ParallelProjectManager, get_parallel_project_manager
from cognitivo_sistema.curiosity_engine import CuriosityEngine, get_curiosity_engine

__all__ = [
    "CognitivoCore",
    "get_cognitivo_core",
    "KernelController",
    "get_kernel_controller",
    "WebResearcher",
    "get_web_researcher",
    "AutoProgrammer",
    "get_auto_programmer",
    "SimulationEngine",
    "get_simulation_engine",
    "ParallelProjectManager",
    "get_parallel_project_manager",
    "CuriosityEngine",
    "get_curiosity_engine",
]
