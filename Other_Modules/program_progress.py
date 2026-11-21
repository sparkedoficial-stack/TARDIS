"""
core/program_progress.py - Canal Soberano de Avances Visuales de Programas
=========================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL
Arquitecto: El Arquitecto (₪)

Propósito:
  Cuando TARDIS/FTL crea o modifica un programa (petición `/ftl`, orden de voz
  «programa», ingeniero FTL o respaldo dinámico), el Arquitecto recibe en su
  terminal privada de Telegram capturas de pantalla periódicas del avance real
  del escritorio y, si aparece, de la ventana del programa recién creado.

Garantías:
  • Privacidad: sólo se envía al chat privado del Arquitecto (REDACTED_PHONE).
    Jamás a grupos ni a terceros, aunque la orden se haya lanzado desde un grupo.
  • Baja entropía: las capturas idénticas se omiten (hash); intervalo mínimo 30 s.
  • Sin bloqueos: todo corre en hilos daemon; un fallo de captura nunca afecta
    al trabajo de FTL ni al polling de Telegram.
  • Persistencia: el estado (activo/pausado, intervalo, máximo de capturas) vive
    en `data/program_progress.json` y sobrevive reinicios.

Uso:
    from core.program_progress import get_program_progress
    progress = get_program_progress()
    progress.start_job(job_id, chat_id, goal, kind="FTL", cwd="/ruta")
    progress.note_output(job_id, "Archivo: dynamic_tools/x.py")
    progress.finish_job(job_id, ok=True, files=["dynamic_tools/x.py"])
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("TARDIS.ProgramProgress")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "program_progress.json"
ARCHITECT_TELEGRAM_ID = REDACTED_PHONE

DEFAULT_STATE: Dict[str, Any] = {
    "enabled": True,
    "interval_sec": 90,
    "initial_delay_sec": 20,
    "max_shots": 24,
}

MIN_INTERVAL_SEC = 30
MAX_INTERVAL_SEC = 900
MAX_CONCURRENT_SESSIONS = 4

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PATH_RE = re.compile(
    r"(?<![\w/.-])((?:dynamic_tools|core|scripts|tools|modules|app|src|tests)/"
    r"[\w./-]+\.(?:py|js|ts|tsx|jsx|html|css|sh|json|md|toml|yaml|yml))"
)
_LABEL_PATH_RE = re.compile(
    r"(?:Archivo|Módulo|File|Path|module|archivo|módulo)\s*[:=]\s*([^\s,;()]+\.\w{1,6})",
    re.IGNORECASE,
)
_NOISE_CHARS = ("╭", "│", "╰", "━", "─")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_architect(chat_id: Any) -> bool:
    try:
        return int(chat_id) == ARCHITECT_TELEGRAM_ID
    except (TypeError, ValueError):
        return str(chat_id).strip() == str(ARCHITECT_TELEGRAM_ID)


def _clean_caption(text: Any, limit: int = 220) -> str:
    """Elimina caracteres que rompen el parse_mode Markdown de Telegram."""
    value = str(text or "")
    value = _ANSI_RE.sub("", value)
    value = value.replace("`", "'").replace("*", "").replace("_", " ").replace("[", "(").replace("]", ")")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _fmt_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    if total >= 3600:
        return f"{total // 3600}h {(total % 3600) // 60:02d}m"
    return f"{total // 60:02d}:{total % 60:02d}"


def _is_noise(line: str) -> bool:
    stripped = _ANSI_RE.sub("", line or "").strip()
    if not stripped:
        return True
    if stripped.startswith(_NOISE_CHARS):
        return True
    if "━━━" in stripped or "───" in stripped:
        return True
    if stripped.startswith(("Warning: Input is not a terminal", "Rendering…")):
        return True
    if set(stripped) <= {"-", "=", " ", ".", "·", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "|", "/", "\\"}:
        return True
    return False


@dataclass
class ProgressSession:
    job_id: str
    chat_id: Any
    goal: str
    kind: str = "FTL"
    cwd: str = ""
    started_at: float = field(default_factory=time.time)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    shots: int = 0
    last_hash: str = ""
    last_line: str = ""
    last_window: Optional[Dict[str, Any]] = None
    files: set = field(default_factory=set)
    known_windows: set = field(default_factory=set)
    last_sent_at: float = 0.0

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "chat_id": self.chat_id,
            "goal": _clean_caption(self.goal, 160),
            "kind": self.kind,
            "elapsed_sec": round(self.elapsed, 1),
            "shots": self.shots,
            "files": sorted(self.files)[-8:],
            "last_line": _clean_caption(self.last_line, 160),
            "last_window": (self.last_window or {}).get("title", ""),
        }


class ProgramProgressNotifier:
    """Gestor único de sesiones de avance visual por programa."""

    _instance: Optional["ProgramProgressNotifier"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProgramProgressNotifier":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, ProgressSession] = {}
        self._state = self._load_state()
        # Puntos de inyección para pruebas y para integraciones alternas.
        self.capture_func: Optional[Callable[..., Tuple[bytes, Dict[str, Any]]]] = None
        self.send_photo_func: Optional[Callable[..., Any]] = None
        self.send_text_func: Optional[Callable[..., Any]] = None

    # -- Estado persistente ------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        state = dict(DEFAULT_STATE)
        try:
            if STATE_FILE.is_file():
                raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    state.update(raw)
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo leer %s: %s", STATE_FILE, exc)
        state["interval_sec"] = max(MIN_INTERVAL_SEC, min(MAX_INTERVAL_SEC, int(state.get("interval_sec", 90))))
        state["max_shots"] = max(1, min(60, int(state.get("max_shots", 24))))
        state["initial_delay_sec"] = max(5, min(120, int(state.get("initial_delay_sec", 20))))
        return state

    def _save_state(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = dict(self._state)
            payload["updated_at"] = _now_iso()
            STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo guardar %s: %s", STATE_FILE, exc)

    @property
    def enabled(self) -> bool:
        return bool(self._state.get("enabled"))

    @property
    def interval_sec(self) -> int:
        return int(self._state.get("interval_sec", 90))

    def configure(
        self,
        enabled: Optional[bool] = None,
        interval_sec: Optional[int] = None,
        max_shots: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if enabled is not None:
                self._state["enabled"] = bool(enabled)
            if interval_sec is not None:
                self._state["interval_sec"] = max(
                    MIN_INTERVAL_SEC, min(MAX_INTERVAL_SEC, int(interval_sec))
                )
            if max_shots is not None:
                self._state["max_shots"] = max(1, min(60, int(max_shots)))
            self._save_state()
            return dict(self._state)

    def enabled_for(self, chat_id: Any) -> bool:
        """Las capturas automáticas sólo van al chat privado del Arquitecto."""
        return self.enabled and _is_architect(chat_id)

    # -- Ciclo de vida de una sesión --------------------------------------

    def start_job(
        self,
        job_id: str,
        chat_id: Any,
        goal: str,
        kind: str = "FTL",
        cwd: Optional[str] = None,
        skip_if_exists: bool = True,
    ) -> bool:
        if not job_id or not self.enabled_for(chat_id):
            return False
        with self._lock:
            if job_id in self._sessions:
                return False if skip_if_exists else True
            if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
                logger.debug("Límite de sesiones de avance alcanzado; %s no se registra.", job_id)
                return False
            session = ProgressSession(
                job_id=str(job_id),
                chat_id=chat_id,
                goal=str(goal or ""),
                kind=kind or "FTL",
                cwd=str(cwd or ""),
            )
            try:
                from core.screen_capture import list_windows

                session.known_windows = {w["address"] for w in list_windows()}
            except Exception:
                session.known_windows = set()
            self._sessions[job_id] = session
            session.thread = threading.Thread(
                target=self._loop,
                args=(session,),
                daemon=True,
                name=f"ProgramProgress-{job_id}",
            )
            session.thread.start()

        logger.info("🎥 [PROGRESO] Canal visual abierto para %s (%s)", job_id, _clean_caption(goal, 80))
        return True

    def note_output(self, job_id: str, line: str) -> None:
        """Registra la última fase significativa y los archivos detectados."""
        session = self._sessions.get(job_id)
        if session is None or _is_noise(line):
            return
        clean = _ANSI_RE.sub("", line).strip()
        if not clean:
            return
        with self._lock:
            session.last_line = _clean_caption(clean, 200)
            for match in _PATH_RE.findall(clean):
                session.files.add(match)
            for match in _LABEL_PATH_RE.findall(clean):
                if len(match) < 240:
                    session.files.add(match)

    def finish_job(
        self,
        job_id: str,
        ok: bool = True,
        summary: str = "",
        files: Optional[Iterable[str]] = None,
    ) -> None:
        with self._lock:
            session = self._sessions.pop(job_id, None)
        if session is None:
            return
        session.stop_event.set()
        if files:
            for item in files:
                if item:
                    session.files.add(str(item))
        if session.thread and session.thread.is_alive() and session.thread is not threading.current_thread():
            session.thread.join(timeout=3.0)

        if not self.enabled_for(session.chat_id):
            return
        try:
            self._send_final(session, ok=ok, summary=summary)
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo enviar la captura final de %s: %s", job_id, exc)

    # -- Bucle de capturas -------------------------------------------------

    def _loop(self, session: ProgressSession) -> None:
        delay = int(self._state.get("initial_delay_sec", 20))
        if session.stop_event.wait(delay):
            return
        while not session.stop_event.is_set():
            try:
                self._tick(session)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Fallo de captura de avance %s: %s", session.job_id, exc)
            if session.shots >= int(self._state.get("max_shots", 24)):
                return
            if session.stop_event.wait(self.interval_sec):
                return

    def _pick_window(self, session: ProgressSession) -> Optional[Dict[str, Any]]:
        """Prioriza una ventana nueva que corresponda al programa en creación."""
        from core.screen_capture import list_windows

        windows = list_windows()
        if not windows:
            return None
        new_windows = [w for w in windows if w["address"] not in session.known_windows]

        # Si la última ventana capturada sigue viva, se conserva.
        if session.last_window:
            for window in windows:
                if window["address"] == session.last_window.get("address"):
                    return window

        if not new_windows:
            return None

        tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{4,}", session.goal)
            if token.casefold() not in {"para", "desde", "crea", "crear", "programa", "función", "funcion", "sistema", "tardis"}
        }
        for path in list(session.files)[-6:]:
            tokens.update(
                part.casefold()
                for part in re.findall(r"[A-Za-z0-9]{4,}", Path(path).stem)
            )

        best = None
        best_score = -1
        for window in new_windows:
            haystack = f"{window['title']} {window['class']} {window['initial_class']}".casefold()
            score = sum(1 for token in tokens if token in haystack)
            if score > best_score:
                best, best_score = window, score
        if best is None and new_windows:
            best = new_windows[-1]
        return best

    def _capture(self, session: ProgressSession) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        window = None
        try:
            window = self._pick_window(session)
        except Exception:
            window = None

        if window:
            session.last_window = window
        try:
            if self.capture_func is not None:
                raw, meta = self.capture_func(window=window)
            else:
                from core.screen_capture import capture

                raw, meta = capture(fmt="jpeg", max_width=1600, quality=82, window=window)
            if window:
                meta["window"] = window
            return raw, meta
        except Exception as exc:  # noqa: BLE001
            logger.debug("Captura de avance falló: %s", exc)
            return None

    def _caption(self, session: ProgressSession, meta: Dict[str, Any], final: bool = False,
                 ok: bool = True, summary: str = "") -> str:
        title = (meta.get("window") or {}).get("title", "")
        lines = []
        if final:
            lines.append("✅ PROGRAMA COMPLETADO" if ok else "⚠️ PROGRAMA CON INCIDENCIAS")
        else:
            lines.append("🧬 AVANCE DEL PROGRAMA EN CREACIÓN")
        lines.append(f"• Motor: {session.kind}")
        lines.append(f"• Orden: {_clean_caption(session.goal, 150)}")
        elapsed = _fmt_elapsed(session.elapsed)
        if final:
            lines.append(f"• Tiempo total: {elapsed}")
        else:
            lines.append(f"• Tiempo: {elapsed} · Captura {session.shots}/{int(self._state.get('max_shots', 24))}")
        if session.last_line:
            lines.append(f"• Fase: {_clean_caption(session.last_line, 150)}")
        if session.files:
            names = ", ".join(Path(path).name for path in sorted(session.files)[-4:])
            lines.append(f"• Archivos: {_clean_caption(names, 180)}")
        if title:
            lines.append(f"• Ventana: {_clean_caption(title, 100)}")
        if final and summary:
            lines.append(f"• Resultado: {_clean_caption(summary, 160)}")
        return "\n".join(lines)[:1000]

    def _tick(self, session: ProgressSession) -> None:
        if not self.enabled_for(session.chat_id):
            return
        from core.screen_capture import is_locked

        if is_locked():
            return
        captured = self._capture(session)
        if not captured:
            return
        raw, meta = captured
        digest = hashlib.sha256(raw).hexdigest()
        if digest == session.last_hash:
            return
        session.shots += 1
        caption = self._caption(session, meta)
        sent = self._send_photo(session.chat_id, raw, caption)
        if sent:
            session.last_hash = digest
            session.last_sent_at = time.time()

    def _send_final(self, session: ProgressSession, ok: bool, summary: str) -> None:
        from core.screen_capture import is_locked

        if is_locked():
            return
        captured = self._capture(session)
        if not captured:
            return
        raw, meta = captured
        digest = hashlib.sha256(raw).hexdigest()
        if digest == session.last_hash and session.last_sent_at and (time.time() - session.last_sent_at) < 45:
            return
        caption = self._caption(session, meta, final=True, ok=ok, summary=summary)
        self._send_photo(session.chat_id, raw, caption)

    # -- Transporte --------------------------------------------------------

    def _send_photo(self, chat_id: Any, raw: bytes, caption: str) -> bool:
        try:
            if self.send_photo_func is not None:
                result = self.send_photo_func(raw, caption=caption, chat_id=chat_id)
            else:
                from core.telegram_bridge import get_telegram_bridge

                result = get_telegram_bridge().send_photo(raw, caption=caption, chat_id=chat_id)
            return bool(isinstance(result, dict) and result.get("ok", True))
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo despachar captura de avance: %s", exc)
            return False

    # -- Consulta ----------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            sessions = [session.to_dict() for session in self._sessions.values()]
            return {
                "enabled": self.enabled,
                "interval_sec": self.interval_sec,
                "max_shots": int(self._state.get("max_shots", 24)),
                "active_count": len(sessions),
                "active": sessions,
            }

    def active_summary(self) -> str:
        """Resumen legible para Telegram y /status."""
        state = self.status()
        mode = "ACTIVO" if state["enabled"] else "PAUSADO"
        lines = [
            f"🧬 Canal de avances visuales: {mode}",
            f"• Intervalo: {state['interval_sec']} s · Máximo {state['max_shots']} capturas por programa",
            f"• Sesiones activas: {state['active_count']}",
        ]
        for item in state["active"]:
            lines.append(
                f"  – {item['job_id']} · {item['kind']} · {_fmt_elapsed(item['elapsed_sec'])} · "
                f"{item['shots']} capturas · {_clean_caption(item['goal'], 80)}"
            )
            if item["last_line"]:
                lines.append(f"     Fase: {_clean_caption(item['last_line'], 120)}")
        if not state["active"]:
            lines.append("  – Ningún programa en creación en este momento.")
        return "\n".join(lines)


def get_program_progress() -> ProgramProgressNotifier:
    return ProgramProgressNotifier.get_instance()
