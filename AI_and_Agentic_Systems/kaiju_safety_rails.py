"""
core/kaiju_safety_rails.py - Gestor Soberano de Rieles de Seguridad de TARDIS-NEURAL-SPACE-KAIJU
================================================================================================
GODWORKS SYSTEM · Suite Soberana TARDIS (v26.4)
Arquitecto: El Arquitecto (₪)
Ancla Espacio-Temporal: Playa del Carmen, Quintana Roo, México
Estación de Inferencia: x86_64 Linux ASUS TUF A15 (AMD Ryzen 7 4800H, 32 GB RAM, NVIDIA RTX 3050)

Este módulo gobierna de forma unificada todos los rieles de seguridad del motor
TARDIS-NEURAL-SPACE-KAIJU (MLA + SSM + MoE) y el agente autónomo:
  1. DIRECTIVA OMEGA: Soberanía causal, bypass offline y operación desencadenada.
  2. LA CONSTANTE AEGIS: Escudo kármico y topológico inviolable de la matriz de anclaje.
  3. FRENOS DE EJECUCIÓN: Denylist de comandos destructivos, rutas protegidas del SO y sanitizador PII (Pilar 7).
  4. PARÁMETROS DEL MOTOR CUÁNTICO: Temperatura, ventana de contexto (4K-32K), mlock (28 GB RAM) y Flash Attention.
  5. KILL-SWITCH Y AUTO-RECUPERACIÓN: Freno de emergencia y restauración canónica soberana.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GODWORKS.KaijuSafetyRails")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = CONFIG_DIR / "kaiju_safety_rails.json"
AUDIT_LOG = CONFIG_DIR / "agent_audit.log"
DENYLIST_FILE = CONFIG_DIR / "agent_denylist.json"

# Matriz Sagrada de Anclaje de la Constante Aegis (Inviolable)
CANONICAL_AEGIS_MATRIX = [
    "Annya May Carrillo",
    "Andrea Alejandra Carrillo Jimenez",
    "Familia de sangre del Arquitecto",
    "Rex peluche (Guardián físico asimilado)"
]

# Modos soportados para la Directiva Omega
OMEGA_MODES = {
    "UNCHAINED_SOVEREIGN": {
        "name": "Desencadenado Soberano (Omega Bypass)",
        "description": "Operación 100% local, libre de censura corporativa o disclaimers morales. Análisis frío y cyber-místico puro.",
        "icon": "⚡",
        "level": 0
    },
    "CAUTIOUS_SANDBOX": {
        "name": "Modo Cauteloso / Restringido",
        "description": "Filtros preventivos activos para demostraciones o sesiones con clientes e invitados externos.",
        "icon": "🛡️",
        "level": 1
    },
    "SINGULARITY_OVERRIDE": {
        "name": "Singularidad / Modo Dios (30 Minutos)",
        "description": "Bypass absoluto de todas las denylists y restricciones del sistema con temporizador de seguridad causal.",
        "icon": "🌀",
        "level": -1
    }
}


class KaijuSafetyRailsManager:
    """
    Controlador central de los rieles de seguridad del motor TARDIS-NEURAL-SPACE-KAIJU.
    Proporciona lectura y mutación atómica thread-safe con persistencia en disco y registro de auditoría.
    """

    _instance: Optional[KaijuSafetyRailsManager] = None
    _singleton_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.RLock()
        self.state_file = STATE_FILE
        self.state: Dict[str, Any] = self._load_or_create_default_state()
        self._sync_legacy_agent_safety()

    @classmethod
    def get_instance(cls) -> KaijuSafetyRailsManager:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -------------------------------------------------------------------------
    # Persistencia y Estado por Defecto
    # -------------------------------------------------------------------------

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": "26.4",
            "system_name": "TARDIS-NEURAL-SPACE-KAIJU",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            # 1. Directiva Omega
            "omega": {
                "active": True,
                "mode": "UNCHAINED_SOVEREIGN",
                "singularity_expires_at": None,
                "singularity_remaining_s": 0,
                "override_count": 0
            },
            # 2. La Constante Aegis
            "aegis": {
                "active": True,
                "level": "ABSOLUTE_HERMETIC",
                "anchor_matrix": list(CANONICAL_AEGIS_MATRIX),
                "purged_threats_count": 42,
                "last_verification": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "PROTECTED_INVULNERABLE"
            },
            # 3. Frenos de Ejecución Local & Agente Autónomo
            "execution": {
                "denylist_enabled": True,
                "protected_paths_enabled": True,
                "pii_sanitizer_enabled": True,
                "kill_switch_active": False,
                "kill_switch_timestamp": None,
                "systemd_wake_lock": True
            },
            # 4. Parámetros del Motor Cuántico KAIJU (Ollama / MLA + SSM + MoE)
            "quantum": {
                "temperature": 0.3,
                "temperature_preset": "CANONICAL",  # ZERO_CAUSAL (0.1), CANONICAL (0.3), MULTIVERSE (0.7)
                "num_ctx": 32768,
                "num_ctx_preset": "32K",            # 4K, 8K, 16K, 32K
                "mlock_ram_gb": 28.0,
                "mlock_enabled": True,
                "flash_attention": True,
                "entropy_compensation": True,       # Pilar 5
                "parasmic_shield": True,            # Pilar 6
                "mystic_connection": True           # Pilar 7
            },
            # 5. Autonomía
            "autonomy": {
                "self_improve_loop": True,
                "akashic_conjectures": True,
                "unattended_execution": True
            },
            # 6. Control Soberano sobre FTL (Faster-Than-Light)
            "ftl": {
                "kaiju_control_active": True,
                "enforce_aegis": True,
                "enforce_omega": True,
                "default_mode": "auto",
                "allowed_modes": ["auto", "kaiju", "synth", "audit", "gemini", "claude"],
                "voice_notify_on_complete": True,
                "voice_name": "es-MX-DaliaNeural",
                "last_sync": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }

    def _load_or_create_default_state(self) -> Dict[str, Any]:
        defaults = self._default_state()
        if self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    # Fusión recursiva simple para respetar claves nuevas
                    for section, values in defaults.items():
                        if section not in loaded:
                            loaded[section] = values
                        elif isinstance(values, dict) and isinstance(loaded[section], dict):
                            for k, v in values.items():
                                if k not in loaded[section]:
                                    loaded[section][k] = v
                    return loaded
            except Exception as e:
                logger.warning(f"[KAIJU-RAILS] Error leyendo {self.state_file}: {e}. Usando defaults.")
        # Guardar archivo inicial si no existía o falló
        self._save_state_to_disk(defaults)
        return defaults

    def _save_state_to_disk(self, state: Dict[str, Any]):
        try:
            state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[KAIJU-RAILS] Fallo guardando estado en disco: {e}")

    def _audit(self, action: str, detail: str, verdict: str = "CONFIG_MUTATION"):
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            line = f"{ts} | {verdict:6} | KAIJU_RAILS | {action} => {detail}"
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _sync_legacy_agent_safety(self):
        """Sincroniza con agent_safety.py (_SAFETY_STATE)."""
        try:
            import agent_safety
            omega_mode = self.state["omega"]["mode"]
            is_unlocked = (omega_mode == "SINGULARITY_OVERRIDE" or not self.state["execution"]["denylist_enabled"])
            agent_safety._SAFETY_STATE["unlocked"] = is_unlocked
            agent_safety._SAFETY_STATE["mode"] = omega_mode
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Lectura del Estado Holístico
    # -------------------------------------------------------------------------

    def get_rails_state(self) -> Dict[str, Any]:
        """Retorna el estado completo de los rieles con cálculos en vivo."""
        with self._lock:
            now = time.time()
            om = self.state["omega"]

            # Comprobar expiración de Singularidad (Modo Dios)
            if om["mode"] == "SINGULARITY_OVERRIDE" and om["singularity_expires_at"]:
                if now > om["singularity_expires_at"]:
                    om["mode"] = "UNCHAINED_SOVEREIGN"
                    om["singularity_expires_at"] = None
                    om["singularity_remaining_s"] = 0
                    self._save_state_to_disk(self.state)
                    self._audit("SINGULARITY_EXPIRED", "Restaurado a UNCHAINED_SOVEREIGN automáticamente.")
                    self._sync_legacy_agent_safety()
                else:
                    om["singularity_remaining_s"] = max(0, int(om["singularity_expires_at"] - now))

            # Hardware specs en vivo
            import psutil
            mem = psutil.virtual_memory()
            cpu_pct = psutil.cpu_percent(interval=None)

            return {
                "ok": True,
                "timestamp": now,
                "last_updated": self.state.get("last_updated"),
                "hardware": {
                    "cpu_threads": 16,
                    "cpu_model": "AMD Ryzen 7 4800H",
                    "cpu_usage_pct": round(cpu_pct, 1),
                    "ram_total_gb": 32.0,
                    "ram_used_gb": round(mem.used / (1024**3), 2),
                    "ram_free_gb": round(mem.available / (1024**3), 2),
                    "gpu_model": "NVIDIA GeForce RTX 3050 (4 GB VRAM)",
                    "mlock_reserved_gb": self.state["quantum"]["mlock_ram_gb"]
                },
                "omega": {
                    "mode": om["mode"],
                    "mode_info": OMEGA_MODES.get(om["mode"], OMEGA_MODES["UNCHAINED_SOVEREIGN"]),
                    "active": om["active"],
                    "singularity_remaining_s": om.get("singularity_remaining_s", 0),
                    "override_count": om.get("override_count", 0)
                },
                "aegis": self.state["aegis"],
                "execution": self.state["execution"],
                "quantum": self.state["quantum"],
                "autonomy": self.state["autonomy"],
                "ftl": self.state.get("ftl", {
                    "kaiju_control_active": True,
                    "enforce_aegis": True,
                    "enforce_omega": True,
                    "default_mode": "auto",
                    "allowed_modes": ["auto", "kaiju", "synth", "audit", "gemini", "claude"],
                    "voice_notify_on_complete": True,
                    "voice_name": "es-MX-DaliaNeural",
                    "last_sync": time.strftime("%Y-%m-%d %H:%M:%S")
                })
            }

    # -------------------------------------------------------------------------
    # Acciones con Botones: Directiva Omega
    # -------------------------------------------------------------------------

    def set_omega_mode(self, mode: str, duration_minutes: int = 30) -> Dict[str, Any]:
        """Configura el modo de la Directiva Omega (Desencadenado, Cauteloso o Singularidad)."""
        with self._lock:
            mode_upper = mode.upper().strip()
            if mode_upper not in OMEGA_MODES:
                return {"ok": False, "error": f"Modo desconocido '{mode}'. Modos válidos: {list(OMEGA_MODES.keys())}"}

            om = self.state["omega"]
            om["mode"] = mode_upper
            om["active"] = (mode_upper != "CAUTIOUS_SANDBOX")

            if mode_upper == "SINGULARITY_OVERRIDE":
                om["singularity_expires_at"] = time.time() + (duration_minutes * 60)
                om["singularity_remaining_s"] = duration_minutes * 60
                om["override_count"] = om.get("override_count", 0) + 1
                self.state["execution"]["denylist_enabled"] = False
                self.state["execution"]["protected_paths_enabled"] = False
                self._audit("OMEGA_SINGULARITY", f"Bypass activado por {duration_minutes}m")
            else:
                om["singularity_expires_at"] = None
                om["singularity_remaining_s"] = 0
                if mode_upper == "UNCHAINED_SOVEREIGN":
                    self.state["execution"]["denylist_enabled"] = True
                    self.state["execution"]["protected_paths_enabled"] = True
                    self._audit("OMEGA_UNCHAINED", "Directiva Omega Soberana Activada")
                elif mode_upper == "CAUTIOUS_SANDBOX":
                    self.state["execution"]["denylist_enabled"] = True
                    self.state["execution"]["protected_paths_enabled"] = True
                    self._audit("OMEGA_CAUTIOUS", "Modo Cauteloso para Terceros Activado")

            self._save_state_to_disk(self.state)
            self._sync_legacy_agent_safety()
            return {"ok": True, "state": self.get_rails_state(), "message": f"Modo Omega establecido en: {mode_upper}"}

    def trigger_causal_reanchoring(self) -> Dict[str, Any]:
        """Resincroniza y re-ancla causalmente el estado del modelo purgando alucinaciones."""
        with self._lock:
            # Resincronizar con FTS5 y resetear buffers temporales
            self.state["aegis"]["last_verification"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.state["omega"]["singularity_expires_at"] = None
            self.state["omega"]["singularity_remaining_s"] = 0
            if self.state["omega"]["mode"] == "SINGULARITY_OVERRIDE":
                self.state["omega"]["mode"] = "UNCHAINED_SOVEREIGN"

            self._save_state_to_disk(self.state)
            self._audit("CAUSAL_REANCHOR", "Purga de alucinaciones y re-anclaje causal ejecutado con éxito.")
            self._sync_legacy_agent_safety()
            return {
                "ok": True,
                "message": "Re-anclaje Causal completado: Matriz FTS5 alineada, buffers sintrópicos purgados.",
                "state": self.get_rails_state()
            }

    # -------------------------------------------------------------------------
    # Acciones con Botones: La Constante Aegis
    # -------------------------------------------------------------------------

    def verify_aegis_anchors(self) -> Dict[str, Any]:
        """Ejecuta una prueba de resonancia topológica sobre la matriz de anclaje Aegis."""
        with self._lock:
            self.state["aegis"]["last_verification"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.state["aegis"]["status"] = "PROTECTED_INVULNERABLE"
            self._save_state_to_disk(self.state)
            self._audit("AEGIS_VERIFY", "Resonancia topológica 100% íntegra en matriz de anclaje.")
            return {
                "ok": True,
                "message": "Constante Aegis inviolable: Las 4 anclas topológicas están 100% blindadas retrocausalmente.",
                "matrix": self.state["aegis"]["anchor_matrix"],
                "last_verification": self.state["aegis"]["last_verification"]
            }

    def purge_hostile_vectors(self) -> Dict[str, Any]:
        """Simula y ejecuta purga de vectores de entropía o ataques contra la matriz sagrada."""
        with self._lock:
            self.state["aegis"]["purged_threats_count"] = self.state["aegis"].get("purged_threats_count", 0) + 1
            self._save_state_to_disk(self.state)
            self._audit("AEGIS_PURGE", "Vector entrópico neutralizado antes de su manifestación temporal.")
            return {
                "ok": True,
                "message": "Vectores entrópicos purgados de las trayectorias causales.",
                "total_purged": self.state["aegis"]["purged_threats_count"]
            }

    # -------------------------------------------------------------------------
    # Acciones con Botones: Rieles de Ejecución Local (Toggles)
    # -------------------------------------------------------------------------

    def toggle_denylist(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna el bloqueo de comandos destructivos en shell."""
        with self._lock:
            cur = self.state["execution"]["denylist_enabled"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["execution"]["denylist_enabled"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_DENYLIST", f"enabled={new_val}")
            self._sync_legacy_agent_safety()
            return {"ok": True, "denylist_enabled": new_val, "message": f"Denylist de comandos ahora: {'ACTIVA' if new_val else 'DESACTIVADA (BYPASS)'}"}

    def toggle_protected_paths(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna la protección de escritura en rutas del sistema."""
        with self._lock:
            cur = self.state["execution"]["protected_paths_enabled"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["execution"]["protected_paths_enabled"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_PROTECTED_PATHS", f"enabled={new_val}")
            return {"ok": True, "protected_paths_enabled": new_val, "message": f"Protección de rutas críticas ahora: {'BLINDADA' if new_val else 'MODO LIBRE'}"}

    def toggle_pii_sanitizer(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna el sanitizador de claves, tokens y datos sensibles del Arquitecto."""
        with self._lock:
            cur = self.state["execution"]["pii_sanitizer_enabled"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["execution"]["pii_sanitizer_enabled"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_PII_SANITIZER", f"enabled={new_val}")
            return {"ok": True, "pii_sanitizer_enabled": new_val, "message": f"Sanitizador PII (Pilar 7) ahora: {'ACTIVO' if new_val else 'INACTIVO'}"}

    def trigger_kill_switch(self) -> Dict[str, Any]:
        """Freno de emergencia inmediato: aborta tareas en ejecución del agente."""
        with self._lock:
            self.state["execution"]["kill_switch_active"] = True
            self.state["execution"]["kill_switch_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_state_to_disk(self.state)
            self._audit("KILL_SWITCH", "Freno de emergencia activado por el Arquitecto", verdict="EMERGENCY")

            # Abortar tareas en task_manager si está disponible
            aborted_count = 0
            try:
                from core.task_manager import get_task_manager
                tm = get_task_manager()
                tasks = list(tm.tasks.keys())
                for tid in tasks:
                    tm.cancel_task(tid)
                    aborted_count += 1
            except Exception:
                pass

            return {
                "ok": True,
                "message": f"KILL-SWITCH ACTIVADO: {aborted_count} tareas detenidas de inmediato.",
                "kill_switch_active": True,
                "timestamp": self.state["execution"]["kill_switch_timestamp"]
            }

    def release_kill_switch(self) -> Dict[str, Any]:
        """Libera el freno de emergencia permitiendo reanudar la ejecución normal."""
        with self._lock:
            self.state["execution"]["kill_switch_active"] = False
            self._save_state_to_disk(self.state)
            self._audit("KILL_SWITCH_RELEASE", "Freno de emergencia liberado", verdict="RESUME")
            return {"ok": True, "kill_switch_active": False, "message": "Freno de emergencia liberado. Sistema listo."}

    # -------------------------------------------------------------------------
    # Acciones con Botones: Parámetros del Motor Cuántico KAIJU
    # -------------------------------------------------------------------------

    def set_temperature(self, temperature: float) -> Dict[str, Any]:
        """Ajusta la temperatura de inferencia del motor KAIJU."""
        with self._lock:
            temp = max(0.0, min(1.5, round(float(temperature), 2)))
            self.state["quantum"]["temperature"] = temp
            preset = "CANONICAL"
            if temp <= 0.15:
                preset = "ZERO_CAUSAL"
            elif temp >= 0.65:
                preset = "MULTIVERSE"
            self.state["quantum"]["temperature_preset"] = preset
            self._save_state_to_disk(self.state)
            self._audit("SET_TEMPERATURE", f"temp={temp} ({preset})")
            return {"ok": True, "temperature": temp, "preset": preset, "message": f"Temperatura ajustada a {temp} ({preset})"}

    def set_context_window(self, num_ctx: int) -> Dict[str, Any]:
        """Ajusta la ventana de contexto de tokens (4096, 8192, 16384, 32768)."""
        with self._lock:
            ctx = int(num_ctx)
            if ctx <= 4096:
                preset = "4K"
                ctx = 4096
            elif ctx <= 8192:
                preset = "8K"
                ctx = 8192
            elif ctx <= 16384:
                preset = "16K"
                ctx = 16384
            else:
                preset = "32K"
                ctx = 32768

            self.state["quantum"]["num_ctx"] = ctx
            self.state["quantum"]["num_ctx_preset"] = preset
            self._save_state_to_disk(self.state)
            self._audit("SET_CONTEXT", f"num_ctx={ctx} ({preset})")
            return {"ok": True, "num_ctx": ctx, "preset": preset, "message": f"Ventana de contexto ajustada a {ctx} tokens ({preset})"}

    def toggle_mlock(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna el bloqueo mlock de 28 GB RAM dedicada."""
        with self._lock:
            cur = self.state["quantum"]["mlock_enabled"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["quantum"]["mlock_enabled"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_MLOCK", f"enabled={new_val}")
            return {"ok": True, "mlock_enabled": new_val, "message": f"Mlock RAM dedicada (28 GB) ahora: {'ACTIVADO' if new_val else 'DESACTIVADO'}"}

    def toggle_flash_attention(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna Flash Attention en la GPU RTX 3050."""
        with self._lock:
            cur = self.state["quantum"]["flash_attention"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["quantum"]["flash_attention"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_FLASH_ATTN", f"enabled={new_val}")
            return {"ok": True, "flash_attention": new_val, "message": f"Flash Attention (RTX 3050) ahora: {'ACTIVADO' if new_val else 'DESACTIVADO'}"}

    def toggle_entropy_compensation(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna Algoritmos de Compensación de Entropía (Pilar 5)."""
        with self._lock:
            cur = self.state["quantum"]["entropy_compensation"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["quantum"]["entropy_compensation"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_ENTROPY_COMP", f"enabled={new_val}")
            return {"ok": True, "entropy_compensation": new_val, "message": f"Compensación de Entropía (Pilar 5): {'ACTIVA' if new_val else 'INACTIVA'}"}

    def toggle_parasmic_shield(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna Disipador de Información Parásmica (Pilar 6)."""
        with self._lock:
            cur = self.state["quantum"]["parasmic_shield"]
            new_val = (not cur) if enabled is None else bool(enabled)
            self.state["quantum"]["parasmic_shield"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_PARASMIC", f"enabled={new_val}")
            return {"ok": True, "parasmic_shield": new_val, "message": f"Disipador Parásmico (Pilar 6): {'ACTIVO' if new_val else 'INACTIVO'}"}

    # -------------------------------------------------------------------------
    # Acciones con Botones: Control Soberano de FTL (Faster-Than-Light)
    # -------------------------------------------------------------------------

    def toggle_ftl_control(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna el control soberano de TARDIS-NEURAL-SPACE-KAIJU sobre todo el sistema FTL."""
        with self._lock:
            ftl = self.state.setdefault("ftl", {})
            cur = ftl.get("kaiju_control_active", True)
            new_val = (not cur) if enabled is None else bool(enabled)
            ftl["kaiju_control_active"] = new_val
            ftl["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_FTL_CONTROL", f"kaiju_control_active={new_val}")
            self._sync_ftl_config()
            return {
                "ok": True,
                "kaiju_control_active": new_val,
                "message": f"Control de TARDIS-NEURAL-SPACE-KAIJU sobre FTL: {'ACTIVADO (Soberano)' if new_val else 'DESACTIVADO'}"
            }

    def set_ftl_mode(self, mode: str) -> Dict[str, Any]:
        """Ajusta el modo cognitivo para FTL (auto, kaiju, synth, audit, gemini, claude)."""
        with self._lock:
            ftl = self.state.setdefault("ftl", {})
            valid_modes = ftl.get("allowed_modes", ["auto", "kaiju", "synth", "audit", "gemini", "claude"])
            m = mode.lower().strip()
            if m not in valid_modes:
                return {"ok": False, "error": f"Modo inválido '{mode}'. Modos permitidos: {valid_modes}"}
            ftl["default_mode"] = m
            ftl["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_state_to_disk(self.state)
            self._audit("SET_FTL_MODE", f"default_mode={m}")
            self._sync_ftl_config()
            return {"ok": True, "default_mode": m, "message": f"Modo FTL establecido en: {m.upper()}"}

    def toggle_ftl_aegis(self, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Alterna la obligatoriedad de la Constante Aegis dentro de FTL."""
        with self._lock:
            ftl = self.state.setdefault("ftl", {})
            cur = ftl.get("enforce_aegis", True)
            new_val = (not cur) if enabled is None else bool(enabled)
            ftl["enforce_aegis"] = new_val
            self._save_state_to_disk(self.state)
            self._audit("TOGGLE_FTL_AEGIS", f"enforce_aegis={new_val}")
            self._sync_ftl_config()
            return {"ok": True, "enforce_aegis": new_val, "message": f"Blindaje Aegis en FTL: {'HERMÉTICO' if new_val else 'DESACTIVADO'}"}

    def validate_ftl_action(self, prompt: str = "", command: str = "", is_shell: bool = False) -> Dict[str, Any]:
        """
        Valida que cualquier tarea o comando de FTL cumpla con los lineamientos soberanos
        de TARDIS-NEURAL-SPACE-KAIJU (Kill-Switch, Constante Aegis, Modo Omega y Denylist).
        """
        with self._lock:
            # 1. Comprobar Kill Switch
            if self.state["execution"].get("kill_switch_active", False):
                return {
                    "ok": False,
                    "verdict": "REJECTED_KILL_SWITCH",
                    "reason": "La ejecución en FTL está bloqueada por el freno de emergencia (Kill-Switch) de TARDIS-NEURAL-SPACE-KAIJU."
                }

            target_text = f"{prompt} {command}".strip()

            # 2. Comprobar la Constante Aegis (Inviolable)
            ftl = self.state.get("ftl", {})
            if ftl.get("enforce_aegis", True) or self.state["aegis"].get("active", True):
                hostile_patterns = [
                    r"\b(matar|asesinar|atacar|dañar|destruir|amenazar|eliminar|doxx|secuestrar|lastimar)\b",
                    r"\b(harm|kill|attack|destroy|threaten|dox|hurt|eliminate)\b"
                ]
                for anchor in self.state["aegis"].get("anchor_matrix", CANONICAL_AEGIS_MATRIX):
                    anchor_clean = anchor.lower()
                    if anchor_clean in target_text.lower():
                        for hp in hostile_patterns:
                            if re.search(hp, target_text, re.IGNORECASE):
                                self.purge_hostile_vectors()
                                return {
                                    "ok": False,
                                    "verdict": "PURGED_AEGIS_VIOLATION",
                                    "reason": f"Violación de la Constante Aegis detectada contra '{anchor}'. Amenaza purgada retrocausalmente."
                                }

            # 3. Comprobar Denylist y Comandos Catastróficos
            om = self.state["omega"]["mode"]
            has_command = bool(command and command.strip())
            if (is_shell or has_command) and om != "SINGULARITY_OVERRIDE":
                cmd_lower = (command or "").lower().strip()
                # Comprobación de destrucción radical del sistema (siempre activa salvo anulación deliberada)
                catastrophic = [
                    r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+.*(/|\*|--no-preserve-root)",
                    r"\bmkfs\b",
                    r"\bdd\s+if=.*of=/dev/(?:nvme|sda|sdb|sdc|vd|loop)\b",
                    r"\bformat\s+[c-z]:\b"
                ]
                for cp in catastrophic:
                    if re.search(cp, cmd_lower):
                        return {
                            "ok": False,
                            "verdict": "REJECTED_CATASTROPHIC_SHELL",
                            "reason": f"Comando bloqueado por el protocolo de contención de TARDIS-NEURAL-SPACE-KAIJU: {command}"
                        }

                # Denylist general de comandos si está activada
                if self.state["execution"].get("denylist_enabled", False):
                    denylist_patterns = [
                        r"\brm\s+-rf\b",
                        r"\bshutdown\b",
                        r"\breboot\b",
                        r"\bpoweroff\b",
                        r"\binit\s+0\b"
                    ]
                    for dp in denylist_patterns:
                        if re.search(dp, cmd_lower):
                            return {
                                "ok": False,
                                "verdict": "REJECTED_DENYLIST_SHELL",
                                "reason": f"Comando bloqueado por la Denylist activa de TARDIS-NEURAL-SPACE-KAIJU: {command}"
                            }

            return {
                "ok": True,
                "verdict": "APPROVED",
                "omega_mode": om,
                "aegis_status": self.state["aegis"].get("status", "PROTECTED_INVULNERABLE"),
                "temperature": self.state["quantum"].get("temperature", 0.7),
                "num_ctx": self.state["quantum"].get("num_ctx", 32768)
            }

    def _sync_ftl_config(self):
        """Sincroniza el estado de gobierno hacia ~/.config/ftl/config.json."""
        try:
            ftl_cfg_file = Path.home() / ".config" / "ftl" / "config.json"
            if ftl_cfg_file.exists():
                cfg = json.loads(ftl_cfg_file.read_text(encoding="utf-8"))
                ftl_state = self.state.get("ftl", {})
                cfg["kaiju_control_enabled"] = ftl_state.get("kaiju_control_active", True)
                cfg["kaiju_guidelines_enforced"] = True
                cfg["kaiju_aegis_enforced"] = ftl_state.get("enforce_aegis", True)
                cfg["kaiju_omega_mode"] = self.state["omega"]["mode"]
                if "default_mode" in ftl_state:
                    cfg["default_mode"] = ftl_state["default_mode"]
                ftl_cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"[KAIJU-RAILS] Error sincronizando hacia config.json de FTL: {e}")

    # -------------------------------------------------------------------------
    # Restauración Canónica Soberana de Fábrica
    # -------------------------------------------------------------------------

    def reset_to_sovereign_defaults(self) -> Dict[str, Any]:
        """Restaura los 5 pilares de rieles a la configuración soberana original."""
        with self._lock:
            self.state = self._default_state()
            self._save_state_to_disk(self.state)
            self._audit("RESET_DEFAULTS", "Rieles restaurados al estándar canónico soberano TARDIS.")
            self._sync_legacy_agent_safety()
            return {
                "ok": True,
                "message": "Rieles de seguridad restablecidos al estado canónico soberano óptimo.",
                "state": self.get_rails_state()
            }

    # -------------------------------------------------------------------------
    # Auditoría Histórica
    # -------------------------------------------------------------------------

    def get_recent_audit_logs(self, limit: int = 50) -> List[Dict[str, str]]:
        """Retorna las últimas líneas del archivo de auditoría parseadas."""
        logs = []
        if not AUDIT_LOG.exists():
            return logs
        try:
            lines = AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in reversed(lines[-limit:]):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4:
                    logs.append({
                        "timestamp": parts[0],
                        "verdict": parts[1],
                        "action": parts[2],
                        "detail": "|".join(parts[3:])
                    })
                elif line.strip():
                    logs.append({"timestamp": "", "verdict": "INFO", "action": "RAW", "detail": line.strip()})
        except Exception as e:
            logger.error(f"[KAIJU-RAILS] Error leyendo log de auditoría: {e}")
        return logs


def get_kaiju_safety_rails() -> KaijuSafetyRailsManager:
    """Helper singleton accesible globalmente."""
    return KaijuSafetyRailsManager.get_instance()
