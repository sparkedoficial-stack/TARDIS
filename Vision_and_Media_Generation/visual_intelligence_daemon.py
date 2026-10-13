"""
core/visual_intelligence_daemon.py - Demonio Autónomo 24/7 de Inteligencia Visual
================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Ejecución en segundo plano continua e indefinida.

Funciones:
  1. Monitoreo constante del directorio spool de ingesta (/vault/visual_intelligence/spool/).
  2. Procesamiento de cola asíncrona de videos, fotos y audios.
  3. Publicación continua de telemetría y latidos (daemon_status.json, global_sync_state.json).
  4. Resiliencia total ante desconexiones o fallos con autorecuperación 100% autónoma.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.visual_intelligence_engine import (
    get_visual_intelligence_engine,
    SPOOL_DIR,
    DATA_DIR,
    VIDEOS_TELEGRAM_DIR,
    IMAGES_VAULT_DIR
)

STATUS_FILE = DATA_DIR / "daemon_status.json"
SYNC_STATE_FILE = BASE_DIR / "global_sync_state.json"
NODES_TELEMETRY_FILE = BASE_DIR / "nodes_telemetry.json"

logger = logging.getLogger("TARDIS.VisualIntelligenceDaemon")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] [VisualDaemon] [%(levelname)s] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


class VisualIntelligenceDaemon:
    """Demonio permanente de Inteligencia Visual."""

    def __init__(self, poll_interval: float = 3.0):
        self.poll_interval = poll_interval
        self.running = False
        self.start_time = time.time()
        self.processed_count = 0
        self.last_item_id = ""
        self.engine = get_visual_intelligence_engine()
        self._setup_signals()

    def _setup_signals(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._handle_exit)
            except Exception:
                pass

    def _handle_exit(self, signum, frame):
        logger.info(f"🛑 [VisualDaemon] Señal de terminación recibida ({signum}). Apagado limpio...")
        self.running = False

    def update_telemetry(self):
        """Escribe latido y telemetría de salud periódicamente."""
        try:
            import psutil
            mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            mem = 0.0

        st = self.engine.get_status()
        status_data = {
            "daemon": "tardis-visual-intelligence",
            "running": self.running,
            "pid": os.getpid(),
            "uptime_sec": round(time.time() - self.start_time, 1),
            "last_heartbeat": datetime.now().isoformat(),
            "items_processed": self.processed_count,
            "last_processed_id": self.last_item_id,
            "memory_rss_mb": round(mem, 2),
            "engine_status": st
        }

        try:
            STATUS_FILE.write_text(json.dumps(status_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        # Registrar en global_sync_state.json
        if SYNC_STATE_FILE.exists():
            try:
                g_state = json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
                g_state["visual_intelligence"] = {
                    "active": True,
                    "pid": os.getpid(),
                    "videos_stored": st.get("stored_videos_count", 0),
                    "last_ping": time.time()
                }
                SYNC_STATE_FILE.write_text(json.dumps(g_state, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def check_spool_directory(self):
        """Revisa si hay medios colocados en la carpeta de ingesta espontánea spool."""
        if not SPOOL_DIR.exists():
            return

        extensions_video = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}
        extensions_image = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        extensions_sound = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}

        for p in list(SPOOL_DIR.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue

            ext = p.suffix.lower()
            try:
                # Comprobar si el archivo está listo (no está escribiéndose)
                initial_size = p.stat().st_size
                time.sleep(0.3)
                if p.stat().st_size != initial_size or initial_size == 0:
                    continue

                logger.info(f"📥 [VisualDaemon] Archivo detectado en Spool: {p.name}")
                if ext in extensions_video:
                    res = self.engine.process_video(p, source="spool", user_name="Spool Ingestion", caption=f"Ingesta autónoma desde Spool: {p.name}")
                    self.last_item_id = res.id
                    self.processed_count += 1
                    p.unlink(missing_ok=True)
                elif ext in extensions_image:
                    res = self.engine.process_image(p, source="spool", user_name="Spool Ingestion", caption=f"Ingesta de imagen: {p.name}")
                    self.last_item_id = res.id
                    self.processed_count += 1
                    p.unlink(missing_ok=True)
                elif ext in extensions_sound:
                    res = self.engine.process_sound(p, source="spool", user_name="Spool Ingestion", caption=f"Ingesta de audio: {p.name}")
                    self.last_item_id = res.id
                    self.processed_count += 1
                    p.unlink(missing_ok=True)
            except Exception as e_proc:
                logger.error(f"Error procesando archivo de spool {p}: {e_proc}")

    def run(self):
        """Bucle principal de ejecución 24/7."""
        self.running = True
        logger.info(f"🚀 [VisualDaemon] Demonio de Inteligencia Visual iniciado (PID: {os.getpid()}).")
        last_telemetry = 0.0

        while self.running:
            try:
                self.check_spool_directory()

                now = time.time()
                if now - last_telemetry >= 10.0:
                    self.update_telemetry()
                    last_telemetry = now

                time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Aviso en ciclo de demonio visual: {e}")
                time.sleep(self.poll_interval)

        self.update_telemetry()
        logger.info("👋 [VisualDaemon] Demonio detenido limpiamente.")


def main():
    parser = argparse.ArgumentParser(description="Demonio Autónomo de Inteligencia Visual de TARDIS")
    parser.add_argument("--interval", type=float, default=3.0, help="Intervalo de sondeo en segundos")
    args = parser.parse_args()

    daemon = VisualIntelligenceDaemon(poll_interval=args.interval)
    daemon.run()


if __name__ == "__main__":
    main()
