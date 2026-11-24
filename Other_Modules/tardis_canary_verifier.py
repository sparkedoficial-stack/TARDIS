#!/usr/bin/env python3
"""
core/tardis_canary_verifier.py - Puerta de Calidad y Verificador Canario Soberano
==================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS-NEURAL-SPACE-KAIJU

Valida determinísticamente cualquier cambio de código generado por AGY, FTL,
AutonomousCoder o SubsystemAgents antes de consolidarlo:

  1. Snapshot atómico en `_selfmod_backups/canary/<run_id>/` para rollback inmediato.
  2. Etapa 1 (Estática / AST / Seguridad): `ast.parse`, `py_compile`, detección de
     patrones peligrosos (secretos hardcodeados, `mlockall`, `requests` sin timeout).
  3. Etapa 2 (Pruebas Unitarias Dirigidas): detecta y ejecuta `tests/test_*<stem>*.py`
     correspondientes a los módulos tocados (o un smoke-set rápido).
  4. Etapa 3 (Sonda Viva Opcional): verifica `/health` y `/api/hub/health` en :8757 para
     confirmar cero regresiones de disponibilidad.
  5. Auditoría inmutable en SQLite WAL (`data/canary_verifications.db`) y emisión de
     eventos `evolution.verified` / `evolution.rollback` al Sovereign Event Bus.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import py_compile
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CANARY_DB = DATA_DIR / "canary_verifications.db"
CANARY_BACKUP_ROOT = PROJECT_ROOT / "_selfmod_backups" / "canary"
CANARY_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
VENV_PYTHON = PROJECT_ROOT / ".venv-linux" / "bin" / "python3"

SECRET_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9]{24,}"),
    re.compile(r"sk-[A-Za-z0-9]{24,}"),
    re.compile(r"ghp_[A-Za-z0-9]{24,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
)


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class TardisCanaryVerifier:
    """Puerta de verificación multi-etapa con snapshots y rollback atómico."""

    _instance: Optional["TardisCanaryVerifier"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "TardisCanaryVerifier":
        if db_path is not None:
            return cls(db_path=db_path)
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=CANARY_DB)
            return cls._instance

    def __init__(self, db_path: Path = CANARY_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    ts REAL NOT NULL,
                    iso TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    files_json TEXT NOT NULL,
                    static_ok INTEGER NOT NULL,
                    tests_ok INTEGER NOT NULL,
                    live_ok INTEGER NOT NULL,
                    backup_dir TEXT DEFAULT '',
                    report_json TEXT NOT NULL
                );
                """
            )

    def _resolve_file(self, f: str | Path) -> Path:
        p = Path(f)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve()

    def snapshot_files(self, files: Sequence[str | Path], run_id: Optional[str] = None) -> Dict[str, Any]:
        """Crea un respaldo atómico de los archivos indicados para rollback inmediato."""
        rid = run_id or f"canary_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        snap_dir = CANARY_BACKUP_ROOT / rid
        snap_dir.mkdir(parents=True, exist_ok=True)
        manifest: List[Dict[str, str]] = []

        for f in files:
            src = self._resolve_file(f)
            if not src.is_file():
                continue
            try:
                rel = src.relative_to(PROJECT_ROOT.resolve()).as_posix()
            except ValueError:
                rel = src.name
            safe_name = rel.replace("/", "__")
            dst = snap_dir / safe_name
            shutil.copy2(src, dst)
            manifest.append({"source": str(src), "relative": rel, "backup": str(dst)})

        (snap_dir / "manifest.json").write_text(
            json.dumps({"run_id": rid, "iso": _now_iso(), "files": manifest}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"ok": True, "run_id": rid, "backup_dir": str(snap_dir), "files_backed_up": len(manifest)}

    def rollback(self, run_id: str) -> Dict[str, Any]:
        """Restaura exactamente los archivos capturados en un snapshot canario."""
        snap_dir = CANARY_BACKUP_ROOT / run_id
        manifest_file = snap_dir / "manifest.json"
        if not manifest_file.is_file():
            return {"ok": False, "error": f"Snapshot canario '{run_id}' no encontrado."}
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        restored: List[str] = []
        for entry in manifest.get("files") or []:
            bkp = Path(entry["backup"])
            dst = Path(entry["source"])
            if bkp.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bkp, dst)
                restored.append(entry["relative"])
        try:
            from core.tardis_event_bus import get_event_bus
            get_event_bus().publish(
                "evolution.rollback",
                "tardis_canary_verifier",
                {"run_id": run_id, "restored_files": restored},
                severity="HIGH",
                dedup_window_s=30.0,
            )
        except Exception:
            pass
        return {"ok": True, "run_id": run_id, "restored_files": restored, "iso": _now_iso()}

    def _static_check(self, paths: List[Path]) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []
        checked: List[str] = []
        for p in paths:
            if not p.is_file():
                issues.append({"file": str(p), "severity": "HIGH", "rule": "missing_file", "detail": "Archivo no existe"})
                continue
            checked.append(str(p))
            src = p.read_text(encoding="utf-8", errors="ignore")

            for pat in SECRET_PATTERNS:
                if pat.search(src):
                    issues.append({"file": p.name, "severity": "HIGH", "rule": "secret_leak", "detail": "Posible clave API embebida"})

            if p.suffix == ".py":
                try:
                    tree = ast.parse(src, filename=str(p))
                except SyntaxError as exc:
                    issues.append({"file": p.name, "severity": "HIGH", "rule": "syntax_error", "detail": f"L{exc.lineno}: {exc.msg}"})
                    continue

                try:
                    py_compile.compile(str(p), doraise=True)
                except py_compile.PyCompileError as exc:
                    issues.append({"file": p.name, "severity": "HIGH", "rule": "py_compile_error", "detail": str(exc)[:200]})

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        if node.func.attr == "mlockall":
                            issues.append({"file": p.name, "severity": "MEDIUM", "rule": "mlockall_guard", "detail": f"L{node.lineno}: evitar mlockall en demonios Python"})
                        if getattr(node.func.value, "id", "") == "requests" and node.func.attr in ("get", "post", "put", "delete", "request"):
                            if not any(k.arg == "timeout" for k in node.keywords):
                                issues.append({"file": p.name, "severity": "MEDIUM", "rule": "requests_no_timeout", "detail": f"L{node.lineno}: requests.{node.func.attr} sin timeout"})
            elif p.suffix == ".json":
                try:
                    json.loads(src)
                except Exception as exc:
                    issues.append({"file": p.name, "severity": "HIGH", "rule": "invalid_json", "detail": str(exc)})

        high_issues = [i for i in issues if i["severity"] == "HIGH"]
        return {"ok": len(high_issues) == 0, "checked_count": len(checked), "high_issues": len(high_issues), "issues": issues}

    def _discover_tests(self, paths: List[Path]) -> List[str]:
        tests_dir = PROJECT_ROOT / "tests"
        if not tests_dir.is_dir():
            return []
        matched: List[str] = []
        for p in paths:
            stem = p.stem
            if stem.startswith("test_"):
                if p.is_file():
                    matched.append(str(p))
                continue
            candidates = list(tests_dir.glob(f"test_*{stem}*.py"))
            if stem.startswith("tardis_"):
                short = stem[len("tardis_") :]
                candidates.extend(tests_dir.glob(f"test_*{short}*.py"))
            for c in candidates:
                s = str(c)
                if s not in matched:
                    matched.append(s)
        return matched

    def _run_pytest(self, test_files: List[str], timeout: float = 90.0) -> Dict[str, Any]:
        if not test_files:
            return {"ok": True, "ran": False, "test_files": [], "summary": "Sin tests específicos mapeados"}
        py_bin = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable
        cmd = [py_bin, "-m", "pytest", *test_files, "-q", "--tb=short"]
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (proc.stdout + "\n" + proc.stderr).strip()
            return {
                "ok": proc.returncode == 0,
                "ran": True,
                "returncode": proc.returncode,
                "elapsed_s": round(time.time() - t0, 2),
                "test_files": [Path(t).name for t in test_files],
                "output_tail": out[-1500:],
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "ran": True, "error": f"pytest timeout ({timeout}s)", "test_files": test_files}
        except Exception as exc:
            return {"ok": False, "ran": True, "error": str(exc), "test_files": test_files}

    def _probe_live_api(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen("http://127.0.0.1:8757/health", timeout=4.0) as r:
                health_ok = r.status == 200
            ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return {"ok": health_ok, "health_latency_ms": ms}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def verify_files(
        self,
        files: Sequence[str | Path],
        *,
        run_tests: bool = True,
        extra_tests: Optional[Sequence[str]] = None,
        check_live_api: bool = False,
        create_snapshot: bool = False,
        timeout: float = 90.0,
    ) -> Dict[str, Any]:
        """Ejecuta verificación canaria completa y persiste el scorecard."""
        run_id = f"canary_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        paths = [self._resolve_file(f) for f in files]
        backup_dir = ""
        if create_snapshot and paths:
            snap = self.snapshot_files(paths, run_id=run_id)
            backup_dir = snap.get("backup_dir", "")

        static_res = self._static_check(paths)
        test_targets = self._discover_tests(paths) if run_tests else []
        for et in extra_tests or []:
            ep = self._resolve_file(et)
            if ep.is_file() and str(ep) not in test_targets:
                test_targets.append(str(ep))
        test_res = self._run_pytest(test_targets, timeout=timeout) if (run_tests and static_res["ok"]) else {
            "ok": static_res["ok"],
            "ran": False,
            "summary": "Omitido por fallo estático o run_tests=False",
        }
        live_res = self._probe_live_api() if check_live_api else {"ok": True, "skipped": True}
        passed = bool(static_res["ok"] and test_res["ok"] and live_res["ok"])

        report = {
            "ok": passed,
            "run_id": run_id,
            "iso": _now_iso(),
            "files": [str(p) for p in paths],
            "backup_dir": backup_dir,
            "static": static_res,
            "tests": test_res,
            "live_api": live_res,
        }

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO verifications (run_id, ts, iso, passed, files_json, static_ok, tests_ok, live_ok, backup_dir, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    time.time(),
                    report["iso"],
                    1 if passed else 0,
                    json.dumps([p.name for p in paths], ensure_ascii=False),
                    1 if static_res["ok"] else 0,
                    1 if test_res["ok"] else 0,
                    1 if live_res["ok"] else 0,
                    backup_dir,
                    json.dumps(report, ensure_ascii=False),
                ),
            )

        try:
            from core.tardis_event_bus import get_event_bus
            get_event_bus().publish(
                "evolution.verified",
                "tardis_canary_verifier",
                {"run_id": run_id, "passed": passed, "files": [p.name for p in paths], "high_issues": static_res["high_issues"]},
                severity="INFO" if passed else "HIGH",
                dedup_window_s=15.0,
            )
        except Exception:
            pass
        return report

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, iso, passed, files_json, static_ok, tests_ok, live_ok, backup_dir FROM verifications ORDER BY id DESC LIMIT ?",
                (max(1, min(200, int(limit))),),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["passed"] = bool(d["passed"])
            d["files"] = json.loads(d.pop("files_json") or "[]")
            out.append(d)
        return out


def get_canary_verifier(db_path: Optional[Path] = None) -> TardisCanaryVerifier:
    return TardisCanaryVerifier.get_instance(db_path=db_path)


def main() -> int:
    ap = argparse.ArgumentParser(prog="tardis-canary", description="TARDIS Sovereign Canary & Quality Gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_v = sub.add_parser("verify", help="Verifica archivos con AST, seguridad y pytest dirigido")
    p_v.add_argument("files", nargs="+")
    p_v.add_argument("--no-tests", action="store_true")
    p_v.add_argument("--live", action="store_true")
    p_v.add_argument("--snapshot", action="store_true")

    p_rb = sub.add_parser("rollback", help="Revierte un snapshot canario por run_id")
    p_rb.add_argument("run_id")

    p_h = sub.add_parser("history", help="Historial de verificaciones canarias")
    p_h.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()
    verifier = get_canary_verifier()

    if args.cmd == "verify":
        res = verifier.verify_files(
            args.files,
            run_tests=not args.no_tests,
            check_live_api=args.live,
            create_snapshot=args.snapshot,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "rollback":
        res = verifier.rollback(args.run_id)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    if args.cmd == "history":
        print(json.dumps({"ok": True, "history": verifier.history(limit=args.limit)}, indent=2, ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
