"""
core/os_optimizer.py - Optimizador Soberano de Sistema Operativo y Runtime
==========================================================================
GODWORKS SYSTEM & TARDIS Sovereign Architecture

Misión:
1. Ajustar los parámetros de recolección de basura (GC) y memoria de Python
   para evitar micro-pausas durante inferencia, radar RF y streaming.
2. Aplicar prioridades de I/O de disco (ionice) y CPU al proceso en ejecución.
3. Garantizar que todas las conexiones SQLite operen con mmap_size de 2 GB,
   cache_size en RAM y modo WAL sin bloqueos.
4. Monitorear parámetros del kernel (swappiness, somaxconn, limits).
"""

from __future__ import annotations

import gc
import logging
import os
import psutil
import resource
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("godworks.os_optimizer")


class OSOptimizer:
    """Motor soberano de optimización en tiempo de ejecución del sistema."""

    _instance = None

    def __init__(self):
        self.applied = False
        self.diagnostics: Dict[str, Any] = {}

    @classmethod
    def get_instance(cls) -> "OSOptimizer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def apply_runtime_optimizations(self) -> Dict[str, Any]:
        """Aplica todas las optimizaciones seguras a nivel de proceso y runtime."""
        results = {}

        # 1. Optimización del Recolector de Basura (Garbage Collector)
        try:
            old_thresholds = gc.get_threshold()
            # Elevar el umbral de generación 0 de 700 a 50,000 para evitar micro-pausas en inferencia
            gc.set_threshold(50000, 10, 10)
            results["gc_tuned"] = {
                "old_thresholds": old_thresholds,
                "new_thresholds": gc.get_threshold(),
                "status": "active"
            }
        except Exception as e:
            results["gc_tuned"] = {"status": "error", "error": str(e)}

        # 2. Prioridad de I/O (ionice) sobre el disco
        try:
            proc = psutil.Process()
            if hasattr(psutil, "IOPRIO_CLASS_BE"):
                proc.ionice(psutil.IOPRIO_CLASS_BE, value=1)
                results["ionice"] = "best-effort (priority 1)"
            else:
                results["ionice"] = "not_supported"
        except Exception as e:
            results["ionice"] = f"warning: {e}"

        # 3. Límites de Descriptores de Archivo (NOFILE)
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            target = min(65536, hard)
            if soft < target:
                resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
                results["nofile_limit"] = {"old_soft": soft, "new_soft": target, "hard": hard}
            else:
                results["nofile_limit"] = {"soft": soft, "hard": hard}
        except Exception as e:
            results["nofile_limit"] = f"warning: {e}"

        # 4. Ajuste de asignación de memoria glibc
        try:
            import ctypes
            libc = ctypes.CDLL(None)
            # M_TRIM_THRESHOLD = -1, M_MMAP_THRESHOLD = -3
            if hasattr(libc, "mallopt"):
                libc.mallopt(-1, 131072)  # M_TRIM_THRESHOLD: 128 KB
                results["mallopt"] = "trimmed_threshold_128k"
        except Exception as e:
            results["mallopt"] = f"skipped: {e}"

        self.applied = True
        self.diagnostics = results
        logger.info(f"[OSOptimizer] ✅ Optimizaciones de SO y Runtime aplicadas: {results}")
        return results

    def tune_sqlite_connection(self, conn: sqlite3.Connection) -> None:
        """Aplica directivas de alto rendimiento y zero-copy I/O a conexiones SQLite."""
        try:
            total_ram_gb = psutil.virtual_memory().total / (1024**3)
            # Para 32 GB de RAM, asignar 4 GB de MMAP y 128 MB de caché SQLite
            if total_ram_gb >= 30.0:
                cache_size = -128000       # 128 MB de caché en RAM
                mmap_size = 4294967296     # 4 GB zero-copy memory-mapped I/O
            else:
                cache_size = -64000        # 64 MB de caché en RAM
                mmap_size = 2147483648     # 2 GB zero-copy memory-mapped I/O

            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute(f"PRAGMA cache_size = {cache_size}")
            conn.execute(f"PRAGMA mmap_size = {mmap_size}")
            conn.execute("PRAGMA busy_timeout = 10000")
        except Exception as e:
            logger.debug(f"[OSOptimizer] Aviso al tunear SQLite: {e}")

    def get_system_efficiency_report(self) -> Dict[str, Any]:
        """Genera un reporte de eficiencia del sistema operativo y hardware."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        swappiness = "unknown"
        if os.path.exists("/proc/sys/vm/swappiness"):
            try:
                swappiness = Path("/proc/sys/vm/swappiness").read_text().strip()
            except Exception:
                pass

        vfs_pressure = "unknown"
        if os.path.exists("/proc/sys/vm/vfs_cache_pressure"):
            try:
                vfs_pressure = Path("/proc/sys/vm/vfs_cache_pressure").read_text().strip()
            except Exception:
                pass

        soft_nofile, hard_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)

        return {
            "ok": True,
            "runtime_optimizations_applied": self.applied,
            "cpu_cores_logical": psutil.cpu_count(logical=True),
            "cpu_cores_physical": psutil.cpu_count(logical=False),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_available_gb": round(mem.available / (1024**3), 2),
            "ram_percent_used": mem.percent,
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "swappiness": swappiness,
            "vfs_cache_pressure": vfs_pressure,
            "nofile_soft_limit": soft_nofile,
            "nofile_hard_limit": hard_nofile,
            "gc_thresholds": gc.get_threshold(),
            "diagnostics": self.diagnostics
        }


def get_os_optimizer() -> OSOptimizer:
    return OSOptimizer.get_instance()
