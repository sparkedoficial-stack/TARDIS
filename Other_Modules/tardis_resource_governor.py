#!/usr/bin/env python3
"""
core/tardis_resource_governor.py - Gobernador Soberano de Recursos y Árbitro de Inferencia (Ring 0)
==================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Resuelve la contención de silicio (CPU PSI, RAM, Swap, VRAM RTX 3050) entre los 37+
servicios de TARDIS, Ollama (:11434/:11435), TemporalBrain y agentes de fondo:

  1. Telemetría Ring 0 de ultra-baja sobrecarga:
     - `/proc/pressure/{cpu,memory,io}` (PSI), `/proc/meminfo`, `/proc/loadavg`
     - `nvidia-smi` (VRAM usada/libre, temperatura GPU, utilización)
     - Modelos residentes en Ollama `:11434` (CPU) y `:11435` (GPU Voice Lane)
     - Estado de `/tmp/temporal_brain.sock`, `/tmp/embed_brain.sock` y prioridad de llamadas Telegram
  2. Niveles de Presión y Control de Admisión (`GREEN` | `YELLOW` | `ORANGE` | `RED`):
     - Publica snapshot atómico en tmpfs (`/run/user/<uid>/tardis_governor.json`) para
       lecturas en <0.1 ms desde cualquier demonio sin bloquear ni generar I/O de disco.
     - Control de admisión por clase de tarea (`interactive`, `critical_repair`,
       `agy_discovery`, `heavy_learning`, `idle_evolution`, `video_render`).
  3. Árbitro Activo de Inferencia y Reclamación (`reclaim_resources`):
     - Detecta modelos LLM duplicados en CPU Ollama `:11434` cuando ya residen en
       TemporalBrain (`TARDIS-NEURAL-SPACE-KAIJU`) o en el carril GPU `:11435` (`qwen3-vl`)
       y los descarga limpiamente (`keep_alive: 0`) recuperando GBs de RAM sin cortar inferencia.
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
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GOVERNOR_DB = DATA_DIR / "resource_governor.db"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
TMPFS_SNAPSHOT = RUNTIME_DIR / "tardis_governor.json"
DISK_SNAPSHOT = DATA_DIR / "resource_governor_latest.json"
LOCK_FILE = DATA_DIR / "resource_governor.lock"
BACKUP_ARCHIVE_DIR = PROJECT_ROOT / "_selfmod_backups" / "legacy_archive"

logger = logging.getLogger("TARDIS.ResourceGovernor")


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
    return {"available": False, "temp_c": 0.0, "util_pct": 0.0, "vram_used_mb": 0.0, "vram_free_mb": 0.0, "vram_total_mb": 0.0, "vram_used_pct": 0.0}


def _query_ollama_ps(port: int) -> List[Dict[str, Any]]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            out = []
            for m in data.get("models") or []:
                out.append({
                    "name": str(m.get("name") or ""),
                    "size_mb": round(float(m.get("size") or 0) / (1024 * 1024), 1),
                    "size_vram_mb": round(float(m.get("size_vram") or 0) / (1024 * 1024), 1),
                    "expires_at": str(m.get("expires_at") or ""),
                })
            return out
    except Exception:
        return []


def _is_call_active() -> bool:
    try:
        from core.telegram_call_priority import is_call_priority_active
        return bool(is_call_priority_active())
    except Exception:
        return False


class TardisResourceGovernor:
    """Gobernador Ring 0 y Árbitro de Inferencia para todo el ecosistema TARDIS."""

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

    def __init__(self, db_path: Path = GOVERNOR_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_level: Optional[str] = None
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

    def collect_snapshot(self, persist: bool = True) -> Dict[str, Any]:
        """Recolecta telemetría Ring 0, detecta modelos duplicados y calcula presión."""
        cpu_psi = _parse_psi_file(Path("/proc/pressure/cpu"))
        mem_psi = _parse_psi_file(Path("/proc/pressure/memory"))
        io_psi = _parse_psi_file(Path("/proc/pressure/io"))
        mem = _read_meminfo_mb()
        load1, load5, load15 = _read_loadavg()
        gpu = _read_gpu()
        ncpus = os.cpu_count() or 16
        call_active = _is_call_active()

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
                duplicate_models.append({
                    "port": 11434,
                    "model": mname,
                    "size_mb": m.get("size_mb", 0.0),
                    "reason": "duplicado_con_temporal_brain" if is_kaiju_dup else "duplicado_cpu_con_gpu_lane_11435",
                })

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

        if duplicate_models:
            wasted_mb = sum(d["size_mb"] for d in duplicate_models)
            reasons.append(f"{len(duplicate_models)} modelo(s) duplicado(s) en Ollama :11434 ({wasted_mb:.0f} MB)")

        sleep_mult = {"GREEN": 1.0, "YELLOW": 1.5, "ORANGE": 2.5, "RED": 5.0}[level]
        admission = {
            "interactive": True,
            "critical_repair": True,
            "agy_discovery": (not call_active) and (level in ("GREEN", "YELLOW", "ORANGE")) and mem["available_mb"] >= 2000,
            "heavy_learning": (not call_active) and (level in ("GREEN", "YELLOW")),
            "idle_evolution": (not call_active) and (level in ("GREEN", "YELLOW")) and cpu_psi["some_avg60"] < 45.0,
            "video_render": (not call_active) and (level == "GREEN") and gpu.get("temp_c", 0.0) < 74.0,
            "recommended_sleep_multiplier": sleep_mult,
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
            "cpu": {"cores": ncpus, "load1": load1, "load5": load5, "load15": load15, "psi": cpu_psi},
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
                        (ts, iso, level, cpu_psi_60, mem_avail_mb, swap_used_mb, load1, gpu_temp_c, vram_used_mb, duplicate_models_count, reasons_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snap["ts"],
                        snap["iso"],
                        snap["level"],
                        snap["cpu"]["psi"]["some_avg60"],
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
                        "gpu_temp_c": snap["gpu"].get("temp_c", 0.0),
                        "duplicate_models": snap["inference_lanes"]["duplicate_models"],
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
            "reasons": snap.get("reasons", []),
            "iso": snap.get("iso", _now_iso()),
        }

    def reclaim_resources(self, *, dry_run: bool = False, prune_backups: bool = True, keep_backups_per_file: int = 2) -> Dict[str, Any]:
        """
        Acciones seguras y deterministas de estabilización:
          1. Descarga modelos LLM duplicados en CPU Ollama :11434 (keep_alive=0).
          2. Archiva/poda archivos `.bak*` obsoletos acumulados dentro de GODWORKS SYSTEM.
        """
        snap_before = self.collect_snapshot(persist=False)
        evicted: List[Dict[str, Any]] = []
        errors: List[str] = []

        # 1. Evict duplicate CPU models from Ollama :11434
        for dup in snap_before["inference_lanes"]["duplicate_models"]:
            model_name = dup["model"]
            if dry_run:
                evicted.append({"model": model_name, "port": 11434, "size_mb": dup["size_mb"], "action": "would_unload"})
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
                evicted.append({"model": model_name, "port": 11434, "size_mb": dup["size_mb"], "action": "unloaded"})
            except Exception as exc:
                errors.append(f"unload {model_name}: {exc}")

        # 2. Podar backups `.bak.*` redundantes en GODWORKS SYSTEM raíz y core/
        pruned_count = 0
        pruned_bytes = 0
        archived_count = 0
        if prune_backups:
            by_origin: Dict[str, List[Path]] = {}
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

                # Mover los backups conservados fuera de core/ al archivo ordenado si hay >3 archivos
                if len(files) > 3:
                    for k in keep:
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
        result = {
            "ok": True,
            "dry_run": dry_run,
            "models_evicted": evicted,
            "backups_pruned": pruned_count,
            "backups_archived": archived_count,
            "bytes_reclaimed_disk": pruned_bytes,
            "mem_available_before_mb": snap_before["memory"]["available_mb"],
            "mem_available_after_mb": snap_after["memory"]["available_mb"],
            "level_before": snap_before["level"],
            "level_after": snap_after["level"],
            "errors": errors,
            "iso": _now_iso(),
        }
        if not dry_run and (evicted or pruned_count > 0):
            try:
                from core.tardis_event_bus import get_event_bus
                get_event_bus().publish(
                    "governor.reclaim",
                    "tardis_resource_governor",
                    {
                        "models_evicted": [e["model"] for e in evicted],
                        "backups_pruned": pruned_count,
                        "mem_before_mb": snap_before["memory"]["available_mb"],
                        "mem_after_mb": snap_after["memory"]["available_mb"],
                    },
                    severity="INFO",
                    dedup_window_s=60.0,
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
        try:
            while not self._stop_event.is_set():
                snap = self.collect_snapshot(persist=True)
                now = time.time()
                has_dups = bool(snap["inference_lanes"]["duplicate_models"])
                if has_dups or (now - last_reclaim) >= reclaim_interval:
                    if has_dups or snap["level"] in ("ORANGE", "RED"):
                        res = self.reclaim_resources(dry_run=False, prune_backups=True)
                        if res["models_evicted"] or res["backups_pruned"]:
                            logger.info(
                                "Reclamación completada: modelos=%s backups=%d RAM=%.0f->%.0fMB",
                                [e["model"] for e in res["models_evicted"]],
                                res["backups_pruned"],
                                res["mem_available_before_mb"],
                                res["mem_available_after_mb"],
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


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-governor", description="TARDIS Sovereign Resource Governor & Inference Arbiter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Snapshot actual de presión y admisión")
    p_adm = sub.add_parser("admit", help="Consulta admisión para una clase de tarea")
    p_adm.add_argument("task_class", nargs="?", default="heavy_learning")
    p_rec = sub.add_parser("reclaim", help="Descarga modelos duplicados y poda backups")
    p_rec.add_argument("--dry-run", action="store_true")
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
        print(json.dumps(gov.reclaim_resources(dry_run=args.dry_run), indent=2, ensure_ascii=False))
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
