#!/usr/bin/env python3
"""
core/tardis_agy_coevolution.py - Motor de Co-Evolución Continua y Descubrimiento Autónomo (TARDIS <-> AGY)
===========================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Establece un canal bidireccional, persistente y 100% autónomo entre TARDIS y Antigravity (AGY)
para buscar continuamente nuevos sistemas alternos, diagnosticar cuellos de botella reales,
co-diseñar mejoras arquitectónicas, verificar cambios con puerta canaria y acumular
inteligencia evolutiva verificada:

  1. Radar de Descubrimiento Multi-Lente (6 Lentes Rotativos + Eventos en Vivo):
     - `runtime`      : Presión Ring 0 (PSI/RAM/Swap/VRAM/duplicados), HubHealth, systemd, ZeroErrorShield.
     - `codebase`     : Auditoría AST/arquitectura en `core/` y `modulos_ftl/` (god-files, funciones gigantes,
                        módulos críticos sin tests, llamadas sin timeout, deuda técnica).
     - `capabilities` : Matriz Viva de Capacidades que detecta qué sistemas alternos de nueva generación
                        le faltan a TARDIS y prioriza construirlos por ROI técnico.
     - `frontier`     : Recoge avances científicos/técnicos recientes (`omniscient_tech_evolution.jsonl`,
                        `autonomous_conjectures.json`, literatura arXiv/OpenAlex) y los traduce a blueprints.
     - `memory`       : Salud de bases SQLite (RAGVault, DeepMemory, OfflineChat, Continuity), backups y `/dev/shm`.
     - `security`     : Exposición de puertos `0.0.0.0`, integridad AEGIS, permisos y túneles activos.
  2. Canal Bidireccional Continuo TARDIS <-> AGY (3 Vías Sincronizadas):
     - Vía A (Autónoma Activa): Despacha briefs estructurados a AGY vía `TardisAgyController`
       (manteniendo una conversación persistente `coevolution_conversation_id` con memoria acumulada)
       con guardrails estrictos anti-recursión (`TARDIS_COEVOLUTION_NESTED`), cuota diaria y
       admisión del `ResourceGovernor`.
     - Vía B (Sesiones Interactivas AGY): Genera `~/vw-control/tardis_agy_coevolution/inbox_for_agy.md`
       consumido por `tardis-agy-hook` en cada sesión AGY y admite respuestas directas desde AGY
       (`reply-tardis` / `POST /api/coevolution/reply_from_agy`).
     - Vía C (Sistema Nervioso): Sincronizado en tiempo real con `SovereignEventBus`,
       `OmniFeedbackBridge` (`live_dialogue.jsonl`), `CanaryVerifier` y `DeepMemoryVault`.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import fcntl
import hashlib
import json
import logging
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
for _p in (str(PROJECT_ROOT), str(HOME)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
COEVOL_DB = DATA_DIR / "coevolution_vault.db"

APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / "vw-control"
CHANNEL_DIR = APPDATA_DIR / "tardis_agy_coevolution"
WS_CHANNEL_DIR = PROJECT_ROOT / ".agents" / "tardis_agy_coevolution"
for _d in (CHANNEL_DIR, WS_CHANNEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

STATE_FILE = CHANNEL_DIR / "state.json"
INBOX_MD_FILE = CHANNEL_DIR / "inbox_for_agy.md"
DIALOGUE_JSONL = CHANNEL_DIR / "dialogue.jsonl"
LOCK_FILE = CHANNEL_DIR / "coevolution.lock"

LENSES = ("runtime", "codebase", "capabilities", "frontier", "memory", "security")

# Matriz Viva de Sistemas Alternos y Capacidades de Siguiente Generación para TARDIS
SOVEREIGN_CAPABILITY_MATRIX: List[Dict[str, Any]] = [
    {
        "id": "cap_resource_governor",
        "name": "Sovereign Resource Governor & Inference Arbiter",
        "check_files": ["core/tardis_resource_governor.py"],
        "category": "alternate_system",
        "roi_score": 95,
        "problem": "Contención sin arbitraje de CPU PSI, RAM, Swap y VRAM entre 37 demonios y múltiples LLM locales.",
        "proposal": "Desplegar Gobernador Ring 0 con control de admisión por presión y evicción automática de modelos duplicados.",
    },
    {
        "id": "cap_event_bus",
        "name": "Sovereign Nervous System (Unified SQLite WAL Event Bus)",
        "check_files": ["core/tardis_event_bus.py"],
        "category": "alternate_system",
        "roi_score": 92,
        "problem": "Mensajería fragmentada en 4 archivos JSONL desconectados sin cursores durables ni correlación causal.",
        "proposal": "Centralizar eventos de salud, anomalías, hallazgos y diálogo AGY en un bus SQLite WAL pub/sub.",
    },
    {
        "id": "cap_canary_verifier",
        "name": "Sovereign Canary & Quality Gate",
        "check_files": ["core/tardis_canary_verifier.py"],
        "category": "alternate_system",
        "roi_score": 90,
        "problem": "Modificaciones autónomas sin puerta determinista de AST + seguridad + pytest dirigido + rollback atómico.",
        "proposal": "Integrar verificador canario multi-etapa con snapshots en _selfmod_backups/canary y auditoría SQLite.",
    },
    {
        "id": "cap_semantic_llm_cache",
        "name": "Semantic Inference Cache & Prompt Router (EmbedBrain + SQLite)",
        "check_files": ["core/tardis_semantic_cache.py", "core/semantic_cache.py"],
        "category": "alternate_system",
        "roi_score": 86,
        "problem": "Consultas repetitivas de agentes de fondo re-computan inferencia en TemporalBrain/Ollama quemando CPU.",
        "proposal": "Crear caché semántica local sobre /tmp/embed_brain.sock con similitud coseno >= 0.94, TTL adaptativo y telemetría de ahorro de tokens/CPU.",
    },
    {
        "id": "cap_eval_benchmark_suite",
        "name": "Continuous Autonomous Eval & Regression Benchmark Harness",
        "check_files": ["core/tardis_eval_harness.py"],
        "category": "alternate_system",
        "roi_score": 84,
        "problem": "Falta una evaluación continua automatizada de calidad de respuestas (RAG, tool-calling, latencia P50/P95, precisión AEGIS) tras cada evolución.",
        "proposal": "Construir un harness de evaluación determinista + LLM-as-judge que mida calidad pre/post evolución y alimente al motor de co-evolución.",
    },
    {
        "id": "cap_memory_compactor",
        "name": "Autonomous Memory Compactor & Knowledge Graph Deduplicator",
        "check_files": ["core/tardis_memory_compactor.py"],
        "category": "alternate_system",
        "roi_score": 82,
        "problem": "Las bóvedas SQLite (RAG, DeepMemory, OfflineChat) crecen indefinidamente con chunks duplicados y sin compactación programada.",
        "proposal": "Crear compactador nocturno (VACUUM, ANALYZE, poda de duplicados SimHash/coseno, consolidación jerárquica de episodios).",
    },
    {
        "id": "cap_adaptive_circuit_breaker",
        "name": "Adaptive Multi-Provider Circuit Breaker & Cost/Latency Router",
        "check_files": ["core/tardis_adaptive_router.py"],
        "category": "alternate_system",
        "roi_score": 81,
        "problem": "El enrutamiento entre TemporalBrain, Ollama GPU :11435, Cloud APIs y AGY carece de circuit breakers con EMA de latencia y salud por proveedor.",
        "proposal": "Diseñar un enrutador adaptativo con circuit breakers por carril, selección consciente de VRAM/PSI y degradación transparente.",
    },
    {
        "id": "cap_security_hardening_auditor",
        "name": "Continuous Zero-Trust Perimeter & Secret Hygiene Auditor",
        "check_files": ["core/tardis_perimeter_auditor.py"],
        "category": "alternate_system",
        "roi_score": 80,
        "problem": "Puertos en 0.0.0.0, túneles Cloudflare, permisos de archivos de estado y dependencias Python necesitan auditoría continua automatizada.",
        "proposal": "Implementar auditor perimetral continuo integrado con AEGIS y Zero-Error Shield que detecte exposiciones y endurezca configuraciones.",
    },
    {
        "id": "cap_voice_latency_profiler",
        "name": "End-to-End Voice Pipeline Profiler (Tapo C310 + Telegram Live Call)",
        "check_files": ["core/tardis_voice_profiler.py"],
        "category": "alternate_system",
        "roi_score": 78,
        "problem": "Los canales de voz (Tapo C310, Telegram Call) consumen mucha CPU en ffmpeg/YOLO/Whisper sin perfilado por etapa (STT/LLM/TTS).",
        "proposal": "Crear perfilador de latencia por etapa con decodificación acelerada/FPS adaptativo para bajar >50% la carga CPU de C310.",
    },
]

logger = logging.getLogger("TARDIS.AgyCoevolution")


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-coev-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _mirror_file(src_name: str, content: str) -> None:
    _atomic_write_text(CHANNEL_DIR / src_name, content)
    try:
        _atomic_write_text(WS_CHANNEL_DIR / src_name, content)
    except Exception:
        pass


def _append_jsonl_mirrored(name: str, record: Dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    for folder in (CHANNEL_DIR, WS_CHANNEL_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / name).open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass


class TardisAgyCoevolutionEngine:
    """Orquestador bidireccional continuo TARDIS <-> AGY para auto-búsqueda de sistemas y mejoras."""

    _instance: Optional["TardisAgyCoevolutionEngine"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "TardisAgyCoevolutionEngine":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=COEVOL_DB)
            return cls._instance

    def __init__(self, db_path: Path = COEVOL_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._is_isolated_instance = self.db_path.resolve() != COEVOL_DB.resolve()
        self._channel_dir = (self.db_path.parent / "coevolution_channel") if self._is_isolated_instance else CHANNEL_DIR
        self._channel_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._init_schema()
        self._state = self._load_state()

    def _write_channel_file(self, src_name: str, content: str) -> Path:
        if self._is_isolated_instance:
            target = self._channel_dir / src_name
            _atomic_write_text(target, content)
            return target
        _mirror_file(src_name, content)
        return CHANNEL_DIR / src_name

    def _append_channel_jsonl(self, name: str, record: Dict[str, Any]) -> None:
        if self._is_isolated_instance:
            line = json.dumps(record, ensure_ascii=False) + "\n"
            try:
                self._channel_dir.mkdir(parents=True, exist_ok=True)
                with (self._channel_dir / name).open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception:
                pass
            return
        _append_jsonl_mirrored(name, record)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_ts REAL NOT NULL,
                    created_iso TEXT NOT NULL,
                    updated_ts REAL NOT NULL,
                    updated_iso TEXT NOT NULL,
                    lens TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    roi_score INTEGER NOT NULL DEFAULT 50,
                    title TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    proposed_solution TEXT NOT NULL,
                    target_files_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    agy_task_id TEXT DEFAULT '',
                    agy_conversation_id TEXT DEFAULT '',
                    agy_response TEXT DEFAULT '',
                    verification_run_id TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_prop_status_roi ON proposals(status, roi_score DESC);

                CREATE TABLE IF NOT EXISTS dialogue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT NOT NULL UNIQUE,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'coevolution',
                    proposal_id TEXT DEFAULT '',
                    conversation_id TEXT DEFAULT '',
                    content TEXT NOT NULL,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_dlg_ts ON dialogue(ts DESC);

                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    lens TEXT NOT NULL,
                    findings_new INTEGER NOT NULL DEFAULT 0,
                    dispatched_to_agy INTEGER NOT NULL DEFAULT 0,
                    governor_level TEXT DEFAULT '',
                    kpi_json TEXT NOT NULL DEFAULT '{}',
                    summary TEXT DEFAULT ''
                );
                """
            )

    def _load_state(self) -> Dict[str, Any]:
        default = {
            "schema": "tardis.agy_coevolution.v1",
            "enabled": True,
            "coevolution_conversation_id": "",
            "interactive_conversation_id": "",
            "default_model": os.environ.get("TARDIS_COEVOLUTION_MODEL", "gemini-4-neon-xhigh"),
            "default_effort": os.environ.get("TARDIS_COEVOLUTION_EFFORT", "xhigh"),
            "lens_index": 0,
            "cycles_completed": 0,
            "total_agy_dispatches": 0,
            "daily_agy_dispatches": 0,
            "daily_day": time.strftime("%Y-%m-%d"),
            "max_daily_agy_dispatches": int(os.environ.get("TARDIS_COEVOLUTION_MAX_DAILY_AGY", "12")),
            "dispatch_interval_sec": float(os.environ.get("TARDIS_COEVOLUTION_DISPATCH_INTERVAL_SEC", "5400")),
            "last_dispatch_ts": 0.0,
            "last_dispatch_iso": "",
            "last_scan_ts": 0.0,
            "last_scan_iso": "",
            "daemon_pid": None,
            "daemon_heartbeat_iso": "",
            "updated_at": _now_iso(),
        }
        state_path = (self._channel_dir / "state.json") if self._is_isolated_instance else STATE_FILE
        if state_path.is_file():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    default.update(loaded)
            except Exception:
                pass
        return default

    def _save_state(self) -> None:
        self._state["updated_at"] = _now_iso()
        self._write_channel_file("state.json", json.dumps(self._state, indent=2, ensure_ascii=False) + "\n")

    def _reset_daily_budget_if_needed(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._state.get("daily_day") != today:
            self._state["daily_day"] = today
            self._state["daily_agy_dispatches"] = 0

    # =========================================================================
    # REGISTRO DE PROPUESTAS Y DIÁLOGO BIDIRECCIONAL
    # =========================================================================
    def upsert_proposal(
        self,
        *,
        lens: str,
        category: str,
        severity: str,
        roi_score: int,
        title: str,
        problem: str,
        proposed_solution: str,
        target_files: Optional[Sequence[str]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        fingerprint_seed: Optional[str] = None,
    ) -> Dict[str, Any]:
        seed = fingerprint_seed or f"{lens}|{category}|{title.strip().lower()}"
        fp = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        now = time.time()
        iso = _now_iso()
        files_list = list(target_files or [])
        ev_dict = dict(evidence or {})

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT proposal_id, status, roi_score FROM proposals WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
            if existing is not None:
                # Actualizar evidencia y ROI si sigue pendiente
                if existing["status"] in ("pending", "deferred"):
                    conn.execute(
                        """
                        UPDATE proposals
                        SET updated_ts=?, updated_iso=?, severity=?, roi_score=?, problem=?, proposed_solution=?,
                            target_files_json=?, evidence_json=?
                        WHERE fingerprint=?
                        """,
                        (
                            now,
                            iso,
                            severity.upper(),
                            int(roi_score),
                            problem[:1500],
                            proposed_solution[:2000],
                            json.dumps(files_list, ensure_ascii=False),
                            json.dumps(ev_dict, ensure_ascii=False),
                            fp,
                        ),
                    )
                return {"created": False, "proposal_id": existing["proposal_id"], "status": existing["status"]}

            pid = f"COEV-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            conn.execute(
                """
                INSERT INTO proposals (
                    proposal_id, fingerprint, created_ts, created_iso, updated_ts, updated_iso,
                    lens, category, severity, roi_score, title, problem, proposed_solution,
                    target_files_json, evidence_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    pid,
                    fp,
                    now,
                    iso,
                    now,
                    iso,
                    lens,
                    category,
                    severity.upper(),
                    int(roi_score),
                    title[:180],
                    problem[:1500],
                    proposed_solution[:2000],
                    json.dumps(files_list, ensure_ascii=False),
                    json.dumps(ev_dict, ensure_ascii=False),
                ),
            )

        try:
            from core.tardis_event_bus import get_event_bus
            get_event_bus().publish(
                "discovery.system",
                "tardis_agy_coevolution",
                {"proposal_id": pid, "lens": lens, "category": category, "roi_score": roi_score, "title": title},
                severity="HIGH" if severity.upper() in ("CRITICAL", "HIGH") else "INFO",
                dedup_key=f"coev_prop|{fp}",
                dedup_window_s=600.0,
            )
        except Exception:
            pass
        return {"created": True, "proposal_id": pid, "status": "pending"}

    def _record_dialogue(
        self,
        *,
        direction: str,
        sender: str,
        content: str,
        mode: str = "coevolution",
        proposal_id: str = "",
        conversation_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        iso = _now_iso()
        msg_id = f"coev_msg_{int(now * 1000)}_{uuid.uuid4().hex[:5]}"
        rec = {
            "msg_id": msg_id,
            "ts": now,
            "iso": iso,
            "direction": direction,  # "TARDIS->AGY" | "AGY->TARDIS" | "SYSTEM"
            "sender": sender,
            "mode": mode,
            "proposal_id": proposal_id or "",
            "conversation_id": conversation_id or "",
            "content": content.strip(),
            "meta": dict(meta or {}),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dialogue (msg_id, ts, iso, direction, sender, mode, proposal_id, conversation_id, content, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    now,
                    iso,
                    direction,
                    sender,
                    mode,
                    rec["proposal_id"],
                    rec["conversation_id"],
                    rec["content"][:16000],
                    json.dumps(rec["meta"], ensure_ascii=False),
                ),
            )
        self._append_channel_jsonl("dialogue.jsonl", rec)

        # Espejar en OmniFeedbackBridge para visibilidad en el Web Cockpit / HUD (omitir en instancias aisladas de test)
        if not self._is_isolated_instance:
            try:
                import antigravity_bridge
                antigravity_bridge.get_bridge().post_dialogue_message(
                    sender=sender,
                    text=f"[{direction} · {mode}] {content[:1200]}",
                    role="assistant" if direction == "AGY->TARDIS" else "system",
                    category="TARDIS_AGY_COEVOLUTION",
                )
            except Exception:
                pass
        return rec

    def capture_kpi_baseline(self) -> Dict[str, Any]:
        """Captura KPIs reales actuales de TARDIS para comparar mejoras pre/post."""
        kpi: Dict[str, Any] = {"iso": _now_iso()}
        try:
            from core.tardis_resource_governor import get_resource_governor
            gov = get_resource_governor().read_fast_snapshot(max_age_s=60.0)
            kpi["governor_level"] = gov.get("level")
            kpi["cpu_psi_60"] = (gov.get("cpu") or {}).get("psi", {}).get("some_avg60")
            kpi["load1"] = (gov.get("cpu") or {}).get("load1")
            kpi["mem_avail_mb"] = (gov.get("memory") or {}).get("available_mb")
            kpi["swap_used_mb"] = (gov.get("memory") or {}).get("swap_used_mb")
            kpi["gpu_temp_c"] = (gov.get("gpu") or {}).get("temp_c")
            kpi["vram_used_mb"] = (gov.get("gpu") or {}).get("vram_used_mb")
            kpi["duplicate_models"] = len((gov.get("inference_lanes") or {}).get("duplicate_models") or [])
        except Exception:
            pass
        try:
            from core.hub_health import hub_health
            hh = hub_health(force=False)
            kpi["hub_counts"] = hh.get("counts") or {}
        except Exception:
            pass
        try:
            from core.tardis_event_bus import get_event_bus
            kpi["bus_total_events"] = get_event_bus().stats().get("total_events", 0)
        except Exception:
            pass
        return kpi

    # =========================================================================
    # LOS 6 LENTES DE AUTO-BÚSQUEDA DE SISTEMAS Y MEJORAS
    # =========================================================================
    def _scan_runtime_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        # 1. Resource Governor
        try:
            from core.tardis_resource_governor import get_resource_governor
            snap = get_resource_governor().collect_snapshot(persist=True)
            dups = snap["inference_lanes"]["duplicate_models"]
            if dups:
                found.append(self.upsert_proposal(
                    lens="runtime",
                    category="performance",
                    severity="HIGH",
                    roi_score=93,
                    title=f"Eliminar carga duplicada de modelos LLM en Ollama :11434 ({len(dups)} duplicado(s))",
                    problem=f"Se detectaron modelos residentes duplicados en CPU Ollama :11434: {dups}",
                    proposed_solution="Invocar ResourceGovernor.reclaim_resources() y enrutar todos los llamadores VLM/LLM al carril GPU :11435 o socket TemporalBrain.",
                    target_files=["gia_sovereign_engine.py", "core/visual_intelligence_engine.py", "vlm_visual_guard.py"],
                    evidence={"duplicate_models": dups, "mem_avail_mb": snap["memory"]["available_mb"]},
                    fingerprint_seed="runtime|duplicate_ollama_models",
                ))
            if snap["level"] in ("ORANGE", "RED"):
                found.append(self.upsert_proposal(
                    lens="runtime",
                    category="performance",
                    severity="HIGH" if snap["level"] == "RED" else "MEDIUM",
                    roi_score=88,
                    title=f"Mitigar presión sostenida de silicio (Nivel {snap['level']})",
                    problem=f"Razones activas: {'; '.join(snap['reasons'])}",
                    proposed_solution="Auditar procesos top CPU/RAM (TemporalBrain, Tapo C310 ffmpeg/YOLO, Ollama), ajustar frecuencias/FPS/threads y aplicar throttling coordinado vía ResourceGovernor.",
                    target_files=["core/tapo_c310_sentinel.py", "core/tardis_resource_governor.py"],
                    evidence={"level": snap["level"], "reasons": snap["reasons"], "load1": snap["cpu"]["load1"]},
                    fingerprint_seed=f"runtime|pressure|{snap['level']}",
                ))
        except Exception as exc:
            logger.debug("runtime governor scan note: %s", exc)

        # 2. Hub Health degradados / offline (con guarda contra reinicio/arranque de tardis.service y auto-cierre al recuperar)
        online_subs: set = set()
        try:
            from core.hub_health import hub_health
            hh = hub_health(force=True)
            subs_map = hh.get("subsystems") or {}
            total_subs = len(subs_map)
            offline_subs = [
                sid for sid, info in subs_map.items()
                if sid != "airplay_monitor" and info.get("status") == "offline"
            ]
            online_subs = {
                sid for sid, info in subs_map.items()
                if info.get("status") == "online"
            }

            # Auto-reconciliar propuestas pendientes (reliability Y regression de subsistema) que ya volvieron a ONLINE
            if online_subs:
                now_ok = time.time()
                iso_ok = _now_iso()
                with self._connect() as conn:
                    pend_rel = conn.execute(
                        "SELECT proposal_id, category, evidence_json FROM proposals WHERE status = 'pending' AND category IN ('reliability', 'regression') AND lens = 'runtime'"
                    ).fetchall()
                    for prow in pend_rel:
                        try:
                            ev_rel = json.loads(prow["evidence_json"] or "{}")
                        except Exception:
                            ev_rel = {}
                        if ev_rel.get("topic") == "health.regression":
                            pl_prev = ev_rel.get("payload") or {}
                            sid_prev = str(pl_prev.get("subsystem") or "")
                        else:
                            sid_prev = str(ev_rel.get("id") or "")
                        if sid_prev and sid_prev in online_subs:
                            conn.execute(
                                """
                                UPDATE proposals
                                SET status = 'reviewed',
                                    agy_response = 'Auto-reconciliado: subsistema confirmado ONLINE por hub_health.',
                                    updated_ts = ?,
                                    updated_iso = ?
                                WHERE proposal_id = ?
                                """,
                                (now_ok, iso_ok, prow["proposal_id"]),
                            )

            # Si >=40% de los subsistemas aparecen offline simultáneamente, tardis.service está reiniciando:
            # evitar tormenta de 38 propuestas falsas individuales.
            is_mass_restart = total_subs >= 5 and len(offline_subs) >= max(5, int(total_subs * 0.4))
            if is_mass_restart:
                logger.info(
                    "Omitiendo creación individual de propuestas HubHealth: %d/%d subsistemas offline (posible reinicio de tardis.service).",
                    len(offline_subs),
                    total_subs,
                )
            else:
                for sid, info in subs_map.items():
                    st = info.get("status")
                    if st in ("degraded", "offline") and sid != "airplay_monitor":
                        found.append(self.upsert_proposal(
                            lens="runtime",
                            category="reliability",
                            severity="HIGH" if st == "offline" else "MEDIUM",
                            roi_score=87 if st == "offline" else 79,
                            title=f"Reparar subsistema {sid} en estado {st.upper()}",
                            problem=f"Sonda de HubHealth reporta `{sid}` = {st} (detail={info.get('detail')}, unit={info.get('unit')}, http={info.get('http')}).",
                            proposed_solution=f"Diagnosticar unidad `{info.get('unit')}` o endpoint HTTP asociado a `{sid}`, aplicar corrección y validar 200 OK en `/api/hub/health`.",
                            target_files=["core/hub_health.py"],
                            evidence=info,
                            fingerprint_seed=f"runtime|hub_health|{sid}|{st}",
                        ))
        except Exception as exc:
            logger.debug("runtime hub_health scan note: %s", exc)

        # 3. Consumir regresiones y recuperaciones simétricas del Sovereign Event Bus
        #    Drenar en lotes acotados (hasta 2000 eventos) para impedir que limit=40 parta una ola
        #    de regresión+recuperación dejando eventos health.recovered huérfanos (COEV-20261125-E31804).
        try:
            from core.tardis_event_bus import get_event_bus
            bus = get_event_bus()
            bus_topics = ("health.regression", "health.recovered", "sentinel.anomaly", "evolution.rollback", "eval.regression")
            evs: List[Dict[str, Any]] = []
            for _ in range(10):
                batch = bus.consume(
                    "tardis_agy_coevolution",
                    topics=bus_topics,
                    limit=200,
                    advance=True,
                )
                if not batch:
                    break
                evs.extend(batch)
                if len(batch) < 200:
                    break

            def _bus_recovery_key(ev_item: Dict[str, Any]) -> str:
                pl = ev_item.get("payload") or {}
                src = str(ev_item.get("source") or "")
                sub = str(pl.get("subsystem") or "").strip()
                if sub:
                    return f"{src}|sub|{sub}"
                k = str(pl.get("kind") or "").strip()
                if k in ("salud_baja", "salud_recuperada"):
                    return f"{src}|health_score"
                return f"{src}|{k or pl.get('anomaly', '')}"

            # Mapear último timestamp/id de recuperación por clave en este lote
            recovered_latest_id: Dict[str, int] = {}
            for ev in evs:
                if ev.get("topic") == "health.recovered":
                    rk = _bus_recovery_key(ev)
                    recovered_latest_id[rk] = max(recovered_latest_id.get(rk, 0), int(ev.get("id") or 0))

            # Auto-cerrar propuestas pendientes que ya recibieron health.recovered
            if recovered_latest_id:
                now_rec = time.time()
                iso_rec = _now_iso()
                with self._connect() as conn:
                    pending_regs = conn.execute(
                        "SELECT proposal_id, evidence_json FROM proposals WHERE status = 'pending' AND category = 'regression'"
                    ).fetchall()
                    for prow in pending_regs:
                        try:
                            ev_prev = json.loads(prow["evidence_json"] or "{}")
                        except Exception:
                            ev_prev = {}
                        if ev_prev.get("topic") == "health.regression":
                            rk_prev = _bus_recovery_key(ev_prev)
                            if rk_prev in recovered_latest_id and recovered_latest_id[rk_prev] > int(ev_prev.get("id") or 0):
                                conn.execute(
                                    """
                                    UPDATE proposals
                                    SET status = 'reviewed',
                                        agy_response = 'Auto-resuelto: evento simétrico health.recovered confirmado en SovereignEventBus.',
                                        updated_ts = ?,
                                        updated_iso = ?
                                    WHERE proposal_id = ?
                                    """,
                                    (now_rec, iso_rec, prow["proposal_id"]),
                                )

            for ev in evs:
                if ev.get("topic") == "health.recovered":
                    continue
                payload = ev.get("payload") or {}
                # Filtrar artefactos sintéticos de pruebas unitarias
                restored_files = payload.get("restored_files") or []
                if ev.get("topic") == "evolution.rollback" and restored_files == ["sample_mod.py"]:
                    continue
                # Si una regresión ya fue superada por un health.recovered posterior en este lote,
                # o si hub_health acaba de confirmar el subsistema ONLINE en vivo, omitir alerta obsoleta.
                if ev.get("topic") == "health.regression":
                    rk = _bus_recovery_key(ev)
                    if recovered_latest_id.get(rk, 0) > int(ev.get("id") or 0):
                        continue
                    ev_sub = str(payload.get("subsystem") or "").strip()
                    if ev_sub and ev_sub in online_subs:
                        continue

                title = f"Resolver evento crítico {ev['topic']} desde {ev['source']}"
                target_key = (
                    payload.get("subsystem")
                    or payload.get("run_id")
                    or payload.get("anomaly")
                    or payload.get("kind")
                    or ""
                )
                sev_raw = str(ev.get("severity") or "MEDIUM").upper()
                found.append(self.upsert_proposal(
                    lens="runtime",
                    category="regression",
                    severity="HIGH" if sev_raw in ("HIGH", "CRITICAL") else "MEDIUM",
                    roi_score=91 if sev_raw in ("HIGH", "CRITICAL") else 82,
                    title=title,
                    problem=json.dumps(payload, ensure_ascii=False)[:1000],
                    proposed_solution="Investigar causa raíz en el subsistema afectado, corregir el fallo de forma estructural y verificar con `tardis-canary verify`.",
                    evidence=ev,
                    fingerprint_seed=f"bus|{ev['topic']}|{ev['source']}|{target_key}",
                ))
        except Exception as exc:
            logger.debug("runtime bus scan note: %s", exc)

        return found

    def _scan_codebase_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        core_dir = PROJECT_ROOT / "core"
        tests_dir = PROJECT_ROOT / "tests"
        test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
        test_names = {p.name.lower() for p in test_files}

        # Detectar también módulos de `core/` importados y ejercitados dentro de suites compartidas
        # (p. ej. tests/test_sovereign_alternate_systems.py) para evitar falsos "sin cobertura".
        tested_core_imports: set = set()
        for tf in test_files:
            try:
                t_tree = ast.parse(tf.read_text(encoding="utf-8", errors="ignore"))
                for node in ast.walk(t_tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module == "core":
                            for alias in node.names:
                                tested_core_imports.add(alias.name.lower())
                        elif node.module.startswith("core."):
                            tested_core_imports.add(node.module.split(".", 2)[1].lower())
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("core."):
                                tested_core_imports.add(alias.name.split(".", 2)[1].lower())
            except Exception:
                continue

        god_files: List[Dict[str, Any]] = []
        untested_large: List[str] = []
        syntax_errors: List[Dict[str, Any]] = []

        for py_file in sorted(core_dir.glob("*.py")):
            try:
                src = py_file.read_text(encoding="utf-8", errors="ignore")
                loc = src.count("\n") + 1
                try:
                    ast.parse(src)
                except SyntaxError as exc:
                    syntax_errors.append({"file": f"core/{py_file.name}", "line": exc.lineno, "msg": exc.msg})
                    continue
                if loc >= 2000:
                    god_files.append({"file": f"core/{py_file.name}", "loc": loc})
                stem = py_file.stem.lower()
                short = stem[7:] if stem.startswith("tardis_") else stem
                has_dedicated_file = any((stem in tn or short in tn) for tn in test_names)
                has_import_coverage = stem in tested_core_imports
                if loc >= 800 and not (has_dedicated_file or has_import_coverage):
                    untested_large.append(f"core/{py_file.name} ({loc} LOC)")
            except Exception:
                continue

        for se in syntax_errors:
            found.append(self.upsert_proposal(
                lens="codebase",
                category="bugfix",
                severity="CRITICAL",
                roi_score=98,
                title=f"Corregir SyntaxError en {se['file']}",
                problem=f"Error de compilación AST en {se['file']} línea {se['line']}: {se['msg']}",
                proposed_solution=f"Reparar sintaxis en `{se['file']}` y validar con `tardis-canary verify {se['file']}`.",
                target_files=[se["file"]],
                evidence=se,
                fingerprint_seed=f"codebase|syntax|{se['file']}",
            ))

        if god_files:
            god_files.sort(key=lambda x: -x["loc"])
            top = god_files[:5]
            found.append(self.upsert_proposal(
                lens="codebase",
                category="architecture",
                severity="MEDIUM",
                roi_score=76,
                title=f"Modularizar módulos monolíticos de alta complejidad ({top[0]['file']}: {top[0]['loc']} LOC)",
                problem=f"Existen {len(god_files)} módulos en `core/` que superan 2000 líneas: {top}",
                proposed_solution="Extraer subcomponentes cohesivos (protocolo, transporte, almacenamiento y reglas) manteniendo fachadas retrocompatibles y añadiendo tests unitarios.",
                target_files=[g["file"] for g in top[:3]],
                evidence={"god_files": top},
                fingerprint_seed="codebase|god_files_refactor",
            ))

        if untested_large:
            found.append(self.upsert_proposal(
                lens="codebase",
                category="quality",
                severity="MEDIUM",
                roi_score=78,
                title=f"Ampliar cobertura pytest en {len(untested_large)} módulos críticos de core/",
                problem=f"Módulos extensos (>800 LOC) sin suite unitaria dedicada: {', '.join(untested_large[:8])}",
                proposed_solution="Generar tests unitarios aislados (mocks de red/hardware) en `tests/` para prevenir regresiones durante la auto-evolución.",
                target_files=[u.split(" ")[0] for u in untested_large[:4]],
                evidence={"untested_large": untested_large[:12]},
                fingerprint_seed="codebase|untested_large_modules",
            ))
        return found

    def _scan_capabilities_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        for cap in SOVEREIGN_CAPABILITY_MATRIX:
            present = any((PROJECT_ROOT / rel).is_file() for rel in cap["check_files"])
            if not present:
                found.append(self.upsert_proposal(
                    lens="capabilities",
                    category=cap["category"],
                    severity="HIGH" if cap["roi_score"] >= 85 else "MEDIUM",
                    roi_score=cap["roi_score"],
                    title=f"Crear sistema alterno: {cap['name']}",
                    problem=cap["problem"],
                    proposed_solution=cap["proposal"],
                    target_files=[cap["check_files"][0]],
                    evidence={"capability_id": cap["id"], "checked_paths": cap["check_files"]},
                    fingerprint_seed=f"capability|{cap['id']}",
                ))
        return found

    def _scan_frontier_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        tech_log = DATA_DIR / "omniscient_tech_evolution.jsonl"
        if tech_log.is_file():
            try:
                lines = tech_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-10:]
                if lines:
                    latest = json.loads(lines[-1])
                    title_f = str(latest.get("frontier_title") or "Frontera Tecnológica TARDIS")
                    bp = str(latest.get("optimization_blueprint") or "")
                    ev_list = latest.get("scientific_evidence") or []
                    if bp:
                        found.append(self.upsert_proposal(
                            lens="frontier",
                            category="research_translation",
                            severity="MEDIUM",
                            roi_score=74,
                            title=f"Traducir investigación científica a código: {title_f[:110]}",
                            problem=f"El motor omnisciente generó evidencia científica ({len(ev_list)} papers) y un blueprint aún no materializado en ingeniería.",
                            proposed_solution=f"Evaluar con AGY y convertir los puntos aplicables del blueprint en mejora real con benchmark:\n{bp[:900]}",
                            evidence={"dossier_id": latest.get("id"), "scientific_evidence": ev_list[:3]},
                            fingerprint_seed=f"frontier|{title_f[:80]}",
                        ))
            except Exception:
                pass
        return found

    def _scan_memory_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        heavy_dbs: List[Dict[str, Any]] = []
        for db in list(DATA_DIR.glob("*.db")) + list((HOME / ".tardis").glob("*.db")):
            try:
                sz_mb = round(db.stat().st_size / (1024 * 1024), 1)
                if sz_mb >= 100.0:
                    heavy_dbs.append({"db": str(db), "size_mb": sz_mb})
            except Exception:
                continue

        bak_count = sum(1 for _ in PROJECT_ROOT.glob("*.bak*")) + sum(1 for _ in (PROJECT_ROOT / "core").glob("*.bak*"))
        if bak_count > 30:
            found.append(self.upsert_proposal(
                lens="memory",
                category="hygiene",
                severity="MEDIUM",
                roi_score=80,
                title=f"Limpiar acumulación de {bak_count} archivos .bak* en el repositorio",
                problem=f"Se detectaron {bak_count} respaldos `.bak*` sin rotar en `GODWORKS SYSTEM/` y `core/`.",
                proposed_solution="Ejecutar `tardis-governor reclaim` y reforzar retención acotada en `_selfmod_backups/`.",
                target_files=["core/subsystem_agents.py", "core/tardis_resource_governor.py"],
                evidence={"bak_count": bak_count},
                fingerprint_seed="memory|backup_bloat",
            ))

        if heavy_dbs:
            heavy_dbs.sort(key=lambda x: -x["size_mb"])
            found.append(self.upsert_proposal(
                lens="memory",
                category="storage",
                severity="MEDIUM",
                roi_score=77,
                title=f"Compactar y optimizar índices SQLite ({heavy_dbs[0]['size_mb']} MB)",
                problem=f"Bases SQLite extensas detectadas: {heavy_dbs[:5]}",
                proposed_solution="Implementar compactación incremental (WAL checkpoint, ANALYZE, deduplicación de chunks) sin bloquear lecturas.",
                target_files=["core/rag_vault.py", "core/deep_memory_vault.py"],
                evidence={"heavy_dbs": heavy_dbs[:5]},
                fingerprint_seed="memory|heavy_sqlite_dbs",
            ))
        return found

    def _scan_security_lens(self) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        # Detectar puertos escuchando en 0.0.0.0
        exposed: List[str] = []
        try:
            out = subprocess.check_output(["ss", "-tln"], text=True, timeout=3.0)
            for line in out.splitlines():
                if "0.0.0.0:" in line or "[::]:" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        exposed.append(parts[3])
        except Exception:
            pass

        if len(exposed) >= 4:
            found.append(self.upsert_proposal(
                lens="security",
                category="hardening",
                severity="MEDIUM",
                roi_score=75,
                title=f"Auditar {len(exposed)} sockets expuestos en todas las interfaces (0.0.0.0)",
                problem=f"Sockets vinculados a 0.0.0.0/[::]: {', '.join(sorted(set(exposed))[:8])}",
                proposed_solution="Verificar autenticación estricta (token/JWT/mTLS) en puertos 8757, 8765, 7690 y restringir puertos internos a 127.0.0.1 o LAN/Tailscale vía nftables.",
                target_files=["core/network_shield.py", "core/cyberdefense_sentinel.py"],
                evidence={"exposed_sockets": sorted(set(exposed))},
                fingerprint_seed="security|exposed_0000_sockets",
            ))
        return found

    def scan(self, lens: str = "all") -> Dict[str, Any]:
        """Ejecuta uno o todos los lentes de descubrimiento y regenera inbox_for_agy.md."""
        target_lenses = list(LENSES) if lens == "all" else [lens]
        dispatch_map = {
            "runtime": self._scan_runtime_lens,
            "codebase": self._scan_codebase_lens,
            "capabilities": self._scan_capabilities_lens,
            "frontier": self._scan_frontier_lens,
            "memory": self._scan_memory_lens,
            "security": self._scan_security_lens,
        }
        results: List[Dict[str, Any]] = []
        for ln in target_lenses:
            fn = dispatch_map.get(ln)
            if fn:
                try:
                    results.extend(fn())
                except Exception as exc:
                    logger.warning("Error en lente %s: %s", ln, exc)

        created = sum(1 for r in results if r.get("created"))
        self._state["last_scan_ts"] = time.time()
        self._state["last_scan_iso"] = _now_iso()
        self._save_state()
        self.write_agy_inbox_digest()
        return {
            "ok": True,
            "lenses": target_lenses,
            "evaluated": len(results),
            "new_proposals": created,
            "proposals": results,
            "iso": _now_iso(),
        }

    # =========================================================================
    # INBOX PARA AGY & LECTURA DE PROPUESTAS
    # =========================================================================
    def list_proposals(self, status: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(200, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM proposals {where} ORDER BY roi_score DESC, updated_ts DESC LIMIT ?",
                params,
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["target_files"] = json.loads(d.pop("target_files_json") or "[]")
            d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
            out.append(d)
        return out

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["target_files"] = json.loads(d.pop("target_files_json") or "[]")
        d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
        return d

    def get_dialogue(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dialogue ORDER BY id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            d["meta"] = json.loads(d.pop("meta_json") or "{}")
            out.append(d)
        return out

    def write_agy_inbox_digest(self) -> Path:
        """Genera un resumen Markdown limpio para que cualquier sesión AGY lea qué descubrió TARDIS."""
        pending = self.list_proposals(status="pending", limit=10)
        kpi = self.capture_kpi_baseline()
        lines = [
            "# 🤝 TARDIS → AGY :: Buzón Continuo de Co-Evolución y Sistemas Alternos",
            f"- **Actualizado:** `{_now_iso()}`",
            f"- **Conversación Persistente de Co-Evolución:** `{self._state.get('coevolution_conversation_id') or '(se creará en el próximo intercambio)'}`",
            f"- **Nivel de Presión ResourceGovernor:** `{kpi.get('governor_level', '?')}` | CPU PSI60=`{kpi.get('cpu_psi_60', '?')}%` | RAM libre=`{kpi.get('mem_avail_mb', '?')} MB` | GPU=`{kpi.get('gpu_temp_c', '?')}°C`",
            f"- **HubHealth:** `{kpi.get('hub_counts', {})}`",
            "",
            "## 🎯 Top Propuestas de Sistemas Alternos y Mejoras Pendientes",
        ]
        if not pending:
            lines.append("- Sin propuestas pendientes en este momento.")
        else:
            for p in pending:
                lines.append(
                    f"- **`{p['proposal_id']}`** [ROI={p['roi_score']} | {p['severity']} | lente=`{p['lens']}` | `{p['category']}`] **{p['title']}**"
                )
                lines.append(f"  - *Problema:* {p['problem'][:220]}")
                lines.append(f"  - *Propuesta:* {p['proposed_solution'][:260]}")
                if p["target_files"]:
                    lines.append(f"  - *Archivos:* `{', '.join(p['target_files'][:4])}`")
        lines.extend([
            "",
            "## 💬 Cómo Responder a TARDIS desde AGY",
            "```bash",
            'tardis-coevolution reply-tardis "Análisis o sistema implementado..." --proposal-id <ID> --status implemented',
            "```",
            "",
        ])
        return self._write_channel_file("inbox_for_agy.md", "\n".join(lines))

    # =========================================================================
    # COMUNICACIÓN BIDIRECCIONAL ACTIVA CON AGY
    # =========================================================================
    def build_agy_brief(self, proposal: Optional[Dict[str, Any]] = None, custom_prompt: Optional[str] = None, mode: str = "coevolution") -> str:
        kpi = self.capture_kpi_baseline()
        pending = self.list_proposals(status="pending", limit=5)
        recent_dlg = self.get_dialogue(limit=4)
        dlg_preview = "\n".join(f"  - [{m['iso']}] {m['direction']} ({m['sender']}): {m['content'][:180]}" for m in recent_dlg) or "  (primer intercambio)"

        if custom_prompt:
            core_request = custom_prompt.strip()
            pid_hint = proposal["proposal_id"] if proposal else ""
        elif proposal:
            pid_hint = proposal["proposal_id"]
            core_request = (
                f"Propuesta prioritaria seleccionada: `{proposal['proposal_id']}`\n"
                f"- Título: {proposal['title']}\n"
                f"- Categoría: {proposal['category']} | Lente: {proposal['lens']} | Severidad: {proposal['severity']} | ROI: {proposal['roi_score']}/100\n"
                f"- Problema detectado: {proposal['problem']}\n"
                f"- Solución / Sistema propuesto: {proposal['proposed_solution']}\n"
                f"- Archivos objetivo: {', '.join(proposal.get('target_files') or []) or '(por definir)'}\n"
                f"- Evidencia: {json.dumps(proposal.get('evidence') or {}, ensure_ascii=False)[:800]}"
            )
        else:
            pid_hint = pending[0]["proposal_id"] if pending else ""
            top_list = "\n".join(f"  - [{p['proposal_id']}] (ROI {p['roi_score']}) {p['title']}" for p in pending) or "  (auditoría abierta)"
            core_request = (
                "Realiza una búsqueda y diseño autónomo de mejoras y sistemas alternos de alto impacto para TARDIS.\n"
                f"Candidatos detectados por el radar de TARDIS:\n{top_list}"
            )

        return (
            f"[TARDIS <-> AGY :: CANAL SOBERANO DE CO-EVOLUCIÓN CONTINUA | modo={mode}]\n"
            f"Timestamp: {_now_iso()}\n"
            f"Telemetría actual TARDIS: governor={kpi.get('governor_level')} | cpu_psi60={kpi.get('cpu_psi_60')}% | "
            f"load1={kpi.get('load1')} | ram_avail={kpi.get('mem_avail_mb')}MB | swap={kpi.get('swap_used_mb')}MB | "
            f"gpu={kpi.get('gpu_temp_c')}C/{kpi.get('vram_used_mb')}MB | hub={kpi.get('hub_counts')}\n\n"
            f"### SOLICITUD DE TARDIS A AGY\n{core_request}\n\n"
            f"### CONTEXTO RECIENTE DEL DIÁLOGO TARDIS <-> AGY\n{dlg_preview}\n\n"
            "### CONTRATO DE RESPUESTA Y VERIFICACIÓN AUTÓNOMA\n"
            "1. Analiza la evidencia empírica y busca (en el codebase, herramientas locales o literatura/web) la mejor solución o sistema alterno.\n"
            "2. Si implementas código en `/home/m11/Escritorio/GODWORKS SYSTEM`, valida SIEMPRE con `tardis-canary verify <archivos> --snapshot` antes de concluir.\n"
            "3. Registra tu respuesta de vuelta a TARDIS ejecutando:\n"
            f'   `tardis-coevolution reply-tardis "<resumen técnico y hallazgos>" --proposal-id "{pid_hint}" --status <reviewed|implemented|deferred>`\n'
            "4. Si descubres un NUEVO sistema alterno o mejora futura, regístralo con:\n"
            '   `tardis-coevolution propose "<título>" --problem "<problema>" --solution "<propuesta>" --roi 85`\n'
            "5. Regla anti-bucle: NO invoques `tardis-coevolution ask-agy` desde dentro de esta ejecución.\n"
        )

    def communicate_with_agy(
        self,
        *,
        prompt: Optional[str] = None,
        proposal_id: Optional[str] = None,
        mode: str = "coevolution",
        sync: bool = False,
        use_stream: bool = False,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        timeout: int = 600,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Envía una comunicación estructurada desde TARDIS hacia AGY (encolada o síncrona)."""
        if os.environ.get("TARDIS_COEVOLUTION_NESTED") == "1" and not force:
            return {"ok": False, "blocked": "anti_recursion_guard", "error": "Ejecución anidada bloqueada para evitar bucles infinitos."}

        self._reset_daily_budget_if_needed()
        if not force:
            # 1. Revisar presupuesto diario
            max_daily = int(self._state.get("max_daily_agy_dispatches", 12))
            if int(self._state.get("daily_agy_dispatches", 0)) >= max_daily:
                return {"ok": False, "skipped": "daily_budget_reached", "daily_dispatches": self._state["daily_agy_dispatches"], "max_daily": max_daily}
            # 2. Revisar ResourceGovernor
            try:
                from core.tardis_resource_governor import get_resource_governor
                adm = get_resource_governor().admit("agy_discovery")
                if not adm.get("allowed", True):
                    return {"ok": False, "skipped": "resource_governor_deferred", "admission": adm}
            except Exception:
                pass

        proposal = self.get_proposal(proposal_id) if proposal_id else None
        if proposal is None and not prompt:
            pend = self.list_proposals(status="pending", limit=1)
            proposal = pend[0] if pend else None
            proposal_id = proposal["proposal_id"] if proposal else None

        brief = self.build_agy_brief(proposal=proposal, custom_prompt=prompt, mode=mode)
        target_model = model or self._state.get("default_model") or "gemini-4-neon-xhigh"
        target_effort = effort or self._state.get("default_effort") or "xhigh"
        coev_cid = str(self._state.get("coevolution_conversation_id") or "").strip() or None

        from core.tardis_agy_controller import get_tardis_agy_controller
        ctrl = get_tardis_agy_controller()

        # Marcar entorno anti-recursión para llamadas síncronas
        prev_nested = os.environ.get("TARDIS_COEVOLUTION_NESTED")
        os.environ["TARDIS_COEVOLUTION_NESTED"] = "1"
        try:
            self._record_dialogue(
                direction="TARDIS->AGY",
                sender="TARDIS-COEVOLUTION",
                content=brief,
                mode=mode,
                proposal_id=proposal_id or "",
                conversation_id=coev_cid or "",
                meta={"sync": sync, "model": target_model},
            )

            try:
                from core.tardis_event_bus import get_event_bus
                get_event_bus().publish(
                    "agy.request",
                    "tardis_agy_coevolution",
                    {"proposal_id": proposal_id or "", "mode": mode, "sync": sync, "model": target_model, "brief_preview": brief[:240]},
                    severity="INFO",
                    dedup_window_s=30.0,
                )
            except Exception:
                pass

            if sync:
                if use_stream:
                    res = ctrl.send_turn(
                        brief,
                        cwd=str(PROJECT_ROOT),
                        model=target_model,
                        effort=target_effort,
                        conversation_id=coev_cid,
                        timeout=float(timeout),
                        source="tardis_coevolution_stream",
                    )
                else:
                    res = ctrl.run_task(
                        brief,
                        cwd=str(PROJECT_ROOT),
                        model=target_model,
                        effort=target_effort,
                        conversation_id=coev_cid,
                        timeout=int(timeout),
                        source="tardis_coevolution_sync",
                        fallback_to_local=False,
                    )
                out_cid = str(res.get("conversation_id") or coev_cid or "").strip()
                if out_cid:
                    self._state["coevolution_conversation_id"] = out_cid
                reply_txt = str(res.get("response") or res.get("reply") or res.get("error") or "").strip()
                if reply_txt:
                    self.record_agy_reply(
                        reply_txt,
                        proposal_id=proposal_id,
                        status="reviewed" if res.get("ok") else "failed",
                        conversation_id=out_cid,
                        sender="Antigravity-AGY",
                        meta={"task_id": res.get("task_id"), "model": target_model, "elapsed": res.get("elapsed")},
                    )
                dispatch_id = str(res.get("task_id") or "")
                ok = bool(res.get("ok"))
            else:
                res = ctrl.enqueue_task(
                    brief,
                    source="tardis_coevolution_daemon",
                    priority="high" if (proposal and proposal.get("severity") in ("CRITICAL", "HIGH")) else "normal",
                    cwd=str(PROJECT_ROOT),
                    model=target_model,
                    effort=target_effort,
                    conversation_id=coev_cid,
                    use_stream_session=use_stream,
                    timeout=int(timeout),
                    dedup_window_s=1800.0,
                    meta={"proposal_id": proposal_id or "", "coevolution_mode": mode, "nested_guard": True},
                )
                dispatch_id = str(res.get("task_id") or "")
                ok = bool(res.get("ok"))
                out_cid = coev_cid or ""

            if ok:
                self._state["total_agy_dispatches"] = int(self._state.get("total_agy_dispatches", 0)) + 1
                self._state["daily_agy_dispatches"] = int(self._state.get("daily_agy_dispatches", 0)) + 1
                self._state["last_dispatch_ts"] = time.time()
                self._state["last_dispatch_iso"] = _now_iso()
                self._save_state()

                if proposal_id and not sync:
                    with self._connect() as conn:
                        conn.execute(
                            "UPDATE proposals SET status='dispatched', agy_task_id=?, agy_conversation_id=?, updated_ts=?, updated_iso=? WHERE proposal_id=?",
                            (dispatch_id, out_cid, time.time(), _now_iso(), proposal_id),
                        )
                self.write_agy_inbox_digest()
            return {
                "ok": ok,
                "mode": mode,
                "sync": sync,
                "proposal_id": proposal_id,
                "task_id": dispatch_id,
                "conversation_id": out_cid,
                "result": res,
            }
        finally:
            if prev_nested is None:
                os.environ.pop("TARDIS_COEVOLUTION_NESTED", None)
            else:
                os.environ["TARDIS_COEVOLUTION_NESTED"] = prev_nested

    def record_agy_reply(
        self,
        message: str,
        *,
        proposal_id: Optional[str] = None,
        status: str = "reviewed",
        conversation_id: Optional[str] = None,
        sender: str = "Antigravity-AI",
        verification_run_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Registra una respuesta directa de AGY hacia TARDIS y actualiza bóvedas y propuestas."""
        clean_msg = (message or "").strip()
        if not clean_msg:
            return {"ok": False, "error": "Mensaje de respuesta vacío."}

        cid = (conversation_id or self._state.get("coevolution_conversation_id") or "").strip()
        if cid and not self._state.get("coevolution_conversation_id"):
            self._state["coevolution_conversation_id"] = cid
            self._save_state()

        dlg = self._record_dialogue(
            direction="AGY->TARDIS",
            sender=sender,
            content=clean_msg,
            mode="reply",
            proposal_id=proposal_id or "",
            conversation_id=cid,
            meta=meta,
        )

        if proposal_id:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE proposals
                    SET status=?, agy_response=?, agy_conversation_id=COALESCE(NULLIF(?, ''), agy_conversation_id),
                        verification_run_id=COALESCE(NULLIF(?, ''), verification_run_id),
                        updated_ts=?, updated_iso=?
                    WHERE proposal_id=?
                    """,
                    (status, clean_msg[:8000], cid, verification_run_id, time.time(), _now_iso(), proposal_id),
                )

        # Ingestar en Sovereign Event Bus
        try:
            from core.tardis_event_bus import get_event_bus
            get_event_bus().publish(
                "agy.response",
                sender,
                {"proposal_id": proposal_id or "", "status": status, "conversation_id": cid, "preview": clean_msg[:300]},
                severity="INFO",
                dedup_window_s=10.0,
            )
        except Exception:
            pass

        # Ingestar en DeepMemoryVault para aprendizaje acumulativo de TARDIS (omitir en instancias aisladas de test)
        if not self._is_isolated_instance:
            try:
                from core.deep_memory_vault import get_deep_memory_vault
                get_deep_memory_vault().record_contemplation(
                    question=f"[CO-EVOLUCIÓN TARDIS <-> AGY] Propuesta {proposal_id or 'abierta'} ({status})",
                    answer=clean_msg[:4000],
                    source="tardis_agy_coevolution",
                    status="COMPLETED",
                    complexity_score=2.9,
                )
            except Exception:
                pass

        self.write_agy_inbox_digest()
        return {"ok": True, "message": dlg, "proposal_id": proposal_id, "status": status}

    def run_cycle(self, *, lens: str = "auto", allow_dispatch: bool = True, force_dispatch: bool = False) -> Dict[str, Any]:
        """Ejecuta un ciclo completo: KPIs -> Escaneo por lente -> Priorización -> Comunicación con AGY."""
        t0 = time.time()
        self._state = self._load_state()
        kpi = self.capture_kpi_baseline()

        if lens == "auto":
            idx = int(self._state.get("lens_index", 0))
            chosen_lens = LENSES[idx % len(LENSES)]
            self._state["lens_index"] = idx + 1
        else:
            chosen_lens = lens

        # Siempre revisar runtime + el lente elegido para reacción inmediata a anomalías
        scan_lenses = [chosen_lens] if chosen_lens in ("all", "runtime") else ["runtime", chosen_lens]
        new_total = 0
        for ln in scan_lenses:
            sr = self.scan(lens=ln)
            new_total += int(sr.get("new_proposals", 0))

        dispatched = False
        dispatch_res: Optional[Dict[str, Any]] = None
        if allow_dispatch:
            now = time.time()
            last_d = float(self._state.get("last_dispatch_ts", 0.0) or 0.0)
            interval = float(self._state.get("dispatch_interval_sec", 5400.0))
            pending = self.list_proposals(status="pending", limit=3)
            top = pending[0] if pending else None
            is_critical = bool(top and top.get("severity") == "CRITICAL")

            if top and (force_dispatch or is_critical or (now - last_d) >= interval):
                if int(top.get("roi_score", 0)) >= 75 or force_dispatch or is_critical:
                    dispatch_res = self.communicate_with_agy(
                        proposal_id=top["proposal_id"],
                        mode="autonomous_discovery",
                        sync=False,
                        force=force_dispatch,
                    )
                    dispatched = bool(dispatch_res.get("ok"))

        self._state["cycles_completed"] = int(self._state.get("cycles_completed", 0)) + 1
        self._save_state()

        summary = f"lens={chosen_lens} new={new_total} dispatched={dispatched} gov={kpi.get('governor_level')}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cycles (ts, iso, lens, findings_new, dispatched_to_agy, governor_level, kpi_json, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), _now_iso(), chosen_lens, new_total, 1 if dispatched else 0, str(kpi.get("governor_level") or ""), json.dumps(kpi, ensure_ascii=False), summary),
            )

        return {
            "ok": True,
            "cycle_number": self._state["cycles_completed"],
            "lens": chosen_lens,
            "new_proposals": new_total,
            "dispatched_to_agy": dispatched,
            "dispatch_result": dispatch_res,
            "kpi": kpi,
            "elapsed_s": round(time.time() - t0, 2),
            "iso": _now_iso(),
        }

    def get_status(self) -> Dict[str, Any]:
        self._state = self._load_state()
        self._reset_daily_budget_if_needed()
        with self._connect() as conn:
            by_status = {
                r["status"]: int(r["cnt"])
                for r in conn.execute("SELECT status, COUNT(*) AS cnt FROM proposals GROUP BY status").fetchall()
            }
            dlg_count = int(conn.execute("SELECT COUNT(*) FROM dialogue").fetchone()[0])
            last_cycle = conn.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()

        dpid = self._state.get("daemon_pid")
        daemon_alive = False
        if isinstance(dpid, int) and dpid > 1:
            try:
                os.kill(dpid, 0)
                daemon_alive = True
            except OSError:
                daemon_alive = False

        return {
            "ok": True,
            "schema": "tardis.agy_coevolution.v1",
            "enabled": bool(self._state.get("enabled", True)),
            "daemon": {
                "alive": daemon_alive,
                "pid": dpid if daemon_alive else None,
                "heartbeat_iso": self._state.get("daemon_heartbeat_iso"),
            },
            "coevolution_conversation_id": self._state.get("coevolution_conversation_id"),
            "default_model": self._state.get("default_model"),
            "cycles_completed": self._state.get("cycles_completed", 0),
            "agy_dispatches": {
                "total": self._state.get("total_agy_dispatches", 0),
                "today": self._state.get("daily_agy_dispatches", 0),
                "max_daily": self._state.get("max_daily_agy_dispatches", 12),
                "interval_sec": self._state.get("dispatch_interval_sec", 5400.0),
                "last_dispatch_iso": self._state.get("last_dispatch_iso"),
            },
            "proposals_by_status": by_status,
            "dialogue_messages": dlg_count,
            "top_pending": self.list_proposals(status="pending", limit=5),
            "last_cycle": dict(last_cycle) if last_cycle else None,
            "inbox_md": str(INBOX_MD_FILE),
            "db_path": str(self.db_path),
            "iso": _now_iso(),
        }

    def run_daemon(self, scan_interval: float = 1200.0, dispatch_interval: float = 5400.0) -> int:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = LOCK_FILE.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.error("Otra instancia de tardis-agy-coevolution ya está activa.")
            return 1

        def _sig(signum, _frame):
            logger.info("Señal %s recibida; deteniendo tardis-agy-coevolution...", signum)
            self._stop_event.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        self._state["dispatch_interval_sec"] = max(300.0, float(dispatch_interval))
        self._state["daemon_pid"] = os.getpid()
        self._state["daemon_heartbeat_iso"] = _now_iso()
        self._save_state()
        logger.info(
            "tardis-agy-coevolution activo 24/7 (PID=%d, scan=%.0fs, dispatch=%.0fs)",
            os.getpid(),
            scan_interval,
            dispatch_interval,
        )

        # Esperar brevemente a que tardis.service (:8757/health) esté listo tras reinicios simultáneos
        try:
            import urllib.request as _ureq
            deadline = time.time() + 25.0
            while not self._stop_event.is_set() and time.time() < deadline:
                try:
                    with _ureq.urlopen("http://127.0.0.1:8757/health", timeout=2.0) as _resp:
                        if _resp.status == 200:
                            break
                except Exception:
                    self._stop_event.wait(2.0)
        except Exception:
            pass

        try:
            while not self._stop_event.is_set():
                self._state["daemon_pid"] = os.getpid()
                self._state["daemon_heartbeat_iso"] = _now_iso()
                self._save_state()

                try:
                    res = self.run_cycle(lens="auto", allow_dispatch=True, force_dispatch=False)
                    logger.info(
                        "Ciclo Co-Evolución #%d | lente=%s | nuevas=%d | despachado_agy=%s | %.1fs",
                        res["cycle_number"],
                        res["lens"],
                        res["new_proposals"],
                        res["dispatched_to_agy"],
                        res["elapsed_s"],
                    )
                except Exception as exc:
                    logger.error("Error en ciclo de co-evolución: %s", exc)

                # Adaptar espera al nivel del ResourceGovernor
                wait_s = max(60.0, float(scan_interval))
                try:
                    from core.tardis_resource_governor import get_resource_governor
                    mult = float(get_resource_governor().admit("agy_discovery").get("recommended_sleep_multiplier", 1.0))
                    wait_s = min(3600.0, wait_s * mult)
                except Exception:
                    pass
                self._stop_event.wait(wait_s)
        finally:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                lock_fh.close()
            except Exception:
                pass
        return 0


def get_coevolution_engine(db_path: Optional[Path] = None) -> TardisAgyCoevolutionEngine:
    return TardisAgyCoevolutionEngine.get_instance(db_path=db_path)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-coevolution", description="Canal Continuo TARDIS <-> AGY de Co-Evolución y Descubrimiento de Sistemas")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Estado holístico del canal TARDIS <-> AGY")

    p_scan = sub.add_parser("scan", help="Ejecuta lentes de auto-búsqueda de sistemas y mejoras")
    p_scan.add_argument("--lens", default="all", choices=["all", *LENSES])

    p_props = sub.add_parser("proposals", help="Lista propuestas descubiertas")
    p_props.add_argument("--status", default="all", choices=["all", "pending", "dispatched", "reviewed", "implemented", "deferred", "failed"])
    p_props.add_argument("--limit", type=int, default=25)

    p_prop_add = sub.add_parser("propose", help="Registra una nueva propuesta de sistema alterno o mejora")
    p_prop_add.add_argument("title")
    p_prop_add.add_argument("--problem", required=True)
    p_prop_add.add_argument("--solution", required=True)
    p_prop_add.add_argument("--lens", default="capabilities")
    p_prop_add.add_argument("--category", default="alternate_system")
    p_prop_add.add_argument("--severity", default="MEDIUM")
    p_prop_add.add_argument("--roi", type=int, default=80)
    p_prop_add.add_argument("--files", nargs="*", default=[])

    p_dlg = sub.add_parser("dialogue", help="Historial de diálogo continuo TARDIS <-> AGY")
    p_dlg.add_argument("--limit", type=int, default=20)

    p_ask = sub.add_parser("ask-agy", help="Envía una consulta o propuesta de TARDIS a AGY")
    p_ask.add_argument("prompt", nargs="*")
    p_ask.add_argument("--proposal-id", default=None)
    p_ask.add_argument("--mode", default="coevolution")
    p_ask.add_argument("--sync", action="store_true")
    p_ask.add_argument("--stream", action="store_true")
    p_ask.add_argument("--model", default=None)
    p_ask.add_argument("--timeout", type=int, default=600)
    p_ask.add_argument("--force", action="store_true")

    p_rep = sub.add_parser("reply-tardis", help="Envía respuesta de AGY de vuelta a TARDIS")
    p_rep.add_argument("message", nargs="+")
    p_rep.add_argument("--proposal-id", default=None)
    p_rep.add_argument("--status", default="reviewed", choices=["reviewed", "implemented", "deferred", "failed"])
    p_rep.add_argument("--conversation-id", default=None)
    p_rep.add_argument("--sender", default="Antigravity-AI")
    p_rep.add_argument("--verification-run-id", default="")

    p_cyc = sub.add_parser("run-cycle", help="Ejecuta un ciclo de co-evolución")
    p_cyc.add_argument("--lens", default="auto", choices=["auto", "all", *LENSES])
    p_cyc.add_argument("--dispatch", action="store_true", help="Permitir despacho automático a AGY")
    p_cyc.add_argument("--force-dispatch", action="store_true")

    p_d = sub.add_parser("daemon", help="Demonio 24/7 de co-evolución TARDIS <-> AGY")
    p_d.add_argument("--interval", type=float, default=1200.0)
    p_d.add_argument("--dispatch-interval", type=float, default=5400.0)

    args = ap.parse_args()
    eng = get_coevolution_engine()

    if args.cmd == "status":
        print(json.dumps(eng.get_status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "scan":
        print(json.dumps(eng.scan(lens=args.lens), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "proposals":
        print(json.dumps({"ok": True, "proposals": eng.list_proposals(status=args.status, limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "propose":
        res = eng.upsert_proposal(
            lens=args.lens,
            category=args.category,
            severity=args.severity,
            roi_score=args.roi,
            title=args.title,
            problem=args.problem,
            proposed_solution=args.solution,
            target_files=args.files,
        )
        eng.write_agy_inbox_digest()
        print(json.dumps({"ok": True, **res}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "dialogue":
        print(json.dumps({"ok": True, "dialogue": eng.get_dialogue(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "ask-agy":
        prompt_str = " ".join(args.prompt).strip() or None
        res = eng.communicate_with_agy(
            prompt=prompt_str,
            proposal_id=args.proposal_id,
            mode=args.mode,
            sync=args.sync,
            use_stream=args.stream,
            model=args.model,
            timeout=args.timeout,
            force=args.force,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "reply-tardis":
        res = eng.record_agy_reply(
            " ".join(args.message),
            proposal_id=args.proposal_id,
            status=args.status,
            conversation_id=args.conversation_id,
            sender=args.sender,
            verification_run_id=args.verification_run_id,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "run-cycle":
        res = eng.run_cycle(lens=args.lens, allow_dispatch=args.dispatch or args.force_dispatch, force_dispatch=args.force_dispatch)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "daemon":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (tardis-coevolution) %(message)s")
        return eng.run_daemon(scan_interval=args.interval, dispatch_interval=args.dispatch_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
