"""
core/task_manager.py - Registro y Control Asíncrono de Procesos e Inferencias Activas
Permite abortar inferencias en tiempo real y terminar subprocesos en GPU/CPU de forma segura.
"""
from __future__ import annotations
import subprocess
import threading
import time
from typing import Dict, Any, Optional, List


class TaskManager:
    _instance: Optional[TaskManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._mutex = threading.Lock()

    @classmethod
    def get_instance(cls) -> TaskManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register(self, request_id: str, client_id: str = "anon", model: str = "") -> Dict[str, Any]:
        cancel_ev = threading.Event()
        info = {
            "request_id": request_id,
            "client_id": client_id,
            "model": model,
            "start_time": time.time(),
            "cancel_event": cancel_ev,
            "process": None,
            "cancelled": False
        }
        with self._mutex:
            self._tasks[request_id] = info
        return info

    def set_process(self, request_id: str, proc: subprocess.Popen) -> None:
        with self._mutex:
            if request_id in self._tasks:
                self._tasks[request_id]["process"] = proc

    def unregister(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._mutex:
            return self._tasks.pop(request_id, None)

    def cancel(self, request_id: Optional[str] = None, client_id: Optional[str] = None) -> List[str]:
        """Aborta la tarea especificada por request_id o todas las del client_id."""
        cancelled_ids = []
        with self._mutex:
            targets = []
            if request_id and request_id in self._tasks:
                targets.append(self._tasks[request_id])
            elif client_id:
                targets.extend([t for t in self._tasks.values() if t.get("client_id") == client_id])
            else:
                targets.extend(list(self._tasks.values()))

            for t in targets:
                t["cancelled"] = True
                ev = t.get("cancel_event")
                if ev:
                    ev.set()
                proc = t.get("process")
                if proc:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                cancelled_ids.append(t["request_id"])

        return cancelled_ids

    def list_active(self) -> List[Dict[str, Any]]:
        with self._mutex:
            return [
                {
                    "request_id": t["request_id"],
                    "client_id": t["client_id"],
                    "model": t["model"],
                    "elapsed_s": round(time.time() - t["start_time"], 2),
                    "cancelled": t["cancelled"]
                }
                for t in self._tasks.values()
            ]


def get_task_manager() -> TaskManager:
    return TaskManager.get_instance()
