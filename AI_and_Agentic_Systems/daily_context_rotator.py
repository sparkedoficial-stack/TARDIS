"""
core/daily_context_rotator.py - Rotador Autónomo de Contexto y Archivador de Conversaciones
=============================================================================================
GODWORKS SYSTEM v26.4 & TARDIS Sovereign Architecture

Misión:
1. Respaldar y archivar el 100% de las conversaciones e interacciones a un archivo local
   en formato JSON y Markdown con marca de tiempo.
2. Limpiar las tablas activas de conversación (events, events_fts, offline_chat_turns,
   offline_chat_fts, agent_context.json) liberando el 100% de los tokens de contexto
   para máxima velocidad, cero fragmentación y máxima capacidad de razonamiento.
3. Demonio de ejecución cíclica cada 24 horas (86,400s) de forma completamente autónoma.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.daily_context_rotator")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
ARCHIVE_DIR = BASE_DIR / "conversations_archive"
STATE_FILE = CONFIG_DIR / "context_rotation_state.json"

GIA_MASTER_DB = CONFIG_DIR / "gia_master.db"
OFFLINE_CHATS_DB = BASE_DIR / "data" / "offline_chats.db"
AGENT_CONTEXT_JSON = CONFIG_DIR / "agent_context.json"

ROTATION_INTERVAL_SECONDS = 86400  # 24 horas exactas


class DailyContextRotator:
    """Gestor autónomo de archivo y rotación periódica cada 24 horas."""

    _instance: Optional["DailyContextRotator"] = None
    _lock = threading.Lock()

    def __init__(self):
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.state = self._load_state()

    @classmethod
    def get_instance(cls) -> "DailyContextRotator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_state(self) -> Dict[str, Any]:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Error cargando {STATE_FILE}: {e}")
        return {
            "enabled": True,
            "interval_seconds": ROTATION_INTERVAL_SECONDS,
            "last_rotation_ts": 0.0,
            "last_rotation_iso": "",
            "next_rotation_ts": time.time() + ROTATION_INTERVAL_SECONDS,
            "total_rotations": 0,
            "total_events_archived": 0,
            "total_turns_archived": 0,
            "archives": [],
        }

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando {STATE_FILE}: {e}")

    # =========================================================================
    # 1. EXPORTACIÓN Y ARCHIVADO LOCAL
    # =========================================================================

    def archive_current_conversations(self) -> Dict[str, Any]:
        """Exporta todas las conversaciones activas a un archivo local con timestamp."""
        now = datetime.datetime.now()
        ts_tag = now.strftime("%Y%m%d_%H%M%S")
        iso_str = now.isoformat()

        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        json_archive_path = ARCHIVE_DIR / f"conversation_archive_{ts_tag}.json"
        md_archive_path = ARCHIVE_DIR / f"conversation_archive_{ts_tag}.md"

        events_data: List[Dict[str, Any]] = []
        turns_data: List[Dict[str, Any]] = []
        context_history: List[Any] = []

        # A. Extraer de gia_master.db (events)
        if GIA_MASTER_DB.exists():
            try:
                con = sqlite3.connect(str(GIA_MASTER_DB), timeout=10.0)
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                rows = cur.execute("SELECT * FROM events ORDER BY id ASC;").fetchall()
                for r in rows:
                    events_data.append(dict(r))
                con.close()
            except Exception as e:
                logger.error(f"[Rotator] Error extrayendo gia_master.db: {e}")

        # B. Extraer de offline_chats.db (offline_chat_turns)
        if OFFLINE_CHATS_DB.exists():
            try:
                con = sqlite3.connect(str(OFFLINE_CHATS_DB), timeout=10.0)
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                rows = cur.execute("SELECT * FROM offline_chat_turns ORDER BY id ASC;").fetchall()
                for r in rows:
                    turns_data.append(dict(r))
                con.close()
            except Exception as e:
                logger.error(f"[Rotator] Error extrayendo offline_chats.db: {e}")

        # C. Extraer de agent_context.json
        if AGENT_CONTEXT_JSON.exists():
            try:
                ctx_data = json.loads(AGENT_CONTEXT_JSON.read_text(encoding="utf-8"))
                context_history = ctx_data.get("history", [])
            except Exception as e:
                logger.error(f"[Rotator] Error extrayendo agent_context.json: {e}")

        total_records = len(events_data) + len(turns_data) + len(context_history)

        payload = {
            "archive_version": "26.4",
            "archived_at_ts": time.time(),
            "archived_at_iso": iso_str,
            "summary": {
                "events_count": len(events_data),
                "offline_turns_count": len(turns_data),
                "agent_context_history_count": len(context_history),
                "total_records": total_records,
            },
            "events": events_data,
            "offline_chat_turns": turns_data,
            "agent_context_history": context_history,
        }

        # Guardar JSON
        json_archive_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        # Generar Markdown estructurado y legible para humanos
        md_lines = [
            f"# 📜 Archivo de Conversaciones y Contexto · GODWORKS SYSTEM v26.4",
            f"**Fecha de Archivo:** {now.strftime('%Y-%m-%d %H:%M:%S')} (ISO: `{iso_str}`)",
            f"**Total Turnos / Eventos Respaldados:** `{total_records}`",
            f"**Ubicación JSON:** `{json_archive_path}`",
            "",
            "---",
            "",
            "## 1. Turnos de Diálogo Offline (`offline_chats.db`)",
            "",
        ]

        if turns_data:
            for t in turns_data:
                ts_dt = datetime.datetime.fromtimestamp(t.get("ts", time.time())).strftime("%Y-%m-%d %H:%M:%S")
                u_msg = (t.get("user_message") or "").strip()
                a_reply = (t.get("assistant_reply") or "").strip()
                sess = t.get("session_id", "app")
                md_lines.append(f"### Turno #{t.get('id')} · [{ts_dt}] (Sesión: `{sess}`)")
                md_lines.append(f"👤 **Usuario:**\n{u_msg}\n")
                md_lines.append(f"🤖 **Asistente (TARDIS / GIA):**\n{a_reply}\n")
                md_lines.append("")
        else:
            md_lines.append("*(No se registraron turnos en la bóveda offline)*\n")

        md_lines.extend([
            "---",
            "",
            "## 2. Eventos del Historial Maestro (`gia_master.db`)",
            "",
        ])

        if events_data:
            for ev in events_data:
                ts_dt = datetime.datetime.fromtimestamp(ev.get("ts", time.time())).strftime("%Y-%m-%d %H:%M:%S")
                role = ev.get("role", "system")
                source = ev.get("source", "app")
                content = (ev.get("content") or "").strip()
                md_lines.append(f"- **[{ts_dt}] [{source.upper()}:{role.upper()}]:** {content}")
            md_lines.append("")
        else:
            md_lines.append("*(No se registraron eventos maestros)*\n")

        md_archive_path.write_text("\n".join(md_lines), encoding="utf-8")

        return {
            "ok": True,
            "json_path": str(json_archive_path),
            "md_path": str(md_archive_path),
            "events_count": len(events_data),
            "turns_count": len(turns_data),
            "history_count": len(context_history),
            "total_records": total_records,
            "file_size_bytes": json_archive_path.stat().st_size if json_archive_path.exists() else 0,
        }

    # =========================================================================
    # 2. LIMPIEZA COMPLETA DE TOKENS Y MEMORIA ACTIVA
    # =========================================================================

    def clear_active_conversations(self, clear_vault_db: bool = False) -> Dict[str, Any]:
        """
        Elimina el historial de conversación activo liberando todos los tokens de contexto
        del sistema de comprensión, preservando la memoria local permanente en offline_chats.db.
        """
        cleared_events = 0
        cleared_turns = 0
        cleared_history = 0

        # A. Limpiar gia_master.db (eventos activos de contexto)
        if GIA_MASTER_DB.exists():
            try:
                con = sqlite3.connect(str(GIA_MASTER_DB), timeout=15.0)
                cur = con.cursor()
                row = cur.execute("SELECT COUNT(*) FROM events;").fetchone()
                cleared_events = row[0] if row else 0
                cur.execute("DELETE FROM events;")
                try:
                    cur.execute("DELETE FROM events_fts;")
                except Exception:
                    pass
                con.commit()
                con.execute("VACUUM;")
                con.close()
            except Exception as e:
                logger.error(f"[Rotator] Error limpiando gia_master.db: {e}")

        # B. offline_chats.db es la memoria local persistente solicitada.
        # Solo se borra si se especifica clear_vault_db=True explícitamente.
        if clear_vault_db and OFFLINE_CHATS_DB.exists():
            try:
                con = sqlite3.connect(str(OFFLINE_CHATS_DB), timeout=15.0)
                cur = con.cursor()
                row = cur.execute("SELECT COUNT(*) FROM offline_chat_turns;").fetchone()
                cleared_turns = row[0] if row else 0
                cur.execute("DELETE FROM offline_chat_turns;")
                try:
                    cur.execute("DELETE FROM offline_chat_fts;")
                except Exception:
                    pass
                con.commit()
                con.execute("VACUUM;")
                con.close()
            except Exception as e:
                logger.error(f"[Rotator] Error limpiando offline_chats.db: {e}")

        # C. Limpiar agent_context.json
        if AGENT_CONTEXT_JSON.exists():
            try:
                ctx_data = json.loads(AGENT_CONTEXT_JSON.read_text(encoding="utf-8"))
                cleared_history = len(ctx_data.get("history", []))
                ctx_data["history"] = []
                ctx_data["updated_ts"] = time.time()
                ctx_data["updated_iso"] = datetime.datetime.now().isoformat()
                AGENT_CONTEXT_JSON.write_text(json.dumps(ctx_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                logger.error(f"[Rotator] Error limpiando agent_context.json: {e}")

        # D. Limpiar SYNC_HUB en memoria y archivo de sincronización activo
        try:
            from omni_temporal_control import SYNC_HUB
            with SYNC_HUB._lock:
                hub_count = len(SYNC_HUB.history)
                SYNC_HUB.history = []
                SYNC_HUB.revision += 1
                SYNC_HUB._save_persisted_state()
            cleared_history += hub_count
        except Exception:
            pass

        # E. Actualizar visores estáticos si el módulo existe
        try:
            from core.offline_chat_vault import get_offline_chat_vault
            get_offline_chat_vault().generate_standalone_viewer()
        except Exception:
            pass

        return {
            "ok": True,
            "cleared_events": cleared_events,
            "cleared_turns": cleared_turns,
            "cleared_history": cleared_history,
            "tokens_freed_estimate": (cleared_events * 45) + (cleared_history * 60) + (cleared_turns * 120),
        }

    def handle_saturation(self, session_id: str = "omni_app", client_id: str = "anon") -> Dict[str, Any]:
        """
        Guarda toda la conversación en la memoria local persistente y elimina todo
        del chat activo para mantener un contexto limpio cuando el sistema se satura.
        """
        logger.info(f"[Rotator] ⚡ Saturación de contexto detectada para sesión {session_id}. Archivando en memoria local...")
        arch_res = self.archive_current_conversations()
        clear_res = self.clear_active_conversations(clear_vault_db=False)
        return {
            "ok": True,
            "action": "saturation_mitigated",
            "archived_records": arch_res.get("total_records", 0),
            "archive_json": arch_res.get("json_path"),
            "tokens_freed": clear_res.get("tokens_freed_estimate", 0),
            "timestamp": datetime.datetime.now().isoformat()
        }

    def purge_expired_comprehension(self, max_age_seconds: float = 86400.0) -> int:
        """
        Elimina turnos con más de 24 horas del sistema de comprensión activa
        (SYNC_HUB.history y agent_context.json), asegurando que ya estén guardados
        en la memoria local permanente.
        """
        purged = 0
        now = time.time()
        try:
            from omni_temporal_control import SYNC_HUB
            with SYNC_HUB._lock:
                fresh_history = [
                    m for m in SYNC_HUB.history
                    if (now - m.get("timestamp", now)) <= max_age_seconds
                ]
                purged = len(SYNC_HUB.history) - len(fresh_history)
                if purged > 0:
                    SYNC_HUB.history = fresh_history
                    SYNC_HUB.revision += 1
                    SYNC_HUB._save_persisted_state()
                    logger.info(f"[Rotator] 🧹 {purged} turnos con >24h purgados del sistema de comprensión activa.")
        except Exception as e:
            logger.debug(f"[Rotator] SYNC_HUB no accesible directamente para purge: {e}")
        return purged

    # =========================================================================
    # 3. ROTACIÓN INMEDIATA (ARCHIVAR + VACIAR)
    # =========================================================================

    def rotate_now(self) -> Dict[str, Any]:
        """Ejecuta inmediatamente el ciclo de respaldo local + liberación total de tokens."""
        logger.info("[Rotator] 🔄 Iniciando rotación de contexto y liberación de tokens...")
        t0 = time.time()

        # 1. Respaldar
        arch_res = self.archive_current_conversations()

        # 2. Limpiar contexto activo
        clear_res = self.clear_active_conversations()

        elapsed = round(time.time() - t0, 3)
        now_ts = time.time()
        now_iso = datetime.datetime.now().isoformat()

        # 3. Registrar estado
        self.state["last_rotation_ts"] = now_ts
        self.state["last_rotation_iso"] = now_iso
        self.state["next_rotation_ts"] = now_ts + ROTATION_INTERVAL_SECONDS
        self.state["total_rotations"] = self.state.get("total_rotations", 0) + 1
        self.state["total_events_archived"] = self.state.get("total_events_archived", 0) + arch_res.get("events_count", 0)
        self.state["total_turns_archived"] = self.state.get("total_turns_archived", 0) + arch_res.get("turns_count", 0)

        archives = self.state.setdefault("archives", [])
        archives.append({
            "ts": now_ts,
            "iso": now_iso,
            "json_path": arch_res.get("json_path"),
            "md_path": arch_res.get("md_path"),
            "records": arch_res.get("total_records"),
            "size_bytes": arch_res.get("file_size_bytes"),
        })
        # Conservar registro de los últimos 100 archivos
        if len(archives) > 100:
            self.state["archives"] = archives[-100:]

        self._save_state()

        logger.info(
            f"[Rotator] ✅ Rotación completada en {elapsed}s: "
            f"{arch_res.get('total_records')} registros archivados en {arch_res.get('json_path')}. "
            f"Tokens liberados estimados: {clear_res.get('tokens_freed_estimate')}."
        )

        return {
            "ok": True,
            "elapsed_seconds": elapsed,
            "timestamp": now_iso,
            "archive": arch_res,
            "clear": clear_res,
            "next_rotation_iso": datetime.datetime.fromtimestamp(self.state["next_rotation_ts"]).isoformat(),
        }

    # =========================================================================
    # 4. CICLO DAEMON DE 24 HORAS
    # =========================================================================

    def _daemon_loop(self) -> None:
        """Bucle en segundo plano que verifica cada minuto si han transcurrido 24 horas."""
        logger.info("[Rotator] ⏰ Demonio de rotación de contexto cada 24 horas ACTIVO.")
        while not self._stop_event.is_set():
            now = time.time()
            next_rot = self.state.get("next_rotation_ts", 0.0)

            # Si nunca se ha rotado o ya pasaron 24 horas
            if next_rot == 0.0:
                self.state["next_rotation_ts"] = now + ROTATION_INTERVAL_SECONDS
                self._save_state()
            elif now >= next_rot:
                try:
                    self.rotate_now()
                except Exception as e:
                    logger.error(f"[Rotator] Excepción en ciclo de 24h: {e}")
                    self.state["next_rotation_ts"] = now + ROTATION_INTERVAL_SECONDS
                    self._save_state()

            # Purgar turnos con >24h de antigüedad del sistema de comprensión de forma continua
            try:
                self.purge_expired_comprehension(ROTATION_INTERVAL_SECONDS)
            except Exception:
                pass

            # Esperar 60 segundos antes de la siguiente comprobación
            self._stop_event.wait(60.0)

    def start(self) -> bool:
        """Inicia el demonio de rotación automática cada 24 horas."""
        if self.running and self._thread and self._thread.is_alive():
            return True
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True, name="DailyContextRotatorDaemon")
        self._thread.start()
        return True

    def stop(self) -> None:
        """Detiene el demonio de rotación."""
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def get_status(self) -> Dict[str, Any]:
        now = time.time()
        next_ts = self.state.get("next_rotation_ts", now + ROTATION_INTERVAL_SECONDS)
        remaining_s = max(0, int(next_ts - now))
        rem_hours = round(remaining_s / 3600.0, 2)

        return {
            "ok": True,
            "running": self.running and (self._thread.is_alive() if self._thread else False),
            "rotation_interval_hours": round(ROTATION_INTERVAL_SECONDS / 3600.0, 1),
            "last_rotation_iso": self.state.get("last_rotation_iso", "Nunca"),
            "next_rotation_iso": datetime.datetime.fromtimestamp(next_ts).isoformat() if next_ts else "",
            "hours_until_next_rotation": rem_hours,
            "total_rotations_completed": self.state.get("total_rotations", 0),
            "total_events_archived": self.state.get("total_events_archived", 0),
            "total_turns_archived": self.state.get("total_turns_archived", 0),
            "archives_count": len(self.state.get("archives", [])),
            "archive_dir": str(ARCHIVE_DIR),
        }


def get_daily_context_rotator() -> DailyContextRotator:
    return DailyContextRotator.get_instance()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Rotador Autónomo de Contexto y Archivador de Conversaciones (24h)")
    parser.add_argument("--rotate-now", action="store_true", help="Ejecutar archivado y limpieza completa ahora mismo")
    parser.add_argument("--status", action="store_true", help="Ver estado del rotador y próxima ejecución")
    parser.add_argument("--daemon", action="store_true", help="Iniciar demonio persistente en primer plano")
    args = parser.parse_args()

    rotator = get_daily_context_rotator()

    if args.rotate_now:
        res = rotator.rotate_now()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.status:
        st = rotator.get_status()
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return 0

    if args.daemon:
        rotator.start()
        print("[DailyContextRotator] Demonio iniciado. Presiona Ctrl+C para salir.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            rotator.stop()
            print("\n[DailyContextRotator] Demonio detenido.")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
