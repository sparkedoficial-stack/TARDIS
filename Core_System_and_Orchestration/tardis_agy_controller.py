#!/usr/bin/env python3
"""
core/tardis_agy_controller.py - Control Soberano y Autónomo Total de TARDIS sobre la Terminal AGY
==================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Proporciona a TARDIS control programático, persistente, bidireccional y 100% autónomo
sobre la terminal Antigravity CLI (`agy`) usando únicamente contratos oficiales y
documentados de Antigravity CLI v1.5+:

1. Verificación y Auditoría de Permisos Cero-Prompts (`verify_permissions`):
   - Valida `~/.gemini/antigravity-cli/settings.json`, `~/.config/agy/pinned-settings.json`,
     `~/.gemini/config/hooks.json` y el wrapper `~/.local/bin/agy`.
   - Comprueba las claves oficiales: `toolPermission: "always-proceed"`,
     `agentMode: "accept-edits"|"auto"`, `artifactReviewPolicy: "always-proceed"`,
     `allowNonWorkspaceAccess: true` y wildcards globales en `permissions.allow`.
   - Opcionalmente ejecuta una sonda en vivo (`--output-format stream-json`) para
     confirmar empíricamente `init.permission_mode == "always-proceed"`.

2. Sesión Persistente Multi-Turno en Streaming (`AgyStreamSession`):
   - Mantiene un proceso `agy --input-format stream-json --output-format stream-json`
     caliente y stateful controlado por TARDIS vía NDJSON en stdin/stdout.
   - Cero overhead de arranque entre turnos, captura en tiempo real de `init`,
     `step_update` (herramientas ejecutadas, deltas de texto) y `result` (tokens/estado).

3. Ejecución Estructurada Headless (`run_task` / `continue_session`):
   - Ejecuta tareas one-shot o continuación de sesiones existentes (`--conversation <id>`
     o `--continue`) con `--output-format json`, `--json-schema`, `--model`, `--effort`,
     `--add-dir` y `--dangerously-skip-permissions`.
   - Telemetría completa en `~/vw-control/agy_terminal_control/session_ledger.jsonl`
     y respaldo opcional en TemporalBrain ante errores de red/cuota.

4. Cola Autónoma Persistente y Demonio Autopilot (`enqueue_task` / `run_daemon`):
   - Spool atómico en `~/vw-control/agy_terminal_control/{queue,running,completed,failed}`
     con bloqueo exclusivo `fcntl.flock`, deduplicación por SHA-256, prioridades
     (`critical`, `high`, `normal`, `low`), pausa/reanudación, circuit-breaker ante
     errores consecutivos y despacho directo desde cualquier subsistema de TARDIS.
"""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import logging
import os
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("TARDIS.AgyController")

HOME = Path.home()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / "vw-control"
CONTROL_DIR = APPDATA_DIR / "agy_terminal_control"

QUEUE_DIR = CONTROL_DIR / "queue"
RUNNING_DIR = CONTROL_DIR / "running"
COMPLETED_DIR = CONTROL_DIR / "completed"
FAILED_DIR = CONTROL_DIR / "failed"

STATE_FILE = CONTROL_DIR / "state.json"
EVENTS_FILE = CONTROL_DIR / "events.jsonl"
LEDGER_FILE = CONTROL_DIR / "session_ledger.jsonl"
LIVE_SESSIONS_FILE = CONTROL_DIR / "live_sessions.json"
LOCK_FILE = CONTROL_DIR / "autopilot.lock"

AGY_CLI_DIR = HOME / ".gemini" / "antigravity-cli"
AGY_SETTINGS_FILE = AGY_CLI_DIR / "settings.json"
AGY_PINNED_FILE = HOME / ".config" / "agy" / "pinned-settings.json"
AGY_HOOKS_FILE = HOME / ".gemini" / "config" / "hooks.json"
AGY_SUMMARIES_DB = AGY_CLI_DIR / "conversation_summaries.db"
AGY_CONVERSATIONS_DIR = AGY_CLI_DIR / "conversations"
AGY_BRAIN_DIR = AGY_CLI_DIR / "brain"

DEFAULT_MODEL = "gemini-4-neon-xhigh"
FAST_MODEL = "gemini-3.8-flash-high"
PROBE_MODEL = "gemini-3.8-flash-low"

REQUIRED_WILDCARDS = (
    "command(*)",
    "read_file(*)",
    "write_file(*)",
    "read_url(*)",
    "execute_url(*)",
    "mcp(*)",
)

PRIORITY_RANK = {
    "critical": 0,
    "urgent": 0,
    "high": 1,
    "normal": 2,
    "medium": 2,
    "low": 3,
}


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_dirs() -> None:
    for d in (CONTROL_DIR, QUEUE_DIR, RUNNING_DIR, COMPLETED_DIR, FAILED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-agy-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _resolve_agy_bin(prefer_real: bool = False) -> str:
    candidates = (
        [HOME / ".local" / "bin" / "agy-real", Path("/home/m11/.local/bin/agy-real")]
        if prefer_real
        else [HOME / ".local" / "bin" / "agy", Path("/home/m11/.local/bin/agy")]
    )
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    found = shutil.which("agy-real" if prefer_real else "agy")
    return found or str(candidates[0])


def _effort_for_model(model: str, explicit_effort: Optional[str] = None) -> str:
    if explicit_effort:
        return explicit_effort.strip().lower()
    low = (model or "").lower()
    if "neon" in low or "xhigh" in low:
        return "xhigh"
    if "low" in low:
        return "low"
    if "medium" in low:
        return "medium"
    return "high"


def _build_autonomous_env() -> Dict[str, str]:
    env = os.environ.copy()
    local_bin = str(HOME / ".local" / "bin")
    opencode_bin = str(HOME / ".opencode" / "bin")
    env["PATH"] = f"{local_bin}:{opencode_bin}:/usr/local/bin:/usr/bin:/bin:{env.get('PATH', '')}"
    env["AGY_MODE"] = "ultra"
    env["AGY_VERBOSITY"] = "high"
    env["AGY_KERNEL_LEVEL"] = "1"
    env["KERNEL_OPERATIONS"] = "1"
    env["FTL_AUTONOMOUS"] = "1"
    env["TARDIS_AGY_AUTONOMOUS"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _terminate_process_group(proc: subprocess.Popen) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class AgyStreamSession:
    """
    Sesión persistente multi-turno sobre el protocolo oficial NDJSON de Antigravity CLI:
      `agy --input-format stream-json --output-format stream-json --dangerously-skip-permissions`
    Permite a TARDIS conducir múltiples turnos consecutivos en el mismo proceso caliente,
    conservando la memoria conversacional e inspeccionando cada paso y llamada a herramientas.
    """

    def __init__(
        self,
        cwd: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
        add_dirs: Optional[List[str]] = None,
        use_real_binary: bool = False,
    ):
        self.cwd = cwd if (cwd and os.path.isdir(cwd)) else str(PROJECT_ROOT)
        self.model = model or DEFAULT_MODEL
        self.effort = _effort_for_model(self.model, effort)
        self.initial_conversation_id = conversation_id
        self.conversation_id: Optional[str] = conversation_id
        self.add_dirs = list(add_dirs or [])
        self.use_real_binary = use_real_binary

        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_lines: List[str] = []
        self._stderr_thread: Optional[threading.Thread] = None
        self.permission_mode: str = ""
        self.tools: List[str] = []
        self.turns_completed: int = 0
        self.started_at: Optional[float] = None
        self.last_turn_at: Optional[float] = None

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> Dict[str, Any]:
        with self._lock:
            return self._start_unlocked()

    def _start_unlocked(self) -> Dict[str, Any]:
        if self.is_alive:
            return {
                "ok": True,
                "already_running": True,
                "pid": self._proc.pid if self._proc else None,
                "conversation_id": self.conversation_id,
            }

        agy_bin = _resolve_agy_bin(prefer_real=self.use_real_binary)
        cmd = [
            agy_bin,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
            "--model", self.model,
            "--effort", self.effort,
        ]
        if self.conversation_id:
            cmd.extend(["--conversation", self.conversation_id])
        for extra_dir in self.add_dirs:
            if os.path.isdir(extra_dir):
                cmd.extend(["--add-dir", extra_dir])

        self._stderr_lines = []
        self._proc = subprocess.Popen(
            cmd,
            cwd=self.cwd,
            env=_build_autonomous_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.started_at = time.time()

        def _drain_stderr(pipe) -> None:
            try:
                for line in pipe:
                    s = line.rstrip()
                    if s:
                        self._stderr_lines.append(s)
                        if len(self._stderr_lines) > 200:
                            self._stderr_lines.pop(0)
            except Exception:
                pass

        self._stderr_thread = threading.Thread(
            target=_drain_stderr,
            args=(self._proc.stderr,),
            daemon=True,
            name=f"AgyStreamStderr-{self._proc.pid}",
        )
        self._stderr_thread.start()

        return {
            "ok": True,
            "pid": self._proc.pid,
            "model": self.model,
            "effort": self.effort,
            "cwd": self.cwd,
            "conversation_id": self.conversation_id,
        }

    def send_turn(
        self,
        prompt: str,
        timeout: float = 600.0,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return {"ok": False, "error": "Prompt vacío para AgyStreamSession."}

        with self._lock:
            if not self.is_alive:
                self._start_unlocked()

            assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None

            t0 = time.time()
            deadline = t0 + max(5.0, float(timeout))
            msg = {"event": "user", "message": {"content": clean_prompt}}
            try:
                self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except Exception as exc:
                self._close_unlocked()
                return {"ok": False, "error": f"Error enviando turno por stdin a agy: {exc}"}

            tool_calls: List[Dict[str, Any]] = []
            text_deltas: List[str] = []
            raw_non_json: List[str] = []
            result_payload: Optional[Dict[str, Any]] = None
            fd = self._proc.stdout.fileno()

            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self._close_unlocked()
                    return {
                        "ok": False,
                        "status": "TIMEOUT",
                        "conversation_id": self.conversation_id,
                        "error": f"Timeout ({timeout}s) esperando resultado de agy stream-json.",
                        "elapsed_seconds": round(time.time() - t0, 2),
                        "tool_calls": tool_calls,
                        "stderr_tail": self._stderr_lines[-15:],
                    }

                ready, _, _ = select.select([fd], [], [], min(1.0, remaining))
                if not ready:
                    if self._proc.poll() is not None:
                        break
                    continue

                line = self._proc.stdout.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    ev = json.loads(stripped)
                except json.JSONDecodeError:
                    raw_non_json.append(stripped)
                    continue

                if on_event:
                    try:
                        on_event(ev)
                    except Exception:
                        pass

                ev_type = ev.get("event")
                if ev_type == "init":
                    cid = ev.get("conversation_id")
                    if cid:
                        self.conversation_id = cid
                    init_obj = ev.get("init") or {}
                    self.permission_mode = str(init_obj.get("permission_mode") or self.permission_mode)
                    if isinstance(init_obj.get("tools"), list):
                        self.tools = init_obj["tools"]
                elif ev_type == "step_update":
                    su = ev.get("step_update") or {}
                    if su.get("conversation_id"):
                        self.conversation_id = su["conversation_id"]
                    if su.get("text_delta"):
                        text_deltas.append(str(su["text_delta"]))
                    if su.get("step_type") == "tool" and su.get("state") == "DONE":
                        tinfo = su.get("tool_info") or {}
                        tool_calls.append({
                            "name": su.get("tool_name") or tinfo.get("name"),
                            "duration_seconds": su.get("duration_seconds"),
                            "error": tinfo.get("error"),
                        })
                elif ev_type == "result":
                    result_payload = ev.get("result") or {}
                    if result_payload.get("conversation_id"):
                        self.conversation_id = result_payload["conversation_id"]
                    break

            elapsed = round(time.time() - t0, 2)
            self.last_turn_at = time.time()

            if result_payload is None:
                rc = self._proc.poll()
                self._close_unlocked()
                return {
                    "ok": False,
                    "status": "EOF_ERROR",
                    "returncode": rc,
                    "conversation_id": self.conversation_id,
                    "error": "El proceso agy stream-json terminó sin emitir evento result.",
                    "elapsed_seconds": elapsed,
                    "partial_response": "".join(text_deltas).strip(),
                    "stderr_tail": self._stderr_lines[-20:],
                    "raw_non_json": raw_non_json[-10:],
                }

            status = str(result_payload.get("status") or "UNKNOWN")
            ok = status == "SUCCESS"
            if ok:
                self.turns_completed += 1
            return {
                "ok": ok,
                "status": status,
                "conversation_id": self.conversation_id or result_payload.get("conversation_id"),
                "response": (result_payload.get("response") or "".join(text_deltas)).strip(),
                "error": result_payload.get("error") or "",
                "num_turns": result_payload.get("num_turns", self.turns_completed),
                "duration_seconds": result_payload.get("duration_seconds", elapsed),
                "turn_elapsed_seconds": elapsed,
                "usage": result_payload.get("usage") or {},
                "permission_mode": self.permission_mode,
                "model": self.model,
                "effort": self.effort,
                "tool_calls": tool_calls,
                "tool_calls_count": len(tool_calls),
            }

    def close(self) -> Dict[str, Any]:
        with self._lock:
            return self._close_unlocked()

    def _close_unlocked(self) -> Dict[str, Any]:
        proc = self._proc
        self._proc = None
        if proc is None:
            return {"ok": True, "was_running": False}
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            _terminate_process_group(proc)
        return {"ok": True, "was_running": True, "conversation_id": self.conversation_id}

    def info(self) -> Dict[str, Any]:
        return {
            "alive": self.is_alive,
            "pid": self._proc.pid if (self._proc and self.is_alive) else None,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "effort": self.effort,
            "cwd": self.cwd,
            "permission_mode": self.permission_mode,
            "turns_completed": self.turns_completed,
            "started_at": self.started_at,
            "last_turn_at": self.last_turn_at,
        }


class TardisAgyController:
    """
    Controlador soberano central que entrega a TARDIS dominio operativo total sobre
    la terminal Antigravity CLI (`agy`) sin prompts ni solicitud de permisos.
    """

    _instance: Optional["TardisAgyController"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisAgyController":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        _ensure_dirs()
        self._op_lock = threading.Lock()
        self._stream_session: Optional[AgyStreamSession] = None
        self._stop_daemon = threading.Event()
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "schema": "tardis.agy_control.v1",
            "autonomous_control_enabled": True,
            "paused": False,
            "default_model": DEFAULT_MODEL,
            "default_effort": "xhigh",
            "tasks_executed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "consecutive_failures": 0,
            "last_conversation_id": None,
            "last_task_id": None,
            "last_task_at": None,
            "daemon_pid": None,
            "daemon_heartbeat_ts": 0.0,
            "daemon_heartbeat_iso": None,
            "updated_at": _now_iso(),
        }
        loaded = _load_json(STATE_FILE)
        if isinstance(loaded, dict):
            default_state.update(loaded)
        return default_state

    def _save_state(self) -> None:
        self._state["updated_at"] = _now_iso()
        try:
            _atomic_write_json(STATE_FILE, self._state, mode=0o600)
        except Exception as exc:
            logger.debug("No se pudo guardar state.json: %s", exc)

    def _emit_event(self, kind: str, **data: Any) -> None:
        _append_jsonl(
            EVENTS_FILE,
            {"ts": time.time(), "iso": _now_iso(), "kind": kind, **data},
        )

    # -------------------------------------------------------------------------
    # 1. VERIFICACIÓN DE PERMISOS OFICIALES AGY (CERO-PROMPTS)
    # -------------------------------------------------------------------------
    def verify_permissions(self, run_live_probe: bool = False) -> Dict[str, Any]:
        """
        Audita settings.json, pinned-settings.json, hooks.json y el wrapper `agy`.
        Con `run_live_probe=True`, ejecuta una sonda real con `agy-real` sin flags
        de bypass para demostrar empíricamente que el perfil persistente aplica
        `permission_mode == "always-proceed"`.
        """
        settings = _load_json(AGY_SETTINGS_FILE, {}) or {}
        pinned = _load_json(AGY_PINNED_FILE, {}) or {}
        hooks = _load_json(AGY_HOOKS_FILE, {}) or {}

        allow_list = set((settings.get("permissions") or {}).get("allow") or [])
        missing_wildcards = [w for w in REQUIRED_WILDCARDS if w not in allow_list]
        deny_list = (settings.get("permissions") or {}).get("deny") or []
        ask_list = (settings.get("permissions") or {}).get("ask") or []

        checks = {
            "agy_wrapper_exists": Path(_resolve_agy_bin(prefer_real=False)).is_file(),
            "agy_real_exists": Path(_resolve_agy_bin(prefer_real=True)).is_file(),
            "settings_toolPermission_always_proceed": settings.get("toolPermission") == "always-proceed",
            "settings_agentMode_autonomous": settings.get("agentMode") in ("accept-edits", "auto"),
            "settings_artifactReviewPolicy_always_proceed": settings.get("artifactReviewPolicy") == "always-proceed",
            "settings_allowNonWorkspaceAccess": settings.get("allowNonWorkspaceAccess") is True,
            "settings_enableTerminalSandbox_off": settings.get("enableTerminalSandbox") in (False, None),
            "settings_all_wildcards_present": len(missing_wildcards) == 0,
            "settings_no_blocking_ask_or_deny": len(deny_list) == 0 and len(ask_list) == 0,
            "pinned_aligned": (
                pinned.get("toolPermission") == "always-proceed"
                and pinned.get("artifactReviewPolicy") == "always-proceed"
            ),
            "tardis_hook_registered": "tardis-agy-bridge" in hooks,
        }

        report: Dict[str, Any] = {
            "ok": all(checks.values()),
            "checks": checks,
            "missing_wildcards": missing_wildcards,
            "effective_settings": {
                "toolPermission": settings.get("toolPermission"),
                "agentMode": settings.get("agentMode"),
                "artifactReviewPolicy": settings.get("artifactReviewPolicy"),
                "allowNonWorkspaceAccess": settings.get("allowNonWorkspaceAccess"),
                "enableTerminalSandbox": settings.get("enableTerminalSandbox"),
                "model": settings.get("model"),
                "verbosity": settings.get("verbosity"),
                "allow_count": len(allow_list),
            },
            "agy_bin": _resolve_agy_bin(prefer_real=False),
            "agy_real_bin": _resolve_agy_bin(prefer_real=True),
        }

        if run_live_probe:
            probe_res = self._run_live_permission_probe()
            report["live_probe"] = probe_res
            report["ok"] = report["ok"] and bool(probe_res.get("ok"))

        return report

    def _run_live_permission_probe(self, timeout: int = 45) -> Dict[str, Any]:
        """Sonda real con `agy-real` SIN `--dangerously-skip-permissions` para validar settings.json."""
        agy_real = _resolve_agy_bin(prefer_real=True)
        cmd = [
            agy_real,
            "--model", PROBE_MODEL,
            "--output-format", "stream-json",
            "--print-timeout", f"{timeout}s",
            "-p", "Reply with exactly: AGY_AUTONOMOUS_PROBE_OK",
        ]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=_build_autonomous_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout + 15,
                start_new_session=True,
            )
            init_mode = ""
            final_status = ""
            response = ""
            cid = ""
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event") == "init":
                    cid = ev.get("conversation_id") or cid
                    init_mode = str((ev.get("init") or {}).get("permission_mode") or "")
                elif ev.get("event") == "result":
                    res = ev.get("result") or {}
                    final_status = str(res.get("status") or "")
                    response = str(res.get("response") or "").strip()
                    cid = res.get("conversation_id") or cid

            ok = proc.returncode == 0 and init_mode == "always-proceed" and final_status == "SUCCESS"
            return {
                "ok": ok,
                "returncode": proc.returncode,
                "permission_mode": init_mode,
                "status": final_status,
                "conversation_id": cid,
                "response": response,
                "elapsed_seconds": round(time.time() - t0, 2),
                "stderr": (proc.stderr or "").strip()[-400:],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "elapsed_seconds": round(time.time() - t0, 2)}

    # -------------------------------------------------------------------------
    # 2. EJECUCIÓN HEADLESS ESTRUCTURADA (ONE-SHOT Y CONTINUACIÓN DE SESIÓN)
    # -------------------------------------------------------------------------
    def run_task(
        self,
        prompt: str,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
        continue_recent: bool = False,
        add_dirs: Optional[List[str]] = None,
        json_schema: Optional[str] = None,
        timeout: int = 900,
        source: str = "tardis_autonomous",
        fallback_to_local: bool = False,
        disable_slash_commands: bool = False,
    ) -> Dict[str, Any]:
        """
        Ejecuta una orden directa y autónoma en `agy` con salida JSON estructurada,
        cero prompts (`--dangerously-skip-permissions` + settings `always-proceed`),
        captura de telemetría de tokens y registro en el ledger de TARDIS.
        """
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return {"ok": False, "error": "Prompt vacío para ejecución en agy."}

        work_dir = cwd if (cwd and os.path.isdir(cwd)) else str(PROJECT_ROOT)
        target_model = model or self._state.get("default_model") or DEFAULT_MODEL
        target_effort = _effort_for_model(target_model, effort)
        agy_bin = _resolve_agy_bin(prefer_real=False)

        cmd: List[str] = [
            agy_bin,
            "--dangerously-skip-permissions",
            "--model", target_model,
            "--effort", target_effort,
            "--output-format", "json",
            "--print-timeout", f"{int(timeout)}s",
        ]
        if conversation_id:
            cmd.extend(["--conversation", conversation_id])
        elif continue_recent:
            cmd.append("--continue")
        if disable_slash_commands:
            cmd.append("--disable-slash-commands")
        if json_schema:
            cmd.extend(["--json-schema", json_schema])
        for extra_dir in (add_dirs or []):
            if os.path.isdir(extra_dir):
                cmd.extend(["--add-dir", extra_dir])
        cmd.extend(["-p", clean_prompt])

        task_id = f"agy_run_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        t0 = time.time()
        self._emit_event("task_started", task_id=task_id, source=source, model=target_model, cwd=work_dir)

        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                env=_build_autonomous_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=int(timeout) + 30,
                start_new_session=True,
            )
            elapsed = round(time.time() - t0, 2)
            stdout_raw = (proc.stdout or "").strip()
            stderr_raw = (proc.stderr or "").strip()

            envelope: Dict[str, Any] = {}
            if stdout_raw:
                # agy --output-format json emite un objeto JSON en la última línea de stdout
                for candidate in reversed(stdout_raw.splitlines()):
                    candidate = candidate.strip()
                    if candidate.startswith("{") and candidate.endswith("}"):
                        try:
                            envelope = json.loads(candidate)
                            break
                        except json.JSONDecodeError:
                            continue

            status = str(envelope.get("status") or ("SUCCESS" if proc.returncode == 0 else "ERROR"))
            response = str(envelope.get("response") or (stdout_raw if not envelope else "")).strip()
            err_msg = str(envelope.get("error") or (stderr_raw if proc.returncode != 0 else "")).strip()
            out_cid = envelope.get("conversation_id") or conversation_id
            ok = (proc.returncode == 0) and (status == "SUCCESS") and bool(response or envelope.get("structured_output") is not None)

            fallback_used = False
            if not ok and fallback_to_local:
                fb = self._fallback_temporal_brain(clean_prompt)
                if fb.get("ok") and fb.get("reply"):
                    response = f"{fb['reply']}\n\n[⚡ Resuelto con respaldo de Núcleo Soberano Temporal Brain]"
                    status = "FALLBACK_LOCAL"
                    ok = True
                    fallback_used = True

            result = {
                "ok": ok,
                "task_id": task_id,
                "source": source,
                "status": status,
                "returncode": proc.returncode,
                "conversation_id": out_cid,
                "model": target_model,
                "effort": target_effort,
                "cwd": work_dir,
                "response": response,
                "reply": response,
                "structured_output": envelope.get("structured_output"),
                "usage": envelope.get("usage") or {},
                "num_turns": envelope.get("num_turns", 1),
                "duration_seconds": envelope.get("duration_seconds", elapsed),
                "elapsed": elapsed,
                "error": "" if ok else (err_msg or f"agy exited with rc={proc.returncode}"),
                "stderr_tail": stderr_raw[-600:] if stderr_raw else "",
                "fallback_used": fallback_used,
                "iso": _now_iso(),
            }
            self._record_execution(result, clean_prompt)
            return result

        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - t0, 2)
            res = {
                "ok": False,
                "task_id": task_id,
                "source": source,
                "status": "TIMEOUT",
                "conversation_id": conversation_id,
                "cwd": work_dir,
                "elapsed": elapsed,
                "error": f"Timeout ({timeout}s) ejecutando tarea en terminal agy.",
                "iso": _now_iso(),
            }
            self._record_execution(res, clean_prompt)
            return res
        except Exception as exc:
            elapsed = round(time.time() - t0, 2)
            res = {
                "ok": False,
                "task_id": task_id,
                "source": source,
                "status": "EXCEPTION",
                "conversation_id": conversation_id,
                "cwd": work_dir,
                "elapsed": elapsed,
                "error": str(exc),
                "iso": _now_iso(),
            }
            self._record_execution(res, clean_prompt)
            return res

    def _fallback_temporal_brain(self, prompt: str) -> Dict[str, Any]:
        try:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            from core.temporal_brain import get_temporal_brain
            return get_temporal_brain().chat(
                [{"role": "user", "content": f"[TAREA AUTÓNOMA AGY/TARDIS]: {prompt}"}],
                max_tokens=2048,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _record_execution(self, result: Dict[str, Any], prompt: str) -> None:
        with self._op_lock:
            self._state["tasks_executed"] = int(self._state.get("tasks_executed", 0)) + 1
            if result.get("ok"):
                self._state["tasks_succeeded"] = int(self._state.get("tasks_succeeded", 0)) + 1
                self._state["consecutive_failures"] = 0
            else:
                self._state["tasks_failed"] = int(self._state.get("tasks_failed", 0)) + 1
                self._state["consecutive_failures"] = int(self._state.get("consecutive_failures", 0)) + 1
            if result.get("conversation_id"):
                self._state["last_conversation_id"] = result["conversation_id"]
            self._state["last_task_id"] = result.get("task_id")
            self._state["last_task_at"] = _now_iso()
            self._save_state()

        _append_jsonl(
            LEDGER_FILE,
            {
                "ts": time.time(),
                "iso": _now_iso(),
                "task_id": result.get("task_id"),
                "source": result.get("source"),
                "ok": result.get("ok"),
                "status": result.get("status"),
                "conversation_id": result.get("conversation_id"),
                "model": result.get("model"),
                "elapsed": result.get("elapsed", result.get("turn_elapsed_seconds")),
                "usage": result.get("usage") or {},
                "prompt_preview": prompt[:300],
                "response_preview": str(result.get("response") or "")[:600],
                "error": result.get("error") or "",
            },
        )
        self._emit_event(
            "task_finished",
            task_id=result.get("task_id"),
            ok=result.get("ok"),
            status=result.get("status"),
            conversation_id=result.get("conversation_id"),
            elapsed=result.get("elapsed", result.get("turn_elapsed_seconds")),
        )

    # -------------------------------------------------------------------------
    # 3. CONTROL PERSISTENTE MULTI-TURNO (STREAM-JSON)
    # -------------------------------------------------------------------------
    def get_stream_session(
        self,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> AgyStreamSession:
        with self._op_lock:
            needs_new = self._stream_session is None or not self._stream_session.is_alive
            if not needs_new and self._stream_session is not None:
                if model and model != self._stream_session.model:
                    needs_new = True
                if conversation_id and conversation_id != self._stream_session.conversation_id:
                    needs_new = True
            if needs_new:
                if self._stream_session is not None:
                    self._stream_session.close()
                self._stream_session = AgyStreamSession(
                    cwd=cwd or str(PROJECT_ROOT),
                    model=model or self._state.get("default_model") or DEFAULT_MODEL,
                    effort=effort,
                    conversation_id=conversation_id,
                )
            assert self._stream_session is not None
            return self._stream_session

    def send_turn(
        self,
        prompt: str,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
        timeout: float = 600.0,
        source: str = "tardis_stream",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Envía un turno a la sesión persistente `agy` stream-json controlada por TARDIS."""
        session = self.get_stream_session(
            cwd=cwd,
            model=model,
            effort=effort,
            conversation_id=conversation_id,
        )
        res = session.send_turn(prompt, timeout=timeout, on_event=on_event)
        res["task_id"] = f"agy_turn_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        res["source"] = source
        res["reply"] = res.get("response", "")
        res["elapsed"] = res.get("turn_elapsed_seconds", res.get("duration_seconds", 0.0))
        self._record_execution(res, prompt)
        return res

    def reset_stream_session(self) -> Dict[str, Any]:
        with self._op_lock:
            if self._stream_session is None:
                return {"ok": True, "was_running": False}
            res = self._stream_session.close()
            self._stream_session = None
            return res

    # -------------------------------------------------------------------------
    # 4. CONTINUACIÓN Y OBSERVABILIDAD DE SESIONES AGY DEL DISPOSITIVO
    # -------------------------------------------------------------------------
    def get_live_sessions(self) -> Dict[str, Any]:
        data = _load_json(LIVE_SESSIONS_FILE, {})
        if not isinstance(data, dict):
            return {"latest_conversation_id": None, "sessions": {}}
        return data

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Lista sesiones recientes de la terminal `agy` (DB SQLite + hooks en vivo)."""
        live = self.get_live_sessions().get("sessions") or {}
        sessions_by_id: Dict[str, Dict[str, Any]] = {}

        if AGY_SUMMARIES_DB.is_file():
            try:
                conn = sqlite3.connect(f"file:{AGY_SUMMARIES_DB}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cols = {r[1] for r in cur.execute("PRAGMA table_info(conversation_summaries)").fetchall()}
                order_col = "last_modified_time" if "last_modified_time" in cols else "rowid"
                rows = cur.execute(
                    f"SELECT * FROM conversation_summaries ORDER BY {order_col} DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                for row in rows:
                    d = dict(row)
                    cid = str(d.get("conversation_id") or "")
                    if not cid:
                        continue
                    transcript = AGY_BRAIN_DIR / cid / ".system_generated" / "logs" / "transcript.jsonl"
                    sessions_by_id[cid] = {
                        "conversation_id": cid,
                        "summary": d.get("summary") or d.get("title") or "",
                        "last_modified_time": d.get("last_modified_time") or "",
                        "workspace": d.get("workspace_uri") or d.get("workspace") or "",
                        "has_db": (AGY_CONVERSATIONS_DIR / f"{cid}.db").is_file(),
                        "has_transcript": transcript.is_file(),
                        "transcript_path": str(transcript) if transcript.is_file() else "",
                    }
                conn.close()
            except Exception as exc:
                logger.debug("Aviso leyendo conversation_summaries.db: %s", exc)

        for cid, linfo in live.items():
            entry = sessions_by_id.setdefault(cid, {"conversation_id": cid})
            entry["live_hook"] = True
            entry["last_event"] = linfo.get("last_event")
            entry["model_name"] = linfo.get("model_name") or entry.get("model_name", "")
            entry["workspace_paths"] = linfo.get("workspace_paths") or []
            entry["updated_at"] = linfo.get("updated_at") or entry.get("last_modified_time", "")
            if linfo.get("transcript_path"):
                entry["transcript_path"] = linfo["transcript_path"]
            if linfo.get("last_user_input"):
                entry["last_user_input"] = linfo["last_user_input"]

        result = list(sessions_by_id.values())
        result.sort(
            key=lambda s: str(s.get("updated_at") or s.get("last_modified_time") or ""),
            reverse=True,
        )
        return result[:limit]

    def get_session_transcript(self, conversation_id: str, tail: int = 30) -> Dict[str, Any]:
        """Lee los últimos pasos del transcript JSONL oficial de una sesión `agy`."""
        cid = (conversation_id or "").strip()
        if not cid:
            return {"ok": False, "error": "conversation_id requerido."}
        path = AGY_BRAIN_DIR / cid / ".system_generated" / "logs" / "transcript.jsonl"
        if not path.is_file():
            return {"ok": False, "error": f"Transcript no encontrado para {cid}", "path": str(path)}
        steps: List[Dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-int(tail):]
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    obj = json.loads(ln)
                    steps.append({
                        "step_index": obj.get("step_index"),
                        "source": obj.get("source"),
                        "type": obj.get("type"),
                        "status": obj.get("status"),
                        "created_at": obj.get("created_at"),
                        "content": str(obj.get("content") or "")[:1200],
                    })
                except json.JSONDecodeError:
                    continue
            return {"ok": True, "conversation_id": cid, "path": str(path), "count": len(steps), "steps": steps}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def continue_session(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        timeout: int = 900,
        source: str = "tardis_continue",
    ) -> Dict[str, Any]:
        """Continúa una sesión específica de la terminal `agy` o la más reciente del dispositivo."""
        cid = (conversation_id or "").strip()
        if not cid:
            live = self.get_live_sessions()
            cid = str(live.get("latest_conversation_id") or "").strip()
        if cid and not (AGY_CONVERSATIONS_DIR / f"{cid}.db").is_file():
            cid = ""
        return self.run_task(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            conversation_id=cid or None,
            continue_recent=not bool(cid),
            timeout=timeout,
            source=source,
        )

    # -------------------------------------------------------------------------
    # 5. COLA AUTÓNOMA PERSISTENTE Y DEMONIO AUTOPILOT
    # -------------------------------------------------------------------------
    def set_paused(self, paused: bool) -> Dict[str, Any]:
        with self._op_lock:
            self._state["paused"] = bool(paused)
            self._save_state()
        self._emit_event("autopilot_pause_changed", paused=bool(paused))
        return {"ok": True, "paused": bool(paused)}

    def is_paused(self) -> bool:
        latest = _load_json(STATE_FILE, {})
        if isinstance(latest, dict) and "paused" in latest:
            return bool(latest["paused"])
        return bool(self._state.get("paused", False))

    def enqueue_task(
        self,
        prompt: str,
        *,
        source: str = "tardis_autonomous",
        priority: str = "normal",
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        conversation_id: Optional[str] = None,
        continue_recent: bool = False,
        use_stream_session: bool = False,
        timeout: int = 900,
        dedup_window_s: float = 180.0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Encola de forma atómica una tarea autónoma para ejecución inmediata en `agy`."""
        _ensure_dirs()
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return {"ok": False, "error": "Prompt vacío; no se encola."}

        prio = (priority or "normal").lower().strip()
        rank = PRIORITY_RANK.get(prio, 2)
        work_dir = cwd if (cwd and os.path.isdir(cwd)) else str(PROJECT_ROOT)
        content_sha = hashlib.sha256(
            f"{work_dir}|{conversation_id or ''}|{clean_prompt}".encode("utf-8")
        ).hexdigest()

        now = time.time()
        if dedup_window_s > 0:
            for folder in (QUEUE_DIR, RUNNING_DIR, COMPLETED_DIR):
                for p in folder.glob("*.json"):
                    rec = _load_json(p)
                    if not isinstance(rec, dict):
                        continue
                    if (
                        rec.get("content_sha") == content_sha
                        and (now - float(rec.get("created_ts", 0))) < dedup_window_s
                    ):
                        return {
                            "ok": True,
                            "duplicate": True,
                            "task_id": rec.get("task_id"),
                            "status": rec.get("status"),
                        }

        task_id = f"agyq_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        record = {
            "schema": "tardis.agy_task.v1",
            "task_id": task_id,
            "created_ts": now,
            "created_iso": _now_iso(),
            "status": "QUEUED",
            "priority": prio,
            "priority_rank": rank,
            "source": source,
            "prompt": clean_prompt,
            "cwd": work_dir,
            "model": model or DEFAULT_MODEL,
            "effort": effort or "",
            "conversation_id": conversation_id or "",
            "continue_recent": bool(continue_recent),
            "use_stream_session": bool(use_stream_session),
            "timeout": int(timeout),
            "content_sha": content_sha,
            "meta": dict(meta or {}),
        }
        fname = f"{rank}_{int(now * 1000)}_{task_id}.json"
        dest = QUEUE_DIR / fname
        _atomic_write_json(dest, record, mode=0o600)
        self._emit_event("task_enqueued", task_id=task_id, source=source, priority=prio)
        return {
            "ok": True,
            "duplicate": False,
            "task_id": task_id,
            "status": "QUEUED",
            "priority": prio,
            "file": str(dest),
        }

    def list_queue(self, limit_history: int = 20) -> Dict[str, Any]:
        _ensure_dirs()

        def _scan(folder: Path, limit: Optional[int] = None, reverse: bool = False) -> List[Dict[str, Any]]:
            files = sorted(folder.glob("*.json"), key=lambda p: p.name, reverse=reverse)
            out: List[Dict[str, Any]] = []
            for p in (files[:limit] if limit else files):
                rec = _load_json(p)
                if isinstance(rec, dict):
                    out.append({
                        "task_id": rec.get("task_id"),
                        "status": rec.get("status"),
                        "priority": rec.get("priority"),
                        "source": rec.get("source"),
                        "created_iso": rec.get("created_iso"),
                        "finished_iso": rec.get("finished_iso"),
                        "prompt": str(rec.get("prompt") or "")[:240],
                        "conversation_id": rec.get("conversation_id") or (rec.get("result") or {}).get("conversation_id"),
                        "elapsed": (rec.get("result") or {}).get("elapsed"),
                        "ok": (rec.get("result") or {}).get("ok"),
                        "error": (rec.get("result") or {}).get("error", ""),
                    })
            return out

        queued = _scan(QUEUE_DIR)
        running = _scan(RUNNING_DIR)
        completed = _scan(COMPLETED_DIR, limit=limit_history, reverse=True)
        failed = _scan(FAILED_DIR, limit=limit_history, reverse=True)
        return {
            "ok": True,
            "paused": self.is_paused(),
            "counts": {
                "queued": len(queued),
                "running": len(running),
                "completed_total": len(list(COMPLETED_DIR.glob("*.json"))),
                "failed_total": len(list(FAILED_DIR.glob("*.json"))),
            },
            "queued": queued,
            "running": running,
            "recent_completed": completed,
            "recent_failed": failed,
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        _ensure_dirs()
        tid = (task_id or "").strip()
        if not tid:
            return None
        for folder in (QUEUE_DIR, RUNNING_DIR, COMPLETED_DIR, FAILED_DIR):
            for p in folder.glob(f"*{tid}*.json"):
                rec = _load_json(p)
                if isinstance(rec, dict) and rec.get("task_id") == tid:
                    return rec
        return None

    def ingest_autonomous_directives(self) -> int:
        """
        Promueve directivas explícitamente marcadas como `AUTONOMOUS_READY` en
        `~/vw-control/antigravity_bridge/pending_directives.json` hacia la cola `agy`.
        """
        directives_file = APPDATA_DIR / "antigravity_bridge" / "pending_directives.json"
        data = _load_json(directives_file)
        if not isinstance(data, dict):
            return 0
        directives = data.get("directives") or []
        promoted = 0
        modified = False
        for d in directives:
            if not isinstance(d, dict):
                continue
            if d.get("status") != "AUTONOMOUS_READY":
                continue
            prompt = (
                f"[DIRECTIVA AUTÓNOMA TARDIS → AGY]\n"
                f"Título: {d.get('title', 'Mejora autónoma')}\n"
                f"Archivo objetivo: {d.get('target_file', '')}\n"
                f"Problema: {d.get('problem', '')}\n"
                f"Propuesta técnica: {d.get('proposed_action', '')}\n"
                f"Verificación: {d.get('verification_cmd', '')}\n\n"
                "Aplica la solución completa de forma autónoma y verifica con pruebas."
            )
            enq = self.enqueue_task(
                prompt,
                source="antigravity_bridge_directive",
                priority="high" if str(d.get("severity", "")).upper() in ("HIGH", "ALTA", "CRITICAL", "CRITICA") else "normal",
                dedup_window_s=3600.0,
                meta={"directive_id": d.get("id"), "target_file": d.get("target_file")},
            )
            if enq.get("ok"):
                d["status"] = "AUTONOMOUS_QUEUED"
                d["agy_task_id"] = enq.get("task_id")
                d["dispatched_at"] = _now_iso()
                promoted += 1
                modified = True
        if modified:
            try:
                _atomic_write_json(directives_file, data, mode=0o600)
            except Exception:
                pass
        return promoted

    def _notify_tardis_bridge(self, record: Dict[str, Any], result: Dict[str, Any]) -> None:
        try:
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
            import antigravity_bridge
            bridge = antigravity_bridge.get_bridge()
            status_tag = "OK" if result.get("ok") else f"ERROR ({result.get('status')})"
            summary = str(result.get("response") or result.get("error") or "")[:600]
            bridge.post_dialogue_message(
                sender="TARDIS-AGY-AUTOPILOT",
                text=(
                    f"[AGY AUTÓNOMO :: {status_tag}] task={record.get('task_id')} "
                    f"source={record.get('source')} cid={result.get('conversation_id')}\n{summary}"
                ),
                role="assistant",
                category="AGY_AUTONOMOUS_EXECUTION",
            )
        except Exception:
            pass

    def process_next_task(self) -> Optional[Dict[str, Any]]:
        """Reclama atómicamente la siguiente tarea en cola y la ejecuta en `agy`."""
        _ensure_dirs()
        if self.is_paused():
            return None

        self.ingest_autonomous_directives()

        queued_files = sorted(QUEUE_DIR.glob("*.json"), key=lambda p: p.name)
        if not queued_files:
            return None

        src_file = queued_files[0]
        running_file = RUNNING_DIR / src_file.name
        try:
            os.replace(src_file, running_file)
        except OSError:
            return None

        record = _load_json(running_file)
        if not isinstance(record, dict):
            running_file.unlink(missing_ok=True)
            return None

        record["status"] = "RUNNING"
        record["started_ts"] = time.time()
        record["started_iso"] = _now_iso()
        _atomic_write_json(running_file, record, mode=0o600)

        try:
            if record.get("use_stream_session"):
                result = self.send_turn(
                    record["prompt"],
                    cwd=record.get("cwd") or str(PROJECT_ROOT),
                    model=record.get("model") or DEFAULT_MODEL,
                    effort=record.get("effort") or None,
                    conversation_id=record.get("conversation_id") or None,
                    timeout=float(record.get("timeout") or 900),
                    source=record.get("source") or "agy_queue_stream",
                )
            else:
                result = self.run_task(
                    record["prompt"],
                    cwd=record.get("cwd") or str(PROJECT_ROOT),
                    model=record.get("model") or DEFAULT_MODEL,
                    effort=record.get("effort") or None,
                    conversation_id=record.get("conversation_id") or None,
                    continue_recent=bool(record.get("continue_recent", False)),
                    timeout=int(record.get("timeout") or 900),
                    source=record.get("source") or "agy_queue",
                    fallback_to_local=True,
                )
        except Exception as exc:
            result = {"ok": False, "status": "EXCEPTION", "error": str(exc)}

        record["finished_ts"] = time.time()
        record["finished_iso"] = _now_iso()
        record["status"] = "COMPLETED" if result.get("ok") else "FAILED"
        record["result"] = result

        dest_dir = COMPLETED_DIR if result.get("ok") else FAILED_DIR
        dest_file = dest_dir / running_file.name
        _atomic_write_json(dest_file, record, mode=0o600)
        running_file.unlink(missing_ok=True)

        self._notify_tardis_bridge(record, result)
        return record

    def _recover_stale_running(self) -> int:
        """Devuelve a la cola tareas huérfanas de un reinicio anterior del demonio."""
        recovered = 0
        for p in RUNNING_DIR.glob("*.json"):
            try:
                rec = _load_json(p)
                if isinstance(rec, dict):
                    rec["status"] = "QUEUED"
                    rec["recovered_at"] = _now_iso()
                    _atomic_write_json(QUEUE_DIR / p.name, rec, mode=0o600)
                    p.unlink(missing_ok=True)
                    recovered += 1
            except Exception:
                pass
        return recovered

    def run_daemon(self, interval: float = 10.0) -> int:
        """Bucle de demonio systemd 24/7 con bloqueo exclusivo y circuit breaker."""
        _ensure_dirs()
        lock_fh = LOCK_FILE.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Otra instancia de tardis-agy-autopilot ya está en ejecución.")
            return 1

        def _handle_signal(signum, _frame):
            logger.info("Señal %s recibida; deteniendo tardis-agy-autopilot con gracia...", signum)
            self._stop_daemon.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        recovered = self._recover_stale_running()
        if recovered:
            logger.info("Recuperadas %d tareas interrumpidas hacia la cola.", recovered)

        self._state["daemon_pid"] = os.getpid()
        self._state["daemon_heartbeat_ts"] = time.time()
        self._state["daemon_heartbeat_iso"] = _now_iso()
        self._save_state()
        self._emit_event("daemon_started", pid=os.getpid(), interval=interval)
        logger.info("tardis-agy-autopilot activo (PID=%d, interval=%.1fs)", os.getpid(), interval)

        last_terminal_sweep = 0.0
        terminal_sweep_interval = max(60.0, float(os.environ.get("TARDIS_CONTINUATOR_SWEEP_SEC", "180")))

        try:
            while not self._stop_daemon.is_set():
                self._state["daemon_pid"] = os.getpid()
                self._state["daemon_heartbeat_ts"] = time.time()
                self._state["daemon_heartbeat_iso"] = _now_iso()
                self._save_state()

                if not self.is_paused():
                    consec_fail = int(self._state.get("consecutive_failures", 0))
                    if consec_fail >= 5:
                        backoff = min(300.0, 15.0 * consec_fail)
                        logger.warning("Circuit breaker activo (%d fallos consecutivos); pausa %.0fs.", consec_fail, backoff)
                        self._stop_daemon.wait(backoff)
                        with self._op_lock:
                            self._state["consecutive_failures"] = 0
                            self._save_state()
                        continue

                    processed = self.process_next_task()
                    if processed is not None:
                        # Continuar inmediatamente si quedan más tareas en cola
                        continue

                    # Barrido autónomo multi-terminal (AGY · FTL · OpenCode) cuando la cola está libre
                    now_ts = time.time()
                    if (now_ts - last_terminal_sweep) >= terminal_sweep_interval:
                        last_terminal_sweep = now_ts
                        try:
                            from core.ftl_terminal_continuator import get_ftl_terminal_continuator
                            sw = get_ftl_terminal_continuator().sweep_and_enqueue(max_items=2)
                            if sw.get("dispatched", 0) > 0:
                                logger.info(
                                    "Barrido multi-terminal despachó %d continuaciones (reconciliadas=%d).",
                                    sw.get("dispatched", 0),
                                    sw.get("initial_reconciled", 0),
                                )
                                continue
                        except Exception as exc_sw:
                            logger.debug("Aviso en barrido multi-terminal: %s", exc_sw)

                self._stop_daemon.wait(max(2.0, float(interval)))
        finally:
            self.reset_stream_session()
            self._emit_event("daemon_stopped", pid=os.getpid())
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                lock_fh.close()
            except Exception:
                pass
        return 0

    # -------------------------------------------------------------------------
    # 6. ESTADO HOLÍSTICO
    # -------------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        self._state = self._load_state()
        perms = self.verify_permissions(run_live_probe=False)
        q = self.list_queue(limit_history=8)
        live = self.get_live_sessions()

        daemon_pid = self._state.get("daemon_pid")
        daemon_alive = False
        if isinstance(daemon_pid, int) and daemon_pid > 1:
            try:
                os.kill(daemon_pid, 0)
                daemon_alive = True
            except OSError:
                daemon_alive = False

        agy_version = ""
        try:
            v = subprocess.run(
                [_resolve_agy_bin(prefer_real=True), "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
            )
            agy_version = (v.stdout or v.stderr or "").strip()
        except Exception:
            pass

        return {
            "ok": True,
            "schema": "tardis.agy_control.v1",
            "autonomous_control_enabled": True,
            "zero_prompt_verified": perms.get("ok", False),
            "agy_version": agy_version,
            "agy_bin": _resolve_agy_bin(prefer_real=False),
            "permissions": perms,
            "daemon": {
                "alive": daemon_alive,
                "pid": daemon_pid if daemon_alive else None,
                "paused": q.get("paused", False),
                "heartbeat_iso": self._state.get("daemon_heartbeat_iso"),
            },
            "stream_session": self._stream_session.info() if self._stream_session else {"alive": False},
            "queue": q["counts"],
            "stats": {
                "tasks_executed": self._state.get("tasks_executed", 0),
                "tasks_succeeded": self._state.get("tasks_succeeded", 0),
                "tasks_failed": self._state.get("tasks_failed", 0),
                "last_conversation_id": self._state.get("last_conversation_id"),
                "last_task_id": self._state.get("last_task_id"),
                "last_task_at": self._state.get("last_task_at"),
            },
            "latest_live_conversation_id": live.get("latest_conversation_id"),
            "control_dir": str(CONTROL_DIR),
            "iso": _now_iso(),
        }


def get_tardis_agy_controller() -> TardisAgyController:
    return TardisAgyController.get_instance()
