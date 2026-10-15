"""
Tests for FTL & TARDIS Temporal Progress Bar and Time Estimation System
======================================================================
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from progress import TemporalProgressBar, TimeEstimator, run_command_with_progress, time_estimator
from router import router


def test_time_estimator_tiers():
    # Test level 1 to 5 estimation
    e1 = time_estimator.estimate("crea un archivo de configuracion", complexity=1, mode="gemini", model="gemini-3.8-flash-high")
    e2 = time_estimator.estimate("agrega un endpoint REST de telemetria", complexity=2, mode="gemini", model="gemini-3.8-flash-high")
    e3 = time_estimator.estimate("refactoriza modulo de seguridad y base de datos", complexity=3, mode="gemini", model="gemini-3.1-pro-high")
    e4 = time_estimator.estimate("arquitectura distribuida y orquestacion con failover", complexity=4, mode="dual_synth")
    e5 = time_estimator.estimate("compilador formal y verificacion matematica con AST", complexity=5, mode="claude", model="claude-opus-4-6")

    assert e1 >= 10.0, f"e1 too low: {e1}"
    assert e2 >= e1, f"e2 should be >= e1: {e2} vs {e1}"
    assert e3 >= e2, f"e3 should be >= e2: {e3} vs {e2}"
    assert e4 >= e3, f"e4 should be >= e3: {e4} vs {e3}"
    assert e5 >= e4, f"e5 should be >= e4: {e5} vs {e4}"


def test_router_integration():
    plan = router.route("disenia e implementa un motor de navegacion temporal para TARDIS")
    assert hasattr(plan, "estimated_duration")
    assert plan.estimated_duration > 15.0
    assert plan.complexity_level in (1, 2, 3, 4, 5)


def test_progress_bar_run():
    # Run a short simulated subprocess with the live progress bar
    cmd = ["python3", "-c", "import time; time.sleep(0.4); print('Evento intermedio'); time.sleep(0.4)"]
    rc, out, dur = run_command_with_progress(
        cmd=cmd,
        prompt="Verificación de barra de avance temporal",
        estimated_duration=1.0,
        engine_label="TEST-ENGINE",
        model_name="test-flash",
        complexity_label="Level 1: Verification"
    )
    assert rc == 0
    assert dur >= 0.7
    assert "Evento intermedio" in out


if __name__ == "__main__":
    test_time_estimator_tiers()
    print("✓ test_time_estimator_tiers PASSED")
    test_router_integration()
    print("✓ test_router_integration PASSED")
    test_progress_bar_run()
    print("✓ test_progress_bar_run PASSED")
    print("\nALL PROGRESS BAR & ESTIMATION TESTS PASSED SUCESSFULLY!")
