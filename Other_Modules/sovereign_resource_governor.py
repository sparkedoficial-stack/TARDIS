#!/usr/bin/env python3
"""
core/sovereign_resource_governor.py - Gobernador de Recursos Ring 0 y Árbitro de Inferencia
===========================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Sistema alterno soberano diseñado para eliminar contención de silicio, saturación de CPU/PSI,
swap thrashing y modelos duplicados en RAM/VRAM entre los 35+ demonios de TARDIS:

1. Telemetría Kernel Ring 0 en tiempo real:
   - /proc/pressure/cpu, /proc/pressure/memory, /proc/pressure/io (PSI avg10/avg60/avg300)
   - /proc/meminfo (RAM total, disponible, usada, swap usada, Mlocked)
   - /proc/loadavg y número de hilos lógicos
   - GPU NVIDIA RTX 3050 (VRAM usada/libre, utilización, temperatura vía nvidia-smi)
   - Inspección de modelos cargados en Temporal Brain (/tmp/temporal_brain.sock),
     Ollama CPU (:11434) y Ollama GPU Voice/Vision Lane (:11435).

2. Control de Admisión (Backpressure Arbiter):
   - Calcula nivel de presión determinista: NOMINAL | ELEVATED | CONSTRAINED | CRITICAL.
   - `can_admit(task_type, priority)` decide si un demonio pesado puede ejecutar un ciclo
     o debe diferirlo hasta que baje la contención o termine una llamada de Telegram.

3. Auto-Reclamación Soberana (`reclaim`):
   - Detecta modelos LLM/VLM duplicados en Ollama CPU (:11434) que ya residen en
     Temporal Brain o en Ollama GPU (:11435) y los descarga limpiamente (keep_alive=0).
   - Detecta directorios temporales huérfanos `/dev/shm/tardis_browser_*` sin Chrome activo.
   - Rota respaldos `.bak.*` redundantes hacia `_selfmod_backups/archived_baks/`.

4. Persistencia de Series Temporales y Emisión al Bus de Eventos:
   - Snapshot atómico en `data/resource_governor_state.json`.
   - Historial en SQLite WAL `data/resource_governor.db` (retención 7 días).
   - Emite eventos `resource.pressure_high` / `resource.reclaimed` al SovereignEventBus.
"""
from __future__ import annotations

import argparse
import datetime
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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TARDIS.ResourceGovernor")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [RESOURCE-GOVERNOR] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "resource_governor_state.json"
DB_FILE = DATA_DIR / "resource_governor.db"
ARCHIVE_BAK_DIR = PROJECT_ROOT / "_selfmod_backups" / "archived_baks"

TEMPORAL_BRAIN_SOCK = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
OLLAMA_CPU_URL = os.environ.get("OLLAMA_CPU_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_GPU_URL = os.environ.get("OLLAMA_GPU_URL", "http://127.0.0.1:11435").rstrip("/")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: Any) -> None:
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


def _parse_psi_file(path: Path) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            kind = parts[0]
            metrics: Dict[str, float] = {}
            for tok in parts[1:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    try:
                        metrics[k] = float(v)
                    except ValueError:
                        pass
            out[kind] = metrics
    except Exception:
        pass
    return out


def _read_meminfo_mb() -> Dict[str, float]:
    info: Dict[str, float] = {}
    p = Path("/proc/meminfo")
    if not p.is_file():
        return info
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            toks = rest.strip().split()
            if toks:
                try:
                    val_kb = float(toks[0])
                    info[k.strip()] = round(val_kb / 1024.0, 1)
                except ValueError:
                    pass
    except Exception:
        pass
    return info


def _read_loadavg() -> Tuple[float, float, float]:
    try:
        l1, l5, l15 = os.getloadavg()
        return round(l1, 2), round(l5, 2), round(l15, 2)
    except Exception:
        return 0.0, 0.0, 0.0


def _read_gpu_telemetry() -> Dict[str, Any]:
    if not shutil.which("nvidia-smi"):
        return {"available": False}
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"available": False}
        parts = [x.strip() for x in proc.stdout.strip().splitlines()[0].split(",")]
        if len(parts) < 6:
            return {"available": False}
        total_mb = float(parts[1])
        used_mb = float(parts[2])
        free_mb = float(parts[3])
        return {
            "available": True,
            "name": parts[0],
            "vram_total_mb": total_mb,
            "vram_used_mb": used_mb,
            "vram_free_mb": free_mb,
            "vram_percent": round((used_mb / max(1.0, total_mb)) * 100.0, 1),
            "util_percent": float(parts[4]),
            "temp_c": float(parts[5]),
        }
    except Exception:
        return {"available": False}


def _http_get_json(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TARDIS-ResourceGovernor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None
    return None


def _check_temporal_brain_sock() -> bool:
    if not TEMPORAL_BRAIN_SOCK.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(TEMPORAL_BRAIN_SOCK))
        s.close()
        return True
    except Exception:
        return False


def _is_telegram_call_active() -> bool:
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from core.telegram_call_priority import is_call_priority_active
        return bool(is_call_priority_active())
    except Exception:
        return False


class SovereignResourceGovernor:
    """
    Gobernador de Recursos Ring 0 y Árbitro de Admisión/Reclamación para TARDIS.
    """

    _instance: Optional["SovereignResourceGovernor"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "SovereignResourceGovernor":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_snapshot: Dict[str, Any] = {}
        self._last_snapshot_ts: float = 0.0
        self._init_db()

    def _init_db(self) -> None:
        try:
            DB_FILE.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(DB_FILE, timeout=10.0) as con:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=NORMAL")
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        iso TEXT NOT NULL,
                        pressure_level TEXT NOT NULL,
                        pressure_score REAL NOT NULL,
                        load1 REAL,
                        cpu_psi_avg10 REAL,
                        mem_psi_avg10 REAL,
                        io_psi_avg10 REAL,
                        ram_used_pct REAL,
                        ram_avail_mb REAL,
                        swap_used_mb REAL,
                        mlocked_mb REAL,
                        vram_used_mb REAL,
                        gpu_temp_c REAL,
                        duplicate_models INTEGER DEFAULT 0
                    )
                    """
                )
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reclaim_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts REAL NOT NULL,
                        iso TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        target TEXT NOT NULL,
                        reclaimed_mb REAL DEFAULT 0.0,
                        detail TEXT
                    )
                    """
                )
                con.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON telemetry_samples(ts)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_reclaim_ts ON reclaim_actions(ts)")
        except Exception as exc:
            logger.debug("No se pudo inicializar DB del gobernador: %s", exc)

    def _emit_bus_event(self, topic: str, severity: str, payload: Dict[str, Any]) -> None:
        try:
            from core.sovereign_event_bus import get_event_bus
            get_event_bus().publish(
                topic=topic,
                source="sovereign_resource_governor",
                severity=severity,
                payload=payload,
                dedup_window_s=300.0,
            )
        except Exception:
            pass

    def inspect_inference_lanes(self) -> Dict[str, Any]:
        """Inspecciona Temporal Brain y ambos demonios Ollama (:11434 CPU y :11435 GPU)."""
        tb_online = _check_temporal_brain_sock()
        cpu_ps = _http_get_json(f"{OLLAMA_CPU_URL}/api/ps") or {}
        gpu_ps = _http_get_json(f"{OLLAMA_GPU_URL}/api/ps") or {}

        cpu_models = []
        for m in cpu_ps.get("models") or []:
            cpu_models.append({
                "name": m.get("name") or m.get("model") or "",
                "size_mb": round(float(m.get("size") or 0) / (1024 * 1024), 1),
                "vram_mb": round(float(m.get("size_vram") or 0) / (1024 * 1024), 1),
                "expires_at": m.get("expires_at") or "",
            })

        gpu_models = []
        for m in gpu_ps.get("models") or []:
            gpu_models.append({
                "name": m.get("name") or m.get("model") or "",
                "size_mb": round(float(m.get("size") or 0) / (1024 * 1024), 1),
                "vram_mb": round(float(m.get("size_vram") or 0) / (1024 * 1024), 1),
                "expires_at": m.get("expires_at") or "",
            })

        gpu_names = {m["name"].split(":")[0].lower() for m in gpu_models}
        gpu_full_names = {m["name"].lower() for m in gpu_models}

        duplicates: List[Dict[str, Any]] = []
        for cm in cpu_models:
            cname = cm["name"]
            clow = cname.lower()
            cbase = clow.split(":")[0]
            # 1) KAIJU duplicado en Ollama CPU mientras TemporalBrain UNIX socket está vivo
            if tb_online and ("kaiju" in clow or "tardis-neural-space" in clow):
                duplicates.append({
                    "lane": "ollama_cpu_11434",
                    "model": cname,
                    "size_mb": cm["size_mb"],
                    "reason": "duplicate_of_temporal_brain_socket",
                })
            # 2) Modelo VLM/voz duplicado en Ollama CPU mientras ya reside en GPU lane :11435
            elif (clow in gpu_full_names or cbase in gpu_names) and cm["vram_mb"] == 0:
                duplicates.append({
                    "lane": "ollama_cpu_11434",
                    "model": cname,
                    "size_mb": cm["size_mb"],
                    "reason": "duplicate_of_gpu_lane_11435",
                })

        return {
            "temporal_brain_online": tb_online,
            "ollama_cpu_11434": cpu_models,
            "ollama_gpu_11435": gpu_models,
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
            "reclaimable_ram_mb": round(sum(d["size_mb"] for d in duplicates), 1),
        }

    def collect_telemetry(self, persist: bool = True, cache_ttl: float = 0.0) -> Dict[str, Any]:
        """Recolecta telemetría Ring 0, calcula presión y opcionalmente persiste snapshot/DB."""
        now = time.time()
        if cache_ttl > 0 and self._last_snapshot and (now - self._last_snapshot_ts) < cache_ttl:
            return self._last_snapshot

        cpus = os.cpu_count() or 16
        l1, l5, l15 = _read_loadavg()
        psi_cpu = _parse_psi_file(Path("/proc/pressure/cpu"))
        psi_mem = _parse_psi_file(Path("/proc/pressure/memory"))
        psi_io = _parse_psi_file(Path("/proc/pressure/io"))
        mem = _read_meminfo_mb()
        gpu = _read_gpu_telemetry()
        lanes = self.inspect_inference_lanes()
        call_active = _is_telegram_call_active()

        ram_total = mem.get("MemTotal", 0.0)
        ram_avail = mem.get("MemAvailable", 0.0)
        ram_used = max(0.0, round(ram_total - ram_avail, 1))
        ram_pct = round((ram_used / max(1.0, ram_total)) * 100.0, 1) if ram_total else 0.0
        swap_total = mem.get("SwapTotal", 0.0)
        swap_free = mem.get("SwapFree", 0.0)
        swap_used = max(0.0, round(swap_total - swap_free, 1))
        mlocked_mb = mem.get("Mlocked", 0.0)

        cpu_psi_10 = float((psi_cpu.get("some") or {}).get("avg10", 0.0))
        cpu_psi_60 = float((psi_cpu.get("some") or {}).get("avg60", 0.0))
        mem_psi_10 = float((psi_mem.get("some") or {}).get("avg10", 0.0))
        io_psi_10 = float((psi_io.get("some") or {}).get("avg10", 0.0))

        # Calcular puntaje de presión compuesto (0 = relajado, 100 = saturación extrema)
        load_ratio = min(1.5, l1 / max(1.0, float(cpus)))
        score = 0.0
        score += min(35.0, (cpu_psi_10 / 80.0) * 35.0)
        score += min(25.0, (load_ratio / 1.5) * 25.0)
        score += min(25.0, max(0.0, (ram_pct - 55.0) / 40.0) * 25.0)
        score += min(10.0, (min(swap_used, 16384.0) / 16384.0) * 10.0)
        score += min(5.0, (mem_psi_10 / 20.0) * 5.0)
        if gpu.get("available") and gpu.get("temp_c", 0) >= 85:
            score += 10.0
        score = round(min(100.0, score), 1)

        if score >= 75.0 or ram_avail < 1200.0 or (gpu.get("available") and gpu.get("temp_c", 0) >= 88):
            level = "CRITICAL"
        elif score >= 52.0 or ram_avail < 2500.0 or cpu_psi_10 >= 50.0:
            level = "CONSTRAINED"
        elif score >= 30.0 or cpu_psi_10 >= 25.0 or ram_pct >= 78.0:
            level = "ELEVATED"
        else:
            level = "NOMINAL"

        snapshot: Dict[str, Any] = {
            "ok": True,
            "timestamp": now,
            "iso": _now_iso(),
            "pressure_level": level,
            "pressure_score": score,
            "telegram_call_active": call_active,
            "cpu": {
                "cores": cpus,
                "loadavg_1m": l1,
                "loadavg_5m": l5,
                "loadavg_15m": l15,
                "load_per_core": round(l1 / max(1, cpus), 2),
                "psi_some_avg10": cpu_psi_10,
                "psi_some_avg60": cpu_psi_60,
            },
            "memory": {
                "ram_total_mb": ram_total,
                "ram_used_mb": ram_used,
                "ram_avail_mb": ram_avail,
                "ram_used_pct": ram_pct,
                "swap_total_mb": swap_total,
                "swap_used_mb": swap_used,
                "mlocked_mb": mlocked_mb,
                "psi_some_avg10": mem_psi_10,
            },
            "io": {
                "psi_some_avg10": io_psi_10,
            },
            "gpu": gpu,
            "inference_lanes": lanes,
            "recommendations": self._build_recommendations(level, cpu_psi_10, ram_avail, swap_used, lanes, gpu),
        }

        self._last_snapshot = snapshot
        self._last_snapshot_ts = now

        if persist:
            _atomic_write_json(STATE_FILE, snapshot)
            self._persist_sample(snapshot)
            if level in ("CONSTRAINED", "CRITICAL") or lanes["duplicate_count"] > 0:
                self._emit_bus_event(
                    topic="resource.pressure_alert",
                    severity="HIGH" if level == "CRITICAL" else "WARN",
                    payload={
                        "pressure_level": level,
                        "pressure_score": score,
                        "cpu_psi_avg10": cpu_psi_10,
                        "ram_avail_mb": ram_avail,
                        "swap_used_mb": swap_used,
                        "duplicate_models": lanes["duplicate_count"],
                        "reclaimable_ram_mb": lanes["reclaimable_ram_mb"],
                    },
                )

        return snapshot

    @staticmethod
    def _build_recommendations(
        level: str,
        cpu_psi_10: float,
        ram_avail_mb: float,
        swap_used_mb: float,
        lanes: Dict[str, Any],
        gpu: Dict[str, Any],
    ) -> List[str]:
        recs: List[str] = []
        if lanes.get("duplicate_count", 0) > 0:
            recs.append(
                f"Evict {lanes['duplicate_count']} modelos duplicados en Ollama CPU :11434 "
                f"(recupera ~{lanes['reclaimable_ram_mb']} MB RAM)."
            )
        if cpu_psi_10 >= 45.0:
            recs.append(
                f"Contención de CPU PSI elevada ({cpu_psi_10}%): diferir demonios background no interactivos."
            )
        if ram_avail_mb < 3000.0:
            recs.append(f"RAM disponible baja ({ram_avail_mb} MB): restringir concurrencia de inferencia.")
        if swap_used_mb > 6144.0:
            recs.append(f"Swap elevado ({round(swap_used_mb / 1024.0, 1)} GB): auditar procesos con mlock/leaks.")
        if gpu.get("available") and gpu.get("vram_free_mb", 4096) < 350:
            recs.append(f"VRAM RTX 3050 ajustada ({gpu['vram_free_mb']} MB libres): mantener VLM en :11435.")
        if not recs and level == "NOMINAL":
            recs.append("Silicio en estado NOMINAL: admisión abierta para todos los ciclos de evolución.")
        return recs

    def _persist_sample(self, snap: Dict[str, Any]) -> None:
        try:
            with sqlite3.connect(DB_FILE, timeout=10.0) as con:
                con.execute(
                    """
                    INSERT INTO telemetry_samples (
                        ts, iso, pressure_level, pressure_score, load1,
                        cpu_psi_avg10, mem_psi_avg10, io_psi_avg10,
                        ram_used_pct, ram_avail_mb, swap_used_mb, mlocked_mb,
                        vram_used_mb, gpu_temp_c, duplicate_models
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        snap["timestamp"],
                        snap["iso"],
                        snap["pressure_level"],
                        snap["pressure_score"],
                        snap["cpu"]["loadavg_1m"],
                        snap["cpu"]["psi_some_avg10"],
                        snap["memory"]["psi_some_avg10"],
                        snap["io"]["psi_some_avg10"],
                        snap["memory"]["ram_used_pct"],
                        snap["memory"]["ram_avail_mb"],
                        snap["memory"]["swap_used_mb"],
                        snap["memory"]["mlocked_mb"],
                        snap["gpu"].get("vram_used_mb", 0.0),
                        snap["gpu"].get("temp_c", 0.0),
                        snap["inference_lanes"]["duplicate_count"],
                    ),
                )
                # Retención de 7 días
                cutoff = snap["timestamp"] - (7 * 86400)
                con.execute("DELETE FROM telemetry_samples WHERE ts < ?", (cutoff,))
        except Exception as exc:
            logger.debug("Error guardando muestra del gobernador: %s", exc)

    def _record_reclaim(self, action_type: str, target: str, reclaimed_mb: float, detail: str) -> None:
        try:
            with sqlite3.connect(DB_FILE, timeout=10.0) as con:
                con.execute(
                    "INSERT INTO reclaim_actions (ts, iso, action_type, target, reclaimed_mb, detail) VALUES (?,?,?,?,?,?)",
                    (time.time(), _now_iso(), action_type, target, round(reclaimed_mb, 2), detail[:400]),
                )
        except Exception:
            pass

    # =========================================================================
    # CONTROL DE ADMISIÓN (BACKPRESSURE ARBITER)
    # =========================================================================
    def can_admit(
        self,
        task_type: str = "heavy_background",
        priority: str = "normal",
        cache_ttl: float = 10.0,
    ) -> Dict[str, Any]:
        """
        Determina si una tarea puede ejecutarse ahora según presión de silicio y llamadas activas.
        task_type: interactive | telegram_call | coevolution_agy | heavy_background | maintenance
        """
        ttype = (task_type or "heavy_background").lower().strip()
        prio = (priority or "normal").lower().strip()

        if ttype in ("interactive", "telegram_call", "emergency") or prio == "critical":
            return {"admitted": True, "reason": "always_admitted_priority", "task_type": ttype}

        snap = self.collect_telemetry(persist=False, cache_ttl=cache_ttl)
        level = snap["pressure_level"]
        cpu_psi = snap["cpu"]["psi_some_avg10"]
        ram_avail = snap["memory"]["ram_avail_mb"]
        call_active = snap["telegram_call_active"]

        if call_active and ttype in ("heavy_background", "coevolution_agy"):
            return {
                "admitted": False,
                "reason": "telegram_call_priority_active",
                "pressure_level": level,
                "pressure_score": snap["pressure_score"],
                "retry_after_s": 60,
            }

        if ttype == "coevolution_agy":
            # AGY corre principalmente en nube + comandos locales ligeros: permitir hasta CONSTRAINED
            if level == "CRITICAL" or ram_avail < 1400.0:
                return {
                    "admitted": False,
                    "reason": f"system_critical_pressure (ram_avail={ram_avail}MB, score={snap['pressure_score']})",
                    "pressure_level": level,
                    "pressure_score": snap["pressure_score"],
                    "retry_after_s": 180,
                }
            return {
                "admitted": True,
                "reason": f"admitted_for_coevolution ({level})",
                "pressure_level": level,
                "pressure_score": snap["pressure_score"],
            }

        if ttype == "maintenance":
            admitted = level != "CRITICAL"
            return {
                "admitted": admitted,
                "reason": "admitted" if admitted else "deferred_critical_pressure",
                "pressure_level": level,
                "pressure_score": snap["pressure_score"],
                "retry_after_s": 0 if admitted else 120,
            }

        # heavy_background (idle_evolution, omniscient, browser_crawl, subsystem_agents, batch_vlm)
        if level in ("CONSTRAINED", "CRITICAL") or cpu_psi >= 55.0 or ram_avail < 2200.0:
            if prio == "high" and level == "CONSTRAINED" and ram_avail >= 2000.0:
                return {
                    "admitted": True,
                    "reason": "high_priority_override_constrained",
                    "pressure_level": level,
                    "pressure_score": snap["pressure_score"],
                }
            return {
                "admitted": False,
                "reason": f"backpressure_throttle (level={level}, cpu_psi10={cpu_psi}%, ram_avail={ram_avail}MB)",
                "pressure_level": level,
                "pressure_score": snap["pressure_score"],
                "retry_after_s": 120 if level == "CONSTRAINED" else 300,
            }

        return {
            "admitted": True,
            "reason": f"nominal_admission ({level})",
            "pressure_level": level,
            "pressure_score": snap["pressure_score"],
        }

    # =========================================================================
    # AUTO-RECLAMACIÓN SOBERANA (DUPLICATE MODELS, STALE BAKS, ZOMBIE SHM)
    # =========================================================================
    def evict_duplicate_ollama_models(self, dry_run: bool = False) -> Dict[str, Any]:
        """Descarga modelos LLM/VLM duplicados en Ollama CPU (:11434) mediante keep_alive=0."""
        lanes = self.inspect_inference_lanes()
        evicted: List[Dict[str, Any]] = []
        errors: List[str] = []
        total_mb = 0.0

        for dup in lanes["duplicates"]:
            model_name = dup["model"]
            if dry_run:
                evicted.append({**dup, "dry_run": True})
                total_mb += float(dup["size_mb"])
                continue
            try:
                payload = json.dumps({"model": model_name, "keep_alive": 0, "prompt": ""}).encode("utf-8")
                req = urllib.request.Request(
                    f"{OLLAMA_CPU_URL}/api/generate",
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "TARDIS-ResourceGovernor/1.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    _ = resp.read()
                evicted.append({**dup, "evicted": True})
                total_mb += float(dup["size_mb"])
                self._record_reclaim("evict_duplicate_model", model_name, float(dup["size_mb"]), dup["reason"])
                logger.info("Evicted duplicate CPU Ollama model '%s' (~%.1f MB) [%s]", model_name, dup["size_mb"], dup["reason"])
            except Exception as exc:
                errors.append(f"{model_name}: {exc}")

        return {
            "ok": len(errors) == 0,
            "evicted": evicted,
            "evicted_count": len(evicted),
            "reclaimed_mb_est": round(total_mb, 1),
            "errors": errors,
        }

    def prune_redundant_bak_files(self, keep_latest_per_file: int = 1, dry_run: bool = False) -> Dict[str, Any]:
        """
        Archiva el respaldo más reciente de cada archivo `.bak.*` disperso en el workspace
        hacia `_selfmod_backups/archived_baks/` y purga copias redundantes.
        """
        groups: Dict[str, List[Path]] = {}
        pat = re.compile(r"^(?P<orig>.+?)\.bak(?:\.[0-9A-Za-z_-]+)?$")

        for root_dir in (PROJECT_ROOT, PROJECT_ROOT / "core", PROJECT_ROOT / "server"):
            if not root_dir.is_dir():
                continue
            for p in root_dir.iterdir():
                if not p.is_file():
                    continue
                m = pat.match(p.name)
                if m:
                    rel_key = str(p.parent.relative_to(PROJECT_ROOT) / m.group("orig"))
                    groups.setdefault(rel_key, []).append(p)

        archived = 0
        deleted = 0
        reclaimed_bytes = 0

        if not dry_run:
            ARCHIVE_BAK_DIR.mkdir(parents=True, exist_ok=True)

        for rel_key, paths in groups.items():
            ordered = sorted(paths, key=lambda x: x.stat().st_mtime, reverse=True)
            keep_set = ordered[: max(0, keep_latest_per_file)]
            drop_set = ordered[max(0, keep_latest_per_file) :]

            for kp in keep_set:
                size = kp.stat().st_size
                safe_name = rel_key.replace("/", "__") + "__" + kp.name
                dst = ARCHIVE_BAK_DIR / safe_name
                if not dry_run:
                    try:
                        shutil.move(str(kp), str(dst))
                        archived += 1
                    except Exception:
                        pass
                else:
                    archived += 1

            for dp in drop_set:
                try:
                    size = dp.stat().st_size
                    if not dry_run:
                        dp.unlink(missing_ok=True)
                    deleted += 1
                    reclaimed_bytes += size
                except Exception:
                    pass

        reclaimed_mb = round(reclaimed_bytes / (1024 * 1024), 2)
        if not dry_run and (archived or deleted):
            self._record_reclaim(
                "prune_bak_files",
                f"{len(groups)}_source_files",
                reclaimed_mb,
                f"archived={archived}, deleted={deleted}",
            )

        return {
            "ok": True,
            "dry_run": dry_run,
            "unique_files": len(groups),
            "archived_to_selfmod_backups": archived,
            "deleted_duplicates": deleted,
            "reclaimed_mb": reclaimed_mb,
            "archive_dir": str(ARCHIVE_BAK_DIR),
        }

    def cleanup_orphan_browser_shm(self, max_age_hours: float = 12.0, dry_run: bool = False) -> Dict[str, Any]:
        """Limpia perfiles Chrome huérfanos en /dev/shm/tardis_browser_* sin proceso Chrome vivo."""
        shm = Path("/dev/shm")
        if not shm.is_dir():
            return {"ok": True, "removed": 0, "reclaimed_mb": 0.0}

        active_cmdline = ""
        try:
            proc = subprocess.run(
                ["ps", "-eo", "args"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            active_cmdline = proc.stdout or ""
        except Exception:
            pass

        now = time.time()
        removed = 0
        reclaimed_bytes = 0
        for d in shm.glob("tardis_browser_*"):
            if not d.is_dir():
                continue
            if str(d) in active_cmdline:
                continue
            try:
                age_h = (now - d.stat().st_mtime) / 3600.0
                if age_h < max_age_hours:
                    continue
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)
                removed += 1
                reclaimed_bytes += size
            except Exception:
                pass

        reclaimed_mb = round(reclaimed_bytes / (1024 * 1024), 2)
        if not dry_run and removed:
            self._record_reclaim("cleanup_browser_shm", "/dev/shm/tardis_browser_*", reclaimed_mb, f"removed={removed}")
        return {"ok": True, "dry_run": dry_run, "removed": removed, "reclaimed_mb": reclaimed_mb}

    def reclaim(self, include_baks: bool = True, dry_run: bool = False) -> Dict[str, Any]:
        """Ejecuta una ronda completa de reclamación soberana de recursos."""
        t0 = time.time()
        evict_res = self.evict_duplicate_ollama_models(dry_run=dry_run)
        shm_res = self.cleanup_orphan_browser_shm(dry_run=dry_run)
        bak_res = self.prune_redundant_bak_files(dry_run=dry_run) if include_baks else {"ok": True, "skipped": True}
        post_snap = self.collect_telemetry(persist=not dry_run)

        total_reclaimed = round(
            float(evict_res.get("reclaimed_mb_est", 0.0))
            + float(shm_res.get("reclaimed_mb", 0.0))
            + float(bak_res.get("reclaimed_mb", 0.0)),
            2,
        )
        summary = {
            "ok": True,
            "dry_run": dry_run,
            "elapsed_s": round(time.time() - t0, 2),
            "total_reclaimed_mb_est": total_reclaimed,
            "ollama_duplicates": evict_res,
            "browser_shm": shm_res,
            "bak_pruning": bak_res,
            "post_pressure_level": post_snap["pressure_level"],
            "post_pressure_score": post_snap["pressure_score"],
            "post_ram_avail_mb": post_snap["memory"]["ram_avail_mb"],
            "iso": _now_iso(),
        }
        if not dry_run and total_reclaimed > 0:
            self._emit_bus_event(
                topic="resource.reclaimed",
                severity="INFO",
                payload={
                    "reclaimed_mb": total_reclaimed,
                    "evicted_models": evict_res.get("evicted_count", 0),
                    "deleted_baks": bak_res.get("deleted_duplicates", 0),
                    "post_ram_avail_mb": post_snap["memory"]["ram_avail_mb"],
                },
            )
        return summary

    def get_history(self, limit: int = 50) -> Dict[str, Any]:
        samples: List[Dict[str, Any]] = []
        reclaims: List[Dict[str, Any]] = []
        try:
            with sqlite3.connect(DB_FILE, timeout=10.0) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT * FROM telemetry_samples ORDER BY ts DESC LIMIT ?",
                    (max(1, min(500, int(limit))),),
                ).fetchall()
                samples = [dict(r) for r in rows]
                r_rows = con.execute(
                    "SELECT * FROM reclaim_actions ORDER BY ts DESC LIMIT 30"
                ).fetchall()
                reclaims = [dict(r) for r in r_rows]
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "samples": samples, "reclaim_actions": reclaims}

    def get_status(self) -> Dict[str, Any]:
        return self.collect_telemetry(persist=True, cache_ttl=5.0)

    def run_daemon(self, interval: float = 30.0, auto_reclaim: bool = True) -> int:
        def _sig(signum, _frame):
            logger.info("Señal %s recibida; deteniendo Sovereign Resource Governor...", signum)
            self._stop_event.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        logger.info("Sovereign Resource Governor activo (PID=%d, interval=%.1fs, auto_reclaim=%s)", os.getpid(), interval, auto_reclaim)
        cycle = 0
        while not self._stop_event.is_set():
            cycle += 1
            try:
                snap = self.collect_telemetry(persist=True)
                if auto_reclaim:
                    if snap["inference_lanes"]["duplicate_count"] > 0:
                        self.evict_duplicate_ollama_models(dry_run=False)
                    if cycle % 120 == 1:  # cada ~1 hora con interval=30s
                        self.cleanup_orphan_browser_shm(dry_run=False)
                        self.prune_redundant_bak_files(keep_latest_per_file=2, dry_run=False)
            except Exception as exc:
                logger.warning("Error en ciclo del gobernador: %s", exc)
            self._stop_event.wait(max(5.0, float(interval)))
        return 0


def get_resource_governor() -> SovereignResourceGovernor:
    return SovereignResourceGovernor.get_instance()


def can_admit(task_type: str = "heavy_background", priority: str = "normal") -> Dict[str, Any]:
    return get_resource_governor().can_admit(task_type=task_type, priority=priority)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-governor", description="TARDIS Ring 0 Resource Governor & Inference Arbiter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Telemetría Ring 0, carriles de inferencia y nivel de presión")

    p_admit = sub.add_parser("admit", help="Evaluar admisión de una tarea")
    p_admit.add_argument("--task", default="heavy_background")
    p_admit.add_argument("--priority", default="normal")

    p_rec = sub.add_parser("reclaim", help="Ejecutar reclamación de modelos duplicados, shm y .bak")
    p_rec.add_argument("--dry-run", action="store_true")
    p_rec.add_argument("--no-baks", action="store_true")

    p_hist = sub.add_parser("history", help="Mostrar historial de presión y reclamaciones")
    p_hist.add_argument("--limit", type=int, default=20)

    p_dae = sub.add_parser("daemon", help="Ejecutar demonio 24/7")
    p_dae.add_argument("--interval", type=float, default=30.0)
    p_dae.add_argument("--no-reclaim", action="store_true")

    args = ap.parse_args()
    gov = get_resource_governor()

    if args.cmd == "status":
        print(json.dumps(gov.get_status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "admit":
        print(json.dumps(gov.can_admit(task_type=args.task, priority=args.priority), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "reclaim":
        print(json.dumps(gov.reclaim(include_baks=not args.no_baks, dry_run=args.dry_run), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "history":
        print(json.dumps(gov.get_history(limit=args.limit), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "daemon":
        return gov.run_daemon(interval=args.interval, auto_reclaim=not args.no_reclaim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
