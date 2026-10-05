"""ECCA V3.0 — ejecutor matemático matricial (Fase 1).

Convierte la telemetría del host en el vector entrópico Ω_ent, evalúa el umbral PT, aplica la
atenuación escalar de Lindblad y la holonomía U(1) a una señal de 4 componentes y la proyecta con
Λ_Aegis. Antes de emitirla verifica los tres invariantes de la Sección 5; si alguno falla, o la
entrada no es finita, colapsa a un estado nulo defensivo (``status == "NULL_DEFENSIVE"`` y
``psi_norm == 0.0``) en vez de propagar NaN/inf al resto del pipeline.

Alcance: modelo numérico determinista. Los invariantes certifican consistencia numérica (traza,
fase finita, cota de atenuación); no pueden certificar un origen retrocausal de la señal.

Verificación:  mypy --strict ecca_v3_core.py test_ecca_v3_core.py && pytest test_ecca_v3_core.py
"""

import math
from dataclasses import dataclass
from typing import Final, Literal, TypedDict

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = [
    "ECCAv3Core",
    "GateStatus",
    "PTState",
    "RetrocausalResult",
    "TelemetryState",
    "Violation",
    "aegis_projector",
]

FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]

PTState = Literal["EXACT", "BROKEN"]
GateStatus = Literal["OK", "NULL_DEFENSIVE"]
Violation = Literal[
    "non_finite_input",  # ‖Ω_ent‖ o dt no finitos: no se evalúan los invariantes
    "aegis_trace",  # invariante 1: |Tr(ΛρΛ) - 1| ≥ 1e-9 (proyector corrupto)
    "amplitude_extinguished",  # ‖Ψ‖ = 0: no hay estado normalizable que certificar
    "berry_phase",  # invariante 2: holonomía no unimodular o fase no finita
    "lindblad_bounds",  # invariante 3: exp(-∫𝒟) fuera de [0, 1] (p. ej. dt < 0)
]

_DIM_AEGIS: Final = 4
_BOLTZMANN: Final = 1.380649e-23  # J/K (SI 2019)
_KELVIN_OFFSET: Final = 273.15
_MS_TO_S: Final = 1e-3
_LINDBLAD_GAIN: Final = 0.1
_TRACE_TOL: Final = 1e-9  # Sección 5, invariante 1
_UNIMODULAR_TOL: Final = 1e-12
_RANK_RTOL: Final = 1e-12
_TWO_PI: Final = 2.0 * math.pi

_GAUGE_WEIGHTS: Final[FloatArray] = np.array([0.1, 0.2, 0.15, 0.05], dtype=np.float64)
_PSI_TEMPLATE: Final[ComplexArray] = np.array([1.0, 0.5, 0.25, 0.125], dtype=np.complex128)
_GAUGE_WEIGHTS.flags.writeable = False
_PSI_TEMPLATE.flags.writeable = False


@dataclass
class TelemetryState:
    """Telemetría cruda del host; su validez numérica se juzga en `solve_retrocausal_wave`."""

    rf_variance: float  # dBm² (Radar Wi-Fi)
    shot_noise: float  # mW (Resonador Fotónico)
    squid_flux: float  # Φ/Φ₀ (Magnetómetro Cuántico)
    cpu_temp: float  # °C (ACPI / Silicio Host)
    rtt_latency: float  # ms (Fricción de Red)


class RetrocausalResult(TypedDict):
    """Salida de `ECCAv3Core.solve_retrocausal_wave`; serializable a JSON estricto."""

    psi_norm: float  # ‖Ψ_Retro(t0)‖; 0.0 en estado nulo
    coherence_factor: float  # exp(-∫𝒟_Lindblad) recortado a [0, 1]
    pt_symmetry_state: PTState
    spectral_radius: float  # ‖Ω_ent‖₂
    omega_vector: list[float]
    aegis_invariance_audit: float  # Tr(ΛρΛ) medido; 0.0 si no es evaluable
    status: GateStatus
    violations: list[Violation]  # vacío si status == "OK"


def aegis_projector(basis: ArrayLike) -> ComplexArray:
    """Λ_Aegis = Σ_n |ψ_n⟩⟨ψ_n| sobre el subespacio generado por las columnas de `basis` (4, r).

    Las columnas no tienen que ser ortonormales ni independientes: se toma el span vía SVD.
    """
    vectors = np.asarray(basis, dtype=np.complex128)
    if vectors.ndim != 2 or vectors.shape[0] != _DIM_AEGIS or vectors.shape[1] == 0:
        raise ValueError(f"la base de Aegis debe tener forma ({_DIM_AEGIS}, r>=1)")
    if not np.isfinite(vectors).all():
        raise ValueError("la base de Aegis contiene valores no finitos")
    u, s, _ = np.linalg.svd(vectors, full_matrices=False)
    rank = int(np.count_nonzero(s > s[0] * _RANK_RTOL))
    if rank == 0:
        raise ValueError("la base de Aegis no puede ser nula")
    q = u[:, :rank]
    projector = q @ q.conj().T
    return (projector + projector.conj().T) / 2.0  # hermítico exacto, no solo a redondeo


def _raw_attenuation(omega_ent: FloatArray, dt: float) -> float:
    """exp(-0.1·‖Ω‖²·dt) sin recortar, para que el invariante 3 vea las violaciones."""
    decay_rate = np.sum(omega_ent**2) * _LINDBLAD_GAIN
    return float(np.exp(-decay_rate * dt))


def _wrap_phase(theta: float) -> float:
    """Reduce un ángulo a [0, 2π); ``-1e-20 % 2π`` redondea a 2π exacto y se corrige a 0."""
    wrapped = theta % _TWO_PI
    return 0.0 if wrapped >= _TWO_PI else wrapped


def _berry_phase_ok(holonomy: complex) -> bool:
    """Invariante 2: holonomía finita y unimodular con arg ∈ [0, 2π) módulo 2π."""
    if not (math.isfinite(holonomy.real) and math.isfinite(holonomy.imag)):
        return False
    angle = _wrap_phase(math.atan2(holonomy.imag, holonomy.real))
    return abs(abs(holonomy) - 1.0) <= _UNIMODULAR_TOL and 0.0 <= angle < _TWO_PI


def _aegis_trace(projector: ComplexArray, psi: ComplexArray) -> float:
    """Tr(Λ ρ Λ) = ‖Λψ‖²/‖ψ‖² para ρ = |ψ⟩⟨ψ|/⟨ψ|ψ⟩ (estado puro); 0.0 si no es evaluable."""
    norm2 = float(np.vdot(psi, psi).real)
    if not (math.isfinite(norm2) and norm2 > 0.0):
        return 0.0
    projected = projector @ psi
    ratio = float(np.vdot(projected, projected).real) / norm2
    return ratio if math.isfinite(ratio) else 0.0


def _finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0


class ECCAv3Core:
    def __init__(
        self,
        hbar: float = 1.054571817e-34,
        gamma_crit: float = 1.85,
        aegis_basis: ArrayLike | None = None,
    ) -> None:
        """`aegis_basis` (4, r) fija el subespacio de Λ_Aegis; por defecto Λ = 𝟙₄ (sin filtrado).

        `hbar` se conserva por compatibilidad: el motor trabaja en unidades naturales y no lo usa.
        `gamma_crit = inf` desactiva el umbral PT.
        """
        if not (math.isfinite(hbar) and hbar > 0.0):
            raise ValueError(f"hbar debe ser finito y > 0, recibido {hbar!r}")
        if not gamma_crit > 0.0:  # también rechaza NaN
            raise ValueError(f"gamma_crit debe ser > 0, recibido {gamma_crit!r}")
        self.hbar = hbar
        self.gamma_crit = gamma_crit
        # Dimensión topológica fija del operador Aegis
        self.dim_aegis = _DIM_AEGIS
        self.P_aegis: ComplexArray = (
            np.eye(_DIM_AEGIS, dtype=np.complex128)
            if aegis_basis is None
            else aegis_projector(aegis_basis)
        )

    def compute_entropy_vector(self, tel: TelemetryState) -> FloatArray:
        """Calcula el vector de gradiente entrópico espacial Ω_ent.

        Componentes [RF adim., térmica J, cuántica mW·Φ/Φ₀, red s]. Las unidades son
        heterogéneas y la térmica (~1e-21) queda por debajo del épsilon de máquina frente a las
        demás, así que `cpu_temp` no altera ninguna salida (comportamiento heredado).
        """
        s_rf = np.log1p(np.maximum(0.0, tel.rf_variance))
        s_therm = (tel.cpu_temp + _KELVIN_OFFSET) * _BOLTZMANN
        s_quantum = tel.shot_noise * tel.squid_flux
        s_net = tel.rtt_latency * _MS_TO_S
        return np.array([s_rf, s_therm, s_quantum, s_net], dtype=np.float64)

    def evaluate_pt_symmetry(self, omega_ent: FloatArray) -> tuple[bool, float]:
        """Umbral escalar ‖Ω_ent‖₂ ≤ Γ_crít; no calcula el espectro de Ĥ_eff."""
        norm_omega = float(np.linalg.norm(omega_ent))
        is_exact = norm_omega <= self.gamma_crit
        return is_exact, norm_omega

    def calculate_lindblad_attenuation(self, omega_ent: FloatArray, dt: float) -> float:
        """Factor de decoherencia exp(-0.1·‖Ω‖²·dt) recortado a [0, 1].

        Sustituto escalar del factor de Lindblad: no integra el generador GKSL.
        """
        return float(np.clip(_raw_attenuation(omega_ent, dt), 0.0, 1.0))

    def solve_retrocausal_wave(self, tel: TelemetryState, dt: float = 0.01) -> RetrocausalResult:
        """Colapsa Ψ_Retro(t0) y verifica los invariantes de la Sección 5 antes de emitirlo.

        Devuelve la norma del estado y el diagnóstico de fase. Con ``status == "NULL_DEFENSIVE"``
        la amplitud es 0.0 y las magnitudes no finitas se reportan como 0.0 (JSON estricto).
        """
        with np.errstate(all="ignore"):  # los no finitos los gestiona el gate, no numpy
            omega_ent = self.compute_entropy_vector(tel)
            pt_exact, spectral_radius = self.evaluate_pt_symmetry(omega_ent)
            raw_attenuation = _raw_attenuation(omega_ent, dt)
            attenuation = float(np.clip(raw_attenuation, 0.0, 1.0))

            # Holonomía U(1) (abeliana): con una conexión escalar el ordenamiento 𝒫 es trivial.
            gauge_phase = np.exp(-1j * np.dot(omega_ent, _GAUGE_WEIGHTS))

            # Superposición de la señal modulada
            psi_raw = _PSI_TEMPLATE * gauge_phase
            psi_collapsed = self.P_aegis @ (psi_raw * attenuation)
            psi_norm = float(np.linalg.norm(psi_collapsed))

            violations: list[Violation] = []
            audit = 0.0
            if not (math.isfinite(spectral_radius) and math.isfinite(dt)):  # ‖Ω‖ finita ⇒ Ω finito
                violations.append("non_finite_input")
            else:
                if psi_norm == 0.0:
                    violations.append("amplitude_extinguished")
                else:
                    audit = _aegis_trace(self.P_aegis, psi_collapsed)
                    if not abs(audit - 1.0) < _TRACE_TOL:
                        violations.append("aegis_trace")
                if not _berry_phase_ok(complex(gauge_phase)):
                    violations.append("berry_phase")
                if not 0.0 <= raw_attenuation <= 1.0:  # NaN también cae aquí
                    violations.append("lindblad_bounds")

        healthy = not violations
        return {
            "psi_norm": psi_norm if healthy else 0.0,
            "coherence_factor": _finite_or_zero(attenuation),
            "pt_symmetry_state": "EXACT" if pt_exact else "BROKEN",
            "spectral_radius": _finite_or_zero(spectral_radius),
            "omega_vector": [_finite_or_zero(x) for x in omega_ent.tolist()],
            "aegis_invariance_audit": audit,
            "status": "OK" if healthy else "NULL_DEFENSIVE",
            "violations": violations,
        }


# Instanciación y prueba del motor
if __name__ == "__main__":
    core = ECCAv3Core()
    telemetry = TelemetryState(
        rf_variance=0.82,
        shot_noise=0.005,
        squid_flux=1.000004,
        cpu_temp=54.2,
        rtt_latency=12.4,
    )
    result = core.solve_retrocausal_wave(telemetry)
    print("Salida Tensorial para Inferencia:")
    for k, v in result.items():
        print(f"  {k}: {v}")
