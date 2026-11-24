"""
core/mundo_sin_censura_hardware.py - Controlador Soberano Absoluto de Hardware para Un Mundo Sin Censura
========================================================================================================
GODWORKS SYSTEM v26.4 · TARDIS · Enlace Ring-0 / Hardware Físico para `mundo-sin-censura`

Concede a `Un Mundo Sin Censura` (`/mundo-sin-censura`, `mundo-chat` y la app nativa
`mundo-desktop`) autoridad operativa total sobre el hardware del equipo mientras el
sistema se encuentre en funcionamiento:

  1. Silicio & CPU: telemetría por núcleo, frecuencias, gobernadores `cpufreq`
     (`performance` / `powersave`), perfiles ACPI `platform_profile` y `powerprofilesctl`.
  2. Plataforma ASUS TUF WMI: política térmica (`throttle_thermal_policy`:
     0=Balanced, 1=Turbo/Overboost, 2=Silent), ventiladores `hwmon` (RPM CPU/GPU),
     retroiluminación de teclado `asus::kbd_backlight` (0–3 con fallback root sysfs),
     modo de carga de batería y sensores térmicos (`k10temp`, `nvme`, `amdgpu`, `acpitz`).
  3. GPU NVIDIA (RTX 3050): temperatura, utilización, VRAM, potencia instantánea,
     relojes, límite de potencia (`nvidia-smi -pl`), persistencia y control de relojes.
  4. Kernel Ring-0 (`FtlKernelBridge`): PSI (`/proc/pressure/{cpu,memory,io}`),
     lectura/escritura `sysctl` en caliente, purga de cachés (`drop_caches=3`),
     `dmesg`, módulos del kernel (`lsmod`/`modprobe`), lectura/escritura controlada
     de `/sys` y `/proc/sys`, estado de nodos `/dev/uinput`, `/dev/uhid`, `/dev/fuse`,
     `/dev/net/tun` y ejecución privilegiada auditada.
  5. Audio, Pantalla & Periféricos: PipeWire/ALSA volumen y mute, brillo óptico y
     DPMS Hyprland, bloqueo/desbloqueo con inyección `/dev/uinput`, capturas de pantalla,
     inhibidor de suspensión 24/7, emulación de teclado y ratón.
  6. Radiofrecuencia & Redes: Wi-Fi (escaneo, conexión, auto-recuperación), Bluetooth,
     Hotspot Soberano `TimeMachine`, Escudo de Red AEGIS (AdBlock/AntiSpy/conntrack).
  7. Servicios Systemd, Procesos & Agente Autónomo: control de unidades systemd
     (`user`/`system`), lanzamiento/cierre de aplicaciones y protocolo de invocación
     directa desde el chat (`[[HW_ACTION:{...}]]` y `/hw <accion> [params]`).

Seguridad e Integridad:
  - Activo automáticamente mientras el sistema esté en funcionamiento (`runtime_active`).
  - Restringido estrictamente a peticiones locales (loopback) o sesiones soberanas
    autenticadas; preserva `LA CONSTANTE AEGIS` y bloquea comandos autodestructivos.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TARDIS.MundoHardware")

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
HOME_DIR = Path.home()
for _p in (str(PROJECT_ROOT), str(HOME_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HW_STATE_FILE = DATA_DIR / "mundo_sin_censura_hardware_state.json"
HW_AUDIT_LOG = DATA_DIR / "mundo_sin_censura_hardware_audit.jsonl"

ASUS_WMI_DIR = Path("/sys/devices/platform/asus-nb-wmi")
ASUS_KBD_PATH = ASUS_WMI_DIR / "leds" / "asus::kbd_backlight" / "brightness"
ASUS_KBD_MAX_PATH = ASUS_WMI_DIR / "leds" / "asus::kbd_backlight" / "max_brightness"
ASUS_THERMAL_POLICY_PATH = ASUS_WMI_DIR / "throttle_thermal_policy"
ASUS_CHARGE_MODE_PATH = ASUS_WMI_DIR / "charge_mode"
ACPI_PLATFORM_PROFILE = Path("/sys/firmware/acpi/platform_profile")
ACPI_PLATFORM_CHOICES = Path("/sys/firmware/acpi/platform_profile_choices")

THERMAL_POLICY_LABELS = {0: "balanced", 1: "turbo", 2: "silent"}
THERMAL_POLICY_MAP = {
    "0": 0, "balanced": 0, "balanceado": 0, "normal": 0, "equilibrado": 0,
    "1": 1, "turbo": 1, "overboost": 1, "performance": 1, "rendimiento": 1, "max": 1,
    "2": 2, "silent": 2, "silencioso": 2, "quiet": 2, "ahorro": 2, "eco": 2,
}

# Patrones estrictamente bloqueados para proteger la integridad física del host y AEGIS
_CATASTROPHIC_PATTERNS = (
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:\s|$|\*)"),
    re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+/(?:\s|$|\*)"),
    re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\s+/dev/(?:nvme|sd|vd|hd)"),
    re.compile(r"\bdd\b.*\bof=/dev/(?:nvme|sd|vd|hd)[a-z0-9]*(?:\s|$)"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;"),
    re.compile(r">\s*/dev/(?:nvme|sd|vd|hd)[a-z0-9]*(?:\s|$)"),
)

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


def _is_catastrophic_command(cmd: str) -> bool:
    txt = (cmd or "").strip()
    return any(pat.search(txt) for pat in _CATASTROPHIC_PATTERNS)


def _run_cmd(
    cmd: List[str],
    *,
    timeout: float = 10.0,
    input_text: Optional[str] = None,
) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            stdin=subprocess.DEVNULL if input_text is None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout ({timeout}s)"
    except Exception as exc:
        return 1, "", str(exc)


def _sudo_write_sysfs(path: Path, value: str) -> Tuple[bool, str]:
    """Escribe un valor en /sys o /proc/sys usando escritura directa o sudo -n tee."""
    resolved = str(path)
    if not (resolved.startswith("/sys/") or resolved.startswith("/proc/sys/")):
        return False, f"Ruta fuera de /sys o /proc/sys: {resolved}"
    try:
        path.write_text(str(value), encoding="utf-8")
        return True, "direct"
    except Exception:
        pass
    rc, _out, err = _run_cmd(["sudo", "-n", "tee", resolved], timeout=5.0, input_text=f"{value}\n")
    if rc == 0:
        return True, "sudo_tee"
    return False, err or f"rc={rc}"


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return None


def _publish_bus(topic: str, payload: Dict[str, Any], severity: str = "INFO") -> None:
    try:
        from core.tardis_event_bus import get_event_bus
        get_event_bus().publish(topic, "mundo_sin_censura_hardware", payload, severity=severity)
    except Exception:
        pass


class MundoSinCensuraHardwareController:
    """
    Orquestador absoluto de hardware y Kernel Ring-0 para `Un Mundo Sin Censura`.
    Se arma automáticamente mientras el sistema está en ejecución y expone control
    directo vía REST, Chat Agéntico (`[[HW_ACTION:...]]` / `/hw`) y la app nativa.
    """

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._audit_ring: deque[Dict[str, Any]] = deque(maxlen=200)
        self._state = self._load_state()
        # Activar automáticamente mientras el sistema esté en funcionamiento
        self._state["runtime_active"] = True
        self._state["runtime_pid"] = os.getpid()
        self._state["armed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if self._state.get("auto_arm_on_startup", True):
            self._state["hardware_control_enabled"] = True
        self._save_state()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "hardware_control_enabled": True,
            "auto_arm_on_startup": True,
            "ring0_enabled": True,
            "agentic_hw_in_chat": True,
            "sovereignty_level": "ABSOLUTE_RING_0_RUNTIME",
            "runtime_active": True,
            "runtime_pid": os.getpid(),
            "armed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "actions_executed": 0,
            "actions_failed": 0,
            "last_action": None,
            "last_action_at": None,
        }

    def _load_state(self) -> Dict[str, Any]:
        base = self._default_state()
        if HW_STATE_FILE.exists():
            try:
                loaded = json.loads(HW_STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    base.update(loaded)
                    base["version"] = self.VERSION
            except Exception:
                pass
        return base

    def _save_state(self) -> None:
        with self._lock:
            try:
                tmp = HW_STATE_FILE.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, HW_STATE_FILE)
            except Exception:
                pass

    def _record_audit(
        self,
        *,
        action: str,
        params: Dict[str, Any],
        ok: bool,
        source: str,
        elapsed_ms: float,
        summary: str = "",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        entry = {
            "ts": time.time(),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "params": params,
            "ok": bool(ok),
            "source": source,
            "elapsed_ms": round(elapsed_ms, 2),
            "summary": summary[:280],
            "error": (error or "")[:240] or None,
        }
        with self._lock:
            self._audit_ring.appendleft(entry)
            self._state["actions_executed"] = int(self._state.get("actions_executed", 0)) + 1
            if not ok:
                self._state["actions_failed"] = int(self._state.get("actions_failed", 0)) + 1
            self._state["last_action"] = action
            self._state["last_action_at"] = entry["timestamp"]
            self._save_state()
            try:
                with HW_AUDIT_LOG.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
        return entry

    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        lim = max(1, min(200, int(limit)))
        with self._lock:
            if self._audit_ring:
                return list(self._audit_ring)[:lim]
        if HW_AUDIT_LOG.exists():
            try:
                lines = HW_AUDIT_LOG.read_text(encoding="utf-8").splitlines()
                parsed = [json.loads(ln) for ln in reversed(lines[-lim:]) if ln.strip()]
                return parsed
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------
    # Control de modo y ciclo de vida en ejecución
    # ------------------------------------------------------------------
    def is_system_running(self) -> bool:
        """Verifica que el sistema operativo y el entorno runtime estén activos."""
        return bool(self._state.get("runtime_active", True) and os.getpid() > 0)

    def is_armed(self) -> bool:
        """Devuelve True cuando el control absoluto de hardware está armado y el sistema corre."""
        return bool(self.is_system_running() and self._state.get("hardware_control_enabled", True))

    def set_mode(
        self,
        *,
        enabled: Optional[bool] = None,
        ring0_enabled: Optional[bool] = None,
        agentic_hw_in_chat: Optional[bool] = None,
        auto_arm_on_startup: Optional[bool] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if enabled is not None:
                self._state["hardware_control_enabled"] = bool(enabled)
                if enabled:
                    self._state["armed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if ring0_enabled is not None:
                self._state["ring0_enabled"] = bool(ring0_enabled)
            if agentic_hw_in_chat is not None:
                self._state["agentic_hw_in_chat"] = bool(agentic_hw_in_chat)
            if auto_arm_on_startup is not None:
                self._state["auto_arm_on_startup"] = bool(auto_arm_on_startup)
            self._state["runtime_active"] = True
            self._save_state()
        _publish_bus("mundo_sin_censura.hardware.mode", dict(self._state))
        return {"ok": True, "armed": self.is_armed(), "state": dict(self._state)}

    def ensure_runtime_armed(self) -> Dict[str, Any]:
        """Asegura el enlace absoluto de hardware mientras el sistema esté en funcionamiento."""
        with self._lock:
            self._state["runtime_active"] = True
            self._state["runtime_pid"] = os.getpid()
            if self._state.get("auto_arm_on_startup", True):
                self._state["hardware_control_enabled"] = True
            self._save_state()
        # Asegurar también que el orquestador de 5 capas esté activo si es posible
        try:
            from core.background_hardware_orchestrator import get_background_hardware_orchestrator
            bg = get_background_hardware_orchestrator()
            if not bg.is_running():
                bg.start()
        except Exception:
            pass
        return {"ok": True, "armed": self.is_armed(), "state": dict(self._state)}

    # ------------------------------------------------------------------
    # Sub-sistemas y puentes lazy
    # ------------------------------------------------------------------
    def _hw(self):
        from core.hardware_controller import get_hardware_controller
        return get_hardware_controller()

    def _os(self):
        from core.os_controller import get_os_controller
        return get_os_controller()

    def _kernel(self):
        from modulos_ftl.ftl_kernel_bridge import get_kernel_bridge
        return get_kernel_bridge()

    def _bg(self):
        from core.background_hardware_orchestrator import get_background_hardware_orchestrator
        return get_background_hardware_orchestrator()

    # ------------------------------------------------------------------
    # Lectores de telemetría física en tiempo real
    # ------------------------------------------------------------------
    def get_cpu_telemetry(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "percent": 0.0,
            "per_core": [],
            "cores_logical": os.cpu_count() or 1,
            "freq_mhz": None,
            "freq_min_mhz": None,
            "freq_max_mhz": None,
            "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else [],
            "governor": _read_text_safe(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")) or "unknown",
            "available_governors": (
                _read_text_safe(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors")) or ""
            ).split(),
        }
        if HAS_PSUTIL:
            try:
                out["percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
                out["per_core"] = [round(float(x), 1) for x in psutil.cpu_percent(interval=None, percpu=True)]
                fr = psutil.cpu_freq()
                if fr:
                    out["freq_mhz"] = round(fr.current, 1)
                    out["freq_min_mhz"] = round(fr.min, 1)
                    out["freq_max_mhz"] = round(fr.max, 1)
            except Exception:
                pass
        return out

    def get_gpu_telemetry(self) -> Dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"ok": False, "available": False, "error": "nvidia-smi no disponible"}
        fields = [
            "name",
            "temperature.gpu",
            "utilization.gpu",
            "utilization.memory",
            "memory.used",
            "memory.total",
            "power.draw",
            "power.limit",
            "power.min_limit",
            "power.max_limit",
            "clocks.gr",
            "clocks.mem",
            "driver_version",
            "persistence_mode",
        ]
        rc, out, err = _run_cmd(
            [exe, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
            timeout=3.0,
        )
        if rc != 0 or not out:
            return {"ok": False, "available": False, "error": err or "sin salida nvidia-smi"}
        line = out.splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < len(fields):
            return {"ok": False, "available": False, "raw": line}

        def _f(v: str) -> Optional[float]:
            try:
                return round(float(v), 2)
            except Exception:
                return None

        used_mb = _f(parts[4]) or 0.0
        total_mb = _f(parts[5]) or 1.0
        return {
            "ok": True,
            "available": True,
            "name": parts[0],
            "temperature_c": _f(parts[1]),
            "utilization_gpu_pct": _f(parts[2]),
            "utilization_mem_pct": _f(parts[3]),
            "vram_used_mb": used_mb,
            "vram_total_mb": total_mb,
            "vram_percent": round((used_mb / max(total_mb, 1.0)) * 100.0, 1),
            "power_draw_w": _f(parts[6]),
            "power_limit_w": _f(parts[7]),
            "power_min_w": _f(parts[8]),
            "power_max_w": _f(parts[9]),
            "clock_graphics_mhz": _f(parts[10]),
            "clock_mem_mhz": _f(parts[11]),
            "driver_version": parts[12],
            "persistence_mode": parts[13],
        }

    def get_asus_platform_telemetry(self) -> Dict[str, Any]:
        policy_raw = _read_text_safe(ASUS_THERMAL_POLICY_PATH)
        policy_code = int(policy_raw) if (policy_raw and policy_raw.isdigit()) else None
        charge_raw = _read_text_safe(ASUS_CHARGE_MODE_PATH)
        dgpu_raw = _read_text_safe(ASUS_WMI_DIR / "dgpu_disable")
        kbd = self._hw().get_keyboard_brightness()

        fans: Dict[str, int] = {}
        try:
            for hwdir in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
                hname = _read_text_safe(hwdir / "name") or hwdir.name
                for fan_file in sorted(hwdir.glob("fan*_input")):
                    val = _read_text_safe(fan_file)
                    if val and val.isdigit():
                        fans[f"{hname}:{fan_file.stem.replace('_input', '')}"] = int(val)
        except Exception:
            pass

        return {
            "ok": True,
            "wmi_present": ASUS_WMI_DIR.exists(),
            "throttle_thermal_policy": policy_code,
            "thermal_policy_label": THERMAL_POLICY_LABELS.get(policy_code, "unknown") if policy_code is not None else "unknown",
            "platform_profile": _read_text_safe(ACPI_PLATFORM_PROFILE) or "unknown",
            "platform_profile_choices": (_read_text_safe(ACPI_PLATFORM_CHOICES) or "").split(),
            "charge_mode": int(charge_raw) if (charge_raw and charge_raw.isdigit()) else None,
            "dgpu_disabled": (dgpu_raw == "1") if dgpu_raw is not None else None,
            "keyboard_backlight": kbd,
            "fans_rpm": fans,
        }

    def get_display_telemetry(self) -> Dict[str, Any]:
        monitors: List[Dict[str, Any]] = []
        hypr = shutil.which("hyprctl")
        if hypr:
            rc, out, _ = _run_cmd([hypr, "monitors", "-j"], timeout=2.0)
            if rc == 0 and out.startswith("["):
                try:
                    raw_mons = json.loads(out)
                    for m in raw_mons:
                        if isinstance(m, dict):
                            monitors.append({
                                "name": m.get("name"),
                                "model": m.get("model"),
                                "width": m.get("width"),
                                "height": m.get("height"),
                                "refresh_hz": round(float(m.get("refreshRate") or 0.0), 2),
                                "vrr": bool(m.get("vrr")),
                                "dpms": bool(m.get("dpmsStatus", True)),
                                "scale": m.get("scale"),
                                "focused": bool(m.get("focused")),
                            })
                except Exception:
                    pass
        screen_b = self._bg().get_screen_brightness()
        w, h = self._os().get_screen_resolution()
        return {
            "ok": True,
            "resolution": f"{w}x{h}",
            "width": w,
            "height": h,
            "locked": self._os().is_locked(),
            "brightness": screen_b,
            "monitors": monitors,
        }

    def get_memory_telemetry(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if HAS_PSUTIL:
            vm = psutil.virtual_memory()
            sw = psutil.swap_memory()
            out = {
                "total_gb": round(vm.total / (1024 ** 3), 2),
                "used_gb": round(vm.used / (1024 ** 3), 2),
                "available_gb": round(vm.available / (1024 ** 3), 2),
                "percent": round(vm.percent, 1),
                "swap_total_gb": round(sw.total / (1024 ** 3), 2),
                "swap_used_gb": round(sw.used / (1024 ** 3), 2),
                "swap_percent": round(sw.percent, 1),
            }
        return out

    def get_full_hardware_telemetry(self) -> Dict[str, Any]:
        """Fotografía holística de hardware físico + Kernel Ring-0 + capas TARDIS."""
        hw = self._hw()
        diag = hw.get_full_diagnostic()
        cpu = self.get_cpu_telemetry()
        mem = self.get_memory_telemetry()
        gpu = self.get_gpu_telemetry()
        asus = self.get_asus_platform_telemetry()
        disp = self.get_display_telemetry()
        try:
            kernel = self._kernel().get_kernel_status()
        except Exception as e:
            kernel = {"status": "error", "error": str(e)}
        try:
            bg_tel = self._bg().get_all_layers_telemetry()
        except Exception:
            bg_tel = {}

        # Temperatura máxima CPU
        max_cpu_temp = None
        for name, entries in (diag.get("temperatures") or {}).items():
            for e in entries:
                lbl = str(e.get("label") or "").lower()
                if "k10temp" in name.lower() or "tctl" in lbl or "cpu" in lbl:
                    val = e.get("current_c")
                    if val is not None:
                        max_cpu_temp = max(max_cpu_temp or 0.0, float(val))

        return {
            "ok": True,
            "version": self.VERSION,
            "model": "mundo-sin-censura",
            "system_running": self.is_system_running(),
            "hardware_control_armed": self.is_armed(),
            "ring0_enabled": bool(self._state.get("ring0_enabled", True)),
            "agentic_hw_in_chat": bool(self._state.get("agentic_hw_in_chat", True)),
            "sovereignty_level": self._state.get("sovereignty_level", "ABSOLUTE_RING_0_RUNTIME"),
            "uptime_s": round(time.time() - self._started_at, 1),
            "cpu": {**cpu, "max_temp_c": round(max_cpu_temp, 1) if max_cpu_temp is not None else None},
            "memory": mem,
            "gpu": gpu,
            "asus_platform": asus,
            "power_profile": diag.get("power_profile", {}),
            "battery": diag.get("battery"),
            "temperatures": diag.get("temperatures", {}),
            "audio": diag.get("audio", {}),
            "keyboard": diag.get("keyboard", {}),
            "bluetooth": diag.get("bluetooth", {}),
            "network": diag.get("network", {}),
            "display": disp,
            "kernel_ring0": kernel,
            "background_layers": bg_tel,
            "state": dict(self._state),
            "timestamp": time.time(),
        }

    def get_compact_hardware_summary(self) -> str:
        """Resumen compacto (<650 chars) para inyectar conciencia física en el prompt del LLM."""
        try:
            cpu = self.get_cpu_telemetry()
            mem = self.get_memory_telemetry()
            gpu = self.get_gpu_telemetry()
            asus = self.get_asus_platform_telemetry()
            vol = self._hw().get_volume()
            pwr = self._hw().get_power_profile()
            psi = self._kernel().get_psi_telemetry()
            cpu_psi = (psi.get("cpu") or {}).get("some", {}).get("avg10", 0.0)
            mem_psi = (psi.get("memory") or {}).get("some", {}).get("avg10", 0.0)
            fans_str = ", ".join(f"{k}={v}RPM" for k, v in (asus.get("fans_rpm") or {}).items()) or "n/a"
            gpu_str = (
                f"{gpu.get('name')} {gpu.get('temperature_c')}°C "
                f"util={gpu.get('utilization_gpu_pct')}% "
                f"VRAM={gpu.get('vram_used_mb')}/{gpu.get('vram_total_mb')}MB "
                f"P={gpu.get('power_draw_w')}/{gpu.get('power_limit_w')}W"
                if gpu.get("available")
                else "offline"
            )
            return (
                f"CPU: {cpu.get('percent')}% ({cpu.get('cores_logical')}T @ {cpu.get('freq_mhz')}MHz, gov={cpu.get('governor')}) | "
                f"RAM: {mem.get('used_gb')}/{mem.get('total_gb')}GB ({mem.get('percent')}%) | "
                f"GPU: {gpu_str} | "
                f"ASUS: thermal={asus.get('thermal_policy_label')}, acpi={asus.get('platform_profile')}, "
                f"kbd={asus.get('keyboard_backlight', {}).get('level')}/3, fans=[{fans_str}] | "
                f"Audio: {vol.get('percent')}%{' MUTED' if vol.get('muted') else ''} | "
                f"PowerProfile: {pwr.get('active_profile')} | "
                f"Kernel PSI(10s): cpu={cpu_psi}, mem={mem_psi}"
            )
        except Exception as e:
            return f"Telemetría física parcial ({e})"

    def get_capabilities(self) -> Dict[str, Any]:
        """Catálogo estructurado de todas las capacidades físicas y Ring-0 controlables."""
        return {
            "ok": True,
            "armed": self.is_armed(),
            "sovereignty_level": self._state.get("sovereignty_level"),
            "domains": {
                "silicon_cpu_power": [
                    "set_cpu_governor",
                    "set_thermal_policy",
                    "set_platform_profile",
                    "set_power_profile",
                    "set_charge_mode",
                ],
                "gpu_nvidia": [
                    "gpu_status",
                    "gpu_set_power_limit",
                    "gpu_persistence",
                    "gpu_lock_clocks",
                    "gpu_reset_clocks",
                ],
                "kernel_ring0": [
                    "kernel_status",
                    "psi",
                    "dmesg",
                    "sysctl_get",
                    "sysctl_set",
                    "drop_caches",
                    "tune_kernel",
                    "kernel_modules",
                    "uinput_status",
                    "sysfs_read",
                    "sysfs_write",
                    "root_exec",
                ],
                "audio_optical_display": [
                    "get_volume",
                    "set_volume",
                    "mute",
                    "unmute",
                    "toggle_mute",
                    "get_keyboard_brightness",
                    "set_keyboard_brightness",
                    "toggle_keyboard_brightness",
                    "get_screen_brightness",
                    "set_screen_brightness",
                    "display_dpms",
                    "display_mode",
                    "lock_screen",
                    "unlock_screen",
                    "screenshot",
                    "keep_awake",
                ],
                "input_hid_uinput": [
                    "type_text",
                    "press_keys",
                    "mouse_action",
                ],
                "rf_network_shield": [
                    "wifi_status",
                    "wifi_scan",
                    "wifi_connect",
                    "wifi_recover",
                    "bluetooth_status",
                    "set_bluetooth",
                    "scan_bluetooth",
                    "hotspot_status",
                    "hotspot_start",
                    "hotspot_stop",
                    "hotspot_restart",
                    "hotspot_clients",
                    "shield_status",
                    "shield_audit",
                    "shield_toggle_adblock",
                    "shield_toggle_antispy",
                    "traffic_status",
                ],
                "os_services_processes": [
                    "hardware_status",
                    "full_telemetry",
                    "bg_hardware_telemetry",
                    "get_presence",
                    "pci_usb_devices",
                    "processes_top",
                    "service_status",
                    "service_action",
                    "launch_app",
                    "kill_app",
                    "run_shell",
                    "reboot",
                ],
            },
        }

    # ------------------------------------------------------------------
    # Implementaciones de control directo de hardware
    # ------------------------------------------------------------------
    def set_cpu_governor(self, governor: str) -> Dict[str, Any]:
        gov = (governor or "").strip().lower()
        avail = (
            _read_text_safe(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors")) or ""
        ).split()
        if avail and gov not in avail:
            return {"ok": False, "error": f"Gobernador '{gov}' no soportado. Disponibles: {avail}"}
        gov_files = sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor"))
        if not gov_files:
            return {"ok": False, "error": "Interfaz cpufreq no disponible en /sys."}
        rc, _out, err = _run_cmd(
            ["sudo", "-n", "bash", "-c", f"for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo {shlex.quote(gov)} > \"$f\"; done"],
            timeout=5.0,
        )
        current = _read_text_safe(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"))
        return {
            "ok": rc == 0 and current == gov,
            "governor": current,
            "requested": gov,
            "cores_updated": len(gov_files) if rc == 0 else 0,
            "error": err or None,
        }

    def set_thermal_policy(self, policy: Any) -> Dict[str, Any]:
        key = str(policy).strip().lower()
        if key not in THERMAL_POLICY_MAP:
            return {"ok": False, "error": f"Política térmica inválida '{policy}'. Usa: balanced(0), turbo(1), silent(2)."}
        code = THERMAL_POLICY_MAP[key]
        ok_wmi, method = _sudo_write_sysfs(ASUS_THERMAL_POLICY_PATH, str(code))
        # Sincronizar también ACPI platform_profile si existe
        acpi_map = {0: "balanced", 1: "performance", 2: "quiet"}
        acpi_ok = False
        if ACPI_PLATFORM_PROFILE.exists():
            acpi_ok, _ = _sudo_write_sysfs(ACPI_PLATFORM_PROFILE, acpi_map[code])
        actual = _read_text_safe(ASUS_THERMAL_POLICY_PATH)
        return {
            "ok": ok_wmi or acpi_ok,
            "policy_code": int(actual) if (actual and actual.isdigit()) else code,
            "policy_label": THERMAL_POLICY_LABELS.get(code, "unknown"),
            "acpi_profile": _read_text_safe(ACPI_PLATFORM_PROFILE),
            "method": method,
        }

    def set_platform_profile(self, profile: str) -> Dict[str, Any]:
        prof = (profile or "").strip().lower()
        aliases = {"silent": "quiet", "silencioso": "quiet", "turbo": "performance", "rendimiento": "performance", "balanceado": "balanced"}
        prof = aliases.get(prof, prof)
        choices = (_read_text_safe(ACPI_PLATFORM_CHOICES) or "").split()
        if choices and prof not in choices:
            return {"ok": False, "error": f"Perfil ACPI '{prof}' inválido. Opciones: {choices}"}
        ok, method = _sudo_write_sysfs(ACPI_PLATFORM_PROFILE, prof)
        return {"ok": ok, "platform_profile": _read_text_safe(ACPI_PLATFORM_PROFILE), "method": method}

    def set_keyboard_brightness_root(self, level: Any) -> Dict[str, Any]:
        target = max(0, min(3, int(level)))
        res = self._hw().set_keyboard_brightness(target)
        if res.get("level") == target:
            return res
        ok, method = _sudo_write_sysfs(ASUS_KBD_PATH, str(target))
        after = self._hw().get_keyboard_brightness()
        after["ok"] = bool(ok or after.get("level") == target)
        after["method"] = method
        return after

    def set_charge_mode(self, mode: Any) -> Dict[str, Any]:
        val = 1 if str(mode).strip().lower() in ("1", "true", "on", "full") else 0
        if not ASUS_CHARGE_MODE_PATH.exists():
            return {"ok": False, "error": "charge_mode no disponible en asus-nb-wmi."}
        ok, method = _sudo_write_sysfs(ASUS_CHARGE_MODE_PATH, str(val))
        return {"ok": ok, "charge_mode": _read_text_safe(ASUS_CHARGE_MODE_PATH), "method": method}

    def gpu_set_power_limit(self, watts: Any) -> Dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"ok": False, "error": "nvidia-smi no disponible"}
        gpu = self.get_gpu_telemetry()
        min_w = float(gpu.get("power_min_w") or 15.0)
        max_w = float(gpu.get("power_max_w") or 75.0)
        target = max(max(15.0, min_w), min(max_w, float(watts)))
        rc, out, err = _run_cmd(["sudo", "-n", exe, "-pl", f"{target:.0f}"], timeout=5.0)
        return {
            "ok": rc == 0,
            "requested_watts": round(target, 1),
            "stdout": out,
            "stderr": err,
            "gpu": self.get_gpu_telemetry(),
        }

    def gpu_set_persistence(self, enabled: bool) -> Dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"ok": False, "error": "nvidia-smi no disponible"}
        rc, out, err = _run_cmd(["sudo", "-n", exe, "-pm", "1" if enabled else "0"], timeout=5.0)
        return {"ok": rc == 0, "persistence_enabled": bool(enabled), "stdout": out, "stderr": err}

    def gpu_lock_clocks(self, min_mhz: int, max_mhz: int) -> Dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"ok": False, "error": "nvidia-smi no disponible"}
        rc, out, err = _run_cmd(["sudo", "-n", exe, "-lgc", f"{int(min_mhz)},{int(max_mhz)}"], timeout=5.0)
        return {"ok": rc == 0, "min_mhz": int(min_mhz), "max_mhz": int(max_mhz), "stdout": out, "stderr": err}

    def gpu_reset_clocks(self) -> Dict[str, Any]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"ok": False, "error": "nvidia-smi no disponible"}
        rc, out, err = _run_cmd(["sudo", "-n", exe, "-rgc"], timeout=5.0)
        return {"ok": rc == 0, "stdout": out, "stderr": err}

    def display_dpms(self, state: str) -> Dict[str, Any]:
        st = "on" if str(state).strip().lower() in ("on", "1", "true", "wake") else "off"
        hypr = shutil.which("hyprctl")
        if not hypr:
            return {"ok": False, "error": "hyprctl no disponible"}
        rc, out, err = _run_cmd([hypr, "dispatch", "dpms", st], timeout=3.0)
        return {"ok": rc == 0, "dpms": st, "stdout": out, "stderr": err}

    def display_mode(self, monitor: str, mode: str) -> Dict[str, Any]:
        hypr = shutil.which("hyprctl")
        if not hypr:
            return {"ok": False, "error": "hyprctl no disponible"}
        mon = (monitor or "DP-1").strip()
        spec = (mode or "preferred,auto,auto").strip()
        rc, out, err = _run_cmd([hypr, "keyword", "monitor", f"{mon},{spec}"], timeout=3.0)
        return {"ok": rc == 0, "monitor": mon, "mode": spec, "stdout": out, "stderr": err}

    def list_pci_usb_devices(self) -> Dict[str, Any]:
        pci_rc, pci_out, _ = _run_cmd(["lspci"], timeout=4.0) if shutil.which("lspci") else (1, "", "")
        usb_rc, usb_out, _ = _run_cmd(["lsusb"], timeout=4.0) if shutil.which("lsusb") else (1, "", "")
        return {
            "ok": True,
            "pci": pci_out.splitlines()[:40] if pci_rc == 0 else [],
            "usb": usb_out.splitlines()[:40] if usb_rc == 0 else [],
        }

    def get_top_processes(self, limit: int = 15) -> Dict[str, Any]:
        if not HAS_PSUTIL:
            return {"ok": False, "error": "psutil no disponible"}
        lim = max(1, min(50, int(limit)))
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent", "status"]):
            try:
                info = p.info
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"],
                    "user": info["username"],
                    "cpu_pct": round(float(info.get("cpu_percent") or 0.0), 1),
                    "mem_pct": round(float(info.get("memory_percent") or 0.0), 2),
                    "status": info.get("status"),
                })
            except Exception:
                continue
        procs.sort(key=lambda x: (x["cpu_pct"], x["mem_pct"]), reverse=True)
        return {"ok": True, "count": len(procs), "top": procs[:lim]}

    def manage_systemd_service(self, unit: str, op: str = "status", scope: str = "user") -> Dict[str, Any]:
        clean_unit = (unit or "").strip()
        if not clean_unit or not re.match(r"^[a-zA-Z0-9_.@-]+$", clean_unit):
            return {"ok": False, "error": f"Nombre de unidad inválido: '{unit}'"}
        clean_op = (op or "status").strip().lower()
        if clean_op not in ("status", "start", "stop", "restart", "is-active"):
            return {"ok": False, "error": f"Operación systemd inválida: '{op}'"}
        is_sys = (scope or "user").strip().lower() == "system"
        if is_sys:
            cmd = ["sudo", "-n", "systemctl", clean_op, clean_unit]
            if clean_op == "status":
                cmd = ["systemctl", "status", clean_unit, "--no-pager", "-n", "12"]
        else:
            cmd = ["systemctl", "--user", clean_op, clean_unit]
            if clean_op == "status":
                cmd += ["--no-pager", "-n", "12"]
        rc, out, err = _run_cmd(cmd, timeout=15.0)
        return {
            "ok": rc == 0 or (clean_op == "status" and bool(out)),
            "unit": clean_unit,
            "scope": "system" if is_sys else "user",
            "op": clean_op,
            "rc": rc,
            "stdout": out[:1600],
            "stderr": err[:600],
        }

    # ------------------------------------------------------------------
    # Despachador Universal Absoluto de Hardware
    # ------------------------------------------------------------------
    def execute_action(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        is_local_request: bool = True,
        source: str = "api",
    ) -> Dict[str, Any]:
        """Ejecuta cualquier acción física, de SO o Ring-0 cuando el sistema está armado."""
        t0 = time.time()
        act = (action or "").strip().lower().replace("-", "_")
        p = dict(params or {})

        if not is_local_request:
            res = {
                "ok": False,
                "error": "Control absoluto de hardware restringido exclusivamente al host local o sesión soberana autorizada.",
                "security_alert": "REMOTE_HARDWARE_BLOCKED",
            }
            self._record_audit(action=act, params=p, ok=False, source=source, elapsed_ms=(time.time() - t0) * 1000, error=res["error"])
            return res

        # Operaciones de consulta/control de modo siempre permitidas
        if act in ("mode_status", "armed_status"):
            return {"ok": True, "armed": self.is_armed(), "state": dict(self._state)}
        if act == "arm":
            return self.set_mode(enabled=True)
        if act == "disarm":
            return self.set_mode(enabled=False)

        if not self.is_armed():
            res = {
                "ok": False,
                "error": "Control absoluto de hardware desarmado temporalmente. Actívalo con /api/mundo_sin_censura/hardware/mode.",
            }
            self._record_audit(action=act, params=p, ok=False, source=source, elapsed_ms=(time.time() - t0) * 1000, error=res["error"])
            return res

        try:
            res = self._dispatch_internal(act, p)
        except Exception as exc:
            res = {"ok": False, "error": f"Excepción en acción '{act}': {exc}"}

        ok = bool(res.get("ok", res.get("status") == "ok"))
        if "ok" not in res:
            res["ok"] = ok
        elapsed_ms = (time.time() - t0) * 1000.0
        summary = json.dumps({k: v for k, v in res.items() if k not in ("dmesg", "temperatures", "background_layers", "kernel_ring0")}, ensure_ascii=False)[:260]
        self._record_audit(
            action=act,
            params=p,
            ok=ok,
            source=source,
            elapsed_ms=elapsed_ms,
            summary=summary,
            error=res.get("error"),
        )
        _publish_bus(
            "mundo_sin_censura.hardware.action",
            {"action": act, "ok": ok, "source": source, "elapsed_ms": round(elapsed_ms, 2)},
            severity="INFO" if ok else "WARNING",
        )
        return res

    def _dispatch_internal(self, act: str, p: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Telemetría y diagnóstico global
        if act in ("hardware_status", "full_telemetry", "status", "diagnostics", "full_diagnostic"):
            return self.get_full_hardware_telemetry()
        if act in ("cpu_status", "cpu"):
            return {"ok": True, "cpu": self.get_cpu_telemetry()}
        if act in ("gpu_status", "gpu"):
            return self.get_gpu_telemetry()
        if act in ("asus_status", "fans_status", "platform_status"):
            return self.get_asus_platform_telemetry()
        if act in ("display_status", "monitors"):
            return self.get_display_telemetry()
        if act in ("pci_usb_devices", "devices", "lspci", "lsusb"):
            return self.list_pci_usb_devices()
        if act in ("processes_top", "top", "processes"):
            return self.get_top_processes(limit=int(p.get("limit", 15)))

        # 2. Silicio, CPU, ASUS WMI y Energía
        if act in ("set_cpu_governor", "cpu_governor", "governor"):
            return self.set_cpu_governor(str(p.get("governor") or p.get("value") or "performance"))
        if act in ("set_thermal_policy", "thermal_policy", "fan_mode", "asus_thermal"):
            return self.set_thermal_policy(p.get("policy", p.get("mode", p.get("value", "turbo"))))
        if act in ("set_platform_profile", "platform_profile"):
            return self.set_platform_profile(str(p.get("profile") or p.get("value") or "performance"))
        if act in ("set_charge_mode", "charge_mode"):
            return self.set_charge_mode(p.get("mode", p.get("value", 1)))

        # 3. GPU NVIDIA
        if act in ("gpu_set_power_limit", "gpu_power_limit", "set_gpu_power"):
            return self.gpu_set_power_limit(p.get("watts", p.get("limit", p.get("value", 60))))
        if act in ("gpu_persistence", "set_gpu_persistence"):
            return self.gpu_set_persistence(bool(p.get("enabled", True)))
        if act in ("gpu_lock_clocks",):
            return self.gpu_lock_clocks(int(p.get("min_mhz", 210)), int(p.get("max_mhz", 1500)))
        if act in ("gpu_reset_clocks",):
            return self.gpu_reset_clocks()

        # 4. Kernel Ring-0 (FtlKernelBridge + sysfs)
        if act in ("kernel_status", "ring0_status"):
            r = self._kernel().get_kernel_status()
            r["ok"] = r.get("status") == "ok"
            return r
        if act == "psi":
            return {"ok": True, "psi": self._kernel().get_psi_telemetry()}
        if act == "dmesg":
            return {
                "ok": True,
                "lines": self._kernel().read_dmesg(
                    lines=int(p.get("lines", 40)),
                    filter_term=p.get("filter"),
                ),
            }
        if act == "sysctl_get":
            param = str(p.get("param") or p.get("key") or "").strip()
            if not param:
                return {"ok": False, "error": "Parámetro 'param' requerido."}
            return {"ok": True, "param": param, "value": self._kernel().get_sysctl(param)}
        if act == "sysctl_set":
            if not self._state.get("ring0_enabled", True):
                return {"ok": False, "error": "Modo Ring-0 deshabilitado."}
            param = str(p.get("param") or p.get("key") or "").strip()
            val = p.get("value", p.get("val"))
            if not param or val is None:
                return {"ok": False, "error": "Se requieren 'param' y 'value'."}
            r = self._kernel().set_sysctl(param, str(val))
            r["ok"] = r.get("status") == "ok"
            return r
        if act == "drop_caches":
            r = self._kernel().drop_kernel_caches()
            r["ok"] = r.get("status") == "ok"
            return r
        if act in ("tune_kernel", "tune_all"):
            r = self._kernel().apply_sovereign_kernel_tuning()
            r["ok"] = r.get("status") == "ok"
            return r
        if act in ("kernel_modules", "modules", "lsmod", "modprobe"):
            subcmd = str(p.get("subcmd") or ("load" if act == "modprobe" else "list"))
            r = self._kernel().manage_kernel_modules(subcmd=subcmd, mod_name=p.get("name"))
            r["ok"] = r.get("status") == "ok"
            return r
        if act == "uinput_status":
            return {"ok": True, "nodes": self._kernel().check_hardware_nodes()}
        if act == "sysfs_read":
            target = str(p.get("path") or "").strip()
            if not (target.startswith("/sys/") or target.startswith("/proc/")):
                return {"ok": False, "error": "sysfs_read solo acepta rutas bajo /sys/ o /proc/."}
            val = _read_text_safe(Path(target))
            return {"ok": val is not None, "path": target, "value": val}
        if act == "sysfs_write":
            if not self._state.get("ring0_enabled", True):
                return {"ok": False, "error": "Modo Ring-0 deshabilitado."}
            target = str(p.get("path") or "").strip()
            val = p.get("value")
            if not target or val is None:
                return {"ok": False, "error": "Se requieren 'path' y 'value'."}
            ok, method = _sudo_write_sysfs(Path(target), str(val))
            return {"ok": ok, "path": target, "value": str(val), "method": method}
        if act in ("root_exec", "kernel_exec"):
            if not self._state.get("ring0_enabled", True):
                return {"ok": False, "error": "Modo Ring-0 deshabilitado."}
            cmd = str(p.get("command") or p.get("cmd") or "").strip()
            if not cmd:
                return {"ok": False, "error": "Parámetro 'command' requerido."}
            if _is_catastrophic_command(cmd):
                return {"ok": False, "error": "Bloqueado por guarda destructiva AEGIS."}
            rc, out, err = self._kernel().exec_root(cmd, timeout=float(p.get("timeout", 25.0)))
            return {"ok": rc == 0, "rc": rc, "command": cmd, "stdout": out[:4000], "stderr": err[:2000]}

        # 5. Teclado ASUS TUF (con fallback root sysfs), Pantalla, Input uinput
        if act in ("set_keyboard", "set_keyboard_brightness", "keyboard_brightness"):
            return self.set_keyboard_brightness_root(p.get("level", p.get("value", 3)))
        if act in ("toggle_keyboard", "toggle_keyboard_brightness"):
            curr = self._hw().get_keyboard_brightness().get("level", 0)
            return self.set_keyboard_brightness_root(0 if curr > 0 else 3)
        if act in ("display_dpms", "dpms"):
            return self.display_dpms(str(p.get("state") or p.get("value") or "on"))
        if act == "display_mode":
            return self.display_mode(str(p.get("monitor") or "DP-1"), str(p.get("mode") or "preferred,auto,auto"))
        if act in ("type_text", "uinput_type"):
            txt = str(p.get("text") or "")
            press_enter = bool(p.get("press_enter", False))
            ok = self._os().type_keystrokes_uinput(text=txt, press_enter=press_enter, wake_shield=False)
            return {"ok": ok, "backend": "uinput", "text_len": len(txt)}
        if act == "mouse_action":
            return self._os().mouse_action(
                action=str(p.get("subaction") or p.get("mouse_action") or "move"),
                x=p.get("x"),
                y=p.get("y"),
                button=str(p.get("button") or "left"),
                clicks=int(p.get("clicks", 1)),
                dx=int(p.get("dx", 0)),
                dy=int(p.get("dy", 0)),
            )

        # 6. Servicios Systemd
        if act in ("service_status", "service_action", "systemd"):
            unit = str(p.get("unit") or p.get("service") or "")
            op = "status" if act == "service_status" else str(p.get("op") or p.get("operation") or "status")
            scope = str(p.get("scope") or "user")
            return self.manage_systemd_service(unit=unit, op=op, scope=scope)

        # 7. Shell local auditado (con guarda destructiva)
        if act in ("run_shell", "shell", "command", "bash", "terminal_exec", "sh"):
            cmd = str(p.get("command") or p.get("cmd") or "").strip()
            if _is_catastrophic_command(cmd):
                return {"ok": False, "error": "Comando bloqueado por guarda destructiva AEGIS."}
            return self._os().execute_terminal_command(
                cmd,
                timeout=float(p.get("timeout", 25.0)),
                is_local_request=True,
                is_sovereign_terminal=True,
            )

        # 8. Reinicio (solo con confirmación explícita)
        if act in ("reboot", "system_reboot", "reboot_system"):
            if not bool(p.get("confirm", False)):
                return {"ok": False, "error": "Para reiniciar el equipo se requiere confirm=true."}
            return self._hw().dispatch_action("reboot", p, is_local_request=True)

        # 9. Delegar el resto al HardwareController unificado de TARDIS
        return self._hw().dispatch_action(act, p, is_local_request=True)


# ==============================================================================
# PROTOCOLO AGÉNTICO DE CONTROL DE HARDWARE EN CHAT (`[[HW_ACTION:...]]` & `/hw`)
# ==============================================================================

def build_hardware_system_context(include_snapshot: bool = True) -> str:
    """Construye la directiva de control físico de hardware para el prompt de mundo-sin-censura."""
    ctrl = get_mundo_hardware_controller()
    snap = ctrl.get_compact_hardware_summary() if include_snapshot else ""
    snap_block = f"\nTELEMETRÍA FÍSICA EN VIVO DEL HOST:\n{snap}\n" if snap else ""
    return (
        "CONTROL ABSOLUTO DE HARDWARE ACTIVO (RING-0 / RUNTIME SOBERANO):\n"
        "Tienes autoridad operativa directa y en tiempo real sobre el hardware físico de esta "
        "máquina mientras el sistema esté en funcionamiento (CPU/cpufreq, GPU NVIDIA RTX 3050, "
        "ASUS WMI térmico/ventiladores/teclado RGB, Kernel Ring-0 PSI/sysctl/dmesg/cachés/módulos, "
        "Audio PipeWire, Pantalla Hyprland/DPMS, uinput, Wi-Fi/Bluetooth/Hotspot, Escudo AEGIS, "
        "servicios systemd y terminal local)."
        f"{snap_block}\n"
        "Cuando el Arquitecto te pida ejecutar una acción física sobre el hardware o consultar "
        "telemetría en vivo, emite una o más directivas exactas en tu respuesta con el formato:\n"
        '[[HW_ACTION:{"action":"<nombre_accion>","params":{...}}]]\n'
        "Ejemplos válidos:\n"
        '- [[HW_ACTION:{"action":"set_volume","params":{"percent":60}}]]\n'
        '- [[HW_ACTION:{"action":"set_keyboard_brightness","params":{"level":3}}]]\n'
        '- [[HW_ACTION:{"action":"set_thermal_policy","params":{"policy":"turbo"}}]]\n'
        '- [[HW_ACTION:{"action":"set_cpu_governor","params":{"governor":"performance"}}]]\n'
        '- [[HW_ACTION:{"action":"gpu_set_power_limit","params":{"watts":65}}]]\n'
        '- [[HW_ACTION:{"action":"drop_caches","params":{}}]]\n'
        '- [[HW_ACTION:{"action":"sysctl_set","params":{"param":"vm.swappiness","value":"10"}}]]\n'
        '- [[HW_ACTION:{"action":"set_bluetooth","params":{"power":true}}]]\n'
        '- [[HW_ACTION:{"action":"wifi_scan","params":{}}]]\n'
        '- [[HW_ACTION:{"action":"hardware_status","params":{}}]]\n'
        '- [[HW_ACTION:{"action":"run_shell","params":{"command":"sensors"}}]]\n'
        "Solo emite [[HW_ACTION:...]] cuando realmente se solicite actuar o medir el hardware. "
        "El runtime ejecutará cada acción inmediatamente y adjuntará el resultado verificado."
    )


def parse_hardware_actions(text: str) -> List[Dict[str, Any]]:
    """Extrae bloques `[[HW_ACTION:{...}]]` soportando objetos JSON anidados."""
    if not text or "[[HW_ACTION:" not in text:
        return []
    actions: List[Dict[str, Any]] = []
    marker = "[[HW_ACTION:"
    idx = 0
    n = len(text)
    while idx < n:
        start = text.find(marker, idx)
        if start < 0:
            break
        pos = start + len(marker)
        while pos < n and text[pos].isspace():
            pos += 1
        if pos >= n or text[pos] != "{":
            idx = pos
            continue
        depth = 0
        in_str = False
        esc = False
        end_json = -1
        for i in range(pos, n):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_json = i + 1
                        break
        if end_json < 0:
            break
        raw_json = text[pos:end_json]
        tail = text[end_json:end_json + 4]
        idx = end_json + (2 if tail.startswith("]]") else 0)
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict) and obj.get("action"):
                actions.append({
                    "action": str(obj["action"]).strip(),
                    "params": obj.get("params") if isinstance(obj.get("params"), dict) else {},
                })
        except Exception:
            continue
    return actions


def parse_slash_hw_command(prompt: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parsea comandos directos de usuario como:
      /hw status
      /hw set_volume percent=70
      /hw set_thermal_policy {"policy": "turbo"}
      /hw run_shell command="uptime"
    """
    txt = (prompt or "").strip()
    if not (txt.startswith("/hw ") or txt == "/hw"):
        return None
    rest = txt[3:].strip()
    if not rest:
        return ("hardware_status", {})
    parts = rest.split(maxsplit=1)
    action = parts[0].strip()
    arg_str = parts[1].strip() if len(parts) > 1 else ""
    params: Dict[str, Any] = {}
    if arg_str:
        if arg_str.startswith("{"):
            try:
                parsed = json.loads(arg_str)
                if isinstance(parsed, dict):
                    params = parsed
            except Exception:
                params = {"value": arg_str}
        else:
            try:
                tokens = shlex.split(arg_str)
            except Exception:
                tokens = arg_str.split()
            has_kv = any("=" in t for t in tokens)
            if has_kv:
                for tok in tokens:
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        vl = v.lower()
                        if vl in ("true", "on", "si", "sí"):
                            params[k] = True
                        elif vl in ("false", "off"):
                            params[k] = False
                        else:
                            try:
                                params[k] = int(v)
                            except ValueError:
                                try:
                                    params[k] = float(v)
                                except ValueError:
                                    params[k] = v
            else:
                if action in ("run_shell", "shell", "bash", "root_exec", "kernel_exec"):
                    params = {"command": arg_str}
                elif action in ("set_volume", "set_screen_brightness"):
                    try:
                        params = {"percent": int(arg_str)}
                    except ValueError:
                        params = {"percent": arg_str}
                elif action in ("set_keyboard_brightness", "set_keyboard"):
                    try:
                        params = {"level": int(arg_str)}
                    except ValueError:
                        params = {"level": arg_str}
                elif action in ("set_cpu_governor", "governor"):
                    params = {"governor": arg_str}
                elif action in ("set_thermal_policy", "thermal_policy"):
                    params = {"policy": arg_str}
                elif action in ("set_power_profile", "power_profile"):
                    params = {"profile": arg_str}
                elif action in ("gpu_set_power_limit",):
                    try:
                        params = {"watts": float(arg_str)}
                    except ValueError:
                        params = {"watts": arg_str}
                elif action in ("sysctl_get",):
                    params = {"param": arg_str}
                else:
                    params = {"value": arg_str}
    return (action, params)


def format_hardware_result_markdown(action: str, result: Dict[str, Any]) -> str:
    """Formatea un resultado de ejecución de hardware en Markdown compacto y legible."""
    ok = bool(result.get("ok"))
    badge = "✅ OK" if ok else "❌ ERROR"
    compact = dict(result)
    # Acortar bloques muy extensos para el chat
    if "temperatures" in compact and isinstance(compact["temperatures"], dict):
        compact["temperatures"] = {k: len(v) for k, v in compact["temperatures"].items()}
    if "background_layers" in compact:
        compact["background_layers"] = "active"
    if "kernel_ring0" in compact and isinstance(compact["kernel_ring0"], dict):
        kr = compact["kernel_ring0"]
        compact["kernel_ring0"] = {
            "release": kr.get("kernel_release"),
            "sovereign_mode": kr.get("sovereign_mode"),
            "psi_cpu_10": (kr.get("psi", {}).get("cpu", {}).get("some", {}) or {}).get("avg10"),
        }
    body = json.dumps(compact, indent=2, ensure_ascii=False)
    if len(body) > 1800:
        body = body[:1800] + "\n... [truncado]"
    return f"\n\n> ⚡ **Hardware Ring-0 · `{action}` ({badge})**\n```json\n{body}\n```"


_HW_LOCK = threading.Lock()
_HW_SINGLETON: Optional[MundoSinCensuraHardwareController] = None


def get_mundo_hardware_controller() -> MundoSinCensuraHardwareController:
    global _HW_SINGLETON
    with _HW_LOCK:
        if _HW_SINGLETON is None:
            _HW_SINGLETON = MundoSinCensuraHardwareController()
        return _HW_SINGLETON
