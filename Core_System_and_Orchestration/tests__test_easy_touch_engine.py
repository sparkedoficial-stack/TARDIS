"""Pruebas unitarias aisladas para core/easy_touch_engine.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from pathlib import Path

from core import easy_touch_engine as ete


def test_easy_touch_engine_diagnosis_logging_and_interception(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ete, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ete, "EASY_TOUCH_LEDGER", tmp_path / "easy_touch_ledger.jsonl")
    monkeypatch.setattr(ete, "EASY_TOUCH_STATE", tmp_path / "easy_touch_state.json")
    monkeypatch.setattr(ete.EasyTouchEngine, "_init_self_improvement_agent", lambda self: None)

    eng = ete.EasyTouchEngine()
    eng.log_incident("unit_test_incident", {"detail": "simulated", "healed": True})
    assert (tmp_path / "easy_touch_ledger.jsonl").exists()

    diag_ctx = eng._diagnose_chat_error("context length exceeded 16384 tokens", None, None)
    assert isinstance(diag_ctx, dict) and diag_ctx

    diag_exec = eng._diagnose_execution_error("ModuleNotFoundError: No module named 'nonexistent_pkg'")
    assert isinstance(diag_exec, dict) and diag_exec

    # Historial largo debe recortarse de forma segura sin perder el turno actual
    long_hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i} " * 40} for i in range(30)]
    healed_hist = eng._heal_history_context(long_hist, diag_ctx)
    assert isinstance(healed_hist, list) and len(healed_hist) <= len(long_hist)

    # intercept_execution con returncode == 0 devuelve tupla (0, output) sin mutar
    rc, out = eng.intercept_execution("echo ok", returncode=0, output="ok", is_shell=True)
    assert rc == 0 and out == "ok"

    st = eng.get_status()
    assert isinstance(st, dict)
