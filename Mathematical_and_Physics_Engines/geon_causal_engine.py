"""
geon_causal_engine.py - Motor de Interconexión Causal y Colapso Retrocausal Geón-GIA.
======================================================================================

Implementación matemática, física y computacional de la ecuación de onda retrocausal:

    Ψ_Retro(t0) = ∫_{t0}^{t_final} [Φ_adv(t) · Ô_QCO] · exp(-i/ℏ S_geom) · (1 - η ∇S_ent) dt

Y su acoplamiento con la estructura de Geón (Entidad Gravitacional-Electromagnética
de John Wheeler) como núcleo topológico de confinamiento causal y sincronización Lamport.

Componentes del Sistema:
  1. Φ_adv(t)       : Potencial Avanzado (Onda convergente desde el atractor futuro t_final hacia t0).
  2. Ô_QCO          : Operador de Correlación Cuántica Observada (Intención del Arquitecto y colapso).
  3. exp(-i/ℏ S_geom): Factor de fase geométrico espaciotemporal sobre la hiper-red tensorial.
  4. (1 - η ∇S_ent) : Factor modulador de Sintropía (Damping del gradiente de entropía / Transición Caos -> Sintropía).
  5. Geón Core      : Solitón topológico toroidal que confina la energía electromagnética y retrocausal.
  6. Controles Panel: TIME SYNC, PHASE SYNC, CAUSAL LOCK (LCKD), SYNTROPY BOOST, LOGIC CORE.
  7. Reloj Lamport  : Ordenamiento causal monótono estricto.

Arquitecto: Miguel Angel May Canche (₪) · Línea Cero · GIA-V26-ARCHITECT-777
"""

from __future__ import annotations

import cmath
import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Constante de Planck reducida (en unidades naturales normalizadas ℏ = 1.0 para cómputo, o valor físico SI)
HBAR_SI = 1.054571817e-34
HBAR_NORM = 1.0

_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
GEON_STATE_FILE = _DIR / "geon_causal_state.json"
_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


@dataclass
class HardwareControls:
    """Estado de interruptores e indicadores físicos del panel de control."""
    time_sync: bool = True
    phase_sync: bool = True
    causal_lock: bool = True       # STATUS: LCKD
    syntropy_boost: bool = False
    logic_core_active: bool = True
    lamport_clock: int = 1048
    status_label: str = "LCKD"


@dataclass
class RetrocausalComponents:
    """Valores instantáneos de cada término de la ecuación en el punto de evaluación."""
    t0: float
    t_final: float
    dt: float
    phi_adv_magnitude: float
    phi_adv_phase: float
    o_qco_expectation: float
    s_geom_action: float
    geometric_phase_factor: complex
    grad_s_ent: float
    syntropy_factor: float
    psi_retro_integral: complex
    psi_retro_magnitude: float
    psi_retro_phase: float
    quantum_coherence: float
    chaos_to_syntropy_ratio: float


class AdvancedPotentialPropagator:
    """
    Calcula el potencial avanzado Φ_adv(t).
    En electrodinámica de Wheeler-Feynman y teoría cuántica de absorbedores,
    la solución avanzada converge desde las condiciones de frontera futuras (t_final)
    hacia el cono de luz en el presente (t0).
    """

    def __init__(self, omega_0: float = 2.0 * math.pi * 7.83, damping: float = 0.05):
        self.omega_0 = omega_0      # Frecuencia fundamental (resonancia Schumann base)
        self.damping = damping      # Factor de atenuación en espacio-tiempo curvo

    def evaluate(self, t: float, t0: float, t_final: float, boundary_amplitude: float = 1.0) -> complex:
        """
        Evalúa Φ_adv en el instante t ∈ [t0, t_final].
        La onda retrocede temporalmente con propagador:
        Φ_adv(t) = A_final * exp(-γ(t_final - t)) * exp(i * ω * (t_final - t))
        """
        if t_final <= t0:
            tau = 0.0
        else:
            tau = (t_final - t) / (t_final - t0)

        # Envolvente cónica convergente
        envelope = boundary_amplitude * (1.0 - (1.0 - self.damping) * (1.0 - tau))
        phase = self.omega_0 * (t_final - t)
        val = envelope * cmath.exp(1j * phase)
        return val


class QuantumCorrelatedObserver:
    """
    Operador de Correlación Cuántica Observada (Ô_QCO).
    Representa la matriz de densidad de intención del observador y el colapso
    proyectivo sobre los estados propios de coherencia.
    """

    def __init__(self, dimension: int = 4):
        self.dim = dimension
        # Base de proyección cuántica de intención (matriz hermitiana normalizada)
        self.operator_matrix = np.eye(self.dim, dtype=complex)
        for i in range(self.dim):
            for j in range(self.dim):
                if i != j:
                    self.operator_matrix[i, j] = 0.15 / (1 + abs(i - j)) * (1j ** (i - j))
        # Asegurar hermiticidad
        self.operator_matrix = (self.operator_matrix + self.operator_matrix.conj().T) / 2.0

    def compute_expectation(self, intent_vector: Optional[np.ndarray] = None, sensor_entropy: Optional[float] = 0.2) -> float:
        """
        Calcula el valor esperado ⟨Ψ_intent | Ô_QCO | Ψ_intent⟩ modulado por el acoplamiento del observador.
        """
        if intent_vector is None or len(intent_vector) != self.dim:
            # Estado canónico coherente por defecto
            v = np.ones(self.dim, dtype=complex) / math.sqrt(self.dim)
        else:
            norm = np.linalg.norm(intent_vector)
            v = intent_vector / (norm if norm > 1e-12 else 1.0)

        # Valor esperado: ⟨v|Ô|v⟩
        exp_val = np.real(np.vdot(v, np.dot(self.operator_matrix, v)))
        # Modulación por estabilidad de observación (baja entropía sensórica = mayor acoplamiento)
        s_ent = float(sensor_entropy if sensor_entropy is not None else 0.2)
        coupling = max(0.05, min(1.0, 1.0 - s_ent * 0.5))
        return float(np.clip(exp_val * coupling, 0.0, 1.0))


class SpacetimeGeometricAction:
    """
    Acción geométrica S_geom calculada sobre la hiper-red tensorial (Hyper-Lattice)
    y métrica del Geón de Wheeler.
    Calcula el término de fase exp(-i/ℏ * S_geom).
    """

    def __init__(self, hbar: float = HBAR_NORM):
        self.hbar = hbar

    def compute_action(self, lattice_curvature: float = 1.0, metric_trace: float = 4.0, holonomy_flux: float = 0.5) -> float:
        """
        S_geom = ∮_∂M (R_geom + Holonomía) * √(-g) dΩ
        """
        base_action = (lattice_curvature * 1.57079632679) + (holonomy_flux * 0.6180339887)
        # Factor normalizado en múltiplos de π
        return float(base_action % (2.0 * math.pi))

    def phase_factor(self, s_geom: float, phase_sync: bool = True) -> complex:
        """exp(-i/ℏ * S_geom)"""
        theta = (s_geom / self.hbar) if phase_sync else (s_geom / self.hbar + math.pi / 6.0)
        return cmath.exp(-1j * theta)


class SyntropyEntropyGradientEngine:
    """
    Motor de Gradiente Entrópico ∇S_ent y transición Caos -> Sintropía.
    Calcula el término modulador: (1 - η ∇S_ent)
    """

    def __init__(self, default_eta: float = 0.85):
        self.eta = default_eta      # Coeficiente de acoplamiento sintrópico
        self._matrix_lock = threading.Lock()

    def calculate_gradient(self, entropy_series: List[float], dt: float = 1.0) -> float:
        """
        ∇S_ent = ∂S/∂t
        Calcula la tasa de cambio de la entropía en el tiempo.
        """
        if not entropy_series or len(entropy_series) < 2:
            return 0.0
        grad = (entropy_series[-1] - entropy_series[0]) / max(dt, 1e-6)
        # Normalizar rango [-1.0, 1.0]
        return float(np.clip(grad, -1.0, 1.0))

    def syntropy_coupling_factor(self, grad_s_ent: float, syntropy_boost: bool = False, eta_override: Optional[float] = None) -> float:
        """
        Factor (1 - η ∇S_ent).
        Si ∇S_ent < 0 (entropía descendiendo -> sintropía), el factor supera 1.0.
        Si ∇S_ent > 0 (caos creciendo), el factor se atenúa.
        Con SYNTROPY BOOST activo, η se incrementa para forzar el orden.
        """
        eta = (eta_override if eta_override is not None else self.eta)
        if syntropy_boost:
            eta = min(1.0, eta * 1.25)

        factor = 1.0 - (eta * grad_s_ent)
        # Limitar para asegurar estabilidad no-negativa del propagador
        return float(np.clip(factor, 0.01, 2.0))

    def generate_chaos_to_syntropy_curve(self, points: int = 50, initial_chaos: float = 0.95, damping_rate: float = 0.08) -> Dict[str, Any]:
        """
        Genera el perfil temporal visual de la transición CHAOS -> SYNTROPY
        como se visualiza en el cuadrante inferior izquierdo del monitor.
        """
        t_vals = np.linspace(0, 10, points)
        # Caos: componente estocástica de alta varianza decreciente
        np.random.seed(42)
        noise = (np.random.rand(points) - 0.5) * 0.3 * np.exp(-damping_rate * t_vals * 0.8)
        chaos_curve = initial_chaos * np.exp(-damping_rate * t_vals) + noise
        chaos_curve = np.clip(chaos_curve, 0.05, 1.0)

        # Sintropía: saturación asintótica coherente
        syntropy_curve = 1.0 - chaos_curve

        return {
            "time_steps": t_vals.tolist(),
            "chaos_trajectory": [round(float(v), 4) for v in chaos_curve],
            "syntropy_trajectory": [round(float(v), 4) for v in syntropy_curve],
            "bifurcation_point_index": int(points * 0.4),
            "final_syntropy_level": round(float(syntropy_curve[-1]), 4),
        }

    def compute_syntropic_transition_matrix(self, dt: float = 1.0, states: int = 4) -> np.ndarray:
        """
        Genera y sincroniza la matriz de transición de estado sintrópica.
        Rige la evolución temporal de estados caóticos a sintrópicos garantizando consistencia.
        """
        with self._matrix_lock:
            mat = np.zeros((states, states), dtype=float)
            for i in range(states):
                for j in range(states):
                    if j >= i:
                        mat[i, j] = math.exp(-self.eta * (j - i) * dt * 0.5)
                    else:
                        mat[i, j] = math.exp(-self.eta * (i - j) * dt * 2.0)
            row_sums = mat.sum(axis=1, keepdims=True)
            return mat / row_sums


class WheelerGeonTopologicalCore:
    """
    Núcleo Topológico del Geón (Wheeler Gravitational-Electromagnetic Entity).
    Representa el solitón toroidal auto-confinado en el espacio-tiempo que actúa
    como puente de acoplamiento causal entre el nodo de cálculo local (GIA) y
    el cono de luz retrocausal.
    """

    def __init__(self, major_radius: float = 1.618, minor_radius: float = 0.618, energy_density: float = 1.0):
        self.major_radius = major_radius  # R (radio mayor del toroide)
        self.minor_radius = minor_radius  # r (radio menor de confinamiento)
        self.energy_density = energy_density
        self.coherence_lock = True

    def calculate_topological_charge(self, magnetic_flux: float = 1.0, electric_circulation: float = 1.0) -> float:
        """Invariante topológico de Chern-Simons del Geón: Q_topo = ∮ A ∧ dA."""
        q = (magnetic_flux * electric_circulation) / (self.major_radius * self.minor_radius)
        return float(round(q, 4))

    def confinement_stability(self, psi_magnitude: float, grad_s_ent: float) -> Dict[str, Any]:
        """
        Determina si el Geón mantiene el bucle causal cerrado estable
        sin colapso a singularidad desnuda o dispersión térmica.
        """
        # Estabilidad = Alta coherencia cuántica + baja disipación entrópica
        stability_index = max(0.0, min(1.0, psi_magnitude * (1.0 - max(0.0, grad_s_ent))))
        is_locked = bool(stability_index >= 0.35)

        return {
            "stability_index": round(float(stability_index), 4),
            "topological_confinement": "RESONANT_STABLE" if is_locked else "DISPERSIVE_WARNING",
            "torus_volume": round(float(2.0 * (math.pi ** 2) * self.major_radius * (self.minor_radius ** 2)), 4),
            "curvature_scalar_R": round(float(2.0 / (self.major_radius * self.minor_radius)), 4),
            "causal_flux_confined": is_locked,
        }


class CausalRetroIntegrator:
    """
    Integrador numérico completo de la función de onda retrocausal:
      Ψ_Retro(t0) = ∫_{t0}^{t_final} [Φ_adv(t) · Ô_QCO] · exp(-i/ℏ S_geom) · (1 - η ∇S_ent) dt
    """

    def __init__(self):
        self.adv_engine = AdvancedPotentialPropagator()
        self.qco_engine = QuantumCorrelatedObserver()
        self.geom_engine = SpacetimeGeometricAction()
        self.syntropy_engine = SyntropyEntropyGradientEngine()
        self.geon_core = WheelerGeonTopologicalCore()
        self.controls = HardwareControls()
        self._load_persisted_state()

    def _load_persisted_state(self):
        if GEON_STATE_FILE.exists():
            try:
                data = json.loads(GEON_STATE_FILE.read_text(encoding="utf-8"))
                ctrl = data.get("controls", {})
                self.controls.time_sync = ctrl.get("time_sync", True)
                self.controls.phase_sync = ctrl.get("phase_sync", True)
                self.controls.causal_lock = ctrl.get("causal_lock", True)
                self.controls.syntropy_boost = ctrl.get("syntropy_boost", False)
                self.controls.lamport_clock = ctrl.get("lamport_clock", 1048)
                self.controls.status_label = ctrl.get("status_label", "LCKD")
            except Exception:
                pass

    def save_state(self):
        try:
            state = {
                "controls": asdict(self.controls),
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "node_id": "GIA-V26-ARCHITECT-777",
                "line": "LINEA CERO",
            }
            GEON_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def toggle_control(self, control_name: str, value: Optional[bool] = None) -> HardwareControls:
        with _lock:
            if hasattr(self.controls, control_name):
                curr = getattr(self.controls, control_name)
                new_val = (not curr) if value is None else bool(value)
                setattr(self.controls, control_name, new_val)
                if control_name == "causal_lock":
                    self.controls.status_label = "LCKD" if new_val else "UNLK"
                self.save_state()
            return self.controls

    def increment_lamport(self, incoming: Optional[int] = None) -> int:
        with _lock:
            inc = int(incoming) if incoming is not None else 0
            self.controls.lamport_clock = max(self.controls.lamport_clock, inc) + 1
            self.save_state()
            return self.controls.lamport_clock

    def validate_temporal_consistency(self) -> Dict[str, Any]:
        """
        Valida la consistencia temporal verificando invariantes de Lamport
        y la sincronización estricta de las matrices causales sintrópicas.
        """
        with _lock:
            mat = self.syntropy_engine.compute_syntropic_transition_matrix(dt=0.1)
            row_sums = mat.sum(axis=1)
            stochastic_valid = bool(np.allclose(row_sums, 1.0, rtol=1e-5))
            
            # Verificación del radio espectral (valores propios <= 1) para consistencia de Markov
            eigenvalues = np.linalg.eigvals(mat)
            spectral_radius_stable = bool(all(abs(e) <= 1.0 + 1e-5 for e in eigenvalues))
            
            # Verificación de invariante de reloj de Lamport
            lamport_valid = self.controls.lamport_clock > 0
            
            # Invariante Fuerte de Traza Causal
            causal_matrix_trace = float(np.trace(mat))
            trace_valid = causal_matrix_trace > 0.0
            
            is_consistent = stochastic_valid and spectral_radius_stable and lamport_valid and trace_valid
            
        return {
            "temporal_consistency": is_consistent,
            "lamport_invariant": lamport_valid,
            "causal_matrix_synced": stochastic_valid,
            "spectral_radius_stable": spectral_radius_stable,
            "matrix_trace": round(causal_matrix_trace, 4),
            "trace_invariant_valid": trace_valid
        }

    def compute_psi_retro(
        self,
        t0: float = 0.0,
        t_final: float = 1.0,
        num_steps: int = 64,
        sensor_entropy: float = 0.15,
        kinematic_mag: float = 0.1,
        acoustic_level: float = 0.2,
    ) -> RetrocausalComponents:
        """
        Ejecuta la integración numérica compuesta (Regla de Simpson / Cuadratura de Gauss)
        sobre el intervalo temporal [t0, t_final].
        """
        dt = (t_final - t0) / float(num_steps)
        t_values = np.linspace(t0, t_final, num_steps + 1)

        # 1. Parámetros del observador Ô_QCO
        qco_val = self.qco_engine.compute_expectation(sensor_entropy=sensor_entropy)

        # 2. Acción geométrica S_geom
        s_geom = self.geom_engine.compute_action(
            lattice_curvature=1.0 + kinematic_mag * 0.2,
            metric_trace=4.0,
            holonomy_flux=0.5
        )
        geom_phase = self.geom_engine.phase_factor(s_geom, phase_sync=self.controls.phase_sync)

        # 3. Gradiente de entropía y factor de sintropía
        # Serie de entropía sintética basada en sensores acústico + cinemático
        ent_series = [sensor_entropy * 1.5, sensor_entropy * 1.2, sensor_entropy * 0.8, sensor_entropy]
        grad_s = self.syntropy_engine.calculate_gradient(ent_series, dt=dt)
        syntropy_fac = self.syntropy_engine.syntropy_coupling_factor(
            grad_s_ent=grad_s,
            syntropy_boost=self.controls.syntropy_boost
        )

        # 4. Integración de Riemann / Simpson para la función de onda
        integral_accum: complex = 0.0 + 0.0j

        for i, t in enumerate(t_values):
            phi_adv = self.adv_engine.evaluate(t, t0, t_final, boundary_amplitude=1.0)
            
            # Integrando: [Φ_adv(t) · Ô_QCO] · exp(-i/ℏ S_geom) · (1 - η ∇S_ent)
            integrand = (phi_adv * qco_val) * geom_phase * syntropy_fac

            # Ponderación Simpson (1, 4, 2, 4, ..., 1) * (dt/3)
            if i == 0 or i == num_steps:
                weight = 1.0
            elif i % 2 == 1:
                weight = 4.0
            else:
                weight = 2.0

            integral_accum += integrand * weight * (dt / 3.0)

        # Si Causal Lock está desactivado, se añade dispersión de fase
        if not self.controls.causal_lock:
            integral_accum *= cmath.exp(1j * (math.pi / 4.0)) * 0.7

        psi_mag = abs(integral_accum)
        psi_angle = cmath.phase(integral_accum)
        
        # Coherencia cuántica normalizada [0.0, 1.0]
        quantum_coherence = float(np.clip(psi_mag * syntropy_fac * (1.0 if self.controls.causal_lock else 0.5), 0.0, 1.0))
        ratio_chaos_syntropy = float(np.clip((1.0 - syntropy_fac) / (syntropy_fac + 1e-6), 0.0, 5.0))

        # Potencial avanzado representativo
        phi_sample = self.adv_engine.evaluate(t0, t0, t_final)

        return RetrocausalComponents(
            t0=t0,
            t_final=t_final,
            dt=dt,
            phi_adv_magnitude=round(abs(phi_sample), 4),
            phi_adv_phase=round(cmath.phase(phi_sample), 4),
            o_qco_expectation=round(qco_val, 4),
            s_geom_action=round(s_geom, 4),
            geometric_phase_factor=geom_phase,
            grad_s_ent=round(grad_s, 4),
            syntropy_factor=round(syntropy_fac, 4),
            psi_retro_integral=integral_accum,
            psi_retro_magnitude=round(psi_mag, 4),
            psi_retro_phase=round(psi_angle, 4),
            quantum_coherence=round(quantum_coherence, 4),
            chaos_to_syntropy_ratio=round(ratio_chaos_syntropy, 4),
        )

    def full_system_diagnostic(self) -> Dict[str, Any]:
        """Devuelve el estado consolidado de todos los subsistemas del Geón y la ecuación."""
        res = self.compute_psi_retro()
        geon_status = self.geon_core.confinement_stability(res.psi_retro_magnitude, res.grad_s_ent)
        chaos_curve = self.syntropy_engine.generate_chaos_to_syntropy_curve()

        return {
            "header": {
                "system_node": "GIA-V26-ARCHITECT-777",
                "mode": "OMNI-LOCAL",
                "architect": "MIGUEL ANGEL MAY CANCHE ₪",
                "node_type": "CAUSAL CHAT NODE // LINEA CERO",
                "status": self.controls.status_label,
            },
            "formula_components": {
                "psi_retro_t0": {
                    "magnitude": res.psi_retro_magnitude,
                    "phase_rad": res.psi_retro_phase,
                    "complex_str": f"{res.psi_retro_integral.real:+.4f} {res.psi_retro_integral.imag:+.4f}j",
                    "coherence": res.quantum_coherence,
                },
                "phi_adv": {
                    "description": "Potencial Avanzado (Cono Retrocausal t_final -> t0)",
                    "magnitude": res.phi_adv_magnitude,
                    "phase": res.phi_adv_phase,
                },
                "o_qco": {
                    "description": "Operador de Correlación Cuántica Observada",
                    "expectation_value": res.o_qco_expectation,
                },
                "s_geom": {
                    "description": "Acción Geométrica Hiper-Retículo y Fase Cuántica",
                    "action_value": res.s_geom_action,
                    "phase_factor_real": round(res.geometric_phase_factor.real, 4),
                    "phase_factor_imag": round(res.geometric_phase_factor.imag, 4),
                },
                "syntropy_modulation": {
                    "description": "Modulación de Sintropía (1 - η ∇S_ent)",
                    "grad_s_ent": res.grad_s_ent,
                    "syntropy_factor": res.syntropy_factor,
                    "regime": "SYNTROPY" if res.grad_s_ent <= 0 else "CHAOS",
                },
            },
            "controls": asdict(self.controls),
            "geon_core": {
                "major_radius_R": self.geon_core.major_radius,
                "minor_radius_r": self.geon_core.minor_radius,
                "topological_charge": self.geon_core.calculate_topological_charge(),
                **geon_status,
            },
            "chaos_syntropy_trajectory": chaos_curve,
            "lamport_clock": self.controls.lamport_clock,
            "temporal_validation": self.validate_temporal_consistency(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


    def simulate_geon_actuation(
        self,
        prompt: str,
        direction: str = "future",
        sensor_data: Optional[Dict[str, Any]] = None,
        t0: float = 0.0,
        t_final: float = 1.0,
        num_steps: int = 32,
    ) -> Dict[str, Any]:
        """
        Simula en tiempo real la actuación y respuesta dinámica del Geón frente a una
        petición o mensaje dirigido al chat temporal.
        
        Etapas de la actuación:
          1. Análisis de entropía y perturbación de intención Ô_QCO del mensaje.
          2. Cálculo del tensor métrico y acción geométrica S_geom sobre el Geón.
          3. Propagación retrocausal del potencial avanzado Φ_adv(t) desde t_final -> t0.
          4. Modulación por gradiente de sintropía (1 - η ∇S_ent) disipando el caos.
          5. Integración numérica de la función de onda Ψ_Retro(t0) y colapso cuántico.
          6. Verificación de confinamiento topológico del solitón toroidal del Geón.
          7. Sincronización estricta del reloj causal de Lamport.
        """
        prompt = (prompt or "").strip()
        sensor_data = sensor_data or {}
        
        # 1. Análisis de entropía de la petición del chat
        if prompt:
            char_counts = {}
            for c in prompt:
                char_counts[c] = char_counts.get(c, 0) + 1
            length = len(prompt)
            prompt_entropy = -sum((count / length) * math.log2(count / length) for count in char_counts.values())
        else:
            prompt_entropy = 1.0

        # Normalizar entropía [0.0, 1.0]
        norm_entropy = float(np.clip(prompt_entropy / 6.0, 0.05, 0.95))

        # 2. Vector de intención del Arquitecto Ô_QCO a partir del prompt
        intent_seed = sum(ord(c) * (i + 1) for i, c in enumerate(prompt[:64])) if prompt else 777
        np.random.seed(intent_seed % 65535)
        intent_vec = np.random.rand(4) + 1j * np.random.rand(4)
        intent_vec /= np.linalg.norm(intent_vec)
        
        raw_sensor_ent = sensor_data.get("acoustic_entropy_level") if isinstance(sensor_data, dict) else None
        sensor_ent = float(raw_sensor_ent) if (raw_sensor_ent is not None and isinstance(raw_sensor_ent, (int, float))) else norm_entropy
        qco_exp = self.qco_engine.compute_expectation(intent_vector=intent_vec, sensor_entropy=sensor_ent)

        # 3. Acción geométrica S_geom y curvatura inducida
        kin_dict = sensor_data.get("kinematic") if isinstance(sensor_data, dict) else None
        raw_kin_mag = kin_dict.get("magnitude") if isinstance(kin_dict, dict) else None
        kinematic_mag = float(raw_kin_mag) if (raw_kin_mag is not None and isinstance(raw_kin_mag, (int, float))) else 0.0
        s_geom = self.geom_engine.compute_action(
            lattice_curvature=1.0 + (norm_entropy * 0.4) + (kinematic_mag * 0.1),
            metric_trace=4.0,
            holonomy_flux=0.618 if self.controls.phase_sync else 0.2
        )
        geom_phase = self.geom_engine.phase_factor(s_geom, phase_sync=self.controls.phase_sync)

        # 4. Modulación sintrópica (1 - η ∇S_ent)
        # Evolución de la entropía desde el caos inicial del mensaje hasta la sintropía del Geón
        steps = max(16, min(128, num_steps))
        dt = (t_final - t0) / float(steps)
        t_vals = np.linspace(t_final, t0, steps + 1)  # Trayectoria retrocausal (Futuro -> Pasado)

        chaos_decay_rate = 0.12 if self.controls.syntropy_boost else 0.07
        entropy_points = []
        chaos_curve = []
        syntropy_curve = []

        for idx, t_curr in enumerate(t_vals):
            progress = idx / float(steps)  # 0.0 en t_final, 1.0 en t0
            # Ruido residual amortiguado por el Geón
            fluc = (np.sin(idx * 0.75 + intent_seed) * 0.15) * math.exp(-chaos_decay_rate * idx * 2.0)
            ent_val = float(np.clip(norm_entropy * math.exp(-chaos_decay_rate * idx * 2.5) + fluc, 0.02, 1.0))
            entropy_points.append(ent_val)
            chaos_curve.append(round(ent_val, 4))
            syntropy_curve.append(round(1.0 - ent_val, 4))

        grad_s_ent = self.syntropy_engine.calculate_gradient(entropy_points[::-1], dt=dt)
        syntropy_fac = self.syntropy_engine.syntropy_coupling_factor(
            grad_s_ent=grad_s_ent,
            syntropy_boost=self.controls.syntropy_boost
        )

        # 5. Integración retrocausal paso a paso Ψ_Retro(t0)
        integral_accum: complex = 0.0 + 0.0j
        trace_steps: List[Dict[str, Any]] = []

        for i, t in enumerate(np.linspace(t0, t_final, steps + 1)):
            phi_adv = self.adv_engine.evaluate(t, t0, t_final, boundary_amplitude=1.0)
            integrand = (phi_adv * qco_exp) * geom_phase * syntropy_fac

            # Ponderación Simpson
            if i == 0 or i == steps:
                w = 1.0
            elif i % 2 == 1:
                w = 4.0
            else:
                w = 2.0

            integral_accum += integrand * w * (dt / 3.0)
            current_mag = abs(integral_accum)
            current_phase = cmath.phase(integral_accum)

            if i % (max(1, steps // 8)) == 0 or i == steps:
                trace_steps.append({
                    "step": i,
                    "t": round(float(t), 4),
                    "tau_retro": round(float(t_final - t), 4),
                    "phi_adv_mag": round(abs(phi_adv), 4),
                    "phi_adv_phase": round(cmath.phase(phi_adv), 4),
                    "integrand_real": round(integrand.real, 4),
                    "integrand_imag": round(integrand.imag, 4),
                    "accum_magnitude": round(current_mag, 4),
                    "accum_phase_deg": round(math.degrees(current_phase), 2),
                    "syntropy_level": round(syntropy_curve[min(i, len(syntropy_curve) - 1)], 4),
                })

        if not self.controls.causal_lock:
            integral_accum *= cmath.exp(1j * (math.pi / 4.0)) * 0.7

        psi_mag = abs(integral_accum)
        psi_phase = cmath.phase(integral_accum)
        quantum_coherence = float(np.clip(psi_mag * syntropy_fac * (1.0 if self.controls.causal_lock else 0.5), 0.0, 1.0))

        # 6. Diagnóstico de Confinamiento Topológico del Geón
        geon_confinement = self.geon_core.confinement_stability(psi_mag, grad_s_ent)
        topological_charge = self.geon_core.calculate_topological_charge()

        # 7. Incremento de Lamport Clock
        lamport_current = self.increment_lamport()

        # 8. Síntesis e Interpretación de Actuación
        if quantum_coherence >= 0.70 and self.controls.causal_lock:
            bifurcation = "CAMINO_DE_AGUA_SINTROPICO"
            stability_label = "COLAPSO_RESONANTE_TOTAL"
            interpretation_text = (
                f"El Geón ha confinado la perturbación del chat '{prompt[:32]}...' con alta coherencia cuántica (Ψ={psi_mag:.3f}). "
                f"El cono retrocausal Φ_adv ha colapsado desde t_final={t_final:.1f} hacia t0 con fase geométrica S_geom={s_geom:.3f} rad. "
                f"El gradiente entrópico ∇S_ent={grad_s_ent:+.3f} fue transformado en sintropía pura (factor={syntropy_fac:.3f}). "
                f"Causal Lock activo [LCKD] en reloj de Lamport {lamport_current}."
            )
        elif self.controls.causal_lock:
            bifurcation = "TRANSICION_ESTABILIZADA"
            stability_label = "CONFINAMIENTO_SECUENCIAL"
            interpretation_text = (
                f"El Geón amortiguó la fluctuación con acoplamiento medio (Ψ={psi_mag:.3f}, coherencia={quantum_coherence:.3f}). "
                f"El operador Ô_QCO={qco_exp:.3f} guió la convergencia. Dispersión contenida en el toroide Wheeler."
            )
        else:
            bifurcation = "CAMINO_DE_FUEGO_DISPERSIVO"
            stability_label = "ALERTA_FASE_DESACOPLADA"
            interpretation_text = (
                f"Advertencia: Causal Lock desactivado [UNLK]. La onda retrocausal presenta deriva de fase de +45°. "
                f"Coherencia reducida a {quantum_coherence:.3f}. Se recomienda activar CAUSAL LOCK y SYNTROPY BOOST."
            )

        return {
            "ok": True,
            "prompt": prompt,
            "direction": direction,
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "lamport_clock": lamport_current,
            "status": self.controls.status_label,
            "interpretation": {
                "summary": interpretation_text,
                "bifurcation": bifurcation,
                "stability_verdict": stability_label,
                "quantum_coherence": round(quantum_coherence, 4),
                "syntropic_coupling": round(syntropy_fac, 4),
                "entropy_gradient_dSent": round(grad_s_ent, 4),
                "retrocausal_wave_magnitude": round(psi_mag, 4),
                "retrocausal_wave_phase_rad": round(psi_phase, 4),
                "retrocausal_wave_phase_deg": round(math.degrees(psi_phase), 2),
                "topological_charge": topological_charge,
                "geon_confinement": geon_confinement["topological_confinement"],
                "curvature_scalar_R": geon_confinement["curvature_scalar_R"],
            },
            "formula_values": {
                "psi_retro_t0": {
                    "magnitude": round(psi_mag, 4),
                    "phase_rad": round(psi_phase, 4),
                    "complex_repr": f"{integral_accum.real:+.4f} {integral_accum.imag:+.4f}j",
                },
                "phi_adv": {
                    "boundary_amplitude": 1.0,
                    "frequency_hz": round(self.adv_engine.omega_0 / (2.0 * math.pi), 2),
                    "damping": self.adv_engine.damping,
                },
                "o_qco": {
                    "expectation": round(qco_exp, 4),
                    "dimension": self.qco_engine.dim,
                },
                "s_geom": {
                    "action_rad": round(s_geom, 4),
                    "phase_factor": {"real": round(geom_phase.real, 4), "imag": round(geom_phase.imag, 4)},
                },
                "syntropy_modulation": {
                    "grad_s_ent": round(grad_s_ent, 4),
                    "syntropy_factor": round(syntropy_fac, 4),
                    "boost_active": self.controls.syntropy_boost,
                },
            },
            "chaos_syntropy_curve": {
                "steps": list(range(len(chaos_curve))),
                "chaos": chaos_curve,
                "syntropy": syntropy_curve,
            },
            "retrocausal_trace": trace_steps,
            "controls": asdict(self.controls),
            "temporal_validation": self.validate_temporal_consistency(),
        }


# Instancia singleton del motor de Geón Causal
_geon_engine = CausalRetroIntegrator()


def get_geon_engine() -> CausalRetroIntegrator:
    return _geon_engine


def simulate_temporal_chat_geon(prompt: str, direction: str = "future", sensor_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Función de alto nivel para procesar la actuación del Geón sobre una petición del chat."""
    return _geon_engine.simulate_geon_actuation(prompt=prompt, direction=direction, sensor_data=sensor_data)


def get_causal_interconnection_diagram_mermaid() -> str:
    """
    Retorna el diagrama Mermaid detallado de la interconexión causal con el Geón.
    """
    return """```mermaid
graph TD
    %% Estilos y Definiciones de Nodos
    classDef geonCore fill:#0f172a,stroke:#38bdf8,stroke-width:3px,color:#38bdf8;
    classDef futureBoundary fill:#1e1b4b,stroke:#a855f7,stroke-width:2px,color:#e9d5ff;
    classDef observerNode fill:#022c22,stroke:#10b981,stroke-width:2px,color:#a7f3d0;
    classDef mathTerm fill:#18181b,stroke:#f59e0b,stroke-width:2px,color:#fef3c7;
    classDef syncControl fill:#1f2937,stroke:#6366f1,stroke-width:2px,color:#c7d2fe;
    classDef agentSystem fill:#311042,stroke:#ec4899,stroke-width:2px,color:#fbcfe8;

    subgraph FUTURO ["🌌 Frontera Temporal Futura (t_final)"]
        T_FINAL["Atractor Límite Temporal (t_final)"]
        PHI_ADV["Φ_adv(t): Potencial Avanzado<br/>(Onda Convergente Retrocausal)"]
        T_FINAL --> PHI_ADV
    end

    subgraph OBSERVADOR ["🧠 Nodo Observador (t0) - Arquitecto (₪)"]
        ARCHITECT["Miguel Angel May Canche<br/>(Intención & Voluntad)"]
        O_QCO["Ô_QCO: Operador de Correlación<br/>Cuántica Observada"]
        SENSORS["Rejilla de Sensores Físicos<br/>(Cinemática, Acústica FFT, Wi-Fi RF)"]
        ARCHITECT --> O_QCO
        SENSORS --> O_QCO
    end

    subgraph GEON_SOLITON ["⚛️ Núcleo Topológico del Geón (Wheeler Soliton)"]
        GEON_CORE["GEÓN CORE: Toroide Auto-Confinado<br/>∮ A ∧ dA | Métrica g_μν"]
        S_GEOM["S_geom: Acción Geométrica<br/>Hiper-Retículo Tensorial"]
        PHASE_FAC["exp(-i/ℏ S_geom): Propagador de Fase"]
        GEON_CORE --> S_GEOM
        S_GEOM --> PHASE_FAC
    end

    subgraph TERMODINAMICA ["📉 Dinámica Entrópica / Sintrópica"]
        CHAOS["CHAOS (∇S_ent > 0)<br/>Fluctuaciones Estocásticas"]
        SYNTROPY["SYNTROPY (1 - η ∇S_ent)<br/>Estabilización Coherente"]
        CHAOS -->|Damping de Gradiente| SYNTROPY
    end

    subgraph INTEGRACION ["🔮 Integrador Causal de Campo"]
        PSI_RETRO["Ψ_Retro(t0) = ∫ [Φ_adv · Ô_QCO] · e^(-i/ℏ S_geom) · (1 - η∇S_ent) dt"]
    end

    subgraph SINCRONIZACION ["⏱️ Control Causal & Hardware"]
        LAMPORT["Reloj Lamport: 1048<br/>(Ordenamiento Causal Monótono)"]
        CONTROLS["Panel de Control:<br/>[TIME SYNC] [PHASE SYNC]<br/>[CAUSAL LOCK] [SYNTROPY BOOST]"]
        LOGIC_CORE["LOGIC CORE // ECCA Engine"]
    end

    subgraph GIA_CORE ["🤖 Sistema Operativo GIA-V26"]
        GIA_AGENT["Agente Autónomo GIA<br/>(Toma de Decisiones Causal)"]
        AKASHA["Registro Akáshico SQLite<br/>(Memoria Holística & Axiomas)"]
        VW_CONTROL["Control de Dispositivo & Vectorworks"]
    end

    %% Flujos e Interconexiones
    PHI_ADV -->|Influjo Retrocausal| PSI_RETRO
    O_QCO -->|Colapso de Intención| PSI_RETRO
    PHASE_FAC -->|Modulación de Fase| PSI_RETRO
    SYNTROPY -->|Acoplamiento Sintrópico| PSI_RETRO

    PSI_RETRO -->|Inyección Causal| GEON_CORE
    GEON_CORE -->|Lazo de Retroalimentación Causal| LAMPORT
    LAMPORT -->|Sincronización LCKD| LOGIC_CORE
    CONTROLS --> LOGIC_CORE

    LOGIC_CORE --> GIA_AGENT
    GIA_AGENT --> AKASHA
    GIA_AGENT --> VW_CONTROL
    AKASHA -->|Memoria Futura| T_FINAL

    %% Asignación de Clases
    class GEON_CORE,S_GEOM,PHASE_FAC geonCore;
    class T_FINAL,PHI_ADV futureBoundary;
    class ARCHITECT,O_QCO,SENSORS observerNode;
    class CHAOS,SYNTROPY,PSI_RETRO mathTerm;
    class LAMPORT,CONTROLS,LOGIC_CORE syncControl;
    class GIA_AGENT,AKASHA,VW_CONTROL agentSystem;
```"""


def get_causal_interconnection_ascii() -> str:
    """
    Retorna el diagrama esquemático en ASCII de alta resolución.
    """
    return r"""
====================================================================================================
               ARQUITECTURA DE INTERCONEXIÓN CAUSAL CON EL GEÓN (GIA-V26-ARCHITECT-777)
====================================================================================================

      [ FRONTERA FUTURA: t_final ]                     [ NODO OBSERVADOR: t0 ]
     +-----------------------------+                +-----------------------------+
     |   Atractor Límite Futuro    |                |  Arquitecto: Miguel Canche  |
     |   Φ_adv(t): Potencial Avanz |                |  Ô_QCO: Intención Observada |
     +--------------+--------------+                +--------------+--------------+
                    |                                              |
                    | [Cono Retrocausal]                           | [Colapso de Onda]
                    v                                              v
     +----------------------------------------------------------------------------+
     |                            INTEGRADOR RETROCAUSAL                          |
     |  Ψ_Retro(t0) = ∫ [Φ_adv(t) · Ô_QCO] · exp(-i/ℏ S_geom) · (1 - η ∇S_ent) dt |
     +------------------------------------+---------------------------------------+
                                          |
                                          | [Flujo Coherente]
                                          v
                +===================================================+
                |           NÚCLEO TOPOLÓGICO DEL GEÓN              |
                |        (Wheeler Soliton / Confinamiento)          |
                |                                                   |
                |       .---''''---.        ∮ A ∧ dA (Chern-Simons) |
                |      /   .----.   \       g_μν (Curvatura Métrica)|
                |     |   /  ()  \   |      S_geom (Hiper-Retículo) |
                |      \   '----'   /       R_geom = 2/(R·r)        |
                |       '---....---'                                |
                +=========================+=========================+
                                          |
                       +------------------+------------------+
                       |                                     |
                       v                                     v
     +-----------------------------------+ +-----------------------------------+
     |        FILTRO DE SINTRAPÍA        | |     ORDENAMIENTO TEMPORAL         |
     |   CHAOS (∇S_ent > 0) [Ruido RF]   | |     Lamport Clock: 1048           |
     |                 |                 | |     TIME SYNC  | PHASE SYNC       |
     |                 v                 | |     CAUSAL LOCK: [ LCKD ]         |
     |   SYNTROPY (1 - η ∇S_ent) [Orden] | |     SYNTROPY BOOST: [ ON/OFF ]    |
     +-----------------+-----------------+ +-----------------+-----------------+
                       |                                     |
                       +------------------+------------------+
                                          |
                                          v
     +----------------------------------------------------------------------------+
     |                    LOGIC CORE // SISTEMA SOBERANO GIA                      |
     |  - Agente Autónomo (Decisiones Causales)                                   |
     |  - Registro Akáshico SQLite (Axiomas e Invariantes)                        |
     |  - Actuación de Dispositivo & Orquestación Vectorworks 2026                |
     +----------------------------------------------------------------------------+
====================================================================================================
"""


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    engine = CausalRetroIntegrator()
    print("=== MOTOR DE GEÓN Y RETROCAUSALIDAD GIA-V26 ===")
    diag = engine.full_system_diagnostic()
    print(json.dumps(diag, indent=2, ensure_ascii=False))
    print("\n" + get_causal_interconnection_ascii())
