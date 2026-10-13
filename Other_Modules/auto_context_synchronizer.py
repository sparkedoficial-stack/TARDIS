"""
core/auto_context_synchronizer.py - Sincronizador Automático de Contexto Transversal
=====================================================================================
GODWORKS SYSTEM v26.4 · Suite Maestra Soberana

Mantiene sincronizado y actualizado automáticamente el contexto en TODOS los sistemas:
  1. Matriz de Identidad & Directivas Maestras (gia_context_matrix.json -> agent_context.py)
  2. Telemetría de Hardware y Silicio (CPU, RAM, Temperaturas, Batería, Inhibit 24/7)
  3. Red Wi-Fi Soberana TimeMachine & Clientes Conectados (10.42.0.x, DHCP, ARP)
  4. Bóveda de Chats Offline & Memoria RAG (SQLite FTS5, espejo JSON y visores autónomos)
  5. Hub de Sincronización Transversal Global (global_sync_state.json & Reloj de Lamport)
  6. Motor de Metapensamiento y Reflexión en Segundo Plano
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("godworks.auto_context_synchronizer")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import agent_context
from install_context_matrix import install as install_matrix, load_matrix, compose_directives
from core.offline_chat_vault import get_offline_chat_vault
from core.network_controller import get_network_controller
from core.traffic_monitor import get_traffic_monitor
from core.os_controller import get_os_controller
from core.background_thought_engine import get_background_thought_engine


class AutoContextSynchronizer:
    """Orquestador central que actualiza y sincroniza el contexto de todos los sistemas."""

    _instance: Optional["AutoContextSynchronizer"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.last_sync_ts: float = 0.0
        self.last_sync_iso: str = ""
        self.last_report: Dict[str, Any] = {}
        self._daemon_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False

    @classmethod
    def get_instance(cls) -> "AutoContextSynchronizer":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def sync_all_systems(self, force: bool = False) -> Dict[str, Any]:
        """
        Ejecuta una ronda completa de sincronización y actualización de contexto
        a través de todos los módulos y subsistemas de GODWORKS SYSTEM.
        """
        now = time.time()
        iso = datetime.datetime.now().isoformat()
        updated_subsystems = []
        errors = []

        # ---------------------------------------------------------------------
        # 1. Matriz de Contexto & Directivas Maestras (agent_context)
        # ---------------------------------------------------------------------
        matrix_info = {}
        try:
            res_matrix = install_matrix()
            matrix_info = {
                "version": res_matrix.get("version"),
                "chars": res_matrix.get("chars"),
                "updated_iso": res_matrix.get("updated_iso")
            }
            updated_subsystems.append("matrix_directives")
        except Exception as e:
            err = f"Error en sincronización de matriz de contexto: {e}"
            logger.error(err)
            errors.append(err)

        # ---------------------------------------------------------------------
        # 2. Telemetría de Hardware y Estado del Sistema
        # ---------------------------------------------------------------------
        hw_telemetry = {}
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # Temperaturas si están disponibles en Linux
            temps = {}
            try:
                raw_temps = psutil.sensors_temperatures()
                for k, v in raw_temps.items():
                    if v:
                        temps[k] = round(v[0].current, 1)
            except Exception:
                pass

            hw_telemetry = {
                "cpu_percent": cpu_pct,
                "ram_percent": mem.percent,
                "ram_used_mb": mem.used // (1024 * 1024),
                "ram_total_mb": mem.total // (1024 * 1024),
                "swap_percent": swap.percent,
                "temps": temps,
                "timestamp": now
            }
            updated_subsystems.append("hardware_telemetry")
        except Exception as e:
            errors.append(f"Error recopilando telemetría de hardware: {e}")

        # ---------------------------------------------------------------------
        # 3. Red Wi-Fi Soberana TimeMachine & Auditoría de Tráfico
        # ---------------------------------------------------------------------
        net_info = {}
        try:
            net_ctrl = get_network_controller()
            clients = net_ctrl.get_connected_clients()
            traffic_mon = get_traffic_monitor()
            traffic_stats = traffic_mon.get_quick_status() if hasattr(traffic_mon, "get_quick_status") else {}

            net_info = {
                "hotspot_ssid": "TimeMachine",
                "gateway_ip": "REDACTED_IP",
                "interface": "wlp3s0",
                "connected_clients_count": len(clients),
                "clients": clients,
                "active_flows": traffic_stats.get("active_flows", traffic_stats.get("total_flows", 0)),
                "recurring_orgs": traffic_stats.get("top_orgs", traffic_stats.get("top_organizations", []))
            }
            updated_subsystems.append("sovereign_network")
        except Exception as e:
            errors.append(f"Error recopilando contexto de red: {e}")

        # ---------------------------------------------------------------------
        # 4. Bóveda de Chats Offline & Memoria RAG
        # ---------------------------------------------------------------------
        vault_info = {}
        try:
            vault = get_offline_chat_vault()
            vault.sync_json_mirror()
            vault.generate_standalone_viewer()
            vault_info = {
                "total_turns": vault.get_total_count(),
                "db_path": str(vault.db_path),
                "desktop_viewer": "/home/timemachine/Escritorio/HISTORIAL_CHATS_OFFLINE.html"
            }
            updated_subsystems.append("offline_chat_vault")
        except Exception as e:
            errors.append(f"Error sincronizando bóveda offline: {e}")

        # ---------------------------------------------------------------------
        # 5. Hub de Sincronización Transversal Global (SYNC_HUB)
        # ---------------------------------------------------------------------
        sync_hub_info = {}
        try:
            from omni_temporal_control import SYNC_HUB
            with SYNC_HUB._lock:
                if hasattr(SYNC_HUB, "lamport"):
                    SYNC_HUB.lamport += 1
                # Inyectar telemetría fresca en causal state
                causal = getattr(SYNC_HUB, "state", {}).get("causal", {}) if hasattr(SYNC_HUB, "state") else {}
                if hw_telemetry:
                    causal["cpu"] = hw_telemetry.get("cpu_percent", 0.0)
                    causal["ram"] = hw_telemetry.get("ram_percent", 0.0)
                if net_info:
                    causal["wifi_clients"] = net_info.get("connected_clients_count", 0)
                if hasattr(SYNC_HUB, "state") and isinstance(SYNC_HUB.state, dict):
                    SYNC_HUB.state["causal"] = causal
                    SYNC_HUB.state["updated_at"] = iso
                    if hasattr(SYNC_HUB, "_save_state_to_disk"):
                        SYNC_HUB._save_state_to_disk()
                sync_hub_info = {
                    "lamport": getattr(SYNC_HUB, "lamport", 1042),
                    "revision": getattr(SYNC_HUB, "revision", 1),
                    "active_clients": SYNC_HUB.get_active_client_count() if hasattr(SYNC_HUB, "get_active_client_count") else 1
                }
            updated_subsystems.append("global_sync_hub")
        except Exception as e:
            errors.append(f"Error sincronizando SYNC_HUB: {e}")

        # ---------------------------------------------------------------------
        # 6. Motor Cognitivo de Metapensamiento
        # ---------------------------------------------------------------------
        cognitive_info = {}
        try:
            bg_thought = get_background_thought_engine()
            questions = bg_thought.get_recent_questions(limit=5)
            cognitive_info = {
                "active_questions": len(questions),
                "recent_sample": [q.get("question") for q in questions[:3] if q.get("question")]
            }
            updated_subsystems.append("background_cognition")
        except Exception as e:
            errors.append(f"Error actualizando motor cognitivo: {e}")

        # ---------------------------------------------------------------------
        # 7. Motor Neuronal Soberano (MLA + SSM + MoE)
        # ---------------------------------------------------------------------
        neural_info = {}
        try:
            from core.sovereign_neural_engine import get_sovereign_neural_engine
            sne = get_sovereign_neural_engine()
            neural_info = {
                "active_latent_sessions": list(sne.active_latent_states.keys()),
                "d_model": sne.cfg.d_model,
                "n_heads": sne.cfg.n_heads,
                "mla_compression_ratio": round((sne.cfg.n_heads * sne.cfg.d_head * 2) / (sne.cfg.d_latent_kv + sne.cfg.d_rope), 2),
                "ssm_state_mb": round((sne.cfg.d_model * sne.cfg.d_state * 2) / (1024 * 1024), 4)
            }
            updated_subsystems.append("sovereign_neural_engine")
        except Exception as e:
            errors.append(f"Error sincronizando motor neuronal soberano: {e}")

        # ---------------------------------------------------------------------
        # 8. Sistema FTL :: Historial, Contexto y RAG Transversal
        # ---------------------------------------------------------------------
        ftl_info = {}
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault_inst = get_deep_memory_vault()
            con = vault_inst._connect()
            try:
                ftl_count = con.execute("SELECT count(*) FROM vault_events WHERE source LIKE 'ftl%'").fetchone()[0]
                last_ftl = con.execute("SELECT iso, content, meta FROM vault_events WHERE source LIKE 'ftl%' ORDER BY id DESC LIMIT 1").fetchone()
                ftl_info = {
                    "total_operations": ftl_count,
                    "last_operation_iso": last_ftl[0] if last_ftl else None,
                    "rag_indexed": True
                }
            finally:
                con.close()
            updated_subsystems.append("ftl_transversal_history")
        except Exception as e:
            errors.append(f"Error sincronizando historial FTL: {e}")

        # ---------------------------------------------------------------------
        # 9. Matriz de Continuidad Temporal Soberana (Post-Reboot Resilience)
        # ---------------------------------------------------------------------
        continuity_info = {}
        try:
            from core.tardis_continuity_engine import get_continuity_engine
            c_eng = get_continuity_engine()
            c_eng.render_desktop_dashboard()
            continuity_info = {
                "status": c_eng._active_session.get("status"),
                "progress_percent": c_eng._active_session.get("progress_percent"),
                "reboot_count": c_eng._active_session.get("reboot_count")
            }
            updated_subsystems.append("continuity_matrix")
        except Exception as e:
            errors.append(f"Error sincronizando matriz de continuidad: {e}")

        # Consolidar reporte final
        self.last_sync_ts = now
        self.last_sync_iso = iso
        self.last_report = {
            "ok": len(errors) == 0,
            "timestamp": now,
            "iso": iso,
            "updated_subsystems": updated_subsystems,
            "matrix": matrix_info,
            "hardware": hw_telemetry,
            "network": net_info,
            "vault": vault_info,
            "sync_hub": sync_hub_info,
            "cognition": cognitive_info,
            "neural_engine": neural_info,
            "ftl": ftl_info,
            "continuity": continuity_info,
            "errors": errors
        }

        logger.info(
            f"[AutoContextSynchronizer] ✓ Contexto sincronizado exitosamente en {len(updated_subsystems)} subsistemas "
            f"(Matriz v{matrix_info.get('version', '?')}, {vault_info.get('total_turns', 0)} turnos offline)."
        )
        return self.last_report

    def start_daemon(self, interval_seconds: int = 30) -> None:
        """Inicia el demonio de actualización periódica en segundo plano."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()

            def _daemon_loop():
                logger.info(f"[AutoContextSynchronizer] 🔄 Demonio de actualización de contexto iniciado (Intervalo: {interval_seconds}s).")
                # Ejecutar una primera sincronización inmediata
                try:
                    self.sync_all_systems()
                except Exception as e:
                    logger.error(f"[AutoContextSynchronizer] Error en ciclo inicial: {e}")

                while not self._stop_event.is_set():
                    self._stop_event.wait(timeout=interval_seconds)
                    if self._stop_event.is_set():
                        break
                    try:
                        self.sync_all_systems()
                    except Exception as e:
                        logger.error(f"[AutoContextSynchronizer] Error en ciclo periódico: {e}")
                logger.info("[AutoContextSynchronizer] Demonio de sincronización detenido.")

            self._daemon_thread = threading.Thread(target=_daemon_loop, name="AutoContextSynchronizerDaemon", daemon=True)
            self._daemon_thread.start()

    def stop_daemon(self) -> None:
        """Detiene el demonio en segundo plano."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            self._is_running = False


def get_auto_context_synchronizer() -> AutoContextSynchronizer:
    return AutoContextSynchronizer.get_instance()


def sync_all_systems_context() -> Dict[str, Any]:
    """Función de conveniencia para invocar la sincronización completa."""
    return get_auto_context_synchronizer().sync_all_systems()


if __name__ == "__main__":
    report = sync_all_systems_context()
    print(json.dumps(report, ensure_ascii=False, indent=2))
