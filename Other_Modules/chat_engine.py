#!/usr/bin/env python3
"""
GODWORKS · FTL Chat Engine
==========================
Puente entre la interfaz de chat FTL y el motor OpenCode.

Usa `opencode run --format json` para obtener el mismo flujo estructurado que
la TUI de OpenCode: texto, razonamiento, llamadas a herramientas, estado de
pasos, tokens y coste. Mantiene continuidad real mediante `--session <id>`.

Eventos normalizados que emite `ChatRunner.run()`:
  {"kind": "tick"}                                  latido para animaciones
  {"kind": "text", "text": "...", "raw": {...}}
  {"kind": "thinking", "text": "..."}
  {"kind": "tool", "tool": "shell", "status": "completed",
   "input": {...}, "output": "...", "title": "..."}
  {"kind": "step_start"} / {"kind": "step_finish", "tokens": {...}, "cost": 0}
  {"kind": "error", "message": "...", "status": 429, "retry_after_ms": ...}
  {"kind": "raw", "line": "..."}
  {"kind": "process_end", "rc": 0, "session_id": "ses_...", "duration_s": 1.2}
"""

from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import free_models as fm
import runtime_env

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------------------
# Configuración del motor
# ---------------------------------------------------------------------------
@dataclass
class ChatConfig:
    model: str = "opencode/deepseek-v4.1-flash-free#max"
    agent: str = ""
    thinking: bool = False
    auto: bool = True
    cwd: str = ""
    files: list[str] = field(default_factory=list)
    title: str = ""


def resolve_model(token: str) -> str:
    """Resuelve alias FTL, key o referencia OpenCode completa."""
    token = (token or "").strip()
    if not token:
        raise ValueError("Modelo vacío.")
    match = fm.resolve(token)
    if match:
        return match.ref
    if "/" in token:
        return token
    raise ValueError(
        f"Modelo desconocido: {token}. Usa `ftl --agents` para ver los alias."
    )


def short_model(ref: str) -> str:
    base = (ref or "").split("#", 1)[0].split("/", 1)[-1]
    variant = ref.split("#", 1)[1] if "#" in ref else ""
    return f"{base}#{variant}" if variant else base


def _binary() -> Optional[str]:
    """Ruta absoluta del binario de OpenCode (compatible con systemd/Telegram)."""
    return runtime_env.which("opencode")


def _clean(text: str) -> str:
    return ANSI_RE.sub("", text or "")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class ChatRunner:
    def __init__(
        self,
        prompt: str,
        config: ChatConfig,
        opencode_session_id: Optional[str] = None,
    ):
        self.prompt = prompt
        self.config = config
        self.opencode_session_id = opencode_session_id or None
        self.proc: Optional[subprocess.Popen] = None
        self.session_id: Optional[str] = self.opencode_session_id
        self.started_at = 0.0
        self._cancelled = False

    # ------------------------------------------------------------------
    def command(self) -> list[str]:
        cmd = [_binary() or "opencode", "run", "--format", "json"]
        if self.config.model:
            cmd += ["--model", self.config.model]
        if self.config.auto:
            cmd.append("--auto")
        if self.config.agent:
            cmd += ["--agent", self.config.agent]
        if self.config.thinking:
            cmd.append("--thinking")
        if self.opencode_session_id:
            cmd += ["--session", self.opencode_session_id]
        if self.config.title:
            cmd += ["--title", self.config.title]
        for path in self.config.files:
            cmd += ["--file", path]
        cmd.append(self.prompt)
        return cmd

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancelled = True
        if not self.proc:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def run(self) -> Iterator[dict]:
        self.started_at = time.time()
        exe = _binary()
        if not exe:
            yield {
                "kind": "error",
                "message": (
                    "No se encontró el ejecutable 'opencode'. "
                    "Instálalo o añade ~/.opencode/bin al PATH del servicio "
                    "(runtime_env describe los directorios buscados)."
                ),
                "status": 127,
                "error_type": "binary_missing",
                "retry_after_ms": None,
            }
            yield {"kind": "process_end", "rc": 127, "session_id": self.session_id,
                   "duration_s": round(time.time() - self.started_at, 2)}
            return
        cwd = self.config.cwd or os.getcwd()
        if not Path(cwd).is_dir():
            cwd = os.getcwd()
        env = runtime_env.augment_path({**os.environ})
        env.update({"PYTHONUNBUFFERED": "1", "NO_COLOR": "1"})
        try:
            self.proc = subprocess.Popen(
                self.command(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                cwd=cwd,
                start_new_session=True,
                env=env,
            )
        except Exception as exc:
            yield {"kind": "error", "message": f"No se pudo iniciar OpenCode: {exc}"}
            yield {"kind": "process_end", "rc": -1, "session_id": self.session_id,
                   "duration_s": round(time.time() - self.started_at, 2)}
            return

        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        buffer = ""
        try:
            while True:
                if self._cancelled:
                    break
                try:
                    ready, _, _ = select.select([fd], [], [], 0.12)
                except Exception:
                    ready = [fd]
                if not ready:
                    yield {"kind": "tick"}
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    event = self._parse_line(line)
                    if event:
                        yield event
        finally:
            try:
                self.proc.stdout.close()
            except Exception:
                pass
            rc = self.proc.poll()
            if rc is None:
                try:
                    rc = self.proc.wait(timeout=5)
                except Exception:
                    rc = -1

        yield {
            "kind": "process_end",
            "rc": rc,
            "session_id": self.session_id,
            "duration_s": round(time.time() - self.started_at, 2),
        }

    # ------------------------------------------------------------------
    def _parse_line(self, line: str) -> Optional[dict]:
        try:
            raw = json.loads(line)
        except Exception:
            return {"kind": "raw", "line": _clean(line)}

        event_type = raw.get("type")
        session_id = raw.get("sessionID") or (
            (raw.get("part") or {}).get("sessionID") if isinstance(raw.get("part"), dict) else None
        )
        if session_id:
            self.session_id = session_id

        part = raw.get("part") if isinstance(raw.get("part"), dict) else {}

        if event_type == "text":
            text = part.get("text", "")
            if not text:
                return None
            return {"kind": "text", "text": _clean(text), "raw": raw}

        if event_type in ("reasoning", "thinking"):
            text = part.get("text") or part.get("reasoning") or ""
            if not text:
                return None
            return {"kind": "thinking", "text": _clean(text), "raw": raw}

        if event_type == "tool_use":
            state = part.get("state") or {}
            return {
                "kind": "tool",
                "tool": part.get("tool") or "tool",
                "status": state.get("status") or "completed",
                "input": state.get("input") or {},
                "output": _clean(str(state.get("output") or "")),
                "title": state.get("title") or part.get("tool") or "tool",
                "raw": raw,
            }

        if event_type == "step_start":
            return {"kind": "step_start", "raw": raw}

        if event_type == "step_finish":
            tokens = part.get("tokens") or {}
            return {
                "kind": "step_finish",
                "tokens": tokens,
                "cost": float(part.get("cost") or 0.0),
                "reason": part.get("reason"),
                "raw": raw,
            }

        if event_type == "error":
            err = raw.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            return {
                "kind": "error",
                "message": _clean(str(message or "Error desconocido")),
                "status": err.get("status") if isinstance(err, dict) else None,
                "error_type": err.get("type") if isinstance(err, dict) else None,
                "retry_after_ms": err.get("retryAfterMs") if isinstance(err, dict) else None,
                "raw": raw,
            }

        return {"kind": "raw", "line": _clean(line), "raw": raw}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_free_limit(event: dict) -> bool:
    if event.get("kind") != "error":
        return False
    text = (event.get("message") or "").lower()
    return (
        event.get("status") == 429
        or "free usage limit" in text
        or "free-limit" in text
        or "límite" in text
    )


def is_missing_session(event: dict) -> bool:
    if event.get("kind") != "error":
        return False
    text = (event.get("message") or "").lower()
    return "session" in text and ("not found" in text or "no encontrada" in text)


def is_transient_error(event: dict) -> bool:
    """
    True si el fallo justifica probar otro modelo gratuito del pool.

    Cubre límites de uso, binario ausente, modelo retirado, sobrecarga,
    timeouts y cortes de red. NO incluye sesiones inexistentes (eso se
    resuelve recreando la sesión, no cambiando de modelo).
    """
    if event.get("kind") != "error":
        return False
    if is_missing_session(event):
        return False
    if is_free_limit(event):
        return True
    text = (event.get("message") or "").lower()
    return any(
        needle in text
        for needle in (
            "no such file or directory",
            "not found",
            "no encontrado",
            "model is unavailable",
            "unavailable",
            "overloaded",
            "rate limit",
            "too many requests",
            "timeout",
            "timed out",
            "connection",
            "502",
            "503",
            "504",
        )
    )


def model_pool() -> list:
    """Pool operable: verificados/habilitados o, si aún no hay sondas, el catálogo."""
    pool = fm.available_models()
    if pool:
        return pool
    return [m for m in fm.all_models(include_disabled=False) if m.enabled_default]


def next_free_model(current: str = "", attempted: Optional[set] = None):
    """
    Siguiente modelo gratuito del pool, evitando el actual y los ya probados.

    `attempted` acepta keys o refs indistintamente.
    """
    tried = set(attempted or ())
    for model in model_pool():
        if model.ref == current or model.key in tried or model.ref in tried:
            continue
        return model
    return None


def tool_summary(tool: dict, max_output: int = 4000) -> str:
    """Representación textual compacta de una herramienta para persistencia."""
    name = tool.get("tool", "tool")
    status = tool.get("status", "")
    inp = tool.get("input") or {}
    out = tool.get("output") or ""
    if "command" in inp:
        head = f"$ {inp['command']}"
    elif "path" in inp or "filePath" in inp:
        head = f"{name}: {inp.get('path') or inp.get('filePath')}"
    elif inp:
        head = f"{name}: {json.dumps(inp, ensure_ascii=False)[:400]}"
    else:
        head = name
    if out:
        head += "\n" + out[:max_output]
    return f"[{status}] {head}"
