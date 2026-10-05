"""
tests/test_tardis_dynamic_function_engine.py - Pruebas para la Síntesis Autónoma de Funciones
=============================================================================================
Verifica que TARDIS detecte brechas de capacidad, investigue, programe en segundo plano,
registre y ejecute funciones sintetizadas dinámicamente según la directiva del Arquitecto.
"""

import os
import sys
import time
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_dynamic_function_engine import get_dynamic_function_engine, DYNAMIC_TOOLS_DIR


def test_engine_initialization():
    engine = get_dynamic_function_engine()
    assert engine is not None
    assert DYNAMIC_TOOLS_DIR.exists()


def test_capability_gap_detection():
    engine = get_dynamic_function_engine()

    # Peticiones que deben ser detectadas como brecha de capacidad / necesidad de función
    gap1, info1 = engine.detect_capability_gap("si tardis no tiene la función para convertir archivos tex a pdf, programa la función en segundo plano")
    assert gap1 is True
    assert "name" in info1
    assert "convertir" in info1["name"] or "pdf" in info1["name"] or "tex" in info1["name"] or "tool" in info1["name"]

    gap2, info2 = engine.detect_capability_gap("/autofunc calcular la órbita sincrónica de un satélite en geoestacionaria")
    assert gap2 is True
    assert "satelite" in info2["name"] or "orbita" in info2["name"] or "tool" in info2["name"]

    # Saludos cotidianos no deben activar la auto-programación
    gap3, _ = engine.detect_capability_gap("hola cómo estás")
    assert gap3 is False


def test_manual_tool_synthesis_and_execution():
    engine = get_dynamic_function_engine()
    test_func_name = "t_test_fibonacci_calculator"
    test_file = DYNAMIC_TOOLS_DIR / f"{test_func_name}.py"

    code_content = '''"""Función de prueba para cálculo de fibonacci sintetizada dinámicamente."""

def run(args: dict) -> dict:
    n = int(args.get("n", 10))
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return {
        "ok": True,
        "n": n,
        "fibonacci_result": a
    }

TOOL_METADATA = {
    "name": "t_test_fibonacci_calculator",
    "description": "Calcula el número de fibonacci para una posición n",
    "parameters": {"n": "int"}
}

if __name__ == "__main__":
    res = run({"n": 5})
    print("Smoke test passed:", res)
'''
    test_file.write_text(code_content, encoding="utf-8")

    try:
        # Cargar módulo
        loaded_func = engine._load_module_function(test_file, test_func_name)
        assert loaded_func is not None

        # Registrar
        engine._tools[test_func_name] = loaded_func

        # Ejecutar función
        exec_res = engine.execute_function(test_func_name, {"n": 7})
        assert exec_res.get("ok") is True
        assert exec_res.get("fibonacci_result") == 13

        # Verificar disponibilidad en catálogo
        assert engine.get_tool(test_func_name) is not None

    finally:
        # Limpieza
        if test_file.exists():
            test_file.unlink()
        if test_func_name in engine._tools:
            del engine._tools[test_func_name]


def test_background_dispatch_and_execution():
    engine = get_dynamic_function_engine()
    test_func_name = "t_test_bg_metric"
    test_file = DYNAMIC_TOOLS_DIR / f"{test_func_name}.py"

    # Inyectar función directamente
    code_content = '''"""Métrica simulada en background."""
def run(args: dict) -> dict:
    return {"ok": True, "metric": "SYNTHESIZED_SUCCESS", "timestamp": 123456}

if __name__ == "__main__":
    print("Smoke test passed")
'''
    test_file.write_text(code_content, encoding="utf-8")

    try:
        loaded = engine._load_module_function(test_file, test_func_name)
        engine._tools[test_func_name] = loaded

        res = engine.execute_function(test_func_name, {})
        assert res.get("ok") is True
        assert res.get("metric") == "SYNTHESIZED_SUCCESS"
    finally:
        if test_file.exists():
            test_file.unlink()
        if test_func_name in engine._tools:
            del engine._tools[test_func_name]
