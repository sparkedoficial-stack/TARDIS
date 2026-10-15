"""
TARDIS Sentinel Background Daemon
Runs recurring scans across all deal sources, maintains telemetry,
and triggers real-time desktop alerts.
"""

import time
import threading
import json
import os
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from scrapers.aggregator import DealAggregator
from core.storage import Storage
from core.notifier import Notifier


class SentinelDaemon:
    def __init__(self, config_path: Optional[str] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.config_path = config_path or str(base_dir / "config.json")
        self.pid_file = Path("/tmp/tardis_hunter_daemon.pid")
        self.status_file = Path("/tmp/tardis_hunter_status.json")

        self.config = self._load_config()
        self.interval = self.config.get("scan_interval_seconds", 300)
        self.storage = Storage()
        self.notifier = Notifier(
            enable_desktop=self.config.get("enable_desktop_notifications", True),
            enable_sound=self.config.get("enable_sound_alerts", True)
        )
        self.aggregator = DealAggregator(storage=self.storage, notifier=self.notifier)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"scan_interval_seconds": 300}

    def run_loop(self):
        """Main monitoring loop."""
        self._save_status("running", "Iniciando primer barrido...")
        while not self._stop_event.is_set():
            try:
                start_t = time.time()
                res = self.aggregator.scan_all()
                dur = round(time.time() - start_t, 2)
                self._save_status("running", f"Último barrido: {res['total_collected']} ofertas analizadas, {res['glitches_detected']} glitches ({dur}s)")
            except Exception as e:
                self._save_status("error", f"Error durante el escaneo: {str(e)}")

            # Sleep in small increments to allow fast exit
            for _ in range(self.interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

        self._save_status("stopped", "Daemon detenido.")

    def _save_status(self, state: str, message: str):
        payload = {
            "state": state,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid()
        }
        try:
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def start_background(self):
        """Starts monitoring in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_loop, daemon=True)
        self._thread.start()
        # Save PID
        self.pid_file.write_text(str(os.getpid()))

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self.pid_file.exists():
            self.pid_file.unlink(missing_ok=True)
        self._save_status("stopped", "Daemon detenido.")

    def get_status(self) -> Dict[str, Any]:
        if self.status_file.exists():
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"state": "stopped", "message": "No hay daemon activo"}
