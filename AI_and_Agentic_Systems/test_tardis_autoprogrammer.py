import pytest
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, "/home/timemachine/.ftl")

from tardis_autoprogrammer import (
    MasterHub,
    TardisAutoprogrammer,
    autoprogrammer,
    MODULOS_DIR,
    BACKUP_DIR
)


def test_masterhub_discovery():
    """Verify MasterHub discovers active dynamic modules in modulos_ftl."""
    tools = autoprogrammer.list_dynamic_tools()
    assert isinstance(tools, list)
    names = [t["name"] for t in tools]
    assert "telemetria_avanzada" in names
    assert "explorador_cuantico" in names

    modules = autoprogrammer.hub.list_modules()
    assert "telemetria_avanzada" in modules
    assert "explorador_cuantico" in modules


def test_execute_dynamic_tool():
    """Verify executing dynamic tools via autoprogrammer."""
    res = autoprogrammer.execute_tool("telemetria_avanzada")
    assert res.get("ok") is True
    assert "result" in res


def test_evolve_rollback_on_syntax_error(tmp_path):
    """Verify evolve_file rolls back immediately when AST validation fails."""
    target = tmp_path / "sample_code.py"
    original_content = "def calculate():\n    return 42\n"
    target.write_text(original_content, encoding="utf-8")

    # Mock invalid code generator
    class BrokenAutoprogrammer(TardisAutoprogrammer):
        def _generate_code_for_evolution(self, prompt, mode="auto"):
            return "def calculate():\n    return 42 syntax error !@#$", "mock_broken"

    broken = BrokenAutoprogrammer()
    report = broken.evolve_file(str(target), "Intentar cambio con error sintáctico")

    assert report.status == "ROLLED_BACK_SYNTAX"
    assert report.error is not None
    # Verify file was rolled back to original content
    assert target.read_text(encoding="utf-8") == original_content


def test_autofunc_synthesis_and_execution(tmp_path):
    """Verify synthesizing a tool, AST validation, and hot loading."""
    # Synthetic code generator
    valid_code = (
        "class ConversorTemporal:\n"
        "    '''Conversor temporal de prueba.'''\n"
        "    def run(self, *args, **kwargs):\n"
        "        return {'status': 'ok', 'factor': 1.618}\n"
    )

    class CustomAutoprogrammer(TardisAutoprogrammer):
        def _generate_code_for_synthesis(self, prompt, mode="auto"):
            return valid_code, "mock_synth"

    custom = CustomAutoprogrammer()
    res = custom.autofunc("Herramienta de conversión temporal", module_name="test_conversor_temp")

    try:
        assert res.get("ok") is True
        assert res.get("module_name") == "test_conversor_temp"
        assert res.get("test_execution", {}).get("result", {}).get("factor") == 1.618

        # Verify execution via execute_tool
        run_res = custom.execute_tool("test_conversor_temp")
        assert run_res.get("ok") is True
        assert run_res.get("result", {}).get("factor") == 1.618
    finally:
        # Clean up temporary module file
        tmp_mod = MODULOS_DIR / "test_conversor_temp.py"
        if tmp_mod.exists():
            tmp_mod.unlink()
