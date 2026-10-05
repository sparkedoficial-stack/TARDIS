"""
tardis_autoprogrammer.py
========================
Motor Unificado de Auto-Programación y Evolución Continua
Fusión Soberana TARDIS (GODWORKS v26.4) & FTL (Faster-Than-Light)

Capacidades:
  1. MasterHubManager: Carga dinámica y ejecución en caliente de módulos en modulos_ftl/.
  2. evolve_file: Auto-programación segura de archivos existentes con AST validation,
     backup automático en _selfmod_backups/ y rollback instantáneo ante fallos.
  3. autofunc / synthesize_module: Generación autónoma de nuevas herramientas y funciones,
     validación sintáctica, registro en MasterHub y ejecución inmediata.
  4. run_self_improvement_cycle: Ciclo continuo de auto-mejora basado en telemetría y señales.
  5. Registro Akáshico: Toda evolución se persiste en DeepMemoryVault y el historial transversal.
"""

from __future__ import annotations

import ast
import importlib.util
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

logger = logging.getLogger("TARDIS_FTL_AUTOPROGRAMMER")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM").resolve()
MODULOS_DIR = Path("/home/timemachine/modulos_ftl").resolve()
BACKUP_DIR = PROJECT_ROOT / "_selfmod_backups"
LOG_FILE = PROJECT_ROOT / "data" / "self_evolution_log.json"

MODULOS_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 1. MASTER HUB & DINÁMICA DE MÓDULOS
# ==============================================================================

class MasterHub:
    """Centro de registro y despacho en memoria para módulos FTL y herramientas TARDIS."""

    def __init__(self):
        self.modules: Dict[str, Any] = {}
        self.metadata: Dict[str, Dict[str, Any]] = {}

    def register_module(self, name: str, module_instance: Any, meta: Optional[Dict[str, Any]] = None):
        self.modules[name] = module_instance
        self.metadata[name] = meta or {
            "registered_at": datetime.now().isoformat(),
            "class_name": type(module_instance).__name__,
            "doc": (module_instance.__doc__ or "").strip()
        }
        logger.info(f"Módulo '{name}' registrado en Master Hub.")

    def list_modules(self) -> List[str]:
        return list(self.modules.keys())

    list_tools = list_modules

    def get_module(self, name: str) -> Optional[Any]:
        return self.modules.get(name)

    def execute_module(self, name: str, *args, **kwargs) -> Any:
        if name not in self.modules:
            return {"ok": False, "error": f"Módulo '{name}' no encontrado en Master Hub."}
        mod = self.modules[name]
        try:
            if hasattr(mod, "run"):
                res = mod.run(*args, **kwargs)
                return {"ok": True, "result": res}
            elif callable(mod):
                res = mod(*args, **kwargs)
                return {"ok": True, "result": res}
            else:
                return {"ok": False, "error": f"El módulo '{name}' no tiene método 'run' ni es invocable."}
        except Exception as e:
            logger.error(f"Error ejecutando módulo '{name}': {e}")
            return {"ok": False, "error": str(e)}

    execute = execute_module



class DynamicModuleManager:
    """Gestiona el descubrimiento, compilación y carga en tiempo de ejecución de modulos_ftl/."""

    def __init__(self, hub: MasterHub, modules_dir: Path = MODULOS_DIR):
        self.hub = hub
        self.modules_dir = modules_dir
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.auto_discover_and_load()

    def auto_discover_and_load(self) -> int:
        """Descubre y carga todos los archivos .py presentes en modulos_ftl/."""
        loaded_count = 0
        for py_file in self.modules_dir.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            mod_name = py_file.stem
            try:
                self.load_from_disk(mod_name, py_file)
                loaded_count += 1
            except Exception as e:
                logger.warning(f"No se pudo cargar módulo '{mod_name}': {e}")
        return loaded_count

    def load_from_disk(self, module_name: str, filepath: Path) -> Any:
        """Carga un módulo dinámico desde disco y lo registra en el Master Hub."""
        spec = importlib.util.spec_from_file_location(module_name, str(filepath))
        if not spec or not spec.loader:
            raise ImportError(f"No se pudo generar spec para {filepath}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"modulos_ftl.{module_name}"] = module
        spec.loader.exec_module(module)

        # Buscar la clase principal del módulo
        target_class = None
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, "run"):
                target_class = attr
                break

        if target_class:
            instance = target_class()
            meta = {
                "file": str(filepath),
                "class_name": target_class.__name__,
                "doc": (target_class.__doc__ or module.__doc__ or "").strip(),
                "loaded_at": datetime.now().isoformat()
            }
            self.hub.register_module(module_name, instance, meta)
            return instance
        else:
            # Fallback a funciones de nivel superior
            if hasattr(module, "run"):
                self.hub.register_module(module_name, module, {"file": str(filepath)})
                return module
            raise AttributeError(f"No se encontró clase con método 'run' en {filepath}")


# ==============================================================================
# 2. MOTOR DE AUTO-PROGRAMACIÓN SEGURO (AST, ROLLBACK, MULTI-MODEL)
# ==============================================================================

@dataclass
class EvolutionReport:
    target_file: str
    goal: str
    status: str  # 'APPLIED', 'ROLLED_BACK_SYNTAX', 'ROLLED_BACK_TESTS', 'FAILED'
    model_used: str
    elapsed_seconds: float
    backup_path: Optional[str] = None
    syntax_valid: bool = False
    tests_passed: Optional[bool] = None
    test_output: Optional[str] = None
    changes_summary: Optional[str] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TardisAutoprogrammer:
    """
    Núcleo Soberano de Auto-Programación:
    Une FTL y TARDIS en el mismo sistema capaz de auto-modificarse,
    crear nuevas capacidades en caliente y evolucionar sin intervención humana.
    """

    _instance: Optional["TardisAutoprogrammer"] = None

    @classmethod
    def get_instance(cls) -> "TardisAutoprogrammer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, hub: Optional[MasterHub] = None, module_manager: Optional[DynamicModuleManager] = None):
        self.hub = hub or MasterHub()
        self.module_manager = module_manager or DynamicModuleManager(self.hub)
        self.evolution_history: List[Dict[str, Any]] = self._load_evolution_log()

    def _load_evolution_log(self) -> List[Dict[str, Any]]:
        if LOG_FILE.exists():
            try:
                data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _append_evolution_log(self, report: EvolutionReport) -> None:
        try:
            self.evolution_history.append(report.to_dict())
            LOG_FILE.write_text(
                json.dumps(self.evolution_history[-100:], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Error escribiendo evolution log: {e}")

    def _backup_file(self, file_path: Path) -> Path:
        """Crea un respaldo seguro con timestamp."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = BACKUP_DIR / f"{file_path.name}.{ts}.bak"
        shutil.copy2(file_path, backup_path)
        return backup_path

    def _validate_syntax(self, code_str: str, file_path: Path) -> Tuple[bool, str]:
        """Verifica estrictamente que la sintaxis Python sea válida."""
        if file_path.suffix == ".py":
            try:
                ast.parse(code_str, filename=str(file_path))
                return True, ""
            except SyntaxError as e:
                return False, f"SyntaxError línea {e.lineno}, col {e.offset}: {e.msg}"
            except Exception as e:
                return False, f"Error analizando sintaxis: {e}"
        elif file_path.suffix == ".json":
            try:
                json.loads(code_str)
                return True, ""
            except Exception as e:
                return False, f"JSON inválido: {e}"
        return True, ""

    def _extract_code_from_markdown(self, raw_output: str, ext: str = ".py") -> str:
        """Extrae el bloque de código limpio si el modelo respondió con markdown."""
        fence_pattern = rf"```(?:python|py|json)?\s*\n(.*?)\n```"
        match = re.search(fence_pattern, raw_output, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        # Si no hay fences pero el texto empieza con import o def o comentarios
        stripped = raw_output.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped.startswith('"""') or stripped.startswith("'''") or stripped.startswith("#"):
            return stripped
        return raw_output.strip()

    def _generate_code_for_evolution(self, prompt: str, mode: str = "auto") -> Tuple[str, str]:
        model_label = "ftl_cognitive_router"
        generated_code = ""
        try:
            from router import router
            from executor import executor
            plan = router.route(prompt, forced_mode=mode)
            model_label = f"{plan.primary_engine}_{plan.primary_model}"
            rc, out = executor.execute_plan(plan, prompt)
            if rc == 0 and out:
                generated_code = self._extract_code_from_markdown(out)
        except Exception as e:
            logger.warning(f"Router local falló o no disponible: {e}. Intentando fallback...")

        if not generated_code:
            try:
                from tardis_bridge import tardis_bridge
                res = tardis_bridge._request_api("/api/chat", method="POST", data={
                    "message": prompt,
                    "stream": False
                }, timeout=120)
                if res.get("ok") and "reply" in res:
                    generated_code = self._extract_code_from_markdown(res["reply"])
                    model_label = res.get("model", "tardis_daemon")
            except Exception as ex:
                logger.error(f"Fallback TARDIS API falló: {ex}")

        return generated_code, model_label

    def evolve_file(
        self,
        target_path: str | Path,
        goal: str,
        mode: str = "auto",
        verify_tests: bool = True,
        test_file: Optional[str] = None
    ) -> EvolutionReport:
        """
        Auto-programa y evoluciona un archivo de código existente:
        1. Respaldo previo garantizado en _selfmod_backups/.
        2. Inferencia y rediseño de código con los motores de frontera de FTL.
        3. Validación AST inmediata.
        4. Si falla la sintaxis o tests: ROLLBACK instantáneo.
        5. Si pasa: persistencia, registro en DeepMemoryVault y notificación.
        """
        t0 = time.time()
        path = Path(target_path).resolve()

        if not path.is_file():
            # Buscar en PROJECT_ROOT o BASE_DIR
            candidate = (PROJECT_ROOT / target_path).resolve()
            if candidate.is_file():
                path = candidate
            else:
                candidate2 = (BASE_DIR / target_path).resolve()
                if candidate2.is_file():
                    path = candidate2
                else:
                    return EvolutionReport(
                        target_file=str(target_path),
                        goal=goal,
                        status="FAILED",
                        model_used=mode,
                        elapsed_seconds=0.0,
                        error=f"Archivo objetivo no encontrado: {target_path}"
                    )

        # 1. Crear respaldo obligatorio
        backup_path = self._backup_file(path)
        original_code = path.read_text(encoding="utf-8", errors="ignore")

        # 2. Generar el código evolucionado
        prompt = (
            f"[MANDATO GLOBAL SOBERANO TARDIS/FTL :: AUTO-PROGRAMACIÓN Y EVOLUCIÓN]\n"
            f"Tu tarea es auto-programar, optimizar o añadir la siguiente funcionalidad al archivo:\n"
            f"Archivo: {path.name} ({path})\n"
            f"Meta de Evolución: {goal}\n\n"
            f"CÓDIGO FUENTE ACTUAL:\n"
            f"```python\n{original_code}\n```\n\n"
            f"INSTRUCCIONES ESTRICTAS:\n"
            f"1. Devuelve ÚNICAMENTE el código Python completo, libre de errores sintácticos.\n"
            f"2. Conserva todas las firmas existentes y retrocompatibilidad necesaria.\n"
            f"3. Responde dentro de un bloque ```python ... ```."
        )

        generated_code, model_label = self._generate_code_for_evolution(prompt, mode)



        if not generated_code:
            return EvolutionReport(
                target_file=str(path),
                goal=goal,
                status="FAILED",
                model_used=model_label,
                elapsed_seconds=round(time.time() - t0, 2),
                backup_path=str(backup_path),
                error="No se pudo obtener generación de código de los motores soberanos."
            )

        # 3. Validación AST estricta
        syntax_ok, syntax_err = self._validate_syntax(generated_code, path)
        if not syntax_ok:
            # ROLLBACK INMEDIATO
            shutil.copy2(backup_path, path)
            report = EvolutionReport(
                target_file=str(path),
                goal=goal,
                status="ROLLED_BACK_SYNTAX",
                model_used=model_label,
                elapsed_seconds=round(time.time() - t0, 2),
                backup_path=str(backup_path),
                syntax_valid=False,
                error=f"Código generado con error sintáctico. Rollback ejecutado: {syntax_err}"
            )
            self._append_evolution_log(report)
            return report

        # 4. Escribir a disco temporalmente para pruebas
        try:
            path.write_text(generated_code, encoding="utf-8")
        except Exception as e:
            shutil.copy2(backup_path, path)
            return EvolutionReport(
                target_file=str(path),
                goal=goal,
                status="FAILED",
                model_used=model_label,
                elapsed_seconds=round(time.time() - t0, 2),
                backup_path=str(backup_path),
                error=f"Error escribiendo archivo: {e}"
            )

        # 5. Verificación de tests automatizados (si corresponde)
        tests_passed = True
        test_out = ""
        if verify_tests:
            # Si hay test_file explícito o test asociado en tests/
            t_candidates = []
            if test_file:
                t_candidates.append(Path(test_file))
            else:
                test_name = f"test_{path.stem}.py"
                for test_dir in [path.parent, path.parent / "tests", PROJECT_ROOT / "tests", BASE_DIR]:
                    candidate = test_dir / test_name
                    if candidate.is_file():
                        t_candidates.append(candidate)
                        break

            if t_candidates:
                test_target = t_candidates[0]
                try:
                    res_test = subprocess.run(
                        [sys.executable, "-m", "pytest", str(test_target), "-q"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    test_out = res_test.stdout or res_test.stderr
                    if res_test.returncode != 0:
                        tests_passed = False
                except Exception as e:
                    test_out = f"Error corriendo tests: {e}"
                    tests_passed = False

        if not tests_passed:
            # ROLLBACK POR FALLO DE TESTS
            shutil.copy2(backup_path, path)
            report = EvolutionReport(
                target_file=str(path),
                goal=goal,
                status="ROLLED_BACK_TESTS",
                model_used=model_label,
                elapsed_seconds=round(time.time() - t0, 2),
                backup_path=str(backup_path),
                syntax_valid=True,
                tests_passed=False,
                test_output=test_out,
                error="Tests fallaron tras aplicar cambios. Rollback automático ejecutado."
            )
            self._append_evolution_log(report)
            return report

        # 6. ÉXITO CONFIRMADO
        elapsed = round(time.time() - t0, 2)
        report = EvolutionReport(
            target_file=str(path),
            goal=goal,
            status="APPLIED",
            model_used=model_label,
            elapsed_seconds=elapsed,
            backup_path=str(backup_path),
            syntax_valid=True,
            tests_passed=tests_passed if test_out else None,
            test_output=test_out if test_out else "Sintaxis AST validada.",
            changes_summary=f"Evolución aplicada exitosamente ({len(generated_code.splitlines())} líneas)."
        )
        self._append_evolution_log(report)

        # Ingesta en memoria akáshica
        try:
            from tardis_bridge import tardis_bridge
            tardis_bridge.record_turn(
                prompt=f"Evolución de código: {path.name} -> {goal}",
                returncode=0,
                duration=elapsed,
                files_changed=[path.name],
                summary_output=f"Evolución exitosa con modelo {model_label} en {elapsed}s."
            )
        except Exception:
            pass

        return report

    def _generate_code_for_synthesis(self, prompt: str, mode: str = "auto") -> Tuple[str, str]:
        code_text = ""
        model_label = "ftl_synth"
        try:
            from router import router
            from executor import executor
            plan = router.route(prompt, forced_mode=mode)
            model_label = f"{plan.primary_engine}_{plan.primary_model}"
            rc, out = executor.execute_plan(plan, prompt)
            if rc == 0 and out:
                code_text = self._extract_code_from_markdown(out)
        except Exception:
            pass

        if not code_text:
            try:
                from tardis_bridge import tardis_bridge
                res = tardis_bridge._request_api("/api/chat", method="POST", data={"message": prompt})
                if res.get("ok") and "reply" in res:
                    code_text = self._extract_code_from_markdown(res["reply"])
                    model_label = res.get("model", "tardis_daemon")
            except Exception:
                pass

        return code_text, model_label

    def autofunc(
        self,
        goal: str,
        module_name: Optional[str] = None,
        mode: str = "auto"
    ) -> Dict[str, Any]:
        """
        Sintetiza de forma 100% autónoma un nuevo módulo en modulos_ftl/,
        valida la sintaxis, lo carga en el Master Hub y ejecuta una prueba.
        """
        t0 = time.time()
        # Si no se dio nombre, generar un identificador limpio
        if not module_name:
            # Extraer palabras clave del goal
            clean = re.sub(r'[^a-zA-Z0-9\s]', '', goal).strip().lower()
            words = [w for w in clean.split() if len(w) > 2 and w not in ("para", "como", "crea", "hacer", "sistema", "modulo")]
            slug = "_".join(words[:3]) if words else "modulo_autonomo"
            module_name = f"{slug}_{int(time.time()) % 10000}"

        module_name = module_name.replace("-", "_").lower()
        class_name = "".join(w.capitalize() for w in module_name.split("_"))

        prompt = (
            f"[MANDATO SOBERANO TARDIS/FTL :: SÍNTESIS DE HERRAMIENTA DINÁMICA]\n"
            f"Diseña e implementa un módulo Python completo para el sistema autónomo con la meta:\n"
            f"Meta: {goal}\n"
            f"Nombre del módulo: {module_name}\n"
            f"Nombre de la clase principal: {class_name}\n\n"
            f"REGLAS TÉCNICAS OBLIGATORIAS:\n"
            f"1. La clase '{class_name}' DEBE implementar el método 'run(self, *args, **kwargs)'.\n"
            f"2. Debe retornar un diccionario o estructura con el resultado de su ejecución.\n"
            f"3. Debe ser código autónomo, robusto y con manejo de excepciones interno.\n"
            f"4. Devuelve ÚNICAMENTE el código en un bloque ```python ... ```."
        )

        code_text, model_label = self._generate_code_for_synthesis(prompt, mode)



        if not code_text:
            return {"ok": False, "error": "No se pudo sintetizar el código para el módulo."}

        # Validar sintaxis AST
        file_path = MODULOS_DIR / f"{module_name}.py"
        syntax_ok, syntax_err = self._validate_syntax(code_text, file_path)
        if not syntax_ok:
            return {"ok": False, "error": f"El código sintetizado tiene errores sintácticos: {syntax_err}"}

        # Guardar archivo en disco
        file_path.write_text(code_text, encoding="utf-8")

        # Cargar e instanciar en Master Hub
        try:
            instance = self.module_manager.load_from_disk(module_name, file_path)
            # Ejecutar prueba de verificación
            test_exec = self.hub.execute_module(module_name)
            elapsed = round(time.time() - t0, 2)

            # Ingestar en memoria akáshica
            try:
                from tardis_bridge import tardis_bridge
                tardis_bridge.record_turn(
                    prompt=f"Síntesis de módulo dinámico: {module_name} -> {goal}",
                    returncode=0,
                    duration=elapsed,
                    files_changed=[str(file_path.name)],
                    summary_output=f"Módulo '{module_name}' registrado en Master Hub. Test: {test_exec}"
                )
            except Exception:
                pass

            return {
                "ok": True,
                "module_name": module_name,
                "class_name": class_name,
                "path": str(file_path),
                "model_used": model_label,
                "elapsed_seconds": elapsed,
                "test_execution": test_exec,
                "message": f"Módulo '{module_name}' creado, validado y cargado en Master Hub exitosamente."
            }
        except Exception as e:
            return {"ok": False, "error": f"Fallo al registrar módulo sintetizado: {e}"}

    def list_dynamic_tools(self) -> List[Dict[str, Any]]:
        """Lista todos los módulos y herramientas dinámicas registradas en el Master Hub."""
        tools = []
        for name in self.hub.list_modules():
            meta = self.hub.metadata.get(name, {})
            tools.append({
                "name": name,
                "class": meta.get("class_name", "Desconocida"),
                "file": meta.get("file", ""),
                "doc": meta.get("doc", "Sin documentación"),
                "registered_at": meta.get("registered_at") or meta.get("loaded_at")
            })
        return tools

    def execute_tool(self, name: str, *args, **kwargs) -> Any:
        """Ejecuta una herramienta dinámica por su nombre."""
        return self.hub.execute_module(name, *args, **kwargs)

    def run_self_improvement_cycle(self, force: bool = False, mode: str = "auto") -> Dict[str, Any]:
        """Ejecuta el ciclo cerrado de auto-mejora continua de TARDIS y FTL."""
        try:
            from core.tardis_ftl_engineer import get_ftl_engineer
            eng = get_ftl_engineer()
            return eng.run_autonomous_self_improvement_cycle(force=force, mode=mode)
        except Exception as e:
            return {"ok": False, "error": f"Error ejecutando ciclo de auto-mejora: {e}"}


# Singleton export
autoprogrammer = TardisAutoprogrammer.get_instance()
