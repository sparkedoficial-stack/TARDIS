"""
core/ftl_telegram_runner.py - Ejecución de peticiones FTL desde Telegram
========================================================================
Permite que el Arquitecto envíe desde Telegram (/ftl <petición>) peticiones de
creación y mejora de código a FTL (~/.ftl/ftl_cli.py), que las enruta a
Claude Code / Antigravity en modo autónomo.

  - Un solo trabajo activo a la vez (FTL modifica archivos del host).
  - Se ejecuta en segundo plano: el polling de Telegram nunca se bloquea.
  - Aviso periódico de avance, timeout duro y cancelación (/ftl cancelar).
  - Registro completo en ~/.ftl/telegram_jobs/<id>.log.
"""

from __future__ import annotations

import html
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

FTL_CLI = Path.home() / ".ftl" / "ftl_cli.py"
JOBS_DIR = Path.home() / ".ftl" / "telegram_jobs"
DEFAULT_CWD = Path.home()
DEFAULT_TIMEOUT_SEC = 45 * 60
HEARTBEAT_SEC = 180
TELEGRAM_CHUNK = 3500
MAX_RESULT_CHUNKS = 3

VALID_MODES = {"auto", "synth", "audit", "gemini", "agy", "claude"}
MODE_ALIASES = {"sintesis": "synth", "auditoria": "audit", "google": "gemini"}

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")

USAGE = (
    "🛸 <b>FTL desde Telegram · Creación y mejora de código</b>\n\n"
    "• <code>/ftl &lt;petición&gt;</code> : crea o mejora código (modo auto)\n"
    "• <code>/ftl -m claude|gemini|synth|audit|auto &lt;petición&gt;</code> : fuerza el motor\n"
    "• <code>/ftl -d ~/ruta/proyecto &lt;petición&gt;</code> : directorio de trabajo (por defecto ~)\n"
    "• <code>/ftl estado</code> : trabajo en curso\n"
    "• <code>/ftl cancelar</code> : detiene el trabajo en curso\n\n"
    "Ejemplo:\n<code>/ftl -d ~/vw-control agrega validación de entradas a la API y pruebas</code>"
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def is_ui_noise(line: str) -> bool:
    """Paneles y barras de rich pensados para la terminal: ilegibles en el móvil."""
    s = line.strip()
    return (
        (s[:1] in ("╭", "│", "╰"))
        or "━━━" in s
        or s.startswith("Warning: Input is not a terminal")
    )


@dataclass
class FTLRequest:
    prompt: str = ""
    mode: Optional[str] = None
    cwd: Path = DEFAULT_CWD
    action: str = "run"  # run | status | cancel | help
    error: str = ""


def parse_request(arg_text: str) -> FTLRequest:
    """Interpreta el texto que sigue a /ftl."""
    text = (arg_text or "").strip()
    req = FTLRequest()
    if not text or text.lower() in ("help", "ayuda", "-h", "--help"):
        req.action = "help"
        return req

    low = text.lower()
    if low in ("estado", "status"):
        req.action = "status"
        return req
    if low in ("cancelar", "cancel", "stop", "detener"):
        req.action = "cancel"
        return req

    # Opciones iniciales -m/--mode y -d/--dir; el resto (con saltos de línea) es la petición
    while True:
        m = re.match(r"^(-m|--mode|-d|--dir)\s+(\"[^\"]+\"|'[^']+'|\S+)\s*", text)
        if not m:
            break
        flag, value = m.group(1), m.group(2)
        try:
            value = shlex.split(value)[0]
        except ValueError:
            value = value.strip("\"'")
        text = text[m.end():]
        if flag in ("-m", "--mode"):
            mode = MODE_ALIASES.get(value.lower(), value.lower())
            if mode not in VALID_MODES:
                req.error = f"Modo inválido: {value}. Usa: {', '.join(sorted(VALID_MODES))}"
                return req
            req.mode = mode
        else:
            path = Path(os.path.expanduser(value)).resolve()
            if not path.is_dir():
                req.error = f"El directorio no existe: {path}"
                return req
            req.cwd = path

    req.prompt = text.strip()
    if not req.prompt:
        req.error = "Falta la petición. Ejemplo: /ftl crea un script que respalde ~/Documentos"
    elif req.prompt[0] in "$!":
        # FTL interpreta $/! como shell directa del host; eso ya está desactivado en remoto (/sh)
        req.error = "La shell directa ($ / !) no está permitida desde Telegram. Describe la tarea en lenguaje natural."
    return req


@dataclass
class FTLJob:
    job_id: str
    chat_id: Any
    request: FTLRequest
    log_path: Path
    started: float = field(default_factory=time.time)
    process: Optional[subprocess.Popen] = None
    cancelled: bool = False
    output: List[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started


class FTLTelegramRunner:
    def __init__(
        self,
        send_html: Callable[[str, Any, Optional[int]], Any],
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        heartbeat_sec: int = HEARTBEAT_SEC,
        ftl_cli: Path = FTL_CLI,
    ):
        self._send = send_html
        self.timeout_sec = timeout_sec
        self.heartbeat_sec = heartbeat_sec
        self.ftl_cli = ftl_cli
        self._lock = threading.Lock()
        self.current: Optional[FTLJob] = None

    # ------------------------------------------------------------------
    def handle(self, chat_id: Any, arg_text: str, msg_id: Optional[int] = None) -> None:
        req = parse_request(arg_text)
        if req.action == "help":
            self._send(USAGE, chat_id, msg_id)
        elif req.action == "status":
            self._send(self._status_text(), chat_id, msg_id)
        elif req.action == "cancel":
            self._send(self.cancel(), chat_id, msg_id)
        elif req.error:
            self._send(f"⚠️ {html.escape(req.error)}", chat_id, msg_id)
        else:
            self.submit(chat_id, req, msg_id)

    def submit(self, chat_id: Any, req: FTLRequest, msg_id: Optional[int] = None) -> Optional[FTLJob]:
        if not self.ftl_cli.exists():
            self._send(f"❌ No se encontró FTL en <code>{html.escape(str(self.ftl_cli))}</code>", chat_id, msg_id)
            return None
        with self._lock:
            if self.current is not None:
                self._send(
                    "⏳ FTL ya está trabajando en otra petición.\n" + self._status_text()
                    + "\n\nUsa <code>/ftl cancelar</code> para detenerla.",
                    chat_id, msg_id,
                )
                return None
            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            job_id = time.strftime("%Y%m%d-%H%M%S")
            job = FTLJob(job_id, chat_id, req, JOBS_DIR / f"{job_id}.log")
            self.current = job

        self._send(
            "🛸 <b>FTL recibió tu petición</b>\n"
            f"• Modo: <code>{req.mode or 'auto'}</code>\n"
            f"• Directorio: <code>{html.escape(str(req.cwd))}</code>\n"
            f"• Trabajo: <code>{job_id}</code>\n\n"
            f"<i>{html.escape(req.prompt[:500])}</i>\n\n"
            "Te aviso al terminar. <code>/ftl estado</code> · <code>/ftl cancelar</code>",
            chat_id, msg_id,
        )
        threading.Thread(target=self._run, args=(job, msg_id), name=f"ftl-job-{job_id}", daemon=True).start()
        return job

    def cancel(self) -> str:
        job = self.current
        if job is None or job.process is None:
            return "ℹ️ No hay ningún trabajo FTL en curso."
        job.cancelled = True
        self._kill(job.process)
        return f"🛑 Cancelando el trabajo FTL <code>{job.job_id}</code>…"

    # ------------------------------------------------------------------
    def _status_text(self) -> str:
        job = self.current
        if job is None:
            return "ℹ️ No hay ningún trabajo FTL en curso."
        last = ""
        for line in reversed(job.output):
            if line.strip():
                last = line.strip()[:200]
                break
        return (
            f"⚙️ Trabajo <code>{job.job_id}</code> en curso · {int(job.elapsed // 60)} min {int(job.elapsed % 60)} s\n"
            f"• Petición: <i>{html.escape(job.request.prompt[:200])}</i>"
            + (f"\n• Última salida: <code>{html.escape(last)}</code>" if last else "")
        )

    def _build_cmd(self, req: FTLRequest) -> List[str]:
        cmd = [sys.executable, str(self.ftl_cli)]
        if req.mode:
            cmd += ["-m", req.mode]
        # "--" evita que una petición que empiece con "-" se interprete como opción
        cmd += ["--", req.prompt]
        return cmd

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass

    def _run(self, job: FTLJob, msg_id: Optional[int]) -> None:
        req = job.request
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "TERM": "dumb", "NO_COLOR": "1", "COLUMNS": "120"})
        timed_out = False
        rc = -1
        try:
            with open(job.log_path, "w", encoding="utf-8") as log:
                log.write(f"# FTL Telegram job {job.job_id}\n# cwd: {req.cwd}\n# mode: {req.mode or 'auto'}\n# prompt:\n{req.prompt}\n\n")
                log.flush()
                job.process = subprocess.Popen(
                    self._build_cmd(req),
                    cwd=str(req.cwd),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    bufsize=1,
                    env=env,
                    start_new_session=True,
                )

                def _watchdog():
                    nonlocal timed_out
                    next_beat = time.time() + self.heartbeat_sec
                    while job.process.poll() is None:
                        if job.elapsed > self.timeout_sec:
                            timed_out = True
                            self._kill(job.process)
                            return
                        if self.heartbeat_sec and time.time() >= next_beat:
                            next_beat = time.time() + self.heartbeat_sec
                            self._send(self._status_text(), job.chat_id, None)
                        time.sleep(2)

                threading.Thread(target=_watchdog, daemon=True).start()

                for raw in job.process.stdout:
                    line = strip_ansi(raw)
                    job.output.append(line)
                    if len(job.output) > 5000:
                        del job.output[:1000]
                    log.write(line)
                    log.flush()
                rc = job.process.wait()
        except Exception as e:
            job.output.append(f"\nError lanzando FTL: {e}\n")
        finally:
            with self._lock:
                self.current = None
        self._report(job, rc, timed_out, msg_id)

    def _report(self, job: FTLJob, rc: int, timed_out: bool, msg_id: Optional[int]) -> None:
        mins = f"{int(job.elapsed // 60)} min {int(job.elapsed % 60)} s"
        if job.cancelled:
            header = f"🛑 <b>Trabajo FTL {job.job_id} cancelado</b> tras {mins}."
        elif timed_out:
            header = f"⏱️ <b>Trabajo FTL {job.job_id} detenido</b>: superó el límite de {self.timeout_sec // 60} min."
        elif rc == 0:
            header = f"✅ <b>FTL terminó tu petición</b> en {mins}."
        else:
            header = f"❌ <b>FTL terminó con errores</b> (código {rc}) en {mins}."
        self._send(f"{header}\n📄 Registro completo: <code>{html.escape(str(job.log_path))}</code>", job.chat_id, msg_id)

        # El registro conserva todo; a Telegram solo va la respuesta útil
        output = "".join(l for l in job.output if not is_ui_noise(l)).strip()
        # Colapsar líneas en blanco repetidas y redibujados de la barra de avance
        output = re.sub(r"\n{3,}", "\n\n", output)
        if not output:
            return
        limit = TELEGRAM_CHUNK * MAX_RESULT_CHUNKS
        if len(output) > limit:
            output = "…(salida recortada, ver registro completo)…\n" + output[-limit:]
        for i in range(0, len(output), TELEGRAM_CHUNK):
            chunk = output[i:i + TELEGRAM_CHUNK]
            self._send(f"<pre>{html.escape(chunk)}</pre>", job.chat_id, None)


_RUNNER: Optional[FTLTelegramRunner] = None


def get_ftl_runner(send_html: Callable[[str, Any, Optional[int]], Any]) -> FTLTelegramRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = FTLTelegramRunner(send_html)
    return _RUNNER
