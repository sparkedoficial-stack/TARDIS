#!/usr/bin/env python3
"""
GODWORKS · FTL Terminal Write Guard
===================================
Aísla la línea de captura de texto de cualquier escritura asíncrona.

Motivo:
    Mientras el Arquitecto escribe un prompt en `ftl chat` (prompt_toolkit) o en
    el shell soberano, cualquier hilo secundario (vigilantes, auto-curación,
    telemetría, voz, progreso) que haga `print()` escribe sobre la misma TTY y
    descoloca/borra el texto que se está escribiendo. El resultado son prompts
    truncados, caracteres mezclados y peticiones corruptas.

Solución:
    Durante la captura de entrada se instala un proxy de `sys.stdout`/
    `sys.stderr` que:
      • deja pasar intactas las escrituras del hilo dueño (prompt_toolkit);
      • retiene las escrituras de cualquier otro hilo en un búfer;
      • vuelca el búfer de forma limpia en cuanto la entrada termina.

    Nada se pierde y ningún hilo puede interferir con el texto escrito.
"""

from __future__ import annotations

import io
import threading
from typing import Optional


class _GuardedStream(io.TextIOBase):
    """Proxy de stream que difiere las escrituras de hilos no propietarios."""

    def __init__(self, real, guard: "TerminalGuard", label: str):
        self._real = real
        self._guard = guard
        self._label = label

    # -- escritura -----------------------------------------------------
    def write(self, data):  # type: ignore[override]
        if not isinstance(data, str):
            data = str(data)
        if self._guard.should_defer():
            self._guard.append(self._label, data)
            return len(data)
        return self._real.write(data)

    def writelines(self, lines):  # type: ignore[override]
        for line in lines:
            self.write(line)

    def flush(self):  # type: ignore[override]
        if self._guard.should_defer():
            return None
        try:
            return self._real.flush()
        except Exception:
            return None

    # -- introspección ------------------------------------------------
    def isatty(self) -> bool:  # type: ignore[override]
        try:
            return bool(self._real.isatty())
        except Exception:
            return False

    def fileno(self) -> int:  # type: ignore[override]
        return self._real.fileno()

    def writable(self) -> bool:  # type: ignore[override]
        return True

    def readable(self) -> bool:  # type: ignore[override]
        return False

    def seekable(self) -> bool:  # type: ignore[override]
        return False

    @property
    def encoding(self):  # type: ignore[override]
        return getattr(self._real, "encoding", "utf-8")

    @property
    def errors(self):  # type: ignore[override]
        return getattr(self._real, "errors", "replace")

    @property
    def buffer(self):  # type: ignore[override]
        return getattr(self._real, "buffer", None)

    def close(self):  # type: ignore[override]
        # Nunca cerrar la TTY real desde un proxy efímero.
        return None

    @property
    def closed(self) -> bool:  # type: ignore[override]
        return getattr(self._real, "closed", False)

    @property
    def real(self):
        return self._real

    def __getattr__(self, item):
        return getattr(self._real, item)


class TerminalGuard:
    """
    Context manager que protege la entrada interactiva de escrituras externas.

    Uso:
        with TerminalGuard() as guard:
            line = prompt_session.prompt(...)
        guard.emit()          # vuelca lo que otros hilos intentaron imprimir
    """

    def __init__(self, protect_stdout: bool = True, protect_stderr: bool = True):
        self.protect_stdout = protect_stdout
        self.protect_stderr = protect_stderr
        self.owner: Optional[int] = None
        self.active = False
        self._buffer: list[tuple[str, str]] = []
        self._buffered_chars = 0
        self._max_buffer_chars = 2_000_000
        self._dropped = 0
        self._lock = threading.Lock()
        self._saved_stdout = None
        self._saved_stderr = None
        self._guard_stdout: Optional[_GuardedStream] = None
        self._guard_stderr: Optional[_GuardedStream] = None

    # -- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "TerminalGuard":
        self.activate()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.deactivate()
        self.emit()

    def activate(self) -> None:
        if self.active:
            return
        import sys

        self.owner = threading.get_ident()
        self.active = True
        if self.protect_stdout:
            self._saved_stdout = sys.stdout
            self._guard_stdout = _GuardedStream(sys.stdout, self, "stdout")
            sys.stdout = self._guard_stdout  # type: ignore[assignment]
        if self.protect_stderr:
            self._saved_stderr = sys.stderr
            self._guard_stderr = _GuardedStream(sys.stderr, self, "stderr")
            sys.stderr = self._guard_stderr  # type: ignore[assignment]

    def deactivate(self) -> None:
        if not self.active:
            return
        import sys

        self.active = False
        if self._saved_stdout is not None:
            sys.stdout = self._saved_stdout  # type: ignore[assignment]
        if self._saved_stderr is not None:
            sys.stderr = self._saved_stderr  # type: ignore[assignment]
        self._saved_stdout = self._saved_stderr = None
        self._guard_stdout = self._guard_stderr = None

    # -- búfer ---------------------------------------------------------
    def should_defer(self) -> bool:
        return self.active and threading.get_ident() != self.owner

    def append(self, label: str, data: str) -> None:
        with self._lock:
            self._buffer.append((label, data))
            self._buffered_chars += len(data)
            # Un hilo muy ruidoso durante una captura larga no debe agotar la RAM.
            while self._buffered_chars > self._max_buffer_chars and len(self._buffer) > 1:
                _, old = self._buffer.pop(0)
                self._buffered_chars -= len(old)
                self._dropped += len(old)

    def pending(self) -> bool:
        with self._lock:
            return bool(self._buffer)

    def drain(self) -> str:
        with self._lock:
            items = self._buffer
            self._buffer = []
            self._buffered_chars = 0
            dropped = self._dropped
            self._dropped = 0
        chunks: list[str] = []
        if dropped:
            chunks.append(f"…({dropped} caracteres de salida omitidos)…\n")
        current_label = None
        for label, data in items:
            if current_label is not None and label != current_label:
                if chunks and not chunks[-1].endswith("\n"):
                    chunks.append("\n")
            current_label = label
            chunks.append(data)
        return "".join(chunks)

    def emit(self, stream=None) -> int:
        """
        Vuelca el texto diferido a la TTY real. Devuelve los caracteres emitidos.

        No usa Rich: el contenido proviene de logs arbitrarios y podría contener
        corchetes que Rich interpretaría como marcado.
        """
        text = self.drain()
        if not text.strip():
            return 0
        if not text.endswith("\n"):
            text += "\n"
        target = stream or self._saved_stdout
        if target is None:
            import sys

            target = sys.stdout
        try:
            target.write(text)
            target.flush()
        except Exception:
            return 0
        return len(text)


# ---------------------------------------------------------------------------
# Guard global (una sola captura interactiva a la vez)
# ---------------------------------------------------------------------------
_ACTIVE: Optional[TerminalGuard] = None
_ACTIVE_LOCK = threading.Lock()


def acquire() -> TerminalGuard:
    """Devuelve el guard activo o crea/activa uno nuevo de forma segura."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None and _ACTIVE.active:
            return _ACTIVE
        guard = TerminalGuard()
        guard.activate()
        _ACTIVE = guard
        return guard


def release(guard: Optional[TerminalGuard] = None, emit: bool = True) -> None:
    """Desactiva el guard y (por defecto) vuelca la salida diferida."""
    global _ACTIVE
    with _ACTIVE_LOCK:
        target = guard or _ACTIVE
        if target is None:
            return
        target.deactivate()
        if emit:
            target.emit()
        if _ACTIVE is target:
            _ACTIVE = None


def protect():
    """Alias semántico para `acquire()`."""
    return acquire()


if __name__ == "__main__":
    import sys
    import time

    def noisy():
        for i in range(3):
            print(f"[hilo secundario] mensaje {i}")
            time.sleep(0.05)

    guard = acquire()
    threading.Thread(target=noisy, daemon=True).start()
    sys.stdout.write("ESCRIBIENDO PROMPT: hola mundo")
    sys.stdout.flush()
    time.sleep(0.3)
    release(guard)
    print("\nOK: el prompt quedó intacto y los mensajes se volcaron después.")
