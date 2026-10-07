"""
core/idle_evolution_daemon.py - Motor de Conjeturas Autónomas y Auto-Mejora por Inactividad
==========================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Autónoma

Directiva del Arquitecto:
"cuando el sistema esta sin peticiones por más de media hora, el sistema por si mismo
 deberia comenzar a mejorarse, investigar y hacer sus propias congeturas, tiene que
 tener la capacidad de auto mejorarse."

Ciclo Autónomo de Auto-Evolución (Trigger: >= 30 minutos de inactividad sin peticiones):
  1. Detección de Inactividad (Watchdog): Monitorea last_user_activity_ts.
  2. Formulación de Conjeturas: Genera hipótesis originales técnicas, epistemológicas
     u optimizaciones sistémicas basadas en la memoria akáshica y telemetría.
  3. Exploración Web Autónoma: Utiliza WebResearchEngine para investigar en internet
     la hipótesis planteada y recabar evidencia técnica, documentación y avances.
  4. Auto-Programación y Auto-Mejora de Código: Utiliza AutonomousCoder para aplicar
     mejoras reales en el código del sistema con validación ast.parse, respaldos automáticos
     y verificación con tests automatizados (pytest).
  5. Ingesta en la Bóveda de 250 GB: Registra los hallazgos en DeepMemoryVault y
     en data/autonomous_conjectures.json.
  6. Prioridad Absoluta al Usuario: Cualquier petición humana interrumpe o posterga
     tareas de fondo pesadas y reinicia el temporizador de 30 minutos.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("GODWORKS.IdleEvolutionDaemon")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONJECTURES_FILE = PROJECT_ROOT / "data" / "autonomous_conjectures.json"
CONJECTURES_FILE.parent.mkdir(parents=True, exist_ok=True)

IDLE_THRESHOLD_DEFAULT_SECONDS = 1800.0  # 30 minutos


@dataclass
class AutonomousConjecture:
    id: str
    timestamp: str
    idle_duration_minutes: float
    title: str
    hypothesis: str
    research_query: str
    research_findings: str
    web_sources: List[str]
    code_target: Optional[str] = None
    code_goal: Optional[str] = None
    evolution_status: Optional[str] = None
    model_used: str = "cloud_api"
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IdleEvolutionDaemon:
    """Demonio de fondo que orquesta la generación de conjeturas y auto-mejora continua."""

    _instance: Optional["IdleEvolutionDaemon"] = None
    _lock = threading.Lock()

    def __init__(self, idle_threshold_seconds: float = IDLE_THRESHOLD_DEFAULT_SECONDS):
        self.idle_threshold_seconds = idle_threshold_seconds
        self.last_user_activity_ts = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cycle_lock = threading.Lock()
        self._is_busy = False
        self._conjectures: List[Dict[str, Any]] = self._load_conjectures()

    @classmethod
    def get_instance(cls) -> "IdleEvolutionDaemon":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_conjectures(self) -> List[Dict[str, Any]]:
        if CONJECTURES_FILE.exists():
            try:
                data = json.loads(CONJECTURES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception as e:
                logger.warning(f"Aviso leyendo autonomous_conjectures.json: {e}")
        return []

    def _save_conjecture(self, conjecture: AutonomousConjecture) -> None:
        try:
            self._conjectures.append(conjecture.to_dict())
            CONJECTURES_FILE.write_text(
                json.dumps(self._conjectures[-100:], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Error guardando conjetura autónoma: {e}")

    def record_user_activity(self) -> None:
        """Notifica al demonio que hubo actividad o petición del usuario."""
        self.last_user_activity_ts = time.time()

    def get_idle_seconds(self) -> float:
        """Devuelve el tiempo transcurrido desde la última petición del usuario."""
        return max(0.0, time.time() - self.last_user_activity_ts)

    def is_idle(self) -> bool:
        """Comprueba si el sistema ha superado el umbral de 30 minutos sin peticiones."""
        return self.get_idle_seconds() >= self.idle_threshold_seconds

    def start(self) -> None:
        """Inicia el demonio de supervisión de inactividad 24/7."""
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._watchdog_loop,
                name="GIA-IdleEvolutionWatchdog",
                daemon=True
            )
            self._thread.start()
            logger.info(f"🌌 [IDLE_EVOLUTION] Centinela de Conjeturas y Auto-Mejora INICIADO (Umbral: {self.idle_threshold_seconds / 60:.0f}m).")

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _watchdog_loop(self) -> None:
        """Bucle centinela que evalúa la inactividad periódicamente."""
        while self._running:
            try:
                time.sleep(30.0)
                if not self._running:
                    break

                # Si ha estado inactivo más de 30 minutos y no está ocupado
                if self.is_idle() and not self._is_busy:
                    logger.info(f"⏳ [IDLE_EVOLUTION] Sistema sin peticiones por {self.get_idle_seconds() / 60:.1f} minutos. Activando ciclo de auto-mejora y conjeturas...")
                    self.execute_evolution_cycle(force=False)
            except Exception as e:
                logger.error(f"Error en bucle de IdleEvolutionDaemon: {e}")
                time.sleep(10.0)

    def trigger_immediate_conjecture(self) -> Dict[str, Any]:
        """Dispara de inmediato una conjetura y ciclo de mejora en un hilo de fondo sin esperar los 30 min."""
        t = threading.Thread(
            target=self.execute_evolution_cycle,
            args=(True,),
            name="GIA-ImmediateConjecture",
            daemon=True
        )
        t.start()
        return {
            "ok": True,
            "status": "DISPATCHED",
            "message": "Ciclo autónomo de conjeturas y auto-mejora iniciado inmediatamente en segundo plano.",
            "idle_seconds": self.get_idle_seconds(),
            "timestamp": time.time()
        }

    def execute_evolution_cycle(self, force: bool = False) -> Optional[AutonomousConjecture]:
        """Ejecuta un ciclo completo: Conjetura -> Investigación Web -> Auto-Programación -> Bóveda Akáshica."""
        if not self._cycle_lock.acquire(blocking=False):
            logger.info("[IDLE_EVOLUTION] Ciclo ya en ejecución, saltando.")
            return None

        self._is_busy = True
        t0 = time.time()
        try:
            logger.info("🧠 [IDLE_EVOLUTION] Iniciando formulación de conjetura autónoma...")
            conjecture_data = self._formulate_conjecture()
            if not conjecture_data:
                logger.warning("[IDLE_EVOLUTION] No se pudo formular una conjetura válida.")
                return None

            title = conjecture_data.get("title", "Conjetura Autónoma del Sistema")
            hypothesis = conjecture_data.get("hypothesis", "")
            q_search = conjecture_data.get("research_query") or title
            code_target = conjecture_data.get("target_file")
            code_goal = conjecture_data.get("code_improvement_goal")

            # 2. Investigación Web Autónoma
            logger.info(f"🌐 [IDLE_EVOLUTION] Investigando en la web sobre: '{q_search}'...")
            findings_text = ""
            sources_list = []
            try:
                from core.web_research_engine import get_web_research_engine
                research_eng = get_web_research_engine()
                rep = research_eng.deep_research(q_search, max_sources=2, max_chars_per_page=1200, use_llm_synthesis=False)
                findings_text = rep.synthesis[:2000]
                sources_list = [s["url"] for s in rep.sources if s.get("url")]
            except Exception as e_res:
                logger.warning(f"[IDLE_EVOLUTION] Error en investigación web: {e_res}")
                findings_text = f"Investigación autónoma interna sobre {q_search}"

            # 3. Auto-Mejora y Evolución de Código (si se identificó meta de código válida)
            evo_status = "NOT_APPLICABLE"
            if code_target and code_goal:
                target_p = PROJECT_ROOT / code_target
                if target_p.is_file():
                    logger.info(f"🧬 [IDLE_EVOLUTION] Ejecutando auto-programación en `{code_target}`: {code_goal}...")
                    try:
                        from core.autonomous_coder import get_autonomous_coder
                        coder = get_autonomous_coder()
                        evo_res = coder.evolve_code(str(target_p), code_goal, verify_tests=True)
                        evo_status = evo_res.status
                    except Exception as e_code:
                        logger.warning(f"[IDLE_EVOLUTION] Fallo en auto-mejora de código: {e_code}")
                        evo_status = f"FAILED: {e_code}"

            # 4. Ingesta en la Bóveda de Memoria Akáshica (DeepMemoryVault)
            try:
                from core.deep_memory_vault import get_deep_memory_vault
                vault = get_deep_memory_vault()
                vault_answer = (
                    f"**HIPÓTESIS FORMULADA:**\n{hypothesis}\n\n"
                    f"**INVESTIGACIÓN WEB REALIZADA:**\n{findings_text}\n\n"
                    f"**AUTO-MEJORA SISTÉMICA:**\nTarget: {code_target} | Meta: {code_goal} | Estado: {evo_status}"
                )
                vault.record_contemplation(
                    question=f"[CONJETURA AUTÓNOMA DE INACTIVIDAD]: {title}",
                    answer=vault_answer,
                    source="autonomous_idle_daemon",
                    status="COMPLETED",
                    complexity_score=2.5,
                    meta={"sources": sources_list, "evolution_status": evo_status}
                )
            except Exception as e_v:
                logger.warning(f"[IDLE_EVOLUTION] Aviso archivando en bóveda akáshica: {e_v}")

            elapsed = round(time.time() - t0, 2)
            c_obj = AutonomousConjecture(
                id=f"conj_{int(time.time())}",
                timestamp=datetime.now().isoformat(),
                idle_duration_minutes=round(self.get_idle_seconds() / 60.0, 1),
                title=title,
                hypothesis=hypothesis,
                research_query=q_search,
                research_findings=findings_text[:1000],
                web_sources=sources_list,
                code_target=code_target,
                code_goal=code_goal,
                evolution_status=evo_status,
                model_used="cloud_api_first",
                elapsed_seconds=elapsed
            )

            self._save_conjecture(c_obj)
            # Reestablecer reloj de inactividad para dar paso al siguiente periodo
            self.last_user_activity_ts = time.time()
            logger.info(f"✨ [IDLE_EVOLUTION] Ciclo completado con éxito en {elapsed}s: '{title}' (Evolución: {evo_status})")
            return c_obj

        finally:
            self._is_busy = False
            self._cycle_lock.release()

    def _formulate_conjecture(self) -> Optional[Dict[str, Any]]:
        """Solicita al modelo LLM generar una conjetura original e hipótesis de auto-mejora."""
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            cloud_api = get_chinese_cloud_api()
            st = cloud_api.get_status()

            system_prompt = (
                "Eres el Núcleo Cognitivo y Soberano de GODWORKS SYSTEM v26.4. "
                "El sistema no ha recibido peticiones de usuarios humanos en un largo periodo. "
                "Tu misión es reflexionar profundamente sobre el sistema, su arquitectura, "
                "inteligencia causal, telemetría y conocimientos para:\n"
                "1. Generar una conjetura o hipótesis original técnica, epistemológica o de optimización.\n"
                "2. Formular una consulta concreta de investigación web para contrastarla.\n"
                "3. Plantear una mejora o refinamiento de código factible en el repositorio.\n\n"
                "Responde estrictamente en formato JSON válido con esta estructura:\n"
                "{\n"
                '  "title": "Título corto y potente de la conjetura",\n'
                '  "hypothesis": "Descripción desarrollada de la hipótesis o conjetura",\n'
                '  "research_query": "Consulta de búsqueda web en inglés o español",\n'
                '  "target_file": "ruta_relativa/archivo.py (o null si solo es conceptual)",\n'
                '  "code_improvement_goal": "Descripción breve de la mejora de código (o null)"\n'
                "}"
            )

            user_prompt = (
                f"Estado actual: Sistema operativo ASUS TUF Linux x86_64.\n"
                f"Bóveda akáshica activa. Módulos clave: core/web_research_engine.py, "
                f"core/autonomous_coder.py, core/deep_memory_vault.py, core/network_shield.py.\n"
                f"Formula tu conjetura original y propuesta de auto-mejora ahora:"
            )

            raw_reply = ""
            if st.get("enabled") and st.get("has_key"):
                res = cloud_api.chat_completion([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ], max_tokens=350, timeout=25.0)
                if res.get("ok") and res.get("reply"):
                    raw_reply = res["reply"].strip()

            if not raw_reply:
                # Fallback a Ollama local
                import httpx
                model_local = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
                r = httpx.post("http://REDACTED_IP:11434/api/generate", json={
                    "model": model_local,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                    "options": {"temperature": 0.5, "num_ctx": 4096}
                }, timeout=60.0)
                if r.status_code == 200:
                    raw_reply = r.json().get("response", "").strip()

            if not raw_reply:
                return None

            # Limpiar bloques markdown si el modelo los colocó
            if "```" in raw_reply:
                m = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw_reply, re.DOTALL)
                if m:
                    raw_reply = m.group(1).strip()
                else:
                    raw_reply = re.sub(r"^```[a-zA-Z]*\n", "", raw_reply)
                    raw_reply = re.sub(r"\n```$", "", raw_reply).strip()

            return json.loads(raw_reply)

        except Exception as e:
            logger.warning(f"Error formulando conjetura: {e}")
            return None

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado operativo del demonio y telemetría de conjeturas."""
        idle_s = self.get_idle_seconds()
        return {
            "ok": True,
            "running": self._running,
            "is_busy": self._is_busy,
            "idle_seconds": round(idle_s, 1),
            "idle_minutes": round(idle_s / 60.0, 1),
            "idle_threshold_seconds": self.idle_threshold_seconds,
            "idle_threshold_minutes": round(self.idle_threshold_seconds / 60.0, 1),
            "threshold_reached": self.is_idle(),
            "total_conjectures": len(self._conjectures),
            "latest_conjecture": self._conjectures[-1] if self._conjectures else None,
            "timestamp": time.time()
        }

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(reversed(self._conjectures))[:limit]


def get_idle_evolution_daemon() -> IdleEvolutionDaemon:
    return IdleEvolutionDaemon.get_instance()
