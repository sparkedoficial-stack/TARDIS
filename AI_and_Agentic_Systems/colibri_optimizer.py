"""
colibri_optimizer.py - Motor de Optimización de Parámetros y Calibración de Hardware
=====================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana GIA · Integración Colibri MoE
=====================================================================================

Optimiza dinámicamente los parámetros de inferencia para motores de transmisión
de expertos (JustVugg/colibri) adaptados al hardware específico del sistema anfitrión:
- CPU: AMD Ryzen 7 4800H (8 núcleos físicos / 16 lógicos Zen 2)
- RAM: ~24 GB DDR4 (20 GB dedicados al Working Set / LRU Cache de expertos)
- GPU: NVIDIA GeForce RTX 3050 Laptop GPU (4 GB VRAM Ampere sm_86)
- Disco: SSD NVMe de alta velocidad en C: (O_DIRECT + Async Pipelining)
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = Path(__file__).resolve().parent
COLIBRI_DIR = WORKSPACE_DIR / "colibri"
PROFILE_PATH = WORKSPACE_DIR / "colibri_profile.json"


class HardwareSensor:
    """Detecta con precisión la topología de cómputo, memoria y almacenamiento."""

    @staticmethod
    def get_cpu_info() -> Dict[str, Any]:
        info = {
            "name": platform.processor() or "Unknown CPU",
            "physical_cores": 8,
            "logical_cores": os.cpu_count() or 16,
            "architecture": platform.machine()
        }
        try:
            import psutil
            phys = psutil.cpu_count(logical=False)
            logi = psutil.cpu_count(logical=True)
            if phys:
                info["physical_cores"] = phys
            if logi:
                info["logical_cores"] = logi
        except Exception:
            pass

        if sys.platform.startswith("linux"):
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            info["name"] = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass
        elif sys.platform == "win32" and info["physical_cores"] == info["logical_cores"]:
            try:
                cmd = ["powershell", "-NoProfile", "-Command", 
                       "(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors) | ConvertTo-Json"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    if isinstance(data, list):
                        data = data[0]
                    info["name"] = data.get("Name", info["name"])
                    info["physical_cores"] = int(data.get("NumberOfCores", info["physical_cores"]))
                    info["logical_cores"] = int(data.get("NumberOfLogicalProcessors", info["logical_cores"]))
            except Exception:
                pass
        return info

    @staticmethod
    def get_memory_info() -> Dict[str, Any]:
        info = {
            "total_gb": 16.0,
            "available_gb": 8.0
        }
        try:
            import psutil
            vm = psutil.virtual_memory()
            info["total_gb"] = round(vm.total / (1024**3), 2)
            info["available_gb"] = round(vm.available / (1024**3), 2)
            return info
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                cmd = ["powershell", "-NoProfile", "-Command",
                       "[math]::round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
                if res.returncode == 0 and res.stdout.strip():
                    info["total_gb"] = float(res.stdout.strip())
                    info["available_gb"] = max(4.0, info["total_gb"] - 6.0)
            except Exception:
                pass
        return info

    @staticmethod
    def get_gpu_info() -> Dict[str, Any]:
        info = {
            "available": False,
            "name": "None",
            "vram_total_mb": 0,
            "vram_free_mb": 0,
            "sm_arch": "sm_86"
        }
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3
            )
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    info["available"] = True
                    info["name"] = parts[0]
                    info["vram_total_mb"] = int(parts[1])
                    info["vram_free_mb"] = int(parts[2])
                    if "3050" in parts[0] or "30" in parts[0]:
                        info["sm_arch"] = "sm_86"
                    elif "40" in parts[0]:
                        info["sm_arch"] = "sm_89"
                    elif "50" in parts[0]:
                        info["sm_arch"] = "sm_120"
        except Exception:
            pass
        return info

    @staticmethod
    def get_storage_info(path: Optional[Path] = None) -> Dict[str, Any]:
        target = path or WORKSPACE_DIR
        info = {
            "drive": str(target.drive or target.anchor or "/"),
            "free_gb": 100.0,
            "total_gb": 500.0,
            "is_nvme": True
        }
        try:
            import shutil
            du = shutil.disk_usage(str(target))
            info["free_gb"] = round(du.free / (1024**3), 1)
            info["total_gb"] = round(du.total / (1024**3), 1)
            return info
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                drive_letter = str(target.drive or "C:").rstrip("\\")
                cmd = ["powershell", "-NoProfile", "-Command",
                       f"$d = Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='{drive_letter}'\"; "
                       "[PSCustomObject]@{ TotalGB=[math]::round($d.Size/1GB, 1); FreeGB=[math]::round($d.FreeSpace/1GB, 1) } | ConvertTo-Json"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
                if res.returncode == 0 and res.stdout.strip():
                    d = json.loads(res.stdout)
                    info["free_gb"] = float(d.get("FreeGB", 100.0))
                    info["total_gb"] = float(d.get("TotalGB", 500.0))
            except Exception:
                pass
        return info


class ColibriParameterOptimizer:
    """Calcula la matriz óptima de banderas y variables de entorno para Colibri."""

    def __init__(self):
        self.sensor = HardwareSensor()
        self.cpu = self.sensor.get_cpu_info()
        self.mem = self.sensor.get_memory_info()
        self.gpu = self.sensor.get_gpu_info()
        self.storage = self.sensor.get_storage_info()

    def calculate_tuning_matrix(self, model_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Calcula la configuración óptima de Colibri:
        - OMP_NUM_THREADS = núcleos físicos (8) para mitigar contención SMT
        - RAM_GB = presupuesto de caché LRU seguro (20 GB en sistema de 24 GB)
        - DIRECT = 1 (O_DIRECT desvío de caché Windows NVMe)
        - PIPE = 1 con 8 workers (solapa pread con matmul)
        - PILOT = 1 (prefetch predictivo de 1 capa)
        - AUTOPIN = 1 (aprendizaje dinámico de consultas en .coli_usage)
        - KVSAVE = 1 (persistencia de KV comprimido en .coli_kv)
        - MTP = 1, SPEC_PIN = 1 (especulación de múltiples tokens)
        """
        # Presupuesto de RAM para expertos: 20 GB asignados de los 24 GB del sistema
        total_ram = self.mem.get("total_gb", 16.0)
        forced_ram = os.environ.get("RAM_GB")
        if forced_ram:
            try:
                ram_budget_gb = float(forced_ram)
            except ValueError:
                ram_budget_gb = 20.0
        elif total_ram >= 32.0:
            ram_budget_gb = 26.0
        elif total_ram >= 22.0:
            ram_budget_gb = 20.0  # 20 GB dedicados de los 24 GB totales para Colibri
        elif total_ram >= 16.0:
            ram_budget_gb = 14.0
        else:
            ram_budget_gb = max(4.0, total_ram - 3.0)

        physical_cores = max(2, self.cpu.get("physical_cores", 8))
        pipe_workers = min(16, max(4, physical_cores))

        # Variables de entorno clave leídas por colibri.exe, qwen38.exe, deepseek_v4.exe
        env_vars = {
            "OMP_NUM_THREADS": str(physical_cores),
            "OMP_PROC_BIND": "close",
            "OMP_PLACES": "cores",
            "OLLAMA_KV_CACHE_TYPE": "q4_0",
            "COLI_NO_OMP_TUNE": "0",
            "RAM_GB": f"{ram_budget_gb:.1f}",
            "DIRECT": "1" if self.storage.get("is_nvme", True) else "0",
            "PIPE": "1",
            "PIPE_WORKERS": str(pipe_workers),
            "PILOT": "1",
            "PILOT_WORKERS": "1",
            "AUTOPIN": "1",
            "PIN": "auto",
            "KVSAVE": "1",
            "MTP": "1",
            "SPEC_PIN": "1",
            "COLI_TEMP": "0.3",
            "NUCLEUS": "0.90",
            "REP_PEN": "1.15",
            "CTX": "4096",
            "COLI_PREFILL_CHUNK": "256",
            "COLI_POLICY": "balanced"
        }

        # Banderas de CLI para `coli run`, `coli chat`, `coli serve`
        cli_flags = [
            f"--ram {ram_budget_gb:.1f}",
            "--ctx 4096",
            "--temp 0.3",
            "--topp 0.90",
            "--policy balanced"
        ]

        if self.gpu.get("available") and self.gpu.get("vram_total_mb", 0) >= 3800:
            # RTX 3050 Laptop 4GB: activar aceleración de VRAM tier para proyecciones
            env_vars["COLI_CUDA"] = "1"
            env_vars["COLI_CUDA_MOE_BATCH"] = "1"
            cli_flags.append("--gpu 0")

        return {
            "hardware": {
                "cpu": self.cpu,
                "memory": self.mem,
                "gpu": self.gpu,
                "storage": self.storage
            },
            "environment_variables": env_vars,
            "recommended_cli_flags": cli_flags,
            "model_path": model_path or ""
        }

    def save_profile(self, filepath: Optional[Path] = None) -> Path:
        dest = filepath or PROFILE_PATH
        data = self.calculate_tuning_matrix()
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return dest

    def get_applied_env(self, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Devuelve una copia del entorno del sistema con todas las optimizaciones inyectadas."""
        current = dict(base_env or os.environ)
        tuning = self.calculate_tuning_matrix()
        for k, v in tuning["environment_variables"].items():
            current[k] = v
        # Agregar directorio colibri al PATH
        if str(COLIBRI_DIR) not in current.get("PATH", ""):
            current["PATH"] = f"{str(COLIBRI_DIR)};{current.get('PATH', '')}"
        return current


def print_summary():
    opt = ColibriParameterOptimizer()
    matrix = opt.calculate_tuning_matrix()
    print("=" * 70)
    print("GODWORKS SYSTEM v26.4 · PERFIL DE OPTIMIZACIÓN DE COLIBRI")
    print("=" * 70)
    hw = matrix["hardware"]
    print(f"CPU: {hw['cpu']['name']} ({hw['cpu']['physical_cores']} núcleos físicos / {hw['cpu']['logical_cores']} hilos)")
    print(f"RAM: {hw['memory']['total_gb']} GB detectados -> Presupuesto LRU Colibri: {matrix['environment_variables']['RAM_GB']} GB")
    print(f"GPU: {hw['gpu']['name']} ({hw['gpu']['vram_total_mb']} MB VRAM)")
    print(f"Almacenamiento: Unidad {hw['storage']['drive']} ({hw['storage']['free_gb']} GB libres)")
    print("\nParámetros de Inferencia y E/S Optimizados:")
    for k, v in matrix["environment_variables"].items():
        print(f"  • {k:22} = {v}")
    saved = opt.save_profile()
    print(f"\n[OK] Perfil persistido exitosamente en: {saved}")
    print("=" * 70)


if __name__ == "__main__":
    print_summary()
