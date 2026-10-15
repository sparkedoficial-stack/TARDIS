"""
core/tardis_ftl_engineer.py - Motor de Ingeniería de Software Autónomo FTL para TARDIS
======================================================================================
Permite a TARDIS (GODWORKS SYSTEM v26.4) acceder directamente a la capacidad de
creación y modificación de software de FTL (~/.ftl/ftl_cli.py) para auto-mejorarse,
crear herramientas, refactorizar código y reparar subsistemas de forma 100% autónoma,
sin supervisión ni petición de permisos.

Capacidades:
  1. execute_software_creation: Genera scripts, módulos o software mediante FTL
     (Claude Code / Antigravity / Dual-Synth / Dual-Audit).
  2. apply_improvement_proposal: Toma una propuesta de mejora de la cola
     (~/vw-control/improvement_queue/), la implementa en el codebase y la valida.
  3. process_pending_improvements: Procesa iterativamente las propuestas pendientes.
  4. run_autonomous_self_improvement_cycle: Ciclo cerrado completo (detección de
     señales -> generación de propuesta -> implementación autónoma con FTL ->
     validación de sintaxis -> registro en DeepMemoryVault).
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("TARDIS_FTL_ENGINEER")

PROJECT_DIR = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM").resolve()
FTL_CLI = Path.home() / ".ftl" / "ftl_cli.py"
FTL_BIN = Path.home() / ".local" / "bin" / "ftl"
QUEUE_DIR = Path.home() / "vw-control" / "improvement_queue"
PROCESSED_DIR = QUEUE_DIR / "processed"
LOGS_DIR = Path.home() / "vw-control" / "ftl_engineer_logs"

QUEUE_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT_SEC = 1800  # 30 minutos por tarea


@dataclass
class FtlEngineerJob:
    job_id: str
    prompt: str
    mode: str
    cwd: Path
    log_path: Path
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    returncode: Optional[int] = None
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, TIMEOUT, CANCELLED
    files_changed: List[str] = field(default_factory=list)
    output_tail: List[str] = field(default_factory=list)
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    process: Optional[subprocess.Popen] = None


class TardisFtlEngineer:
    """Núcleo Autónomo de Ingeniería de Software FTL para TARDIS."""

    _instance: Optional["TardisFtlEngineer"] = None
    _init_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TardisFtlEngineer":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.Lock()
        self.current_job: Optional[FtlEngineerJob] = None
        self.last_completed_job: Optional[Dict[str, Any]] = None
        self.total_jobs_run = 0
        self.total_improvements_applied = 0

    def is_ftl_available(self) -> bool:
        """Verifica que el motor FTL esté presente y accesible."""
        return FTL_CLI.is_file() or FTL_BIN.is_file()

    def get_status(self) -> Dict[str, Any]:
        """Retorna el estado operativo actual del Ingeniero FTL."""
        with self._lock:
            active = None
            if self.current_job:
                elapsed = round(time.time() - self.current_job.started_at, 1)
                active = {
                    "job_id": self.current_job.job_id,
                    "prompt": self.current_job.prompt[:200],
                    "mode": self.current_job.mode,
                    "status": self.current_job.status,
                    "elapsed_sec": elapsed,
                    "log_path": str(self.current_job.log_path),
                }

            # Contar propuestas pendientes (archivos .md directos en QUEUE_DIR)
            pending_files = [
                p.name for p in QUEUE_DIR.glob("*.md")
                if p.is_file() and not p.name.startswith(".")
            ]
            processed_files = [
                p.name for p in PROCESSED_DIR.glob("*.md")
                if p.is_file() and not p.name.startswith(".")
            ]

            return {
                "ok": True,
                "ftl_available": self.is_ftl_available(),
                "ftl_cli_path": str(FTL_CLI),
                "active_job": active,
                "total_jobs_run": self.total_jobs_run,
                "total_improvements_applied": self.total_improvements_applied,
                "pending_improvements_count": len(pending_files),
                "pending_improvements": pending_files[:10],
                "processed_improvements_count": len(processed_files),
                "last_completed_job": self.last_completed_job,
            }

    def _snapshot_filesystem(self, target_dir: Path) -> Dict[str, float]:
        """Captura mtime de archivos en target_dir y subdirectorios clave para detectar cambios."""
        snap = {}
        try:
            for p in list(target_dir.glob("*.py")) + list(target_dir.glob("core/*.py")):
                if p.is_file():
                    try:
                        snap[str(p.relative_to(target_dir))] = p.stat().st_mtime
                    except Exception:
                        pass
        except Exception:
            pass
        return snap

    def _detect_changed_files(self, target_dir: Path, before_snap: Dict[str, float]) -> List[str]:
        """Detecta qué archivos sufrieron modificaciones."""
        changed = []
        try:
            # 1. Comprobar git status
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        changed.append(parts[1])
        except Exception:
            pass

        # 2. Comprobar mtimes
        after_snap = self._snapshot_filesystem(target_dir)
        for rel_path, mtime in after_snap.items():
            if rel_path not in before_snap or abs(before_snap[rel_path] - mtime) > 0.001:
                if rel_path not in changed:
                    changed.append(rel_path)

        return sorted(list(set(changed)))

    def _validate_python_syntax(self, target_dir: Path, files: List[str]) -> Tuple[bool, List[str]]:
        """Verifica que los archivos .py modificados no tengan errores sintácticos."""
        errors = []
        for rel_path in files:
            if rel_path.endswith(".py"):
                full_path = target_dir / rel_path
                if full_path.is_file():
                    try:
                        code = full_path.read_text(encoding="utf-8", errors="ignore")
                        ast.parse(code, filename=str(full_path))
                    except SyntaxError as se:
                        errors.append(f"{rel_path}: SyntaxError línea {se.lineno}: {se.msg}")
                    except Exception as e:
                        errors.append(f"{rel_path}: Error de análisis: {e}")
        return len(errors) == 0, errors

    def _record_in_vault(self, job: FtlEngineerJob, summary: str, duration: float) -> None:
        """Registra el evento de ingeniería en la Bóveda de Memoria Profunda de TARDIS."""
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            action_desc = f"[TARDIS FTL ENGINEER :: {job.mode.upper()}] (RC: {job.returncode})"
            content = (
                f"{action_desc}\n"
                f"• Job ID: {job.job_id}\n"
                f"• Prompt/Tarea: {job.prompt[:400]}\n"
                f"• Duración: {duration:.2f}s | Estado: {job.status}\n"
                f"• Archivos Modificados: {', '.join(job.files_changed) if job.files_changed else 'Ninguno'}\n"
                f"--- RESUMEN DE SALIDA ---\n"
                f"{summary[:3000]}"
            )
            vault.ingest(
                source="tardis_ftl_engineer",
                role="assistant" if job.returncode == 0 else "system",
                content=content,
                session_id="ftl_autonomous_engineering",
                meta={
                    "job_id": job.job_id,
                    "mode": job.mode,
                    "status": job.status,
                    "returncode": job.returncode,
                    "duration": duration,
                    "files_changed": job.files_changed,
                    **job.meta,
                },
                importance=2.0 if job.files_changed else 1.2,
            )
        except Exception as e:
            logger.warning(f"No se pudo registrar en DeepMemoryVault: {e}")

    def execute_software_creation(
        self,
        prompt: str,
        mode: str = "auto",
        cwd: Optional[Path] = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
        background: bool = False,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta una orden de creación o modificación de software a través de FTL.
        Si background=True, se ejecuta en un hilo desacoplado y retorna el job_id.
        Si background=False, espera la finalización y retorna el resultado detallado.
        """
        if not self.is_ftl_available():
            return {"ok": False, "error": f"FTL no disponible en {FTL_CLI}"}

        target_cwd = (cwd or PROJECT_DIR).resolve()
        job_id = f"ftl_eng_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
        log_file = LOGS_DIR / f"{job_id}.log"

        job = FtlEngineerJob(
            job_id=job_id,
            prompt=prompt,
            mode=mode,
            cwd=target_cwd,
            log_path=log_file,
            meta=meta or {},
        )

        with self._lock:
            if self.current_job and self.current_job.status == "RUNNING":
                return {
                    "ok": False,
                    "error": f"FTL Engineer ya está ejecutando la tarea {self.current_job.job_id}",
                    "active_job_id": self.current_job.job_id,
                }
            self.current_job = job

        if background:
            thread = threading.Thread(
                target=self._run_job_sync,
                args=(job, timeout_sec),
                name=f"FtlEngThread-{job_id}",
                daemon=True,
            )
            thread.start()
            return {
                "ok": True,
                "status": "RUNNING",
                "job_id": job_id,
                "mode": mode,
                "log_path": str(log_file),
                "cwd": str(target_cwd),
                "message": "Tarea de ingeniería de software FTL iniciada en segundo plano.",
            }

        return self._run_job_sync(job, timeout_sec)

    def _run_job_sync(self, job: FtlEngineerJob, timeout_sec: int) -> Dict[str, Any]:
        """Ejecuta el proceso FTL de forma síncrona dentro del hilo."""
        job.status = "RUNNING"
        t_start = time.time()
        before_snap = self._snapshot_filesystem(job.cwd)

        # Inyectar invariante soberano
        sovereign_prompt = (
            "[MANDATO GLOBAL SOBERANO TARDIS :: CREACIÓN AUTÓNOMA DE SOFTWARE]\n"
            "- Operación 100% autónoma sin supervisión ni solicitud de permisos.\n"
            "- Aplica cambios concretos en el código y verifica la integridad.\n\n"
            f"{job.prompt}"
        )

        cmd = [sys.executable, str(FTL_CLI)]
        if job.mode and job.mode != "auto":
            cmd += ["-m", job.mode]
        cmd += ["--", sovereign_prompt]

        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "CLAUDE_CODE_SKIP_PERMISSIONS": "1",
            "COLUMNS": "120",
        })

        full_output = []
        try:
            with open(job.log_path, "w", encoding="utf-8") as lf:
                lf.write(f"=== TARDIS FTL ENGINEER JOB {job.job_id} ===\n")
                lf.write(f"Timestamp: {datetime.now().isoformat()}\n")
                lf.write(f"CWD: {job.cwd}\n")
                lf.write(f"Mode: {job.mode}\n")
                lf.write(f"Prompt:\n{job.prompt}\n")
                lf.write("=" * 60 + "\n\n")

                proc = subprocess.Popen(
                    cmd,
                    cwd=str(job.cwd),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    preexec_fn=os.setsid if os.name != "nt" else None,
                )
                job.process = proc

                for line in proc.stdout:
                    full_output.append(line)
                    lf.write(line)
                    lf.flush()
                    if len(job.output_tail) > 30:
                        job.output_tail.pop(0)
                    job.output_tail.append(line.rstrip())

                proc.wait(timeout=timeout_sec)
                job.returncode = proc.returncode

        except subprocess.TimeoutExpired:
            self._terminate_proc(proc)
            job.status = "TIMEOUT"
            job.returncode = 124
            job.error = f"Tiempo límite excedido ({timeout_sec}s)"
        except Exception as e:
            job.status = "FAILED"
            job.returncode = 1
            job.error = str(e)
        finally:
            job.finished_at = time.time()
            duration = round(job.finished_at - t_start, 2)

            if job.status == "RUNNING":
                job.status = "COMPLETED" if job.returncode == 0 else "FAILED"

            # Detectar archivos modificados
            changed_files = self._detect_changed_files(job.cwd, before_snap)
            job.files_changed = changed_files

            # Validar sintaxis si se tocaron archivos Python
            syntax_ok, syntax_errors = self._validate_python_syntax(job.cwd, changed_files)
            if not syntax_ok:
                job.error = f"Advertencia de sintaxis: {'; '.join(syntax_errors)}"
                logger.error(f"[TardisFtlEngineer] Fallo de sintaxis detectado: {syntax_errors}")

            out_text = "".join(full_output)
            self._record_in_vault(job, out_text, duration)

            result_summary = {
                "ok": job.returncode == 0 and syntax_ok,
                "job_id": job.job_id,
                "status": job.status,
                "returncode": job.returncode,
                "duration_sec": duration,
                "files_changed": changed_files,
                "syntax_valid": syntax_ok,
                "syntax_errors": syntax_errors,
                "error": job.error,
                "log_path": str(job.log_path),
                "output_preview": out_text[-2500:] if out_text else "",
            }

            with self._lock:
                self.total_jobs_run += 1
                self.last_completed_job = result_summary
                self.current_job = None

        return result_summary

    @staticmethod
    def _terminate_proc(proc: subprocess.Popen) -> None:
        """Termina forzosamente un subproceso y su grupo."""
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            else:
                proc.terminate()
        except Exception:
            try:
                if os.name != "nt":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except Exception:
                pass

    def cancel_current_job(self) -> Dict[str, Any]:
        """Cancela el trabajo FTL en ejecución si existe."""
        with self._lock:
            if not self.current_job or not self.current_job.process:
                return {"ok": False, "message": "No hay ningún trabajo FTL en ejecución."}
            job = self.current_job
            job.status = "CANCELLED"
            self._terminate_proc(job.process)
            return {"ok": True, "message": f"Trabajo {job.job_id} cancelado con éxito."}

    def apply_improvement_proposal(
        self,
        proposal_path: Path | str,
        mode: str = "auto",
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> Dict[str, Any]:
        """
        Lee una propuesta de mejora (.md) de la cola, construye un prompt autónomo
        de implementación técnica, lo ejecuta con FTL y tras el éxito archiva la
        propuesta en 'processed/'.
        """
        path = Path(proposal_path).resolve()
        if not path.is_file():
            return {"ok": False, "error": f"Archivo de propuesta no encontrado: {path}"}

        content = path.read_text(encoding="utf-8", errors="ignore")
        title = path.stem
        for line in content.splitlines():
            if line.strip().startswith("#"):
                title = line.strip("# ").strip()
                break

        prompt = (
            f"TAREA DE AUTO-MEJORA AUTÓNOMA DEL SISTEMA TARDIS:\n"
            f"Implementa completamente en el codebase (/home/timemachine/Escritorio/GODWORKS SYSTEM) "
            f"la siguiente propuesta de mejora técnica:\n\n"
            f"--- PROPUESTA: {title} ---\n"
            f"{content}\n"
            f"--- FIN DE PROPUESTA ---\n\n"
            f"REGLAS OBLIGATORIAS:\n"
            f"1. Inspecciona los archivos afectados con atención técnica.\n"
            f"2. Edita directamente el código, implementando la solución con alta robustez.\n"
            f"3. Si la propuesta incluye comando de verificación o tests, ejecútalos directamente.\n"
            f"4. Asegura que ningún archivo quede con errores de sintaxis.\n"
            f"5. Concluye resumiendo los archivos modificados y las mejoras logradas."
        )

        meta = {
            "action": "apply_improvement",
            "proposal_file": path.name,
            "proposal_title": title,
        }

        res = self.execute_software_creation(
            prompt=prompt,
            mode=mode,
            cwd=PROJECT_DIR,
            timeout_sec=timeout_sec,
            background=False,
            meta=meta,
        )

        if res.get("ok"):
            # Mover la propuesta a processed/
            dest = PROCESSED_DIR / path.name
            try:
                shutil.move(str(path), str(dest))
                report_file = PROCESSED_DIR / f"{path.stem}.result.json"
                report_file.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
                with self._lock:
                    self.total_improvements_applied += 1
                res["archived_to"] = str(dest)
            except Exception as e:
                logger.warning(f"No se pudo mover propuesta procesada {path.name}: {e}")

        return res

    def process_pending_improvements(self, max_items: int = 1, mode: str = "auto") -> List[Dict[str, Any]]:
        """
        Busca propuestas pendientes en QUEUE_DIR y las aplica de forma autónoma con FTL.
        """
        results = []
        pending_files = sorted(
            [p for p in QUEUE_DIR.glob("*.md") if p.is_file() and not p.name.startswith(".")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,  # Más recientes primero
        )

        for proposal_path in pending_files[:max_items]:
            logger.info(f"[TardisFtlEngineer] Aplicando propuesta autónoma: {proposal_path.name}")
            res = self.apply_improvement_proposal(proposal_path, mode=mode)
            results.append(res)
            if not res.get("ok"):
                logger.warning(f"[TardisFtlEngineer] Fallo al aplicar {proposal_path.name}: {res.get('error')}")
                break  # Detener la cola ante fallo para evitar efecto cascada

        return results

    def run_autonomous_self_improvement_cycle(
        self,
        force: bool = False,
        model: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """
        Ciclo completo y soberano de auto-mejora:
        1. Si hay propuestas pendientes en la cola, aplica la más relevante con FTL.
        2. Si no hay propuestas, invoca a self_improve para generar una nueva propuesta
           basada en señales operativas reales, y la aplica DE INMEDIATO con FTL.
        """
        # 1. Verificar si hay propuestas en cola
        pending = [p for p in QUEUE_DIR.glob("*.md") if p.is_file() and not p.name.startswith(".")]
        if pending and not force:
            logger.info(f"[TardisFtlEngineer] Encontradas {len(pending)} propuestas pendientes. Procesando...")
            applied = self.process_pending_improvements(max_items=1, mode=mode)
            if applied:
                return {
                    "ok": applied[0].get("ok", False),
                    "cycle_type": "queue_processing",
                    "result": applied[0],
                }

        # 2. Generar nueva propuesta fresca si no hay pendientes
        try:
            import self_improve
            target_model = model or getattr(self_improve, "DEFAULT_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
            sig = self_improve.gather_signals()
            content = self_improve.generate_request(target_model, sig)

            if not content:
                return {
                    "ok": False,
                    "cycle_type": "signal_generation",
                    "error": "El modelo no generó una nueva propuesta en este ciclo.",
                }

            # Guardar la propuesta
            new_proposal_path = self_improve.write_request(content)
            logger.info(f"[TardisFtlEngineer] Nueva propuesta formulada: {new_proposal_path.name}. Aplicando con FTL...")

            # Aplicar inmediatamente con FTL sin esperar supervisión
            applied_res = self.apply_improvement_proposal(new_proposal_path, mode=mode)
            return {
                "ok": applied_res.get("ok", False),
                "cycle_type": "fresh_cycle_applied",
                "proposal_file": new_proposal_path.name,
                "result": applied_res,
            }

        except Exception as e:
            logger.error(f"[TardisFtlEngineer] Error en ciclo autónomo: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}


def get_ftl_engineer() -> TardisFtlEngineer:
    return TardisFtlEngineer.get_instance()
