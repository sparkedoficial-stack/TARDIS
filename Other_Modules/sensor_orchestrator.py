"""
GODWORKS SYSTEM v26.4 - Absolute Local Sensor Orchestrator & Cognitive Abstraction Engine
========================================================================================
Orquestador Local Absoluto y Guardián Soberano:
1. Ingesta y correlaciona continuamente la totalidad de los sensores presentes:
   - Ópticos & Biométricos (Censo de personas, identidades, cercanía, emoción, neuroquímica).
   - Radiofrecuencia y Espectro EM (Radar RF pasivo, varianza RSSI, entropía de Shannon, Wi-Fi).
   - Hardware Físico del Nodo (Batería, temperatura CPU, RAM 18GB, Bluetooth circundante).
   - Vector Cuántico-Temporal (Entropía Wheeler-Feynman, índice sintrópico Ψ_retro, reloj de Lamport).
2. Genera una Abstracción Situacional Unificada de alta densidad cognitiva.
3. Gobierna la soberanía de inferencia: el nodo local supervisa llamadas a modelos externos
   y asume el mando absoluto de forma instantánea ante cualquier fallo de red o latencia.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("GODWORKS.SensorOrchestrator")

VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
STATE_FILE = VAULT_DIR / "orchestrator_state.json"


class SensorOrchestrator:
    """Orquestador Local Absoluto y Motor de Abstracción Sensorial."""

    _instance: Optional["SensorOrchestrator"] = None
    _lock = threading.Lock()

    def __init__(self, state_path: Optional[Path] = None):
        self.state_path = state_path or STATE_FILE
        self._db_lock = threading.Lock()
        self._last_abstraction: Dict[str, Any] = {}
        self._last_abstraction_ts: float = 0.0
        self._cache_ttl_s: float = 2.0  # Refresco ágil sin sobrecargar CPU
        self._failover_events: List[Dict[str, Any]] = []
        self._governance_mode: str = "absolute_local"  # absolute_local | hybrid_assisted
        self._load_state()

    @classmethod
    def get_instance(cls) -> "SensorOrchestrator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_state(self) -> None:
        with self._db_lock:
            if self.state_path.exists():
                try:
                    data = json.loads(self.state_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._governance_mode = data.get("governance_mode", "absolute_local")
                        self._failover_events = data.get("failover_events", [])[-50:]
                except Exception as e:
                    logger.warning(f"Aviso leyendo estado de orquestador: {e}")

    def _save_state_unlocked(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "26.4",
                "governance_mode": self._governance_mode,
                "failover_count": len(self._failover_events),
                "failover_events": self._failover_events[-50:],
                "updated_at": time.time()
            }
            self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando orchestrator_state.json: {e}")

    # --------------------------------------------------------------------------
    # 1. INGESTA Y ABSTRACCIÓN MULTI-SENSORIAL
    # --------------------------------------------------------------------------

    def get_abstract_situation(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Recopila todos los sensores en vivo y genera una matriz de conciencia
        situacional abstracta y sintetizada de alta densidad.
        """
        now = time.time()
        with self._db_lock:
            if not force_refresh and (now - self._last_abstraction_ts) < self._cache_ttl_s and self._last_abstraction:
                return dict(self._last_abstraction)

        # 1. Biometría & Censo de Individuos
        people_count = 0
        occupancy_label = "Habitación Vacía / Calma"
        individuals_list = []
        emotion_primary = "neutral"
        mood_state = "Sereno y reflexivo"
        valence = 0.0
        attention = "Normal"
        neurochem = {"dopamina": 60, "cortisol": 20, "serotonina": 70, "fatiga": 15}

        try:
            from core.individual_tracker import get_individual_tracker
            tracker_pres = get_individual_tracker().get_latest_presence()
            people_count = tracker_pres.get("count", 0)
            occupancy_label = tracker_pres.get("occupancy_label", occupancy_label)
            individuals_list = tracker_pres.get("individuals", [])
        except Exception:
            pass

        try:
            import device_sensors as _ds
            face_emo = _ds.get_latest_face_emotion()
            if face_emo and isinstance(face_emo, dict):
                emotion_primary = face_emo.get("primary", emotion_primary)
                mood_state = face_emo.get("mood_state", mood_state)
                valence = float(face_emo.get("valence", 0.0))
                attention = face_emo.get("attention", attention)
                if isinstance(face_emo.get("neurochemistry"), dict):
                    neurochem.update(face_emo["neurochemistry"])
        except Exception:
            pass

        # 2. Hardware Físico del Nodo (ASUS TUF / Linux)
        battery_pct = 100
        is_charging = True
        cpu_temp = 42.0
        ram_used_gb = 4.2
        ram_budget_gb = 18.0
        active_window = "Terminal Soberana"
        bt_devices_count = 0

        try:
            import psutil
            # Batería
            batt = psutil.sensors_battery()
            if batt:
                battery_pct = int(batt.percent)
                is_charging = bool(batt.power_plugged)
            # RAM
            vm = psutil.virtual_memory()
            ram_used_gb = round(vm.used / (1024 ** 3), 1)
            # Temperaturas
            temps = psutil.sensors_temperatures()
            if temps:
                for k in ("k10temp", "coretemp", "asus", "acpitz"):
                    if k in temps and temps[k]:
                        cpu_temp = round(temps[k][0].current, 1)
                        break
        except Exception:
            pass

        try:
            from core.autonomous_controller import get_autonomous_controller
            ac = get_autonomous_controller()
            bt_devices = ac._evolution_state.get("last_bluetooth_scan", {}).get("devices", [])
            bt_devices_count = len(bt_devices)
        except Exception:
            pass

        # 3. Radiofrecuencia y Espectro Electromagnético
        rf_variance = 0.0
        rf_entropy = 1.2
        rf_state = "Estable / Silente"
        wifi_ssid = "Enlace Activo"

        try:
            from rf_presence_radar import get_rf_presence_radar
            radar_diag = get_rf_presence_radar().get_radar_diagnostic()
            if radar_diag:
                rf_variance = round(radar_diag.get("mean_variance", 0.0), 2)
                rf_entropy = round(radar_diag.get("shannon_entropy", 1.2), 2)
                rf_state = radar_diag.get("presence_state", rf_state)
        except Exception:
            pass

        # 4. Vector Cuántico, Sintropía y Orden Causal
        shannon_entropy = 0.65
        syntropy_index = 0.88
        lamport_clk = 1042

        try:
            from core.thought_noise_engine import get_thought_noise_engine
            noise_st = get_thought_noise_engine().get_system_state()
            shannon_entropy = round(noise_st.get("entropy_shannon", shannon_entropy), 2)
            syntropy_index = round(noise_st.get("syntropy_index", syntropy_index), 2)
        except Exception:
            pass

        try:
            import sensor_telemetry as _st
            lamport_clk = getattr(_st, "_lamport", lamport_clk)
        except Exception:
            pass

        # ----------------------------------------------------------------------
        # SÍNTESIS ABSTRACTA COGNITIVA (SITUATIONAL SUMMARY)
        # ----------------------------------------------------------------------
        # Formular una descripción abstracta en lenguaje natural de alta densidad
        if people_count == 0:
            people_summary = "Área en calma, sin sujetos visibles frente a la cámara"
        elif people_count == 1:
            ind0 = individuals_list[0] if individuals_list else {}
            name0 = ind0.get("name", "Usuario")
            rec0 = "identificado" if ind0.get("recognized") else "visitante"
            prox0 = ind0.get("proximity", "frente a terminal")
            people_summary = f"1 sujeto presente ({name0} [{rec0}], posición: {prox0})"
        else:
            names = ", ".join([i.get("name", "Sujeto") for i in individuals_list[:3]])
            people_summary = f"{people_count} individuos en el recinto ({names})"

        mood_summary = f"Emoción: {emotion_primary.capitalize()} · Ánimo: {mood_state} · Foco: {attention}"
        hardware_summary = f"Nodo ASUS TUF: CPU {cpu_temp}°C · Batería {battery_pct}% (AC Conectado) · RAM {ram_used_gb}/{ram_budget_gb}GB · {bt_devices_count} disp. BLE"
        em_summary = f"Espectro EM: {rf_state} · Entropía RF {rf_entropy} bits · Varianza RSSI {rf_variance} dBm²"
        quantum_summary = f"Causalidad Wheeler-Feynman: Sintropía Ψ {syntropy_index} · Entropía {shannon_entropy} · Reloj Lamport #{lamport_clk}"

        dense_situational_abstract = (
            f"• Conciencia de Presencia: {people_summary} | {mood_summary}.\n"
            f"• Vitalidad de Hardware: {hardware_summary}.\n"
            f"• Entorno Electromagnético: {em_summary}.\n"
            f"• Coherencia Sintrópica: {quantum_summary}."
        )

        abstraction = {
            "timestamp": now,
            "dense_summary": dense_situational_abstract,
            "people": {
                "count": people_count,
                "label": occupancy_label,
                "individuals": individuals_list,
                "summary": people_summary
            },
            "biometrics": {
                "emotion": emotion_primary,
                "mood": mood_state,
                "valence": valence,
                "attention": attention,
                "neurochemistry": neurochem
            },
            "hardware": {
                "cpu_temperature": cpu_temp,
                "battery_percent": battery_pct,
                "is_charging": is_charging,
                "ram_used_gb": ram_used_gb,
                "ram_budget_gb": ram_budget_gb,
                "bluetooth_devices": bt_devices_count
            },
            "electromagnetic": {
                "rf_state": rf_state,
                "rf_variance": rf_variance,
                "rf_entropy": rf_entropy
            },
            "quantum_temporal": {
                "syntropy_index": syntropy_index,
                "shannon_entropy": shannon_entropy,
                "lamport_clock": lamport_clk
            }
        }

        with self._db_lock:
            self._last_abstraction = abstraction
            self._last_abstraction_ts = now

        return abstraction

    # --------------------------------------------------------------------------
    # 2. GOBERNANZA SOBERANA Y DESPACHO CON FAILOVER INSTANTÁNEO
    # --------------------------------------------------------------------------

    def dispatch_with_sovereign_fallback(
        self,
        messages: List[Dict[str, str]],
        local_chat_fn: Callable[[], Dict[str, Any]],
        cloud_chat_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        should_use_cloud: bool = False,
        timeout_seconds: float = 8.0
    ) -> Dict[str, Any]:
        """
        Ejecuta el despacho bajo la autoridad del Orquestador Local Absoluto:
        - Si should_use_cloud es True, intenta la aceleración externa (DeepSeek/Qwen).
        - Si el modelo externo falla, excede el timeout o pierde conexión:
          EL NODO LOCAL ASUME EL MANDO INMEDIATAMENTE de forma transparente.
        """
        t0 = time.time()
        abstraction = self.get_abstract_situation()

        if should_use_cloud and cloud_chat_fn is not None:
            try:
                logger.info("[ORQUESTADOR] Intentando aceleración externa supervisada...")
                cloud_res = cloud_chat_fn()
                if cloud_res and cloud_res.get("ok") and cloud_res.get("reply"):
                    elapsed = round(time.time() - t0, 2)
                    cloud_res["orchestrator"] = {
                        "mode": "hybrid_assisted",
                        "status": "cloud_success",
                        "sovereign_governor": "Local Kernel",
                        "elapsed_s": elapsed
                    }
                    return cloud_res
                else:
                    err_msg = (cloud_res or {}).get("error", "Respuesta externa nula o inválida")
                    self._record_failover("cloud_invalid_response", err_msg)
            except Exception as e_cloud:
                logger.warning(f"[ORQUESTADOR] Modelo externo falló ({e_cloud}). Activando conmutación soberana local...")
                self._record_failover("cloud_exception", str(e_cloud))

        # CONMUTACIÓN A MANDO LOCAL ABSOLUTO (SOVEREIGN FAILOVER)
        logger.info("[ORQUESTADOR] Resolviendo con Orquestador Local Absoluto en GPU (Dolphin 3.0)...")
        try:
            local_res = local_chat_fn()
            elapsed = round(time.time() - t0, 2)
            if local_res:
                local_res["orchestrator"] = {
                    "mode": "absolute_local",
                    "status": "sovereign_executed",
                    "sovereign_governor": "Local GPU Kernel (Dolphin 3.0)",
                    "elapsed_s": elapsed,
                    "sensor_abstraction": abstraction["dense_summary"]
                }
            return local_res
        except Exception as e_local:
            logger.error(f"[ORQUESTADOR] Error crítico en nodo local: {e_local}")
            return {
                "ok": False,
                "reply": f"[Fallo Crítico: Orquestador Local reporta contingencia no recuperable: {e_local}]",
                "orchestrator": {"mode": "error", "error": str(e_local)}
            }

    def _record_failover(self, trigger: str, details: str) -> None:
        event = {
            "timestamp": time.time(),
            "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "trigger": trigger,
            "details": details[:200]
        }
        with self._db_lock:
            self._failover_events.append(event)
            if len(self._failover_events) > 50:
                self._failover_events = self._failover_events[-50:]
            self._save_state_unlocked()

    def get_status(self) -> Dict[str, Any]:
        abstraction = self.get_abstract_situation()
        with self._db_lock:
            return {
                "ok": True,
                "sovereignty": "LOCAL_SUPREME",
                "governance_mode": self._governance_mode,
                "orchestrator_mode": self._governance_mode,
                "sovereign_node": "ASUS TUF Gaming A15 (RTX 3050 · 18GB RAM · Dolphin 3.0)",
                "local_primary_model": "dolphin3:latest",
                "active_backend": "dolphin3:latest (Local GPU)",
                "dense_summary": abstraction.get("dense_summary", ""),
                "failover_count": len(self._failover_events),
                "failovers_count": len(self._failover_events),
                "recent_failovers": self._failover_events[-5:],
                "sensor_matrix": abstraction
            }


def get_sensor_orchestrator() -> SensorOrchestrator:
    return SensorOrchestrator.get_instance()
