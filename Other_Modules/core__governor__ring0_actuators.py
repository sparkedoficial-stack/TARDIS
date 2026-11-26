"""core/governor/ring0_actuators.py - Políticas de histéresis y actuadores Ring 0 (cgroup v2, power-profiles, NVIDIA clock cap, Hyprland)."""
from __future__ import annotations

from typing import Union
from core.governor.config import *
from core.governor.config import _atomic_write_json, _facade_hook, _now_iso
from core.governor.telemetry_probes import _read_cpu_power_profile

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
    return str(_facade_hook("_read_cpu_power_profile", _read_cpu_power_profile)().get("power_profile") or "")

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
    if not _facade_hook("_is_thermal_or_heavy_psi", _is_thermal_or_heavy_psi)(snap, target_level):
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

def _gpu_eco_control_enabled() -> bool:
    """Desactiva mutaciones reales de GPU/Hyprland durante pytest salvo habilitación explícita."""
    if os.environ.get("PYTEST_CURRENT_TEST") and str(os.environ.get("TARDIS_GOVERNOR_GPU_ECO_TEST", "0")) != "1":
        return False
    return str(os.environ.get("TARDIS_GOVERNOR_GPU_ECO_CONTROL", "1")).lower() not in ("0", "false", "no")

def _resolve_gpu_eco_mode(snap: Dict[str, Any], display_state: Dict[str, Any]) -> str:
    """
    Decide de forma determinista el modo eco GPU/Escritorio:
      - 'normal': llamada prioritaria, inferencia CUDA activa, o usuario interactivo con holgura térmica.
      - 'eco_idle': reposo/pantalla apagada (P8 ~6-9W) o GPU estancada en P0 caliente sin carga CUDA.
      - 'eco_thermal': presión térmica severa RED o GPU >= 82°C (P5 ~9-12W).
    """
    if bool(snap.get("call_priority_active", False)):
        return "normal"
    gpu = snap.get("gpu") or {}
    if not gpu.get("available"):
        return "normal"

    lvl = str(snap.get("level") or "GREEN").upper()
    gpu_temp = float(gpu.get("temp_c", 0.0))
    gpu_util = float(gpu.get("util_pct", 0.0))
    gpu_power = float(gpu.get("power_w", 0.0))
    gpu_pstate = str(gpu.get("pstate") or "").upper()
    tb_busy = bool(display_state.get("temporal_brain_busy", False))
    ollama_11435_busy = bool(display_state.get("ollama_11435_active", False))
    if not ollama_11435_busy:
        try:
            ollama_11435_busy = bool(snap.get("inference_lanes", {}).get("ollama_11435_gpu_voice"))
        except Exception:
            ollama_11435_busy = False
    headless = bool(display_state.get("headless_or_display_off", False))

    # Nunca degradar inferencia CUDA activa salvo emergencia térmica real (>= 84°C)
    if (tb_busy or ollama_11435_busy) and gpu_temp < 84.0:
        return "normal"

    if lvl == "RED" or gpu_temp >= 82.0:
        return "eco_thermal"

    if gpu_util >= 25.0:
        return "normal"

    # Pantalla desconectada/tapa cerrada o presión ORANGE sin carga CUDA -> P8 eco_idle
    if headless and gpu_util < 15.0:
        return "eco_idle"
    if lvl == "ORANGE" and gpu_util < 15.0:
        return "eco_idle"
    if gpu_pstate == "P0" and gpu_util < 10.0 and gpu_power >= 11.0 and gpu_temp >= 68.0:
        return "eco_idle"
    return "normal"

def _apply_nvidia_clock_cap(mode: str) -> Tuple[bool, str]:
    """Aplica o libera topes reversibles de relojes GPU/VRAM vía `sudo -n nvidia-smi`."""
    if not shutil.which("nvidia-smi"):
        return False, "nvidia_smi_missing"
    try:
        if mode == "normal":
            r1 = subprocess.run(
                ["sudo", "-n", "nvidia-smi", "-rgc"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=4.0,
                check=False,
            )
            r2 = subprocess.run(
                ["sudo", "-n", "nvidia-smi", "-rmc"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=4.0,
                check=False,
            )
            ok = (r1.returncode == 0 and r2.returncode == 0)
            return ok, ("clocks_unlocked" if ok else f"unlock_err:{(r1.stderr or r2.stderr).strip()[:120]}")

        spec = GPU_ECO_PROFILES.get(mode)
        if not spec:
            return False, f"unknown_mode:{mode}"
        r1 = subprocess.run(
            ["sudo", "-n", "nvidia-smi", "-lgc", f"{spec['gr_min']},{spec['gr_max']}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4.0,
            check=False,
        )
        r2 = subprocess.run(
            ["sudo", "-n", "nvidia-smi", "-lmc", f"{spec['mem_min']},{spec['mem_max']}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4.0,
            check=False,
        )
        ok = (r1.returncode == 0 and r2.returncode == 0)
        return ok, (f"capped_{spec['target_pstate']}" if ok else f"cap_err:{(r1.stderr or r2.stderr).strip()[:120]}")
    except Exception as exc:
        return False, f"nvidia_exc:{exc}"

def _hyprctl_get_bool(sig: str, option: str) -> Optional[int]:
    if not sig or not shutil.which("hyprctl"):
        return None
    env = os.environ.copy()
    env["HYPRLAND_INSTANCE_SIGNATURE"] = sig
    try:
        res = subprocess.run(
            ["hyprctl", "getoption", option],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode != 0:
            return None
        for ln in (res.stdout or "").splitlines():
            low = ln.strip().lower()
            if low.startswith("bool:"):
                return 1 if "true" in low else 0
            if low.startswith("int:"):
                val = low.split(":", 1)[1].strip()
                return 1 if val not in ("0", "") else 0
    except Exception:
        pass
    return None

def _hyprctl_set_keyword(sig: str, option: str, value: Union[int, str]) -> bool:
    if not sig or not shutil.which("hyprctl"):
        return False
    env = os.environ.copy()
    env["HYPRLAND_INSTANCE_SIGNATURE"] = sig
    try:
        res = subprocess.run(
            ["hyprctl", "keyword", option, str(value)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False

def _swap_recycle_control_enabled() -> bool:
    """Política Cero-Reinicios: deshabilitado por defecto (activar solo manualmente con TARDIS_GOVERNOR_SWAP_RECYCLE=1)."""
    raw = os.environ.get("TARDIS_GOVERNOR_SWAP_RECYCLE", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")

def _restart_systemd_user_unit(unit: str, timeout: float = 20.0) -> Tuple[bool, str]:
    """Reinicia de forma limpia una unidad systemd --user con stdin/stdout/stderr desacoplados."""
    try:
        res = subprocess.run(
            ["systemctl", "--user", "restart", unit],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if res.returncode == 0:
            return True, "restarted"
        return False, (res.stderr or res.stdout or f"rc={res.returncode}").strip()[:180]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

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
