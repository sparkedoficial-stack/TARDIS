"""
Test Suite: FTL Recursion Prevention & Idempotent Hot-Reload
============================================================
Ensures that prompt_toolkit container monkey patches and dynamic reloads
do not accumulate stack frames or trigger 'maximum recursion depth exceeded'.
"""

import importlib
import sys
from pathlib import Path

# Add ~/.ftl to path
FTL_DIR = Path(__file__).parent
sys.path.insert(0, str(FTL_DIR))

import prompt_toolkit.layout.containers as _pt_containers
from prompt_toolkit.layout.containers import Window, HSplit, VSplit
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.screen import WritePosition

import ui
from ftl_cli import reload_ftl_modules, _get_ftl_mtimes


def test_idempotent_pt_patching():
    """Verify that repeatedly reloading ui.py does not nest monkey patches."""
    for _ in range(500):
        importlib.reload(ui)

    # After 500 reloads, HSplit._divide_heights should execute without RecursionError
    h = HSplit([Window(FormattedTextControl("FTL Test"))])
    pos = WritePosition(0, 0, 80, 24)
    heights = h._divide_heights(pos)
    assert heights == [24], f"Expected [24], got {heights}"

    # VSplit._divide_widths should also execute without RecursionError
    v = VSplit([Window(FormattedTextControl("FTL Test"))])
    widths = v._divide_widths(80)
    assert widths == [80], f"Expected [80], got {widths}"


def test_reload_ftl_modules_preserves_mode():
    """Verify that reload_ftl_modules preserves the user's active mode."""
    new_ui, new_exec, new_rout, new_reg, cfg_m, bri_m = reload_ftl_modules(preserve_mode="kaiju")
    assert new_ui.mode == "kaiju"

    new_ui2, _, _, _, _, _ = reload_ftl_modules(preserve_mode="claude")
    assert new_ui2.mode == "claude"


def test_get_ftl_mtimes():
    """Verify that _get_ftl_mtimes returns a valid timestamp."""
    mtime = _get_ftl_mtimes()
    assert isinstance(mtime, float)
    assert mtime > 0.0


def test_prompt_user_fallback(monkeypatch):
    """Verify that prompt_user gracefully falls back to input() if session fails."""
    test_ui = ui.FTLInterface()
    test_ui.mode = "test"

    # Simulate a session failure
    def mock_prompt(*args, **kwargs):
        raise RuntimeError("Terminal disconnected")

    monkeypatch.setattr(test_ui.session, "prompt", mock_prompt)
    monkeypatch.setattr("builtins.input", lambda prompt: "fallback command")

    result = test_ui.prompt_user()
    assert result == "fallback command"


if __name__ == "__main__":
    test_idempotent_pt_patching()
    print("✔ test_idempotent_pt_patching passed")
    test_reload_ftl_modules_preserves_mode()
    print("✔ test_reload_ftl_modules_preserves_mode passed")
    test_get_ftl_mtimes()
    print("✔ test_get_ftl_mtimes passed")
    print("\nALL RECURSION GUARD TESTS PASSED!")
