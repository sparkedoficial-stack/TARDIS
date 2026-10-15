"""Reproducibility and analysis tests for the causal prompt chaining first experiment."""

from experiments.causal_prompt_chaining.run import run_experiment
from experiments.causal_prompt_chaining.world import BROKEN_SNIPPETS, VALID_SNIPPET, compile_code


def test_live_coder_classifies_fixture_snippets():
    ok, err, klass = compile_code(VALID_SNIPPET)
    assert ok is True
    assert klass == "ok"

    ok_b, err_b, klass_b = compile_code(BROKEN_SNIPPETS["fix_parens"])
    assert ok_b is False
    assert err_b
    assert klass_b in {"UnclosedParen", "other"}


def test_experiment_is_seed_reproducible():
    a = run_experiment(seed=42)
    b = run_experiment(seed=42)
    assert a["control_trials"] == b["control_trials"]
    assert a["treatment_trials"] == b["treatment_trials"]
    assert a["analysis"]["relative_reduction"] == b["analysis"]["relative_reduction"]


def test_experiment_reports_method_and_limits_shape():
    payload = run_experiment(seed=42)
    assert "hypothesis" in payload
    assert payload["method"]["compiler"] == "AutonomousCoder._validate_syntax"
    assert payload["expected_result"]["relative_reduction_gte"] == 0.30
    analysis = payload["analysis"]
    assert analysis["control_failed_attempts"]["n"] == 80
    assert analysis["treatment_failed_attempts"]["n"] == 80
    assert 0.0 <= analysis["relative_reduction"] <= 1.0


def test_hypothesis_direction_preregistered():
    """Documents the pre-registered 30% claim on the synthetic world; fails if unsupported."""
    analysis = run_experiment(seed=42)["analysis"]
    assert analysis["treatment_failed_attempts"]["mean"] < analysis["control_failed_attempts"]["mean"]
    assert analysis["hypothesis_30pct_supported"] is True
