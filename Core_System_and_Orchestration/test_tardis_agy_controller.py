"""Pruebas unitarias aisladas para core/tardis_agy_controller.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from pathlib import Path

from core import tardis_agy_controller as tac


def test_agy_controller_helpers_queue_and_pause_isolation(tmp_path: Path, monkeypatch):
    ctrl_dir = tmp_path / "agy_ctrl"
    monkeypatch.setattr(tac, "APPDATA_DIR", tmp_path)
    monkeypatch.setattr(tac, "CONTROL_DIR", ctrl_dir)
    monkeypatch.setattr(tac, "QUEUE_DIR", ctrl_dir / "queue")
    monkeypatch.setattr(tac, "RUNNING_DIR", ctrl_dir / "running")
    monkeypatch.setattr(tac, "COMPLETED_DIR", ctrl_dir / "completed")
    monkeypatch.setattr(tac, "FAILED_DIR", ctrl_dir / "failed")
    monkeypatch.setattr(tac, "STATE_FILE", ctrl_dir / "state.json")
    monkeypatch.setattr(tac, "EVENTS_FILE", ctrl_dir / "events.jsonl")
    monkeypatch.setattr(tac, "LEDGER_FILE", ctrl_dir / "ledger.jsonl")
    monkeypatch.setattr(tac, "LIVE_SESSIONS_FILE", ctrl_dir / "live_sessions.json")
    monkeypatch.setattr(tac, "LOCK_FILE", ctrl_dir / "controller.lock")

    assert tac._effort_for_model("claude-opus-5-5-high", None) in ("high", "xhigh")
    assert tac._effort_for_model("gemini-4-neon-xhigh", "low") == "low"
    env = tac._build_autonomous_env({"TARDIS_UNIT_TEST": "1"})
    assert env["TARDIS_UNIT_TEST"] == "1"

    p_json = tmp_path / "atomic.json"
    tac._atomic_write_json(p_json, {"ok": True, "n": 7})
    assert tac._load_json(p_json, {}) == {"ok": True, "n": 7}

    ctrl = tac.TardisAgyController()
    assert ctrl.is_paused() is False
    ctrl.set_paused(True)
    assert ctrl.is_paused() is True
    ctrl.set_paused(False)

    enq = ctrl.enqueue_task(
        prompt="Auditar cobertura unitaria de prueba",
        source="pytest",
        priority="high",
        dedup_window_s=60.0,
    )
    assert enq.get("ok") is True and enq.get("task_id")
    tid = enq["task_id"]
    fetched = ctrl.get_task(tid)
    assert fetched is not None and fetched.get("task_id") == tid

    # Deduplicación dentro de ventana
    enq_dup = ctrl.enqueue_task(
        prompt="Auditar cobertura unitaria de prueba",
        source="pytest",
        priority="high",
        dedup_window_s=60.0,
    )
    assert enq_dup.get("deduplicated") is True or enq_dup.get("task_id") == tid

    st = ctrl.get_status()
    assert isinstance(st, dict) and st.get("ok") is not False
