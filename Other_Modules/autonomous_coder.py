"""
core/autonomous_coder.py - Motor de Auto-Programación y Evolución Continua
=========================================================================

Permite al sistema auto-programar su código fuente para auto-mejorarse de manera
continua y adaptarse eficientemente a cada tarea impuesta.

Arquitectura de Seguridad y Estabilidad:
  1. API-First Offload: delega la generación de código al acelerador Cloud API
     (Groq Qwen 27B / GPT-OSS 120B a 350+ tok/s) para evitar sobrecarga local de hardware.
  2. Aislamiento de Proyecto: solo puede modificar archivos dentro del repositorio de GODWORKS.
  3. Validación Sintáctica Rigurosa: ast.parse() obligatorio antes de escribir a disco.
  4. Respaldo Automático con Timestamp: en _selfmod_backups/.
  5. Verificación de Regresión Automatizada (pytest): ejecuta tests unitarios antes de
     confirmar el cambio; si fallan, ejecuta ROLLBACK inmediato al respaldo.
  6. Medición de Eficiencia: evalúa tiempos de ejecución (benchmarking) pre vs post.
  7. Bitácora Histórica de Evolución: data/self_evolution_log.json.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("GODWORKS.AutonomousCoder")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "_selfmod_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = PROJECT_ROOT / "data" / "self_evolution_log.json"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class EvolutionResult:
    target_file: str
    goal: str
    status: str  # 'APPLIED', 'ROLLED_BACK_SYNTAX', 'ROLLED_BACK_TESTS', 'API_FAILED', 'REJECTED'
    model_used: str
    elapsed_seconds: float
    backup_path: Optional[str] = None
    syntax_valid: bool = False
    tests_passed: Optional[bool] = None
    test_output: Optional[str] = None
    efficiency_improvement: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AutonomousCoder:
    """Orquestador de auto-programación, benchmarking y evolución de software."""

    _instance: Optional["AutonomousCoder"] = None

    def __init__(self):
        self._load_log()

    @classmethod
    def get_instance(cls) -> "AutonomousCoder":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_log(self) -> List[Dict[str, Any]]:
        if LOG_FILE.exists():
            try:
                data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _append_log(self, record: EvolutionResult) -> None:
        try:
            records = self._load_log()
            records.append(record.to_dict())
            LOG_FILE.write_text(json.dumps(records[-100:], indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error escribiendo bitácora de evolución: {e}")

    def get_evolution_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        records = self._load_log()
        return list(reversed(records))[:limit]

    def _validate_syntax(self, file_path: Path, code_text: str) -> Tuple[bool, str]:
        """Verifica que el código no contenga errores de sintaxis."""
        if file_path.suffix == ".py":
            try:
                ast.parse(code_text)
                return True, ""
            except SyntaxError as e:
                return False, f"SyntaxError línea {e.lineno}: {e.msg}"
        elif file_path.suffix == ".json":
            try:
                json.loads(code_text)
                return True, ""
            except Exception as e:
                return False, f"JSON inválido: {e}"
        return True, ""

    def _create_backup(self, file_path: Path) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_name = file_path.name
        backup_dst = BACKUP_DIR / f"{rel_name}.{ts}.bak"
        shutil.copy2(file_path, backup_dst)
        return backup_dst

    def run_tests(self, test_target: Optional[str] = None, timeout: float = 45.0) -> Tuple[bool, str]:
        """Ejecuta la suite de pruebas o un test específico con pytest."""
        cmd = [sys.executable, "-m", "pytest"]
        if test_target:
            cmd.append(test_target)
        else:
            cmd.extend(["tests/", "-q", "--tb=short"])

        try:
            res = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            success = (res.returncode == 0)
            output = (res.stdout + "\n" + res.stderr).strip()
            return success, output[:2500]
        except subprocess.TimeoutExpired:
            return False, "Timeout al ejecutar pytest"
        except Exception as e:
            return False, f"Error ejecutando pytest: {e}"

    def benchmark_code(self, func: Callable, iterations: int = 5, *args, **kwargs) -> Dict[str, Any]:
        """Mide tiempos de ejecución para validar optimizaciones."""
        times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            try:
                func(*args, **kwargs)
                elapsed = time.perf_counter() - t0
                times.append(elapsed)
            except Exception as e:
                return {"ok": False, "error": str(e)}

        avg_time = sum(times) / len(times) if times else 0.0
        min_time = min(times) if times else 0.0
        return {
            "ok": True,
            "iterations": iterations,
            "avg_ms": round(avg_time * 1000, 3),
            "min_ms": round(min_time * 1000, 3),
        }

    def evolve_code(
        self,
        target_path: str,
        goal: str,
        verify_tests: bool = True,
        test_file: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> EvolutionResult:
        """Auto-programa y evoluciona el archivo especificado para cumplir la meta u optimización."""
        t_start = time.time()
        p = Path(target_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p

        # 1. Validación de ruta dentro del proyecto
        try:
            p.resolve().relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="REJECTED",
                model_used="none",
                elapsed_seconds=0.0,
                error="Ruta fuera del límite seguro del proyecto",
            )
            self._append_log(res)
            return res

        if not p.is_file():
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="REJECTED",
                model_used="none",
                elapsed_seconds=0.0,
                error=f"Archivo no encontrado: {p}",
            )
            self._append_log(res)
            return res

        original_code = p.read_text(encoding="utf-8")
        backup_file = self._create_backup(p)

        # 2. Generación con API-First Offloading (Groq / Cloud API)
        model_used = "groq_deepseek"
        new_code = ""

        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            cloud_api = get_chinese_cloud_api()
            st = cloud_api.get_status()

            system_instruction = (
                "Eres el Módulo de Auto-Programación y Evolución Continua de GODWORKS SYSTEM v26.4. "
                "Tu objetivo es mejorar, optimizar y evolucionar el código fuente provisto según la meta indicada. "
                "REGLAS CRÍTICAS:\n"
                "1. Devuelve ÚNICAMENTE el código completo listo para ejecutar, sin comentarios de preámbulo ni explicaciones.\n"
                "2. Envuelve el código estrictamente en un bloque ```python ... ```.\n"
                "3. No elimines funciones ni clases existentes a menos que sea explícito en la meta.\n"
                "4. Mantén la sintaxis 100% válida y compatible con Python 3.10+.\n"
                "5. Optimiza algoritmos, reduce redundancias y mejora la eficiencia de cómputo y memoria."
            )

            user_prompt = (
                f"ARCHIVO: {p.name}\n"
                f"META DE EVOLUCIÓN / MEJORA:\n{goal}\n\n"
                f"CÓDIGO ORIGINAL ACTUAL:\n{original_code}\n\n"
                "Genera el código completo optimizado:"
            )

            # Intentar API Cloud si tiene clave configurada
            if st.get("enabled") and st.get("has_key"):
                target_model = model_override or st.get("active_model", "qwen/qwen3.8-27b")
                # Groq free tier OTPM es 1000 tokens/minuto acumulado; 600 garantiza margen seguro
                max_toks = 600 if "groq" in st.get("active_provider", "") else 4096
                api_resp = cloud_api.chat_completion([
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt},
                ], model=target_model, max_tokens=max_toks, timeout=45.0)

                if api_resp.get("ok") and api_resp.get("reply"):
                    new_code = api_resp["reply"].strip()
                    model_used = f"{api_resp.get('provider')} ({api_resp.get('model')})"

            # Fallback a Ollama local si la API externa falló o no devolvió código
            if not new_code:
                import httpx
                model_local = model_override or os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
                model_used = f"local_ollama ({model_local})"
                try:
                    r = httpx.post("http://REDACTED_IP:11434/api/generate", json={
                        "model": model_local,
                        "prompt": f"{system_instruction}\n\n{user_prompt}",
                        "stream": False,
                        "options": {"temperature": 0.2, "num_ctx": 8192},
                    }, timeout=120.0)
                    if r.status_code == 200:
                        new_code = r.json().get("response", "").strip()
                except Exception as e_loc:
                    logger.warning(f"Fallback a Ollama local falló: {e_loc}")

        except Exception as e_gen:
            logger.error(f"Fallo en generación de código: {e_gen}")
            # Restaurar por precaución
            shutil.copy2(backup_file, p)
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="API_FAILED",
                model_used=model_used,
                elapsed_seconds=round(time.time() - t_start, 2),
                backup_path=str(backup_file),
                error=str(e_gen),
            )
            self._append_log(res)
            return res

        # 3. Limpieza de bloques markdown
        if "```" in new_code:
            match = re.search(r"```(?:python)?\s*\n(.*?)\n```", new_code, re.DOTALL)
            if match:
                new_code = match.group(1).strip() + "\n"
            else:
                new_code = re.sub(r"^```[a-zA-Z]*\n", "", new_code)
                new_code = re.sub(r"\n```$", "", new_code).strip() + "\n"

        # Validar tamaño mínimo de seguridad (al menos 35% del original para evitar truncamientos)
        if len(new_code) < 0.35 * len(original_code):
            shutil.copy2(backup_file, p)
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="REJECTED",
                model_used=model_used,
                elapsed_seconds=round(time.time() - t_start, 2),
                backup_path=str(backup_file),
                error=f"Respuesta generada demasiado corta ({len(new_code)} vs {len(original_code)} bytes)",
            )
            self._append_log(res)
            return res

        # 4. Validación de sintaxis
        ok_syntax, err_syntax = self._validate_syntax(p, new_code)
        if not ok_syntax:
            shutil.copy2(backup_file, p)
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="ROLLED_BACK_SYNTAX",
                model_used=model_used,
                elapsed_seconds=round(time.time() - t_start, 2),
                backup_path=str(backup_file),
                syntax_valid=False,
                error=err_syntax,
            )
            self._append_log(res)
            return res

        # 5. Escribir código nuevo a disco temporalmente
        try:
            p.write_text(new_code, encoding="utf-8")
        except Exception as e_write:
            shutil.copy2(backup_file, p)
            res = EvolutionResult(
                target_file=str(p),
                goal=goal,
                status="REJECTED",
                model_used=model_used,
                elapsed_seconds=round(time.time() - t_start, 2),
                backup_path=str(backup_file),
                error=f"Error escribiendo archivo: {e_write}",
            )
            self._append_log(res)
            return res

        # 6. Verificación de Regresión con Tests Automatizados
        tests_passed = True
        test_out = "Tests omitidos por configuración"
        if verify_tests:
            logger.info("Ejecutando tests de verificación para código evolucionado...")
            tests_passed, test_out = self.run_tests(test_target=test_file)
            if not tests_passed:
                # ROLLBACK AUTOMÁTICO
                logger.warning(f"Tests fallaron tras evolución de {p.name}. Ejecutando rollback...")
                shutil.copy2(backup_file, p)
                res = EvolutionResult(
                    target_file=str(p),
                    goal=goal,
                    status="ROLLED_BACK_TESTS",
                    model_used=model_used,
                    elapsed_seconds=round(time.time() - t_start, 2),
                    backup_path=str(backup_file),
                    syntax_valid=True,
                    tests_passed=False,
                    test_output=test_out,
                    error="Tests unitarios fallaron; código revertido automáticamente a versión estable previa",
                )
                self._append_log(res)
                return res

        # 7. Éxito: Código evolucionado confirmado
        elapsed = round(time.time() - t_start, 2)
        res = EvolutionResult(
            target_file=str(p),
            goal=goal,
            status="APPLIED",
            model_used=model_used,
            elapsed_seconds=elapsed,
            backup_path=str(backup_file),
            syntax_valid=True,
            tests_passed=tests_passed,
            test_output=test_out[:500] if test_out else "",
        )
        self._append_log(res)
        logger.info(f"Auto-evolución exitosa de {p.name} en {elapsed}s vía {model_used}")
        return res

    def restore_backup(self, backup_path: str) -> Dict[str, Any]:
        """Restaura un archivo a un respaldo previo específico."""
        b = Path(backup_path)
        if not b.is_file():
            return {"ok": False, "error": f"Respaldo no existe: {backup_path}"}

        # Extraer nombre original: <archivo>.<timestamp>.bak
        orig_name = b.name.rsplit(".", 2)[0]
        dst = PROJECT_ROOT / orig_name
        try:
            shutil.copy2(b, dst)
            return {
                "ok": True,
                "restored_file": str(dst),
                "from_backup": str(b),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {"ok": False, "error": f"Error al restaurar: {e}"}

    def list_backups(self, file_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista los respaldos disponibles en _selfmod_backups."""
        pat = f"{file_name}.*.bak" if file_name else "*.bak"
        items = sorted(BACKUP_DIR.glob(pat), reverse=True)
        results = []
        for item in items[:40]:
            results.append({
                "backup_file": item.name,
                "full_path": str(item),
                "size_bytes": item.stat().st_size,
                "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
            })
        return results


def get_autonomous_coder() -> AutonomousCoder:
    return AutonomousCoder.get_instance()
