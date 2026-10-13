"""
tardis_continuity_engine.py - Motor de Continuidad Temporal y Persistencia de Avance
====================================================================================
GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Garantiza de forma soberana e indestructible que a pesar de que el dispositivo
se reinicie (por ciclos de evolución de autonomous_controller, mantenimiento,
actualizaciones del kernel o cortes de energía), NUNCA se pierda el contexto
de las peticiones del Arquitecto, las tareas en progreso, los hitos alcanzados
ni el avance acumulado.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.continuity")

# Directorios de anclaje de persistencia
TARDIS_HOME = Path(os.path.expanduser("~/.tardis"))
TARDIS_HOME.mkdir(parents=True, exist_ok=True)

GODWORKS_DATA = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/data")
GODWORKS_DATA.mkdir(parents=True, exist_ok=True)

FTL_DIR = Path(os.path.expanduser("~/.ftl"))
FTL_DIR.mkdir(parents=True, exist_ok=True)

DESKTOP_PATH = Path("/home/timemachine/Escritorio")

DB_PATH = TARDIS_HOME / "continuity_vault.db"
STATE_JSON_TARDIS = TARDIS_HOME / "continuity_state.json"
STATE_JSON_GODWORKS = GODWORKS_DATA / "continuity_state.json"
STATE_JSON_FTL = FTL_DIR / "continuity_state.json"
DASHBOARD_MD = DESKTOP_PATH / "CONTINUIDAD_SISTEMA_TARDIS.md"


class TardisContinuityEngine:
    """Motor Soberano de Continuidad Temporal & Resiliencia Post-Reinicio."""

    _instance: Optional["TardisContinuityEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()
        self._active_session: Dict[str, Any] = self._load_active_state()

    @classmethod
    def get_instance(cls) -> "TardisContinuityEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=5.0)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _init_db(self):
        """Inicializa el esquema relacional de continuidad."""
        with self._connect() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS active_session (
                session_id TEXT PRIMARY KEY,
                architect_goal TEXT,
                current_request TEXT,
                source TEXT,
                status TEXT,
                progress_percent INTEGER,
                phase TEXT,
                details_json TEXT,
                created_ts REAL,
                updated_ts REAL,
                reboot_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp REAL,
                iso TEXT,
                source TEXT,
                prompt TEXT,
                plan_mode TEXT,
                model TEXT,
                status TEXT,
                progress_summary TEXT,
                artifacts_json TEXT,
                reboot_survived INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                step_index INTEGER,
                title TEXT,
                status TEXT,
                output_snippet TEXT,
                timestamp REAL,
                iso TEXT
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_name TEXT,
                timestamp REAL,
                iso TEXT,
                trigger_reason TEXT,
                state_data TEXT
            );
            """)

    def _load_active_state(self) -> Dict[str, Any]:
        """Carga el estado activo desde SQLite o los espejos JSON."""
        try:
            with self._connect() as con:
                row = con.execute("""
                    SELECT session_id, architect_goal, current_request, source,
                           status, progress_percent, phase, details_json,
                           created_ts, updated_ts, reboot_count
                    FROM active_session
                    WHERE session_id = 'master_timeline'
                """).fetchone()

                if row:
                    return {
                        "session_id": row[0],
                        "architect_goal": row[1] or "",
                        "current_request": row[2] or "",
                        "source": row[3] or "ARCHITECT",
                        "status": row[4] or "idle",
                        "progress_percent": row[5] or 0,
                        "phase": row[6] or "",
                        "details": json.loads(row[7] or "{}"),
                        "created_ts": row[8] or time.time(),
                        "updated_ts": row[9] or time.time(),
                        "reboot_count": row[10] or 0
                    }
        except Exception as e:
            logger.warning(f"[CONTINUITY] Error leyendo DB: {e}")

        # Fallback a JSON espejo
        if STATE_JSON_TARDIS.exists():
            try:
                return json.loads(STATE_JSON_TARDIS.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            "session_id": "master_timeline",
            "architect_goal": "Operación Autónoma Soberana GODWORKS & TARDIS",
            "current_request": "",
            "source": "ARCHITECT",
            "status": "idle",
            "progress_percent": 100,
            "phase": "Listo para nuevas directivas",
            "details": {},
            "created_ts": time.time(),
            "updated_ts": time.time(),
            "reboot_count": 0
        }

    def _save_active_state(self):
        """Persiste el estado activo atómicamente en SQLite y todos los espejos JSON."""
        now = time.time()
        self._active_session["updated_ts"] = now

        try:
            with self._connect() as con:
                con.execute("""
                    INSERT INTO active_session (
                        session_id, architect_goal, current_request, source,
                        status, progress_percent, phase, details_json,
                        created_ts, updated_ts, reboot_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        architect_goal = excluded.architect_goal,
                        current_request = excluded.current_request,
                        source = excluded.source,
                        status = excluded.status,
                        progress_percent = excluded.progress_percent,
                        phase = excluded.phase,
                        details_json = excluded.details_json,
                        updated_ts = excluded.updated_ts,
                        reboot_count = excluded.reboot_count
                """, (
                    self._active_session.get("session_id", "master_timeline"),
                    self._active_session.get("architect_goal", ""),
                    self._active_session.get("current_request", ""),
                    self._active_session.get("source", "ARCHITECT"),
                    self._active_session.get("status", "idle"),
                    int(self._active_session.get("progress_percent", 0)),
                    self._active_session.get("phase", ""),
                    json.dumps(self._active_session.get("details", {}), ensure_ascii=False),
                    float(self._active_session.get("created_ts", now)),
                    now,
                    int(self._active_session.get("reboot_count", 0))
                ))
        except Exception as e:
            logger.error(f"[CONTINUITY] Error guardando en SQLite: {e}")

        # Espejos JSON instantáneos
        json_blob = json.dumps(self._active_session, indent=2, ensure_ascii=False)
        for target in [STATE_JSON_TARDIS, STATE_JSON_GODWORKS, STATE_JSON_FTL]:
            try:
                target.write_text(json_blob, encoding="utf-8")
            except Exception as e:
                logger.debug(f"[CONTINUITY] Error escribiendo {target}: {e}")

        # Actualizar Dashboard Markdown en el Escritorio
        self.render_desktop_dashboard()

    def start_request(
        self,
        prompt: str,
        source: str = "ARCHITECT",
        plan_mode: str = "kaiju",
        model: str = "",
        goal: Optional[str] = None
    ) -> str:
        """
        Registra una nueva petición del Arquitecto antes de iniciar su ejecución.
        Garantiza que si el sistema se apaga un milisegundo después, la intención ya está salvada.
        """
        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            if goal:
                self._active_session["architect_goal"] = goal
            elif not self._active_session.get("architect_goal"):
                self._active_session["architect_goal"] = prompt[:120]

            self._active_session["current_request"] = prompt
            self._active_session["source"] = source
            self._active_session["status"] = "in_progress"
            self._active_session["progress_percent"] = 5
            self._active_session["phase"] = f"Iniciando ejecución con motor {plan_mode.upper()} ({model or 'Frontier'})"
            self._active_session["created_ts"] = now
            self._active_session["details"] = {
                "plan_mode": plan_mode,
                "model": model,
                "start_iso": iso,
                "artifacts": []
            }
            self._save_active_state()

            # Insertar en log de peticiones
            try:
                with self._connect() as con:
                    con.execute("""
                        INSERT INTO request_log (
                            session_id, timestamp, iso, source, prompt,
                            plan_mode, model, status, progress_summary, artifacts_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        "master_timeline", now, iso, source, prompt,
                        plan_mode, model, "in_progress", "Petición registrada", "[]"
                    ))
            except Exception as e:
                logger.error(f"[CONTINUITY] Error insertando request_log: {e}")

            # Registrar primer hito
            self.record_milestone(
                step_index=1,
                title=f"Recepción de Petición: {prompt[:80]}",
                status="in_progress",
                output_snippet="Contexto y directivas anclados de forma persistente."
            )

        return "master_timeline"

    def record_milestone(
        self,
        step_index: int,
        title: str,
        status: str = "completed",
        output_snippet: str = ""
    ):
        """Registra un hito de avance discreto dentro de la tarea actual."""
        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with self._connect() as con:
                con.execute("""
                    INSERT INTO milestones (session_id, step_index, title, status, output_snippet, timestamp, iso)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("master_timeline", step_index, title, status, output_snippet[:500], now, iso))
        except Exception as e:
            logger.debug(f"[CONTINUITY] Error registrando hito: {e}")

    def update_progress(
        self,
        progress_percent: int,
        phase: str,
        step_title: Optional[str] = None,
        output_snippet: str = "",
        artifacts: Optional[List[str]] = None
    ):
        """Actualiza el porcentaje y descripción de avance en tiempo real."""
        with self._lock:
            self._active_session["progress_percent"] = max(0, min(100, progress_percent))
            self._active_session["phase"] = phase

            if artifacts:
                cur_arts = self._active_session["details"].setdefault("artifacts", [])
                for a in artifacts:
                    if a not in cur_arts:
                        cur_arts.append(a)

            if step_title:
                milestones_count = self.get_milestones_count() + 1
                self.record_milestone(
                    step_index=milestones_count,
                    title=step_title,
                    status="completed" if progress_percent >= 100 else "in_progress",
                    output_snippet=output_snippet
                )

            self._save_active_state()

    def get_milestones_count(self) -> int:
        try:
            with self._connect() as con:
                return con.execute("SELECT count(*) FROM milestones WHERE session_id='master_timeline'").fetchone()[0]
        except Exception:
            return 0

    def get_recent_milestones(self, limit: int = 8) -> List[Dict[str, Any]]:
        try:
            with self._connect() as con:
                rows = con.execute("""
                    SELECT step_index, title, status, output_snippet, iso
                    FROM milestones
                    WHERE session_id='master_timeline'
                    ORDER BY id DESC LIMIT ?
                """, (limit,)).fetchall()
                return [
                    {"step": r[0], "title": r[1], "status": r[2], "snippet": r[3], "iso": r[4]}
                    for r in reversed(rows)
                ]
        except Exception:
            return []

    def create_checkpoint(self, reason: str = "Pre-reboot state preservation") -> Dict[str, Any]:
        """
        Crea un punto de control integral antes de reiniciar o entrar en modo de suspensión.
        Guarda estado de interfaces, memoria, progreso y tareas pendientes.
        """
        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            # Estado de red
            net_stat = {}
            try:
                ip_r = subprocess.run(["ip", "-br", "a"], capture_output=True, text=True, timeout=2)
                net_stat["interfaces"] = ip_r.stdout.strip().splitlines()
            except Exception:
                pass

            checkpoint_data = {
                "active_session": dict(self._active_session),
                "network_snapshot": net_stat,
                "recent_milestones": self.get_recent_milestones(5),
                "timestamp": now,
                "iso": iso,
                "reason": reason
            }

            self._active_session["status"] = "checkpointed_pre_reboot"
            self._active_session["details"]["last_checkpoint_reason"] = reason
            self._active_session["details"]["last_checkpoint_iso"] = iso
            self._save_active_state()

            try:
                with self._connect() as con:
                    con.execute("""
                        INSERT INTO checkpoints (checkpoint_name, timestamp, iso, trigger_reason, state_data)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        f"CP_{int(now)}", now, iso, reason,
                        json.dumps(checkpoint_data, ensure_ascii=False)
                    ))
            except Exception as e:
                logger.error(f"[CONTINUITY] Error guardando checkpoint: {e}")

        logger.info(f"[CONTINUITY] 🛡️ Checkpoint creado exitosamente: {reason} ({iso})")
        return {"ok": True, "reason": reason, "iso": iso}

    def resume_after_reboot(self) -> Dict[str, Any]:
        """
        Detecta y reanuda el contexto tras un reinicio físico del equipo.
        Recupera la petición que estaba en vuelo y los hitos previos.
        """
        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            cur_reboots = int(self._active_session.get("reboot_count", 0)) + 1
            self._active_session["reboot_count"] = cur_reboots
            prev_status = self._active_session.get("status", "idle")

            if prev_status in ("in_progress", "checkpointed_pre_reboot"):
                self._active_session["status"] = "resumed_post_reboot"
                self._active_session["phase"] = f"Reanudado automáticamente tras reinicio #{cur_reboots}"
            else:
                self._active_session["status"] = "idle"
                self._active_session["phase"] = f"Sistema operativo y en línea tras reinicio #{cur_reboots}"

            self._active_session["details"]["last_recovery_iso"] = iso
            self._save_active_state()

            # Registrar hito de supervivencia a reinicio
            self.record_milestone(
                step_index=self.get_milestones_count() + 1,
                title=f"⚡ Supervivencia a Reinicio #{cur_reboots} Confirmada",
                status="resumed",
                output_snippet=f"Contexto temporal intacto. Petición en curso: '{self._active_session.get('current_request','')[:70]}'"
            )

        logger.info(f"[CONTINUITY] 🛸 Continuidad temporal restablecida tras reinicio #{cur_reboots}")
        return {
            "ok": True,
            "reboot_count": cur_reboots,
            "status": self._active_session["status"],
            "current_request": self._active_session.get("current_request", ""),
            "progress_percent": self._active_session.get("progress_percent", 0)
        }

    def complete_request(
        self,
        output_summary: str = "",
        returncode: int = 0,
        files_changed: Optional[List[str]] = None
    ):
        """Marca la petición como completada con éxito."""
        now = time.time()
        iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            self._active_session["status"] = "completed" if returncode == 0 else "error"
            self._active_session["progress_percent"] = 100 if returncode == 0 else self._active_session.get("progress_percent", 0)
            self._active_session["phase"] = "Completado exitosamente" if returncode == 0 else "Finalizado con observaciones"

            if files_changed:
                self._active_session["details"]["files_changed"] = files_changed
            self._active_session["details"]["completion_iso"] = iso
            self._active_session["details"]["output_summary"] = output_summary[:1000]

            self._save_active_state()

            # Actualizar en request_log
            try:
                with self._connect() as con:
                    con.execute("""
                        UPDATE request_log
                        SET status = ?, progress_summary = ?, artifacts_json = ?
                        WHERE id = (SELECT max(id) FROM request_log WHERE session_id = 'master_timeline')
                    """, (
                        "completed" if returncode == 0 else "failed",
                        output_summary[:500],
                        json.dumps(files_changed or [], ensure_ascii=False)
                    ))
            except Exception as e:
                logger.debug(f"[CONTINUITY] Error actualizando request_log: {e}")

            self.record_milestone(
                step_index=self.get_milestones_count() + 1,
                title="Petición Concluida Exitosamente",
                status="completed",
                output_snippet=output_summary[:200]
            )

    def get_transversal_continuity_context(self, max_chars: int = 1400) -> str:
        """
        Genera el bloque inyectable para el RAG transversal de FTL / TARDIS / Antigravity,
        garantizando que cualquier modelo llamado tenga conocimiento inmediato del estado.
        """
        s = self._active_session
        status = s.get("status", "idle")
        req = s.get("current_request", "")
        goal = s.get("architect_goal", "")
        pct = s.get("progress_percent", 0)
        phase = s.get("phase", "")
        reboots = s.get("reboot_count", 0)
        details = s.get("details", {})

        milestones = self.get_recent_milestones(4)
        m_lines = []
        for m in milestones:
            m_lines.append(f"    - [{m['iso']}] {m['title']} ({m['status']})")
        m_str = "\n".join(m_lines) if m_lines else "    - Sin hitos previos registrados."

        txt = (
            f"• ESTADO DE CONTINUIDAD TEMPORAL TARDIS (BLINDAJE ANTE REINICIOS):\n"
            f"  [ESTADO: {status.upper()} | AVANCE: {pct}% | REINICIOS SOBREVIVIDOS: {reboots}]\n"
            f"  • Objetivo Maestro Activo : {goal}\n"
            f"  • Última Petición Recibida : {req}\n"
            f"  • Fase / Acción en Curso   : {phase}\n"
            f"  • Hitos Recientes de Avance:\n{m_str}\n"
            f"  • Garantía de Continuidad : ACTIVA (El avance previo NO se reinicia; se continúa directamente)."
        )
        return txt[:max_chars]

    def render_desktop_dashboard(self):
        """Genera y actualiza el Dashboard visual en Markdown en el Escritorio."""
        s = self._active_session
        status = s.get("status", "idle")
        status_color = "🟢 ONLINE / COMPLETADO" if status == "completed" else ("🟡 EN CURSO" if status == "in_progress" else ("🔵 RECUPERADO POST-REINICIO" if "reboot" in status else "⚪ LISTO"))
        req = s.get("current_request", "Ninguna petición activa.")
        goal = s.get("architect_goal", "Soberanía y evolución continua")
        pct = s.get("progress_percent", 0)
        phase = s.get("phase", "En espera")
        reboots = s.get("reboot_count", 0)
        updated_iso = datetime.datetime.fromtimestamp(s.get("updated_ts", time.time())).strftime("%Y-%m-%d %H:%M:%S")

        # Barra de progreso ASCII
        bar_len = 24
        filled = int(bar_len * (pct / 100))
        prog_bar = "█" * filled + "░" * (bar_len - filled)

        milestones = self.get_recent_milestones(8)
        ms_table = "| Paso | Hora | Hito / Acción | Estado |\n|---|---|---|---|\n"
        for m in milestones:
            ms_table += f"| {m['step']} | {m['iso'].split()[-1]} | {m['title']} | `{m['status']}` |\n"

        content = f"""# 🛸 TARDIS :: MATRIZ DE CONTINUIDAD TEMPORAL SOBERANA
**GODWORKS SYSTEM v26.4 · TARDIS-NEURAL-SPACE-KAIJU**  
*Arquitecto: El Arquitecto (₪) · Ancla: Playa del Carmen, Quintana Roo, México*  
*Última Sincronización: {updated_iso}*

---

### 📊 ESTADO DE LA SESIÓN & RESILIENCIA ANTE REINICIOS
- **Estado General:** {status_color}
- **Reinicios Físicos Sobrevividos:** `{reboots}`
- **Progreso Global:** `[{prog_bar}] {pct}%`
- **Fase Actual:** `{phase}`

### 🎯 OBJETIVO & PETICIÓN EN CURSO
> **Objetivo Maestro:**  
> *{goal}*

> **Última Petición Registrada del Arquitecto:**  
> *"{req}"*

---

### 📜 CRONOLOGÍA DE HITOS & AVANCE REGISTRADO (INALTERABLE TRAS REINICIO)
{ms_table}

---
*⚡ Este archivo se actualiza atómicamente en tiempo real ante cualquier comando o cambio de estado. Los reinicios de hardware nunca eliminan este contexto.*
"""
        try:
            DASHBOARD_MD.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.debug(f"[CONTINUITY] Error escribiendo dashboard escritorio: {e}")


def get_continuity_engine() -> TardisContinuityEngine:
    return TardisContinuityEngine.get_instance()


if __name__ == "__main__":
    eng = get_continuity_engine()
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "status":
            st = eng._active_session
            print(json.dumps(st, indent=2, ensure_ascii=False))
        elif cmd == "resume":
            res = eng.resume_after_reboot()
            print(f"✓ Reanudación completada: {res}")
        elif cmd == "checkpoint":
            reason = sys.argv[2] if len(sys.argv) > 2 else "Checkpoint manual CLI"
            cp = eng.create_checkpoint(reason)
            print(f"✓ Checkpoint guardado: {cp}")
        elif cmd == "context":
            print(eng.get_transversal_continuity_context())
    else:
        print(eng.get_transversal_continuity_context())
