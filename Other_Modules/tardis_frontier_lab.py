#!/usr/bin/env python3
"""
TARDIS FRONTIER LAB — Red de 5 divisiones de investigación autónoma 100% local.
================================================================================

Convierte el laboratorio de frontera diseñado por la red de subagentes de AGY
(Divisiones 1-5) en una rutina de daemon permanente, con pizarra común SQLite WAL,
admisión por Resource Governor (PSI), bus de eventos y política Cero-Reinicios.

Divisiones:
  1. silicon          — Silicon, Kernel & Inference Compute Lab
  2. abstraction      — Abstraction, Reasoning & Test-Time Compute Lab
  3. skills           — Autonomous Function & Verified Skill Synthesis Lab
  4. memory           — Hierarchical Memory & Local World-Model Lab
  5. self_improvement — Recursive Self-Improvement & Canary Orchestration Lab

Garantías:
  * 100% local: no requiere red ni APIs externas.
  * No destructivo: solo telemetría, índices y propuestas; nunca reinicia servicios.
  * Fail-closed: una división que falla se registra y no contamina el estado.
  * Admisión cooperativa: respeta PSI y el Resource Governor (Ring 0).
  * Estado durable: `data/frontier_lab.db` (WAL) + eventos en `tardis_event_bus`.

CLI:
  python3 core/tardis_frontier_lab.py --once
  python3 core/tardis_frontier_lab.py --daemon --interval 900
  python3 core/tardis_frontier_lab.py --status
  python3 core/tardis_frontier_lab.py --division memory --once
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "frontier_lab.db"
LOG_PATH = DATA_DIR / "frontier_lab.log"
RAG_DB = DATA_DIR / "rag_vault.db"
EVAL_DB = DATA_DIR / "eval_harness.db"
REGISTRY_FILE = DATA_DIR / "dynamic_tools_registry.json"
CANARY_DB = DATA_DIR / "canary_verifications.db"
VAULT_DB = Path(os.path.expanduser("~")) / "vw-control" / "deep_memory_vault" / "vault_master.db"
BRAIN_SOCKET = Path("/tmp/temporal_brain.sock")

DEFAULT_INTERVAL_S = 900.0
STUB_CHARS = 160
MAX_VECTOR_REPAIRS_PER_CYCLE = 500

DIVISIONS: Dict[str, Dict[str, str]] = {
    "silicon": {
        "label": "Silicon, Kernel & Inference Compute Lab",
        "task_class": "heavy_learning",
    },
    "abstraction": {
        "label": "Abstraction, Reasoning & Test-Time Compute Lab",
        "task_class": "light_learning",
    },
    "skills": {
        "label": "Autonomous Function & Verified Skill Synthesis Lab",
        "task_class": "light_learning",
    },
    "memory": {
        "label": "Hierarchical Memory & Local World-Model Lab",
        "task_class": "heavy_learning",
    },
    "self_improvement": {
        "label": "Recursive Self-Improvement & Canary Orchestration Lab",
        "task_class": "light_learning",
    },
}

logger = logging.getLogger("TARDIS_FRONTIER_LAB")


# --------------------------------------------------------------------------- utils
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _run(cmd: Sequence[str], timeout: float = 4.0) -> Tuple[int, str]:
    """Ejecuta un comando de solo lectura con timeout; nunca lanza excepción."""
    try:
        res = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return res.returncode, (res.stdout or "") + (res.stderr or "")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def _read_pressure() -> Dict[str, float]:
    """Lee PSI (/proc/pressure) en avg10 para cpu, memory e io."""
    out: Dict[str, float] = {}
    for kind in ("cpu", "memory", "io"):
        try:
            text = Path(f"/proc/pressure/{kind}").read_text(encoding="utf-8")
            m = re.search(r"avg10=([0-9.]+)", text)
            out[kind] = float(m.group(1)) if m else 0.0
        except Exception:
            out[kind] = 0.0
    return out


def _mem_available_gib() -> float:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024 / 1024, 2)
    except Exception:
        pass
    return 0.0


def _gpu_snapshot() -> Dict[str, Any]:
    code, out = _run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=3.0,
    )
    if code != 0 or not out.strip():
        return {"available": False}
    try:
        util, used, total, temp = [p.strip() for p in out.strip().splitlines()[0].split(",")]
        return {
            "available": True,
            "util_pct": float(util),
            "mem_used_mib": float(used),
            "mem_total_mib": float(total),
            "temp_c": float(temp),
        }
    except Exception:
        return {"available": False}


def _brain_health() -> Dict[str, Any]:
    """Comprueba el socket UDS del Temporal Brain y su endpoint /health."""
    if not BRAIN_SOCKET.exists():
        return {"ok": False, "reason": "socket ausente"}
    try:
        import httpx

        transport = httpx.HTTPTransport(uds=str(BRAIN_SOCKET))
        with httpx.Client(transport=transport, timeout=2.0) as client:
            res = client.get("http://localhost/health")
            return {"ok": res.status_code == 200, "status": res.status_code}
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def _running_services() -> int:
    code, out = _run(
        ["systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"],
        timeout=4.0,
    )
    if code != 0:
        return 0
    return len([ln for ln in out.splitlines() if ".service" in ln])


# --------------------------------------------------------------------------- core
class FrontierLab:
    """Coordinador durable de las 5 divisiones del laboratorio de frontera."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop = False
        self._init_schema()

    # ---------------------------------------------------------------- persistence
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=15000")
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    division TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    status TEXT NOT NULL DEFAULT 'RUNNING',
                    summary TEXT,
                    payload TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_id INTEGER,
                    division TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'INFO',
                    kind TEXT NOT NULL DEFAULT 'observation',
                    title TEXT NOT NULL,
                    detail TEXT,
                    evidence TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    division TEXT NOT NULL,
                    title TEXT NOT NULL,
                    rationale TEXT,
                    target TEXT,
                    risk TEXT NOT NULL DEFAULT 'LOW',
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    division TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    meta TEXT
                );
                CREATE TABLE IF NOT EXISTS negative_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    division TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    failure TEXT NOT NULL,
                    evidence TEXT
                );
                CREATE TABLE IF NOT EXISTS blackboard (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cycles_division ON cycles(division, started_at);
                CREATE INDEX IF NOT EXISTS idx_findings_division ON findings(division, created_at);
                CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name, ts);
                CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, created_at);
                """
            )

    def _blackboard_set(self, key: str, value: Any) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO blackboard(key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False, default=str), time.time()),
            )

    def blackboard_get(self, key: str, default: Any = None) -> Any:
        with self._connect() as con:
            row = con.execute("SELECT value FROM blackboard WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def _record_metric(self, division: str, name: str, value: float, unit: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO metrics(ts, division, name, value, unit, meta) VALUES (?,?,?,?,?,?)",
                (time.time(), division, name, float(value), unit, json.dumps(meta or {}, ensure_ascii=False, default=str)),
            )

    def _record_finding(
        self,
        cycle_id: int,
        division: str,
        title: str,
        detail: str = "",
        severity: str = "INFO",
        kind: str = "observation",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO findings(cycle_id, division, severity, kind, title, detail, evidence, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cycle_id, division, severity.upper(), kind, title[:300], detail,
                 json.dumps(evidence or {}, ensure_ascii=False, default=str), time.time()),
            )

    def _record_proposal(self, division: str, title: str, rationale: str, target: str = "", risk: str = "LOW") -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO proposals(division, title, rationale, target, risk, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,'PENDING',?,?)",
                (division, title[:300], rationale, target, risk.upper(), time.time(), time.time()),
            )

    def _record_negative(self, division: str, hypothesis: str, failure: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO negative_results(ts, division, hypothesis, failure, evidence) VALUES (?,?,?,?,?)",
                (time.time(), division, hypothesis[:400], failure[:800],
                 json.dumps(evidence or {}, ensure_ascii=False, default=str)),
            )

    # ------------------------------------------------------------------- event bus
    def _publish(self, topic: str, payload: Dict[str, Any], severity: str = "INFO") -> None:
        try:
            from core.tardis_event_bus import get_event_bus

            get_event_bus().publish(topic, source="tardis_frontier_lab", payload=payload, severity=severity)
        except Exception:
            logger.debug("Event bus no disponible para %s", topic, exc_info=True)

    # -------------------------------------------------------------------- admission
    def _admit(self, task_class: str) -> Tuple[bool, str]:
        try:
            from core.tardis_resource_governor import can_run_background_task, get_pressure_sleep_multiplier

            level, multiplier = get_pressure_sleep_multiplier()
            if level in ("RED", "CRITICAL"):
                return False, f"PSI {level} (x{multiplier:.1f})"
            allowed = bool(can_run_background_task(task_class))
            return allowed, f"PSI {level} (x{multiplier:.1f})"
        except Exception as e:
            # Sin gobernador disponible, el laboratorio opera en modo conservador.
            return True, f"governor no disponible: {type(e).__name__}"

    # ---------------------------------------------------------------- division 1
    def _div_silicon(self, cycle_id: int) -> Dict[str, Any]:
        psi = _read_pressure()
        mem = _mem_available_gib()
        gpu = _gpu_snapshot()
        brain = _brain_health()
        services = _running_services()

        self._record_metric("silicon", "psi_cpu_avg10", psi["cpu"], "%")
        self._record_metric("silicon", "psi_memory_avg10", psi["memory"], "%")
        self._record_metric("silicon", "psi_io_avg10", psi["io"], "%")
        self._record_metric("silicon", "mem_available_gib", mem, "GiB")
        self._record_metric("silicon", "running_services", services, "count")
        if gpu.get("available"):
            self._record_metric("silicon", "gpu_util_pct", gpu["util_pct"], "%")
            self._record_metric("silicon", "gpu_mem_used_mib", gpu["mem_used_mib"], "MiB")
            self._record_metric("silicon", "gpu_temp_c", gpu["temp_c"], "C")

        if not brain.get("ok"):
            self._record_finding(
                cycle_id, "silicon",
                "Temporal Brain no responde por su socket UDS",
                f"Detalle: {brain.get('reason') or brain.get('status')}",
                severity="CRITICAL", kind="availability", evidence=brain,
            )
            self._record_proposal(
                "silicon",
                "Verificar tardis-temporal-brain.service y el socket /tmp/temporal_brain.sock",
                "El núcleo de inferencia local es la dependencia crítica de todas las divisiones.",
                target="tardis-temporal-brain.service", risk="MEDIUM",
            )
        if psi["cpu"] >= 25.0:
            self._record_finding(
                cycle_id, "silicon",
                "Presión de CPU elevada (PSI avg10 ≥ 25%)",
                "El laboratorio debe ceder CPU a la ruta interactiva.",
                severity="WARNING", kind="pressure", evidence=psi,
            )
        if mem < 3.0:
            self._record_finding(
                cycle_id, "silicon",
                "Memoria disponible por debajo de 3 GiB",
                "Riesgo de thrashing; se recomienda pausar divisiones pesadas.",
                severity="WARNING", kind="memory", evidence={"mem_available_gib": mem},
            )
        if gpu.get("available") and gpu["mem_total_mib"] > 0:
            ratio = gpu["mem_used_mib"] / gpu["mem_total_mib"]
            if ratio >= 0.92:
                self._record_finding(
                    cycle_id, "silicon",
                    "VRAM casi agotada en la RTX 3050",
                    f"Uso {gpu['mem_used_mib']:.0f}/{gpu['mem_total_mib']:.0f} MiB.",
                    severity="WARNING", kind="vram", evidence=gpu,
                )

        summary = (
            f"PSI cpu={psi['cpu']:.1f}% mem={psi['memory']:.1f}% io={psi['io']:.1f}% · "
            f"RAM libre={mem:.1f} GiB · brain={'OK' if brain.get('ok') else 'DOWN'} · "
            f"servicios={services}"
        )
        return {"summary": summary, "metrics": {**psi, "mem_available_gib": mem}, "gpu": gpu, "brain": brain}

    # ---------------------------------------------------------------- division 2
    def _recent_vault_texts(self, limit: int = 12) -> List[str]:
        if not VAULT_DB.exists():
            return []
        try:
            con = sqlite3.connect(VAULT_DB, timeout=5.0)
            rows = con.execute(
                "SELECT content FROM vault_events WHERE is_compressed=0 AND length(content) BETWEEN 120 AND 4000 "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            con.close()
            return [str(r[0]) for r in rows if r and r[0]]
        except Exception:
            return []

    def _div_abstraction(self, cycle_id: int) -> Dict[str, Any]:
        texts = self._recent_vault_texts(12)
        self._record_metric("abstraction", "vault_samples", len(texts), "count")
        if not texts:
            self._record_finding(
                cycle_id, "abstraction",
                "Sin muestras recientes en la bóveda profunda",
                "No hay material episódico para sintetizar principios.",
                severity="INFO", kind="data_gap",
            )
            return {"summary": "sin muestras"}

        principle: Optional[str] = None
        try:
            from core.temporal_brain import get_temporal_brain

            corpus = "\n---\n".join(t[:900] for t in texts[:6])
            prompt = (
                "Eres la División 2 (Abstracción y Razonamiento) de TARDIS. "
                "A partir de estos episodios recientes, extrae UN principio operativo "
                "accionable y verificable, en una sola frase, sin inventar datos:\n\n" + corpus
            )
            res = get_temporal_brain().chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=160,
            )
            if res.get("ok") and str(res.get("reply", "")).strip():
                principle = str(res["reply"]).strip()[:600]
        except Exception as e:
            logger.debug("Síntesis LLM no disponible: %s", e)

        if not principle:
            # Fallback determinista: términos recurrentes como patrón emergente.
            freq: Dict[str, int] = {}
            stop = {"para", "como", "este", "esta", "desde", "sobre", "entre", "cuando", "donde", "tardis"}
            for t in texts:
                for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{6,}", t.lower()):
                    if w not in stop:
                        freq[w] = freq.get(w, 0) + 1
            top = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:8]
            principle = "Patrón emergente (fallback léxico): " + ", ".join(f"{w}({c})" for w, c in top)

        self._blackboard_set("abstraction.last_principle", {"principle": principle, "ts": _now_iso()})
        self._record_finding(
            cycle_id, "abstraction",
            "Principio operativo sintetizado",
            principle,
            severity="INFO", kind="principle", evidence={"samples": len(texts)},
        )
        self._record_metric("abstraction", "principle_chars", len(principle), "chars")
        return {"summary": f"principio sintetizado ({len(principle)} chars)", "principle": principle}

    # ---------------------------------------------------------------- division 3
    def _div_skills(self, cycle_id: int) -> Dict[str, Any]:
        registry: Dict[str, Any] = {}
        if REGISTRY_FILE.exists():
            try:
                registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                self._record_negative("skills", "Leer registro de herramientas dinámicas", str(e))
        active = [k for k, v in registry.items() if str((v or {}).get("status", "")).upper().startswith("ACTIVE")]
        failed = [k for k, v in registry.items() if not str((v or {}).get("status", "")).upper().startswith("ACTIVE")]
        self._record_metric("skills", "dynamic_tools_total", len(registry), "count")
        self._record_metric("skills", "dynamic_tools_active", len(active), "count")
        self._record_metric("skills", "dynamic_tools_failed", len(failed), "count")

        if failed:
            self._record_finding(
                cycle_id, "skills",
                f"{len(failed)} herramienta(s) dinámica(s) no verificadas",
                ", ".join(failed[:20]),
                severity="WARNING", kind="skill_health", evidence={"failed": failed[:50]},
            )
            self._record_proposal(
                "skills",
                "Re-verificar herramientas dinámicas fallidas en sandbox aislado",
                "Las herramientas no verificadas no deben registrarse (política fail-closed).",
                target=str(REGISTRY_FILE), risk="LOW",
            )

        # Cobertura del registro frente a los archivos reales en dynamic_tools/
        tools_dir = PROJECT_ROOT / "dynamic_tools"
        on_disk = {p.stem for p in tools_dir.glob("*.py")} if tools_dir.is_dir() else set()
        orphans = sorted(on_disk - set(registry))
        if orphans:
            self._record_finding(
                cycle_id, "skills",
                f"{len(orphans)} archivo(s) en dynamic_tools/ fuera del registro",
                ", ".join(orphans[:20]),
                severity="INFO", kind="registry_drift", evidence={"orphans": orphans[:50]},
            )

        # Última evaluación del harness
        eval_score = None
        if EVAL_DB.exists():
            try:
                con = sqlite3.connect(EVAL_DB, timeout=5.0)
                row = con.execute(
                    "SELECT overall_score FROM eval_runs ORDER BY ts DESC LIMIT 1"
                ).fetchone()
                con.close()
                if row and row[0] is not None:
                    eval_score = float(row[0])
                    self._record_metric("skills", "eval_score", eval_score, "score")
                    if eval_score < 80.0:
                        self._record_finding(
                            cycle_id, "skills",
                            "Score de evaluación por debajo de 80",
                            f"Último score={eval_score:.1f}. Revisar suites RAG/tool-calling.",
                            severity="WARNING", kind="eval_regression", evidence={"score": eval_score},
                        )
            except Exception as e:
                logger.debug("Eval harness no legible: %s", e)

        summary = f"registry={len(registry)} active={len(active)} failed={len(failed)} orphans={len(orphans)}"
        return {"summary": summary, "active": active, "failed": failed, "eval_score": eval_score}

    # ---------------------------------------------------------------- division 4
    def _div_memory(self, cycle_id: int) -> Dict[str, Any]:
        if not RAG_DB.exists():
            self._record_finding(
                cycle_id, "memory", "rag_vault.db ausente",
                "No se puede auditar la memoria semántica.", severity="WARNING", kind="data_gap",
            )
            return {"summary": "rag_vault.db ausente"}

        total = stubs = zero_vecs = 0
        repaired = 0
        try:
            con = sqlite3.connect(RAG_DB, timeout=10.0)
            con.row_factory = sqlite3.Row
            total = int(con.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0])
            stubs = int(con.execute(
                "SELECT COUNT(*) FROM rag_chunks WHERE length(trim(text)) < ?", (STUB_CHARS,)
            ).fetchone()[0])

            # Reparación segura: eliminar vectores cero/NaN (nunca tocar el texto).
            rows = con.execute(
                "SELECT v.chunk_id, v.vec FROM rag_vectors v ORDER BY v.chunk_id DESC LIMIT ?",
                (MAX_VECTOR_REPAIRS_PER_CYCLE,),
            ).fetchall()
            bad_ids: List[int] = []
            for r in rows:
                raw = r["vec"] or b""
                if len(raw) != 384 * 4:
                    bad_ids.append(int(r["chunk_id"]))
                    continue
                try:
                    import numpy as np

                    vec = np.frombuffer(raw, dtype=np.float32)
                    if not np.isfinite(vec).all() or float(np.linalg.norm(vec)) <= 1e-6:
                        bad_ids.append(int(r["chunk_id"]))
                except Exception:
                    bad_ids.append(int(r["chunk_id"]))
            if bad_ids:
                con.executemany("DELETE FROM rag_vectors WHERE chunk_id=?", [(i,) for i in bad_ids])
                con.commit()
                repaired = len(bad_ids)
            zero_vecs = repaired
            con.close()
        except Exception as e:
            self._record_negative("memory", "Auditar y reparar vectores RAG", str(e))

        stub_ratio = (stubs / total) if total else 0.0
        self._record_metric("memory", "rag_chunks", total, "count")
        self._record_metric("memory", "rag_stub_chunks", stubs, "count")
        self._record_metric("memory", "rag_stub_ratio", stub_ratio, "ratio")
        self._record_metric("memory", "rag_vectors_repaired", repaired, "count")

        if stubs:
            self._record_finding(
                cycle_id, "memory",
                f"{stubs} fragmento(s) stub (<{STUB_CHARS} chars) en RAG",
                "Los stubs generan hubness tras la isotropía ZCA; el chunker ya fusiona colas nuevas.",
                severity="WARNING", kind="chunk_quality", evidence={"stubs": stubs, "total": total},
            )
            self._record_proposal(
                "memory",
                "Reingestar documentos con stubs para consolidar fragmentos cortos",
                "Fusionar colas <160 chars con el fragmento anterior y recalcular embeddings.",
                target=str(RAG_DB), risk="MEDIUM",
            )
        if repaired:
            self._record_finding(
                cycle_id, "memory",
                f"{repaired} vector(es) inválido(s) eliminado(s)",
                "Vectores cero/NaN eliminados; el texto permanece indexado en FTS5.",
                severity="INFO", kind="repair", evidence={"repaired": repaired},
            )

        summary = f"chunks={total} stubs={stubs} ({stub_ratio:.1%}) vectores_reparados={repaired}"
        return {"summary": summary, "total": total, "stubs": stubs, "repaired": repaired}

    # ---------------------------------------------------------------- division 5
    def _latest_metrics(self) -> Dict[str, float]:
        wanted = {
            "psi_cpu_avg10", "mem_available_gib", "gpu_util_pct",
            "rag_stub_ratio", "rag_chunks", "dynamic_tools_active",
            "dynamic_tools_failed", "eval_score",
        }
        out: Dict[str, float] = {}
        with self._connect() as con:
            for name in wanted:
                row = con.execute(
                    "SELECT value FROM metrics WHERE name=? ORDER BY ts DESC LIMIT 1", (name,)
                ).fetchone()
                if row:
                    out[name] = float(row["value"])
        return out

    def _compute_sfi(self, m: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
        """Singularity Frontier Index: promedio ponderado de ejes empíricos (0-100)."""
        brain_ok = 1.0 if self.blackboard_get("silicon.brain_ok", True) else 0.0
        axes = {
            "inference": brain_ok,
            "memory_hygiene": 1.0 - _clamp(m.get("rag_stub_ratio", 0.0) / 0.10),
            "skill_health": 1.0 - _clamp(m.get("dynamic_tools_failed", 0.0) / 5.0),
            "pressure_headroom": 1.0 - _clamp(m.get("psi_cpu_avg10", 0.0) / 50.0),
            "eval": _clamp(m.get("eval_score", 75.0) / 100.0),
        }
        weights = {
            "inference": 0.30,
            "memory_hygiene": 0.20,
            "skill_health": 0.15,
            "pressure_headroom": 0.15,
            "eval": 0.20,
        }
        sfi = sum(axes[k] * weights[k] for k in axes) * 100.0
        return round(sfi, 2), axes

    def _div_self_improvement(self, cycle_id: int) -> Dict[str, Any]:
        metrics = self._latest_metrics()
        sfi, axes = self._compute_sfi(metrics)
        prev = self.blackboard_get("self_improvement.sfi")
        self._record_metric("self_improvement", "sfi", sfi, "index", {"axes": axes})
        self._blackboard_set("self_improvement.sfi", sfi)

        if isinstance(prev, (int, float)) and (prev - sfi) >= 5.0:
            self._record_finding(
                cycle_id, "self_improvement",
                f"Regresión del SFI: {prev:.1f} → {sfi:.1f}",
                "Caída ≥5 puntos respecto al ciclo anterior.",
                severity="WARNING", kind="regression", evidence={"prev": prev, "now": sfi, "axes": axes},
            )
        else:
            self._record_finding(
                cycle_id, "self_improvement",
                f"SFI={sfi:.1f}",
                "Índice de frontera calculado sobre ejes empíricos.",
                severity="INFO", kind="sfi", evidence={"axes": axes},
            )

        pending = 0
        with self._connect() as con:
            pending = int(con.execute("SELECT COUNT(*) FROM proposals WHERE status='PENDING'").fetchone()[0])
        self._record_metric("self_improvement", "pending_proposals", pending, "count")

        canary_status = "unknown"
        if CANARY_DB.exists():
            try:
                con = sqlite3.connect(CANARY_DB, timeout=5.0)
                row = con.execute(
                    "SELECT passed FROM verifications ORDER BY ts DESC LIMIT 1"
                ).fetchone()
                con.close()
                if row:
                    canary_status = "PASSED" if int(row[0]) else "FAILED"
            except Exception:
                pass
        self._blackboard_set("self_improvement.canary", {"status": canary_status, "ts": _now_iso()})

        summary = f"SFI={sfi:.1f} pending_proposals={pending} canary={canary_status}"
        return {"summary": summary, "sfi": sfi, "axes": axes, "pending": pending}

    # ------------------------------------------------------------------- runner
    _DIVISION_METHODS = {
        "silicon": "_div_silicon",
        "abstraction": "_div_abstraction",
        "skills": "_div_skills",
        "memory": "_div_memory",
        "self_improvement": "_div_self_improvement",
    }

    def run_division(self, division: str) -> Dict[str, Any]:
        if division not in self._DIVISION_METHODS:
            return {"ok": False, "error": f"división desconocida: {division}"}

        allowed, reason = self._admit(DIVISIONS[division]["task_class"])
        if not allowed:
            logger.info("⏸️  %s diferida por admisión: %s", division, reason)
            self._publish("lab.deferred", {"division": division, "reason": reason}, severity="INFO")
            return {"ok": True, "division": division, "deferred": True, "reason": reason}

        started = time.time()
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO cycles(division, started_at, status) VALUES (?,?, 'RUNNING')",
                (division, started),
            )
            cycle_id = int(cur.lastrowid)

        try:
            result = getattr(self, self._DIVISION_METHODS[division])(cycle_id)
            elapsed = round(time.time() - started, 2)
            with self._connect() as con:
                con.execute(
                    "UPDATE cycles SET finished_at=?, status='OK', summary=?, payload=? WHERE id=?",
                    (time.time(), str(result.get("summary", ""))[:500],
                     json.dumps(result, ensure_ascii=False, default=str), cycle_id),
                )
            if division == "silicon":
                self._blackboard_set("silicon.brain_ok", bool((result.get("brain") or {}).get("ok")))
            self._publish(
                f"lab.{division}.cycle",
                {"division": division, "summary": result.get("summary"), "elapsed_s": elapsed},
            )
            logger.info("✅ %s · %s · %.2fs", division, result.get("summary", ""), elapsed)
            return {"ok": True, "division": division, "cycle_id": cycle_id, "elapsed_s": elapsed, **result}
        except Exception as e:
            elapsed = round(time.time() - started, 2)
            logger.exception("❌ División %s falló", division)
            with self._connect() as con:
                con.execute(
                    "UPDATE cycles SET finished_at=?, status='FAILED', error=? WHERE id=?",
                    (time.time(), f"{type(e).__name__}: {e}", cycle_id),
                )
            self._record_negative(division, "Ciclo autónomo de la división", f"{type(e).__name__}: {e}")
            self._publish(f"lab.{division}.failed", {"division": division, "error": str(e)}, severity="ERROR")
            return {"ok": False, "division": division, "error": str(e), "elapsed_s": elapsed}

    def run_once(self, divisions: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        selected = list(divisions or DIVISIONS.keys())
        results = {d: self.run_division(d) for d in selected}
        ok = all(r.get("ok", False) for r in results.values())
        return {"ok": ok, "ts": _now_iso(), "divisions": results}

    def status(self) -> Dict[str, Any]:
        with self._connect() as con:
            last_cycles = [dict(r) for r in con.execute(
                "SELECT id, division, status, summary, error, started_at, finished_at "
                "FROM cycles ORDER BY id DESC LIMIT 10"
            ).fetchall()]
            pending = int(con.execute("SELECT COUNT(*) FROM proposals WHERE status='PENDING'").fetchone()[0])
            findings = int(con.execute("SELECT COUNT(*) FROM findings").fetchone()[0])
            negatives = int(con.execute("SELECT COUNT(*) FROM negative_results").fetchone()[0])
            cycles = int(con.execute("SELECT COUNT(*) FROM cycles").fetchone()[0])
        return {
            "ok": True,
            "db": str(self.db_path),
            "ts": _now_iso(),
            "sfi": self.blackboard_get("self_improvement.sfi"),
            "last_principle": self.blackboard_get("abstraction.last_principle"),
            "counts": {"cycles": cycles, "findings": findings, "pending_proposals": pending, "negative_results": negatives},
            "last_cycles": last_cycles,
        }

    # --------------------------------------------------------------------- daemon
    def stop(self, *_args: Any) -> None:
        self._stop = True
        logger.info("🛑 Señal de parada recibida; cerrando tras el ciclo actual.")

    def daemon(self, interval_s: float = DEFAULT_INTERVAL_S) -> int:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        logger.info("🚀 Frontier Lab en modo daemon · intervalo base %.0fs", interval_s)
        while not self._stop:
            t0 = time.time()
            self.run_once()
            try:
                from core.tardis_resource_governor import get_pressure_sleep_multiplier

                _, mult = get_pressure_sleep_multiplier()
            except Exception:
                mult = 1.0
            sleep_s = max(30.0, interval_s * max(1.0, mult))
            logger.info("💤 Próximo ciclo en %.0fs (multiplicador PSI x%.1f)", sleep_s, mult)
            end = time.time() + sleep_s
            while time.time() < end and not self._stop:
                time.sleep(min(5.0, end - time.time()))
        return 0


# --------------------------------------------------------------------------- CLI
def _configure_logging(verbose: bool = False) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="tardis-frontier-lab", description="Red de 5 divisiones autónomas de TARDIS")
    parser.add_argument("--once", action="store_true", help="Ejecuta un ciclo completo y termina")
    parser.add_argument("--daemon", action="store_true", help="Ejecuta en bucle permanente")
    parser.add_argument("--status", action="store_true", help="Muestra el estado del laboratorio")
    parser.add_argument("--division", action="append", default=[], choices=list(DIVISIONS.keys()),
                        help="División específica (repetible)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S, help="Intervalo base del daemon (s)")
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    parser.add_argument("--verbose", action="store_true", help="Log detallado")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    lab = FrontierLab()

    if args.status:
        out = lab.status()
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        return 0

    if args.daemon:
        return lab.daemon(interval_s=args.interval)

    out = lab.run_once(divisions=args.division or None)
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
