"""
kernel_controller.py - Controlador de Nivel Kernel y Gobernador de Hardware
========================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Proporciona telemetría profunda, control de afinidad de núcleos (sched_affinity),
prioridad de procesos (nice / ionice), supervisión térmica (/sys/class/thermal),
monitoreo de memoria en tiempo real (/proc/meminfo) y aceleración de hardware
(AMD Ryzen 7 16 hilos + NVIDIA RTX 3050 CUDA).
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = logging.getLogger("Cognitivo.KernelController")


@dataclass
class KernelTelemetry:
    kernel_release: str
    kernel_version: str
    uptime_seconds: float
    load_avg: Tuple[float, float, float]
    cpu_cores_physical: int
    cpu_threads_logical: int
    cpu_freq_mhz: float
    cpu_percent: float
    ram_total_gb: float
    ram_used_gb: float
    ram_percent: float
    swap_used_gb: float
    temperatures_c: Dict[str, float]
    gpu_available: bool
    gpu_name: str
    gpu_vram_total_mb: float
    gpu_vram_used_mb: float
    kernel_modules_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KernelController:
    """
    Gobernador del Sistema Operativo y Núcleo Linux para TARDIS Cognitivo.
    Supervisa recursos y optimiza la ejecución de simulaciones y cómputo.
    """

    _instance: Optional[KernelController] = None

    def __init__(self):
        self._thermal_paths = self._discover_thermal_sensors()
        self._cpu_threads = os.cpu_count() or 16
        logger.info(f"[KERNEL] Inicializado con {self._cpu_threads} hilos lógicos.")

    @classmethod
    def get_instance(cls) -> KernelController:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _discover_thermal_sensors(self) -> Dict[str, Path]:
        sensors = {}
        for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
            z_path = Path(zone)
            type_file = z_path / "type"
            temp_file = z_path / "temp"
            if temp_file.is_file():
                name = z_path.name
                if type_file.is_file():
                    try:
                        name = type_file.read_text().strip()
                    except Exception:
                        pass
                sensors[name] = temp_file
        return sensors

    def get_temperatures(self) -> Dict[str, float]:
        temps = {}
        for name, p in self._thermal_paths.items():
            try:
                raw = float(p.read_text().strip())
                # Los sensores Linux reportan miligrados Celsius
                temps[name] = round(raw / 1000.0, 1)
            except Exception:
                continue
        return temps

    def get_kernel_release(self) -> str:
        try:
            return Path("/proc/sys/kernel/osrelease").read_text().strip()
        except Exception:
            return os.uname().release

    def get_kernel_version(self) -> str:
        try:
            return Path("/proc/version").read_text().strip()
        except Exception:
            return os.uname().version

    def get_gpu_telemetry(self) -> Dict[str, Any]:
        info = {
            "available": False,
            "name": "N/A",
            "vram_total_mb": 0.0,
            "vram_used_mb": 0.0,
            "gpu_utilization_pct": 0.0,
            "temperature_c": 0.0
        }

        # Inspección por PyTorch
        if TORCH_AVAILABLE and torch.cuda.is_available():
            info["available"] = True
            info["name"] = torch.cuda.get_device_name(0)
            mem = torch.cuda.mem_get_info(0)
            info["vram_total_mb"] = round((mem[1]) / (1024**2), 1)
            info["vram_used_mb"] = round((mem[1] - mem[0]) / (1024**2), 1)

        # Inspección precisa por nvidia-smi
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                if len(parts) >= 5:
                    info["available"] = True
                    info["name"] = parts[0]
                    info["vram_total_mb"] = float(parts[1])
                    info["vram_used_mb"] = float(parts[2])
                    info["gpu_utilization_pct"] = float(parts[3])
                    info["temperature_c"] = float(parts[4])
        except Exception:
            pass

        return info

    def get_telemetry(self) -> KernelTelemetry:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        cpu_freq = psutil.cpu_freq()
        load_avg = os.getloadavg()
        temps = self.get_temperatures()
        gpu = self.get_gpu_telemetry()

        # Contador de módulos cargados en el kernel
        mod_count = 0
        try:
            if Path("/proc/modules").is_file():
                mod_count = len(Path("/proc/modules").read_text().splitlines())
        except Exception:
            pass

        # Uptime
        uptime = 0.0
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            pass

        return KernelTelemetry(
            kernel_release=self.get_kernel_release(),
            kernel_version=self.get_kernel_version(),
            uptime_seconds=uptime,
            load_avg=load_avg,
            cpu_cores_physical=psutil.cpu_count(logical=False) or 8,
            cpu_threads_logical=self._cpu_threads,
            cpu_freq_mhz=round(cpu_freq.current, 1) if cpu_freq else 0.0,
            cpu_percent=psutil.cpu_percent(interval=None),
            ram_total_gb=round(mem.total / (1024**3), 2),
            ram_used_gb=round(mem.used / (1024**3), 2),
            ram_percent=mem.percent,
            swap_used_gb=round(swap.used / (1024**3), 2),
            temperatures_c=temps,
            gpu_available=gpu["available"],
            gpu_name=gpu["name"],
            gpu_vram_total_mb=gpu["vram_total_mb"],
            gpu_vram_used_mb=gpu["vram_used_mb"],
            kernel_modules_count=mod_count
        )

    def optimize_simulation_affinity(self, target_cores: Optional[List[int]] = None) -> bool:
        """
        Asigna la afinidad de CPU para este proceso o hilo en núcleos específicos
        de alto rendimiento (e.g. núcleos 4-15 para dejar 0-3 libres para la UI y OS).
        """
        if not hasattr(os, "sched_setaffinity"):
            return False

        if target_cores is None:
            # En Ryzen 7 (16 hilos), dedicar hilos 4 a 15 para simulaciones pesadas
            total = self._cpu_threads
            target_cores = list(range(min(4, total - 1), total))

        try:
            os.sched_setaffinity(0, set(target_cores))
            logger.info(f"[KERNEL] Afinidad de simulación fijada en núcleos: {target_cores}")
            return True
        except Exception as e:
            logger.warning(f"[KERNEL] No se pudo fijar afinidad de CPU: {e}")
            return False

    def set_nice_priority(self, nice_value: int = 10) -> bool:
        """
        Ajusta la prioridad de programación 'nice' del proceso.
        nice_value > 0 permite correr en segundo plano sin ralentizar tareas del usuario.
        """
        try:
            p = psutil.Process()
            p.nice(nice_value)
            logger.info(f"[KERNEL] Prioridad nice fijada en {nice_value}")
            return True
        except Exception as e:
            logger.warning(f"[KERNEL] Error ajustando nice: {e}")
            return False

    def is_thermal_safe(self, max_celsius: float = 85.0) -> Tuple[bool, float]:
        """Verifica si las temperaturas del sistema están dentro del límite seguro."""
        temps = self.get_temperatures()
        if not temps:
            return True, 0.0
        max_t = max(temps.values())
        return (max_t < max_celsius), max_t


def get_kernel_controller() -> KernelController:
    return KernelController.get_instance()
