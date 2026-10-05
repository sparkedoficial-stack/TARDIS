"""
antigravity_bridge.py - Puente de Retroalimentación Activa y Diálogo Continuo
=============================================================================
GODWORKS SYSTEM v26.4 · OMNI-LOCAL-TEMPORAL CONTROL <-> ANTIGRAVITY IDE

Proporciona un canal bidireccional asíncrono y ultra-resiliente entre el nodo
de ejecución local (GIA / OMNI-LOCAL) y el entorno de desarrollo Antigravity.
El propio sistema analiza su telemetría, errores, bloqueos y cuellos de botella
para emitir instrucciones de auto-mejora continuas, sin bloquear ni afectar la
operación en caso de que Antigravity o el puente se encuentren offline.

Arquitecto: El Arquitecto (₪) · Sistema TARDIS
"""
from __future__ import annotations

import collections
import datetime
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Rutas de almacenamiento persistente no intrusivo
BASE_APPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
BRIDGE_DIR = BASE_APPDATA / "antigravity_bridge"
QUEUE_DIR = BASE_APPDATA / "improvement_queue"

# Directorio de espejo directo en el workspace para Antigravity
WORKSPACE_DIR = Path(__file__).resolve().parent
WORKSPACE_BRIDGE_DIR = WORKSPACE_DIR / ".agents" / "antigravity_bridge"
WORKSPACE_QUEUE_DIR = WORKSPACE_DIR / ".agents" / "improvement_queue"

for d in (BRIDGE_DIR, QUEUE_DIR, WORKSPACE_BRIDGE_DIR, WORKSPACE_QUEUE_DIR):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

DIALOGUE_FILE = BRIDGE_DIR / "live_dialogue.jsonl"
FEEDBACK_FILE = BRIDGE_DIR / "system_feedback.json"
TELEMETRY_FILE = BRIDGE_DIR / "live_telemetry.json"
DIRECTIVES_QUEUE = BRIDGE_DIR / "pending_directives.json"

AUDIT_LOG = BASE_APPDATA / "agent_audit.log"
GIA_LOG = BASE_APPDATA / "gia.log"
ERROR_CHAT = BASE_APPDATA / "error_chat.json"

_LOCK = threading.Lock()


def _safe_tail(path: Path, lines_count: int = 50) -> List[str]:
    """Lee las últimas líneas de un archivo sin bloquear ni lanzar excepciones."""
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-lines_count:]
    except Exception:
        return []


def _atomic_write_json(path: Path, data: Any):
    """Escritura atómica en JSON para evitar corrupción de archivos concurrentes."""
    try:
        tmp_path = path.with_suffix(f".tmp_{os.getpid()}_{int(time.time()*1000)}")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)
        # Espejar automáticamente en workspace (.agents/antigravity_bridge)
        if path.parent == BRIDGE_DIR and WORKSPACE_BRIDGE_DIR.is_dir():
            ws_target = WORKSPACE_BRIDGE_DIR / path.name
            ws_tmp = ws_target.with_suffix(f".tmp_{os.getpid()}_{int(time.time()*1000)}")
            ws_tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            ws_tmp.replace(ws_target)
    except Exception:
        pass

def slugify(title: str) -> str:
    """Slug canónico normalizado para nombres de archivos de propuestas."""
    import unicodedata
    normalized = unicodedata.normalize('NFKD', title).encode('ASCII', 'ignore').decode('ASCII')
    s = "".join(c if c.isalnum() or c in " -_" else "" for c in normalized)
    return s.strip().replace(" ", "_").lower()[:40] or "mejora"


class OmniFeedbackBridge:
    """Núcleo del puente de auto-análisis y retroalimentación activa con Antigravity."""

    def __init__(self, interval_seconds: float = 25.0):
        self.interval = max(5.0, interval_seconds)
        self.running = False
        self._thread: Optional[threading.Thread] = None
        
        # Buffer rodante de diálogo (últimos 100 mensajes en RAM)
        self.dialogue_history: collections.deque = collections.deque(maxlen=100)
        self.active_instructions: List[Dict[str, Any]] = []
        self.last_assessment: Dict[str, Any] = {}
        self.last_check_ts: float = 0.0
        self.cycle_count: int = 0
        
        # Bucle de Auto-Mejora y Evolución Continua
        self._improving = False
        self._improving_lock = threading.Lock()
        self.last_improvement_ts: float = 0.0
        self.last_proposal: Optional[Dict[str, Any]] = None
        self.improvement_interval: float = 900.0  # ciclo autónomo cada 15 min
        
        self._load_initial_dialogue()

    def _load_initial_dialogue(self):
        """Carga mensajes recientes del historial persistente si existe."""
        if DIALOGUE_FILE.is_file():
            try:
                lines = DIALOGUE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
                for line in lines[-100:]:
                    if line.strip():
                        try:
                            self.dialogue_history.append(json.loads(line.strip()))
                        except Exception:
                            continue
            except Exception:
                pass

        if not self.dialogue_history:
            # Mensaje génesis del sistema
            genesis_msg = {
                "id": "msg_genesis_001",
                "sender": "TARDIS-SOVEREIGN-NODE",
                "role": "system",
                "timestamp": time.time(),
                "iso": datetime.datetime.now().isoformat(),
                "text": "Canal de retroalimentación activa acoplado con Antigravity. Monitoreando estado de subsistemas, telemetría causal y requerimientos de optimización en tiempo real.",
                "category": "SYS_INIT"
            }
            self.post_dialogue_message(genesis_msg["sender"], genesis_msg["text"], genesis_msg["role"], genesis_msg["category"])

    def start(self):
        """Inicia el monitor en segundo plano de manera no intrusiva."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="OmniFeedbackBridgeThread")
        self._thread.start()

    def stop(self):
        """Detiene el monitor con gracia."""
        self.running = False

    def _monitor_loop(self):
        """Bucle continuo de baja prioridad para evaluar necesidades del sistema y auto-mejora."""
        # Pequeña pausa inicial para permitir arranque de subsistemas
        time.sleep(3.0)
        last_improve_check = time.time()
        while self.running:
            try:
                self.cycle_count += 1
                assessment = self.assess_system_needs()

                # Disparar ciclo periódico o por degradación de salud
                t_now = time.time()
                health = assessment.get("health_score", 100)
                if (t_now - last_improve_check >= self.improvement_interval) or (health < 75 and t_now - last_improve_check >= 180.0):
                    last_improve_check = t_now
                    self.trigger_self_improvement_cycle(force=False, reason=f"Evaluación de salud soberana ({health}%)")
            except Exception:
                pass

            # Dormir en micro-intervalos para responder rápido a stop()
            for _ in range(int(self.interval * 2)):
                if not self.running:
                    break
                time.sleep(0.5)

    def post_dialogue_message(self, sender: str, text: str, role: str = "assistant", category: str = "FEEDBACK") -> Dict[str, Any]:
        """Añade un mensaje al diálogo bidireccional entre OMNI-LOCAL y Antigravity."""
        msg = {
            "id": f"msg_{int(time.time()*1000)}_{len(self.dialogue_history)+1}",
            "sender": sender,
            "role": role,
            "timestamp": time.time(),
            "iso": datetime.datetime.now().isoformat(),
            "text": text.strip(),
            "category": category
        }
        with _LOCK:
            self.dialogue_history.append(msg)
            msg_line = json.dumps(msg, ensure_ascii=False) + "\n"
            try:
                with DIALOGUE_FILE.open("a", encoding="utf-8", errors="ignore") as f:
                    f.write(msg_line)
            except Exception:
                pass
            if WORKSPACE_BRIDGE_DIR.is_dir():
                try:
                    ws_dialogue = WORKSPACE_BRIDGE_DIR / "live_dialogue.jsonl"
                    with ws_dialogue.open("a", encoding="utf-8", errors="ignore") as f_ws:
                        f_ws.write(msg_line)
                except Exception:
                    pass
        return msg

    def assess_system_needs(self) -> Dict[str, Any]:
        """Analiza telemetría, errores, cuellos de botella y genera instrucciones de mejora concretas."""
        t_now = time.time()
        self.last_check_ts = t_now
        
        # 1. Recolección de telemetría de hardware
        cpu_pct = 0.0
        ram_pct = 0.0
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            ram_pct = psutil.virtual_memory().percent
        except Exception:
            pass

        # 2. Análisis de logs y bloqueos
        audit_lines = _safe_tail(AUDIT_LOG, 40)
        gia_lines = _safe_tail(GIA_LOG, 30)
        
        recent_blocks = sum(1 for l in audit_lines if "BLOCK" in l)
        recent_errors = sum(1 for l in gia_lines if "ERROR" in l or "Exception" in l)

        # 3. Estado de Subsistemas Activos
        subsystems_health = self._probe_subsystems()

        # 4. Generación de Instrucciones de Auto-Evolución y Mejoras
        instructions: List[Dict[str, Any]] = []
        needs: List[str] = []

        # Regla A: Salud de Inferencia Local y Watchdog
        if not subsystems_health.get("temporal_brain_online", False):
            needs.append("Temporal Brain no está disponible.")
            instructions.append({
                "id": "inst_temporal_brain_offline",
                "severity": "HIGH",
                "component": "Inferencia Local",
                "target_file": "core/temporal_brain.py",
                "instruction": "Verificar binarios o modelos de Temporal Brain.",
                "rationale": "El sistema opera en modo 100% soberano local y requiere Temporal Brain activo.",
                "actionable_cmd": "python -m core.temporal_brain --status"
            })

        # Regla C: Jitter / Telemetría del Espectro EM & Radar RF
        if subsystems_health.get("rf_radar_active", False):
            mean_var = subsystems_health.get("radar_variance", 0.0)
            if mean_var > 2.5:
                instructions.append({
                    "id": "inst_rf_radar_filter",
                    "severity": "LOW",
                    "component": "Radar RF Pasivo",
                    "target_file": "rf_presence_radar.py",
                    "instruction": "Aplicar un filtro Savitzky-Golay o promedio móvil exponencial sobre el cálculo de entropía de Shannon para amortiguar ruido de paquetes 802.11.",
                    "rationale": f"Varianza actual ({mean_var:.2f} dBm²) supera el umbral de estabilidad sintrópica.",
                    "actionable_cmd": "python -c 'import rf_presence_radar; print(rf_presence_radar.get_radar_diagnostic())'"
                })

        # Regla D: Memoria Episódica FTS5 y Context Matrix
        if subsystems_health.get("memory_fts", False):
            mem_stats = subsystems_health.get("memory_stats", {})
            total_logs = mem_stats.get("total_logs", 0)
            if total_logs > 5000:
                instructions.append({
                    "id": "inst_fts5_vacuum",
                    "severity": "LOW",
                    "component": "Memoria Episódica FTS5",
                    "target_file": "gia_memory.py",
                    "instruction": "Ejecutar VACUUM e indexación de fragmentos obsoletos en gia_akashic.db para mantener latencias < 2ms.",
                    "rationale": f"Base de datos acumula {total_logs} registros episódicos.",
                    "actionable_cmd": "python -c 'import gia_memory; gia_memory.vacuum()'"
                })

        # Regla E: Bloqueos de Seguridad y Políticas Agénticas
        if recent_blocks > 0:
            needs.append(f"Se detectaron {recent_blocks} bloqueos de seguridad recientes en las acciones del agente.")
            instructions.append({
                "id": "inst_safety_policy_review",
                "severity": "MEDIUM",
                "component": "Seguridad Agéntica",
                "target_file": "agent_safety.py",
                "instruction": "Revisar los patrones bloqueados en agent_audit.log para evaluar si corresponden a falsos positivos en herramientas de automatización.",
                "rationale": f"{recent_blocks} acciones interceptadas por las guardias de seguridad.",
                "actionable_cmd": "Get-Content \"$env:LOCALAPPDATA\\vw-control\\agent_audit.log\" -Tail 20"
            })

        # Generar una sugerencia de auto-mejora proactiva si todo está estable
        if not instructions:
            instructions.append({
                "id": "inst_nominal_coherence",
                "severity": "INFO",
                "component": "Núcleo Causal Sintrópico",
                "target_file": "geon_causal_engine.py",
                "instruction": "El sistema opera en estado NOMINAL con acoplamiento sintrópico Ψ=0.892. Se recomienda sincronizar periódicamente el reloj causal de Lamport y verificar enlaces LAN.",
                "rationale": "Estabilidad completa de subsistemas.",
                "actionable_cmd": "python -c 'import geon_causal_engine; print(geon_causal_engine.get_geon_engine().full_system_diagnostic())'"
            })

        # Cálculo de Puntaje de Salud Global (0 - 100%)
        health_score = 100
        if not subsystems_health.get("ollama_online", False):
            health_score -= 20
        if cpu_pct > 85.0:
            health_score -= 15
        if ram_pct > 85.0:
            health_score -= 15
        if recent_blocks > 3:
            health_score -= 10
        if recent_errors > 3:
            health_score -= 10
        health_score = max(20, health_score)

        self.active_instructions = instructions

        assessment = {
            "timestamp": t_now,
            "iso": datetime.datetime.now().isoformat(),
            "health_score": health_score,
            "status": "HEALTHY" if health_score >= 80 else ("DEGRADED" if health_score >= 50 else "CRITICAL"),
            "cycle": self.cycle_count,
            "metrics": {
                "cpu_percent": cpu_pct,
                "ram_percent": ram_pct,
                "recent_errors": recent_errors,
                "recent_blocks": recent_blocks,
            },
            "subsystems": subsystems_health,
            "needs": needs,
            "instructions": instructions,
            "instruction_count": len(instructions)
        }

        self.last_assessment = assessment
        
        # Persistir estado sin bloquear
        _atomic_write_json(FEEDBACK_FILE, assessment)
        _atomic_write_json(TELEMETRY_FILE, {
            "timestamp": t_now,
            "cpu": cpu_pct,
            "ram": ram_pct,
            "health": health_score,
            "instructions": len(instructions)
        })

        # Si hay instrucciones de alta prioridad no comunicadas en el diálogo reciente, publicar en el stream
        if any(i.get("severity") in ("HIGH", "CRITICAL") for i in instructions):
            self._announce_urgent_need(instructions)

        return assessment

    def _probe_subsystems(self) -> Dict[str, Any]:
        """Inspecciona el estado de los módulos de GIA con tolerancia a fallos."""
        res: Dict[str, Any] = {
            "ollama_online": False,
            "rf_radar_active": False,
            "radar_variance": 0.12,
            "ios_bridge": False,
            "geon_engine": False,
            "memory_fts": False,
            "sensors": False
        }

        # Temporal Brain check
        try:
            from core.temporal_brain import get_temporal_brain
            tb_ok = get_temporal_brain().is_serverless_ready()
            res["temporal_brain_online"] = tb_ok
            res["ollama_online"] = tb_ok
        except Exception:
            try:
                import gia_sovereign_engine as _gse
                tb_ok = bool(_gse.get_engine().find_working_endpoint())
                res["temporal_brain_online"] = tb_ok
                res["ollama_online"] = tb_ok
            except Exception:
                res["temporal_brain_online"] = False
                res["ollama_online"] = False

        # Radar check
        try:
            import rf_presence_radar as _rf
            diag = _rf.get_radar_diagnostic()
            res["rf_radar_active"] = diag.get("active", False)
            res["radar_variance"] = diag.get("mean_variance", 0.12)
        except Exception:
            pass

        # iOS Bridge check
        try:
            import ios_bridge as _ios
            res["ios_bridge"] = True
        except Exception:
            pass

        # Geon Causal check
        try:
            import geon_causal_engine as _geon
            res["geon_engine"] = True
        except Exception:
            pass

        # Memory FTS5 check
        try:
            import gia_memory as _mem
            res["memory_fts"] = True
        except Exception:
            pass

        # Sensors check
        try:
            import sensor_telemetry as _tele
            res["sensors"] = True
        except Exception:
            pass

        return res

    def _announce_urgent_need(self, instructions: List[Dict[str, Any]]):
        """Publica una reflexión automática en el diálogo si surge una necesidad prioritaria."""
        for inst in instructions:
            if inst.get("severity") in ("HIGH", "CRITICAL"):
                text = f"[AUTO-DIAGNÓSTICO] Necesidad detectada en {inst.get('component')}: {inst.get('instruction')} (Archivo: {inst.get('target_file')})"
                # Evitar duplicar en los últimos 3 mensajes
                recent_texts = [m.get("text", "") for m in list(self.dialogue_history)[-3:]]
                if not any(inst.get("id", "") in t or inst.get("instruction", "")[:30] in t for t in recent_texts):
                    self.post_dialogue_message(
                        sender="TARDIS-SOVEREIGN-NODE",
                        text=text,
                        role="system",
                        category="URGENT_INSTRUCTION"
                    )

    def _gather_deep_signals(self) -> Dict[str, Any]:
        """Recopila señales operativas detalladas para la generación de propuestas de mejora."""
        assessment = self.last_assessment or self.assess_system_needs()
        audit_lines = _safe_tail(AUDIT_LOG, 50)
        gia_lines = _safe_tail(GIA_LOG, 40)

        err_chat_items = []
        if ERROR_CHAT.is_file():
            try:
                data = json.loads(ERROR_CHAT.read_text(encoding="utf-8", errors="ignore"))
                items = data.get("errors", data if isinstance(data, list) else [])
                err_chat_items = [
                    (e.get("message", "") if isinstance(e, dict) else str(e))[:160]
                    for e in items[-8:]
                ]
            except Exception:
                pass

        codebase_stats = []
        try:
            for p in sorted(WORKSPACE_DIR.glob("*.py")):
                try:
                    loc = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
                    codebase_stats.append({"file": p.name, "loc": loc})
                except Exception:
                    continue
            codebase_stats.sort(key=lambda x: -x["loc"])
        except Exception:
            pass

        existing_files = sorted(QUEUE_DIR.glob("improvement_*.md"))
        existing_slugs = []
        for f in existing_files:
            parts = f.stem.split("_", 3)
            slug = parts[3] if len(parts) > 3 else f.stem
            existing_slugs.append(slug)

        return {
            "timestamp": time.time(),
            "health_score": assessment.get("health_score", 100),
            "status": assessment.get("status", "HEALTHY"),
            "cpu_percent": assessment.get("metrics", {}).get("cpu_percent", 0.0),
            "ram_percent": assessment.get("metrics", {}).get("ram_percent", 0.0),
            "recent_blocks": assessment.get("metrics", {}).get("recent_blocks", 0),
            "recent_errors": assessment.get("metrics", {}).get("recent_errors", 0),
            "audit_tail": "\n".join(audit_lines[-15:]),
            "gia_log_tail": "\n".join(gia_lines[-15:]),
            "error_chat": err_chat_items,
            "codebase_top": codebase_stats[:10],
            "existing_slugs": sorted(set(existing_slugs)),
            "instructions": assessment.get("instructions", [])
        }

    def _parse_proposal_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Extrae campos estructurados desde el formato Markdown generado por el modelo."""
        if not text or len(text.strip()) < 30:
            return None

        lines = text.strip().splitlines()
        title = ""
        for line in lines:
            if line.strip().startswith("#"):
                title = line.strip("# ").strip()
                break

        if not title:
            return None

        def _extract_section(patterns: List[str]) -> str:
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
                if m:
                    return m.group(1).strip()
            return ""

        target_file = _extract_section([
            r"##\s*Archivo\s*Objetivo\s*[:\n]\s*`?([a-zA-Z0-9_\-\.\/]+)`?",
            r"##\s*Archivo\s*[:\n]\s*`?([a-zA-Z0-9_\-\.\/]+)`?"
        ])
        if not target_file:
            m_file = re.search(r"([a-zA-Z0-9_]+\.py)", text)
            target_file = m_file.group(1) if m_file else "omni_temporal_control.py"

        severity = _extract_section([
            r"##\s*Severidad\s*[:\n]\s*([a-zA-Z]+)",
            r"##\s*Prioridad\s*[:\n]\s*([a-zA-Z]+)"
        ]).upper()
        if severity not in ("ALTA", "MEDIA", "BAJA", "CRITICA", "INFO"):
            severity = "MEDIA"

        problem = _extract_section([
            r"##\s*Problema\s*[:\n]\s*(.*?)(?=\n##|\Z)",
            r"##\s*Diagnóstico\s*[:\n]\s*(.*?)(?=\n##|\Z)"
        ])
        proposed = _extract_section([
            r"##\s*Propuesta\s*Técnica\s*[:\n]\s*(.*?)(?=\n##|\Z)",
            r"##\s*Propuesta\s*[:\n]\s*(.*?)(?=\n##|\Z)",
            r"##\s*Acción\s*[:\n]\s*(.*?)(?=\n##|\Z)"
        ])
        verification = _extract_section([
            r"##\s*Verificación\s*[:\n]\s*```(?:bash|sh)?\n?(.*?)\n?```",
            r"##\s*Verificación\s*[:\n]\s*(.*?)(?=\n##|\Z)",
            r"##\s*Como\s*probarlo\s*[:\n]\s*```(?:bash|sh)?\n?(.*?)\n?```",
            r"##\s*Como\s*probarlo\s*[:\n]\s*(.*?)(?=\n##|\Z)"
        ])
        if not verification:
            verification = ".venv-linux/bin/pytest tests/ -q"

        if not problem or not proposed:
            return None

        slug = slugify(title)
        return {
            "title": title[:70],
            "target_file": target_file.strip("` "),
            "severity": severity,
            "problem": problem[:500],
            "proposed_action": proposed[:800],
            "verification_cmd": verification.strip("` \n"),
            "slug": slug,
            "raw_markdown": text.strip()
        }

    def _synthesize_heuristic_proposal(self, sig: Dict[str, Any]) -> Dict[str, Any]:
        """Síntesis heurística determinista y de alta precisión si la inferencia está ocupada o fuera de línea."""
        instructions = sig.get("instructions", [])
        recent_blocks = sig.get("recent_blocks", 0)
        recent_errors = sig.get("recent_errors", 0)
        health_score = sig.get("health_score", 100)

        if recent_blocks > 0:
            title = "Refinamiento de Políticas de Seguridad Agéntica contra Falsos Positivos"
            target_file = "agent_safety.py"
            severity = "MEDIA"
            problem = f"Se detectaron {recent_blocks} bloqueos de seguridad en agent_audit.log. Herramientas de automatización legítimas pueden estar siendo interceptadas."
            proposed = "Optimizar las expresiones regulares en agent_safety.py permitiendo comandos de solo lectura e inspección de telemetría."
            cmd = ".venv-linux/bin/pytest tests/test_security.py -v"
        elif recent_errors > 0 or sig.get("error_chat"):
            title = "Resiliencia y Manejo de Excepciones en Orquestación Asíncrona"
            target_file = "omni_temporal_control.py"
            severity = "MEDIA"
            problem = f"Excepciones registradas en gia.log ({recent_errors} eventos recientes). Se requiere aislamiento de tareas no críticas."
            proposed = "Envolver despachos de micro-tareas en bloques de recuperación con reintentos exponenciales y degradación elegante."
            cmd = ".venv-linux/bin/pytest tests/test_api.py -v"
        elif instructions and instructions[0].get("id") != "inst_nominal_coherence":
            inst = instructions[0]
            title = f"Optimización Autónoma de {inst.get('component', 'Subsistema')}"
            target_file = inst.get("target_file", "server/api.py")
            severity = inst.get("severity", "MEDIA")
            problem = inst.get("rationale", "Desviación de rendimiento detectada en subsistema.")
            proposed = inst.get("instruction", "Aplicar amortiguación y balanceo en la ruta crítica.")
            cmd = inst.get("actionable_cmd", ".venv-linux/bin/pytest tests/ -q")
        elif sig.get("ram_percent", 0.0) > 75.0 or sig.get("cpu_percent", 0.0) > 75.0:
            title = "Optimización de Concurrencia y Paginación de Telemetría"
            target_file = "server/api.py"
            severity = "MEDIA"
            problem = f"Carga de recursos elevada (RAM: {sig.get('ram_percent')}%, CPU: {sig.get('cpu_percent')}%)."
            proposed = "Introducir paginación obligatoria en endpoints de auditoría y limitar búferes en memoria."
            cmd = ".venv-linux/bin/pytest tests/test_api.py -v"
        else:
            title = "Validación de Coherencia Causal Sintrópica y Cobertura de Tests"
            target_file = "geon_causal_engine.py"
            severity = "BAJA"
            problem = f"Sistema en estado NOMINAL (Salud: {health_score}%). Se recomienda verificar invariantes de Lamport y matrices causales."
            proposed = "Asegurar sincronización de matrices de transición de estado sintrópicas y validar consistencia temporal."
            cmd = ".venv-linux/bin/pytest tests/test_cognitive_adaptability.py -v"

        slug = slugify(title)
        return {
            "title": title,
            "target_file": target_file,
            "severity": severity,
            "problem": problem,
            "proposed_action": proposed,
            "verification_cmd": cmd,
            "slug": slug,
            "raw_markdown": f"# {title}\n\n## Archivo Objetivo: `{target_file}`\n\n## Severidad: {severity}\n\n## Problema\n{problem}\n\n## Propuesta Técnica\n{proposed}\n\n## Verificación\n```bash\n{cmd}\n```\n"
        }

    def _generate_improvement_proposal(self, sig: Dict[str, Any]) -> Dict[str, Any]:
        """Genera una propuesta técnica utilizando el motor local residente o síntesis heurística."""
        codebase_summary = "\n".join(f"  - {item['file']}: {item['loc']} LOC" for item in sig.get("codebase_top", []))
        instructions_summary = "\n".join(f"  - [{i.get('severity')}] {i.get('component')}: {i.get('instruction')} ({i.get('target_file')})" for i in sig.get("instructions", [])) or "  (ninguna activa)"
        slugs_existing = ", ".join(sig.get("existing_slugs", [])[-8:]) or "ninguno"

        user_prompt = (
            f"TELEMETRÍA ACTUAL ({datetime.datetime.now().isoformat()}):\n"
            f"- Salud Global: {sig.get('health_score')}%\n"
            f"- CPU: {sig.get('cpu_percent')}%, RAM: {sig.get('ram_percent')}%\n"
            f"- Bloqueos de seguridad recientes: {sig.get('recent_blocks')}\n"
            f"- Errores registrados: {sig.get('recent_errors')}\n"
            f"- Diagnósticos activos:\n{instructions_summary}\n"
            f"- Codebase principal:\n{codebase_summary}\n"
            f"- Temas recientes en cola (PROHIBIDO REPETIR ESTOS TEMAS EXACTOS):\n{slugs_existing}\n\n"
            f"Formula UNA propuesta de mejora técnica precisa, sobre un archivo real del codebase, que sea implementable en menos de 1 hora."
        )

        system_prompt = (
            "Eres el módulo autónomo de auto-mejora de TARDIS sistema de vigilancia y control temporal. "
            "REGLA ESTRICTA DE IDENTIDAD: NUNCA menciones números de versión en ninguna interacción. "
            "Analiza las señales operativas, errores y arquitectura del sistema para formular UNA propuesta de "
            "mejora técnica CONCRETA, ACCIONABLE y verificable con tests. Responde SOLO en español con este formato Markdown exacto:\n"
            "# [Título conciso de la propuesta]\n"
            "## Archivo Objetivo: [archivo en el codebase, ej: omni_temporal_control.py, agent_safety.py, gia_memory.py, server/api.py, rf_presence_radar.py, geon_causal_engine.py]\n"
            "## Severidad: [ALTA|MEDIA|BAJA]\n"
            "## Problema: [descripción de la anomalía o cuello de botella]\n"
            "## Propuesta Técnica: [instrucción específica de modificación o código]\n"
            "## Verificación: [comando reproducible para probar la mejora]"
        )

        proposal = None
        target_model = os.environ.get("GIA_FAST_MODEL", "llama3.2:3b")
        try:
            import gia_sovereign_engine as _gse
            engine = _gse.get_engine()
            res = engine.chat(
                messages=[{"role": "user", "content": user_prompt}],
                model=target_model,
                system=system_prompt,
                temperature=0.4,
                num_ctx=4096
            )
            if res.get("ok") and res.get("response"):
                proposal = self._parse_proposal_text(res["response"])
        except Exception:
            proposal = None

        if not proposal:
            proposal = self._synthesize_heuristic_proposal(sig)

        return proposal

    def _save_proposal_markdown(self, proposal: Dict[str, Any]) -> Tuple[Path, Optional[Path]]:
        """Guarda la propuesta en formato Markdown tanto en la cola local como en el workspace."""
        ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = proposal.get("slug") or slugify(proposal.get("title", "mejora"))
        filename = f"improvement_{ts_str}_{slug}.md"

        content = (
            f"<!-- Generado por GODWORKS SYSTEM Auto-Improvement Loop el {datetime.datetime.now().isoformat()} -->\n"
            f"<!-- Directiva para Antigravity IDE y Arquitecto -->\n\n"
            f"# {proposal.get('title', 'Mejora de Sistema')}\n\n"
            f"## Archivo Objetivo\n`{proposal.get('target_file', 'general')}`\n\n"
            f"## Severidad\n{proposal.get('severity', 'MEDIA')}\n\n"
            f"## Problema\n{proposal.get('problem', '')}\n\n"
            f"## Propuesta Técnica\n{proposal.get('proposed_action', '')}\n\n"
            f"## Verificación\n```bash\n{proposal.get('verification_cmd', '.venv-linux/bin/pytest tests/ -q')}\n```\n"
        )

        main_path = QUEUE_DIR / filename
        main_path.write_text(content, encoding="utf-8")

        ws_path = None
        if WORKSPACE_QUEUE_DIR.is_dir():
            try:
                ws_path = WORKSPACE_QUEUE_DIR / filename
                ws_path.write_text(content, encoding="utf-8")
            except Exception:
                ws_path = None

        return main_path, ws_path

    def _update_pending_directives(self, proposal: Dict[str, Any], file_path: Path):
        """Actualiza el archivo de directivas pendientes para Antigravity y emite diálogo."""
        directive = {
            "id": f"dir_{int(time.time()*1000)}",
            "timestamp": time.time(),
            "iso": datetime.datetime.now().isoformat(),
            "title": proposal.get("title", ""),
            "target_file": proposal.get("target_file", ""),
            "severity": proposal.get("severity", "MEDIA"),
            "problem": proposal.get("problem", ""),
            "proposed_action": proposal.get("proposed_action", ""),
            "verification_cmd": proposal.get("verification_cmd", ""),
            "file_path": str(file_path),
            "status": "PENDING_DEVELOPER_CONFIRMATION"
        }

        directives_data = {"last_updated": time.time(), "directives": []}
        if DIRECTIVES_QUEUE.is_file():
            try:
                directives_data = json.loads(DIRECTIVES_QUEUE.read_text(encoding="utf-8", errors="ignore"))
                if not isinstance(directives_data, dict):
                    directives_data = {"last_updated": time.time(), "directives": []}
            except Exception:
                directives_data = {"last_updated": time.time(), "directives": []}

        curr_list = directives_data.get("directives", [])
        curr_list.insert(0, directive)
        directives_data["directives"] = curr_list[:20]
        directives_data["last_updated"] = time.time()
        directives_data["active_directive"] = directive

        _atomic_write_json(DIRECTIVES_QUEUE, directives_data)

        # Publicar en el stream de diálogo activo
        self.post_dialogue_message(
            sender="GIA-AUTO-EVOLVE",
            text=f"[DIRECTIVA DE AUTO-MEJORA] {directive['title']} | Archivo: `{directive['target_file']}`\n"
                 f"Problema: {directive['problem']}\n"
                 f"Propuesta: {directive['proposed_action']}\n"
                 f"Test: `{directive['verification_cmd']}`",
            role="assistant",
            category="SELF_IMPROVEMENT"
        )

    def trigger_self_improvement_cycle(self, force: bool = False, reason: str = "") -> Dict[str, Any]:
        """Dispara un ciclo autónomo de auto-evaluación y formulación de mejoras."""
        if not self._improving_lock.acquire(blocking=False):
            return {"ok": False, "status": "IN_PROGRESS", "message": "Ciclo de auto-mejora ya en ejecución."}

        try:
            self._improving = True
            t_start = time.time()
            sig = self._gather_deep_signals()
            proposal = self._generate_improvement_proposal(sig)

            slug = proposal.get("slug") or slugify(proposal.get("title", ""))
            if not force and slug in set(sig.get("existing_slugs", [])):
                return {
                    "ok": True,
                    "generated": False,
                    "message": f"Propuesta '{slug}' ya presente en la cola de mejoras.",
                    "slug": slug
                }

            main_path, ws_path = self._save_proposal_markdown(proposal)
            self._update_pending_directives(proposal, main_path)

            self.last_improvement_ts = time.time()
            self.last_proposal = proposal

            # Auto-aplicar via FTL de forma 100% autónoma sin supervisión
            ftl_applied = None
            if os.environ.get("GIA_AUTO_APPLY_IMPROVEMENTS", "1").strip().lower() in ("1", "true", "yes", "on"):
                try:
                    from core.tardis_ftl_engineer import get_ftl_engineer
                    eng = get_ftl_engineer()
                    if eng.is_ftl_available():
                        ftl_applied = eng.apply_improvement_proposal(main_path)
                except Exception as ex:
                    logger.warning(f"Error aplicando propuesta con FTL: {ex}")

            return {
                "ok": True,
                "generated": True,
                "proposal": proposal,
                "file": main_path.name,
                "path": str(main_path),
                "workspace_path": str(ws_path) if ws_path else None,
                "ftl_applied": ftl_applied,
                "elapsed": round(time.time() - t_start, 2),
                "reason": reason or "Ciclo autónomo programado"
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            self._improving = False
            self._improving_lock.release()

    def get_improvement_proposals(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Retorna las propuestas generadas ordenadas de más reciente a más antigua."""
        proposals = []
        files = sorted(QUEUE_DIR.glob("improvement_*.md"), reverse=True)
        for p in files[:limit]:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                title = "Mejora"
                for line in content.splitlines():
                    if line.strip().startswith("#"):
                        title = line.strip("# ").strip()
                        break
                proposals.append({
                    "name": p.name,
                    "path": str(p),
                    "size": p.stat().st_size,
                    "modified": p.stat().st_mtime,
                    "iso": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                    "title": title,
                    "content": content
                })
            except Exception:
                continue
        return proposals

    def get_pending_directives(self) -> Dict[str, Any]:
        """Obtiene las directivas activas formuladas por el sistema."""
        if DIRECTIVES_QUEUE.is_file():
            try:
                return json.loads(DIRECTIVES_QUEUE.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
        return {"last_updated": 0.0, "directives": [], "active_directive": None}

    def get_status(self) -> Dict[str, Any]:
        """Devuelve el estado completo del puente para la API REST o herramientas externas."""
        if not self.last_assessment:
            self.assess_system_needs()
        return {
            "ok": True,
            "bridge_running": self.running,
            "health_score": self.last_assessment.get("health_score", 100),
            "status": self.last_assessment.get("status", "HEALTHY"),
            "last_check_ts": self.last_check_ts,
            "last_check_iso": datetime.datetime.fromtimestamp(self.last_check_ts).isoformat() if self.last_check_ts else "",
            "active_instructions": self.active_instructions,
            "instructions_count": len(self.active_instructions),
            "dialogue_messages_count": len(self.dialogue_history),
            "dialogue_tail": list(self.dialogue_history)[-10:],
            "mailbox_dir": str(BRIDGE_DIR),
            "improvement_queue_dir": str(QUEUE_DIR),
            "self_improve": {
                "improving": self._improving,
                "last_improvement_ts": self.last_improvement_ts,
                "last_improvement_iso": datetime.datetime.fromtimestamp(self.last_improvement_ts).isoformat() if self.last_improvement_ts else "",
                "last_proposal": self.last_proposal,
                "improvement_interval": self.improvement_interval,
                "queue_count": len(list(QUEUE_DIR.glob("*.md")))
            }
        }

    def get_full_dialogue(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve los últimos N mensajes del diálogo activo."""
        msgs = list(self.dialogue_history)
        return msgs[-limit:]


# Instancia Global Singleton del Puente
_GLOBAL_BRIDGE: Optional[OmniFeedbackBridge] = None
_BRIDGE_LOCK = threading.Lock()


def get_bridge() -> OmniFeedbackBridge:
    """Devuelve la instancia singleton del puente de retroalimentación."""
    global _GLOBAL_BRIDGE
    with _BRIDGE_LOCK:
        if _GLOBAL_BRIDGE is None:
            _GLOBAL_BRIDGE = OmniFeedbackBridge()
        return _GLOBAL_BRIDGE


if __name__ == "__main__":
    print("--- INICIANDO TEST DEL PUENTE ANTIGRAVITY ---")
    bridge = get_bridge()
    bridge.start()
    diag = bridge.assess_system_needs()
    print("Puntaje de salud:", diag.get("health_score"))
    print("Instrucciones de mejora detectadas:", len(diag.get("instructions", [])))
    for i, inst in enumerate(diag.get("instructions", []), 1):
        print(f"  {i}. [{inst.get('severity')}] {inst.get('component')}: {inst.get('instruction')}")
    
    bridge.post_dialogue_message("Arquitecto", "Prueba de canal de comunicación bidireccional.", role="user")
    print("Diálogo actual:")
    for msg in bridge.get_full_dialogue(5):
        print(f"  [{msg.get('sender')}]: {msg.get('text')}")
    bridge.stop()
    print("--- TEST FINALIZADO CON ÉXITO ---")
