"""Pruebas unitarias aisladas para core/mission_scouting_engine.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from pathlib import Path

from core import mission_scouting_engine as mse


def test_mission_scouting_engine_crud_contact_extraction_and_synergy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mse, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(mse, "VAULT_FILE", tmp_path / "missions_vault.json")
    monkeypatch.setattr(mse, "FALLBACK_DIR", tmp_path / "fb")
    monkeypatch.setattr(mse, "FALLBACK_VAULT_FILE", tmp_path / "fb" / "missions_vault.json")

    eng = mse.MissionScoutingEngine()

    contacts = mse.MissionScoutingEngine.extract_contact_info(
        "Contacto técnico: REDACTED_EMAIL | Web: https://github.com/tardis-lab | Tel: +REDACTED_PHONE",
        target_name="Dr. Demo",
    )
    assert isinstance(contacts, dict)
    assert "REDACTED_EMAIL" in (contacts.get("emails") or [])

    m = eng.create_mission(
        title="Investigación GPU Kernel",
        category="engineering",
        description="Optimización CUDA y memoria virtual Linux",
        required_skills=["cuda", "linux", "python"],
        priority="HIGH",
        synergy_tags=["gpu", "kernel"],
    )
    assert isinstance(m, dict) and m.get("id")
    mid = m["id"]
    assert eng.get_mission(mid) is not None
    assert any(x.get("id") == mid for x in eng.list_missions())

    syn = eng.calculate_synergy(
        {"name": "Ada", "skills": ["cuda", "python"], "bio": "Linux kernel and GPU optimization"},
        m,
    )
    assert isinstance(syn, (int, float, dict))

    summary = eng.get_status_summary()
    assert isinstance(summary, dict)
    assert (tmp_path / "missions_vault.json").exists()
