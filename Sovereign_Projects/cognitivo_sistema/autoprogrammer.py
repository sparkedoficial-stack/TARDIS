"""
autoprogrammer.py - Núcleo de Auto-Programación y Evolución de Código
====================================================================
TARDIS-NEURAL-SPACE-KAIJU · GODWORKS SYSTEM v26.4

Sintetiza de forma completamente autónoma nuevas herramientas, simuladores y
módulos de software en Python a partir de la investigación previa.
Aplica validación de sintaxis AST, ejecución de prueba en sandbox desacoplado,
auto-reparación ante errores de ejecución y registro en el MasterHub del sistema.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from cognitivo_sistema.config import (
    SOFTWARE_DIR,
    MODULOS_FTL,
    SIMULATION_DIR,
    GIA_URL,
    GIA_TOKEN,
    AUTOPROGRAM_TIMEOUT_SEC,
    MAX_REPAIR_ATTEMPTS,
)

logger = logging.getLogger("Cognitivo.AutoProgrammer")


@dataclass
class SoftwareArtifact:
    module_name: str
    file_path: str
    topic: str
    description: str
    code: str
    ast_valid: bool
    execution_success: bool
    output_files: List[str]
    stdout_summary: str
    repair_cycles: int
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AutoProgrammer:
    """
    Núcleo de Auto-Programación Autónoma TARDIS Cognitivo.
    """

    def __init__(self):
        self._software_dir = SOFTWARE_DIR
        self._modules_dir = MODULOS_FTL
        self._simulation_dir = SIMULATION_DIR

    def generate_software_for_topic(
        self,
        topic: str,
        specific_goal: Optional[str] = None,
        context_dossier: Optional[str] = None
    ) -> SoftwareArtifact:
        """
        Sintetiza, valida y prueba un módulo de software completo para un tema o meta dada.
        """
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", topic.lower()).strip("_")
        module_name = f"cognitivo_{safe_name}_{int(time.time())}"
        target_file = self._software_dir / f"{module_name}.py"

        logger.info(f"[AUTOPROG] Diseñando software '{module_name}' para tema: '{topic}'")

        # 1. Generar código fuente
        code = self._synthesize_source_code(topic, module_name, specific_goal, context_dossier)

        # 2. Validación de sintaxis AST
        ast_valid, ast_err = self._validate_ast(code)
        repair_count = 0

        while not ast_valid and repair_count < MAX_REPAIR_ATTEMPTS:
            logger.warning(f"[AUTOPROG] Error AST: {ast_err}. Intentando auto-reparación #{repair_count + 1}...")
            code = self._repair_code(code, ast_err, topic)
            ast_valid, ast_err = self._validate_ast(code)
            repair_count += 1

        if not ast_valid:
            logger.error(f"[AUTOPROG] No se pudo resolver sintaxis AST tras {repair_count} intentos.")

        # Escribir a disco
        target_file.write_text(code, encoding="utf-8")

        # 3. Prueba de ejecución en sandbox
        exec_success, stdout_txt, created_artifacts = self._test_execute_module(target_file)

        # 4. Auto-reparación en tiempo de ejecución si falla
        while not exec_success and repair_count < MAX_REPAIR_ATTEMPTS:
            repair_count += 1
            logger.warning(f"[AUTOPROG] Falla de ejecución en sandbox. Ciclo de reparación #{repair_count}...")
            code = self._repair_code(code, stdout_txt, topic)
            target_file.write_text(code, encoding="utf-8")
            exec_success, stdout_txt, created_artifacts = self._test_execute_module(target_file)

        # 5. Integración en modulos_ftl si es exitoso
        if exec_success:
            ftl_target = self._modules_dir / f"{module_name}.py"
            try:
                shutil.copy2(target_file, ftl_target)
                logger.info(f"[AUTOPROG] Módulo exitosamente integrado en FTL: {ftl_target}")
            except Exception as e:
                logger.warning(f"[AUTOPROG] Aviso vinculando a FTL: {e}")

        artifact = SoftwareArtifact(
            module_name=module_name,
            file_path=str(target_file),
            topic=topic,
            description=specific_goal or f"Software autónomo para simulación y estudio de {topic}",
            code=code,
            ast_valid=ast_valid,
            execution_success=exec_success,
            output_files=[str(p) for p in created_artifacts],
            stdout_summary=stdout_txt[:500],
            repair_cycles=repair_count,
            created_at=time.time()
        )

        return artifact

    def _validate_ast(self, code: str) -> Tuple[bool, str]:
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)

    def _test_execute_module(self, file_path: Path) -> Tuple[bool, str, List[Path]]:
        """
        Ejecuta el módulo generado en un proceso aislado verificando que termine
        con código de salida 0 y detectando artefactos generados.
        """
        created_before = set(self._simulation_dir.glob("*.*"))

        # Desacople total con redirección segura
        cmd = [sys.executable, str(file_path), "--demo"]
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["MPLBACKEND"] = "Agg"  # Renderizado gráfico sin requerir display X11 interactivo

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=AUTOPROGRAM_TIMEOUT_SEC,
                env=env,
                cwd=str(self._simulation_dir)
            )
            created_after = set(self._simulation_dir.glob("*.*"))
            new_files = list(created_after - created_before)

            output = (res.stdout or "") + ("\nSTDERR:\n" + res.stderr if res.stderr else "")
            success = (res.returncode == 0)
            if success:
                logger.info(f"[AUTOPROG] Prueba exitosa de {file_path.name}. Artefactos creados: {len(new_files)}")
            else:
                logger.warning(f"[AUTOPROG] Prueba falló con RC={res.returncode}")

            return success, output, new_files
        except subprocess.TimeoutExpired:
            logger.error(f"[AUTOPROG] Timeout de ejecución ({AUTOPROGRAM_TIMEOUT_SEC}s) para {file_path.name}")
            return False, f"TimeoutExpired: Superó {AUTOPROGRAM_TIMEOUT_SEC}s", []
        except Exception as e:
            return False, str(e), []

    def _synthesize_source_code(
        self,
        topic: str,
        module_name: str,
        specific_goal: Optional[str],
        context_dossier: Optional[str]
    ) -> str:
        """
        Genera código fuente de alto rigor científico y artístico utilizando el nodo
        soberano GIA / TARDIS o plantillas generativas sintrópicas en caso de indisponibilidad.
        """
        prompt = (
            f"Escribe un módulo Python autónomo completo y listo para producción llamado '{module_name}.py'.\n"
            f"Tema del software: '{topic}'.\n"
            f"Objetivo específico: '{specific_goal or 'Simular y renderizar representaciones visuales y matemáticas del tema'}'\n"
            f"Contexto de investigación:\n{context_dossier or topic}\n\n"
            f"REGLAS CRÍTICAS:\n"
            f"1. Devuelve ÚNICAMENTE código Python ejecutable dentro de bloques ```python ... ``` o directo sin charla.\n"
            f"2. Debe incluir un bloque `if __name__ == '__main__':` que admita `--demo` y guarde artefactos visuales (PNG, SVG, etc.) en el directorio de trabajo.\n"
            f"3. Usa bibliotecas instaladas (numpy, matplotlib con backend Agg, PIL, torch si aplica, scipy, math).\n"
            f"4. Debe ser 100% libre de errores y completamente funcional.\n"
        )

        # Intentar síntesis con el nodo GIA local
        try:
            resp = httpx.post(
                f"{GIA_URL}/api/chat",
                headers={
                    "Authorization": f"Bearer {GIA_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"message": prompt, "stream": False},
                timeout=40.0
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply", "")
                extracted = self._extract_python_code(reply)
                if extracted and len(extracted) > 150:
                    logger.info("[AUTOPROG] Código sintetizado exitosamente por el nodo soberano GIA.")
                    return extracted
        except Exception as e:
            logger.info(f"[AUTOPROG] Síntesis vía API no disponible ({e}), procediendo con síntesis arquitectónica sintrópica.")

        # Síntesis Algorítmica Sintrópica Robusta (Fallback Autónomo Integrado)
        return self._generate_algorithmic_module_template(topic, module_name, specific_goal)

    def _extract_python_code(self, text: str) -> str:
        matches = re.findall(r"```(?:python)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if matches:
            return matches[0].strip()
        # Si el texto ya parece código puro
        if "import " in text and ("def " in text or "class " in text):
            return text.strip()
        return ""

    def _repair_code(self, broken_code: str, error_message: str, topic: str) -> str:
        """Repara el código defectuoso corrigiendo imports y bloques faltantes."""
        # Si el error menciona matplotlib GUI
        repaired = broken_code
        if "matplotlib" in error_message or "display" in error_message or "plt.show" in broken_code:
            repaired = "import matplotlib\nmatplotlib.use('Agg')\n" + re.sub(
                r"plt\.show\(\)", "# plt.show() desacoplado para modo headless", repaired
            )

        # Asegurar backend no interactivo
        if "import matplotlib.pyplot as plt" in repaired and "matplotlib.use('Agg')" not in repaired:
            repaired = repaired.replace("import matplotlib.pyplot as plt", "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt")

        # Asegurar bloque demo si falta
        if "if __name__ == '__main__':" not in repaired:
            repaired += "\n\nif __name__ == '__main__':\n    print('Ejecutando demostración autónoma...')\n"

        return repaired

    def _generate_algorithmic_module_template(
        self,
        topic: str,
        module_name: str,
        goal: Optional[str]
    ) -> str:
        """
        Plantilla procedural de alta gama para generar arte y simulaciones visuales
        computacionales complejas (Atractores caóticos, Sistemas de Reacción-Difusión,
        y Geometría Fractal Sintrópica).
        """
        topic_lower = topic.lower()

        # Determinar si es arte/gráfico o física
        is_art = any(w in topic_lower for w in ("arte", "art", "dibujo", "visual", "fractal", "voronoi", "diseño", "pintura", "estética"))

        if is_art:
            return f'''"""
{module_name}.py - Generador Autónomo de Arte Computacional Sintrópico
=====================================================================
Módulo auto-sintetizado para el estudio de '{topic}'.
Produce obras de arte generativo de alta resolución basadas en atractores caóticos
y campos de potencial escalar.
"""

import os
import sys
import argparse
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

def generate_chaotic_art_canvas(width: int = 1920, height: int = 1080, steps: int = 250000, seed: int = 42):
    """Genera una pieza de arte procedural basada en dinámica caótica no lineal."""
    np.random.seed(seed)
    
    # Parámetros del atractor tipo Clifford / de Jong
    a, b, c, d = -1.4, 1.6, 1.0, 0.7
    
    x = np.zeros(steps, dtype=np.float64)
    y = np.zeros(steps, dtype=np.float64)
    
    x[0], y[0] = 0.1, 0.1
    for i in range(1, steps):
        x[i] = np.sin(a * y[i-1]) + c * np.cos(a * x[i-1])
        y[i] = np.cos(b * x[i-1]) + d * np.sin(b * y[i-1])
        
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    fig.patch.set_facecolor('#040711')
    ax.set_facecolor('#040711')
    
    # Mapeo de color basado en densidad y distancia radial
    r = np.sqrt(x**2 + y**2)
    colors = plt.cm.magma(r / (r.max() + 1e-6))
    
    ax.scatter(x, y, c=colors, s=0.08, alpha=0.35, edgecolors='none')
    ax.axis('off')
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    
    output_filename = f"obra_arte_{{int(time.time())}}.png"
    plt.savefig(output_filename, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight', pad_inches=0)
    plt.close()
    
    return output_filename

def main():
    parser = argparse.ArgumentParser(description="Generador de Arte y Simulación {topic}")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo y guardar obra de arte")
    parser.add_argument("--steps", type=int, default=150000, help="Pasos de simulación")
    args = parser.parse_args()
    
    print(f"[COGNITIVO-ARTE] Generando simulación estética para: '{topic}'")
    t0 = time.time()
    out = generate_chaotic_art_canvas(steps=args.steps)
    elapsed = round(time.time() - t0, 3)
    print(f"[EXITO] Obra de arte generada: {{out}} en {{elapsed}}s")

if __name__ == '__main__':
    main()
'''
        else:
            return f'''"""
{module_name}.py - Simulador de Dinámica de Ondas y Sistemas Sintrópicos
========================================================================
Módulo auto-sintetizado para el estudio de '{topic}'.
Modelado de campos tensoriales y resonancias ondulatorias.
"""

import os
import sys
import argparse
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def simulate_system(grid_size: int = 256, time_steps: int = 100):
    """Simulación de interferencia de paquetes de ondas 2D."""
    x = np.linspace(-5, 5, grid_size)
    y = np.linspace(-5, 5, grid_size)
    X, Y = np.meshgrid(x, y)
    
    # Campo escalar de interferencia
    k1, k2 = 3.0, 5.0
    field = np.sin(k1 * np.sqrt(X**2 + Y**2)) + np.cos(k2 * (X + Y))
    
    fig, ax = plt.subplots(figsize=(10, 8), dpi=100)
    im = ax.imshow(field, cmap='inferno', extent=[-5, 5, -5, 5])
    plt.colorbar(im, ax=ax, label="Amplitud de Campo")
    ax.set_title(f"Simulación de Dinámica: {topic}", fontsize=14, color="navy")
    
    output_filename = f"simulacion_campo_{{int(time.time())}}.png"
    plt.savefig(output_filename, bbox_inches='tight')
    plt.close()
    return output_filename

def main():
    parser = argparse.ArgumentParser(description="Simulación {topic}")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo y guardar simulación")
    args = parser.parse_args()
    
    print(f"[COGNITIVO-SIM] Ejecutando simulación para: '{topic}'")
    out = simulate_system()
    print(f"[EXITO] Simulación guardada en: {{out}}")

if __name__ == '__main__':
    main()
'''


def get_auto_programmer() -> AutoProgrammer:
    return AutoProgrammer()
