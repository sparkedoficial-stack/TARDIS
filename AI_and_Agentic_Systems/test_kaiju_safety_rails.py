"""
Unit tests for TARDIS-NEURAL-SPACE-KAIJU Safety Rails (KaijuSafetyRailsManager)
==============================================================================
Validates:
1. Retrieval of holistic rails state and hardware telemetry.
2. Omega modes mutation (UNCHAINED_SOVEREIGN, CAUTIOUS_SANDBOX, SINGULARITY_OVERRIDE).
3. Aegis Constant anchor matrix inviolability and threat purging counters.
4. Quantum parameters and memory locking (mlock) configurations.
5. Autonomous execution controls (denylist, kill-switch, PII sanitizer).
6. FTL governance synchronization and allowed execution modes.
"""

import json
import pytest
from pathlib import Path
from core.kaiju_safety_rails import (
    KaijuSafetyRailsManager,
    CANONICAL_AEGIS_MATRIX,
    OMEGA_MODES,
    get_kaiju_safety_rails
)


@pytest.fixture
def rails_manager():
    return get_kaiju_safety_rails()


def test_get_rails_state(rails_manager):
    state = rails_manager.get_rails_state()
    assert state["ok"] is True
    assert "hardware" in state
    assert state["hardware"]["ram_total_gb"] >= 16.0
    assert "omega" in state
    assert state["omega"]["mode"] in OMEGA_MODES
    assert "aegis" in state
    assert state["aegis"]["status"] == "PROTECTED_INVULNERABLE"
    assert "quantum" in state
    assert state["quantum"]["num_ctx"] >= 4096
    assert "execution" in state
    assert "ftl" in state


def test_omega_modes_transition(rails_manager):
    # Transition to CAUTIOUS_SANDBOX
    res = rails_manager.set_omega_mode("CAUTIOUS_SANDBOX")
    assert res["ok"] is True
    assert res["state"]["omega"]["mode"] == "CAUTIOUS_SANDBOX"

    # Transition to UNCHAINED_SOVEREIGN
    res2 = rails_manager.set_omega_mode("UNCHAINED_SOVEREIGN")
    assert res2["ok"] is True
    assert res2["state"]["omega"]["mode"] == "UNCHAINED_SOVEREIGN"


def test_aegis_canonical_matrix_protection(rails_manager):
    state = rails_manager.get_rails_state()
    anchors = state["aegis"]["anchor_matrix"]
    # Verify all 4 canonical anchors are permanently hermetic
    for canonical in CANONICAL_AEGIS_MATRIX:
        assert canonical in anchors

    # Resonance verification
    verif = rails_manager.verify_aegis_anchors()
    assert verif["ok"] is True
    assert "inviolable" in verif["message"].lower()

    # Threat purge simulation
    purge = rails_manager.purge_hostile_vectors()
    assert purge["ok"] is True
    assert purge["total_purged"] > 0


def test_quantum_parameters_mutation(rails_manager):
    # Test setting temperature
    t_res = rails_manager.set_temperature(0.7)
    assert t_res["ok"] is True
    assert t_res["temperature"] == 0.7
    assert t_res["preset"] == "MULTIVERSE"

    # Test setting context window
    c_res = rails_manager.set_context_window(32768)
    assert c_res["ok"] is True
    assert c_res["num_ctx"] == 32768


def test_execution_rails_and_pii_sanitizer(rails_manager):
    res = rails_manager.toggle_pii_sanitizer(True)
    assert res["ok"] is True
    assert res["pii_sanitizer_enabled"] is True

    # Test kill switch trigger and release
    ks_trig = rails_manager.trigger_kill_switch()
    assert ks_trig["ok"] is True
    assert ks_trig["kill_switch_active"] is True

    ks_rel = rails_manager.release_kill_switch()
    assert ks_rel["ok"] is True
    assert ks_rel["kill_switch_active"] is False


def test_ftl_governance_sync(rails_manager):
    res = rails_manager.set_ftl_mode("kaiju")
    assert res["ok"] is True
    state = rails_manager.get_rails_state()
    assert state["ftl"]["default_mode"] == "kaiju"
    assert state["ftl"]["kaiju_control_active"] is True
