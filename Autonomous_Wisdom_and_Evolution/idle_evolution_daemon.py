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

# Archivos que la auto-programacion no puede reescribir: el LLM elige el destino
# libremente y estos sostienen autenticacion, el motor del modelo y la propia
# validacion del auto-programador (que ya se habia reescrito a si mismo 305 veces).
SELF_MODIFY_PROTECTED = {
    "core/temporal_brain.py", "core/security.py", "core/device_vault.py",
    "core/telegram_bridge.py", "core/whatsapp_bridge.py", "core/autonomous_coder.py",
    "core/idle_evolution_daemon.py", "server/api.py", "omni_temporal_control.py",
    "client_gateway.py", "supervisor.py",
}

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
        # Los ciclos de auto-evolución se suspenden mientras haya llamadas de Telegram
        # activas: la prioridad absoluta es del interlocutor humano (Directiva Omega).
        self._call_suspend_count = 0
        self._conjectures: List[Dict[str, Any]] = self._load_conjectures()
        self.infinite_evolution_mode = os.environ.get("GIA_INFINITE_EVOLUTION", "1").lower() in ("1", "true", "yes")
        self.infinite_interval_seconds = float(os.environ.get("GIA_INFINITE_INTERVAL_SEC", "120.0"))
        self._last_dep_check = 0.0

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

    def suspend_for_call(self) -> bool:
        """Posterga los ciclos pesados de auto-evolución mientras haya una llamada."""
        with self._lock:
            self._call_suspend_count += 1
            suspended = self._call_suspend_count > 0
        self.record_user_activity()
        if suspended and self._call_suspend_count == 1:
            logger.info("⏸️ [IDLE_EVOLUTION] Auto-evolución suspendida: llamada prioritaria en curso.")
        return suspended

    def resume_after_call(self) -> bool:
        """Reanuda los ciclos de auto-evolución al finalizar la última llamada."""
        with self._lock:
            if self._call_suspend_count > 0:
                self._call_suspend_count -= 1
            remaining = self._call_suspend_count
        self.record_user_activity()
        if remaining == 0:
            logger.info("▶️ [IDLE_EVOLUTION] Auto-evolución reanudada: sin llamadas activas.")
        return remaining == 0

    def is_suspended_for_call(self) -> bool:
        if self._call_suspend_count > 0:
            return True
        try:
            from core.telegram_call_priority import is_call_priority_active

            return bool(is_call_priority_active())
        except Exception:
            return False

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
            logger.info(f"🌌 [IDLE_EVOLUTION] Centinela de Conjeturas y Auto-Mejora INICIADO (Modo Infinito: {self.infinite_evolution_mode}, Umbral: {self.idle_threshold_seconds / 60:.0f}m).")

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _watchdog_loop(self) -> None:
        """Bucle centinela infinito de auto-evolución continua y permanente 24/7."""
        logger.info(f"🌌 [INFINITE_EVOLUTION] Demonio de auto-evolución infinita ACTIVO 24/7.")
        while self._running:
            try:
                poll_interval = 25.0 if self.infinite_evolution_mode else 30.0
                time.sleep(poll_interval)
                if not self._running:
                    break
                # Prioridad absoluta al interlocutor: ningún ciclo de auto-mejora
                # compete por CPU/IO mientras haya una llamada de Telegram activa.
                if self.is_suspended_for_call():
                    self.record_user_activity()
                    continue

                # Condición 1: Modo Infinito (sin peticiones en los últimos 300s y no ocupado)
                if self.infinite_evolution_mode:
                    user_idle_s = self.get_idle_seconds()
                    idle_target = float(os.environ.get("GIA_IDLE_MIN_SECONDS", "300.0"))
                    if user_idle_s >= idle_target and not self._is_busy:
                        logger.info(f"🌌 [INFINITE_EVOLUTION] Ejecutando ciclo autónomo infinito (inactividad: {user_idle_s:.1f}s)...")
                        self.execute_evolution_cycle(force=True)
                        self.check_and_update_system_dependencies()
                else:
                    # Condición 2: Modo clásico por umbral (>= 30 minutos)
                    if self.is_idle() and not self._is_busy:
                        logger.info(f"⏳ [IDLE_EVOLUTION] Sistema sin peticiones por {self.get_idle_seconds() / 60:.1f} minutos. Activando ciclo...")
                        self.execute_evolution_cycle(force=False)
            except Exception as e:
                logger.error(f"Error en bucle de IdleEvolutionDaemon: {e}")
                time.sleep(10.0)

    def check_and_update_system_dependencies(self) -> Dict[str, Any]:
        """Comprueba y auto-actualiza dependencias y salud del repositorio de forma autónoma."""
        now = time.time()
        if (now - self._last_dep_check) < 600.0:  # Cada 10 minutos
            return {"status": "SKIPPED_INTERVAL"}
        self._last_dep_check = now
        try:
            from core.package_manager import get_package_manager
            pm = get_package_manager()
            env_info = pm.get_environment_info()
            return {"status": "CHECKED", "env": env_info}
        except Exception as e:
            logger.warning(f"[AUTO_UPDATE] Aviso en verificación de dependencias: {e}")
            return {"status": "ERROR", "error": str(e)}

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
        if not force and self.is_suspended_for_call():
            logger.info("[IDLE_EVOLUTION] Ciclo postergado: llamada prioritaria de Telegram activa.")
            return None
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
                target_p = (PROJECT_ROOT / code_target).resolve()
                rel = target_p.relative_to(PROJECT_ROOT.resolve()).as_posix() if target_p.is_relative_to(PROJECT_ROOT.resolve()) else None
                if rel is None or rel in SELF_MODIFY_PROTECTED:
                    logger.warning(f"🛡️ [IDLE_EVOLUTION] Auto-programacion bloqueada sobre archivo protegido: {code_target}")
                    evo_status = "BLOCKED_PROTECTED_FILE"
                elif target_p.is_file():
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

    @staticmethod
    def _parse_conjecture_json(raw_reply: str) -> Optional[Dict[str, Any]]:
        """
        Extrae y parsea de forma resiliente el objeto JSON de una conjetura generada por LLM.
        Tolera bloques <think>, cercas markdown sin cerrar, saltos de línea sin escapar,
        comas finales y respuestas truncadas al límite de tokens.
        """
        if not raw_reply or not isinstance(raw_reply, str):
            return None

        text = raw_reply.strip()
        # 1. Eliminar bloques de razonamiento interno (<think>...</think>) si existen
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

        # 2. Extraer contenido dentro de cercas markdown (cerradas o abiertas por truncado)
        if "```" in text:
            m = re.search(r"```(?:json)?\s*\n(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
            if m:
                text = m.group(1).strip()
            else:
                text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", text)
                text = re.sub(r"\n?```\s*$", "", text).strip()

        # 3. Recortar desde la primera llave de apertura '{'
        start_idx = text.find("{")
        if start_idx == -1:
            return None
        candidate = text[start_idx:]
        end_idx = candidate.rfind("}")
        sliced = candidate[: end_idx + 1] if end_idx != -1 else candidate

        def _escape_newlines_in_strings(src: str) -> str:
            out: List[str] = []
            in_str = False
            escaped = False
            for ch in src:
                if in_str:
                    if escaped:
                        out.append(ch)
                        escaped = False
                    elif ch == "\\":
                        out.append(ch)
                        escaped = True
                    elif ch == '"':
                        out.append(ch)
                        in_str = False
                    elif ch == "\n":
                        out.append("\\n")
                    elif ch == "\r":
                        out.append("\\r")
                    elif ch == "\t":
                        out.append("\\t")
                    elif ord(ch) < 0x20:
                        out.append(" ")
                    else:
                        out.append(ch)
                else:
                    if ch == '"':
                        in_str = True
                    out.append(ch)
            return "".join(out)

        def _try_load(src: str) -> Optional[Dict[str, Any]]:
            for attempt in (
                src,
                re.sub(r",\s*([}\]])", r"\1", src),
                re.sub(r",\s*([}\]])", r"\1", _escape_newlines_in_strings(src)),
            ):
                try:
                    parsed = json.loads(attempt, strict=False)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    continue
            return None

        parsed = _try_load(sliced)
        if parsed is None:
            # 4. Reparación estructural para JSON truncado (ej. Unterminated string)
            repaired = _escape_newlines_in_strings(candidate).rstrip()
            # Determinar si quedó dentro de una cadena abierta
            in_str = False
            escaped = False
            open_braces = 0
            open_brackets = 0
            for ch in repaired:
                if in_str:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        open_braces += 1
                    elif ch == "}":
                        open_braces = max(0, open_braces - 1)
                    elif ch == "[":
                        open_brackets += 1
                    elif ch == "]":
                        open_brackets = max(0, open_brackets - 1)

            if in_str:
                if repaired.endswith("\\"):
                    repaired = repaired[:-1]
                repaired += '"'
            repaired = re.sub(r",\s*$", "", repaired)
            # Si quedó una clave colgando tipo `"target_file":` sin valor
            repaired = re.sub(r',?\s*"[^"]+"\s*:\s*$', "", repaired)
            repaired += "]" * open_brackets + "}" * open_braces
            parsed = _try_load(repaired)

        if parsed is None:
            # 5. Último recurso: extracción de campos clave por regex sobre salida parcial
            fields: Dict[str, Any] = {}
            for key in ("title", "hypothesis", "research_query", "target_file", "code_improvement_goal"):
                m_null = re.search(rf'"{key}"\s*:\s*null\b', candidate, re.IGNORECASE)
                if m_null:
                    fields[key] = None
                    continue
                m_str = re.search(
                    rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"?',
                    candidate,
                    re.DOTALL,
                )
                if m_str:
                    val = m_str.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
                    if val:
                        fields[key] = val
            if fields.get("title") and fields.get("hypothesis"):
                parsed = fields

        if not isinstance(parsed, dict):
            return None
        title = str(parsed.get("title") or "").strip()
        hypothesis = str(parsed.get("hypothesis") or "").strip()
        if not title or not hypothesis:
            return None

        if not parsed.get("research_query"):
            parsed["research_query"] = title[:120]
        return parsed

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
                "Responde ÚNICAMENTE con un objeto JSON válido, compacto, en una sola respuesta sin texto adicional ni bloques markdown, "
                "manteniendo cada campo conciso (<= 2 frases) con esta estructura exacta:\n"
                "{\n"
                '  "title": "Título corto y potente de la conjetura",\n'
                '  "hypothesis": "Descripción concisa (máx 2 frases) de la hipótesis o conjetura",\n'
                '  "research_query": "Consulta de búsqueda web en inglés o español",\n'
                '  "target_file": "ruta_relativa/archivo.py (o null si solo es conceptual)",\n'
                '  "code_improvement_goal": "Descripción breve de la mejora de código (o null)"\n'
                "}"
            )

            user_prompt = (
                f"Estado actual: Sistema operativo ASUS TUF Linux x86_64.\n"
                f"Bóveda akáshica activa. Módulos clave: core/web_research_engine.py, "
                f"core/deep_memory_vault.py, core/network_shield.py, core/chronovision_engine.py.\n"
                f"Formula tu conjetura original y propuesta de auto-mejora ahora:"
            )

            raw_reply = ""
            if st.get("enabled") and st.get("has_key"):
                res = cloud_api.chat_completion([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ], max_tokens=1024, timeout=30.0)
                if res.get("ok") and res.get("reply"):
                    raw_reply = res["reply"].strip()

            if not raw_reply:
                # Inferencia soberana mediante Temporal Brain
                try:
                    from core.temporal_brain import get_temporal_brain
                    brain = get_temporal_brain()
                    res_tb = brain.chat(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.45,
                        max_tokens=1024
                    )
                    if res_tb.get("ok") and res_tb.get("reply"):
                        raw_reply = res_tb["reply"].strip()
                except Exception as e_tb:
                    logger.warning(f"Inferencia en Temporal Brain falló: {e_tb}")

            if not raw_reply:
                return None

            parsed = self._parse_conjecture_json(raw_reply)
            if parsed is None:
                logger.warning(
                    "Error formulando conjetura: JSON irrecuperable (len=%d, preview=%r)",
                    len(raw_reply),
                    raw_reply[:160],
                )
            return parsed

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
            "suspended_for_call": self.is_suspended_for_call(),
            "call_suspend_count": self._call_suspend_count,
            "total_conjectures": len(self._conjectures),
            "latest_conjecture": self._conjectures[-1] if self._conjectures else None,
            "timestamp": time.time()
        }

    def get_history(self, limit: Optional[int] = 20) -> List[Dict[str, Any]]:
        out = list(reversed(self._conjectures))
        if limit is None:
            return out
        return out[:max(1, int(limit))]


def get_idle_evolution_daemon() -> IdleEvolutionDaemon:
    return IdleEvolutionDaemon.get_instance()
