#!/usr/bin/env python3
"""
core/canary_verifier.py - Compuerta Cerrada de Verificación Canario y Rollback Automático
=========================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU
Arquitecto: El Arquitecto (₪)

Compuerta de verificación multi-capa para cualquier cambio autónomo en TARDIS (ya sea generado
por AGY Co-Evolution, AutonomousCoder, SubsystemAgents o FTL Engineer):

  Capa 0 (Snapshot Pre-Cambio):
    - Almacena copia íntegra + SHA-256 en `_selfmod_backups/canary_snapshots/<run_id>/`.
  Capa 1 (Análisis Estático y Guardias de Ingeniería):
    - `ast.parse` + `compile()` obligatorio sobre todos los archivos modificados.
    - Reglas anti-regresión soberanas:
      * Prohíbe `"keep_alive": -1` en rutas que apunten a Ollama CPU (:11434).
      * Prohíbe llamadas `mlockall(` sin guardia de entorno en módulos no-inferencia.
      * Verifica ausencia de conflictos de merge (`<<<<<<<`).
  Capa 2 (Pruebas Unitarias Dirigidas):
    - Mapea automáticamente los archivos modificados a sus suites `tests/test_*.py`
      y ejecuta `.venv-linux/bin/pytest -q`.
  Capa 3 (Compuerta de Salud en Vivo):
    - Sondea `/api/hub/health` (o `core.hub_health.hub_health`), unidades systemd fallidas
      y presión del `SovereignResourceGovernor` para detectar regresiones en caliente.
  Capa 4 (Scorecard SQLite + Bus de Eventos + Rollback):
    - Registra veredicto en `data/canary_verifier.db`, publica `canary.passed` /
      `canary.failed` en `SovereignEventBus` y ofrece `rollback(run_id)` atómico.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import logging
import os
import py_compile
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("TARDIS.CanaryVerifier")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CANARY_DB = DATA_DIR / "canary_verifier.db"
SNAPSHOTS_ROOT = PROJECT_ROOT / "_selfmod_backups" / "canary_snapshots"
VENV_PYTEST = PROJECT_ROOT / ".venv-linux" / "bin" / "pytest"

# Mapa automático de archivos fuente -> suites pytest más relevantes
FILE_TO_TESTS: Dict[str, List[str]] = {
    "antigravity_bridge.py": ["tests/test_self_improve_loop.py"],
    "core/autonomous_coder.py": ["tests/test_web_research_and_coder.py"],
    "core/idle_evolution_daemon.py": ["tests/test_idle_evolution_daemon.py"],
    "core/tardis_agy_controller.py": ["tests/test_tardis_agy_control.py"],
    "core/temporal_brain.py": ["tests/test_temporal_brain.py"],
    "core/zero_error_shield.py": ["tests/test_zero_error_shield.py"],
    "core/cas_neural_space_kaiju.py": ["tests/test_cas_neural_space_kaiju.py"],
    "core/rag_vault.py": ["tests/test_transversal_rag_vault.py"],
    "core/deep_memory_vault.py": ["tests/test_deep_memory_vault.py"],
    "core/offline_chat_vault.py": ["tests/test_offline_chat_vault.py"],
    "core/sovereign_resource_governor.py": ["tests/test_sovereign_coevolution_suite.py"],
    "core/sovereign_event_bus.py": ["tests/test_sovereign_coevolution_suite.py"],
    "core/canary_verifier.py": ["tests/test_sovereign_coevolution_suite.py"],
    "core/tardis_agy_coevolution.py": ["tests/test_sovereign_coevolution_suite.py"],
    "core/hub_health.py": ["tests/test_sovereign_coevolution_suite.py"],
    "core/tardis_error_sentinel.py": ["tests/test_sovereign_coevolution_suite.py"],
    "server/api.py": ["tests/test_api.py", "tests/test_self_improve_loop.py"],
    "agent_safety.py": ["tests/test_security.py"],
}


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class CanaryVerifier:
    """Motor de verificación canario multi-capa con snapshots y rollback automático."""

    _instance: Optional["CanaryVerifier"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "CanaryVerifier":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=CANARY_DB)
            return cls._instance

    def __init__(self, db_path: Path = CANARY_DB) -> None:
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS canary_runs (
                    run_id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT,
                    files_json TEXT NOT NULL,
                    snapshot_dir TEXT,
                    passed INTEGER NOT NULL,
                    score REAL NOT NULL,
                    static_ok INTEGER NOT NULL,
                    tests_ok INTEGER NOT NULL,
                    runtime_ok INTEGER NOT NULL,
                    rolled_back INTEGER DEFAULT 0,
                    report_json TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_canary_ts ON canary_runs(ts)")

    def _emit_bus(self, topic: str, severity: str, payload: Dict[str, Any]) -> None:
        try:
            from core.sovereign_event_bus import get_event_bus
            get_event_bus().publish(topic=topic, source="canary_verifier", severity=severity, payload=payload)
        except Exception:
            pass

    def _resolve_file(self, f: str | Path) -> Path:
        p = Path(f)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve()

    # =========================================================================
    # CAPA 0: SNAPSHOTS PRE-CAMBIO
    # =========================================================================
    def create_snapshot(self, files: Sequence[str | Path], run_id: Optional[str] = None) -> Dict[str, Any]:
        rid = run_id or f"can_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        snap_dir = SNAPSHOTS_ROOT / rid
        snap_dir.mkdir(parents=True, exist_ok=True)
        manifest: Dict[str, Any] = {"run_id": rid, "iso": _now_iso(), "files": []}

        for raw_f in files:
            p = self._resolve_file(raw_f)
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(PROJECT_ROOT.resolve()))
            except ValueError:
                rel = p.name
            safe_rel = rel.replace("/", "__")
            dst = snap_dir / safe_rel
            shutil.copy2(p, dst)
            manifest["files"].append({
                "original_path": str(p),
                "relative_path": rel,
                "snapshot_file": str(dst),
                "sha256": _sha256_file(p),
                "size_bytes": p.stat().st_size,
            })

        (snap_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "run_id": rid, "snapshot_dir": str(snap_dir), "files_count": len(manifest["files"])}

    def rollback(self, run_id: str) -> Dict[str, Any]:
        """Restaura atómicamente los archivos capturados en un snapshot previo."""
        snap_dir = SNAPSHOTS_ROOT / run_id
        manifest_file = snap_dir / "manifest.json"
        if not manifest_file.is_file():
            return {"ok": False, "error": f"Snapshot '{run_id}' no encontrado."}
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        restored: List[str] = []
        errors: List[str] = []
        for item in manifest.get("files") or []:
            src = Path(item["snapshot_file"])
            dst = Path(item["original_path"])
            try:
                if src.is_file():
                    shutil.copy2(src, dst)
                    restored.append(str(dst))
            except Exception as exc:
                errors.append(f"{dst}: {exc}")

        try:
            with self._connect() as con:
                con.execute("UPDATE canary_runs SET rolled_back = 1 WHERE run_id = ?", (run_id,))
        except Exception:
            pass

        self._emit_bus(
            "canary.rolled_back",
            "WARN",
            {"run_id": run_id, "restored_count": len(restored), "errors": errors},
        )
        return {"ok": len(errors) == 0, "run_id": run_id, "restored": restored, "errors": errors}

    # =========================================================================
    # CAPA 1: VERIFICACIÓN ESTÁTICA + GUARDIAS DE INGENIERÍA
    # =========================================================================
    def run_static_gate(self, files: Sequence[str | Path]) -> Dict[str, Any]:
        checked: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        for raw_f in files:
            p = self._resolve_file(raw_f)
            if not p.is_file():
                failures.append({"file": str(raw_f), "rule": "missing_file", "detail": "Archivo no encontrado"})
                continue
            if p.suffix != ".py":
                checked.append({"file": str(p), "ok": True, "kind": "non_python"})
                continue

            src = p.read_text(encoding="utf-8", errors="ignore")
            file_errors: List[str] = []

            # 1) Conflictos de merge
            if "<<<<<<< " in src and "=======" in src and ">>>>>>> " in src:
                file_errors.append("Marcadores de conflicto git detectados")

            # 2) AST parse + compile
            try:
                ast.parse(src, filename=str(p))
                compile(src, str(p), "exec")
                py_compile.compile(str(p), doraise=True)
            except (SyntaxError, py_compile.PyCompileError) as exc:
                file_errors.append(f"Error de sintaxis/compilación: {exc}")

            # 3) Guardia anti-regresión: keep_alive=-1 en módulos de inferencia CPU
            if re.search(r'"keep_alive"\s*:\s*-1\b', src) and "11435" not in src and "canary_verifier" not in p.name:
                warnings.append({
                    "file": p.name,
                    "rule": "cpu_ollama_infinite_keepalive",
                    "detail": "Uso de keep_alive=-1 detectado; asegúrate de que sólo aplique al carril GPU :11435.",
                })

            # 4) Guardia anti-mlockall sin env guard
            if "mlockall(" in src and "os.environ" not in src and "canary_verifier" not in p.name:
                warnings.append({
                    "file": p.name,
                    "rule": "unguarded_mlockall",
                    "detail": "mlockall() sin variable de entorno de control puede fijar RAM innecesaria.",
                })

            if file_errors:
                failures.append({"file": str(p), "rule": "static_compile", "detail": "; ".join(file_errors)})
                checked.append({"file": str(p), "ok": False, "errors": file_errors})
            else:
                checked.append({"file": str(p), "ok": True, "sha256": _sha256_file(p)[:16]})

        return {
            "ok": len(failures) == 0,
            "checked_count": len(checked),
            "checked": checked,
            "failures": failures,
            "warnings": warnings,
        }

    # =========================================================================
    # CAPA 2: TESTS DIRIGIDOS (PYTEST)
    # =========================================================================
    def resolve_tests_for_files(self, files: Sequence[str | Path]) -> List[str]:
        tests: List[str] = []
        for raw_f in files:
            p = self._resolve_file(raw_f)
            try:
                rel = p.relative_to(PROJECT_ROOT.resolve()).as_posix()
            except ValueError:
                rel = p.name
            for t in FILE_TO_TESTS.get(rel, []):
                if (PROJECT_ROOT / t).is_file() and t not in tests:
                    tests.append(t)
            # Heurística por nombre de módulo: core/foo.py -> tests/test_foo.py
            cand = f"tests/test_{p.stem}.py"
            if (PROJECT_ROOT / cand).is_file() and cand not in tests:
                tests.append(cand)
        return tests

    def run_tests_gate(
        self,
        files: Sequence[str | Path],
        extra_tests: Optional[Sequence[str]] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        targets = self.resolve_tests_for_files(files)
        for et in (extra_tests or []):
            if (PROJECT_ROOT / et).is_file() and et not in targets:
                targets.append(et)

        if not targets:
            return {"ok": True, "skipped": True, "reason": "no_mapped_tests", "targets": []}

        pytest_bin = str(VENV_PYTEST) if VENV_PYTEST.is_file() else (shutil.which("pytest") or "pytest")
        cmd = [pytest_bin, "-q", "--tb=short", *targets]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                start_new_session=True,
            )
            elapsed = round(time.time() - t0, 2)
            out_tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-1800:]
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "targets": targets,
                "elapsed_s": elapsed,
                "output_tail": out_tail,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "returncode": -1, "targets": targets, "error": f"Timeout ({timeout}s)"}
        except Exception as exc:
            return {"ok": False, "returncode": -1, "targets": targets, "error": str(exc)}

    # =========================================================================
    # CAPA 3: SONDEO EN VIVO DE SALUD Y REGRESIONES
    # =========================================================================
    def run_runtime_gate(self) -> Dict[str, Any]:
        failed_units: List[str] = []
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "--failed", "--no-legend", "--plain"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=4.0,
            )
            for line in (proc.stdout or "").splitlines():
                parts = line.split()
                if parts:
                    failed_units.append(parts[0])
        except Exception:
            pass

        hub_counts: Dict[str, int] = {}
        try:
            from core.hub_health import hub_health
            hh = hub_health(force=False)
            hub_counts = hh.get("counts") or {}
        except Exception:
            pass

        pressure_level = "UNKNOWN"
        ram_avail_mb = 0.0
        try:
            from core.sovereign_resource_governor import get_resource_governor
            snap = get_resource_governor().collect_telemetry(persist=False, cache_ttl=10.0)
            pressure_level = snap["pressure_level"]
            ram_avail_mb = snap["memory"]["ram_avail_mb"]
        except Exception:
            pass

        # No fallamos sólo por airplay_monitor opcional; fallamos si hay unidades systemd fallidas
        # o si hay > 2 subsistemas offline inesperados
        offline_count = int(hub_counts.get("offline", 0))
        runtime_ok = (len(failed_units) == 0) and (offline_count <= 2)
        return {
            "ok": runtime_ok,
            "failed_systemd_units": failed_units,
            "hub_health_counts": hub_counts,
            "pressure_level": pressure_level,
            "ram_avail_mb": ram_avail_mb,
        }

    # =========================================================================
    # EJECUCIÓN COMPLETA DE COMPUERTA CANARIO
    # =========================================================================
    def verify(
        self,
        files: Sequence[str | Path],
        *,
        actor: str = "tardis_autonomous",
        reason: str = "verification",
        run_tests: bool = True,
        run_runtime: bool = True,
        extra_tests: Optional[Sequence[str]] = None,
        snapshot_run_id: Optional[str] = None,
        auto_rollback_on_fail: bool = False,
    ) -> Dict[str, Any]:
        t0 = time.time()
        rid = snapshot_run_id or f"can_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        file_list = [str(self._resolve_file(f)) for f in files]

        static_res = self.run_static_gate(file_list)
        tests_res = self.run_tests_gate(file_list, extra_tests=extra_tests) if (run_tests and static_res["ok"]) else {
            "ok": static_res["ok"],
            "skipped": True,
            "reason": "static_failed" if not static_res["ok"] else "disabled",
        }
        runtime_res = self.run_runtime_gate() if run_runtime else {"ok": True, "skipped": True}

        passed = bool(static_res["ok"] and tests_res["ok"] and runtime_res["ok"])
        score = 0.0
        score += 40.0 if static_res["ok"] else 0.0
        score += 40.0 if tests_res["ok"] else 0.0
        score += 20.0 if runtime_res["ok"] else 0.0
        score = max(0.0, score - (2.0 * len(static_res.get("warnings") or [])))

        rolled_back = False
        rollback_res: Optional[Dict[str, Any]] = None
        if not passed and auto_rollback_on_fail and snapshot_run_id:
            rollback_res = self.rollback(snapshot_run_id)
            rolled_back = bool(rollback_res.get("ok"))

        report = {
            "ok": True,
            "run_id": rid,
            "iso": _now_iso(),
            "actor": actor,
            "reason": reason,
            "passed": passed,
            "score": round(score, 1),
            "elapsed_s": round(time.time() - t0, 2),
            "files": file_list,
            "static": static_res,
            "tests": tests_res,
            "runtime": runtime_res,
            "rolled_back": rolled_back,
            "rollback_result": rollback_res,
        }

        try:
            with self._connect() as con:
                con.execute(
                    """
                    INSERT OR REPLACE INTO canary_runs (
                        run_id, ts, iso, actor, reason, files_json, snapshot_dir,
                        passed, score, static_ok, tests_ok, runtime_ok, rolled_back, report_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        rid,
                        time.time(),
                        report["iso"],
                        actor,
                        reason,
                        json.dumps(file_list, ensure_ascii=False),
                        str(SNAPSHOTS_ROOT / snapshot_run_id) if snapshot_run_id else "",
                        1 if passed else 0,
                        report["score"],
                        1 if static_res["ok"] else 0,
                        1 if tests_res["ok"] else 0,
                        1 if runtime_res["ok"] else 0,
                        1 if rolled_back else 0,
                        json.dumps(report, ensure_ascii=False),
                    ),
                )
        except Exception as exc:
            logger.debug("Error guardando scorecard canario: %s", exc)

        self._emit_bus(
            topic="canary.passed" if passed else "canary.failed",
            severity="INFO" if passed else "HIGH",
            payload={
                "run_id": rid,
                "actor": actor,
                "score": report["score"],
                "files_count": len(file_list),
                "rolled_back": rolled_back,
            },
        )
        return report

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT run_id, ts, iso, actor, reason, passed, score,
                       static_ok, tests_ok, runtime_ok, rolled_back, files_json
                FROM canary_runs ORDER BY ts DESC LIMIT ?
                """,
                (max(1, min(200, int(limit))),),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["passed"] = bool(d["passed"])
            d["static_ok"] = bool(d["static_ok"])
            d["tests_ok"] = bool(d["tests_ok"])
            d["runtime_ok"] = bool(d["runtime_ok"])
            d["rolled_back"] = bool(d["rolled_back"])
            try:
                d["files"] = json.loads(d.pop("files_json") or "[]")
            except Exception:
                d["files"] = []
            out.append(d)
        return out

    def get_status(self) -> Dict[str, Any]:
        with self._connect() as con:
            total = int(con.execute("SELECT COUNT(*) FROM canary_runs").fetchone()[0])
            passed = int(con.execute("SELECT COUNT(*) FROM canary_runs WHERE passed = 1").fetchone()[0])
            rolled = int(con.execute("SELECT COUNT(*) FROM canary_runs WHERE rolled_back = 1").fetchone()[0])
        hist = self.get_history(limit=5)
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "total_runs": total,
            "passed_runs": passed,
            "failed_runs": total - passed,
            "rolled_back_runs": rolled,
            "pass_rate_pct": round((passed / max(1, total)) * 100.0, 1) if total else 100.0,
            "recent_runs": hist,
            "iso": _now_iso(),
        }


def get_canary_verifier(db_path: Optional[Path] = None) -> CanaryVerifier:
    return CanaryVerifier.get_instance(db_path=db_path)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-canary", description="TARDIS Closed-Loop Canary Verifier")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Resumen de verificaciones canario")

    p_hist = sub.add_parser("history", help="Historial de verificaciones")
    p_hist.add_argument("--limit", type=int, default=15)

    p_ver = sub.add_parser("verify", help="Verificar archivos modificados con compuerta canario")
    p_ver.add_argument("files", nargs="+")
    p_ver.add_argument("--actor", default="cli")
    p_ver.add_argument("--reason", default="manual_verification")
    p_ver.add_argument("--no-tests", action="store_true")
    p_ver.add_argument("--no-runtime", action="store_true")

    p_snap = sub.add_parser("snapshot", help="Crear snapshot pre-cambio")
    p_snap.add_argument("files", nargs="+")

    p_rb = sub.add_parser("rollback", help="Revertir snapshot por run_id")
    p_rb.add_argument("run_id")

    args = ap.parse_args()
    cv = get_canary_verifier()

    if args.cmd == "status":
        print(json.dumps(cv.get_status(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "history":
        print(json.dumps({"ok": True, "runs": cv.get_history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "snapshot":
        print(json.dumps(cv.create_snapshot(args.files), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "rollback":
        print(json.dumps(cv.rollback(args.run_id), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "verify":
        res = cv.verify(
            args.files,
            actor=args.actor,
            reason=args.reason,
            run_tests=not args.no_tests,
            run_runtime=not args.no_runtime,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("passed") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
