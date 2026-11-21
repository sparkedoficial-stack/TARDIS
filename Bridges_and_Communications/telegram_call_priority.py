"""
core/telegram_call_priority.py - Gestor Soberano de Prioridad por Llamada de Telegram
=====================================================================================

Cuando TARDIS recibe una llamada por Telegram (bot `/llamar`, nota de voz o Mini App
de voz en vivo `/tg-call`), este módulo activa el "modo llamada prioritaria":

  1. Aplica las optimizaciones de runtime de baja latencia (GC, ionice, descriptores).
  2. Eleva la prioridad CPU/IO del proceso de TARDIS **de forma segura** (best-effort):
     si el usuario no tiene CAP_SYS_NICE se registrará el aviso y no se aborta la llamada.
  3. Suspende el demonio de auto-evolución por inactividad mientras haya llamadas.
  4. Refuerza los procesos de inferencia hijos (`ollama run`, whisper, ffmpeg) vía
     `boost_process_for_call()` para que compitan por CPU contra el resto del sistema.
  5. Publica el estado en un archivo JSON compartido para que otros procesos
     (servidor de llamadas, bot, API, sensores) vean que hay una llamada activa.

El gestor usa referencias por `source` y un TTL de seguridad: si un proceso muere sin
liberar su referencia, la prioridad se restaura automáticamente.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("TARDIS.TelegramCallPriority")

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "data" / "telephony" / "telegram_call_priority.json"
DEFAULT_TTL_SEC = float(os.environ.get("TARDIS_CALL_PRIORITY_TTL_SEC", "1800"))
DEFAULT_NICE = int(os.environ.get("TARDIS_CALL_PRIORITY_NICE", "-10"))


class TelegramCallPriorityManager:
    """Registro centralizado y cross-process del modo prioritario de llamada."""

    _instance: Optional["TelegramCallPriorityManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._holders: Dict[str, Dict[str, Any]] = {}
        self._active = False
        self._active_since: Optional[float] = None
        self._generation = 0
        self._saved_nice: Optional[int] = None
        self._boosted_pids: set[int] = set()

    @classmethod
    def get_instance(cls) -> "TelegramCallPriorityManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------ estado

    def _now(self) -> float:
        return time.time()

    def _prune_expired_locked(self) -> None:
        now = self._now()
        expired = [
            src for src, info in self._holders.items()
            if float(info.get("expires_at") or 0) <= now
        ]
        for src in expired:
            logger.warning(f"⏱️ Referencia de prioridad expirada liberada: {src}")
            self._holders.pop(src, None)

    def _transition_locked(self, should_be_active: bool) -> None:
        if should_be_active == self._active:
            return
        if should_be_active:
            self._active = True
            self._active_since = self._now()
            self._generation += 1
            self._apply_boost()
        else:
            self._active = False
            self._active_since = None
            self._restore()

    def _file_state_active(self) -> bool:
        """Fallback cross-process: detecta llamadas activas escritas por otro proceso."""
        try:
            if not STATE_FILE.exists():
                return False
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not raw.get("active"):
                return False
            ts = float(raw.get("timestamp") or 0)
            # Solo confiar en estado reciente para evitar falsos positivos por crash.
            return (self._now() - ts) <= max(30.0, min(DEFAULT_TTL_SEC, 120.0))
        except Exception:
            return False

    def is_active(self) -> bool:
        with self._lock:
            self._prune_expired_locked()
            self._transition_locked(bool(self._holders))
            if self._holders:
                return True
        # Fuera del lock: lectura cross-process best-effort.
        return self._file_state_active()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            self._prune_expired_locked()
            self._transition_locked(bool(self._holders))
            local_active = bool(self._holders)
            state = {
                "ok": True,
                "active": local_active,
                "system_priority": local_active,
                "system_priority_active": local_active,
                "call_priority": local_active,
                "priority_mode": "telegram_call" if local_active else "normal",
                "holders": [
                    {"source": src, "chat_id": info.get("chat_id"), "expires_at": info.get("expires_at")}
                    for src, info in self._holders.items()
                ],
                "holder_count": len(self._holders),
                "generation": self._generation,
                "active_since": self._active_since,
                "boosted_pids": sorted(self._boosted_pids),
                "state_file": str(STATE_FILE),
                "timestamp": self._now(),
            }
        if local_active:
            self._write_state(state)
            return state

        # Sin holders locales: no pisar el estado de otro proceso si sigue activo.
        if self._file_state_active():
            try:
                raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw["ok"] = True
                    raw["cross_process_active"] = True
                    raw["local_holder_count"] = 0
                    return raw
            except Exception:
                pass
        self._write_state(state)
        return state

    def _write_state(self, state: Dict[str, Any]) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_FILE)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso escribiendo estado de prioridad: {exc}")

    # ------------------------------------------------------------ activación

    def activate(
        self,
        source: str,
        chat_id: Optional[int | str] = None,
        ttl_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Registra una llamada activa y activa el modo prioritario la primera vez."""
        src = str(source or "unknown")
        ttl = float(ttl_sec if ttl_sec is not None else DEFAULT_TTL_SEC)
        with self._lock:
            self._prune_expired_locked()
            self._holders[src] = {
                "chat_id": str(chat_id) if chat_id is not None else None,
                "registered_at": self._now(),
                "expires_at": self._now() + max(0.001, ttl),
            }
            self._transition_locked(True)
            state = self.get_status()
        logger.info(f"⚡ [CALL-PRIORITY] Activado por {src} (chat={chat_id}, holders={state['holder_count']})")
        return state

    def touch(
        self,
        source: str,
        chat_id: Optional[int | str] = None,
        ttl_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Renueva el TTL de una llamada larga sin cambiar el número de referencias."""
        src = str(source or "unknown")
        ttl = float(ttl_sec if ttl_sec is not None else DEFAULT_TTL_SEC)
        with self._lock:
            info = self._holders.get(src)
            if not info:
                return self.activate(src, chat_id=chat_id, ttl_sec=ttl)
            info["expires_at"] = self._now() + max(0.001, ttl)
            if chat_id is not None:
                info["chat_id"] = str(chat_id)
            state = self.get_status()
        return state

    def release(self, source: str) -> Dict[str, Any]:
        """Libera la referencia de una llamada; restaura prioridad al llegar a cero."""
        src = str(source or "unknown")
        with self._lock:
            self._holders.pop(src, None)
            self._prune_expired_locked()
            self._transition_locked(bool(self._holders))
            state = self.get_status()
        logger.info(f"🔽 [CALL-PRIORITY] Liberado {src} (holders={state['holder_count']})")
        return state

    def clear(self) -> Dict[str, Any]:
        """Liberación forzada (uso en pruebas, apagado o recuperación)."""
        with self._lock:
            self._holders.clear()
            self._transition_locked(False)
            state = self.get_status()
        return state

    # ---------------------------------------------------- prioridad de proceso

    def _apply_boost(self) -> None:
        # 1. Optimizaciones de runtime de baja latencia (GC, NOFILE, mallopt, ionice base)
        try:
            from core.os_optimizer import get_os_optimizer

            opt = get_os_optimizer()
            if not getattr(opt, "applied", False):
                opt.apply_runtime_optimizations()
            fn = getattr(opt, "prioritize_for_telegram_call", None)
            if callable(fn):
                fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso aplicando OSOptimizer en llamada: {exc}")

        # 2. Prioridad CPU del proceso actual (best-effort, sin requerir root)
        try:
            current = os.getpriority(os.PRIO_PROCESS, 0)
            self._saved_nice = current
            if current > DEFAULT_NICE:
                os.setpriority(os.PRIO_PROCESS, 0, DEFAULT_NICE)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso elevando nice del proceso (CAP_SYS_NICE ausente): {exc}")
        try:
            import psutil

            proc = psutil.Process()
            if proc.nice() > DEFAULT_NICE:
                proc.nice(DEFAULT_NICE)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso elevando nice vía psutil: {exc}")

        # 3. Silenciar auto-evolución pesada mientras dure la llamada
        self._set_idle_daemon_suspended(True)

    def _restore(self) -> None:
        try:
            from core.os_optimizer import get_os_optimizer

            fn = getattr(get_os_optimizer(), "restore_normal_priority", None)
            if callable(fn):
                fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso restaurando OSOptimizer: {exc}")

        try:
            if self._saved_nice is not None:
                os.setpriority(os.PRIO_PROCESS, 0, self._saved_nice)
                self._saved_nice = None
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso restaurando nice del proceso: {exc}")
        try:
            import psutil

            proc = psutil.Process()
            if proc.nice() < 0:
                proc.nice(0)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso restaurando nice vía psutil: {exc}")

        self._set_idle_daemon_suspended(False)

    @staticmethod
    def _set_idle_daemon_suspended(suspended: bool) -> None:
        try:
            from core.idle_evolution_daemon import get_idle_evolution_daemon

            daemon = get_idle_evolution_daemon()
            if suspended:
                fn = getattr(daemon, "suspend_for_call", None)
                if callable(fn):
                    fn()
                else:
                    daemon.record_user_activity()
            else:
                fn = getattr(daemon, "resume_after_call", None)
                if callable(fn):
                    fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso ajustando IdleEvolutionDaemon: {exc}")

    def boost_process_for_call(self, proc: Any) -> Dict[str, Any]:
        """Eleva la prioridad de un proceso hijo de inferencia/STT/FFmpeg durante la llamada."""
        result: Dict[str, Any] = {"ok": False, "pid": None}
        if proc is None:
            return result
        pid = getattr(proc, "pid", None)
        result["pid"] = pid
        if not isinstance(pid, int) or pid <= 0:
            return result
        with self._lock:
            if pid in self._boosted_pids:
                result["ok"] = True
                result["already_boosted"] = True
                return result
            self._boosted_pids.add(pid)
        try:
            import psutil

            p = psutil.Process(pid)
            if p.nice() > DEFAULT_NICE:
                p.nice(DEFAULT_NICE)
            try:
                if hasattr(psutil, "IOPRIO_CLASS_RT"):
                    p.ionice(psutil.IOPRIO_CLASS_RT, value=4)
                elif hasattr(psutil, "IOPRIO_CLASS_BE"):
                    p.ionice(psutil.IOPRIO_CLASS_BE, value=0)
            except Exception:
                pass
            result["ok"] = True
            result["nice"] = p.nice()
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
        return result


def get_telegram_call_priority_manager() -> TelegramCallPriorityManager:
    return TelegramCallPriorityManager.get_instance()


def activate_call_priority(
    source: str,
    chat_id: Optional[int | str] = None,
    ttl_sec: Optional[float] = None,
) -> Dict[str, Any]:
    return get_telegram_call_priority_manager().activate(source, chat_id=chat_id, ttl_sec=ttl_sec)


def touch_call_priority(
    source: str,
    chat_id: Optional[int | str] = None,
    ttl_sec: Optional[float] = None,
) -> Dict[str, Any]:
    return get_telegram_call_priority_manager().touch(source, chat_id=chat_id, ttl_sec=ttl_sec)


def release_call_priority(source: str) -> Dict[str, Any]:
    return get_telegram_call_priority_manager().release(source)


def is_call_priority_active() -> bool:
    return get_telegram_call_priority_manager().is_active()


def boost_process_for_call(proc: Any) -> Dict[str, Any]:
    return get_telegram_call_priority_manager().boost_process_for_call(proc)


def get_call_priority_status() -> Dict[str, Any]:
    return get_telegram_call_priority_manager().get_status()
