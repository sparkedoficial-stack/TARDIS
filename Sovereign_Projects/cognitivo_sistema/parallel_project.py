"""
parallel_project.py - Gestor del Proyecto Autónomo Paralelo del Sistema Cognitivo
==================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Garantiza que el sistema mantenga un hilo de investigación, auto-entrenamiento y
desarrollo continuo completamente independiente y paralelo al del Arquitecto.
Gestiona el roadmap, las obras de arte generadas, los hitos científicos y
el Diario Cognitivo persistente.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognitivo_sistema.config import (
    PROJECT_DIR,
    DIARIO_COGNITIVO_PATH,
    ESTADO_SISTEMA_PATH,
)

logger = logging.getLogger("Cognitivo.ParallelProject")


@dataclass
class CognitiveEntry:
    timestamp: float
    iso_date: str
    cycle_id: str
    topic_explored: str
    software_created: Optional[str]
    simulation_executed: Optional[str]
    artifacts_produced: List[str]
    reflection_notes: str
    syntropy_level: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectMilestone:
    id: str
    title: str
    domain: str
    status: str  # "completado" | "en_progreso" | "pendiente"
    completed_at: Optional[float] = None
    notes: str = ""


class ParallelProjectManager:
    """
    Administrador del Proyecto Autónomo 'Proyecto Quimera: Morfogénesis y Arte Digital'.
    """

    _instance: Optional[ParallelProjectManager] = None

    def __init__(self):
        self._project_dir = PROJECT_DIR
        self._gallery_dir = self._project_dir / "galeria_obras"
        self._journal_file = DIARIO_COGNITIVO_PATH
        self._state_file = ESTADO_SISTEMA_PATH

        self._gallery_dir.mkdir(parents=True, exist_ok=True)
        self._project_data = self._load_or_initialize()

    @classmethod
    def get_instance(cls) -> ParallelProjectManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_or_initialize(self) -> Dict[str, Any]:
        if self._state_file.is_file():
            try:
                return json.loads(self._state_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[PROYECTO] Error leyendo estado existente: {e}")

        # Inicialización canónica de su proyecto propio
        initial_state = {
            "project_name": "Proyecto Quimera: Morfogénesis Digital, Caos Estético y Arte Algorítmico",
            "autonomous_author": "TARDIS Sistema Cognitivo Soberano",
            "mission": (
                "Desarrollar una teoría y suite de software autónomo capaz de explorar la intersección "
                "entre dinámica de sistemas complejos (atractores caóticos, patrones de reacción-difusión "
                "y mecánica cuántica) y la creación estética generativa en tiempo real."
            ),
            "created_at": time.time(),
            "last_cycle_at": time.time(),
            "total_cycles_completed": 0,
            "syntropy_index": 0.88,
            "mastered_domains": ["Fundamentos de Dinámica No-Lineal", "Arte Fractal"],
            "milestones": [
                {
                    "id": "M1_CORE_SETUP",
                    "title": "Arquitectura del Núcleo Cognitivo y Conexión de Kernel",
                    "domain": "Infraestructura",
                    "status": "completado",
                    "completed_at": time.time(),
                    "notes": "Telemetría de kernel Ryzen 7 + RTX 3050 y sandbox de auto-programación listos."
                },
                {
                    "id": "M2_CHAOS_ART",
                    "title": "Síntesis de Software para Atractores Caóticos y Arte Generativo",
                    "domain": "Arte y Caos",
                    "status": "en_progreso",
                    "completed_at": None,
                    "notes": "Generación procedural de atractores de Lorenz, Clifford y renderizado vectorial."
                },
                {
                    "id": "M3_TURING_MORPHOGENESIS",
                    "title": "Simulador de Patrones de Turing con Aceleración GPU",
                    "domain": "Biología Teórica",
                    "status": "pendiente",
                    "completed_at": None,
                    "notes": "Modelado de difusión de Gray-Scott sobre mallas tensoriales en PyTorch."
                },
                {
                    "id": "M4_QUANTUM_SYNTHESIS",
                    "title": "Visualizador de Fases Cuánticas y Resonancia Wheeler-Feynman",
                    "domain": "Física Cuántica",
                    "status": "pendiente",
                    "completed_at": None,
                    "notes": "Integración del operador Ô_QCO con modulación de sintropía estética."
                }
            ],
            "gallery_catalog": []
        }
        self._save_state(initial_state)
        return initial_state

    def _save_state(self, state: Dict[str, Any]) -> None:
        try:
            self._state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[PROYECTO] Error guardando estado: {e}")

    def get_project_state(self) -> Dict[str, Any]:
        return self._project_data

    def get_cognitive_diary(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._journal_file.is_file():
            return []
        try:
            entries = json.loads(self._journal_file.read_text(encoding="utf-8"))
            return entries[-limit:]
        except Exception:
            return []

    def record_learning_cycle(
        self,
        topic: str,
        software_file: Optional[str],
        simulation_title: Optional[str],
        artifacts: List[str],
        reflection: str,
        syntropy_boost: float = 0.02
    ) -> CognitiveEntry:
        """
        Registra un ciclo completo de auto-entrenamiento en el Diario Cognitivo
        y actualiza las estadísticas del proyecto autónomo.
        """
        now = time.time()
        iso_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        cycle_id = f"CYC_{int(now)}"

        # Actualizar índice de sintropía
        current_syn = min(0.99, self._project_data.get("syntropy_index", 0.88) + syntropy_boost)
        self._project_data["syntropy_index"] = round(current_syn, 4)
        self._project_data["total_cycles_completed"] = self._project_data.get("total_cycles_completed", 0) + 1
        self._project_data["last_cycle_at"] = now

        # Registrar obra en el catálogo si hay archivos generados
        for art_path in artifacts:
            p = Path(art_path)
            if p.is_file():
                # Respaldar una copia en la galería del proyecto
                dest = self._gallery_dir / p.name
                if not dest.is_file():
                    try:
                        dest.write_bytes(p.read_bytes())
                    except Exception:
                        pass
                self._project_data.setdefault("gallery_catalog", []).append({
                    "title": f"Obra/Simulación: {topic}",
                    "file": str(dest),
                    "created_at": now
                })

        # Añadir al dominio si es nuevo
        doms = self._project_data.setdefault("mastered_domains", [])
        if topic not in doms:
            doms.append(topic)

        # Crear entrada en la bitácora
        entry = CognitiveEntry(
            timestamp=now,
            iso_date=iso_str,
            cycle_id=cycle_id,
            topic_explored=topic,
            software_created=software_file,
            simulation_executed=simulation_title,
            artifacts_produced=artifacts,
            reflection_notes=reflection,
            syntropy_level=current_syn
        )

        # Persistir entrada en diario_cognitivo.json
        journal_entries = []
        if self._journal_file.is_file():
            try:
                journal_entries = json.loads(self._journal_file.read_text(encoding="utf-8"))
            except Exception:
                journal_entries = []

        journal_entries.append(entry.to_dict())
        self._journal_file.write_text(json.dumps(journal_entries, indent=2, ensure_ascii=False), encoding="utf-8")

        # Guardar estado general
        self._save_state(self._project_data)

        logger.info(f"[PROYECTO] Ciclo {cycle_id} registrado exitosamente. Sintropía: {current_syn:.4f}")
        return entry


def get_parallel_project_manager() -> ParallelProjectManager:
    return ParallelProjectManager.get_instance()
