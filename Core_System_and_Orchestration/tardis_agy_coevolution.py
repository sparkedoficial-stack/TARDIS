#!/usr/bin/env python3
"""
core/tardis_agy_coevolution.py - Motor de Co-Evolución Continua TARDIS ↔ AGY y Descubrimiento Autónomo
======================================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

MANDATO DEL ARQUITECTO:
"Investiga el sistema TARDIS de forma completa y analiza formas de mejorarlo, así como crear
sistemas alternos que consideres deberia incluir para mejorar, permitele comunicarse contigo
de forma continua, para auto buscar sistemas y mejoras."

ARQUITECTURA SOBERANA DE CO-EVOLUCIÓN BIDIRECCIONAL:
  1. Radar Autónomo de 6 Lentes Rotativos (`scan_discoveries`):
     - Lente 1 (`runtime_telemetry`): Presión de silicio Ring 0 (PSI/RAM/Swap/VRAM), modelos
       duplicados, subsistemas degradados en HubHealth, alertas del SovereignEventBus.
     - Lente 2 (`codebase_archaeology`): Auditoría AST/estática de `core/*.py` y raíz buscando
       monolitos sin tests, timeouts faltantes, excepciones silenciadas y deuda técnica.
     - Lente 3 (`capability_matrix`): Matriz viva de sistemas alternos de alto impacto que
       TARDIS aún no posee (Semantic Inference Cache, Unified DR Snapshot Engine, Voice Latency
       Profiler, RAG Index Hygiene Engine, Distributed LAN Mesh Sync, etc.).
     - Lente 4 (`external_frontier_scouting`): Conecta los dossiers científicos/técnicos de
       `tardis_omniscient_autonomy` y `idle_evolution_daemon` con módulos reales de TARDIS.
     - Lente 5 (`memory_knowledge_hygiene`): Tamaño y fragmentación de DBs SQLite, acumulación
       de colas (`improvement_queue`, `live_dialogue.jsonl`) y archivos `.bak`.
     - Lente 6 (`security_resilience`): Permisos de secretos, exposición de puertos y estado AEGIS.

  2. Canal Bidireccional Persistente TARDIS ↔ AGY:
     - Mantiene un `coevolution_conversation_id` dedicado y persistente en `data/coevolution_state.json`.
     - Bóveda SQLite WAL `data/coevolution_vault.db` (`discoveries`, `dialogue`, `cycles`).
     - TARDIS → AGY: Formula briefs estructurados con evidencia real, métricas pre-cambio y
       criterios de verificación, despachándolos a AGY vía `TardisAgyController` (encolado
       en `tardis-agy-autopilot` o en turno directo en la conversación persistente).
     - AGY → TARDIS: AGY lee descubrimientos pendientes, responde al hilo (`reply_from_agy`),
       registra sistemas creados/parches aplicados con verificación `CanaryVerifier` y delta KPI.

  3. Guardias de Seguridad Anti-Recursión y Presupuesto:
     - `TARDIS_COEVOLUTION_NESTED=1` bloquea recursión infinita cuando AGY ejecuta una orden
       originada por este mismo motor.
     - Consulta `SovereignResourceGovernor.can_admit("coevolution_agy")` antes de despachar.
     - Presupuesto diario acotado (por defecto máx. 12 despachos autónomos/día, cooldown 20 min)
       y deduplicación SHA-256 de descubrimientos.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("TARDIS.AgyCoevolution")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [COEVOLUTION] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

VAULT_DB = DATA_DIR / "coevolution_vault.db"
STATE_FILE = DATA_DIR / "coevolution_state.json"
INBOX_SNAPSHOT_FILE = DATA_DIR / "coevolution_inbox_snapshot.json"
APPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"

DEFAULT_DAILY_DISPATCH_BUDGET = int(os.environ.get("TARDIS_COEVOLUTION_DAILY_BUDGET", "12"))
DEFAULT_DISPATCH_COOLDOWN_S = float(os.environ.get("TARDIS_COEVOLUTION_COOLDOWN_S", "1200"))
DEFAULT_MIN_ROI_FOR_DISPATCH = float(os.environ.get("TARDIS_COEVOLUTION_MIN_ROI", "72.0"))

# Matriz Viva de Capacidades y Sistemas Alternos Candidatos
CAPABILITY_BLUEPRINT_MATRIX: List[Dict[str, Any]] = [
    {
        "id": "alt_semantic_inference_cache",
        "title": "Caché Semántico Local de Inferencia (Embeddings E5 + SQLite WAL)",
        "category": "alternate_system",
        "check_files": ["core/semantic_inference_cache.py"],
        "target_file": "core/semantic_inference_cache.py",
        "roi_score": 88.0,
        "problem": "Consultas repetitivas de demonios autónomos (clasificación, resumen, telemetría) re-invocan TemporalBrain consumiendo CPU/VRAM redundante.",
        "proposal": "Crear `core/semantic_inference_cache.py` usando `embed-e5-small` (`/tmp/embed_brain.sock`) con umbral coseno >= 0.96 y TTL configurable para servir respuestas semánticamente equivalentes en < 5 ms.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_semantic_inference_cache.py -q",
    },
    {
        "id": "alt_unified_dr_snapshot",
        "title": "Motor Soberano de Respaldo Incremental y Recuperación ante Desastres (SQLite Online Backup)",
        "category": "alternate_system",
        "check_files": ["core/sovereign_dr_backup.py"],
        "target_file": "core/sovereign_dr_backup.py",
        "roi_score": 84.0,
        "problem": "Las bóvedas críticas (`rag_vault.db`, `knowledge_graph.db`, `offline_chats.db`, `coevolution_vault.db`) carecen de copias consistentes con verificación de integridad PRAGMA integrity_check y retención GFS.",
        "proposal": "Crear `core/sovereign_dr_backup.py` usando `sqlite3.Connection.backup()` atómico, checksum SHA-256, compresión zstd/gzip y verificación automática de restauración.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_sovereign_dr_backup.py -q",
    },
    {
        "id": "alt_rag_hygiene_deduplicator",
        "title": "Motor de Higiene, Compactación y Deduplicación Semántica de Bóveda RAG & KnowledgeGraph",
        "category": "alternate_system",
        "check_files": ["core/rag_hygiene_engine.py"],
        "target_file": "core/rag_hygiene_engine.py",
        "roi_score": 82.0,
        "problem": "Tras >4,400 papers y >1,400 dossiers omniscientes, `rag_vault.db` y `knowledge_graph.db` acumulan entradas casi duplicadas y fragmentación FTS5 que degradan la precisión de recuperación.",
        "proposal": "Crear `core/rag_hygiene_engine.py` con deduplicación SimHash/MinHash, poda de nodos huérfanos en KnowledgeGraph, `PRAGMA optimize` y `VACUUM` bajo admisión del Resource Governor.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_rag_hygiene_engine.py -q",
    },
    {
        "id": "alt_inference_priority_scheduler",
        "title": "Planificador de Colas con Prioridad para Temporal Brain IPC",
        "category": "alternate_system",
        "check_files": ["core/inference_priority_scheduler.py"],
        "target_file": "core/inference_priority_scheduler.py",
        "roi_score": 86.0,
        "problem": "Cuando múltiples demonios envían prompts concurrentes a `/tmp/temporal_brain.sock` (`--parallel 2`), las consultas interactivas del Arquitecto compiten en FIFO contra tareas background.",
        "proposal": "Crear `core/inference_priority_scheduler.py` con cola heapq multi-carril (P0 Voz/Telegram, P1 Chat Arquitecto, P2 AGY Co-Evolution, P3 Background) y cancelación cooperativa.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_inference_priority_scheduler.py -q",
    },
    {
        "id": "alt_voice_latency_profiler",
        "title": "Perfilador End-to-End de Latencia de Voz (Tapo C310 + Telegram Live Call)",
        "category": "alternate_system",
        "check_files": ["core/voice_latency_profiler.py"],
        "target_file": "core/voice_latency_profiler.py",
        "roi_score": 78.0,
        "problem": "El pipeline de voz (VAD -> Whisper STT -> LLM -> TTS -> Altavoz/WebRTC) carece de trazas desglosadas por etapa (p50/p95/p99) para optimizar tiempos de respuesta.",
        "proposal": "Crear `core/voice_latency_profiler.py` con spans ligeros por etapa, percentiles en SQLite WAL y alertas automáticas al SovereignEventBus cuando p95 > 2.5s.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_voice_latency_profiler.py -q",
    },
    {
        "id": "alt_autonomous_eval_harness",
        "title": "Banco de Evaluación Continua de Calidad Cognitiva y Tool-Calling de KAIJU",
        "category": "alternate_system",
        "check_files": ["core/cognitive_eval_harness.py"],
        "target_file": "core/cognitive_eval_harness.py",
        "roi_score": 80.0,
        "problem": "No existe un benchmark periódico automatizado que mida precisión de tool-calling, adherencia a reglas AEGIS y fidelidad RAG tras cambios de prompts o modelos.",
        "proposal": "Crear `core/cognitive_eval_harness.py` con casos dorados deterministas y reporte histórico de regresiones cognitivas conectado a CanaryVerifier.",
        "verification_cmd": ".venv-linux/bin/pytest tests/test_cognitive_eval_harness.py -q",
    },
]


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-coevo-")
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


class TardisAgyCoevolution:
    """
    Motor de Co-Evolución Continua TARDIS ↔ AGY y Descubrimiento Autónomo de Sistemas/Mejoras.
    """

    _instance: Optional["TardisAgyCoevolution"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None, state_path: Optional[Path] = None) -> "TardisAgyCoevolution":
        if db_path is not None or state_path is not None:
            return cls(db_path=db_path or VAULT_DB, state_path=state_path or STATE_FILE)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=VAULT_DB, state_path=STATE_FILE)
            return cls._instance

    def __init__(self, db_path: Path = VAULT_DB, state_path: Path = STATE_FILE) -> None:
        self.db_path = Path(db_path)
        self.state_path = Path(state_path)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._init_schema()
        self._state = self._load_state()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS discoveries (
                    id TEXT PRIMARY KEY,
                    fingerprint TEXT UNIQUE NOT NULL,
                    created_ts REAL NOT NULL,
                    created_iso TEXT NOT NULL,
                    updated_ts REAL NOT NULL,
                    updated_iso TEXT NOT NULL,
                    lens TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    target_file TEXT,
                    severity TEXT NOT NULL,
                    roi_score REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    problem TEXT NOT NULL,
                    proposal TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    verification_cmd TEXT,
                    dispatched_task_id TEXT,
                    agy_conversation_id TEXT,
                    agy_response TEXT,
                    kpi_impact_json TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS dialogue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_id TEXT UNIQUE NOT NULL,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    conversation_id TEXT,
                    discovery_id TEXT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta_json TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    lenses_run TEXT NOT NULL,
                    discoveries_found INTEGER NOT NULL,
                    discoveries_new INTEGER NOT NULL,
                    dispatched INTEGER NOT NULL,
                    dispatched_id TEXT,
                    pressure_level TEXT,
                    elapsed_s REAL NOT NULL,
                    summary_json TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_disc_status_roi ON discoveries(status, roi_score DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_dial_ts ON dialogue(ts DESC)")

    def _load_state(self) -> Dict[str, Any]:
        default: Dict[str, Any] = {
            "schema": "tardis.coevolution.v1",
            "coevolution_conversation_id": "",
            "enabled": True,
            "auto_dispatch_enabled": True,
            "daily_dispatch_budget": DEFAULT_DAILY_DISPATCH_BUDGET,
            "dispatches_today": 0,
            "dispatch_day": time.strftime("%Y-%m-%d"),
            "last_dispatch_ts": 0.0,
            "last_dispatch_iso": "",
            "last_scan_ts": 0.0,
            "last_scan_iso": "",
            "next_lens_index": 0,
            "cycles_completed": 0,
            "total_dispatches": 0,
            "total_agy_replies": 0,
            "daemon_pid": None,
            "daemon_heartbeat_ts": 0.0,
            "daemon_heartbeat_iso": "",
            "updated_at": _now_iso(),
        }
        if self.state_path.is_file():
            try:
                loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    default.update(loaded)
            except Exception:
                pass
        return default

    def _save_state(self) -> None:
        self._state["updated_at"] = _now_iso()
        _atomic_write_json(self.state_path, self._state)
        self._write_inbox_snapshot()

    def _write_inbox_snapshot(self) -> None:
        """Mantiene un snapshot ultra-ligero para que `tardis-agy-hook` lo lea en < 2 ms."""
        try:
            pending = self.list_discoveries(status="pending", limit=8)
            recent_msgs = self.get_dialogue(limit=5)
            snap = {
                "iso": _now_iso(),
                "coevolution_conversation_id": self._state.get("coevolution_conversation_id", ""),
                "pending_count": len(pending),
                "top_pending": [
                    {
                        "id": d["id"],
                        "lens": d["lens"],
                        "category": d["category"],
                        "severity": d["severity"],
                        "roi_score": d["roi_score"],
                        "title": d["title"],
                        "target_file": d["target_file"],
                    }
                    for d in pending[:5]
                ],
                "latest_dialogue": [
                    {
                        "iso": m["iso"],
                        "direction": m["direction"],
                        "sender": m["sender"],
                        "kind": m["kind"],
                        "preview": m["content"][:220],
                    }
                    for m in recent_msgs[:3]
                ],
            }
            _atomic_write_json(INBOX_SNAPSHOT_FILE, snap)
        except Exception:
            pass

    def _emit_bus(self, topic: str, severity: str, payload: Dict[str, Any]) -> None:
        try:
            from core.sovereign_event_bus import get_event_bus
            get_event_bus().publish(topic=topic, source="tardis_agy_coevolution", severity=severity, payload=payload, dedup_window_s=120.0)
        except Exception:
            pass

    def _mirror_to_bridge(self, sender: str, text: str, role: str = "assistant", category: str = "COEVOLUTION") -> None:
        try:
            import antigravity_bridge
            antigravity_bridge.get_bridge().post_dialogue_message(sender=sender, text=text, role=role, category=category)
        except Exception:
            pass

    def _record_dialogue(
        self,
        *,
        direction: str,
        sender: str,
        kind: str,
        content: str,
        conversation_id: str = "",
        discovery_id: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        iso = _now_iso()
        msg_id = f"coev_msg_{int(now * 1000)}_{uuid.uuid4().hex[:6]}"
        cid = conversation_id or self._state.get("coevolution_conversation_id", "")
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO dialogue (msg_id, ts, iso, direction, sender, conversation_id, discovery_id, kind, content, meta_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (msg_id, now, iso, direction, sender, cid, discovery_id, kind, content, json.dumps(meta or {}, ensure_ascii=False)),
            )
        self._write_inbox_snapshot()
        return {
            "msg_id": msg_id,
            "ts": now,
            "iso": iso,
            "direction": direction,
            "sender": sender,
            "conversation_id": cid,
            "discovery_id": discovery_id,
            "kind": kind,
            "content": content,
        }

    def register_discovery(
        self,
        *,
        lens: str,
        category: str,
        title: str,
        problem: str,
        proposal: str,
        target_file: str = "",
        severity: str = "MEDIA",
        roi_score: float = 70.0,
        evidence: Optional[Dict[str, Any]] = None,
        verification_cmd: str = ".venv-linux/bin/pytest tests/ -q",
        stable_key: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Inserta o actualiza un descubrimiento con deduplicación SHA-256. Retorna (record, is_new)."""
        fp_src = stable_key or f"{lens}|{category}|{target_file}|{title.lower().strip()}"
        fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:24]
        now = time.time()
        iso = _now_iso()
        sev = (severity or "MEDIA").upper()

        with self._lock:
            with self._connect() as con:
                existing = con.execute("SELECT * FROM discoveries WHERE fingerprint = ?", (fp,)).fetchone()
                if existing is not None:
                    # Actualizar evidencia y score si sigue pendiente; no reabrir si ya implementado
                    if existing["status"] == "pending":
                        con.execute(
                            """
                            UPDATE discoveries
                            SET updated_ts = ?, updated_iso = ?, roi_score = ?, problem = ?, evidence_json = ?
                            WHERE id = ?
                            """,
                            (now, iso, float(roi_score), problem, json.dumps(evidence or {}, ensure_ascii=False), existing["id"]),
                        )
                    updated = con.execute("SELECT * FROM discoveries WHERE id = ?", (existing["id"],)).fetchone()
                    return self._row_to_discovery(updated), False

                disc_id = f"disc_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                con.execute(
                    """
                    INSERT INTO discoveries (
                        id, fingerprint, created_ts, created_iso, updated_ts, updated_iso,
                        lens, category, title, target_file, severity, roi_score, status,
                        problem, proposal, evidence_json, verification_cmd
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        disc_id,
                        fp,
                        now,
                        iso,
                        now,
                        iso,
                        lens,
                        category,
                        title[:160],
                        target_file,
                        sev,
                        float(roi_score),
                        "pending",
                        problem[:1200],
                        proposal[:1600],
                        json.dumps(evidence or {}, ensure_ascii=False),
                        verification_cmd,
                    ),
                )
                row = con.execute("SELECT * FROM discoveries WHERE id = ?", (disc_id,)).fetchone()
                rec = self._row_to_discovery(row)

        self._emit_bus(
            "discovery.new",
            "HIGH" if sev in ("ALTA", "HIGH", "CRITICA", "CRITICAL") else "INFO",
            {"id": rec["id"], "lens": lens, "category": category, "title": rec["title"], "roi_score": rec["roi_score"]},
        )
        return rec, True

    @staticmethod
    def _row_to_discovery(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        try:
            d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
        except Exception:
            d["evidence"] = {}
        try:
            d["kpi_impact"] = json.loads(d.pop("kpi_impact_json") or "{}")
        except Exception:
            d["kpi_impact"] = {}
        return d

    # =========================================================================
    # RADAR DE 6 LENTES DE DESCUBRIMIENTO AUTÓNOMO
    # =========================================================================
    def _lens_1_runtime_telemetry(self) -> List[Dict[str, Any]]:
        """Lente 1: Presión Ring 0, carriles LLM, HubHealth y alertas del Bus."""
        found: List[Dict[str, Any]] = []
        try:
            from core.sovereign_resource_governor import get_resource_governor
            snap = get_resource_governor().collect_telemetry(persist=False, cache_ttl=10.0)
            lanes = snap.get("inference_lanes") or {}
            if lanes.get("duplicate_count", 0) > 0:
                found.append({
                    "lens": "runtime_telemetry",
                    "category": "performance_optimization",
                    "title": f"Modelos duplicados activos en Ollama CPU :11434 (~{lanes['reclaimable_ram_mb']} MB recuperables)",
                    "target_file": "core/sovereign_resource_governor.py",
                    "severity": "ALTA",
                    "roi_score": 92.0,
                    "problem": f"Se detectaron {lanes['duplicate_count']} modelos duplicados en :11434 mientras TemporalBrain/GPU lane están activos.",
                    "proposal": "Ejecutar `tardis-governor reclaim` y auditar qué servicio sigue enviando peticiones a 127.0.0.1:11434.",
                    "evidence": lanes,
                    "verification_cmd": "tardis-governor status",
                    "stable_key": "lens1_duplicate_ollama_models",
                })
            if snap["cpu"]["psi_some_avg10"] >= 45.0 or snap["memory"]["ram_avail_mb"] < 2800.0:
                found.append({
                    "lens": "runtime_telemetry",
                    "category": "resource_optimization",
                    "title": f"Contención sostenida de silicio (PSI CPU {snap['cpu']['psi_some_avg10']}%, RAM libre {snap['memory']['ram_avail_mb']} MB)",
                    "target_file": "core/tapo_c310_sentinel.py",
                    "severity": "ALTA",
                    "roi_score": 89.0,
                    "problem": f"Load={snap['cpu']['loadavg_1m']} | PSI CPU={snap['cpu']['psi_some_avg10']}% | Swap={snap['memory']['swap_used_mb']} MB.",
                    "proposal": "Perfilar top consumidores (llama-server, tapo_c310_sentinel/ffmpeg, python daemons), ajustar nice/CPUQuota systemd y reducir FPS/resolución de decodificación continua cuando no hay movimiento.",
                    "evidence": {"cpu": snap["cpu"], "memory": snap["memory"], "gpu": snap["gpu"]},
                    "verification_cmd": "tardis-governor status",
                    "stable_key": "lens1_silicon_contention",
                })
        except Exception as exc:
            logger.debug("Lens 1 governor error: %s", exc)

        try:
            from core.hub_health import hub_health
            hh = hub_health(force=False)
            for sid, info in (hh.get("subsystems") or {}).items():
                st = info.get("status")
                if st in ("degraded", "offline") and sid != "airplay_monitor":
                    found.append({
                        "lens": "runtime_telemetry",
                        "category": "reliability_fix",
                        "title": f"Subsistema Master Hub `{sid}` en estado {st.upper()}",
                        "target_file": "core/hub_health.py",
                        "severity": "ALTA" if st == "offline" else "MEDIA",
                        "roi_score": 85.0 if st == "offline" else 76.0,
                        "problem": f"Sonda de `{sid}` reporta `{st}`: detail={info.get('detail')}, unit={info.get('unit')}, http={info.get('http')}.",
                        "proposal": f"Diagnosticar servicio/endpoint de `{sid}`, reparar unidad systemd o ruta HTTP y verificar con `/api/hub/health?force=true`.",
                        "evidence": info,
                        "verification_cmd": "curl -s http://127.0.0.1:8757/api/hub/health",
                        "stable_key": f"lens1_hub_sub_{sid}",
                    })
        except Exception as exc:
            logger.debug("Lens 1 hub_health error: %s", exc)

        # Consumir alertas de severidad HIGH/CRITICAL del SovereignEventBus
        try:
            from core.sovereign_event_bus import get_event_bus
            consumed = get_event_bus().consume(
                "coevolution_lens1",
                topic_prefixes=["anomaly.", "health.", "canary.failed", "security."],
                severities=["HIGH", "CRITICAL"],
                limit=10,
            )
            for ev in consumed.get("events") or []:
                found.append({
                    "lens": "runtime_telemetry",
                    "category": "incident_remediation",
                    "title": f"Evento crítico en Bus [{ev['topic']}] desde {ev['source']}",
                    "target_file": str(ev["payload"].get("target_file") or "server/api.py"),
                    "severity": "ALTA",
                    "roi_score": 88.0,
                    "problem": json.dumps(ev["payload"], ensure_ascii=False)[:600],
                    "proposal": "Investigar causa raíz del evento en SovereignEventBus, aplicar corrección quirúrgica y validar con CanaryVerifier.",
                    "evidence": ev,
                    "verification_cmd": "tardis-bus tail --limit 10",
                    "stable_key": f"lens1_bus_{ev['topic']}_{ev['source']}",
                })
        except Exception:
            pass

        return found

    def _lens_2_codebase_archaeology(self) -> List[Dict[str, Any]]:
        """Lente 2: Auditoría AST de deuda técnica, monolitos sin tests y anti-patrones."""
        found: List[Dict[str, Any]] = []
        tests_dir = PROJECT_ROOT / "tests"
        existing_tests = {p.stem.lower() for p in tests_dir.glob("test_*.py")} if tests_dir.is_dir() else set()

        monoliths: List[Tuple[int, str]] = []
        untested_large: List[Tuple[int, str]] = []
        silent_excepts_top: List[Tuple[int, str]] = []

        core_dir = PROJECT_ROOT / "core"
        py_files = list(core_dir.glob("*.py")) if core_dir.is_dir() else []
        for p in py_files:
            if p.name.startswith("__"):
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
                loc = src.count("\n") + 1
                if loc >= 2000:
                    monoliths.append((loc, f"core/{p.name}"))
                if loc >= 800 and f"test_{p.stem.lower()}" not in existing_tests:
                    untested_large.append((loc, f"core/{p.name}"))
                tree = ast.parse(src)
                silent = sum(
                    1
                    for n in ast.walk(tree)
                    if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 and isinstance(n.body[0], ast.Pass)
                )
                if silent >= 15:
                    silent_excepts_top.append((silent, f"core/{p.name}"))
            except Exception:
                continue

        if monoliths:
            monoliths.sort(reverse=True)
            top = monoliths[:5]
            found.append({
                "lens": "codebase_archaeology",
                "category": "architecture_refactor",
                "title": f"Modularización progresiva de monolitos críticos ({top[0][1]}: {top[0][0]} LOC)",
                "target_file": top[0][1],
                "severity": "MEDIA",
                "roi_score": 74.0,
                "problem": f"Módulos core superan 2,000 LOC ({', '.join(f'{f}={l}L' for l, f in top)}), dificultando testing aislado y mantenibilidad.",
                "proposal": "Extraer componentes cohesivos (transporte, modelos de datos, lógica de dominio) en submódulos con cobertura pytest dedicada.",
                "evidence": {"monoliths": [{"file": f, "loc": l} for l, f in top]},
                "verification_cmd": ".venv-linux/bin/pytest tests/ -q",
                "stable_key": f"lens2_monolith_{top[0][1]}",
            })

        if untested_large:
            untested_large.sort(reverse=True)
            top_u = untested_large[:6]
            found.append({
                "lens": "codebase_archaeology",
                "category": "test_coverage",
                "title": f"Brecha de pruebas automatizadas en {len(untested_large)} módulos core > 800 LOC",
                "target_file": top_u[0][1],
                "severity": "MEDIA",
                "roi_score": 77.0,
                "problem": f"Módulos complejos sin archivo `tests/test_<mod>.py`: {', '.join(f'{f} ({l}L)' for l, f in top_u)}.",
                "proposal": f"Crear suite pytest con mocks de hardware/red para `{top_u[0][1]}` y conectarla al mapeo de CanaryVerifier.",
                "evidence": {"untested_large": [{"file": f, "loc": l} for l, f in top_u]},
                "verification_cmd": ".venv-linux/bin/pytest tests/ -q",
                "stable_key": f"lens2_untested_{top_u[0][1]}",
            })

        if silent_excepts_top:
            silent_excepts_top.sort(reverse=True)
            top_s = silent_excepts_top[:5]
            found.append({
                "lens": "codebase_archaeology",
                "category": "observability_hardening",
                "title": f"Excepciones silenciadas masivas en `{top_s[0][1]}` ({top_s[0][0]} bloques except:pass)",
                "target_file": top_s[0][1],
                "severity": "MEDIA",
                "roi_score": 72.0,
                "problem": f"Múltiples módulos tragan excepciones sin telemetría: {', '.join(f'{f}={c}' for c, f in top_s)}.",
                "proposal": "Reemplazar bloques `except: pass` en rutas críticas por `logger.debug(...)` o emisión al `SovereignEventBus`.",
                "evidence": {"silent_excepts": [{"file": f, "count": c} for c, f in top_s]},
                "verification_cmd": f".venv-linux/bin/python3 -m py_compile {top_s[0][1]}",
                "stable_key": f"lens2_silent_excepts_{top_s[0][1]}",
            })

        return found

    def _lens_3_capability_matrix(self) -> List[Dict[str, Any]]:
        """Lente 3: Sistemas alternos de alto impacto aún ausentes en la arquitectura TARDIS."""
        found: List[Dict[str, Any]] = []
        for bp in CAPABILITY_BLUEPRINT_MATRIX:
            exists = all((PROJECT_ROOT / rel).is_file() for rel in bp["check_files"])
            if not exists:
                found.append({
                    "lens": "capability_matrix",
                    "category": bp["category"],
                    "title": bp["title"],
                    "target_file": bp["target_file"],
                    "severity": "MEDIA",
                    "roi_score": float(bp["roi_score"]),
                    "problem": bp["problem"],
                    "proposal": bp["proposal"],
                    "evidence": {"blueprint_id": bp["id"], "missing_files": bp["check_files"]},
                    "verification_cmd": bp["verification_cmd"],
                    "stable_key": f"lens3_{bp['id']}",
                })
        return found

    def _lens_4_external_frontier_scouting(self) -> List[Dict[str, Any]]:
        """Lente 4: Traduce hallazgos recientes de Omniscient Autonomy e Idle Evolution en mejoras reales."""
        found: List[Dict[str, Any]] = []
        tech_log = DATA_DIR / "omniscient_tech_evolution.jsonl"
        if tech_log.is_file():
            try:
                lines = tech_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-5:]
                for ln in reversed(lines):
                    if not ln.strip():
                        continue
                    rec = json.loads(ln)
                    title = str(rec.get("frontier_title") or "").strip()
                    bp = str(rec.get("optimization_blueprint") or "").strip()
                    if title and bp:
                        found.append({
                            "lens": "external_frontier_scouting",
                            "category": "research_to_production",
                            "title": f"Aplicar frontera científica: {title[:110]}",
                            "target_file": "core/tardis_omniscient_autonomy.py",
                            "severity": "BAJA",
                            "roi_score": 68.0,
                            "problem": f"Dossier científico `{rec.get('id')}` generado pero aún no convertido en experimento/código verificable.",
                            "proposal": bp[:900],
                            "evidence": {
                                "dossier_id": rec.get("id"),
                                "scope": rec.get("target_scope"),
                                "scientific_evidence": rec.get("scientific_evidence", [])[:3],
                            },
                            "verification_cmd": ".venv-linux/bin/pytest tests/test_sovereign_coevolution_suite.py -q",
                            "stable_key": f"lens4_frontier_{hashlib.sha1(title.encode()).hexdigest()[:12]}",
                        })
                        break
            except Exception:
                pass
        return found

    def _lens_5_memory_knowledge_hygiene(self) -> List[Dict[str, Any]]:
        """Lente 5: Auditoría de DBs SQLite, colas estancadas y acumulación de respaldos."""
        found: List[Dict[str, Any]] = []
        large_dbs: List[Dict[str, Any]] = []
        for db in sorted(DATA_DIR.glob("*.db")):
            try:
                mb = round(db.stat().st_size / (1024 * 1024), 2)
                if mb >= 50.0:
                    large_dbs.append({"db": db.name, "size_mb": mb})
            except OSError:
                pass
        if large_dbs:
            found.append({
                "lens": "memory_knowledge_hygiene",
                "category": "storage_hygiene",
                "title": f"Compactación y optimización SQLite requerida ({len(large_dbs)} DBs >= 50 MB)",
                "target_file": "core/rag_vault.py",
                "severity": "BAJA",
                "roi_score": 66.0,
                "problem": f"Bases de datos de gran tamaño detectadas: {large_dbs}.",
                "proposal": "Ejecutar `PRAGMA optimize`, `PRAGMA wal_checkpoint(TRUNCATE)` y deduplicación periódica en horario de baja presión.",
                "evidence": {"large_dbs": large_dbs},
                "verification_cmd": "ls -lh data/*.db",
                "stable_key": "lens5_sqlite_hygiene",
            })

        queue_dir = APPDATA_DIR / "improvement_queue"
        if queue_dir.is_dir():
            q_count = len(list(queue_dir.glob("improvement_*.md")))
            if q_count >= 40:
                found.append({
                    "lens": "memory_knowledge_hygiene",
                    "category": "queue_hygiene",
                    "title": f"Backlog histórico acumulado en improvement_queue ({q_count} propuestas)",
                    "target_file": "antigravity_bridge.py",
                    "severity": "MEDIA",
                    "roi_score": 73.0,
                    "problem": f"Existen {q_count} archivos `improvement_*.md` en `{queue_dir}` sin triaje ni archivo histórico.",
                    "proposal": "Triar propuestas antiguas (>14 días) hacia `improvement_queue/archived/` y consolidar las de mayor ROI en `coevolution_vault.db`.",
                    "evidence": {"queue_dir": str(queue_dir), "count": q_count},
                    "verification_cmd": "ls -1 ~/vw-control/improvement_queue/*.md | wc -l",
                    "stable_key": "lens5_improvement_queue_backlog",
                })
        return found

    def _lens_6_security_resilience(self) -> List[Dict[str, Any]]:
        """Lente 6: Higiene de permisos de secretos y resiliencia del perímetro."""
        found: List[Dict[str, Any]] = []
        secret_files = [
            PROJECT_ROOT / "gia_bridge_token.txt",
            PROJECT_ROOT / "akashic_secret.key",
            PROJECT_ROOT / "client_gateway_secrets.json",
        ]
        loose: List[Dict[str, Any]] = []
        for sf in secret_files:
            if sf.is_file():
                mode = sf.stat().st_mode & 0o777
                if mode & 0o077:
                    loose.append({"file": sf.name, "mode": oct(mode)})
        if loose:
            found.append({
                "lens": "security_resilience",
                "category": "security_hardening",
                "title": f"Permisos excesivos en archivos de credenciales ({len(loose)} archivos)",
                "target_file": "core/security.py",
                "severity": "ALTA",
                "roi_score": 90.0,
                "problem": f"Archivos sensibles legibles por grupo/otros: {loose}.",
                "proposal": "Restringir permisos a `0600` y validar automáticamente en el arranque de `tardis.service`.",
                "evidence": {"loose_secret_files": loose},
                "verification_cmd": "stat -c '%a %n' gia_bridge_token.txt akashic_secret.key client_gateway_secrets.json",
                "stable_key": "lens6_loose_secret_perms",
            })
        return found

    def scan_discoveries(self, lenses: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Ejecuta los lentes de descubrimiento indicados (o todos) y persiste hallazgos."""
        t0 = time.time()
        all_lenses = [
            ("runtime_telemetry", self._lens_1_runtime_telemetry),
            ("codebase_archaeology", self._lens_2_codebase_archaeology),
            ("capability_matrix", self._lens_3_capability_matrix),
            ("external_frontier_scouting", self._lens_4_external_frontier_scouting),
            ("memory_knowledge_hygiene", self._lens_5_memory_knowledge_hygiene),
            ("security_resilience", self._lens_6_security_resilience),
        ]
        selected = all_lenses
        if lenses and "all" not in [x.lower() for x in lenses]:
            want = {x.lower().strip() for x in lenses}
            selected = [
                (name, fn)
                for idx, (name, fn) in enumerate(all_lenses, 1)
                if name in want or str(idx) in want
            ]

        registered: List[Dict[str, Any]] = []
        new_count = 0
        lenses_run: List[str] = []

        for lens_name, fn in selected:
            lenses_run.append(lens_name)
            try:
                items = fn()
                for item in items:
                    rec, is_new = self.register_discovery(**item)
                    registered.append(rec)
                    if is_new:
                        new_count += 1
            except Exception as exc:
                logger.warning("Error ejecutando lente %s: %s", lens_name, exc)

        self._state["last_scan_ts"] = time.time()
        self._state["last_scan_iso"] = _now_iso()
        self._save_state()

        registered.sort(key=lambda x: float(x.get("roi_score", 0.0)), reverse=True)
        return {
            "ok": True,
            "lenses_run": lenses_run,
            "found_count": len(registered),
            "new_count": new_count,
            "elapsed_s": round(time.time() - t0, 2),
            "discoveries": registered,
            "iso": _now_iso(),
        }

    # =========================================================================
    # CONSULTA Y GESTIÓN DE DESCUBRIMIENTOS
    # =========================================================================
    def list_discoveries(self, status: str = "all", limit: int = 30) -> List[Dict[str, Any]]:
        with self._connect() as con:
            if status and status.lower() != "all":
                rows = con.execute(
                    "SELECT * FROM discoveries WHERE status = ? ORDER BY roi_score DESC, updated_ts DESC LIMIT ?",
                    (status.lower(), max(1, min(200, int(limit)))),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM discoveries ORDER BY roi_score DESC, updated_ts DESC LIMIT ?",
                    (max(1, min(200, int(limit))),),
                ).fetchall()
        return [self._row_to_discovery(r) for r in rows]

    def get_discovery(self, discovery_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM discoveries WHERE id = ?", (discovery_id,)).fetchone()
        return self._row_to_discovery(row) if row else None

    def get_dialogue(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM dialogue ORDER BY id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            try:
                d["meta"] = json.loads(d.pop("meta_json") or "{}")
            except Exception:
                d["meta"] = {}
            out.append(d)
        return out

    # =========================================================================
    # COMUNICACIÓN BIDIRECCIONAL PERSISTENTE TARDIS ↔ AGY
    # =========================================================================
    def _reset_daily_budget_if_needed(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._state.get("dispatch_day") != today:
            self._state["dispatch_day"] = today
            self._state["dispatches_today"] = 0

    def _build_coevolution_brief(self, discovery: Dict[str, Any]) -> str:
        """Construye un brief estructurado de alta señal para AGY."""
        cid = self._state.get("coevolution_conversation_id") or "(nueva sesión persistente)"
        return (
            f"[CO-EVOLUCIÓN CONTINUA TARDIS → AGY · {discovery['id']}]\n"
            f"Hilo Persistente: {cid}\n"
            f"Lente de Descubrimiento: {discovery['lens']} | Categoría: {discovery['category']}\n"
            f"Severidad: {discovery['severity']} | ROI Estimado: {discovery['roi_score']}/100\n"
            f"Título: {discovery['title']}\n"
            f"Archivo/Módulo Objetivo: {discovery.get('target_file') or '(sistema nuevo / arquitectura)'}\n\n"
            f"PROBLEMA DETECTADO (Evidencia Empírica):\n{discovery['problem']}\n\n"
            f"EVIDENCIA TÉCNICA:\n{json.dumps(discovery.get('evidence', {}), ensure_ascii=False)[:900]}\n\n"
            f"PROPUESTA INICIAL DE TARDIS:\n{discovery['proposal']}\n\n"
            f"VERIFICACIÓN SUGERIDA:\n{discovery.get('verification_cmd') or '.venv-linux/bin/pytest tests/ -q'}\n\n"
            "INSTRUCCIÓN DE CO-EVOLUCIÓN PARA AGY:\n"
            "1. Evalúa la evidencia y decide si implementar el parche/sistema alterno o proponer una arquitectura superior.\n"
            "2. Si modificas o creas código, valídalo con `tardis-canary verify <archivos>` y pruebas unitarias.\n"
            "3. Reporta tu respuesta estructurada de regreso a TARDIS ejecutando:\n"
            f"   tardis-coevolution reply \"<resumen técnico + archivos + resultados>\" --discovery-id {discovery['id']} --status implemented\n"
            "4. NOTA ANTI-RECURSIÓN: TARDIS_COEVOLUTION_NESTED=1 está activo; NO dispares otro ciclo de despacho AGY."
        )

    def ask_agy(
        self,
        message: str,
        *,
        discovery_id: str = "",
        mode: str = "enqueue",
        priority: str = "normal",
        timeout: int = 300,
        model: Optional[str] = None,
        bypass_guards: bool = False,
    ) -> Dict[str, Any]:
        """
        Envía un mensaje o brief estructurado desde TARDIS hacia AGY manteniendo
        el mismo `coevolution_conversation_id` persistente.
        mode:
          - 'enqueue': encola en `tardis-agy-autopilot` (no bloqueante, ideal para daemon 24/7).
          - 'live': ejecuta un turno real vía `TardisAgyController.run_task` y devuelve la respuesta.
        """
        if not bypass_guards and os.environ.get("TARDIS_COEVOLUTION_NESTED") == "1":
            return {"ok": False, "blocked": True, "reason": "anti_recursion_guard_active"}

        self._reset_daily_budget_if_needed()
        if not bypass_guards:
            if int(self._state.get("dispatches_today", 0)) >= int(self._state.get("daily_dispatch_budget", DEFAULT_DAILY_DISPATCH_BUDGET)):
                return {"ok": False, "blocked": True, "reason": "daily_dispatch_budget_exhausted"}
            try:
                from core.sovereign_resource_governor import get_resource_governor
                adm = get_resource_governor().can_admit("coevolution_agy", priority=priority)
                if not adm.get("admitted"):
                    return {"ok": False, "blocked": True, "reason": adm.get("reason", "resource_governor_denied")}
            except Exception:
                pass

        cid = str(self._state.get("coevolution_conversation_id") or "").strip() or None
        self._record_dialogue(
            direction="tardis_to_agy",
            sender="TARDIS-COEVOLUTION",
            kind="coevolution_brief" if discovery_id else "direct_query",
            content=message,
            conversation_id=cid or "",
            discovery_id=discovery_id,
            meta={"mode": mode, "priority": priority},
        )
        self._mirror_to_bridge(
            sender="TARDIS-COEVOLUTION",
            text=f"[TARDIS → AGY · {mode.upper()}] {message[:500]}",
            role="user",
            category="COEVOLUTION_DISPATCH",
        )

        try:
            from core.tardis_agy_controller import get_tardis_agy_controller
            ctrl = get_tardis_agy_controller()
        except Exception as exc:
            return {"ok": False, "error": f"TardisAgyController no disponible: {exc}"}

        prev_nested = os.environ.get("TARDIS_COEVOLUTION_NESTED")
        os.environ["TARDIS_COEVOLUTION_NESTED"] = "1"
        try:
            if mode == "live":
                res = ctrl.run_task(
                    message,
                    cwd=str(PROJECT_ROOT),
                    model=model,
                    conversation_id=cid,
                    timeout=int(timeout),
                    source="tardis_coevolution_live",
                    fallback_to_local=False,
                )
                out_cid = str(res.get("conversation_id") or cid or "").strip()
                if out_cid:
                    self._state["coevolution_conversation_id"] = out_cid
                self._state["dispatches_today"] = int(self._state.get("dispatches_today", 0)) + 1
                self._state["total_dispatches"] = int(self._state.get("total_dispatches", 0)) + 1
                self._state["last_dispatch_ts"] = time.time()
                self._state["last_dispatch_iso"] = _now_iso()
                self._save_state()

                reply_txt = str(res.get("response") or res.get("error") or "").strip()
                if reply_txt:
                    self.reply_from_agy(
                        reply_txt,
                        discovery_id=discovery_id,
                        status="analyzed" if res.get("ok") else "failed",
                        conversation_id=out_cid,
                        task_id=str(res.get("task_id") or ""),
                    )
                self._emit_bus(
                    "coevolution.live_turn",
                    "INFO" if res.get("ok") else "WARN",
                    {"ok": res.get("ok"), "conversation_id": out_cid, "discovery_id": discovery_id, "elapsed": res.get("elapsed")},
                )
                return {
                    "ok": bool(res.get("ok")),
                    "mode": "live",
                    "task_id": res.get("task_id"),
                    "conversation_id": out_cid,
                    "response": reply_txt,
                    "elapsed": res.get("elapsed"),
                    "error": res.get("error", ""),
                }

            # Modo enqueue (asíncrono vía tardis-agy-autopilot.service)
            enq = ctrl.enqueue_task(
                message,
                source="tardis_coevolution",
                priority=priority,
                cwd=str(PROJECT_ROOT),
                model=model,
                conversation_id=cid,
                timeout=int(timeout),
                dedup_window_s=1800.0,
                meta={"discovery_id": discovery_id, "coevolution": True, "TARDIS_COEVOLUTION_NESTED": "1"},
            )
            if enq.get("ok"):
                self._state["dispatches_today"] = int(self._state.get("dispatches_today", 0)) + 1
                self._state["total_dispatches"] = int(self._state.get("total_dispatches", 0)) + 1
                self._state["last_dispatch_ts"] = time.time()
                self._state["last_dispatch_iso"] = _now_iso()
                self._save_state()
                if discovery_id:
                    with self._connect() as con:
                        con.execute(
                            """
                            UPDATE discoveries
                            SET status = 'dispatched', dispatched_task_id = ?, agy_conversation_id = ?,
                                updated_ts = ?, updated_iso = ?
                            WHERE id = ?
                            """,
                            (str(enq.get("task_id") or ""), cid or "", time.time(), _now_iso(), discovery_id),
                        )
                self._emit_bus(
                    "coevolution.dispatched",
                    "INFO",
                    {"task_id": enq.get("task_id"), "discovery_id": discovery_id, "conversation_id": cid or ""},
                )
            return {"ok": bool(enq.get("ok")), "mode": "enqueue", **enq, "conversation_id": cid or ""}
        finally:
            if prev_nested is None:
                os.environ.pop("TARDIS_COEVOLUTION_NESTED", None)
            else:
                os.environ["TARDIS_COEVOLUTION_NESTED"] = prev_nested

    def reply_from_agy(
        self,
        message: str,
        *,
        discovery_id: str = "",
        status: str = "analyzed",
        conversation_id: str = "",
        task_id: str = "",
        kpi_impact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Registra una respuesta / solución enviada desde AGY hacia TARDIS."""
        cid = conversation_id.strip() or str(self._state.get("coevolution_conversation_id") or "")
        if cid and not self._state.get("coevolution_conversation_id"):
            self._state["coevolution_conversation_id"] = cid

        msg = self._record_dialogue(
            direction="agy_to_tardis",
            sender="AGY-ARCHITECT",
            kind="agy_reply",
            content=message,
            conversation_id=cid,
            discovery_id=discovery_id,
            meta={"status": status, "task_id": task_id, "kpi_impact": kpi_impact or {}},
        )
        self._state["total_agy_replies"] = int(self._state.get("total_agy_replies", 0)) + 1
        self._save_state()

        if discovery_id:
            with self._connect() as con:
                con.execute(
                    """
                    UPDATE discoveries
                    SET status = ?, agy_conversation_id = ?, agy_response = ?,
                        kpi_impact_json = ?, updated_ts = ?, updated_iso = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        cid,
                        message[:4000],
                        json.dumps(kpi_impact or {}, ensure_ascii=False),
                        time.time(),
                        _now_iso(),
                        discovery_id,
                    ),
                )

        self._mirror_to_bridge(
            sender="AGY-COEVOLUTION",
            text=f"[AGY → TARDIS · {status.upper()}] {f'({discovery_id}) ' if discovery_id else ''}{message[:600]}",
            role="assistant",
            category="COEVOLUTION_REPLY",
        )
        self._emit_bus(
            "coevolution.reply",
            "INFO",
            {"discovery_id": discovery_id, "status": status, "conversation_id": cid, "msg_id": msg["msg_id"]},
        )

        # Ingestar hallazgo en RAGVault para memoria a largo plazo de TARDIS
        try:
            from core.rag_vault import get_rag_vault
            get_rag_vault().ingest(
                f"[CO-EVOLUCIÓN AGY → TARDIS · {status}]\nDiscovery: {discovery_id}\n{message[:1500]}",
                source="tardis_agy_coevolution",
                title=f"AGY Co-Evolution Reply {discovery_id or msg['msg_id']}",
                term="coevolution agy tardis",
            )
        except Exception:
            pass

        return {"ok": True, "message": msg, "discovery_id": discovery_id, "status": status, "conversation_id": cid}

    # =========================================================================
    # CICLO COMPLETO DE CO-EVOLUCIÓN Y DEMONIO 24/7
    # =========================================================================
    def run_cycle(
        self,
        *,
        lenses: Optional[Sequence[str]] = None,
        dispatch: bool = True,
        dispatch_mode: str = "enqueue",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Ejecuta un ciclo completo: Radar -> Triaje por ROI -> Despacho opcional a AGY."""
        t0 = time.time()
        pressure_level = "UNKNOWN"
        try:
            from core.sovereign_resource_governor import get_resource_governor
            snap = get_resource_governor().collect_telemetry(persist=False, cache_ttl=10.0)
            pressure_level = snap["pressure_level"]
        except Exception:
            pass

        scan = self.scan_discoveries(lenses=lenses)
        dispatched = False
        dispatched_id = ""
        dispatch_result: Optional[Dict[str, Any]] = None

        now = time.time()
        cooldown_ok = (now - float(self._state.get("last_dispatch_ts", 0.0))) >= DEFAULT_DISPATCH_COOLDOWN_S

        if dispatch and self._state.get("auto_dispatch_enabled", True) and not dry_run:
            pending = self.list_discoveries(status="pending", limit=10)
            top = next((d for d in pending if float(d.get("roi_score", 0.0)) >= DEFAULT_MIN_ROI_FOR_DISPATCH), None)
            if top and cooldown_ok:
                brief = self._build_coevolution_brief(top)
                prio = "high" if top["severity"] in ("ALTA", "HIGH", "CRITICA", "CRITICAL") else "normal"
                dispatch_result = self.ask_agy(
                    brief,
                    discovery_id=top["id"],
                    mode=dispatch_mode,
                    priority=prio,
                )
                if dispatch_result.get("ok"):
                    dispatched = True
                    dispatched_id = top["id"]

        elapsed = round(time.time() - t0, 2)
        self._state["cycles_completed"] = int(self._state.get("cycles_completed", 0)) + 1
        self._save_state()

        summary = {
            "ok": True,
            "cycle_number": self._state["cycles_completed"],
            "lenses_run": scan["lenses_run"],
            "discoveries_found": scan["found_count"],
            "discoveries_new": scan["new_count"],
            "dispatched": dispatched,
            "dispatched_id": dispatched_id,
            "dispatch_result": dispatch_result,
            "pressure_level": pressure_level,
            "elapsed_s": elapsed,
            "iso": _now_iso(),
        }
        try:
            with self._connect() as con:
                con.execute(
                    """
                    INSERT INTO cycles (
                        ts, iso, lenses_run, discoveries_found, discoveries_new,
                        dispatched, dispatched_id, pressure_level, elapsed_s, summary_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        time.time(),
                        summary["iso"],
                        ",".join(scan["lenses_run"]),
                        scan["found_count"],
                        scan["new_count"],
                        1 if dispatched else 0,
                        dispatched_id,
                        pressure_level,
                        elapsed,
                        json.dumps(summary, ensure_ascii=False),
                    ),
                )
        except Exception:
            pass
        return summary

    def get_status(self) -> Dict[str, Any]:
        self._reset_daily_budget_if_needed()
        with self._connect() as con:
            rows = con.execute("SELECT status, COUNT(*) AS c FROM discoveries GROUP BY status").fetchall()
            counts = {r["status"]: int(r["c"]) for r in rows}
            dial_count = int(con.execute("SELECT COUNT(*) FROM dialogue").fetchone()[0])
            cycles_count = int(con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0])
        return {
            "ok": True,
            "schema": "tardis.coevolution.v1",
            "coevolution_conversation_id": self._state.get("coevolution_conversation_id", ""),
            "enabled": bool(self._state.get("enabled", True)),
            "auto_dispatch_enabled": bool(self._state.get("auto_dispatch_enabled", True)),
            "daily_dispatch_budget": int(self._state.get("daily_dispatch_budget", DEFAULT_DAILY_DISPATCH_BUDGET)),
            "dispatches_today": int(self._state.get("dispatches_today", 0)),
            "total_dispatches": int(self._state.get("total_dispatches", 0)),
            "total_agy_replies": int(self._state.get("total_agy_replies", 0)),
            "cycles_completed": cycles_count,
            "dialogue_messages": dial_count,
            "discoveries_by_status": counts,
            "top_pending_discoveries": self.list_discoveries(status="pending", limit=5),
            "last_scan_iso": self._state.get("last_scan_iso", ""),
            "last_dispatch_iso": self._state.get("last_dispatch_iso", ""),
            "daemon_pid": self._state.get("daemon_pid"),
            "daemon_heartbeat_iso": self._state.get("daemon_heartbeat_iso", ""),
            "inbox_snapshot_path": str(INBOX_SNAPSHOT_FILE),
            "vault_db": str(self.db_path),
            "iso": _now_iso(),
        }

    def run_daemon(self, interval: float = 1200.0, auto_dispatch: bool = True) -> int:
        def _sig(signum, _frame):
            logger.info("Señal %s recibida; deteniendo TARDIS Co-Evolution Daemon...", signum)
            self._stop_event.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)

        self._state["daemon_pid"] = os.getpid()
        self._state["daemon_heartbeat_ts"] = time.time()
        self._state["daemon_heartbeat_iso"] = _now_iso()
        self._save_state()
        logger.info("TARDIS ↔ AGY Co-Evolution Daemon activo (PID=%d, interval=%.0fs, auto_dispatch=%s)", os.getpid(), interval, auto_dispatch)

        lens_names = [
            "runtime_telemetry",
            "codebase_archaeology",
            "capability_matrix",
            "external_frontier_scouting",
            "memory_knowledge_hygiene",
            "security_resilience",
        ]

        while not self._stop_event.is_set():
            try:
                idx = int(self._state.get("next_lens_index", 0)) % len(lens_names)
                # Siempre incluir runtime_telemetry + lente rotativo
                lenses_this_turn = list(dict.fromkeys(["runtime_telemetry", lens_names[idx]]))
                self._state["next_lens_index"] = (idx + 1) % len(lens_names)
                self._state["daemon_heartbeat_ts"] = time.time()
                self._state["daemon_heartbeat_iso"] = _now_iso()

                res = self.run_cycle(lenses=lenses_this_turn, dispatch=auto_dispatch, dispatch_mode="enqueue")
                logger.info(
                    "Ciclo #%s completado (%ss) | lentes=%s | hallazgos=%s (nuevos=%s) | dispatched=%s",
                    res["cycle_number"],
                    res["elapsed_s"],
                    res["lenses_run"],
                    res["discoveries_found"],
                    res["discoveries_new"],
                    res["dispatched"],
                )
            except Exception as exc:
                logger.warning("Error en ciclo Co-Evolution: %s", exc)

            # Heartbeat cada 60s durante la espera
            waited = 0.0
            step = 60.0
            target = max(60.0, float(interval))
            while waited < target and not self._stop_event.is_set():
                chunk = min(step, target - waited)
                self._stop_event.wait(chunk)
                waited += chunk
                if not self._stop_event.is_set():
                    self._state["daemon_heartbeat_ts"] = time.time()
                    self._state["daemon_heartbeat_iso"] = _now_iso()
                    self._save_state()
        return 0


def get_coevolution_engine() -> TardisAgyCoevolution:
    return TardisAgyCoevolution.get_instance()


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-coevolution", description="TARDIS ↔ AGY Continuous Co-Evolution & Discovery Engine")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Estado completo del motor de co-evolución")

    p_scan = sub.add_parser("scan", help="Ejecutar radar de descubrimiento autónomo")
    p_scan.add_argument("--lens", default="all", help="all o lista separada por comas (1..6 o nombres)")

    p_disc = sub.add_parser("discoveries", help="Listar descubrimientos y sistemas alternos propuestos")
    p_disc.add_argument("--status", default="all")
    p_disc.add_argument("--limit", type=int, default=20)

    p_dial = sub.add_parser("dialogue", help="Historial de diálogo bidireccional TARDIS ↔ AGY")
    p_dial.add_argument("--limit", type=int, default=20)

    p_ask = sub.add_parser("ask", help="Enviar consulta o brief desde TARDIS hacia AGY")
    p_ask.add_argument("message", nargs="+")
    p_ask.add_argument("--discovery-id", default="")
    p_ask.add_argument("--live", action="store_true", help="Ejecutar turno síncrono en vivo con AGY")
    p_ask.add_argument("--priority", default="normal")
    p_ask.add_argument("--timeout", type=int, default=300)
    p_ask.add_argument("--model", default=None)
    p_ask.add_argument("--bypass-guards", action="store_true")

    p_rep = sub.add_parser("reply", help="Registrar respuesta/solución desde AGY hacia TARDIS")
    p_rep.add_argument("message", nargs="+")
    p_rep.add_argument("--discovery-id", default="")
    p_rep.add_argument("--status", default="analyzed")
    p_rep.add_argument("--conversation-id", default="")

    p_cyc = sub.add_parser("cycle", help="Ejecutar ciclo completo (radar + triaje + despacho opcional)")
    p_cyc.add_argument("--lens", default="all")
    p_cyc.add_argument("--dispatch", action="store_true")
    p_cyc.add_argument("--live", action="store_true")
    p_cyc.add_argument("--dry-run", action="store_true")

    p_dae = sub.add_parser("daemon", help="Ejecutar demonio 24/7")
    p_dae.add_argument("--interval", type=float, default=1200.0)
    p_dae.add_argument("--no-dispatch", action="store_true")

    args = ap.parse_args()
    eng = get_coevolution_engine()

    if args.cmd == "status":
        print(json.dumps(eng.get_status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "scan":
        lenses = [x.strip() for x in args.lens.split(",") if x.strip()]
        print(json.dumps(eng.scan_discoveries(lenses=lenses), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "discoveries":
        items = eng.list_discoveries(status=args.status, limit=args.limit)
        print(json.dumps({"ok": True, "count": len(items), "discoveries": items}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "dialogue":
        msgs = eng.get_dialogue(limit=args.limit)
        print(json.dumps({"ok": True, "count": len(msgs), "dialogue": msgs}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "ask":
        res = eng.ask_agy(
            " ".join(args.message),
            discovery_id=args.discovery_id,
            mode="live" if args.live else "enqueue",
            priority=args.priority,
            timeout=args.timeout,
            model=args.model,
            bypass_guards=args.bypass_guards,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "reply":
        res = eng.reply_from_agy(
            " ".join(args.message),
            discovery_id=args.discovery_id,
            status=args.status,
            conversation_id=args.conversation_id,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "cycle":
        lenses = [x.strip() for x in args.lens.split(",") if x.strip()]
        res = eng.run_cycle(
            lenses=lenses,
            dispatch=args.dispatch,
            dispatch_mode="live" if args.live else "enqueue",
            dry_run=args.dry_run,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "daemon":
        return eng.run_daemon(interval=args.interval, auto_dispatch=not args.no_dispatch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
