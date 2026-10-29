#!/usr/bin/env python3
"""
GODWORKS · FTL Runtime Environment
==================================
Resolución soberana de binarios y PATH para todos los puntos de entrada de FTL:
TUI, CLI, portal web, orquestador de agentes y peticiones provenientes de
Telegram (que corren bajo systemd con un PATH mínimo).

Problema que resuelve:
    Los servicios systemd (`tardis.service`, `ftl-web-portal.service`, etc.)
    arrancan con un PATH reducido que NO incluye `~/.opencode/bin`. Cuando FTL
    intentaba lanzar `opencode` con `subprocess.Popen(["opencode", ...])` el
    kernel devolvía:

        [Errno 2] No such file or directory: 'opencode'

    Este módulo amplía `os.environ["PATH"]` de forma idempotente y ofrece
    `which()`/`require()` que localizan el binario real aunque el servicio haya
    heredado un PATH incompleto.

Uso:
    import runtime_env                      # amplía PATH automáticamente
    exe = runtime_env.which("opencode")     # ruta absoluta o None
    exe = runtime_env.require("opencode")   # lanza FileNotFoundError legible
    env_dict = os.environ.copy()
    env_dict = runtime_env.augment_path(env_dict)   # para subprocess.Popen(env=...)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Mapping, Optional

FTL_HOME = Path(__file__).resolve().parent
_PATH_MARKER = "FTL_RUNTIME_PATH_READY"

# Directorios donde este host instala CLIs reales (opencode, claude, agy, etc.).
_BASE_DIRS: tuple[Path, ...] = (
    Path.home() / ".opencode" / "bin",
    Path.home() / ".local" / "bin",
    Path.home() / ".bun" / "bin",
    Path.home() / ".npm-global" / "bin",
    Path.home() / ".cargo" / "bin",
    Path.home() / ".nvm" / "current" / "bin",
    Path.home() / ".volta" / "bin",
    FTL_HOME / "bin",
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
    Path("/snap/bin"),
)


def _nvm_version_dirs() -> list[Path]:
    """Devuelve los bin de las versiones nvm instaladas (la más nueva primero)."""
    root = Path.home() / ".nvm" / "versions" / "node"
    if not root.is_dir():
        return []
    try:
        versions = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return []
    return [v / "bin" for v in versions]


def candidate_dirs() -> list[str]:
    """Lista ordenada y sin duplicados de directorios candidatos existentes."""
    dirs: list[str] = []
    for path in list(_BASE_DIRS) + _nvm_version_dirs():
        try:
            if path.is_dir():
                text = str(path)
                if text not in dirs:
                    dirs.append(text)
        except OSError:
            continue
    return dirs


def augment_path(env: Optional[Mapping[str, str]] = None) -> dict:
    """
    Garantiza que los directorios soberanos estén al inicio del PATH.

    `env` puede ser un diccionario propio (p. ej. el entorno de un Popen).
    Si se omite, modifica `os.environ` en el proceso actual.
    Idempotente: no duplica entradas ni altera el orden ya establecido.
    """
    target: dict = os.environ if env is None else dict(env)
    current = str(target.get("PATH") or "")
    parts = [p for p in current.split(os.pathsep) if p]
    seen = set(parts)
    extra = [d for d in candidate_dirs() if d not in seen]
    if extra:
        target["PATH"] = os.pathsep.join(extra + parts)
    elif not current:
        target["PATH"] = os.pathsep.join(parts)
    if env is None:
        os.environ["PATH"] = target["PATH"]
        os.environ[_PATH_MARKER] = "1"
        # `shutil.which` cachea la búsqueda de forma implícita por llamada,
        # no por PATH; no se requiere limpiar nada aquí.
    return target


def which(name: str, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """
    Localiza un ejecutable por nombre absoluto, PATH heredado o directorios
    soberanos conocidos. Devuelve la ruta absoluta o None.
    """
    if not name:
        return None
    raw = str(name).strip()
    if not raw:
        return None

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    if os.sep in raw:
        # Ruta relativa con directorios: resolver contra el cwd.
        resolved = candidate.resolve()
        return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None

    if env is None:
        if not os.environ.get(_PATH_MARKER):
            augment_path()
        search_path = os.environ.get("PATH", "")
    else:
        search_path = str(augment_path(env).get("PATH", ""))

    found = shutil.which(raw, path=search_path)
    if found:
        return found

    for directory in candidate_dirs():
        candidate = Path(directory) / raw
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


def require(name: str, purpose: str = "ejecutar el motor FTL") -> str:
    """Como `which`, pero lanza un error explícito y accionable si falta."""
    exe = which(name)
    if exe:
        return exe
    searched = ", ".join(candidate_dirs()) or "(sin directorios candidatos)"
    raise FileNotFoundError(
        f"No se encontró el ejecutable '{name}' para {purpose}. "
        f"PATH actual: {os.environ.get('PATH', '')}. "
        f"Directorios soberanos buscados: {searched}. "
        f"Instálalo o exporta PATH incluyendo su directorio."
    )


def describe() -> dict:
    """Diagnóstico legible del entorno de ejecución de FTL."""
    tools = {}
    for name in ("opencode", "claude", "agy", "git", "edge-tts", "python3"):
        tools[name] = which(name)
    return {
        "home": str(Path.home()),
        "cwd": os.getcwd(),
        "path": os.environ.get("PATH", ""),
        "candidate_dirs": candidate_dirs(),
        "tools": tools,
    }


# Ampliación automática al importar: cualquier módulo que haga
# `import runtime_env` hereda un PATH completo, incluido el de systemd.
try:
    augment_path()
except Exception:
    # Nunca impedir el arranque de FTL por un PATH exótico.
    pass


if __name__ == "__main__":
    import json

    print(json.dumps(describe(), indent=2, ensure_ascii=False))
