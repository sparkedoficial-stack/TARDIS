"""core/governor/config.py - Constantes, umbrales Ring 0, perfiles cgroup v2 y utilidades atómicas."""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import logging
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GOVERNOR_DB = DATA_DIR / "resource_governor.db"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
TMPFS_SNAPSHOT = RUNTIME_DIR / "tardis_governor.json"
THROTTLE_STATE_FILE = RUNTIME_DIR / "tardis_governor_throttle.json"
GPU_ECO_STATE_FILE = RUNTIME_DIR / "tardis_governor_gpu_eco.json"
SWAP_RECYCLE_STATE_FILE = RUNTIME_DIR / "tardis_governor_swap_recycle.json"
DISK_SNAPSHOT = DATA_DIR / "resource_governor_latest.json"
LOCK_FILE = DATA_DIR / "resource_governor.lock"
BACKUP_ARCHIVE_DIR = PROJECT_ROOT / "_selfmod_backups" / "legacy_archive"

logger = logging.getLogger("TARDIS.ResourceGovernor")

# Unidades protegidas que NUNCA deben recibir throttling por presión de fondo.
PROTECTED_UNITS: frozenset[str] = frozenset(
    {
        "tardis-desktop.service",
        "pipewire.service",
        "pipewire-pulse.service",
        "wireplumber.service",
        "tardis-telegram-call.service",
        "tardis-infinite-voice.service",
        "tardis-ollama-voice.service",
        "tardis-resource-governor.service",
        "tardis-thermal-guard.service",
        "tardis-cpuset.service",
        "tardis.service",
        "ftl-public-gateway.service",
    }
)

# Unidades de fondo (lotes, investigación, evolución, respaldo CPU) elegibles para throttling agresivo.
BACKGROUND_THROTTLE_UNITS: Tuple[str, ...] = (
    "tardis-video-pensante.service",
    "tardis-visual-intelligence.service",
    "tardis-omniscient-autonomy.service",
    "tardis-curiosity-debater.service",
    "tardis-hub-agents.service",
    "tardis-browser-autonomous.service",
    "tardis-cyber-evolve.service",
    "tardis-music-maestro.service",
    "tardis4ever.service",
    "ollama.service",
)

# Unidades de vigilancia perimetral: ceden cuota parcialmente sin perder alertas de presencia.
SENTINEL_THROTTLE_UNITS: Tuple[str, ...] = (
    "tardis-tapo-c310-sentinel.service",
    "tardis-tapo-c310-voice.service",
)

# Unidades de inferencia principal supervisadas para telemetría cgroup y alivio térmico/PSI.
INFERENCE_MANAGED_UNITS: Tuple[str, ...] = (
    "tardis-temporal-brain.service",
    "tardis-embed-brain.service",
    "tardis-ollama-voice.service",
)

# Unidades protegidas observadas en modo solo-lectura (telemetría PSI/sobresuscripción, jamás throttling).
OBSERVED_ONLY_UNITS: Tuple[str, ...] = (
    "tardis.service",
)

ALL_INSPECTED_UNITS: Tuple[str, ...] = (
    OBSERVED_ONLY_UNITS + INFERENCE_MANAGED_UNITS + SENTINEL_THROTTLE_UNITS + BACKGROUND_THROTTLE_UNITS
)

# Perfiles deterministas de throttling cgroup v2 en caliente (--runtime) por nivel de presión.
# Los valores de CPUQuota usan porcentaje sobre un núcleo lógico (ej. "150%" = 1.5 hilos).
THROTTLE_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "ORANGE": {
        "background": {"cpu_weight": 10, "io_weight": 10, "cpu_quota": "100%"},
        "sentinel": {"cpu_weight": 15, "io_weight": 20, "cpu_quota": "150%"},
        # TemporalBrain sólo recibe techo suave si además hay presión térmica/PSI sostenida.
        "inference_thermal": {"cpu_weight": 35, "io_weight": 30, "cpu_quota": "450%"},
    },
    "RED": {
        "background": {"cpu_weight": 5, "io_weight": 5, "cpu_quota": "50%"},
        "sentinel": {"cpu_weight": 10, "io_weight": 10, "cpu_quota": "120%"},
        "inference_thermal": {"cpu_weight": 25, "io_weight": 20, "cpu_quota": "350%"},
    },
}

# Histéresis para liberación automática de throttling en el demonio (Schmitt trigger):
# - GREEN: liberación rápida tras 2 muestras consecutivas.
# - YELLOW en banda segura de enfriamiento (PSI60<20%, CPU<79°C, GPU<74°C, RAM>=6GB):
#   liberación tras 3 muestras consecutivas para evitar bloqueo indefinido cuando Tctl ~77°C.
RECOVERY_GREEN_STREAK = 2
RECOVERY_SAFE_YELLOW_STREAK = 3
# Confirmación de picos térmicos puros de CPU (82-85.9°C con PSI/carga bajos) antes de
# aplicar throttling global en el demonio (evita falsas alarmas por micro-ráfagas Ryzen).
THERMAL_SPIKE_CONFIRM_STREAK = 2
# Margen térmico mínimo para restaurar automáticamente el perfil energético 'performance'.
POWER_PROFILE_RESTORE_MAX_CPU_C = 72.0
POWER_PROFILE_RESTORE_MAX_GPU_C = 68.0
# Antigüedad máxima (días) para conservar archivos .bak* sueltos en raíz/core antes de archivarlos.
STALE_BACKUP_ARCHIVE_DAYS = 7.0

# Umbrales Ring 0 de swap-bloat y reciclaje seguro en reposo para motores llama-server (COEV-20261124-5B1F5C).
# Jamás interrumpe slots activos (/slots is_processing=true), clientes TCP en :11435 ni llamadas Telegram.
SWAP_BLOAT_UNITS: Dict[str, Dict[str, Any]] = {
    "tardis-temporal-brain.service": {
        "swap_warn_mb": 1536.0,
        "swap_recycle_mb": 2048.0,
        "total_recycle_mb": 9216.0,
        "min_uptime_s": 600.0,
        "cooldown_s": 1800.0,
        "idle_kind": "temporal_brain",
    },
    "tardis-ollama-voice.service": {
        "swap_warn_mb": 1024.0,
        "swap_recycle_mb": 2048.0,
        "total_recycle_mb": 6144.0,
        "min_uptime_s": 600.0,
        "cooldown_s": 1800.0,
        "idle_kind": "ollama_11435",
    },
}

# Perfiles Ring 0 de relojes NVIDIA RTX 3050 para mitigación P0 -> P5/P8 en reposo o presión térmica.
GPU_ECO_PROFILES: Dict[str, Dict[str, Any]] = {
    "eco_idle": {"gr_min": 210, "gr_max": 420, "mem_min": 405, "mem_max": 405, "target_pstate": "P8", "hypr_eco": True},
    "eco_thermal": {"gr_min": 210, "gr_max": 600, "mem_min": 405, "mem_max": 810, "target_pstate": "P5", "hypr_eco": True},
}

HYPR_ECO_OPTIONS: Tuple[str, ...] = (
    "animations:enabled",
    "decoration:blur:enabled",
    "decoration:shadow:enabled",
)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-gov-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass

def _facade_hook(name: str, default: Any) -> Any:
    """Resuelve un helper a través de `core.tardis_resource_governor` si está cargado (compatibilidad 100% monkeypatch)."""
    mod = sys.modules.get("core.tardis_resource_governor")
    if mod is not None:
        fn = getattr(mod, name, None)
        if fn is not None:
            return fn
    return default
