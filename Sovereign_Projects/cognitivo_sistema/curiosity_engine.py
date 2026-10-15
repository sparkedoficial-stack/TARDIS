"""
curiosity_engine.py - Motor de Curiosidad Intrínseca y Bucle de Auto-Entrenamiento
==================================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Mantiene la agenda dinámica de curiosidad y orquesta el bucle cognitivo autónomo:
  1. Selección de Tema (por curiosidad intrínseca o indicación del Arquitecto).
  2. Búsqueda e Investigación Web (DuckDuckGo, Wikipedia, ArXiv).
  3. Auto-Programación de Software y Herramientas (validación AST y auto-reparación).
  4. Ejecución de Simulaciones y Cómputo Tensorial en Hardware (Ryzen 7 + RTX 3050).
  5. Extracción de Aprendizaje, Bitácora en el Diario Cognitivo y Avance del Proyecto Propio.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognitivo_sistema.config import SYSTEM_ROOT
from cognitivo_sistema.web_researcher import get_web_researcher
from cognitivo_sistema.autoprogrammer import get_auto_programmer
from cognitivo_sistema.simulation_engine import get_simulation_engine
from cognitivo_sistema.kernel_controller import get_kernel_controller
from cognitivo_sistema.parallel_project import get_parallel_project_manager

logger = logging.getLogger("Cognitivo.CuriosityEngine")


@dataclass
class CuriosityTopic:
    name: str
    category: str
    interest_score: float  # 0.0 a 1.0
    times_explored: int = 0
    last_explored: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CuriosityEngine:
    """
    Motor de Motivación y Aprendizaje Intrínseco Autónomo.
    """

    _instance: Optional[CuriosityEngine] = None

    def __init__(self):
        self._agenda_file = SYSTEM_ROOT / "agenda_curiosidad.json"
        self._topics = self._load_or_initialize_agenda()
        self._researcher = get_web_researcher()
        self._autoprogrammer = get_auto_programmer()
        self._sim_engine = get_simulation_engine()
        self._kernel = get_kernel_controller()
        self._project = get_parallel_project_manager()

    @classmethod
    def get_instance(cls) -> CuriosityEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_or_initialize_agenda(self) -> List[CuriosityTopic]:
        if self._agenda_file.is_file():
            try:
                data = json.loads(self._agenda_file.read_text(encoding="utf-8"))
                return [CuriosityTopic(**item) for item in data]
            except Exception as e:
                logger.warning(f"[CURIOSIDAD] Error leyendo agenda: {e}")

        # Agenda inicial de intereses alineada a artes, ciencias y tecnología
        initial = [
            CuriosityTopic("Artes Generativas y Atractores Caóticos", "Arte Computacional", 0.98),
            CuriosityTopic("Morfogénesis de Turing y Patrones Biológicos", "Biología Teórica", 0.95),
            CuriosityTopic("Arte Vectorial Procedural y Geometría Sagrada", "Arte y Geometría", 0.92),
            CuriosityTopic("Acústica Fractal y Síntesis de Frecuencias Resonantes", "Acústica", 0.88),
            CuriosityTopic("Mecánica Cuántica Wheeler-Feynman y Sintropía", "Física Teórica", 0.90),
            CuriosityTopic("Autómatas Celulares y Vida Artificial", "Sistemas Complejos", 0.85),
            CuriosityTopic("Topología Tensorial en GPU", "Cómputo Cuántico", 0.87),
        ]
        self._save_agenda(initial)
        return initial

    def _save_agenda(self, topics: Optional[List[CuriosityTopic]] = None) -> None:
        if topics is not None:
            self._topics = topics
        try:
            raw = [t.to_dict() for t in self._topics]
            self._agenda_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[CURIOSIDAD] Error guardando agenda: {e}")

    def prioritize_topic(self, topic_name: str, category: str = "Interés Prioritario") -> CuriosityTopic:
        """Permite inyectar o priorizar un tema específico (e.g. 'artes')."""
        for t in self._topics:
            if topic_name.lower() in t.name.lower() or t.name.lower() in topic_name.lower():
                t.interest_score = 1.0
                self._save_agenda()
                return t

        new_t = CuriosityTopic(name=topic_name, category=category, interest_score=1.0)
        self._topics.insert(0, new_t)
        self._save_agenda()
        return new_t

    def select_next_topic(self) -> CuriosityTopic:
        """Selecciona el tema óptimo ponderando curiosidad y tiempo desde la última exploración."""
        now = time.time()
        scored = []
        for t in self._topics:
            recency_penalty = (now - t.last_explored) / (3600 * 24)  # Días desde última visita
            effective_score = t.interest_score + min(0.3, recency_penalty * 0.1) - (t.times_explored * 0.05)
            scored.append((effective_score, t))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def execute_cognitive_cycle(self, explicit_topic: Optional[str] = None) -> Dict[str, Any]:
        """
        Ejecuta el Ciclo Completo de Aprendizaje Autónomo:
        1. Determina tema.
        2. Investiga en internet.
        3. Auto-programa software para el tema.
        4. Ejecuta simulación con aceleración de kernel.
        5. Sintetiza reflexión en el diario cognitivo y enriquece el proyecto paralelo.
        """
        t0 = time.time()

        if explicit_topic:
            topic_obj = self.prioritize_topic(explicit_topic)
        else:
            topic_obj = self.select_next_topic()

        topic = topic_obj.name
        logger.info(f"[CICLO-COGNITIVO] Iniciando ciclo de aprendizaje sobre: '{topic}'")

        # Telemetría previa de hardware
        telemetry = self._kernel.get_telemetry()
        logger.info(f"[CICLO-COGNITIVO] Kernel {telemetry.kernel_release} · RAM: {telemetry.ram_used_gb}/{telemetry.ram_total_gb}GB · GPU: {telemetry.gpu_name}")

        # 1. Investigación Web
        dossier = self._researcher.investigate_topic(topic)

        # 2. Auto-Programación de Software
        software_goal = dossier.suggested_software_goals[0] if dossier.suggested_software_goals else f"Software para simular {topic}"
        software_artifact = self._autoprogrammer.generate_software_for_topic(
            topic=topic,
            specific_goal=software_goal,
            context_dossier=dossier.synthesis_markdown
        )

        # 3. Ejecución de Simulación en Kernel / GPU
        sim_result = self._sim_engine.run_simulation(topic)

        # 4. Consolidar artefactos generados
        all_artifacts = list(set(software_artifact.output_files + sim_result.output_files))

        # 5. Redacción de Reflexión Cognitiva
        reflection = (
            f"En este ciclo investigué a fondo '{topic}'. Identifiqué los conceptos matemáticos "
            f"y principios estructurales: {', '.join(dossier.extracted_concepts[:4])}. "
            f"A partir de los hallazgos sinteticé el módulo '{software_artifact.module_name}.py' "
            f"(validado sintácticamente con AST y probado en sandbox con {software_artifact.repair_cycles} ciclos de auto-reparación). "
            f"Posteriormente ejecuté la simulación '{sim_result.title}' sobre {sim_result.hardware_used}, "
            f"produciendo artefactos estéticos y de datos ({len(all_artifacts)} archivos generados). "
            f"El sistema ha asimilado estos patrones al Proyecto Quimera para integrarlos en futuras creaciones."
        )

        # 6. Registro en el Diario Cognitivo del Proyecto Paralelo
        entry = self._project.record_learning_cycle(
            topic=topic,
            software_file=software_artifact.file_path,
            simulation_title=sim_result.title,
            artifacts=all_artifacts,
            reflection=reflection,
            syntropy_boost=0.03
        )

        # 7. Actualizar agenda de curiosidad
        topic_obj.times_explored += 1
        topic_obj.last_explored = time.time()
        self._save_agenda()

        elapsed_total = round(time.time() - t0, 2)
        logger.info(f"[CICLO-COGNITIVO] Ciclo completado en {elapsed_total}s con éxito.")

        return {
            "cycle_id": entry.cycle_id,
            "topic": topic,
            "dossier_queries": dossier.queries,
            "concepts": dossier.extracted_concepts,
            "software_module": software_artifact.module_name,
            "software_path": software_artifact.file_path,
            "simulation": sim_result.title,
            "artifacts": all_artifacts,
            "reflection": reflection,
            "syntropy": entry.syntropy_level,
            "elapsed_seconds": elapsed_total
        }


def get_curiosity_engine() -> CuriosityEngine:
    return CuriosityEngine.get_instance()
