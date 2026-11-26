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


# Subpaquete modular Ring 0 (`core.governor`, COEV-20261123-93393A) — fachada 100% retrocompatible.
from core.governor.config import *
from core.governor.config import _atomic_write_json, _facade_hook, _now_iso
from core.governor.telemetry_probes import (
    _parse_psi_file,
    _parse_cpulist_count,
    _read_cpu_thermal,
    _read_cpu_power_profile,
    _read_meminfo_mb,
    _read_loadavg,
    _read_gpu,
    _read_amd_igpu,
    _probe_temporal_brain_busy,
    _read_display_session_state,
    _extract_cli_int_flag,
    _count_runnable_threads,
    _inspect_cgroup_units,
    _parse_proc_kb,
    _read_proc_mem_status,
    _read_proc_uptime_s,
    _read_cgroup_bytes_mb,
    _inspect_service_memory_bloat,
    _is_service_idle_for_recycle,
    _query_ollama_ps,
    _find_ollama_port_clients,
    _is_call_active,
)
from core.governor.ring0_actuators import (
    _power_profile_control_enabled,
    _get_power_profile,
    _set_power_profile,
    _resolve_throttle_target_level,
    _is_thermal_or_heavy_psi,
    _needs_power_profile_step_down,
    _is_pure_transient_cpu_thermal_spike,
    _is_in_safe_recovery_band,
    _gpu_eco_control_enabled,
    _resolve_gpu_eco_mode,
    _apply_nvidia_clock_cap,
    _hyprctl_get_bool,
    _hyprctl_set_keyword,
    _swap_recycle_control_enabled,
    _restart_systemd_user_unit,
    _systemd_control_enabled,
    _systemd_quota_usec_to_pct,
    _query_systemd_unit_props,
    _apply_systemd_unit_props,
)
from core.governor.cli import main

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

    def __init__(
        self,
        db_path: Path = GOVERNOR_DB,
        throttle_state_file: Optional[Path] = None,
        gpu_eco_state_file: Optional[Path] = None,
        swap_recycle_state_file: Optional[Path] = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if throttle_state_file is not None:
            self.throttle_state_file = Path(throttle_state_file)
        elif self.db_path.resolve() == GOVERNOR_DB.resolve():
            self.throttle_state_file = THROTTLE_STATE_FILE
        else:
            self.throttle_state_file = self.db_path.parent / "tardis_governor_throttle.json"
        if gpu_eco_state_file is not None:
            self.gpu_eco_state_file = Path(gpu_eco_state_file)
        elif self.db_path.resolve() == GOVERNOR_DB.resolve():
            self.gpu_eco_state_file = GPU_ECO_STATE_FILE
        else:
            self.gpu_eco_state_file = self.db_path.parent / "tardis_governor_gpu_eco.json"
        if swap_recycle_state_file is not None:
            self.swap_recycle_state_file = Path(swap_recycle_state_file)
        elif self.db_path.resolve() == GOVERNOR_DB.resolve():
            self.swap_recycle_state_file = SWAP_RECYCLE_STATE_FILE
        else:
            self.swap_recycle_state_file = self.db_path.parent / "tardis_governor_swap_recycle.json"
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
        inference_memory, memory_bloat_units = _inspect_service_memory_bloat()

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

        if memory_bloat_units:
            top_bl = memory_bloat_units[0]
            reasons.append(
                f"Swap-bloat en {top_bl['unit']} (RSS={top_bl['rss_mb']:.0f} MB, Swap={top_bl['swap_mb']:.0f} MB, Total={top_bl['total_mb']:.0f} MB)"
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
            "igpu": _read_amd_igpu(),
            "inference_lanes": {
                "temporal_brain_sock": tb_active,
                "embed_brain_sock": eb_active,
                "ollama_11434": ollama_11434,
                "ollama_11435_gpu_voice": ollama_11435,
                "duplicate_models": duplicate_models,
            },
            "cgroup_pressure": cgroup_pressure[:8],
            "oversubscribed_units": oversubscribed_units,
            "inference_memory": inference_memory,
            "memory_bloat_units": memory_bloat_units,
            "throttling": self.get_throttle_status(),
            "gpu_eco": self.get_gpu_eco_status(),
            "swap_recycle": self.get_swap_recycle_status(),
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
            # - Presión operativa/térmica moderada: performance -> balanced (evita el círculo
            #   vicioso de 487 MHz que satura PSI CPU y paraliza la voz local).
            # - Emergencia térmica real (CPU >=90°C o GPU >=87°C, o RED térmico): -> power-saver.
            power_profile_action = "unchanged"
            if thermal_or_heavy_psi and _power_profile_control_enabled():
                cur_pp = _get_power_profile()
                pp_rank = {"power-saver": 0, "balanced": 1, "performance": 2}
                severe_thermal = (
                    (target_level == "RED" and (cpu_temp_c >= 88.0 or gpu_temp_c >= 86.0))
                    or cpu_temp_c >= 90.0
                    or gpu_temp_c >= 87.0
                )
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
                elif cur_pp == "power-saver" and desired_pp == "balanced" and cpu_temp_c < 87.0 and gpu_temp_c < 85.0:
                    # Escapar automáticamente del estrangulamiento a 487 MHz cuando la térmica está en rango seguro
                    if dry_run:
                        power_profile_action = "would_step_back_to_balanced"
                    elif _set_power_profile("balanced"):
                        power_profile_applied = "balanced"
                        power_profile_action = "switched_to_balanced"
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

    def _load_gpu_eco_state(self) -> Dict[str, Any]:
        default_state: Dict[str, Any] = {
            "active": False,
            "mode": "normal",
            "hypr_baselines": {},
            "hypr_eco_active": False,
            "last_action": "unchanged",
            "updated_iso": "",
        }
        try:
            if self.gpu_eco_state_file.is_file():
                raw = json.loads(self.gpu_eco_state_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    default_state.update(raw)
        except Exception:
            pass
        return default_state

    def _save_gpu_eco_state(self, state: Dict[str, Any]) -> None:
        _atomic_write_json(self.gpu_eco_state_file, state)

    def get_gpu_eco_status(self) -> Dict[str, Any]:
        st = self._load_gpu_eco_state()
        return {
            "active": bool(st.get("active")),
            "mode": str(st.get("mode") or "normal"),
            "hypr_eco_active": bool(st.get("hypr_eco_active")),
            "last_action": str(st.get("last_action") or "unchanged"),
            "updated_iso": str(st.get("updated_iso") or ""),
        }

    def reconcile_gpu_eco(
        self,
        snap: Optional[Dict[str, Any]] = None,
        *,
        dry_run: bool = False,
        force_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gobernador Adaptativo Ring 0 de P-State GPU (RTX 3050) y Modo Eco de Escritorio (Hyprland):
          - En reposo/pantalla apagada o presión ORANGE/RED sin inferencia CUDA: fija relojes GPU/VRAM
            a P8 (420/405 MHz, <10 W) o P5 (600/810 MHz) y desactiva animaciones/blur/sombras Hyprland.
          - Ante inferencia CUDA activa en TemporalBrain, llamada Telegram o uso interactivo nominal:
            desbloquea relojes instantáneamente (-rgc/-rmc) y restaura opciones Hyprland originales.
        """
        current_snap = snap if isinstance(snap, dict) else self.collect_snapshot(persist=False)
        display_state = _read_display_session_state()

        if force_mode is not None:
            fm = str(force_mode).strip().lower()
            target_mode = fm if fm in ("normal", "eco_idle", "eco_thermal") else "normal"
        else:
            target_mode = _resolve_gpu_eco_mode(current_snap, display_state)

        if not _gpu_eco_control_enabled():
            return {
                "ok": True,
                "action": "skipped",
                "skipped_reason": "gpu_eco_control_disabled",
                "target_mode": target_mode,
                "display_state": display_state,
                "dry_run": dry_run,
                "iso": _now_iso(),
            }

        with self._lock:
            st = self._load_gpu_eco_state()
            prev_mode = str(st.get("mode") or "normal")
            hypr_baselines: Dict[str, int] = dict(st.get("hypr_baselines") or {})
            hypr_eco_active = bool(st.get("hypr_eco_active"))
            sig = str(display_state.get("hyprland_signature") or "")

            if target_mode == prev_mode and not dry_run:
                # Si está en eco_idle pero nvidia-smi reporta P0 de nuevo (drift externo), reaplicar tope
                live_ps = str((current_snap.get("gpu") or {}).get("pstate") or "").upper()
                if target_mode == "normal" or live_ps in ("P5", "P8"):
                    return {
                        "ok": True,
                        "action": "maintained",
                        "mode": target_mode,
                        "previous_mode": prev_mode,
                        "display_state": display_state,
                        "dry_run": False,
                        "iso": _now_iso(),
                    }

            if dry_run:
                return {
                    "ok": True,
                    "action": f"would_switch_to_{target_mode}",
                    "mode": target_mode,
                    "previous_mode": prev_mode,
                    "display_state": display_state,
                    "dry_run": True,
                    "iso": _now_iso(),
                }

            ok_gpu, gpu_detail = _apply_nvidia_clock_cap(target_mode)
            hypr_changes: List[str] = []
            if target_mode != "normal":
                if sig and not hypr_eco_active:
                    for opt in HYPR_ECO_OPTIONS:
                        cur_val = _hyprctl_get_bool(sig, opt)
                        if cur_val is not None and opt not in hypr_baselines:
                            hypr_baselines[opt] = cur_val
                        if cur_val != 0 and _hyprctl_set_keyword(sig, opt, 0):
                            hypr_changes.append(f"{opt}=0")
                    hypr_eco_active = True
            else:
                if sig and hypr_eco_active:
                    for opt, base_val in list(hypr_baselines.items()):
                        if _hyprctl_set_keyword(sig, opt, base_val):
                            hypr_changes.append(f"{opt}={base_val}")
                    hypr_baselines = {}
                    hypr_eco_active = False

            new_state = {
                "active": (target_mode != "normal") and ok_gpu,
                "mode": target_mode if ok_gpu else prev_mode,
                "hypr_baselines": hypr_baselines,
                "hypr_eco_active": hypr_eco_active,
                "last_action": gpu_detail,
                "updated_iso": _now_iso(),
            }
            self._save_gpu_eco_state(new_state)

        if ok_gpu and target_mode != prev_mode:
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "governor.gpu_eco",
                    "tardis_resource_governor",
                    {
                        "from_mode": prev_mode,
                        "to_mode": target_mode,
                        "gpu_detail": gpu_detail,
                        "hypr_changes": hypr_changes,
                        "connected_displays": display_state.get("connected_displays", 0),
                        "gpu_temp_c": (current_snap.get("gpu") or {}).get("temp_c", 0.0),
                        "gpu_power_w": (current_snap.get("gpu") or {}).get("power_w", 0.0),
                    },
                    severity="INFO",
                    dedup_key=f"gpu_eco|{target_mode}",
                    dedup_window_s=60.0,
                )
            except Exception:
                pass

        return {
            "ok": ok_gpu,
            "action": f"switched_to_{target_mode}" if ok_gpu else "gpu_eco_error",
            "mode": target_mode if ok_gpu else prev_mode,
            "previous_mode": prev_mode,
            "gpu_detail": gpu_detail,
            "hypr_changes": hypr_changes,
            "display_state": display_state,
            "dry_run": False,
            "iso": _now_iso(),
        }

    def _load_swap_recycle_state(self) -> Dict[str, Any]:
        try:
            if self.swap_recycle_state_file.is_file():
                data = json.loads(self.swap_recycle_state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"units": {}, "history": [], "updated_iso": ""}

    def _save_swap_recycle_state(self, state: Dict[str, Any]) -> None:
        _atomic_write_json(self.swap_recycle_state_file, state)

    def get_swap_recycle_status(self) -> Dict[str, Any]:
        st = self._load_swap_recycle_state()
        units_map = st.get("units") if isinstance(st.get("units"), dict) else {}
        return {
            "enabled": _swap_recycle_control_enabled(),
            "recycled_units": {
                u: {
                    "last_recycle_iso": info.get("last_recycle_iso", ""),
                    "recycle_count": int(info.get("recycle_count", 0)),
                    "last_swap_mb": info.get("last_swap_mb", 0.0),
                    "last_total_mb": info.get("last_total_mb", 0.0),
                }
                for u, info in units_map.items()
                if isinstance(info, dict)
            },
            "updated_iso": str(st.get("updated_iso") or ""),
        }

    def reconcile_swap_bloat(
        self,
        snap: Optional[Dict[str, Any]] = None,
        *,
        dry_run: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Detecta swap-bloat en servicios `llama-server` (`tardis-temporal-brain.service`,
        `tardis-ollama-voice.service`) y ejecuta reciclaje seguro únicamente en reposo
        verificado (0 slots activos, 0 clientes en :11435, sin llamada Telegram y respetando
        uptime mínimo + cooldown) (`COEV-20261124-5B1F5C`).
        """
        if not force and not _swap_recycle_control_enabled():
            return {"ok": True, "action": "disabled", "actions": [], "dry_run": dry_run, "iso": _now_iso()}

        current_snap = snap if snap is not None else self.collect_snapshot(persist=False)
        if bool(current_snap.get("call_priority_active", False)):
            return {
                "ok": True,
                "action": "skipped_call_priority",
                "actions": [],
                "dry_run": dry_run,
                "iso": _now_iso(),
            }

        bloated = [u for u in (current_snap.get("memory_bloat_units") or []) if u.get("recycle_eligible")]
        if not bloated:
            return {
                "ok": True,
                "action": "noop_no_swap_bloat",
                "actions": [],
                "inference_memory": current_snap.get("inference_memory") or [],
                "dry_run": dry_run,
                "iso": _now_iso(),
            }

        now = time.time()
        actions: List[Dict[str, Any]] = []
        errors: List[str] = []

        with self._lock:
            state = self._load_swap_recycle_state()
            units_state: Dict[str, Dict[str, Any]] = dict(state.get("units") or {})
            history: List[Dict[str, Any]] = list(state.get("history") or [])

            for row in bloated:
                unit = str(row.get("unit") or "")
                spec = SWAP_BLOAT_UNITS.get(unit) or {}
                min_up = float(spec.get("min_uptime_s", 600.0))
                cooldown_s = float(spec.get("cooldown_s", 1800.0))
                uptime_s = float(row.get("uptime_s", 0.0))
                prev_info = units_state.get(unit) or {}
                last_ts = float(prev_info.get("last_recycle_ts", 0.0))

                if not force and uptime_s < min_up:
                    actions.append({
                        "unit": unit,
                        "action": "deferred_min_uptime",
                        "uptime_s": uptime_s,
                        "min_uptime_s": min_up,
                        "swap_mb": row.get("swap_mb", 0.0),
                        "total_mb": row.get("total_mb", 0.0),
                    })
                    continue

                if not force and last_ts > 0 and (now - last_ts) < cooldown_s:
                    actions.append({
                        "unit": unit,
                        "action": "deferred_cooldown",
                        "cooldown_remaining_s": round(cooldown_s - (now - last_ts), 1),
                        "swap_mb": row.get("swap_mb", 0.0),
                        "total_mb": row.get("total_mb", 0.0),
                    })
                    continue

                idle_ok, idle_reason = _is_service_idle_for_recycle(unit, str(row.get("idle_kind") or spec.get("idle_kind") or ""))
                if not idle_ok:
                    actions.append({
                        "unit": unit,
                        "action": "deferred_busy",
                        "idle_reason": idle_reason,
                        "swap_mb": row.get("swap_mb", 0.0),
                        "total_mb": row.get("total_mb", 0.0),
                    })
                    continue

                if dry_run:
                    actions.append({
                        "unit": unit,
                        "action": "would_recycle",
                        "idle_reason": idle_reason,
                        "swap_mb": row.get("swap_mb", 0.0),
                        "total_mb": row.get("total_mb", 0.0),
                    })
                    continue

                ok_rst, detail_rst = _restart_systemd_user_unit(unit)
                if ok_rst:
                    rec_entry = {
                        "unit": unit,
                        "action": "recycled",
                        "idle_reason": idle_reason,
                        "rss_before_mb": row.get("rss_mb", 0.0),
                        "swap_before_mb": row.get("swap_mb", 0.0),
                        "total_before_mb": row.get("total_mb", 0.0),
                        "iso": _now_iso(),
                    }
                    actions.append(rec_entry)
                    units_state[unit] = {
                        "last_recycle_ts": now,
                        "last_recycle_iso": rec_entry["iso"],
                        "recycle_count": int(prev_info.get("recycle_count", 0)) + 1,
                        "last_swap_mb": row.get("swap_mb", 0.0),
                        "last_total_mb": row.get("total_mb", 0.0),
                    }
                    history.append(rec_entry)
                else:
                    errors.append(f"restart {unit}: {detail_rst}")
                    actions.append({
                        "unit": unit,
                        "action": "recycle_error",
                        "detail": detail_rst,
                        "swap_mb": row.get("swap_mb", 0.0),
                        "total_mb": row.get("total_mb", 0.0),
                    })

            if not dry_run and any(a["action"] == "recycled" for a in actions):
                state["units"] = units_state
                state["history"] = history[-30:]
                state["updated_iso"] = _now_iso()
                self._save_swap_recycle_state(state)

        recycled_units = [a for a in actions if a["action"] == "recycled"]
        if not dry_run and recycled_units:
            try:
                from core.tardis_event_bus import get_event_bus

                get_event_bus().publish(
                    "governor.reclaim",
                    "tardis_resource_governor",
                    {
                        "kind": "swap_bloat_recycled",
                        "recycled_units": recycled_units,
                    },
                    severity="INFO",
                    dedup_key="swap_bloat_recycled|" + ",".join(sorted(a["unit"] for a in recycled_units)),
                    dedup_window_s=300.0,
                )
            except Exception:
                pass

        top_action = (
            "recycled"
            if recycled_units
            else (actions[0]["action"] if actions else "noop_no_swap_bloat")
        )
        return {
            "ok": len(errors) == 0,
            "action": top_action,
            "actions": actions,
            "errors": errors,
            "dry_run": dry_run,
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
                elif power_profile_applied == "power-saver" and cur_cpu_c < 87.0 and cur_gpu_c < 85.0:
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

        # 2.5. Telemetría de swap-bloat (solo observación; política cero-reinicios autónomos)
        swap_recycle_result = self.reconcile_swap_bloat(snap_before, dry_run=True, force=False)
        for err in swap_recycle_result.get("errors") or []:
            errors.append(f"swap_recycle: {err}")

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
            "swap_recycle": swap_recycle_result,
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

                # Reconciliar Gobernador Adaptativo de P-State GPU y Modo Eco de Escritorio (Hyprland + RTX 3050)
                try:
                    ge = self.reconcile_gpu_eco(snap, dry_run=False)
                    if str(ge.get("action") or "").startswith("switched_to_"):
                        logger.info(
                            "GPU Eco Governor conmutado (%s -> %s, detalle=%s, hypr=%s, GPU=%.0f°C/%.1fW)",
                            ge.get("previous_mode", "normal"),
                            ge.get("mode", "normal"),
                            ge.get("gpu_detail", ""),
                            ge.get("hypr_changes") or [],
                            snap["gpu"].get("temp_c", 0.0),
                            snap["gpu"].get("power_w", 0.0),
                        )
                except Exception as exc_ge:
                    logger.debug("Aviso en reconcile_gpu_eco: %s", exc_ge)

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



if __name__ == "__main__":
    raise SystemExit(main())
