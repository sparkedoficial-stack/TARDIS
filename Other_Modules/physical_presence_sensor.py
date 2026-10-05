"""
core/physical_presence_sensor.py - Sensor Físico de Presencia Humana y Movimiento
GODWORKS SYSTEM - TARDIS-NEURAL-SPACE-KAIJU

Proporciona una referencia sensorial directa al LLM y a los subsistemas de control:
  1. Visión Óptica: Detección facial, proximidad y movimiento de individuos (IndividualTracker).
  2. Radar Pasivo RF: Perturbación electromagnética y multitrayectoria Wi-Fi 2.4/5 GHz (RFPresenceRadar).
  3. Actividad de Entrada: Interacción física activa de usuario (teclado / touchpad).
  4. Fusión Sensorial: Estimación de distancia métrica, zona de proximidad y nivel de certidumbre.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.presence_sensor")


@dataclass
class PhysicalPresenceReading:
    timestamp: float
    timestamp_iso: str
    presence_detected: bool
    motion_detected: bool
    proximity_zone: str               # "IMMEDIATE_DESK", "NEAR_ROOM", "FAR", "ABSENT"
    estimated_distance_m: Optional[float]
    confidence_score: float           # 0.0 a 1.0
    detection_sources: List[str]      # ["OPTICAL_CAMERA", "RF_RADAR", "SYSTEM_INPUT", "ACOUSTIC"]
    individuals_count: int
    optical_details: Dict[str, Any]
    rf_details: Dict[str, Any]
    input_details: Dict[str, Any]
    summary_for_llm: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PhysicalPresenceSensor:
    """
    Sensor unificado de presencia física humana y perturbaciones del entorno.
    """

    _instance: Optional["PhysicalPresenceSensor"] = None
    _lock = threading.Lock()

    def __init__(self, cache_ttl_s: float = 1.5):
        self.cache_ttl_s = cache_ttl_s
        self._cached_reading: Optional[PhysicalPresenceReading] = None
        self._last_read_ts = 0.0
        self._read_lock = threading.Lock()
        self._last_user_input_ts = time.time()

    @classmethod
    def get_instance(cls) -> "PhysicalPresenceSensor":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def notify_user_input(self) -> None:
        """Registra actividad física de entrada (teclado, ratón o comando)."""
        self._last_user_input_ts = time.time()

    # -------------------------------------------------------------------------
    # 1. CANALES SENSORIALES INDIVIDUALES
    # -------------------------------------------------------------------------

    def _inspect_optical(self) -> Dict[str, Any]:
        """Consulta el estado del canal óptico / biométrico."""
        out = {
            "available": False,
            "detected": False,
            "count": 0,
            "proximity_label": "Desconocido",
            "individuals": []
        }
        try:
            from core.individual_tracker import get_individual_tracker
            tracker = get_individual_tracker()
            pres = tracker.get_latest_presence()
            count = pres.get("count", 0)
            out["available"] = True
            out["detected"] = count > 0
            out["count"] = count
            out["proximity_label"] = pres.get("occupancy_label", "Sin presencia")
            out["individuals"] = pres.get("individuals", [])
        except Exception as e:
            out["error"] = str(e)
        return out

    def _inspect_rf_radar(self) -> Dict[str, Any]:
        """Consulta el estado del canal de radar pasivo Wi-Fi."""
        out = {
            "available": False,
            "detected": False,
            "motion_state": "QUIET",
            "confidence": 0.0,
            "closest_distance_m": None,
            "mean_variance": 0.0
        }
        try:
            from rf_presence_radar import get_rf_radar
            radar = get_rf_radar()
            st_3d = radar.get_3d_state()
            if st_3d:
                out["available"] = True
                out["motion_state"] = st_3d.overall_motion_state
                out["confidence"] = round(float(st_3d.confidence), 2)
                out["mean_variance"] = round(float(st_3d.mean_variance), 2)
                
                # Detectado si hay movimiento o individuos mapeados
                is_active = st_3d.overall_motion_state in ("MICRO_MOTION", "ACTIVE_MOTION", "SEVERE_PERTURBATION")
                out["detected"] = is_active or st_3d.has_individuals
                if st_3d.closest_individual_distance < 50.0:
                    out["closest_distance_m"] = round(float(st_3d.closest_individual_distance), 2)
        except Exception as e:
            out["error"] = str(e)
        return out

    def _inspect_input_activity(self) -> Dict[str, Any]:
        """Evalúa la interacción reciente del usuario en el sistema."""
        elapsed = time.time() - self._last_user_input_ts
        is_recent = elapsed < 60.0  # Actividad en el último minuto
        return {
            "last_input_seconds_ago": round(elapsed, 1),
            "recent_interaction": is_recent,
            "detected": is_recent
        }

    # -------------------------------------------------------------------------
    # 2. FUSIÓN SENSORIAL INTEGRAL
    # -------------------------------------------------------------------------

    def get_presence_reading(self, force_refresh: bool = False) -> PhysicalPresenceReading:
        """
        Calcula una lectura fusionada de presencia y movimiento físico.
        Aplica ponderación de certidumbre entre los canales disponibles.
        """
        now = time.time()
        with self._read_lock:
            if not force_refresh and self._cached_reading and (now - self._last_read_ts) < self.cache_ttl_s:
                return self._cached_reading

            optical = self._inspect_optical()
            rf = self._inspect_rf_radar()
            input_act = self._inspect_input_activity()

            sources = []
            confidence_weights = []
            estimated_dist = None
            motion = False

            # Evaluación de canal óptico (alta certidumbre de presencia frontal)
            if optical.get("detected"):
                sources.append("OPTICAL_CAMERA")
                confidence_weights.append(0.95)
                estimated_dist = 0.6  # Distancia típica frente a webcam de laptop
                motion = True

            # Evaluación de canal RF (sensibilidad a perturbaciones del entorno)
            if rf.get("detected"):
                sources.append("RF_RADAR")
                rf_conf = rf.get("confidence", 0.7)
                confidence_weights.append(rf_conf)
                if rf.get("closest_distance_m") is not None:
                    rf_dist = rf["closest_distance_m"]
                    estimated_dist = min(estimated_dist or 999.0, rf_dist)
                if rf.get("motion_state") in ("ACTIVE_MOTION", "MICRO_MOTION", "SEVERE_PERTURBATION"):
                    motion = True

            # Evaluación de interacción con el sistema
            if input_act.get("recent_interaction"):
                sources.append("SYSTEM_INPUT")
                confidence_weights.append(0.98)
                estimated_dist = min(estimated_dist or 999.0, 0.4)
                motion = True

            # Cálculo de presencia y zona
            presence_detected = len(sources) > 0
            if confidence_weights:
                confidence_score = round(max(confidence_weights), 2)
            else:
                confidence_score = 0.0

            # Determinación de zona de proximidad
            if not presence_detected:
                proximity_zone = "ABSENT"
                estimated_dist = None
            elif estimated_dist is not None and estimated_dist <= 1.0:
                proximity_zone = "IMMEDIATE_DESK"
            elif estimated_dist is not None and estimated_dist <= 3.0:
                proximity_zone = "NEAR_ROOM"
            else:
                proximity_zone = "FAR"

            # Conteo de individuos
            indiv_count = optical.get("count", 0)
            if indiv_count == 0 and presence_detected:
                indiv_count = 1

            # Resumen formateado para inyección en el LLM
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if presence_detected:
                dist_str = f"~{estimated_dist:.1f}m" if estimated_dist else "En proximidad"
                src_str = " + ".join(sources)
                summary_llm = (
                    f"Presencia física DETECTADA ({indiv_count} individuo(s)). "
                    f"Zona: {proximity_zone} ({dist_str}). Movimiento: {'SÍ' if motion else 'ESTACIONARIO'}. "
                    f"Sensores: [{src_str}]. Confianza: {int(confidence_score * 100)}%."
                )
            else:
                summary_llm = (
                    "Presencia física NO detectada. Entorno en calma / despejado. "
                    "Sin perturbaciones ópticas ni de radiofrecuencia inmediatas."
                )

            reading = PhysicalPresenceReading(
                timestamp=now,
                timestamp_iso=now_str,
                presence_detected=presence_detected,
                motion_detected=motion,
                proximity_zone=proximity_zone,
                estimated_distance_m=estimated_dist,
                confidence_score=confidence_score,
                detection_sources=sources,
                individuals_count=indiv_count,
                optical_details=optical,
                rf_details=rf,
                input_details=input_act,
                summary_for_llm=summary_llm
            )

            self._cached_reading = reading
            self._last_read_ts = now
            return reading


def get_physical_presence_sensor() -> PhysicalPresenceSensor:
    return PhysicalPresenceSensor.get_instance()
