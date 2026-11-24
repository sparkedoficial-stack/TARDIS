#!/usr/bin/env python3
"""
core/tardis_resource_governor.py - Gobernador Soberano de Recursos y Árbitro de Inferencia (Ring 0)
==================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Resuelve la contención de silicio (CPU PSI, RAM, Swap, VRAM RTX 3050, térmicas CPU/GPU)
entre los 37+ servicios de TARDIS, Ollama (:11434/:11435), TemporalBrain y agentes de fondo:

  1. Telemetría Ring 0 de ultra-baja sobrecarga:
     - `/proc/pressure/{cpu,memory,io}` (PSI), `/proc/meminfo`, `/proc/loadavg`
     - `/sys/class/hwmon/*` (temperatura CPU `k10temp`/Tctl y RPM ventiladores `asus`)
     - `nvidia-smi` (VRAM usada/libre, temperatura GPU, utilización)
     - Cgroups v2 en `app.slice` (`cpuset.cpus.effective`, `cpu.max`, `cpu.weight`, `cpu.pressure`)
       y auditoría de sobresuscripción de hilos frente al `cpuset` asignado (ej. `llama-server`).
     - Modelos residentes en Ollama `:11434` (CPU) y `:11435` (GPU Voice Lane)
     - Estado de `/tmp/temporal_brain.sock`, `/tmp/embed_brain.sock` y prioridad de llamadas Telegram
  2. Niveles de Presión y Control de Admisión (`GREEN` | `YELLOW` | `ORANGE` | `RED`):
     - Publica snapshot atómico en tmpfs (`/run/user/<uid>/tardis_governor.json`) para
       lecturas en <0.1 ms desde cualquier demonio sin bloquear ni generar I/O de disco.
     - Control de admisión por clase de tarea (`interactive`, `critical_repair`,
       `agy_discovery`, `heavy_learning`, `idle_evolution`, `video_render`).
  3. Árbitro Activo de Inferencia, Reclamación y Throttling Ring 0 (`reclaim_resources`):
     - Detecta modelos LLM duplicados en CPU Ollama `:11434` cuando ya residen en
       TemporalBrain (`TARDIS-NEURAL-SPACE-KAIJU`) o en el carril GPU `:11435` (`qwen3-vl`)
       y los descarga limpiamente (`keep_alive: 0`) recuperando GBs de RAM sin cortar inferencia.
     - Aplica throttling dinámico y reversible en caliente vía cgroup v2 (`systemctl --user
       set-property --runtime` sobre `CPUWeight`, `IOWeight` y `CPUQuota`) ante presión
       `ORANGE`/`RED` o térmica CPU/GPU, respetando siempre llamadas prioritarias de Telegram
       y restaurando los valores base al estabilizar en `GREEN` con histéresis anti-oscilación.
     - Rota backups `.bak*` obsoletos acumulados en `GODWORKS SYSTEM/` para mantener el repo limpio.
  4. Histórico SQLite WAL (`data/resource_governor.db`) y publicación al Sovereign Event Bus.
"""
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
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GOVERNOR_DB = DATA_DIR / "resource_governor.db"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
TMPFS_SNAPSHOT = RUNTIME_DIR / "tardis_governor.json"
THROTTLE_STATE_FILE = RUNTIME_DIR / "tardis_governor_throttle.json"
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


def _parse_psi_file(path: Path) -> Dict[str, float]:
    out = {"some_avg10": 0.0, "some_avg60": 0.0, "some_avg300": 0.0, "full_avg10": 0.0, "full_avg60": 0.0}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if not parts:
                continue
            prefix = parts[0]
            if prefix not in ("some", "full"):
                continue
            for kv in parts[1:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if k in ("avg10", "avg60", "avg300"):
                        key = f"{prefix}_{k}"
                        if key in out:
                            out[key] = float(v)
    except Exception:
        pass
    return out


def _parse_cpulist_count(cpulist: str) -> int:
    """Cuenta CPUs lógicas representadas en un formato cpulist Linux (ej. '8-15', '0-3,8-11')."""
    txt = (cpulist or "").strip()
    if not txt:
        return 0
    total = 0
    for token in txt.split(","):
        tok = token.strip()
        if not tok:
            continue
        if "-" in tok:
            parts = tok.split("-", 1)
            if parts[0].isdigit() and parts[1].isdigit():
                lo, hi = int(parts[0]), int(parts[1])
                if hi >= lo:
                    total += (hi - lo) + 1
        elif tok.isdigit():
            total += 1
    return total


def _read_cpu_thermal() -> Dict[str, Any]:
    """Lee temperatura de paquete CPU (k10temp/coretemp/acpitz) y ventiladores (asus) desde sysfs."""
    hwmon_root = Path("/sys/class/hwmon")
    cpu_temp_c = 0.0
    cpu_source = ""
    fallback_temp_c = 0.0
    fans: Dict[str, int] = {}

    if not hwmon_root.is_dir():
        return {"temp_c": 0.0, "source": "", "fan_rpm": fans}

    try:
        for hdir in sorted(hwmon_root.iterdir()):
            name_file = hdir / "name"
            if not name_file.is_file():
                continue
            name = name_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
            if name in ("k10temp", "coretemp", "zenpower"):
                tfile = hdir / "temp1_input"
                if tfile.is_file():
                    raw = tfile.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw.lstrip("-").isdigit():
                        cpu_temp_c = round(int(raw) / 1000.0, 1)
                        cpu_source = name
            elif name == "acpitz" and fallback_temp_c <= 0.0:
                tfile = hdir / "temp1_input"
                if tfile.is_file():
                    raw = tfile.read_text(encoding="utf-8", errors="ignore").strip()
                    if raw.lstrip("-").isdigit():
                        fallback_temp_c = round(int(raw) / 1000.0, 1)
            elif name == "asus":
                for idx, label in ((1, "cpu"), (2, "gpu")):
                    ffile = hdir / f"fan{idx}_input"
                    if ffile.is_file():
                        raw = ffile.read_text(encoding="utf-8", errors="ignore").strip()
                        if raw.isdigit():
                            fans[label] = int(raw)
    except Exception:
        pass

    if cpu_temp_c <= 0.0 and fallback_temp_c > 0.0:
        cpu_temp_c = fallback_temp_c
        cpu_source = "acpitz"

    return {"temp_c": cpu_temp_c, "source": cpu_source, "fan_rpm": fans}


def _read_cpu_power_profile() -> Dict[str, Any]:
    """Lee telemetría Ring 0 de cpufreq/amd-pstate-epp/boost y platform_profile vía sysfs (<0.1ms)."""
    def _read_txt(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            return ""

    cpufreq_dir = Path("/sys/devices/system/cpu/cpu0/cpufreq")
    driver = _read_txt(cpufreq_dir / "scaling_driver")
    governor = _read_txt(cpufreq_dir / "scaling_governor")
    epp = _read_txt(cpufreq_dir / "energy_performance_preference")
    boost_raw = _read_txt(Path("/sys/devices/system/cpu/cpufreq/boost"))
    boost_enabled: Optional[bool] = (
        boost_raw == "1" if boost_raw in ("0", "1") else None
    )
    platform_profile = _read_txt(Path("/sys/firmware/acpi/platform_profile")).lower()
    if platform_profile == "quiet":
        power_profile = "power-saver"
    elif platform_profile in ("balanced", "performance"):
        power_profile = platform_profile
    elif governor == "performance":
        power_profile = "performance"
    elif governor == "powersave":
        power_profile = "balanced"
    else:
        power_profile = ""

    return {
        "power_profile": power_profile,
        "platform_profile": platform_profile,
        "scaling_driver": driver,
        "scaling_governor": governor,
        "epp": epp,
        "boost": boost_enabled,
    }


def _power_profile_control_enabled() -> bool:
    """Desactiva cambios reales de powerprofilesctl durante pytest salvo habilitación explícita."""
    if os.environ.get("PYTEST_CURRENT_TEST") and str(os.environ.get("TARDIS_GOVERNOR_POWER_PROFILE_TEST", "0")) != "1":
        return False
    return str(os.environ.get("TARDIS_GOVERNOR_POWER_PROFILE_CONTROL", "1")).lower() not in ("0", "false", "no")


def _get_power_profile() -> str:
    """Obtiene el perfil energético activo vía powerprofilesctl (con fallback a sysfs)."""
    exe = shutil.which("powerprofilesctl")
    if exe:
        try:
            res = subprocess.run(
                [exe, "get"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().lower()
        except Exception:
            pass
    return str(_read_cpu_power_profile().get("power_profile") or "")


def _set_power_profile(profile: str) -> bool:
    """Conmuta el perfil energético del kernel (amd-pstate-epp + platform_profile) vía powerprofilesctl."""
    prof = (profile or "").strip().lower()
    if prof not in ("performance", "balanced", "power-saver"):
        return False
    exe = shutil.which("powerprofilesctl")
    if not exe:
        return False
    try:
        res = subprocess.run(
            [exe, "set", prof],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def _resolve_throttle_target_level(
    snap: Dict[str, Any],
    force_level: Optional[str] = None,
) -> Optional[str]:
    """Determina el nivel objetivo de throttling ('ORANGE'|'RED'|None) combinando nivel, PSI y térmicas."""
    if force_level:
        forced = str(force_level).strip().upper()
        return forced if forced in THROTTLE_PROFILES else None
    lvl = str(snap.get("level") or "GREEN").upper()
    if lvl in THROTTLE_PROFILES:
        return lvl
    cpu = snap.get("cpu") or {}
    cpu_psi_60 = float((cpu.get("psi") or {}).get("some_avg60", 0.0))
    cpu_temp_c = float(cpu.get("temp_c", 0.0))
    gpu_temp_c = float((snap.get("gpu") or {}).get("temp_c", 0.0))
    load1 = float(cpu.get("load1", 0.0))
    ncpus = max(1, int(cpu.get("cores") or os.cpu_count() or 16))
    # Trigger proactivo en YELLOW ante estrés combinado térmico (GPU/CPU) o contención severa PSI+Load
    if (
        (gpu_temp_c >= 72.0 and cpu_psi_60 >= 40.0)
        or (cpu_temp_c >= 78.0 and cpu_psi_60 >= 30.0)
        or (load1 >= ncpus * 1.1 and cpu_psi_60 >= 35.0)
    ):
        return "ORANGE"
    return None


def _is_thermal_or_heavy_psi(snap: Dict[str, Any], target_level: str) -> bool:
    """Indica si existe presión térmica CPU/GPU o contención PSI suficiente para aliviar inferencia y perfil energético."""
    cpu_psi_60 = float(((snap.get("cpu") or {}).get("psi") or {}).get("some_avg60", 0.0))
    cpu_temp_c = float((snap.get("cpu") or {}).get("temp_c", 0.0))
    gpu_temp_c = float((snap.get("gpu") or {}).get("temp_c", 0.0))
    return (
        target_level == "RED"
        or gpu_temp_c >= 78.0
        or cpu_temp_c >= 82.0
        or cpu_psi_60 >= 60.0
        or (cpu_temp_c >= 78.0 and cpu_psi_60 >= 30.0)
    )


def _needs_power_profile_step_down(
    snap: Dict[str, Any],
    target_level: str,
    throttle_st: Dict[str, Any],
) -> bool:
    """
    Detecta si el perfil energético Ring 0 debe bajar un escalón adicional
    (ej. performance -> balanced o balanced -> power-saver) aunque el nivel de throttling
    (p. ej. ORANGE) ya estuviera activo.
    """
    if not _is_thermal_or_heavy_psi(snap, target_level):
        return False
    cpu_temp_c = float((snap.get("cpu") or {}).get("temp_c", 0.0))
    gpu_temp_c = float((snap.get("gpu") or {}).get("temp_c", 0.0))
    severe_thermal = target_level == "RED" or cpu_temp_c >= 85.0 or gpu_temp_c >= 78.0
    desired_pp = "power-saver" if severe_thermal else "balanced"
    applied_pp = str(throttle_st.get("power_profile_applied") or "").strip().lower()
    live_pp = str((snap.get("cpu") or {}).get("power_profile") or "").strip().lower()
    pp_rank = {"power-saver": 0, "balanced": 1, "performance": 2}
    cur_pp = applied_pp or live_pp
    if cur_pp in pp_rank and pp_rank[cur_pp] > pp_rank[desired_pp]:
        return True
    return severe_thermal and applied_pp != "power-saver" and live_pp != "power-saver"


def _is_pure_transient_cpu_thermal_spike(snap: Dict[str, Any]) -> bool:
    """
    Detecta un pico térmico moderado aislado de CPU (82.0-85.9°C) sin contención PSI,
    GPU, RAM, swap ni loadavg, típico de micro-ráfagas Ryzen Tctl.
    """
    if bool(snap.get("call_priority_active", False)):
        return False
    if str(snap.get("level") or "GREEN").upper() != "ORANGE":
        return False
    cpu = snap.get("cpu") or {}
    mem = snap.get("memory") or {}
    gpu = snap.get("gpu") or {}
    cpu_temp_c = float(cpu.get("temp_c", 0.0))
    cpu_psi_60 = float((cpu.get("psi") or {}).get("some_avg60", 0.0))
    load1 = float(cpu.get("load1", 0.0))
    ncpus = max(1, int(cpu.get("cores") or os.cpu_count() or 16))
    gpu_temp_c = float(gpu.get("temp_c", 0.0))
    mem_avail = float(mem.get("available_mb", 99999.0))
    swap_used = float(mem.get("swap_used_mb", 0.0))
    return (
        82.0 <= cpu_temp_c < 86.0
        and cpu_psi_60 < 25.0
        and gpu_temp_c < 75.0
        and mem_avail >= 6000.0
        and swap_used < 10240.0
        and load1 < ncpus * 0.9
    )


def _is_in_safe_recovery_band(snap: Dict[str, Any]) -> bool:
    """
    Evalúa la banda muerta de recuperación (Schmitt trigger) para liberar throttling
    de forma segura: GREEN siempre, o YELLOW con holgura clara en PSI, CPU/GPU temp, RAM y load.
    """
    if bool(snap.get("call_priority_active", False)):
        return False
    lvl = str(snap.get("level") or "GREEN").upper()
    if lvl == "GREEN":
        return True
    if lvl != "YELLOW":
        return False
    cpu = snap.get("cpu") or {}
    mem = snap.get("memory") or {}
    gpu = snap.get("gpu") or {}
    cpu_psi_60 = float((cpu.get("psi") or {}).get("some_avg60", 0.0))
    cpu_temp_c = float(cpu.get("temp_c", 0.0))
    gpu_temp_c = float(gpu.get("temp_c", 0.0))
    mem_avail = float(mem.get("available_mb", 99999.0))
    swap_used = float(mem.get("swap_used_mb", 0.0))
    load1 = float(cpu.get("load1", 0.0))
    ncpus = max(1, int(cpu.get("cores") or os.cpu_count() or 16))
    return (
        cpu_psi_60 < 20.0
        and cpu_temp_c < 79.0
        and gpu_temp_c < 74.0
        and mem_avail >= 6000.0
        and swap_used < 10240.0
        and load1 < ncpus * 0.9
    )


def _read_meminfo_mb() -> Dict[str, float]:
    info: Dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            toks = rest.strip().split()
            if toks and toks[0].isdigit():
                info[k.strip()] = round(int(toks[0]) / 1024.0, 1)
    except Exception:
        pass
    total = info.get("MemTotal", 0.0)
    avail = info.get("MemAvailable", 0.0)
    used = max(0.0, total - avail)
    swap_total = info.get("SwapTotal", 0.0)
    swap_free = info.get("SwapFree", 0.0)
    swap_used = max(0.0, swap_total - swap_free)
    return {
        "total_mb": round(total, 1),
        "available_mb": round(avail, 1),
        "used_mb": round(used, 1),
        "used_pct": round((used / total) * 100.0, 1) if total > 0 else 0.0,
        "swap_total_mb": round(swap_total, 1),
        "swap_used_mb": round(swap_used, 1),
    }


def _read_loadavg() -> Tuple[float, float, float]:
    try:
        parts = Path("/proc/loadavg").read_text(encoding="utf-8").split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return 0.0, 0.0, 0.0


def _read_gpu() -> Dict[str, Any]:
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.free,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            cols = [c.strip() for c in res.stdout.strip().splitlines()[0].split(",")]
            if len(cols) >= 6:
                v_used = float(cols[3])
                v_tot = float(cols[5])
                return {
                    "available": True,
                    "name": cols[0],
                    "temp_c": float(cols[1]),
                    "util_pct": float(cols[2]),
                    "vram_used_mb": v_used,
                    "vram_free_mb": float(cols[4]),
                    "vram_total_mb": v_tot,
                    "vram_used_pct": round((v_used / v_tot) * 100.0, 1) if v_tot > 0 else 0.0,
                }
    except Exception:
        pass
    return {
        "available": False,
        "temp_c": 0.0,
        "util_pct": 0.0,
        "vram_used_mb": 0.0,
        "vram_free_mb": 0.0,
        "vram_total_mb": 0.0,
        "vram_used_pct": 0.0,
    }


def _extract_cli_int_flag(cmdline: str, flags: Tuple[str, ...]) -> int:
    """Extrae un valor entero de un flag CLI en cmdline (ej. '--threads-batch 16' o '-tb=16')."""
    if not cmdline:
        return 0
    for fl in flags:
        m = re.search(rf"(?:^|\s){re.escape(fl)}(?:=|\s+)(\d+)(?:\s|$)", cmdline)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
    return 0


def _count_runnable_threads(pid: int) -> int:
    """Cuenta hilos en estado 'R' (runnable/running) de un PID vía /proc/<pid>/task/*/stat."""
    task_dir = Path(f"/proc/{pid}/task")
    if not task_dir.is_dir():
        return 0
    runnable = 0
    try:
        for tid_dir in task_dir.iterdir():
            try:
                st = (tid_dir / "stat").read_text(encoding="utf-8", errors="ignore")
                rparen = st.rfind(")")
                if rparen > 0:
                    rest = st[rparen + 2 :].split()
                    if rest and rest[0] == "R":
                        runnable += 1
            except Exception:
                continue
    except Exception:
        pass
    return runnable


def _inspect_cgroup_units(
    units: Iterable[str] = ALL_INSPECTED_UNITS,
    cgroup_app_slice: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Inspecciona cgroup v2 (`app.slice/<unit>`) con latencia <1 ms (lectura pura sysfs/procfs):
      - Retorna `(cgroup_pressure, oversubscribed_units)`.
      - Detecta sobresuscripción de hilos frente al `cpuset.cpus.effective` real
        (causa clásica de thrashing de barrera ggml y CPU PSI > 60%).
    """
    uid = os.getuid()
    app_slice = cgroup_app_slice or Path(
        f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice"
    )
    if not app_slice.is_dir():
        return [], []

    pressure_rows: List[Dict[str, Any]] = []
    oversubscribed: List[Dict[str, Any]] = []

    for unit in units:
        cg = app_slice / unit
        if not cg.is_dir():
            continue
        try:
            cpuset_raw = ""
            for fname in ("cpuset.cpus.effective", "cpuset.cpus"):
                fp = cg / fname
                if fp.is_file():
                    cpuset_raw = fp.read_text(encoding="utf-8", errors="ignore").strip()
                    if cpuset_raw:
                        break
            eff_cpus = _parse_cpulist_count(cpuset_raw) or (os.cpu_count() or 1)
            cpu_max = (
                (cg / "cpu.max").read_text(encoding="utf-8", errors="ignore").strip()
                if (cg / "cpu.max").is_file()
                else "max"
            )
            cpu_weight_raw = (
                (cg / "cpu.weight").read_text(encoding="utf-8", errors="ignore").strip()
                if (cg / "cpu.weight").is_file()
                else ""
            )
            cpu_weight = int(cpu_weight_raw) if cpu_weight_raw.isdigit() else 100
            psi = _parse_psi_file(cg / "cpu.pressure")

            # Auditar sobresuscripción de hilos (individual y agregada multi-proceso) en el cgroup
            procs_file = cg / "cgroup.procs"
            pids: List[int] = []
            if procs_file.is_file():
                pids = [
                    int(line.strip())
                    for line in procs_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip().isdigit()
                ]

            pressure_rows.append(
                {
                    "unit": unit,
                    "cpuset_cpus": cpuset_raw or "all",
                    "effective_cpus": eff_cpus,
                    "cpu_max": cpu_max,
                    "cpu_weight": cpu_weight,
                    "pids_count": len(pids),
                    "psi_some_avg10": psi["some_avg10"],
                    "psi_some_avg60": psi["some_avg60"],
                    "psi_full_avg60": psi["full_avg60"],
                }
            )

            if pids and eff_cpus > 0:
                check_runnable = psi["some_avg60"] >= 15.0 or psi["some_avg10"] >= 25.0
                total_runnable = 0
                active_pids = 0
                unit_flagged_single = False
                top_runnable_pid = 0
                top_runnable_comm = ""
                top_runnable_count = 0

                for pid in pids[:16]:
                    try:
                        cmdline = (
                            Path(f"/proc/{pid}/cmdline")
                            .read_bytes()
                            .replace(b"\x00", b" ")
                            .decode("utf-8", errors="ignore")
                            .strip()
                        )
                        comm = (
                            Path(f"/proc/{pid}/comm")
                            .read_text(encoding="utf-8", errors="ignore")
                            .strip()
                        )
                    except Exception:
                        continue
                    cfg_threads = _extract_cli_int_flag(cmdline, ("--threads", "-t"))
                    cfg_batch = _extract_cli_int_flag(cmdline, ("--threads-batch", "-tb"))
                    max_cfg = max(cfg_threads, cfg_batch)
                    runnable = _count_runnable_threads(pid) if (check_runnable or max_cfg > eff_cpus) else 0
                    total_runnable += runnable
                    if runnable > 0:
                        active_pids += 1
                        if runnable > top_runnable_count:
                            top_runnable_count = runnable
                            top_runnable_pid = pid
                            top_runnable_comm = comm
                    if max_cfg > eff_cpus or runnable > eff_cpus:
                        unit_flagged_single = True
                        peak = max(max_cfg, runnable)
                        ratio = round(peak / float(eff_cpus), 2)
                        rec_gen = max(2, eff_cpus // 2)
                        oversubscribed.append(
                            {
                                "unit": unit,
                                "pid": pid,
                                "comm": comm,
                                "effective_cpus": eff_cpus,
                                "cpuset_cpus": cpuset_raw or "all",
                                "configured_threads": cfg_threads,
                                "configured_threads_batch": cfg_batch,
                                "runnable_threads": runnable,
                                "oversubscription_ratio": ratio,
                                "recommendation": f"Alinear --threads <= {rec_gen} y --threads-batch <= {eff_cpus} con --poll 0 para cpuset {cpuset_raw or 'all'}",
                            }
                        )

                if not unit_flagged_single and total_runnable > eff_cpus:
                    ratio = round(total_runnable / float(eff_cpus), 2)
                    rec_gen = max(2, eff_cpus // 2)
                    agg_comm = (
                        f"{top_runnable_comm or 'multi-proc'} (+{active_pids - 1} procs)"
                        if active_pids > 1
                        else (top_runnable_comm or "cgroup")
                    )
                    oversubscribed.append(
                        {
                            "unit": unit,
                            "pid": top_runnable_pid or pids[0],
                            "comm": agg_comm,
                            "effective_cpus": eff_cpus,
                            "cpuset_cpus": cpuset_raw or "all",
                            "configured_threads": 0,
                            "configured_threads_batch": 0,
                            "runnable_threads": total_runnable,
                            "active_pids": active_pids,
                            "oversubscription_ratio": ratio,
                            "recommendation": (
                                f"Acotar concurrencia agregada del cgroup ({total_runnable} hilos R en {active_pids} procesos) "
                                f"a <= {eff_cpus} hilos para cpuset {cpuset_raw or 'all'} (workers/threads <= {rec_gen})"
                            ),
                        }
                    )
        except Exception:
            continue

    pressure_rows.sort(key=lambda r: (r["psi_some_avg60"], r["psi_some_avg10"]), reverse=True)
    return pressure_rows, oversubscribed


def _query_ollama_ps(port: int) -> List[Dict[str, Any]]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            out = []
            for m in data.get("models") or []:
                out.append(
                    {
                        "name": str(m.get("name") or ""),
                        "size_mb": round(float(m.get("size") or 0) / (1024 * 1024), 1),
                        "size_vram_mb": round(float(m.get("size_vram") or 0) / (1024 * 1024), 1),
                        "expires_at": str(m.get("expires_at") or ""),
                    }
                )
            return out
    except Exception:
        return []


def _find_ollama_port_clients(port: int = 11434) -> List[Dict[str, Any]]:
    """Identifica procesos cliente con sockets TCP activos hacia el puerto Ollama indicado."""
    clients: List[Dict[str, Any]] = []
    seen_pids: set[int] = set()
    try:
        res = subprocess.run(
            ["ss", "-tnp", f"dport = :{int(port)}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode != 0:
            return clients

        for line in res.stdout.splitlines():
            for m in re.finditer(r'\("([^"]+)",pid=(\d+),fd=\d+\)', line):
                comm = m.group(1)
                pid = int(m.group(2))
                if pid in seen_pids or comm == "ollama":
                    continue
                seen_pids.add(pid)
                cmdline = ""
                cgroup = ""
                try:
                    cmdline = (
                        Path(f"/proc/{pid}/cmdline")
                        .read_bytes()
                        .replace(b"\x00", b" ")
                        .decode("utf-8", errors="ignore")
                        .strip()
                    )
                except Exception:
                    pass
                try:
                    cgroup = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="ignore").strip()
                except Exception:
                    pass
                unit = ""
                for seg in cgroup.split("/"):
                    if seg.endswith(".service"):
                        unit = seg
                clients.append(
                    {
                        "pid": pid,
                        "comm": comm,
                        "unit": unit,
                        "cmdline": cmdline[:180],
                    }
                )
    except Exception:
        pass
    return clients


def _is_call_active() -> bool:
    try:
        from core.telegram_call_priority import is_call_priority_active

        return bool(is_call_priority_active())
    except Exception:
        return False


def _systemd_control_enabled() -> bool:
    """Desactiva mutaciones reales sobre systemd --user durante pytest salvo habilitación explícita."""
    if os.environ.get("PYTEST_CURRENT_TEST") and str(os.environ.get("TARDIS_GOVERNOR_SYSTEMD_TEST", "0")) != "1":
        return False
    return str(os.environ.get("TARDIS_GOVERNOR_SYSTEMD_THROTTLE", "1")).lower() not in ("0", "false", "no")


def _systemd_quota_usec_to_pct(raw: str) -> str:
    """Convierte CPUQuotaPerSecUSec de `systemctl show` ('infinity', '1.5s', '500ms') a flag CPUQuota=."""
    val = (raw or "").strip().lower()
    if not val or val in ("infinity", "[not set]", "none"):
        return ""
    if val.endswith("%"):
        return val
    # Formatos systemd: '500ms', '1.5s', '1s 500ms', '2min'
    total_sec = 0.0
    matched = False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(min|ms|us|s)", val):
        matched = True
        v = float(num)
        if unit == "min":
            total_sec += v * 60.0
        elif unit == "s":
            total_sec += v
        elif unit == "ms":
            total_sec += v / 1000.0
        elif unit == "us":
            total_sec += v / 1_000_000.0
    if not matched or total_sec <= 0.0:
        return ""
    return f"{int(round(total_sec * 100.0))}%"


def _query_systemd_unit_props(unit: str) -> Optional[Dict[str, str]]:
    """Consulta ActiveState, CPUWeight, IOWeight y CPUQuotaPerSecUSec en systemd --user."""
    try:
        res = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                "-p",
                "ActiveState,CPUWeight,IOWeight,CPUQuotaPerSecUSec",
                unit,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.5,
            check=False,
        )
        if res.returncode != 0:
            return None
        props: Dict[str, str] = {}
        for line in (res.stdout or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        if props.get("ActiveState") != "active":
            return None
        return props
    except Exception:
        return None


def _apply_systemd_unit_props(
    unit: str,
    *,
    cpu_weight: Optional[int] = None,
    io_weight: Optional[int] = None,
    cpu_quota: Optional[str] = None,
) -> bool:
    """Aplica CPUWeight / IOWeight / CPUQuota en caliente (--runtime) sin reiniciar la unidad."""
    cmd = ["systemctl", "--user", "set-property", "--runtime", unit]
    if cpu_weight is not None:
        cmd.append(f"CPUWeight={max(1, min(10000, int(cpu_weight)))}")
    if io_weight is not None:
        cmd.append(f"IOWeight={max(1, min(10000, int(io_weight)))}")
    if cpu_quota is not None:
        # `CPUQuota=` (vacío) restablece a infinity (max) en cgroup v2.
        cmd.append(f"CPUQuota={cpu_quota}")
    if len(cmd) <= 5:
        return False
    try:
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


class TardisResourceGovernor:
    """Gobernador Ring 0, Árbitro de Inferencia y Controlador de Throttling cgroup v2 para TARDIS."""

    _instance: Optional["TardisResourceGovernor"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "TardisResourceGovernor":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=GOVERNOR_DB)
            return cls._instance

    def __init__(self, db_path: Path = GOVERNOR_DB, throttle_state_file: Optional[Path] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if throttle_state_file is not None:
            self.throttle_state_file = Path(throttle_state_file)
        elif self.db_path.resolve() == GOVERNOR_DB.resolve():
            self.throttle_state_file = THROTTLE_STATE_FILE
        else:
            self.throttle_state_file = self.db_path.parent / "tardis_governor_throttle.json"
        self._lock = threading.Lock()
        self._last_level: Optional[str] = None
        self._green_streak: int = 0
        self._safe_yellow_streak: int = 0
        self._thermal_orange_streak: int = 0
        self._stop_event = threading.Event()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=8.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    level TEXT NOT NULL,
                    cpu_psi_60 REAL,
                    cpu_temp_c REAL DEFAULT 0.0,
                    mem_avail_mb REAL,
                    swap_used_mb REAL,
                    load1 REAL,
                    gpu_temp_c REAL,
                    vram_used_mb REAL,
                    duplicate_models_count INTEGER DEFAULT 0,
                    reasons_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_gov_ts ON snapshots(ts);
                """
            )
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
            if "cpu_temp_c" not in cols:
                conn.execute("ALTER TABLE snapshots ADD COLUMN cpu_temp_c REAL DEFAULT 0.0")

    def _load_throttle_state(self) -> Dict[str, Any]:
        default_state: Dict[str, Any] = {
            "active": False,
            "level": "NONE",
            "updated_iso": "",
            "baselines": {},
            "applied": {},
            "power_profile_baseline": "",
            "power_profile_applied": "",
        }
        try:
            if self.throttle_state_file.is_file():
                raw = json.loads(self.throttle_state_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    default_state.update(raw)
        except Exception:
            pass
        return default_state

    def _save_throttle_state(self, state: Dict[str, Any]) -> None:
        _atomic_write_json(self.throttle_state_file, state)

    def get_throttle_status(self) -> Dict[str, Any]:
        st = self._load_throttle_state()
        applied = st.get("applied") if isinstance(st.get("applied"), dict) else {}
        return {
            "active": bool(st.get("active")),
            "level": str(st.get("level") or "NONE"),
            "throttled_units_count": len(applied),
            "units": sorted(applied.keys()),
            "power_profile_mitigated": bool(st.get("power_profile_applied")),
            "power_profile_applied": str(st.get("power_profile_applied") or ""),
            "updated_iso": str(st.get("updated_iso") or ""),
        }

    def collect_snapshot(self, persist: bool = True) -> Dict[str, Any]:
        """Recolecta telemetría Ring 0, detecta modelos duplicados, sobresuscripción y calcula presión."""
        cpu_psi = _parse_psi_file(Path("/proc/pressure/cpu"))
        mem_psi = _parse_psi_file(Path("/proc/pressure/memory"))
        io_psi = _parse_psi_file(Path("/proc/pressure/io"))
        cpu_thermal = _read_cpu_thermal()
        cpu_power = _read_cpu_power_profile()
        mem = _read_meminfo_mb()
        load1, load5, load15 = _read_loadavg()
        gpu = _read_gpu()
        ncpus = os.cpu_count() or 16
        call_active = _is_call_active()
        cgroup_pressure, oversubscribed_units = _inspect_cgroup_units()

        tb_active = Path("/tmp/temporal_brain.sock").exists()
        eb_active = Path("/tmp/embed_brain.sock").exists()
        ollama_11434 = _query_ollama_ps(11434)
        ollama_11435 = _query_ollama_ps(11435)

        # Detectar modelos duplicados en CPU Ollama :11434
        voice_models = {m["name"].split(":")[0].lower() for m in ollama_11435 if m.get("name")}
        duplicate_models: List[Dict[str, Any]] = []
        for m in ollama_11434:
            mname = m.get("name", "")
            base = mname.split(":")[0].lower()
            is_kaiju_dup = tb_active and ("kaiju" in base or "tardis-neural" in base)
            is_vlm_dup = base in voice_models and m.get("size_vram_mb", 0.0) == 0.0
            if is_kaiju_dup or is_vlm_dup:
                duplicate_models.append(
                    {
                        "port": 11434,
                        "model": mname,
                        "size_mb": m.get("size_mb", 0.0),
                        "reason": (
                            "duplicado_con_temporal_brain"
                            if is_kaiju_dup
                            else "duplicado_cpu_con_gpu_lane_11435"
                        ),
                    }
                )

        # Evaluar nivel de presión soberana
        reasons: List[str] = []
        level = "GREEN"

        def _escalate(target: str, reason: str) -> None:
            nonlocal level
            order = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
            reasons.append(reason)
            if order[target] > order[level]:
                level = target

        if call_active:
            _escalate("RED", "Llamada prioritaria de Telegram activa")
        if mem["available_mb"] < 1800:
            _escalate("RED", f"RAM disponible crítica ({mem['available_mb']:.0f} MB)")
        elif mem["available_mb"] < 3500:
            _escalate("ORANGE", f"RAM disponible baja ({mem['available_mb']:.0f} MB)")
        elif mem["available_mb"] < 6000:
            _escalate("YELLOW", f"RAM disponible moderada ({mem['available_mb']:.0f} MB)")

        if cpu_psi["some_avg60"] >= 75.0:
            _escalate("RED", f"CPU PSI avg60 crítico ({cpu_psi['some_avg60']:.1f}%)")
        elif cpu_psi["some_avg60"] >= 50.0:
            _escalate("ORANGE", f"CPU PSI avg60 elevado ({cpu_psi['some_avg60']:.1f}%)")
        elif cpu_psi["some_avg60"] >= 25.0:
            _escalate("YELLOW", f"CPU PSI avg60 moderado ({cpu_psi['some_avg60']:.1f}%)")

        cpu_temp_c = float(cpu_thermal.get("temp_c") or 0.0)
        if cpu_temp_c >= 88.0:
            _escalate("RED", f"Temperatura CPU crítica ({cpu_temp_c:.0f}°C)")
        elif cpu_temp_c >= 82.0:
            _escalate("ORANGE", f"Temperatura CPU elevada ({cpu_temp_c:.0f}°C)")
        elif cpu_temp_c >= 76.0:
            _escalate("YELLOW", f"Temperatura CPU cálida ({cpu_temp_c:.0f}°C)")

        if gpu.get("available"):
            if gpu["temp_c"] >= 85.0:
                _escalate("RED", f"Temperatura GPU crítica ({gpu['temp_c']:.0f}°C)")
            elif gpu["temp_c"] >= 78.0:
                _escalate("ORANGE", f"Temperatura GPU elevada ({gpu['temp_c']:.0f}°C)")
            elif gpu["temp_c"] >= 72.0:
                _escalate("YELLOW", f"Temperatura GPU cálida ({gpu['temp_c']:.0f}°C)")

        if mem["swap_used_mb"] >= 18432:
            _escalate("RED", f"Uso de swap crítico ({mem['swap_used_mb']/1024:.1f} GB)")
        elif mem["swap_used_mb"] >= 10240:
            _escalate("ORANGE", f"Uso de swap alto ({mem['swap_used_mb']/1024:.1f} GB)")

        if load1 >= ncpus * 1.6:
            _escalate("ORANGE", f"Loadavg1 saturado ({load1:.2f} en {ncpus} hilos)")
        elif load1 >= ncpus * 0.9:
            _escalate("YELLOW", f"Loadavg1 alto ({load1:.2f} en {ncpus} hilos)")

        if cpu_psi["some_avg60"] >= 45.0 and load1 >= ncpus * 1.25:
            _escalate(
                "ORANGE",
                f"Contención combinada CPU PSI/Load (PSI60={cpu_psi['some_avg60']:.1f}%, load1={load1:.2f}/{ncpus})",
            )

        if duplicate_models:
            wasted_mb = sum(d["size_mb"] for d in duplicate_models)
            reasons.append(f"{len(duplicate_models)} modelo(s) duplicado(s) en Ollama :11434 ({wasted_mb:.0f} MB)")

        if oversubscribed_units:
            top_ov = oversubscribed_units[0]
            peak_th = max(
                int(top_ov.get("configured_threads_batch") or 0),
                int(top_ov.get("configured_threads") or 0),
                int(top_ov.get("runnable_threads") or 0),
            )
            reasons.append(
                f"Sobresuscripción de hilos en {top_ov['unit']} ({peak_th} hilos en {top_ov['effective_cpus']} CPUs)"
            )

        sleep_mult = {"GREEN": 1.0, "YELLOW": 1.5, "ORANGE": 2.5, "RED": 5.0}[level]
        yolo_mult = {"GREEN": 1.0, "YELLOW": 1.5, "ORANGE": 2.5, "RED": 3.5}[level]
        admission = {
            "interactive": True,
            "critical_repair": True,
            "agy_discovery": (not call_active) and (level in ("GREEN", "YELLOW", "ORANGE")) and mem["available_mb"] >= 2000,
            "heavy_learning": (not call_active) and (level in ("GREEN", "YELLOW")) and cpu_psi["some_avg60"] < 35.0 and load1 < ncpus * 1.1,
            "idle_evolution": (not call_active) and (level in ("GREEN", "YELLOW")) and cpu_psi["some_avg60"] < 30.0 and load1 < ncpus * 0.9,
            "video_render": (not call_active) and (level == "GREEN") and gpu.get("temp_c", 0.0) < 74.0,
            "recommended_sleep_multiplier": sleep_mult,
            "recommended_yolo_interval_mult": yolo_mult,
        }

        now = time.time()
        iso = _now_iso()
        snap = {
            "ok": True,
            "ts": now,
            "iso": iso,
            "level": level,
            "reasons": reasons or ["Operación nominal con holgura de recursos"],
            "call_priority_active": call_active,
            "cpu": {
                "cores": ncpus,
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "psi": cpu_psi,
                "temp_c": cpu_temp_c,
                "thermal_source": cpu_thermal.get("source", ""),
                "fan_rpm": cpu_thermal.get("fan_rpm", {}),
                "power_profile": cpu_power.get("power_profile", ""),
                "scaling_driver": cpu_power.get("scaling_driver", ""),
                "scaling_governor": cpu_power.get("scaling_governor", ""),
                "epp": cpu_power.get("epp", ""),
                "boost": cpu_power.get("boost"),
            },
            "memory": {**mem, "psi": mem_psi},
            "io": {"psi": io_psi},
            "gpu": gpu,
            "inference_lanes": {
                "temporal_brain_sock": tb_active,
                "embed_brain_sock": eb_active,
                "ollama_11434": ollama_11434,
                "ollama_11435_gpu_voice": ollama_11435,
                "duplicate_models": duplicate_models,
            },
            "cgroup_pressure": cgroup_pressure[:8],
            "oversubscribed_units": oversubscribed_units,
            "throttling": self.get_throttle_status(),
            "admission": admission,
        }

        if persist:
            _atomic_write_json(TMPFS_SNAPSHOT, snap)
            _atomic_write_json(DISK_SNAPSHOT, snap)
            self._persist_db(snap)
            self._emit_transition_if_needed(snap)

        return snap

    def _persist_db(self, snap: Dict[str, Any]) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO snapshots
                        (ts, iso, level, cpu_psi_60, cpu_temp_c, mem_avail_mb, swap_used_mb, load1, gpu_temp_c, vram_used_mb, duplicate_models_count, reasons_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snap["ts"],
                        snap["iso"],
                        snap["level"],
                        snap["cpu"]["psi"]["some_avg60"],
                        float(snap["cpu"].get("temp_c", 0.0)),
                        snap["memory"]["available_mb"],
                        snap["memory"]["swap_used_mb"],
                        snap["cpu"]["load1"],
                        snap["gpu"].get("temp_c", 0.0),
                        snap["gpu"].get("vram_used_mb", 0.0),
                        len(snap["inference_lanes"]["duplicate_models"]),
                        json.dumps(snap["reasons"], ensure_ascii=False),
                    ),
                )
                # Retener últimos 5000 snapshots (~28 horas a 20s)
                conn.execute(
                    "DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 5000)"
                )
        except Exception:
            pass

    def _emit_transition_if_needed(self, snap: Dict[str, Any]) -> None:
        lvl = snap["level"]
        if self._last_level != lvl and lvl in ("ORANGE", "RED"):
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "telemetry.pressure",
                    "tardis_resource_governor",
                    {
                        "from_level": self._last_level or "INIT",
                        "to_level": lvl,
                        "reasons": snap["reasons"],
                        "mem_avail_mb": snap["memory"]["available_mb"],
                        "cpu_psi_60": snap["cpu"]["psi"]["some_avg60"],
                        "cpu_temp_c": snap["cpu"].get("temp_c", 0.0),
                        "gpu_temp_c": snap["gpu"].get("temp_c", 0.0),
                        "duplicate_models": snap["inference_lanes"]["duplicate_models"],
                        "oversubscribed_units": snap.get("oversubscribed_units") or [],
                    },
                    severity="HIGH" if lvl == "RED" else "MEDIUM",
                    dedup_key=f"pressure|{lvl}",
                    dedup_window_s=300.0,
                )
            except Exception:
                pass
        self._last_level = lvl

    def read_fast_snapshot(self, max_age_s: float = 45.0) -> Dict[str, Any]:
        """Lectura ultrarrápida desde tmpfs (<0.1ms); recolecta en vivo si está vencido."""
        for p in (TMPFS_SNAPSHOT, DISK_SNAPSHOT):
            if p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and (time.time() - float(data.get("ts", 0))) <= max_age_s:
                        return data
                except Exception:
                    continue
        return self.collect_snapshot(persist=True)

    def admit(self, task_class: str = "heavy_learning") -> Dict[str, Any]:
        """Decide en <1ms si una clase de tarea debe ejecutarse o diferirse."""
        snap = self.read_fast_snapshot()
        cls = (task_class or "heavy_learning").strip().lower()
        allowed = bool((snap.get("admission") or {}).get(cls, snap.get("level") in ("GREEN", "YELLOW")))
        return {
            "ok": True,
            "task_class": cls,
            "allowed": allowed,
            "level": snap.get("level", "GREEN"),
            "recommended_sleep_multiplier": (snap.get("admission") or {}).get("recommended_sleep_multiplier", 1.0),
            "recommended_yolo_interval_mult": (snap.get("admission") or {}).get("recommended_yolo_interval_mult", 1.0),
            "reasons": snap.get("reasons", []),
            "iso": snap.get("iso", _now_iso()),
        }

    def apply_throttling(
        self,
        snap: Optional[Dict[str, Any]] = None,
        *,
        dry_run: bool = False,
        force_level: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aplica throttling cgroup v2 reversible en caliente (--runtime) sobre unidades de fondo
        y vigilancia de systemd --user cuando el sistema entra en ORANGE/RED o estrés térmico.
        Nunca interfiere con llamadas prioritarias de Telegram ni con unidades protegidas.
        """
        current_snap = snap if isinstance(snap, dict) else self.collect_snapshot(persist=False)
        call_active = bool(current_snap.get("call_priority_active", False))
        if call_active and not force_level:
            return {
                "ok": True,
                "action": "skipped",
                "skipped_reason": "telegram_call_priority_active",
                "level": current_snap.get("level", "RED"),
                "dry_run": dry_run,
                "applied_units": [],
                "iso": _now_iso(),
            }

        target_level = _resolve_throttle_target_level(current_snap, force_level=force_level)
        cpu_psi_60 = float(((current_snap.get("cpu") or {}).get("psi") or {}).get("some_avg60", 0.0))
        cpu_temp_c = float((current_snap.get("cpu") or {}).get("temp_c", 0.0))
        gpu_temp_c = float((current_snap.get("gpu") or {}).get("temp_c", 0.0))

        if target_level is None:
            return {
                "ok": True,
                "action": "noop_within_budget",
                "level": str(current_snap.get("level") or "GREEN").upper(),
                "dry_run": dry_run,
                "applied_units": [],
                "power_profile_action": "unchanged",
                "iso": _now_iso(),
            }

        if not _systemd_control_enabled():
            return {
                "ok": True,
                "action": "skipped",
                "skipped_reason": "systemd_control_disabled",
                "level": target_level,
                "dry_run": dry_run,
                "applied_units": [],
                "power_profile_action": "skipped",
                "iso": _now_iso(),
            }

        profile = THROTTLE_PROFILES[target_level]
        thermal_or_heavy_psi = _is_thermal_or_heavy_psi(current_snap, target_level)

        plan: List[Tuple[str, Dict[str, Any]]] = []
        for u in BACKGROUND_THROTTLE_UNITS:
            if u not in PROTECTED_UNITS:
                plan.append((u, profile["background"]))
        for u in SENTINEL_THROTTLE_UNITS:
            if u not in PROTECTED_UNITS:
                plan.append((u, profile["sentinel"]))
        if thermal_or_heavy_psi and "tardis-temporal-brain.service" not in PROTECTED_UNITS:
            plan.append(("tardis-temporal-brain.service", profile["inference_thermal"]))

        plan_unit_names = {u for u, _ in plan}

        with self._lock:
            state = self._load_throttle_state()
            baselines: Dict[str, Dict[str, str]] = dict(state.get("baselines") or {})
            applied_map: Dict[str, Dict[str, Any]] = dict(state.get("applied") or {})
            power_profile_baseline = str(state.get("power_profile_baseline") or "")
            power_profile_applied = str(state.get("power_profile_applied") or "")
            applied_units: List[Dict[str, Any]] = []
            errors: List[str] = []

            for unit, spec in plan:
                props = _query_systemd_unit_props(unit)
                if not props:
                    continue
                if unit not in baselines:
                    baselines[unit] = {
                        "CPUWeight": props.get("CPUWeight", "100"),
                        "IOWeight": props.get("IOWeight", "100"),
                        "CPUQuota": _systemd_quota_usec_to_pct(props.get("CPUQuotaPerSecUSec", "infinity")),
                    }

                desired = {
                    "cpu_weight": int(spec["cpu_weight"]),
                    "io_weight": int(spec["io_weight"]),
                    "cpu_quota": str(spec["cpu_quota"]),
                }
                if dry_run:
                    applied_units.append({"unit": unit, "action": "would_throttle", **desired})
                    continue

                # Idempotencia verificada contra el estado vivo en systemd (detecta drift por reinicios)
                live_cw = str(props.get("CPUWeight") or "").strip()
                live_iw = str(props.get("IOWeight") or "").strip()
                live_cq = _systemd_quota_usec_to_pct(props.get("CPUQuotaPerSecUSec", "infinity"))
                live_matches = (
                    live_cw == str(desired["cpu_weight"])
                    and live_iw == str(desired["io_weight"])
                    and live_cq == desired["cpu_quota"]
                )
                if applied_map.get(unit) == desired and state.get("level") == target_level and live_matches:
                    applied_units.append({"unit": unit, "action": "already_throttled", **desired})
                    continue

                ok = _apply_systemd_unit_props(
                    unit,
                    cpu_weight=desired["cpu_weight"],
                    io_weight=desired["io_weight"],
                    cpu_quota=desired["cpu_quota"],
                )
                if ok:
                    applied_map[unit] = desired
                    applied_units.append({"unit": unit, "action": "throttled", **desired})
                else:
                    errors.append(f"set-property {unit} failed")

            # De-escalación parcial: liberar unidades que salieron del plan (ej. TemporalBrain tras bajar térmica)
            for unit in [u for u in list(applied_map.keys()) if u not in plan_unit_names]:
                base = baselines.get(unit) or {}
                cw_raw = str(base.get("CPUWeight") or "100").strip()
                iw_raw = str(base.get("IOWeight") or "100").strip()
                cw = int(cw_raw) if cw_raw.isdigit() else 100
                iw = int(iw_raw) if iw_raw.isdigit() else 100
                cq = str(base.get("CPUQuota") or "").strip()
                if dry_run:
                    applied_units.append(
                        {"unit": unit, "action": "would_release_from_plan", "cpu_weight": cw, "io_weight": iw, "cpu_quota": cq or "infinity"}
                    )
                    continue
                ok = _apply_systemd_unit_props(unit, cpu_weight=cw, io_weight=iw, cpu_quota=cq)
                if ok:
                    applied_map.pop(unit, None)
                    baselines.pop(unit, None)
                    applied_units.append(
                        {"unit": unit, "action": "released_from_plan", "cpu_weight": cw, "io_weight": iw, "cpu_quota": cq or "infinity"}
                    )
                else:
                    errors.append(f"release-from-plan {unit} failed")

            # Mitigación térmica Ring 0 en 2 etapas (amd-pstate-epp + platform_profile):
            # - ORANGE moderado (<85°C CPU y <78°C GPU): performance -> balanced
            # - Presión térmica severa (RED o CPU >=85°C o GPU >=78°C): performance/balanced -> power-saver
            power_profile_action = "unchanged"
            if thermal_or_heavy_psi and _power_profile_control_enabled():
                cur_pp = _get_power_profile()
                pp_rank = {"power-saver": 0, "balanced": 1, "performance": 2}
                severe_thermal = target_level == "RED" or cpu_temp_c >= 85.0 or gpu_temp_c >= 78.0
                desired_pp = "power-saver" if severe_thermal else "balanced"
                if cur_pp in pp_rank and pp_rank[cur_pp] > pp_rank[desired_pp]:
                    if dry_run:
                        power_profile_action = f"would_switch_to_{desired_pp}"
                    elif _set_power_profile(desired_pp):
                        if not power_profile_baseline:
                            power_profile_baseline = cur_pp
                        power_profile_applied = desired_pp
                        power_profile_action = f"switched_to_{desired_pp}"
                    else:
                        errors.append(f"powerprofilesctl set {desired_pp} failed")
                elif cur_pp == desired_pp and power_profile_applied == desired_pp:
                    power_profile_action = f"already_{desired_pp}"

            if not dry_run and (applied_map or power_profile_applied):
                new_state = {
                    "active": bool(applied_map),
                    "level": target_level if applied_map else "NONE",
                    "updated_iso": _now_iso(),
                    "baselines": baselines,
                    "applied": applied_map,
                    "power_profile_baseline": power_profile_baseline,
                    "power_profile_applied": power_profile_applied,
                }
                self._save_throttle_state(new_state)

        changed = [u for u in applied_units if u["action"] in ("throttled", "released_from_plan")]
        pp_switched = power_profile_action.startswith("switched_to_")
        if not dry_run and (changed or pp_switched):
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "governor.throttle",
                    "tardis_resource_governor",
                    {
                        "level": target_level,
                        "cpu_psi_60": cpu_psi_60,
                        "cpu_temp_c": cpu_temp_c,
                        "gpu_temp_c": gpu_temp_c,
                        "power_profile_action": power_profile_action,
                        "units": [u["unit"] for u in changed],
                    },
                    severity="MEDIUM" if target_level == "ORANGE" else "HIGH",
                    dedup_key=f"throttle|{target_level}",
                    dedup_window_s=120.0,
                )
            except Exception:
                pass

        return {
            "ok": len(errors) == 0,
            "action": "would_throttle" if dry_run else ("throttled" if (changed or pp_switched) else "maintained"),
            "level": target_level,
            "dry_run": dry_run,
            "applied_units": applied_units,
            "power_profile_action": power_profile_action,
            "errors": errors,
            "iso": _now_iso(),
        }

    def release_throttling(
        self,
        *,
        dry_run: bool = False,
        snap: Optional[Dict[str, Any]] = None,
        force_restore_power_profile: bool = False,
    ) -> Dict[str, Any]:
        """Restaura parámetros cgroup v2 originales y, con holgura térmica suficiente, el perfil energético base."""
        with self._lock:
            state = self._load_throttle_state()
            baselines: Dict[str, Dict[str, str]] = dict(state.get("baselines") or {})
            power_profile_baseline = str(state.get("power_profile_baseline") or "")
            power_profile_applied = str(state.get("power_profile_applied") or "")
            if not baselines and not state.get("active") and not power_profile_baseline:
                return {
                    "ok": True,
                    "action": "noop_not_throttled",
                    "dry_run": dry_run,
                    "restored_units": [],
                    "power_profile_action": "unchanged",
                    "errors": [],
                    "iso": _now_iso(),
                }

            if not _systemd_control_enabled():
                return {
                    "ok": True,
                    "action": "skipped",
                    "skipped_reason": "systemd_control_disabled",
                    "dry_run": dry_run,
                    "restored_units": [],
                    "power_profile_action": "skipped",
                    "errors": [],
                    "iso": _now_iso(),
                }

            restored: List[Dict[str, Any]] = []
            errors: List[str] = []
            for unit, base in baselines.items():
                cw_raw = str(base.get("CPUWeight") or "100").strip()
                iw_raw = str(base.get("IOWeight") or "100").strip()
                cw = int(cw_raw) if cw_raw.isdigit() else 100
                iw = int(iw_raw) if iw_raw.isdigit() else 100
                cq = str(base.get("CPUQuota") or "").strip()
                if dry_run:
                    restored.append({"unit": unit, "action": "would_restore", "cpu_weight": cw, "io_weight": iw, "cpu_quota": cq or "infinity"})
                    continue
                ok = _apply_systemd_unit_props(unit, cpu_weight=cw, io_weight=iw, cpu_quota=cq)
                if ok:
                    restored.append({"unit": unit, "action": "restored", "cpu_weight": cw, "io_weight": iw, "cpu_quota": cq or "infinity"})
                else:
                    errors.append(f"restore {unit} failed")

            # Evaluar restauración segura del perfil energético base según margen térmico real
            power_profile_action = "unchanged"
            next_pp_base = power_profile_baseline
            next_pp_applied = power_profile_applied
            if power_profile_baseline and _power_profile_control_enabled():
                if isinstance(snap, dict):
                    cur_cpu_c = float((snap.get("cpu") or {}).get("temp_c", 0.0))
                    cur_gpu_c = float((snap.get("gpu") or {}).get("temp_c", 0.0))
                else:
                    cur_cpu_c = float(_read_cpu_thermal().get("temp_c", 0.0))
                    cur_gpu_c = 0.0
                cool_enough = (
                    force_restore_power_profile
                    or (cur_cpu_c <= POWER_PROFILE_RESTORE_MAX_CPU_C and cur_gpu_c <= POWER_PROFILE_RESTORE_MAX_GPU_C)
                )
                if cool_enough:
                    if dry_run:
                        power_profile_action = f"would_restore_{power_profile_baseline}"
                    elif _set_power_profile(power_profile_baseline):
                        power_profile_action = f"restored_{power_profile_baseline}"
                        next_pp_base = ""
                        next_pp_applied = ""
                    else:
                        errors.append(f"powerprofilesctl restore {power_profile_baseline} failed")
                elif power_profile_applied == "power-saver" and cur_cpu_c < 82.0 and cur_gpu_c < 76.0:
                    if dry_run:
                        power_profile_action = "would_step_back_to_balanced"
                    elif _set_power_profile("balanced"):
                        power_profile_action = "stepped_back_to_balanced"
                        next_pp_applied = "balanced"
                        if power_profile_baseline == "balanced":
                            next_pp_base = ""
                            next_pp_applied = ""
                    else:
                        errors.append("powerprofilesctl step-back balanced failed")
                else:
                    power_profile_action = f"kept_{power_profile_applied or 'balanced'}_thermal_headroom"

            if not dry_run:
                self._save_throttle_state(
                    {
                        "active": False,
                        "level": "NONE",
                        "updated_iso": _now_iso(),
                        "baselines": {},
                        "applied": {},
                        "power_profile_baseline": next_pp_base,
                        "power_profile_applied": next_pp_applied,
                    }
                )

        if not dry_run and (restored or power_profile_action.startswith("restored_")):
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "governor.throttle_released",
                    "tardis_resource_governor",
                    {
                        "units": [r["unit"] for r in restored],
                        "power_profile_action": power_profile_action,
                    },
                    severity="INFO",
                    dedup_window_s=60.0,
                )
            except Exception:
                pass

        action_label = "would_restore" if dry_run else (
            "restored" if (restored or power_profile_action.startswith("restored_")) else "kept_balanced_thermal_headroom"
        )
        return {
            "ok": len(errors) == 0,
            "action": action_label,
            "dry_run": dry_run,
            "restored_units": restored,
            "power_profile_action": power_profile_action,
            "errors": errors,
            "iso": _now_iso(),
        }

    def reclaim_resources(
        self,
        *,
        dry_run: bool = False,
        prune_backups: bool = True,
        keep_backups_per_file: int = 2,
        apply_throttle: bool = True,
    ) -> Dict[str, Any]:
        """
        Acciones seguras y deterministas de estabilización Ring 0:
          1. Descarga modelos LLM duplicados en CPU Ollama :11434 (keep_alive=0) y, bajo RAM crítica
             en nivel RED (<3500 MB), también descarga modelos CPU-only ociosos en :11434.
          2. Reconcilia throttling cgroup v2 en caliente (--runtime) ante presión ORANGE/RED o
             estrés térmico, y libera throttling automáticamente al estabilizar en GREEN.
          3. Archiva/poda archivos `.bak*` obsoletos acumulados dentro de GODWORKS SYSTEM.
          4. Reporta sobresuscripciones de hilos vs cpuset para remediación estructural.
        """
        snap_before = self.collect_snapshot(persist=False)
        evicted: List[Dict[str, Any]] = []
        errors: List[str] = []

        lanes_before = snap_before.get("inference_lanes") or {}
        mem_before = snap_before.get("memory") or {}
        cpu_before = snap_before.get("cpu") or {}
        gpu_before = snap_before.get("gpu") or {}
        level_before = str(snap_before.get("level") or "GREEN")
        mem_avail_before = float(mem_before.get("available_mb", 0.0))
        cpu_psi60_before = float((cpu_before.get("psi") or {}).get("some_avg60", 0.0))
        cpu_temp_before = float(cpu_before.get("temp_c", 0.0))
        gpu_temp_before = float(gpu_before.get("temp_c", 0.0))
        power_profile_before = str(cpu_before.get("power_profile") or "")

        # 1. Evict duplicate CPU models from Ollama :11434 (verificando post-evicción en /api/ps)
        candidates: List[Dict[str, Any]] = list(lanes_before.get("duplicate_models") or [])
        seen_models = {str(c.get("model") or "") for c in candidates}
        # Bajo RAM crítica en RED (<3500 MB) o estrés sostenido de CPU/térmicas en ORANGE/RED,
        # descargar también modelos CPU-only ociosos en :11434 para liberar ciclos y memoria.
        evict_cpu_only_reason = ""
        if level_before == "RED" and mem_avail_before < 3500.0:
            evict_cpu_only_reason = "red_memory_pressure_cpu_eviction"
        elif level_before in ("ORANGE", "RED") and (cpu_psi60_before >= 30.0 or cpu_temp_before >= 82.0):
            evict_cpu_only_reason = "cpu_psi_or_thermal_pressure_eviction"

        if evict_cpu_only_reason:
            for m in lanes_before.get("ollama_11434") or []:
                mname = str(m.get("name") or "")
                if mname and mname not in seen_models and float(m.get("size_vram_mb", 0.0)) == 0.0:
                    seen_models.add(mname)
                    candidates.append(
                        {
                            "port": 11434,
                            "model": mname,
                            "size_mb": float(m.get("size_mb", 0.0)),
                            "reason": evict_cpu_only_reason,
                        }
                    )

        in_flight_clients: List[Dict[str, Any]] = []
        for dup in candidates:
            model_name = dup["model"]
            if dry_run:
                evicted.append(
                    {
                        "model": model_name,
                        "port": 11434,
                        "size_mb": dup.get("size_mb", 0.0),
                        "reason": dup.get("reason", ""),
                        "action": "would_unload",
                    }
                )
                continue
            try:
                payload = json.dumps({"model": model_name, "prompt": "", "keep_alive": 0}).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:11434/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=12.0) as r:
                    _ = r.read()
                # Verificar empíricamente (hasta 3 sondeos breves) si Ollama descargó el runner
                # o si sigue retenido por una inferencia in-flight.
                still_resident = True
                for _poll_i in range(3):
                    time.sleep(0.35)
                    still_resident = any(m.get("name") == model_name for m in _query_ollama_ps(11434))
                    if not still_resident:
                        break
                if still_resident:
                    if not in_flight_clients:
                        in_flight_clients = _find_ollama_port_clients(11434)
                    evicted.append(
                        {
                            "model": model_name,
                            "port": 11434,
                            "size_mb": dup.get("size_mb", 0.0),
                            "reason": dup.get("reason", ""),
                            "action": "unload_deferred_in_flight",
                            "active_clients": in_flight_clients,
                        }
                    )
                else:
                    evicted.append(
                        {
                            "model": model_name,
                            "port": 11434,
                            "size_mb": dup.get("size_mb", 0.0),
                            "reason": dup.get("reason", ""),
                            "action": "unloaded",
                        }
                    )
            except Exception as exc:
                errors.append(f"unload {model_name}: {exc}")

        # 2. Reconciliación activa de throttling Ring 0 (cgroup v2 --runtime + perfil energético)
        throttling_result: Dict[str, Any] = {"ok": True, "action": "disabled", "applied_units": []}
        if apply_throttle:
            target_lvl = _resolve_throttle_target_level(snap_before)
            throttle_status = self.get_throttle_status()
            if target_lvl is not None:
                throttling_result = self.apply_throttling(snap_before, dry_run=dry_run)
                for err in throttling_result.get("errors") or []:
                    errors.append(f"throttle: {err}")
            elif (throttle_status.get("active") or throttle_status.get("power_profile_mitigated")) and _is_in_safe_recovery_band(snap_before):
                throttling_result = self.release_throttling(dry_run=dry_run, snap=snap_before)
                for err in throttling_result.get("errors") or []:
                    errors.append(f"release: {err}")
            else:
                throttling_result = {
                    "ok": True,
                    "action": "noop_within_budget",
                    "level": level_before,
                    "dry_run": dry_run,
                    "applied_units": [],
                    "power_profile_action": "unchanged",
                }

        # 3. Podar/archivar backups `.bak*` redundantes o antiguos en GODWORKS SYSTEM raíz y core/
        pruned_count = 0
        pruned_bytes = 0
        archived_count = 0
        if prune_backups:
            by_origin: Dict[str, List[Path]] = {}
            now_ts = time.time()
            stale_cutoff = now_ts - (STALE_BACKUP_ARCHIVE_DAYS * 86400.0)
            for scan_dir in (PROJECT_ROOT, PROJECT_ROOT / "core"):
                if not scan_dir.is_dir():
                    continue
                for p in scan_dir.glob("*.bak*"):
                    if not p.is_file():
                        continue
                    origin = f"{scan_dir.name}/{p.name.split('.bak')[0]}"
                    by_origin.setdefault(origin, []).append(p)

            if not dry_run:
                BACKUP_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

            for origin, files in by_origin.items():
                ordered = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
                keep = ordered[: max(0, int(keep_backups_per_file))]
                drop = ordered[max(0, int(keep_backups_per_file)) :]

                # Mover al archivo ordenado si hay >3 backups por origen o si un .bak* suelto tiene >7 días
                for k in keep:
                    try:
                        should_archive = len(files) > 3 or k.stat().st_mtime < stale_cutoff
                    except OSError:
                        should_archive = len(files) > 3
                    if not should_archive:
                        continue
                    if not dry_run:
                        dst = BACKUP_ARCHIVE_DIR / k.name
                        try:
                            shutil.move(str(k), str(dst))
                            archived_count += 1
                        except Exception:
                            pass
                    else:
                        archived_count += 1

                for d in drop:
                    try:
                        sz = d.stat().st_size
                        if not dry_run:
                            d.unlink(missing_ok=True)
                        pruned_count += 1
                        pruned_bytes += sz
                    except Exception as exc:
                        errors.append(f"unlink {d.name}: {exc}")

        snap_after = self.collect_snapshot(persist=not dry_run)
        mem_after = snap_after.get("memory") or {}
        cpu_after = snap_after.get("cpu") or {}
        gpu_after = snap_after.get("gpu") or {}
        oversubscribed_after = snap_after.get("oversubscribed_units") or []

        result = {
            "ok": True,
            "dry_run": dry_run,
            "models_evicted": evicted,
            "throttling": throttling_result,
            "oversubscribed_units": oversubscribed_after,
            "backups_pruned": pruned_count,
            "backups_archived": archived_count,
            "bytes_reclaimed_disk": pruned_bytes,
            "mem_available_before_mb": mem_avail_before,
            "mem_available_after_mb": float(mem_after.get("available_mb", 0.0)),
            "cpu_psi60_before": cpu_psi60_before,
            "cpu_psi60_after": float((cpu_after.get("psi") or {}).get("some_avg60", 0.0)),
            "cpu_temp_before_c": cpu_temp_before,
            "cpu_temp_after_c": float(cpu_after.get("temp_c", 0.0)),
            "gpu_temp_before_c": gpu_temp_before,
            "gpu_temp_after_c": float(gpu_after.get("temp_c", 0.0)),
            "power_profile_before": power_profile_before,
            "power_profile_after": str(cpu_after.get("power_profile") or ""),
            "level_before": level_before,
            "level_after": str(snap_after.get("level") or "GREEN"),
            "errors": errors,
            "iso": _now_iso(),
        }

        if not dry_run and (
            evicted
            or pruned_count > 0
            or archived_count > 0
            or throttling_result.get("action") in ("throttled", "restored")
            or oversubscribed_after
        ):
            try:
                from core.tardis_event_bus import get_event_bus

                deferred = [e for e in evicted if e.get("action") == "unload_deferred_in_flight"]
                unloaded = [e for e in evicted if e.get("action") == "unloaded"]
                if unloaded or pruned_count > 0 or archived_count > 0 or throttling_result.get("action") in ("throttled", "restored"):
                    get_event_bus().publish(
                        "governor.reclaim",
                        "tardis_resource_governor",
                        {
                            "models_evicted": [e["model"] for e in unloaded],
                            "models_deferred_in_flight": [e["model"] for e in deferred],
                            "throttling_action": throttling_result.get("action"),
                            "power_profile_action": throttling_result.get("power_profile_action", "unchanged"),
                            "throttled_units": [
                                u["unit"] for u in (throttling_result.get("applied_units") or [])
                            ],
                            "backups_pruned": pruned_count,
                            "backups_archived": archived_count,
                            "mem_before_mb": mem_avail_before,
                            "mem_after_mb": float(mem_after.get("available_mb", 0.0)),
                            "cpu_psi60_before": result["cpu_psi60_before"],
                            "cpu_psi60_after": result["cpu_psi60_after"],
                            "cpu_temp_before_c": result["cpu_temp_before_c"],
                            "cpu_temp_after_c": result["cpu_temp_after_c"],
                        },
                        severity="INFO",
                        dedup_window_s=60.0,
                    )
                if deferred:
                    get_event_bus().publish(
                        "sentinel.anomaly",
                        "tardis_resource_governor",
                        {
                            "anomaly": "ollama_11434_duplicate_pinned_in_flight",
                            "models": [e["model"] for e in deferred],
                            "active_clients": deferred[0].get("active_clients") or [],
                        },
                        severity="HIGH",
                        dedup_key="ollama_11434_pinned_in_flight",
                        dedup_window_s=300.0,
                    )
                if oversubscribed_after:
                    get_event_bus().publish(
                        "sentinel.anomaly",
                        "tardis_resource_governor",
                        {
                            "anomaly": "cpuset_thread_oversubscription",
                            "units": oversubscribed_after,
                        },
                        severity="HIGH",
                        dedup_key=f"cpuset_oversub|{oversubscribed_after[0]['unit']}",
                        dedup_window_s=600.0,
                    )
            except Exception:
                pass
        return result

    def history(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY id DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def run_daemon(self, interval: float = 20.0, reclaim_interval: float = 300.0) -> int:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = LOCK_FILE.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Otra instancia de tardis-resource-governor ya está activa.")
            return 1

        def _sig(signum, _frame):
            logger.info("Señal %s recibida; deteniendo Resource Governor...", signum)
            self._stop_event.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        logger.info("tardis-resource-governor activo (interval=%.1fs, reclaim=%.0fs)", interval, reclaim_interval)
        last_reclaim = 0.0
        last_deferred_reclaim = 0.0
        try:
            while not self._stop_event.is_set():
                snap = self.collect_snapshot(persist=True)
                now = time.time()
                lvl = str(snap.get("level") or "GREEN")
                throttle_st = self.get_throttle_status()

                # Histéresis Schmitt-trigger de recuperación:
                # - GREEN: liberar tras RECOVERY_GREEN_STREAK muestras consecutivas.
                # - YELLOW en banda segura de enfriamiento (PSI60<20%, CPU<79°C, GPU<74°C):
                #   liberar tras RECOVERY_SAFE_YELLOW_STREAK muestras para evitar bloqueo crónico.
                throttle_or_pp_active = bool(throttle_st.get("active") or throttle_st.get("power_profile_mitigated"))
                if lvl == "GREEN":
                    self._green_streak += 1
                    self._safe_yellow_streak = 0
                    self._thermal_orange_streak = 0
                    if throttle_or_pp_active and self._green_streak >= RECOVERY_GREEN_STREAK:
                        rel = self.release_throttling(dry_run=False, snap=snap)
                        if rel.get("restored_units") or str(rel.get("power_profile_action", "")).startswith("restored_"):
                            logger.info(
                                "Presión estabilizada en GREEN (%d ciclos): throttling liberado en %d unidad(es) (perfil=%s)",
                                self._green_streak,
                                len(rel.get("restored_units") or []),
                                rel.get("power_profile_action", "unchanged"),
                            )
                elif _is_in_safe_recovery_band(snap):
                    self._green_streak = 0
                    self._safe_yellow_streak += 1
                    self._thermal_orange_streak = 0
                    needs_yellow_release = bool(
                        throttle_st.get("active") or throttle_st.get("power_profile_applied") == "power-saver"
                    )
                    if needs_yellow_release and self._safe_yellow_streak >= RECOVERY_SAFE_YELLOW_STREAK:
                        rel = self.release_throttling(dry_run=False, snap=snap)
                        pp_act = str(rel.get("power_profile_action", "unchanged"))
                        if rel.get("restored_units") or pp_act.startswith(("restored_", "stepped_back_")):
                            logger.info(
                                "Presión enfriada en banda segura YELLOW (%d ciclos, CPU=%.1f°C, PSI60=%.1f%%): throttling cgroup liberado en %d unidad(es) (perfil=%s)",
                                self._safe_yellow_streak,
                                snap["cpu"].get("temp_c", 0.0),
                                snap["cpu"]["psi"]["some_avg60"],
                                len(rel.get("restored_units") or []),
                                pp_act,
                            )
                else:
                    self._green_streak = 0
                    self._safe_yellow_streak = 0

                # Throttling proactivo ante ORANGE/RED o estrés combinado térmico+PSI (con filtro de micro-picos Ryzen)
                target_lvl = _resolve_throttle_target_level(snap)
                if target_lvl is not None and not snap.get("call_priority_active", False):
                    if _is_pure_transient_cpu_thermal_spike(snap):
                        self._thermal_orange_streak += 1
                        should_engage = self._thermal_orange_streak >= THERMAL_SPIKE_CONFIRM_STREAK
                    else:
                        self._thermal_orange_streak = 0
                        should_engage = True
                    needs_pp_step = _needs_power_profile_step_down(snap, target_lvl, throttle_st)
                    if should_engage and (
                        (not throttle_st.get("active"))
                        or throttle_st.get("level") != target_lvl
                        or needs_pp_step
                    ):
                        th = self.apply_throttling(snap, dry_run=False)
                        changed = [
                            u["unit"]
                            for u in (th.get("applied_units") or [])
                            if u.get("action") in ("throttled", "released_from_plan")
                        ]
                        pp_act = str(th.get("power_profile_action") or "unchanged")
                        if changed or pp_act.startswith("switched_to_"):
                            logger.info(
                                "Throttling Ring 0 aplicado (nivel=%s, CPU PSI60=%.1f%%, CPU=%.1f°C, GPU=%.0f°C, perfil=%s): unidades=%s",
                                target_lvl,
                                snap["cpu"]["psi"]["some_avg60"],
                                snap["cpu"].get("temp_c", 0.0),
                                snap["gpu"].get("temp_c", 0.0),
                                pp_act,
                                changed,
                            )
                else:
                    self._thermal_orange_streak = 0

                has_dups = bool(snap["inference_lanes"]["duplicate_models"])
                deferred_cooldown_ok = (now - last_deferred_reclaim) >= 60.0
                if (has_dups and deferred_cooldown_ok) or (now - last_reclaim) >= reclaim_interval:
                    if has_dups or target_lvl is not None:
                        res = self.reclaim_resources(dry_run=False, prune_backups=True)
                        unloaded = [e["model"] for e in res["models_evicted"] if e.get("action") == "unloaded"]
                        deferred = [e for e in res["models_evicted"] if e.get("action") == "unload_deferred_in_flight"]
                        if deferred:
                            last_deferred_reclaim = now
                            clients = deferred[0].get("active_clients") or []
                            logger.warning(
                                "Evicción diferida (inferencia activa en :11434): modelos=%s clientes=%s",
                                [e["model"] for e in deferred],
                                [(c.get("pid"), c.get("unit") or c.get("comm")) for c in clients],
                            )
                        if unloaded or res["backups_pruned"] or res.get("backups_archived") or (res.get("throttling") or {}).get("action") == "throttled":
                            logger.info(
                                "Reclamación completada: modelos=%s backups=%d archivados=%d throttle=%s RAM=%.0f->%.0fMB PSI60=%.1f%% CPU=%.1f°C",
                                unloaded,
                                res["backups_pruned"],
                                res.get("backups_archived", 0),
                                (res.get("throttling") or {}).get("action"),
                                res["mem_available_before_mb"],
                                res["mem_available_after_mb"],
                                res["cpu_psi60_after"],
                                res.get("cpu_temp_after_c", 0.0),
                            )
                    last_reclaim = now
                self._stop_event.wait(max(5.0, float(interval)))
        finally:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                lock_fh.close()
            except Exception:
                pass
        return 0


def get_resource_governor(db_path: Optional[Path] = None) -> TardisResourceGovernor:
    return TardisResourceGovernor.get_instance(db_path=db_path)


def can_run_background_task(task_class: str = "heavy_learning") -> bool:
    """Helper rápido (<0.1ms) para demonios de TARDIS."""
    try:
        return bool(get_resource_governor().admit(task_class).get("allowed", True))
    except Exception:
        return True


def get_pressure_sleep_multiplier(
    metric: str = "recommended_sleep_multiplier",
    max_age_s: float = 60.0,
) -> Tuple[str, float]:
    """
    Lectura directa y ultra-ligera (<0.1ms) desde tmpfs del nivel de presión y multiplicador
    de backoff para demonios de muestreo continuo (Tapo C310 Sentinel, motores de fondo).
    """
    for p in (TMPFS_SNAPSHOT, DISK_SNAPSHOT):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and (time.time() - float(data.get("ts", 0))) <= max_age_s:
                lvl = str(data.get("level") or "GREEN")
                adm = data.get("admission") or {}
                mult = float(adm.get(metric, adm.get("recommended_sleep_multiplier", 1.0)))
                return lvl, max(1.0, mult)
        except Exception:
            continue
    return "GREEN", 1.0


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-governor", description="TARDIS Sovereign Resource Governor & Inference Arbiter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Snapshot actual de presión, cgroups y admisión")
    p_adm = sub.add_parser("admit", help="Consulta admisión para una clase de tarea")
    p_adm.add_argument("task_class", nargs="?", default="heavy_learning")
    p_rec = sub.add_parser("reclaim", help="Descarga modelos duplicados, aplica throttling Ring 0 y poda backups")
    p_rec.add_argument("--dry-run", action="store_true")
    p_rec.add_argument("--no-throttle", action="store_true", help="Omitir ajuste cgroup v2 durante reclaim")
    p_th = sub.add_parser("throttle", help="Aplica throttling cgroup v2 en caliente según presión o nivel forzado")
    p_th.add_argument("--level", choices=["ORANGE", "RED"], default=None)
    p_th.add_argument("--dry-run", action="store_true")
    p_rel = sub.add_parser("release", help="Restaura límites cgroup v2 originales tras estabilización")
    p_rel.add_argument("--dry-run", action="store_true")
    p_rel.add_argument("--restore-power-profile", action="store_true", help="Forzar restauración inmediata del perfil energético base")
    p_hist = sub.add_parser("history", help="Histórico de telemetría de presión")
    p_hist.add_argument("--limit", type=int, default=20)
    p_d = sub.add_parser("daemon", help="Ejecuta el gobernador en bucle systemd 24/7")
    p_d.add_argument("--interval", type=float, default=20.0)
    p_d.add_argument("--reclaim-interval", type=float, default=300.0)

    args = ap.parse_args()
    gov = get_resource_governor()

    if args.cmd == "status":
        print(json.dumps(gov.collect_snapshot(persist=True), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "admit":
        res = gov.admit(args.task_class)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("allowed") else 2
    if args.cmd == "reclaim":
        print(
            json.dumps(
                gov.reclaim_resources(dry_run=args.dry_run, apply_throttle=not args.no_throttle),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "throttle":
        print(
            json.dumps(
                gov.apply_throttling(dry_run=args.dry_run, force_level=args.level),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "release":
        print(
            json.dumps(
                gov.release_throttling(
                    dry_run=args.dry_run,
                    force_restore_power_profile=bool(getattr(args, "restore_power_profile", False)),
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "history":
        print(json.dumps({"ok": True, "history": gov.history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "daemon":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (tardis-governor) %(message)s")
        return gov.run_daemon(interval=args.interval, reclaim_interval=args.reclaim_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
