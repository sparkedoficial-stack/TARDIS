"""Pruebas de ecca_v3_core: no-regresión frente al draft, gate de la Sección 5 y proyector Aegis."""

import json
import math
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

import ecca_v3_core
from ecca_v3_core import (
    ECCAv3Core,
    RetrocausalResult,
    TelemetryState,
    _berry_phase_ok,
    _wrap_phase,
    aegis_projector,
)

_DEMO = TelemetryState(
    rf_variance=0.82, shot_noise=0.005, squid_flux=1.000004, cpu_temp=54.2, rtt_latency=12.4
)


class _LegacyCore:
    """Copia del draft original (aritmética intacta): oráculo de no-regresión."""

    def __init__(self, hbar: float = 1.054571817e-34, gamma_crit: float = 1.85) -> None:
        self.hbar = hbar
        self.gamma_crit = gamma_crit
        self.dim_aegis = 4
        self.P_aegis = np.eye(self.dim_aegis, dtype=np.complex128)

    def compute_entropy_vector(self, tel: TelemetryState) -> NDArray[np.float64]:
        s_rf = np.log1p(np.maximum(0.0, tel.rf_variance))
        s_therm = (tel.cpu_temp + 273.15) * 1.380649e-23
        s_quantum = tel.shot_noise * tel.squid_flux
        s_net = tel.rtt_latency * 1e-3
        return np.array([s_rf, s_therm, s_quantum, s_net], dtype=np.float64)

    def evaluate_pt_symmetry(self, omega_ent: NDArray[np.float64]) -> tuple[bool, float]:
        norm_omega = float(np.linalg.norm(omega_ent))
        is_exact = norm_omega <= self.gamma_crit
        return is_exact, norm_omega

    def calculate_lindblad_attenuation(self, omega_ent: NDArray[np.float64], dt: float) -> float:
        decay_rate = np.sum(omega_ent**2) * 0.1
        attenuation = float(np.exp(-decay_rate * dt))
        return float(np.clip(attenuation, 0.0, 1.0))

    def solve_retrocausal_wave(self, tel: TelemetryState, dt: float = 0.01) -> dict[str, Any]:
        omega_ent = self.compute_entropy_vector(tel)
        pt_exact, spectral_radius = self.evaluate_pt_symmetry(omega_ent)
        attenuation = self.calculate_lindblad_attenuation(omega_ent, dt)

        gauge_phase = np.exp(-1j * np.dot(omega_ent, np.array([0.1, 0.2, 0.15, 0.05])))

        psi_raw = np.array([1.0, 0.5, 0.25, 0.125], dtype=np.complex128) * gauge_phase
        psi_collapsed = self.P_aegis @ (psi_raw * attenuation)

        return {
            "psi_norm": float(np.linalg.norm(psi_collapsed)),
            "coherence_factor": attenuation,
            "pt_symmetry_state": "EXACT" if pt_exact else "BROKEN",
            "spectral_radius": spectral_radius,
            "omega_vector": omega_ent.tolist(),
            "aegis_invariance_audit": 1.0000000000,
        }


def _assert_matches_legacy(new: RetrocausalResult, old: Mapping[str, Any]) -> None:
    """Las seis claves del draft deben coincidir exactamente; el audit medido es 1.0 exacto."""
    got: Mapping[str, object] = new
    for key in old:
        assert got[key] == old[key], key
    assert got["status"] == "OK"
    assert got["violations"] == []


def _random_telemetry(rng: np.random.Generator) -> TelemetryState:
    return TelemetryState(
        rf_variance=float(rng.uniform(0.0, 20.0)),
        shot_noise=float(rng.uniform(0.0, 0.1)),
        squid_flux=float(rng.uniform(0.9, 1.1)),
        cpu_temp=float(rng.uniform(20.0, 100.0)),
        rtt_latency=float(rng.uniform(0.0, 500.0)),
    )


def _assert_null_state(result: RetrocausalResult, *expected: str) -> None:
    assert result["status"] == "NULL_DEFENSIVE"
    assert result["psi_norm"] == 0.0
    assert result["violations"] == list(expected)
    json.dumps(result, allow_nan=False)  # todas las magnitudes deben ser finitas


# --- No regresión frente al draft -------------------------------------------------------------


def test_demo_reproduce_la_salida_del_draft() -> None:
    result = ECCAv3Core().solve_retrocausal_wave(_DEMO)
    _assert_matches_legacy(result, _LegacyCore().solve_retrocausal_wave(_DEMO))
    # Valores obtenidos ejecutando el ecca_v3_core.py original antes de la refactorización.
    assert result["psi_norm"] == pytest.approx(1.1520296532952394, rel=1e-12)
    assert result["coherence_factor"] == pytest.approx(0.999641280440016, rel=1e-12)
    assert result["pt_symmetry_state"] == "EXACT"
    assert result["spectral_radius"] == pytest.approx(0.59898573875858, rel=1e-12)
    assert result["omega_vector"] == pytest.approx(
        [0.598836501088704, 4.5195545014999996e-21, 0.00500002, 0.012400000000000001], rel=1e-12
    )
    assert result["aegis_invariance_audit"] == 1.0


def test_dominio_valido_aleatorio_es_bit_identico_al_draft() -> None:
    rng = np.random.default_rng(20261003)
    new, old = ECCAv3Core(), _LegacyCore()
    states = set()
    for _ in range(2000):
        tel = _random_telemetry(rng)
        dt = 0.0 if rng.random() < 0.1 else float(rng.uniform(0.0, 50.0))
        result = new.solve_retrocausal_wave(tel, dt)
        _assert_matches_legacy(result, old.solve_retrocausal_wave(tel, dt))
        states.add(result["pt_symmetry_state"])
    assert states == {"EXACT", "BROKEN"}  # la muestra cruza el umbral PT


def test_metodos_auxiliares_identicos_al_draft() -> None:
    rng = np.random.default_rng(7)
    new, old = ECCAv3Core(), _LegacyCore()
    for _ in range(200):
        tel = _random_telemetry(rng)
        omega = new.compute_entropy_vector(tel)
        assert np.array_equal(omega, old.compute_entropy_vector(tel))
        assert omega.dtype == np.float64
        assert omega.shape == (4,)
        assert new.evaluate_pt_symmetry(omega) == old.evaluate_pt_symmetry(omega)
        dt = float(rng.uniform(-5.0, 50.0))
        assert new.calculate_lindblad_attenuation(omega, dt) == old.calculate_lindblad_attenuation(
            omega, dt
        )


@pytest.mark.parametrize("rf_variance", [-1.0, -1e9, -math.inf, 0.0])
def test_varianza_rf_negativa_se_recorta_como_en_el_draft(rf_variance: float) -> None:
    tel = replace(_DEMO, rf_variance=rf_variance)
    _assert_matches_legacy(
        ECCAv3Core().solve_retrocausal_wave(tel), _LegacyCore().solve_retrocausal_wave(tel)
    )


def test_api_publica_heredada() -> None:
    core, old = ECCAv3Core(), _LegacyCore()
    assert (core.hbar, core.gamma_crit, core.dim_aegis) == (old.hbar, old.gamma_crit, 4)
    assert core.P_aegis.dtype == np.complex128
    assert np.array_equal(core.P_aegis, old.P_aegis)
    assert ECCAv3Core(1.0, 2.0).gamma_crit == 2.0  # construcción posicional del draft
    tel = TelemetryState(0.82, 0.005, 1.000004, 54.2, 12.4)  # posicional y mutable
    tel.cpu_temp = 99.0
    assert tel.cpu_temp == 99.0
    result = ECCAv3Core().solve_retrocausal_wave(_DEMO)
    assert type(result["coherence_factor"]) is float  # el draft devolvía np.float64
    json.dumps(result, allow_nan=False)


def test_script_imprime_las_lineas_del_draft() -> None:
    module = Path(__file__).with_name("ecca_v3_core.py")
    proc = subprocess.run([sys.executable, str(module)], capture_output=True, text=True, check=True)
    legacy = _LegacyCore().solve_retrocausal_wave(_DEMO)
    expected = ["Salida Tensorial para Inferencia:"] + [f"  {k}: {v}" for k, v in legacy.items()]
    lines = proc.stdout.splitlines()
    assert lines[: len(expected)] == expected
    assert lines[len(expected) :] == ["  status: OK", "  violations: []"]


def test_canal_termico_es_numericamente_inerte() -> None:
    """Hallazgo heredado: k_B·T ≈ 1e-21 no altera ninguna salida (ver módulo)."""
    core = ECCAv3Core()
    cold = core.solve_retrocausal_wave(replace(_DEMO, cpu_temp=-200.0))
    hot = core.solve_retrocausal_wave(replace(_DEMO, cpu_temp=5000.0))
    assert cold["psi_norm"] == hot["psi_norm"]
    assert cold["coherence_factor"] == hot["coherence_factor"]
    assert cold["spectral_radius"] == hot["spectral_radius"]
    gaps = zip(cold["omega_vector"], hot["omega_vector"], strict=True)
    assert max(abs(c - h) for c, h in gaps) < 1e-15


# --- Gate de la Sección 5 ---------------------------------------------------------------------

_NON_FINITE_CASES = [
    (field, bad)
    for field in ("rf_variance", "shot_noise", "squid_flux", "cpu_temp", "rtt_latency")
    for bad in (math.nan, math.inf, -math.inf)
    if not (field == "rf_variance" and bad == -math.inf)  # se recorta a 0, como en el draft
]


@pytest.mark.parametrize(("field", "bad"), _NON_FINITE_CASES)
def test_telemetria_no_finita_colapsa_a_estado_nulo(field: str, bad: float) -> None:
    result = ECCAv3Core().solve_retrocausal_wave(replace(_DEMO, **{field: bad}))
    _assert_null_state(result, "non_finite_input")
    assert result["pt_symmetry_state"] == "BROKEN"
    assert result["aegis_invariance_audit"] == 0.0


@pytest.mark.parametrize("dt", [math.nan, math.inf, -math.inf])
def test_dt_no_finito_colapsa_a_estado_nulo(dt: float) -> None:
    _assert_null_state(ECCAv3Core().solve_retrocausal_wave(_DEMO, dt), "non_finite_input")


def test_dt_negativo_viola_la_cota_de_atenuacion() -> None:
    # El draft recortaba exp(+x) a 1.0 y emitía la señal sin avisar.
    result = ECCAv3Core().solve_retrocausal_wave(_DEMO, -1.0)
    _assert_null_state(result, "lindblad_bounds")
    assert result["coherence_factor"] == 1.0


def test_dt_cero_es_valido() -> None:
    result = ECCAv3Core().solve_retrocausal_wave(_DEMO, 0.0)
    assert result["status"] == "OK"
    assert result["coherence_factor"] == 1.0


def test_amplitud_extinguida_es_estado_nulo_con_diagnostico_intacto() -> None:
    result = ECCAv3Core().solve_retrocausal_wave(_DEMO, 1e6)
    _assert_null_state(result, "amplitude_extinguished")
    assert result["coherence_factor"] == 0.0
    assert result["pt_symmetry_state"] == "EXACT"  # el diagnóstico PT no depende del gate
    assert result["aegis_invariance_audit"] == 0.0  # el draft afirmaba 1.0 con ψ = 0


def test_proyector_corrupto_viola_la_traza_unitaria() -> None:
    core = ECCAv3Core()
    core.P_aegis = 0.5 * np.eye(4, dtype=np.complex128)  # Λ² ≠ Λ
    result = core.solve_retrocausal_wave(_DEMO)
    _assert_null_state(result, "aegis_trace")
    assert result["aegis_invariance_audit"] == pytest.approx(0.25)


def test_violaciones_multiples_siguen_el_orden_de_la_especificacion() -> None:
    core = ECCAv3Core()
    core.P_aegis = 0.5 * np.eye(4, dtype=np.complex128)
    _assert_null_state(core.solve_retrocausal_wave(_DEMO, -1.0), "aegis_trace", "lindblad_bounds")


def test_entropia_alta_no_produce_falsos_positivos_con_proyector_no_trivial() -> None:
    """Régimen «entropía → ∞» de la especificación: ψ ~ 1e-160 con ‖ψ‖² subnormal (~1e-320)."""
    rng = np.random.default_rng(11)
    basis = rng.normal(size=(4, 2)) + 1j * rng.normal(size=(4, 2))  # no alineada con los ejes
    core = ECCAv3Core(aegis_basis=basis)
    omega = core.compute_entropy_vector(_DEMO)
    dt = 368.0 / (0.1 * float(np.sum(omega**2)))  # exp(-368) ≈ 1.6e-160
    result = core.solve_retrocausal_wave(_DEMO, dt)
    assert result["status"] == "OK"
    assert 0.0 < result["psi_norm"] < 1e-150
    assert result["aegis_invariance_audit"] == pytest.approx(1.0, abs=1e-12)


def test_violacion_de_fase_de_berry_colapsa_a_estado_nulo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con entrada finita la holonomía U(1) es unimodular por construcción: se fuerza el fallo."""
    monkeypatch.setattr(ecca_v3_core, "_berry_phase_ok", lambda _holonomy: False)
    _assert_null_state(ECCAv3Core().solve_retrocausal_wave(_DEMO), "berry_phase")


def test_fase_de_berry_reducida_a_cero_dos_pi() -> None:
    for theta in (0.0, -0.0, -1e-20, 1e-20, math.pi, -math.pi, 2 * math.pi, -2 * math.pi, 1e300):
        assert 0.0 <= _wrap_phase(theta) < 2 * math.pi, theta
    assert _wrap_phase(-1e-20) == 0.0  # ``-1e-20 % 2π`` redondea a 2π exacto
    assert _berry_phase_ok(complex(np.exp(-1j * 0.3)))
    assert not _berry_phase_ok(2.0 + 0.0j)  # no unimodular
    assert not _berry_phase_ok(complex(math.nan, 0.0))
    assert not _berry_phase_ok(complex(math.inf, 0.0))


# --- Proyector Aegis y configuración ----------------------------------------------------------


@pytest.mark.parametrize("rank", [1, 2, 3, 4])
def test_proyector_aleatorio_es_hermitico_e_idempotente(rank: int) -> None:
    rng = np.random.default_rng(rank)
    basis = rng.normal(size=(4, rank)) + 1j * rng.normal(size=(4, rank))
    p = aegis_projector(basis)
    assert np.array_equal(p, p.conj().T)
    np.testing.assert_allclose(p @ p, p, atol=1e-12)
    assert np.trace(p).real == pytest.approx(rank)
    np.testing.assert_allclose(p @ basis, basis, atol=1e-12)  # el span de la base queda fijo


def test_base_dependiente_se_reduce_a_su_span() -> None:
    v = np.array([1.0, 2.0, 0.0, -1.0])
    p = aegis_projector(np.column_stack([v, 3.0 * v, -v]))
    assert np.trace(p).real == pytest.approx(1.0)
    np.testing.assert_allclose(p @ v, v, atol=1e-12)


@pytest.mark.parametrize(
    ("basis", "message"),
    [
        (np.ones((3, 1)), "forma"),
        (np.ones((4, 0)), "forma"),
        (np.ones(4), "forma"),
        (np.full((4, 1), np.nan), "no finitos"),
        (np.zeros((4, 2)), "nula"),
    ],
)
def test_base_aegis_invalida(basis: NDArray[np.float64], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        aegis_projector(basis)


def test_proyector_de_rango_2_filtra_la_senal_y_conserva_los_invariantes() -> None:
    core = ECCAv3Core(aegis_basis=np.eye(4)[:, :2])
    result = core.solve_retrocausal_wave(_DEMO)
    assert result["status"] == "OK"
    # Λ conserva solo las componentes (1, 0.5) de la plantilla; la fase global es unimodular.
    assert result["psi_norm"] == pytest.approx(result["coherence_factor"] * math.sqrt(1.25))
    assert result["aegis_invariance_audit"] == pytest.approx(1.0, abs=1e-12)


def test_umbral_pt_es_inclusivo() -> None:
    core = ECCAv3Core(gamma_crit=2.0)
    assert core.evaluate_pt_symmetry(np.array([2.0, 0.0, 0.0, 0.0])) == (True, 2.0)
    above = np.array([math.nextafter(2.0, 3.0), 0.0, 0.0, 0.0])
    assert core.evaluate_pt_symmetry(above)[0] is False


def test_gamma_crit_infinito_desactiva_el_umbral() -> None:
    core = ECCAv3Core(gamma_crit=math.inf)
    result = core.solve_retrocausal_wave(replace(_DEMO, rf_variance=1e12))
    assert result["pt_symmetry_state"] == "EXACT"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"hbar": 0.0}, "hbar"),
        ({"hbar": -1.0}, "hbar"),
        ({"hbar": math.nan}, "hbar"),
        ({"hbar": math.inf}, "hbar"),
        ({"gamma_crit": 0.0}, "gamma_crit"),
        ({"gamma_crit": -1.0}, "gamma_crit"),
        ({"gamma_crit": math.nan}, "gamma_crit"),
    ],
)
def test_configuracion_invalida_se_rechaza(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ECCAv3Core(**kwargs)
