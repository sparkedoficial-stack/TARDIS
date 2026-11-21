"""
core/tardis_voice_program.py - Enrutador Soberano del Comando de Voz «programa»
=================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL
Arquitecto: El Arquitecto (₪)

DIRECTIVA SOBERANA:
"En las llamadas o contactos de voz, al decir el comando programa, TARDIS creará
 la función con FTL sin importar en qué micrófono sea."

ARQUITECTURA:
  1. DETECCIÓN MULTI-MICRÓFONO: el mismo parser se aplica a cualquier transcripción
     (llamada en vivo de Telegram, nota de voz, cámara C310, micrófono local, API).
  2. PARSER TOLERANTE: reconoce «programa», «programame», «programá», errores
     típicos del STT («progama») y vocativos («TARDIS, programa...»). Exige que el
     comando abra la locución para no confundirlo con la palabra «programa» usada
     como sustantivo.
  3. DESPACHO AUTÓNOMO: la orden restante se envía en segundo plano al ingeniero
     FTL (~/.ftl/ftl_cli.py), que crea, valida e integra la función Python.
  4. RESILIENCIA: si FTL está ocupado o no disponible, el motor de funciones
     dinámicas de TARDIS sintetiza la función como respaldo, sin perder la orden.
  5. COLA ÚNICA: todos los micrófonos comparten una cola serial y un candado
     `flock` entre procesos (C310, API, Telegram) para que FTL nunca reciba dos
     trabajos simultáneos desde el subsistema de voz.
  6. TRAZABILIDAD: cada orden y su resultado se registran en
     `data/voice_program_commands.jsonl`, en la Bóveda de Memoria y en SYNC_HUB.

USO:
    from core.tardis_voice_program import get_voice_program_router

    routed = get_voice_program_router().handle(
        transcript,
        channel="telegram_live_call",
        source="micrófono del Arquitecto",
        chat_id=chat_id,
    )
    if routed:
        speak(routed["reply"])
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:  # Serialización global entre procesos (Linux)
    import fcntl
except Exception:  # noqa: BLE001
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger("TARDIS.VoiceProgram")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EVENT_LOG = DATA_DIR / "voice_program_commands.jsonl"
FTL_LOCK_PATH = DATA_DIR / "ftl_voice_program.lock"

MAX_GOAL_CHARS = 4000
FTL_BUSY_WAIT_SEC = float(os.environ.get("TARDIS_VOICE_PROGRAM_FTL_WAIT_SEC", "300"))
DYNAMIC_JOB_WAIT_SEC = float(os.environ.get("TARDIS_VOICE_PROGRAM_DYNAMIC_WAIT_SEC", "900"))
FTL_AUTOFUNC_TIMEOUT_SEC = float(os.environ.get("TARDIS_VOICE_PROGRAM_AUTOFUNC_TIMEOUT_SEC", "1200"))
FTL_LOCK_WAIT_SEC = float(os.environ.get("TARDIS_VOICE_PROGRAM_LOCK_WAIT_SEC", "1800"))
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@contextlib.contextmanager
def ftl_serialization_lock(wait_sec: float = FTL_LOCK_WAIT_SEC, on_wait=None):
    """
    Candado exclusivo entre procesos para que FTL nunca reciba dos órdenes de
    voz simultáneas (C310, servicio TARDIS, Telegram, etc. son procesos
    distintos). Si el candado no está disponible se continúa sin bloquear.
    """
    if fcntl is None:
        yield True
        return

    handle = None
    acquired = False
    try:
        try:
            handle = FTL_LOCK_PATH.open("a+", encoding="utf-8")
        except OSError as exc:
            logger.debug("Candado FTL no disponible (%s); se continúa sin él.", exc)
            yield True
            return
        deadline = time.time() + max(0.0, wait_sec)
        notified = False
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if time.time() >= deadline:
                    break
                if not notified and on_wait is not None:
                    try:
                        on_wait()
                    except Exception:  # noqa: BLE001
                        pass
                    notified = True
                time.sleep(1.0)
        yield acquired
    finally:
        if handle is not None:
            try:
                if acquired:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


# Palabras que pueden preceder al comando sin romper la detección.
# Incluye vocativos, restos habituales de la wake word y muletillas de habla.
_PREFIX_NOISE = {
    "tardis", "tardes", "tardiz",
    "oye", "hola", "hey", "ey", "eh",
    "ok", "okay", "vale", "ahora",
    "por", "favor", "porfa", "porfavor",
    "escucha", "atiende", "asistente",
    "estas", "esta", "ahi", "alli", "alla", "aqui", "hay",
}

# Formas exactas del comando.
_COMMAND_WORDS = {"programa", "programame", "program", "programme"}

# Formas que NUNCA deben confundirse con el comando.
_NOT_COMMANDS = {
    "programas", "programada", "programado", "programadas", "programados",
    "programacion", "programando", "programar", "programaron", "programaba",
    "programita", "programon",
}

# Cortesías que pueden seguir al comando («programa, por favor, ...»).
_COURTESY = {"porfa", "porfavor", "please"}

# Artículos y sustantivos de relleno tras el comando («programa UNA FUNCIÓN que...»).
_ARTICLES = {"la", "una", "un", "el", "los", "las", "mi", "nueva", "nuevo"}
_FUNCTION_WORDS = {
    "funcion", "funciones", "herramienta", "herramientas",
    "tool", "tools", "modulo", "modulos", "script", "scripts",
    "capacidad", "capacidades", "programa", "programita",
}

_EDGE_PUNCT = " \t\r\n:;,.-–—¡!¿?\"'“”‘’()[]{}"


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, sin signos: tokens separados por un espacio."""
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9ñ]+", " ", text)
    return " ".join(text.split())


def _edit_distance(a: str, b: str, max_dist: int = 1) -> int:
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            )
        previous = current
    return previous[-1]


_COURTESY_EDGE_RE = re.compile(
    r"^(?:por\s+favor|porfa|porfavor|please)[\s,]+|[\s,]+(?:por\s+favor|porfa|porfavor|please)$",
    re.IGNORECASE,
)


def _clean_goal(raw_tokens: list[str]) -> str:
    goal = " ".join(raw_tokens).strip()
    goal = goal.strip(_EDGE_PUNCT)
    goal = re.sub(r"\s+", " ", goal)
    # Quita comillas envolventes que a veces añade el STT.
    if len(goal) >= 2 and goal[0] == goal[-1] and goal[0] in "\"'“”":
        goal = goal[1:-1].strip()
    # Cortesías al inicio o al final que no forman parte de la orden.
    previous = None
    while goal and goal != previous:
        previous = goal
        goal = _COURTESY_EDGE_RE.sub("", goal).strip(_EDGE_PUNCT)
    return goal[:MAX_GOAL_CHARS]


@dataclass
class ProgramCommand:
    """Resultado del parser de voz."""

    raw: str
    goal: str
    command_token: str
    prefix: str = ""
    approximate: bool = False

    @property
    def has_goal(self) -> bool:
        return bool(self.goal.strip())


def parse_program_command(text: str) -> Optional[ProgramCommand]:
    """
    Detecta el comando «programa» al inicio de la locución (tras vocativos) y
    devuelve el objetivo dictado. Retorna None si no es una orden de programación.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    norm_tokens = normalize_text(raw).split()
    raw_tokens = raw.split()
    if not norm_tokens or len(norm_tokens) != len(raw_tokens):
        # El tokenizador normal puede colapsar signos sueltos; se usa una
        # tokenización alineada para extraer el objetivo con acentos intactos.
        raw_tokens = re.findall(r"\S+", raw)
        norm_tokens = [normalize_text(tok) for tok in raw_tokens]
        norm_tokens = [tok for tok in norm_tokens if tok]
        if len(norm_tokens) != len(raw_tokens):
            # Reconstrucción conservadora: se normaliza la frase completa y se
            # separa el objetivo por número de palabras desde el final.
            norm_tokens = normalize_text(raw).split()
            raw_tokens = raw.split()[-len(norm_tokens):]

    index = 0
    while index < len(norm_tokens) and norm_tokens[index] in _PREFIX_NOISE:
        index += 1
    if index >= len(norm_tokens):
        return None

    token = norm_tokens[index]
    if token in _NOT_COMMANDS:
        return None

    approximate = False
    if token not in _COMMAND_WORDS:
        # Tolerancia a errores leves de STT: progama, programa, prgrama...
        if (
            7 <= len(token) <= 9
            and token not in _NOT_COMMANDS
            and _edit_distance(token, "programa", 1) <= 1
        ):
            approximate = True
        else:
            return None

    prefix = " ".join(raw_tokens[:index]).strip(_EDGE_PUNCT)
    cursor = index + 1

    # «programa me ...» / «programame ...»: el pronombre no forma parte del objetivo.
    if cursor < len(norm_tokens) and norm_tokens[cursor] == "me":
        cursor += 1

    # «programa, por favor, ...»: la cortesía no forma parte del objetivo.
    if (
        cursor + 1 < len(norm_tokens)
        and norm_tokens[cursor] == "por"
        and norm_tokens[cursor + 1] == "favor"
    ):
        cursor += 2
    elif cursor < len(norm_tokens) and norm_tokens[cursor] in _COURTESY:
        cursor += 1

    # Consume relleno: «programa una nueva función de...» -> «de...».
    article_budget = 2
    while (
        cursor < len(norm_tokens)
        and norm_tokens[cursor] in _ARTICLES
        and article_budget > 0
    ):
        cursor += 1
        article_budget -= 1
    if cursor < len(norm_tokens) and norm_tokens[cursor] in _FUNCTION_WORDS:
        cursor += 1

    goal = _clean_goal(raw_tokens[cursor:])
    return ProgramCommand(
        raw=raw,
        goal=goal,
        command_token=token,
        prefix=prefix,
        approximate=approximate,
    )


def is_program_command(text: str) -> bool:
    """Atajo booleano para los centinelas de audio."""
    return parse_program_command(text) is not None


def _short_goal(goal: str, limit: int = 140) -> str:
    goal = re.sub(r"\s+", " ", (goal or "").strip())
    if len(goal) <= limit:
        return goal
    cut = goal[:limit]
    pos = cut.rfind(" ")
    if pos > int(limit * 0.6):
        cut = cut[:pos]
    return cut.rstrip(" ,;:.") + "…"


@dataclass
class ProgramJob:
    job_id: str
    goal: str
    raw_text: str
    channel: str
    source: str
    chat_id: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    status: str = "queued"  # queued | running | completed | failed
    engine: str = "FTL"
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "goal": self.goal,
            "channel": self.channel,
            "source": self.source,
            "chat_id": self.chat_id,
            "status": self.status,
            "engine": self.engine,
            "created_at": self.created_at,
            "created_iso": datetime.fromtimestamp(self.created_at).isoformat(timespec="seconds"),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result,
        }


class VoiceProgramRouter:
    """Cola única y multi-micrófono para órdenes de voz «programa»."""

    _instance: Optional["VoiceProgramRouter"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "VoiceProgramRouter":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._queue: "queue.Queue[ProgramJob]" = queue.Queue()
        self._lock = threading.Lock()
        self._jobs: Dict[str, ProgramJob] = {}
        self._active_job_id: Optional[str] = None
        self._worker: Optional[threading.Thread] = None
        self._counter = 0
        self.total_dispatched = 0
        self.total_completed = 0
        self.total_failed = 0

    # -- API pública -------------------------------------------------------

    def handle(
        self,
        text: str,
        *,
        channel: str,
        source: str = "",
        chat_id: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Examina una transcripción de cualquier micrófono. Si contiene el comando
        «programa», encola la creación de la función y devuelve la respuesta
        hablada. Si no es el comando, devuelve None sin efectos secundarios.
        """
        command = parse_program_command(text)
        if command is None:
            return None

        if not command.has_goal:
            reply = (
                "A la orden, Arquitecto. Dime qué función deseas que programe; "
                "por ejemplo: programa una función que resuma mis correos."
            )
            self._log_event(
                {
                    "event": "missing_goal",
                    "channel": channel,
                    "source": source,
                    "raw": command.raw,
                }
            )
            return {
                "handled": True,
                "matched": True,
                "dispatched": False,
                "goal": "",
                "reply": reply,
                "channel": channel,
            }

        job = self._enqueue(command, channel=channel, source=source, chat_id=chat_id, metadata=metadata or {})
        pending = self._queue.qsize()
        reply = (
            f"A la orden, Arquitecto. FTL ya está creando la función: {_short_goal(command.goal)}. "
            "Quedará validada e integrada en unos minutos."
        )
        if pending > 1:
            reply = (
                f"A la orden. FTL creará la función: {_short_goal(command.goal)}. "
                f"Hay {pending - 1} órdenes más en cola; avanzarán en secuencia."
            )
        return {
            "handled": True,
            "matched": True,
            "dispatched": True,
            "goal": command.goal,
            "job_id": job.job_id,
            "engine": "FTL",
            "reply": reply,
            "channel": channel,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            recent = sorted(
                self._jobs.values(), key=lambda job: job.created_at, reverse=True
            )[:10]
            return {
                "ok": True,
                "queue_size": self._queue.qsize(),
                "active_job": active.to_dict() if active else None,
                "total_dispatched": self.total_dispatched,
                "total_completed": self.total_completed,
                "total_failed": self.total_failed,
                "recent": [job.to_dict() for job in recent],
                "worker_alive": bool(self._worker and self._worker.is_alive()),
            }

    # -- Cola y worker -----------------------------------------------------

    def _enqueue(
        self,
        command: ProgramCommand,
        *,
        channel: str,
        source: str,
        chat_id: Optional[Any],
        metadata: Dict[str, Any],
    ) -> ProgramJob:
        with self._lock:
            self._counter += 1
            job_id = f"vprog_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._counter:03d}"
            job = ProgramJob(
                job_id=job_id,
                goal=command.goal,
                raw_text=command.raw,
                channel=channel,
                source=source,
                chat_id=chat_id,
                metadata=dict(metadata),
            )
            self._jobs[job_id] = job
            self.total_dispatched += 1
            # Retención acotada del historial en memoria.
            if len(self._jobs) > 200:
                for old in sorted(self._jobs.values(), key=lambda j: j.created_at)[:50]:
                    if old.status in ("completed", "failed"):
                        self._jobs.pop(old.job_id, None)

        self._ensure_worker()
        self._queue.put(job)
        self._log_event(
            {
                "event": "dispatched",
                "job_id": job.job_id,
                "goal": job.goal,
                "raw": job.raw_text,
                "channel": channel,
                "source": source,
                "chat_id": chat_id,
                "approximate": command.approximate,
                "queue_size": self._queue.qsize(),
            }
        )
        logger.info(
            "🎙️➡️🧬 [VOICE-PROGRAM] Orden encolada %s · canal=%s · meta=%r",
            job.job_id, channel, job.goal[:120],
        )
        return job

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="TARDIS-VoiceProgramWorker",
                daemon=True,
            )
            self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                with self._lock:
                    self._active_job_id = job.job_id
                    job.status = "running"
                    job.started_at = time.time()
                logger.info("🧬 [VOICE-PROGRAM] Ejecutando %s con FTL...", job.job_id)
                self._start_progress(job)
                self._process_job(job)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Fallo no controlado en worker de voz: %s", exc)
                job.status = "failed"
                job.error = str(exc)
                self._finish_job(job)
            finally:
                with self._lock:
                    self._active_job_id = None
                self._queue.task_done()

    # -- Ejecución FTL -----------------------------------------------------

    @staticmethod
    def _build_ftl_prompt(job: ProgramJob) -> str:
        source = job.source or "micrófono no identificado"
        return (
            "[COMANDO DE VOZ SOBERANO :: PROGRAMA]\n"
            f"Canal de origen: {job.channel}\n"
            f"Micrófono/fuente: {source}\n"
            f"Orden literal del Arquitecto (₪): «{job.goal}»\n\n"
            "MISIÓN OBLIGATORIA (100% autónoma, sin pedir confirmación):\n"
            "1. Diseña e implementa una función Python completa, autosuficiente y robusta "
            "que cumpla exactamente la orden dictada.\n"
            "2. Guárdala como herramienta dinámica en `dynamic_tools/` con nombre descriptivo "
            "en snake_case y expón `run(args: dict) -> dict` con docstring y manejo de errores.\n"
            "3. Si la orden exige integrarse en otro módulo del sistema, realiza la integración "
            "mínima, segura y verificable.\n"
            "4. Valida la sintaxis con `ast.parse` y ejecuta una prueba de humo no destructiva.\n"
            "5. No modifiques secretos, credenciales ni datos personales. No dejes TODOs sin resolver.\n"
            "6. Al finalizar, responde en una sola línea con la función creada y su ruta.\n"
        )

    def _wait_ftl_free(self, max_wait: float) -> bool:
        """Espera a que el ingeniero FTL no tenga un trabajo activo."""
        from core.tardis_ftl_engineer import get_ftl_engineer

        deadline = time.time() + max_wait
        while time.time() < deadline:
            status = get_ftl_engineer().get_status()
            if not status.get("active_job"):
                return True
            logger.info(
                "⏳ [VOICE-PROGRAM] FTL ocupado con %s; la orden espera en cola.",
                (status.get("active_job") or {}).get("job_id"),
            )
            time.sleep(5.0)
        return False

    def _process_job(self, job: ProgramJob) -> None:
        try:
            job.engine = "FTL"
            self._log_event(
                {
                    "event": "ftl_started",
                    "job_id": job.job_id,
                    "goal": job.goal,
                    "channel": job.channel,
                    "source": job.source,
                }
            )

            self._note_progress(job, "FTL recibió la orden; iniciando autoprogramación soberana")

            def _on_ftl_wait() -> None:
                logger.info(
                    "⏳ [VOICE-PROGRAM] Otro proceso está usando FTL; %s espera su turno.",
                    job.job_id,
                )
                self._note_progress(job, "FTL ocupado; la orden espera turno en la cola")
                self._log_event(
                    {
                        "event": "ftl_waiting",
                        "job_id": job.job_id,
                        "goal": job.goal,
                        "channel": job.channel,
                    }
                )

            with ftl_serialization_lock(on_wait=_on_ftl_wait) as lock_acquired:
                if not lock_acquired:
                    logger.warning(
                        "⚠️ [VOICE-PROGRAM] Candado FTL no disponible tras %.0fs; "
                        "se intenta la síntesis de todos modos (%s).",
                        FTL_LOCK_WAIT_SEC, job.job_id,
                    )
                res = self._run_ftl(job)
            ok = bool(res.get("ok"))
            job.result = res
            job.status = "completed" if ok else "failed"
            job.error = "" if ok else str(res.get("error") or res.get("status") or "FTL no completó la función")
            if ok:
                self._reload_dynamic_tools(res)
            else:
                logger.warning(
                    "⚠️ [VOICE-PROGRAM] FTL falló para %s (%s). Activando respaldo dinámico.",
                    job.job_id, job.error,
                )
                self._run_dynamic_fallback(job)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error ejecutando FTL para %s: %s", job.job_id, exc)
            job.error = str(exc)
            try:
                self._run_dynamic_fallback(job)
            except Exception as exc2:  # noqa: BLE001
                logger.exception("También falló el respaldo dinámico: %s", exc2)
                job.status = "failed"
                job.error = f"{exc} · respaldo: {exc2}"
        finally:
            job.finished_at = time.time()
            if job.status == "running":
                job.status = "failed" if job.error else "completed"
            self._finish_job(job)

    def _run_ftl(self, job: ProgramJob) -> Dict[str, Any]:
        """
        Ruta principal: FTL `--autofunc` (síntesis canónica de herramienta).
        Respaldo 1: ingeniero FTL sobre el codebase.
        Respaldo 2 (en _process_job): motor dinámico de TARDIS.
        """
        autofunc = self._run_ftl_autofunc(job)
        if autofunc.get("ok"):
            return autofunc

        logger.warning(
            "⚠️ [VOICE-PROGRAM] FTL --autofunc no completó %s: %s. Probando ingeniero FTL.",
            job.job_id, autofunc.get("error"),
        )
        self._note_progress(job, "Autofunc no completó; activando ingeniero FTL sobre el codebase")
        engineer_res = self._run_ftl_engineer(job)
        if engineer_res.get("ok"):
            engineer_res["autofunc"] = autofunc
            return engineer_res

        return {
            **engineer_res,
            "autofunc": autofunc,
            "error": (
                f"autofunc: {autofunc.get('error') or 'sin resultado'} · "
                f"engineer: {engineer_res.get('error') or 'sin resultado'}"
            ),
        }

    @staticmethod
    def _ftl_cli_path() -> Optional[Path]:
        """Localiza el CLI de FTL usado por el sistema."""
        candidates = [
            Path.home() / ".ftl" / "ftl_cli.py",
            Path("/home/m11/.ftl/ftl_cli.py"),
            Path("/home/m11/.ftl/ftl_cli.py"),
        ]
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _run_ftl_autofunc(self, job: ProgramJob) -> Dict[str, Any]:
        """Crea la función con el autoprogramador nativo de FTL (`--autofunc`)."""
        ftl_cli = self._ftl_cli_path()
        if not ftl_cli:
            return {"ok": False, "error": "No se encontró ~/.ftl/ftl_cli.py"}

        cmd = [sys.executable, str(ftl_cli), "--autofunc", job.goal]
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "TERM": "dumb",
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
                "COLUMNS": "120",
                "CLAUDE_CODE_SKIP_PERMISSIONS": "1",
            }
        )
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=FTL_AUTOFUNC_TIMEOUT_SEC,
            )
            raw = proc.stdout or ""
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            raw = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            cleaned = self._clean_ftl_output(raw)
            return {
                "ok": False,
                "engine": "FTL-autofunc",
                "error": f"Tiempo límite excedido ({FTL_AUTOFUNC_TIMEOUT_SEC:.0f}s)",
                "output_preview": cleaned[-2000:],
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "engine": "FTL-autofunc", "error": str(exc)}

        cleaned = self._clean_ftl_output(raw)
        low = cleaned.lower()
        failed = "error sintetizando herramienta" in low
        succeeded = (
            "herramienta dinámica sintetizada con éxito" in low
            or ("dinámica sintetizada" in low and "módulo:" in low)
        )
        module_match = re.search(r"Módulo:\s*([^\s(]+)", cleaned)
        file_match = re.search(r"Archivo:\s*(\S+)", cleaned)
        module_name = module_match.group(1).strip() if module_match else ""
        file_path = file_match.group(1).strip() if file_match else ""

        result = {
            "ok": bool(succeeded and not failed),
            "engine": "FTL-autofunc",
            "returncode": returncode,
            "duration_sec": round(time.time() - started, 2),
            "module_name": module_name,
            "file_path": file_path,
            "files_changed": [file_path] if file_path else [],
            "output_preview": cleaned[-3000:],
        }
        if not result["ok"]:
            result["error"] = (
                "FTL no confirmó la síntesis de la herramienta"
                if not failed
                else "El autoprogramador FTL reportó un error"
            )
        return result

    @staticmethod
    def _clean_ftl_output(raw: str) -> str:
        text = _ANSI_RE.sub("", raw or "")
        text = text.replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Elimina barras de progreso huérfanas manteniendo los mensajes útiles.
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")):
                continue
            lines.append(stripped)
        return "\n".join(lines)

    def _run_ftl_engineer(self, job: ProgramJob) -> Dict[str, Any]:
        """Respaldo: ingeniero FTL que modifica el codebase del proyecto."""
        from core.tardis_ftl_engineer import get_ftl_engineer

        engineer = get_ftl_engineer()
        if not engineer.is_ftl_available():
            return {"ok": False, "engine": "FTL-engineer", "error": "FTL no disponible en el sistema"}

        if not self._wait_ftl_free(FTL_BUSY_WAIT_SEC):
            return {
                "ok": False,
                "engine": "FTL-engineer",
                "error": "FTL permaneció ocupado; se usa el respaldo dinámico",
            }

        prompt = self._build_ftl_prompt(job)
        res = engineer.execute_software_creation(
            prompt=prompt,
            mode="auto",
            background=False,
            meta={
                "origin": "tardis_voice_program",
                "channel": job.channel,
                "source": job.source,
                "voice_goal": job.goal,
                "job_id": job.job_id,
                "chat_id": job.chat_id,
                "progress_job_id": job.job_id,
            },
        )
        res.setdefault("engine", "FTL-engineer")
        return res

    def _run_dynamic_fallback(self, job: ProgramJob) -> None:
        """Crea la función con el motor dinámico si FTL no puede hacerlo."""
        logger.warning("🧬 [VOICE-PROGRAM] Respaldo dinámico para %s", job.job_id)
        self._note_progress(job, "Respaldo: motor dinámico de TARDIS sintetizando la función")
        job.engine = "TARDIS-dynamic-fallback"
        from core.tardis_dynamic_function_engine import get_dynamic_function_engine

        engine = get_dynamic_function_engine()
        func_name = engine._generate_function_name(job.goal)
        dyn_job_id = engine.dispatch_background_research_and_programming(
            func_name=func_name,
            goal=job.goal,
            sync_hub_client_id=f"voice_program_{job.channel}",
        )
        deadline = time.time() + DYNAMIC_JOB_WAIT_SEC
        final: Dict[str, Any] = {}
        while time.time() < deadline:
            with engine._jobs_lock:  # noqa: SLF001 - estado interno del motor soberano
                final = dict(engine._active_jobs.get(dyn_job_id) or {})
            if final.get("status") in ("COMPLETED", "FAILED"):
                break
            time.sleep(2.0)

        job.result = {
            "ok": final.get("status") == "COMPLETED",
            "engine": "TARDIS-dynamic-function-engine",
            "dynamic_job_id": dyn_job_id,
            "function": func_name,
            "dynamic_status": final.get("status", "RUNNING"),
            "error": final.get("error", ""),
            "result": final.get("result", {}),
            "execution": final.get("execution", {}),
        }
        if job.result["ok"]:
            job.status = "completed"
            job.error = ""
        else:
            job.status = "failed"
            job.error = str(
                final.get("error")
                or f"El motor dinámico terminó en estado {final.get('status', 'desconocido')}"
            )

    def _reload_dynamic_tools(self, res: Dict[str, Any]) -> None:
        changed = [str(path) for path in (res.get("files_changed") or [])]
        if not any("dynamic_tools" in path for path in changed):
            return
        try:
            from core.tardis_dynamic_function_engine import get_dynamic_function_engine

            get_dynamic_function_engine()._preload_dynamic_tools()  # noqa: SLF001
            logger.info("♻️ [VOICE-PROGRAM] dynamic_tools recargado tras crear la función FTL.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo recargar dynamic_tools: %s", exc)

    # -- Cierre y notificación --------------------------------------------

    def _finish_job(self, job: ProgramJob) -> None:
        with self._lock:
            if job.status == "completed":
                self.total_completed += 1
            elif job.status == "failed":
                self.total_failed += 1

        self._log_event(
            {
                "event": "finished",
                "job_id": job.job_id,
                "goal": job.goal,
                "channel": job.channel,
                "source": job.source,
                "status": job.status,
                "engine": job.engine,
                "duration_sec": round(max(0.0, job.finished_at - job.started_at), 2),
                "error": job.error,
                "files_changed": (job.result or {}).get("files_changed", []),
            }
        )
        if job.status == "completed":
            logger.info(
                "✅ [VOICE-PROGRAM] Función creada por %s para «%s» en %.1fs.",
                job.engine, _short_goal(job.goal, 80), job.finished_at - job.started_at,
            )
        else:
            logger.error(
                "❌ [VOICE-PROGRAM] Orden %s falló: %s", job.job_id, job.error,
            )

        self._record_in_vault(job)
        self._sync_hub(job)
        self._finish_progress(job)
        self._notify_telegram(job)

    def _record_in_vault(self, job: ProgramJob) -> None:
        try:
            from core.deep_memory_vault import get_deep_memory_vault

            vault = get_deep_memory_vault()
            vault.record_contemplation(
                question=f"[COMANDO DE VOZ PROGRAMA]: {job.goal}",
                answer=json.dumps(job.to_dict(), ensure_ascii=False)[:6000],
                source="tardis_voice_program",
                status="COMPLETED" if job.status == "completed" else "FAILED",
                complexity_score=2.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Bóveda no disponible para registrar orden de voz: %s", exc)

    def _sync_hub(self, job: ProgramJob) -> None:
        try:
            from omni_temporal_control import SYNC_HUB

            summary = (
                f"🧬 [VOZ · PROGRAMA] {job.status.upper()} · {job.engine}\n"
                f"• Orden: {job.goal}\n"
                f"• Canal: {job.channel} ({job.source})\n"
                f"• Job: {job.job_id}"
            )
            SYNC_HUB.add_chat_turn(
                "assistant",
                summary,
                meta=f"TARDIS Voice Program · {job.channel}",
                client_id=f"voice_program_{job.channel}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("SYNC_HUB no disponible para orden de voz: %s", exc)

    # -- Progreso visual del programa -------------------------------------

    @staticmethod
    def _progress_notifier():
        try:
            from core.program_progress import get_program_progress

            return get_program_progress()
        except Exception:  # noqa: BLE001
            return None

    def _start_progress(self, job: ProgramJob) -> None:
        progress = self._progress_notifier()
        if progress is None or job.chat_id is None:
            return
        try:
            progress.start_job(
                job_id=job.job_id,
                chat_id=job.chat_id,
                goal=job.goal,
                kind="VOZ → FTL",
                cwd=str(PROJECT_ROOT),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo abrir el canal visual de %s: %s", job.job_id, exc)

    def _note_progress(self, job: ProgramJob, line: str) -> None:
        progress = self._progress_notifier()
        if progress is None:
            return
        try:
            progress.note_output(job.job_id, line)
        except Exception:  # noqa: BLE001
            pass

    def _finish_progress(self, job: ProgramJob) -> None:
        progress = self._progress_notifier()
        if progress is None:
            return
        try:
            progress.finish_job(
                job.job_id,
                ok=(job.status == "completed"),
                summary=(job.error or "Función validada e integrada"),
                files=(job.result or {}).get("files_changed") or [],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo cerrar el canal visual de %s: %s", job.job_id, exc)

    def _notify_telegram(self, job: ProgramJob) -> None:
        """Avisa por Telegram si la orden llegó desde un chat de Telegram."""
        chat_id = job.chat_id
        if chat_id is None or not str(chat_id).lstrip("-").isdigit():
            return
        if "telegram" not in (job.channel or "").lower():
            return
        try:
            from core.telegram_bridge import get_telegram_bridge

            bridge = get_telegram_bridge()
            icon = "✅" if job.status == "completed" else "⚠️"
            files = (job.result or {}).get("files_changed") or []
            detail = ""
            if files:
                detail = "\n• Archivos: " + ", ".join(f"`{Path(f).name}`" for f in files[:4])
            bridge.send_message(
                f"{icon} **[FTL · FUNCIÓN POR VOZ]**\n"
                f"• **Orden:** {job.goal}\n"
                f"• **Motor:** `{job.engine}`\n"
                f"• **Estado:** `{job.status.upper()}`"
                f"{detail}",
                chat_id=chat_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo notificar por Telegram: %s", exc)

    # -- Utilidades --------------------------------------------------------

    def _log_event(self, payload: Dict[str, Any]) -> None:
        record = {
            "ts": time.time(),
            "iso": datetime.now().isoformat(timespec="seconds"),
            **payload,
        }
        try:
            with self._lock:
                with EVENT_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo escribir %s: %s", EVENT_LOG, exc)


def get_voice_program_router() -> VoiceProgramRouter:
    return VoiceProgramRouter.get_instance()


def maybe_handle_voice_program(
    text: str,
    *,
    channel: str,
    source: str = "",
    chat_id: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Atajo funcional para integrar el comando en cualquier micrófono."""
    return get_voice_program_router().handle(
        text,
        channel=channel,
        source=source,
        chat_id=chat_id,
        metadata=metadata,
    )
