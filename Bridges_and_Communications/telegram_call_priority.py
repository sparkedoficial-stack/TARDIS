"""
core/telegram_call_priority.py - Gestor Soberano de Prioridad por Llamada de Telegram
=====================================================================================

Cuando TARDIS recibe una llamada por Telegram (bot `/llamar`, nota de voz o Mini App
de voz en vivo `/tg-call`), este módulo activa el "modo llamada prioritaria":

  1. Aplica las optimizaciones de runtime de baja latencia (GC, ionice, descriptores).
  2. Eleva la prioridad CPU/IO del proceso de TARDIS **de forma segura** (best-effort):
     si el usuario no tiene CAP_SYS_NICE se registrará el aviso y no se aborta la llamada.
  3. **Refuerza trans-proceso** los procesos que sirven la llamada: `llama-server`
     (ollama), el servidor TARDIS (`omni_temporal_control`), el servidor de llamadas
     en vivo, el bridge y los hijos STT/FFmpeg. Sin este paso la inferencia seguiría
     compitiendo en desventaja (nice 10/15) frente al resto del sistema.
  4. **Deprioriza** los demonios de fondo no críticos (música, auto-mejora, rastreo)
     para liberar CPU/GPU durante la llamada.
  5. Sube el gobernador CPU a `performance` (best-effort, se restaura al colgar).
  6. Suspende el demonio de auto-evolución por inactividad mientras haya llamadas.
  7. Publica el estado en un archivo JSON compartido para que otros procesos
     (servidor de llamadas, bot, API, sensores) vean que hay una llamada activa.

El gestor usa referencias por `source` y un TTL de seguridad: si un proceso muere sin
liberar su referencia, la prioridad se restaura automáticamente. Todo el refuerzo es
best-effort y reversible: al colgar se restaura el nice original de cada proceso.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("TARDIS.TelegramCallPriority")

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = BASE_DIR / "data" / "telephony" / "telegram_call_priority.json"
DEFAULT_TTL_SEC = float(os.environ.get("TARDIS_CALL_PRIORITY_TTL_SEC", "1800"))
DEFAULT_NICE = int(os.environ.get("TARDIS_CALL_PRIORITY_NICE", "-10"))
DEFAULT_DEPRIORITIZE_NICE = int(os.environ.get("TARDIS_CALL_DEPRIORITIZE_NICE", "19"))

# Procesos que sirven la llamada: se elevan a DEFAULT_NICE (best-effort).
BOOST_TARGET_PATTERNS: tuple[str, ...] = (
    "llama-server",
    "ollama",
    "omni_temporal_control.py",
    "telegram_live_call_server.py",
    "telegram_bridge.py",
    "server/api.py",
    "ftl_public_gateway",
    "cloudflared",
    "tardis-embed-brain",
    "embed_brain",
    "cas_neural_space_kaiju",
    "tardis_cli.py",
    "tardis_app.py",
    "tardis_master_app.py",
    "tardis_infinite_voice",
    "mundo_sin_censura_voice",
    "tardis_voice_engine",
    "tardis-talk",
    "whisper",
    "ffmpeg",
    "ffprobe",
    "piper",
    "espeak",
)

# Demonios de fondo no críticos: se bajan a DEFAULT_DEPRIORITIZE_NICE durante la llamada.
# NOTA: NO se depriorizan `ftl_public_gateway` (proxy del WebSocket /tg-call/ws),
# `tardis-desktop` (cabina interactiva en CCD 0) ni `tardis-thermal-guard` (seguridad térmica).
DEPRIORITIZE_PATTERNS: tuple[str, ...] = (
    "tardis-music-maestro",
    "tardis_music_maestro.py",
    "tardis-easy-touch",
    "tardis-browser-autonomous",
    "tardis_browser.py",
    "tardis-omniscient-autonomy",
    "tardis_omniscient",
    "tardis-video-pensante",
    "tardis_video_pensante",
    "tardis-curiosity-debater",
    "tardis_curiosity_debater.py",
    "tardis-cyber-evolve",
    "cyber_recursive_agent.py",
    "tardis-hub-agents",
    "data/auto_agents.py",
    "tardis-feedback",
    "tardis-antispy-guard",
    "tardis-tapo-c310-sentinel",
    "tapo_c310_sentinel.py",
    "tardis_visual_intelligence",
    "chrome-testing",
    "tardis-hunter",
    "tardis4ever_agent",
    "singularity_engine",
    "ftl_web_server",
)

# Unidades systemd --user críticas para la latencia de llamadas de Telegram.
SYSTEMD_CRITICAL_UNITS: tuple[str, ...] = (
    "tardis-telegram-call.service",
    "tardis-infinite-voice.service",
    "tardis.service",
    "tardis-temporal-brain.service",
    "tardis-embed-brain.service",
    "tardis-ollama-voice.service",
    "ollama.service",
    "ftl-public-gateway.service",
)

# Unidades systemd --user de fondo que ceden CPUWeight/IOWeight durante la llamada.
SYSTEMD_YIELD_UNITS: tuple[str, ...] = (
    "tardis-browser-autonomous.service",
    "tardis-omniscient-autonomy.service",
    "tardis-hub-agents.service",
    "tardis-cyber-evolve.service",
    "tardis-curiosity-debater.service",
    "tardis-video-pensante.service",
    "tardis-music-maestro.service",
)


# --------------------------------------------------------------------------------------
# Utilidades de sistema (aislables en pruebas)
# --------------------------------------------------------------------------------------

def _matches_any(haystack: str, patterns: Iterable[str]) -> bool:
    return any(p and p in haystack for p in patterns)


def _process_haystack(proc: Any) -> str:
    """Construye el texto de coincidencia de un proceso (nombre + línea de comandos)."""
    info = getattr(proc, "info", None) or {}
    parts: List[str] = [str(info.get("name") or "")]
    cmdline = info.get("cmdline") or []
    if isinstance(cmdline, (list, tuple)):
        parts.extend(str(c) for c in cmdline)
    else:
        parts.append(str(cmdline))
    if not any(parts):
        try:
            parts.append(" ".join(proc.cmdline()))
        except Exception:
            pass
    return " ".join(p for p in parts if p).lower()


def iter_system_processes() -> list:
    """Itera los procesos del sistema. Aislable en pruebas mediante monkeypatch."""
    try:
        import psutil

        return list(psutil.process_iter(["pid", "name", "nice", "cmdline"]))
    except Exception:
        return []


def _read_cpu_governor() -> Optional[str]:
    try:
        return Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text(
            encoding="ascii"
        ).strip()
    except Exception:
        return None


def _set_cpu_governor(value: str) -> Optional[str]:
    """Escribe el gobernador CPU en todas las CPUs. Devuelve el valor anterior."""
    previous = _read_cpu_governor()
    if previous == value:
        return previous
    cpus = os.cpu_count() or 1
    for cpu in range(cpus):
        path = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor"
        try:
            with open(path, "w", encoding="ascii") as fh:
                fh.write(value)
            continue
        except Exception:
            pass
        try:
            subprocess.run(
                ["sudo", "-n", "tee", path],
                input=value.encode("ascii"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso escribiendo gobernador CPU en {path}: {exc}")
            return None
    return previous


def _safe_set_nice(pid: int, value: int) -> None:
    """Restaura/mejora el nice de un PID y sus hilos de trabajo (best-effort, nunca lanza)."""
    try:
        import psutil

        p = psutil.Process(pid)
        p.nice(value)
        threads_fn = getattr(p, "threads", None)
        if callable(threads_fn):
            for th in threads_fn():
                tid = getattr(th, "id", None)
                if isinstance(tid, int) and tid > 0 and tid != pid:
                    try:
                        os.setpriority(os.PRIO_PROCESS, tid, value)
                    except Exception:
                        pass
    except Exception:
        pass


def _safe_set_ionice(pid: int, ioclass: int, value: int = 0) -> None:
    """Restaura/mejora ionice de un PID de forma best-effort (nunca lanza)."""
    try:
        import psutil

        p = psutil.Process(pid)
        if ioclass in (
            getattr(psutil, "IOPRIO_CLASS_NONE", 0),
            getattr(psutil, "IOPRIO_CLASS_IDLE", 3),
        ):
            p.ionice(ioclass)
        else:
            p.ionice(ioclass, value=value)
    except Exception:
        pass


def _pid_is_alive(pid: Any) -> bool:
    """Comprueba si un PID remoto sigue vivo (True si no es verificable)."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True


def _systemd_boost_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return str(os.environ.get("TARDIS_CALL_SYSTEMD_BOOST", "1")).lower() not in ("0", "false", "no")


def _trigger_cpuset_sync_async() -> None:
    """Dispara tardis-cpuset en segundo plano desacoplado para ajustar cpuset v2 sin esperar el ciclo de 15s."""
    if not _systemd_boost_enabled():
        return
    cpuset_bin = Path("/usr/local/bin/tardis-cpuset")
    if not cpuset_bin.is_file():
        return
    try:
        subprocess.Popen(
            ["sudo", "-n", str(cpuset_bin)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Aviso sincronizando tardis-cpuset: {exc}")


def _set_systemd_unit_weights(units: Iterable[str], cpu_weight: int, io_weight: int) -> Dict[str, Dict[str, str]]:
    """Ajusta CPUWeight/IOWeight en caliente (--runtime) en systemd --user sin reiniciar servicios."""
    saved: Dict[str, Dict[str, str]] = {}
    if not _systemd_boost_enabled():
        return saved
    for unit in units:
        try:
            probe = subprocess.run(
                ["systemctl", "--user", "show", "-p", "ActiveState,CPUWeight,IOWeight", unit],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0,
                check=False,
            )
            if probe.returncode != 0:
                continue
            props: Dict[str, str] = {}
            for line in (probe.stdout or "").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
            if props.get("ActiveState") != "active":
                continue
            saved[unit] = {
                "CPUWeight": props.get("CPUWeight", "100"),
                "IOWeight": props.get("IOWeight", "100"),
            }
            subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "set-property",
                    "--runtime",
                    unit,
                    f"CPUWeight={int(cpu_weight)}",
                    f"IOWeight={int(io_weight)}",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
        except Exception:
            continue
    return saved


def _restore_systemd_unit_weights(saved: Dict[str, Dict[str, str]]) -> None:
    """Restaura CPUWeight/IOWeight en caliente a sus valores previos a la llamada."""
    if not saved or not _systemd_boost_enabled():
        return
    for unit, props in list(saved.items()):
        try:
            args = ["systemctl", "--user", "set-property", "--runtime", unit]
            cw = str(props.get("CPUWeight") or "").strip()
            iw = str(props.get("IOWeight") or "").strip()
            if cw.isdigit():
                args.append(f"CPUWeight={cw}")
            else:
                args.append("CPUWeight=100")
            if iw.isdigit():
                args.append(f"IOWeight={iw}")
            else:
                args.append("IOWeight=100")
            subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
                check=False,
            )
        except Exception:
            continue


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
        # nice original de procesos hijos de inferencia (whisper/ffmpeg/ollama run)
        self._child_nice: Dict[int, int] = {}
        # nice original de procesos del sistema reforzados trans-proceso
        self._boosted_procs: Dict[int, int] = {}
        # ionice original de procesos reforzados trans-proceso: {pid: (ioclass, value)}
        self._boosted_ionice: Dict[int, tuple[int, int]] = {}
        # nice original de demonios de fondo depriorizados
        self._deprioritized_procs: Dict[int, int] = {}
        # propiedades cgroup v2 originales en systemd --user
        self._saved_systemd_weights: Dict[str, Dict[str, str]] = {}
        self._saved_governor: Optional[str] = None
        self._governor_changed = False

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
            # Si el archivo lo escribió este mismo proceso, el estado local es autoritativo.
            owner_pid = raw.get("owner_pid")
            if owner_pid == os.getpid():
                return False
            if owner_pid is not None and not _pid_is_alive(owner_pid):
                return False
            now = self._now()
            holders = raw.get("holders")
            if isinstance(holders, list) and holders:
                return any(float(h.get("expires_at") or 0) > now for h in holders if isinstance(h, dict))
            ts = float(raw.get("timestamp") or 0)
            return (now - ts) <= max(30.0, DEFAULT_TTL_SEC)
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
                "boosted_processes": len(self._boosted_procs),
                "boosted_system_pids": sorted(self._boosted_procs),
                "deprioritized_processes": len(self._deprioritized_procs),
                "deprioritized_pids": sorted(self._deprioritized_procs),
                "cpu_governor": _read_cpu_governor(),
                "cpu_governor_forced": bool(self._governor_changed),
                "state_file": str(STATE_FILE),
                "owner_pid": os.getpid(),
                "timestamp": self._now(),
            }
        if local_active:
            self._write_state(state)
            return state

        # Sin holders locales: no pisar el estado de otro proceso si sigue activo.
        if self._file_state_active():
            try:
                raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("owner_pid") != os.getpid():
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
            tmp = STATE_FILE.with_name(f".{STATE_FILE.name}.{os.getpid()}.tmp")
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
            was_active = self._active
            self._prune_expired_locked()
            self._holders[src] = {
                "chat_id": str(chat_id) if chat_id is not None else None,
                "registered_at": self._now(),
                "expires_at": self._now() + max(0.001, ttl),
            }
            self._transition_locked(True)
            state = self.get_status()
            became_active = (not was_active) and self._active
        if became_active:
            _trigger_cpuset_sync_async()
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
            was_active = self._active
            self._holders.pop(src, None)
            self._prune_expired_locked()
            self._transition_locked(bool(self._holders))
            state = self.get_status()
            became_inactive = was_active and (not self._active)
        if became_inactive:
            _trigger_cpuset_sync_async()
        logger.info(f"🔽 [CALL-PRIORITY] Liberado {src} (holders={state['holder_count']})")
        return state

    def clear(self) -> Dict[str, Any]:
        """Liberación forzada (uso en pruebas, apagado o recuperación)."""
        with self._lock:
            was_active = self._active
            self._holders.clear()
            self._transition_locked(False)
            state = self.get_status()
        if was_active:
            _trigger_cpuset_sync_async()
        return state

    # ---------------------------------------------------- prioridad de proceso

    def _boost_system_processes(self) -> Dict[int, int]:
        """Eleva trans-proceso los procesos que sirven la llamada (best-effort).

        Devuelve {pid: nice_anterior} para poder restaurarlo al colgar.
        """
        boosted: Dict[int, int] = {}
        if str(os.environ.get("TARDIS_CALL_BOOST_PROCESSES", "1")).lower() in ("0", "false", "no"):
            return boosted
        for proc in iter_system_processes():
            try:
                info = getattr(proc, "info", None) or {}
                pid = int(info.get("pid") or 0)
                if pid <= 0 or pid == os.getpid():
                    continue
                if pid in self._boosted_procs:
                    continue
                if not _matches_any(_process_haystack(proc), BOOST_TARGET_PATTERNS):
                    continue
                import psutil

                p = psutil.Process(pid)
                current = int(p.nice())
                self._boosted_procs[pid] = current
                if current > DEFAULT_NICE:
                    p.nice(DEFAULT_NICE)
                    threads_fn = getattr(p, "threads", None)
                    if callable(threads_fn):
                        for th in threads_fn():
                            tid = getattr(th, "id", None)
                            if isinstance(tid, int) and tid > 0 and tid != pid:
                                try:
                                    os.setpriority(os.PRIO_PROCESS, tid, DEFAULT_NICE)
                                except Exception:
                                    pass
                try:
                    if hasattr(p, "ionice") and hasattr(psutil, "IOPRIO_CLASS_BE"):
                        try:
                            prev_io = p.ionice()
                            if prev_io is not None and hasattr(prev_io, "ioclass"):
                                self._boosted_ionice[pid] = (int(prev_io.ioclass), int(prev_io.value))
                        except Exception:
                            pass
                        p.ionice(psutil.IOPRIO_CLASS_BE, value=0)
                except Exception:
                    pass
                if current > DEFAULT_NICE:
                    boosted[pid] = current
            except Exception:  # noqa: BLE001
                continue
        return boosted

    def _deprioritize_competitors(self) -> Dict[int, int]:
        """Baja la prioridad de los demonios de fondo no críticos (best-effort).

        Devuelve {pid: nice_anterior} para poder restaurarlo al colgar.
        """
        deprio: Dict[int, int] = {}
        if str(os.environ.get("TARDIS_CALL_DEPRIORITIZE_COMPETITORS", "1")).lower() in ("0", "false", "no"):
            return deprio
        for proc in iter_system_processes():
            try:
                info = getattr(proc, "info", None) or {}
                pid = int(info.get("pid") or 0)
                if pid <= 0 or pid == os.getpid():
                    continue
                if pid in self._boosted_procs or pid in self._deprioritized_procs:
                    continue
                if not _matches_any(_process_haystack(proc), DEPRIORITIZE_PATTERNS):
                    continue
                import psutil

                p = psutil.Process(pid)
                current = int(p.nice())
                self._deprioritized_procs[pid] = current
                if current >= DEFAULT_DEPRIORITIZE_NICE:
                    continue
                p.nice(DEFAULT_DEPRIORITIZE_NICE)
                deprio[pid] = current
            except Exception:  # noqa: BLE001
                continue
        return deprio

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

        # 4. Refuerzo trans-proceso: inferencia (llama-server/ollama) y servidor TARDIS
        try:
            boosted = self._boost_system_processes()
            if boosted:
                logger.info(f"⚡ [CALL-PRIORITY] Procesos reforzados: {boosted}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso reforzando procesos del sistema: {exc}")

        # 5. Depriorizar demonios de fondo para liberar CPU/GPU
        try:
            deprio = self._deprioritize_competitors()
            if deprio:
                logger.info(f"🔉 [CALL-PRIORITY] Demonios de fondo depriorizados: {deprio}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso depriorizando demonios de fondo: {exc}")

        # 6. Gobernador CPU en `performance` (best-effort, se restaura al colgar)
        try:
            if str(os.environ.get("TARDIS_CALL_GOVERNOR", "1")).lower() not in ("0", "false", "no"):
                previous = _set_cpu_governor("performance")
                if previous and previous != "performance":
                    self._saved_governor = previous
                    self._governor_changed = True
                    logger.info(f"⚡ [CALL-PRIORITY] Gobernador CPU: {previous} -> performance")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Aviso ajustando gobernador CPU: {exc}")

        # 7. Refuerzo cgroup v2 en caliente (--runtime) en systemd --user sin reiniciar servicios
        if _systemd_boost_enabled():
            def _apply_systemd_weights_bg() -> None:
                try:
                    saved_crit = _set_systemd_unit_weights(SYSTEMD_CRITICAL_UNITS, cpu_weight=5000, io_weight=5000)
                    saved_bg = _set_systemd_unit_weights(SYSTEMD_YIELD_UNITS, cpu_weight=5, io_weight=5)
                    with self._lock:
                        if self._active:
                            self._saved_systemd_weights.update(saved_crit)
                            self._saved_systemd_weights.update(saved_bg)
                        else:
                            _restore_systemd_unit_weights({**saved_crit, **saved_bg})
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"Aviso ajustando CPUWeight/IOWeight systemd: {exc}")

            threading.Thread(
                target=_apply_systemd_weights_bg,
                name="CallPrioritySystemdBoost",
                daemon=True,
            ).start()

    def _restore(self) -> None:
        # 0. Restaurar cgroup v2 CPUWeight/IOWeight en systemd --user
        saved_weights = dict(self._saved_systemd_weights)
        self._saved_systemd_weights.clear()
        if saved_weights and _systemd_boost_enabled():
            threading.Thread(
                target=_restore_systemd_unit_weights,
                args=(saved_weights,),
                name="CallPrioritySystemdRestore",
                daemon=True,
            ).start()

        # 1. Restaurar el nice original de los hijos de inferencia
        for pid, nice_value in list(self._child_nice.items()):
            _safe_set_nice(pid, nice_value)
        self._child_nice.clear()
        self._boosted_pids.clear()

        # 2. Restaurar procesos del sistema reforzados (nice + ionice)
        for pid, nice_value in list(self._boosted_procs.items()):
            _safe_set_nice(pid, nice_value)
        self._boosted_procs.clear()
        for pid, (ioclass, ioval) in list(self._boosted_ionice.items()):
            _safe_set_ionice(pid, ioclass, ioval)
        self._boosted_ionice.clear()

        # 3. Restaurar demonios de fondo depriorizados
        for pid, nice_value in list(self._deprioritized_procs.items()):
            _safe_set_nice(pid, nice_value)
        self._deprioritized_procs.clear()

        # 4. Restaurar el gobernador CPU original
        if self._governor_changed and self._saved_governor:
            try:
                _set_cpu_governor(self._saved_governor)
                logger.info(f"🔽 [CALL-PRIORITY] Gobernador CPU restaurado a {self._saved_governor}")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Aviso restaurando gobernador CPU: {exc}")
        self._governor_changed = False
        self._saved_governor = None

        # 5. Restaurar optimizaciones de SO y nice propio
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

        # 6. Reanudar auto-evolución
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
            self._child_nice.setdefault(pid, int(p.nice()))
            if p.nice() > DEFAULT_NICE:
                p.nice(DEFAULT_NICE)
            ionice_ok = False
            if hasattr(psutil, "IOPRIO_CLASS_RT"):
                try:
                    p.ionice(psutil.IOPRIO_CLASS_RT, value=4)
                    ionice_ok = True
                except Exception:
                    ionice_ok = False
            if not ionice_ok and hasattr(psutil, "IOPRIO_CLASS_BE"):
                try:
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
