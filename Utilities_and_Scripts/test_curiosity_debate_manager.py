"""Pruebas unitarias aisladas para core/curiosity_debate_manager.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from pathlib import Path

from core import curiosity_debate_manager as cdm


def test_curiosity_debate_manager_state_topic_rotation_and_pdf(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cdm, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cdm, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(cdm, "STATE_FILE", tmp_path / "debate_state.json")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    mgr = cdm.CuriosityDebateManager()
    st0 = mgr.get_status()
    assert isinstance(st0, dict)

    topic1 = mgr.select_next_topic()
    assert isinstance(topic1, cdm.DebateTopicData)
    assert topic1.title and topic1.domain

    msg = mgr.format_telegram_message(topic1)
    assert isinstance(msg, str) and len(msg) > 40
    assert topic1.title[:12].lower() in msg.lower() or topic1.domain.lower() in msg.lower()

    pdf_path = mgr.generate_debate_pdf(topic1)
    assert pdf_path is not None
    p = Path(pdf_path)
    assert p.exists() and p.stat().st_size > 500

    mgr._save_state()
    assert (tmp_path / "debate_state.json").exists()
