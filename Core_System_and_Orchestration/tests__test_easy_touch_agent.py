"""Pruebas unitarias aisladas para core/easy_touch_agent.py (COEV-20261123-ADB934)."""
from __future__ import annotations

import json
from pathlib import Path

from core import easy_touch_agent as eta


def test_unresolved_incident_roundtrip_and_dynamic_healer_registry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(eta, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(eta, "DYNAMIC_HEALERS_FILE", tmp_path / "dynamic_healers.json")

    inc = eta.UnresolvedIncident(
        id="INC-001",
        timestamp=REDACTED_PHONE.0,
        iso="2026-11-26T00:00:00",
        source="ledger",
        category="dns_resolution_timeout",
        command_or_prompt="curl https://example.com",
        error_output="Temporary failure in name resolution",
    )
    d = inc.to_dict()
    inc2 = eta.UnresolvedIncident.from_dict(d)
    assert inc2.id == "INC-001" and inc2.category == "dns_resolution_timeout"

    reg = eta.EasyTouchDynamicHealerRegistry()
    reg.register_healer(
        name="dns_flush_test",
        category="dns_resolution_timeout",
        pattern=r"name resolution",
        action_desc="Flush DNS resolver cache",
        code_snippet="pass",
    )
    assert "dns_flush_test" in reg.get_healers()
    reg.record_execution("dns_flush_test", success=True)
    reg2 = eta.EasyTouchDynamicHealerRegistry()
    found = reg2.get_healers().get("dns_flush_test")
    assert found and int(found.get("success_count", 0)) >= 1


def test_easy_touch_agent_categorization_and_ledger_audit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(eta, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(eta, "EASY_TOUCH_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(eta, "EASY_TOUCH_STATE", tmp_path / "state.json")
    monkeypatch.setattr(eta, "AGENT_STATE_FILE", tmp_path / "agent_state.json")
    monkeypatch.setattr(eta, "UNRESOLVED_FILE", tmp_path / "unresolved.json")
    monkeypatch.setattr(eta, "EVOLUTIONS_FILE", tmp_path / "evolutions.jsonl")
    monkeypatch.setattr(eta, "RETRO_HEALS_FILE", tmp_path / "retro_heals.jsonl")
    monkeypatch.setattr(eta, "DYNAMIC_HEALERS_FILE", tmp_path / "dynamic_healers.json")

    agent = eta.EasyTouchSelfImprovementAgent(check_interval_seconds=3600)
    assert agent.categorize_error("Temporary failure in name resolution", "curl") == "dns_resolution_timeout"
    assert agent.categorize_error("ModuleNotFoundError: No module named 'foo'", "python3") == "python_module_missing"
    assert agent.categorize_error("error: unknown flag --bad-flag", "agy --bad-flag") == "cli_flags_mismatch"
    assert agent.categorize_error("ggml-cuda CUDA error: out of memory", "llama-server") == "llama_server_cuda_crash"
    assert agent.categorize_error("PermissionError: Permission denied", "cat") == "permission_denied"
    assert agent.categorize_error("OSError: Address already in use", "uvicorn") == "port_conflict"

    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-11-26T01:00:00",
            "type": "execution_failure",
            "details": {"command": "python3 x.py", "output": "ModuleNotFoundError: No module named 'demo'", "healed": False},
        }) + "\n",
        encoding="utf-8",
    )
    found = agent.audit_unresolved_from_ledger()
    assert isinstance(found, list)
    st = agent.get_status()
    assert isinstance(st, dict)
