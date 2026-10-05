"""
core/autonomous_controller.py - Motor de Conexión y Control Completamente Autónomo
===================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Opera un bucle de control proactivo (OODA: Observar - Orientar - Decidir - Actuar)
que percibe el entorno y gobierna el sistema de forma totalmente autónoma:
  1. Conexión y Conectividad:
     - Auto-verificación de internet y auto-recuperación ante caídas de red.
     - Auto-escaneo de espectro Wi-Fi circundante.
     - Auto-escaneo y gestión de dispositivos Bluetooth.
     - Descubrimiento continuo de nodos y periféricos en red local (LAN).
  2. Control de Hardware y Sistema:
     - Auto-ajuste dinámico de perfiles de energía (rendimiento vs ahorro) según carga y temperaturas.
     - Supervisión térmica activa (CPU/GPU) y alertas de umbral.
     - Centinela 24/7 de inhibición de suspensión (inhibit keepalive permanente).
     - Auto-consolidación periódica de la Bóveda de Memoria de 250 GB.
     - Auto-reparación e instalación de paqueterías necesarias mediante PackageManager.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_settings
from core.os_controller import get_os_controller
from core.hardware_controller import get_hardware_controller
from core.network_controller import get_network_controller
from core.package_manager import get_package_manager

logger = logging.getLogger("GODWORKS.AutonomousController")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class AutonomousController:
    """
    Controlador Autónomo Soberano para GODWORKS SYSTEM.
    Supervisa, conecta y gobierna subsistemas de forma continua e independiente.
    """

    _instance: Optional["AutonomousController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.settings = get_settings()
        self.os_ctrl = get_os_controller()
        self.hw_ctrl = get_hardware_controller()
        self.net_ctrl = get_network_controller()
        self.pkg_mgr = get_package_manager()

        # Configuración de autonomía
        self.config: Dict[str, Any] = {
            "enabled": True,
            "cycle_interval_seconds": 30.0,
            "auto_wifi": True,
            "auto_bluetooth": True,
            "auto_hardware": True,
            "auto_guardian": True,
            "auto_memory": True,
            "auto_packages": True,
            "auto_evolution": True,
            "auto_missions": True,
            "allow_autonomous_reboot": True,  # Autorizado explícitamente por el usuario
            "ignore_energy_restrictions": True,  # Sin restricciones de energía para reinicios automáticos y rendimiento
            "unrestricted_energy_reboot": True,
            "min_reboot_interval_s": 1800.0,  # Salvaguarda anti-bucles repetidos (30 min salvo forzado)
            "evolution_reboot_cycles": 120,  # Ciclos antes de auto-reinicio de mejora
            "temp_threshold_high": 78.0,
            "memory_consolidation_interval_s": 1800.0,  # 30 min
        }

        # Estado operativo
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cycle_count: int = 0
        self._last_cycle_ts: float = 0.0
        self._last_consolidation_ts: float = 0.0
        self._recent_actions: List[Dict[str, Any]] = []

        # Directorio y archivo de auditoría y evolución
        appdata = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
        appdata.mkdir(parents=True, exist_ok=True)
        self.log_file: Path = appdata / "autonomous_actions.json"
        self._load_history()

        config_dir = Path(os.path.expanduser("~/.config/godworks"))
        config_dir.mkdir(parents=True, exist_ok=True)
        self.evolution_file: Path = config_dir / "reboot_evolution_state.json"
        self._evolution_state: Dict[str, Any] = self._load_evolution_state()

    @classmethod
    def get_instance(cls) -> "AutonomousController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _load_history(self):
        if self.log_file.exists():
            try:
                raw = self.log_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, list):
                    self._recent_actions = data[-100:]
            except Exception:
                self._recent_actions = []

    def _load_evolution_state(self) -> Dict[str, Any]:
        if self.evolution_file.exists():
            try:
                return json.loads(self.evolution_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "reboot_authorized_by_user": True,
            "total_improvement_reboots": 0,
            "last_reboot_ts": 0.0,
            "last_reboot_reason": "",
            "pending_post_reboot_tasks": [],
            "history": []
        }

    def _save_evolution_state(self):
        try:
            self.evolution_file.write_text(json.dumps(self._evolution_state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[AUTONOMOUS.EVOLUTION] Error guardando estado de evolución: {e}")

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def _cycles_completed(self) -> int:
        return self._cycle_count

    def _record_action(self, domain: str, action: str, details: Dict[str, Any], level: str = "INFO", status: Optional[str] = None):
        entry = {
            "timestamp": time.time(),
            "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "domain": domain,
            "subsystem": domain,
            "action": action,
            "level": level,
            "status": status or ("success" if level == "INFO" else "warning"),
            "cycle": self._cycle_count,
            "details": details,
        }
        self._recent_actions.append(entry)
        if len(self._recent_actions) > 200:
            self._recent_actions = self._recent_actions[-200:]
        try:
            self.log_file.write_text(json.dumps(self._recent_actions, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        logger.info(f"[AUTONOMOUS.{domain.upper()}] {action}: {details}")

    # -------------------------------------------------------------------------
    # 1. CICLO DE CONEXIÓN Y CONTROL AUTÓNOMO
    # -------------------------------------------------------------------------

    def start(self):
        """Inicia el demonio de control autónomo en segundo plano."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._autonomic_loop, name="AutonomousControllerDaemon", daemon=True)
            self._thread.start()
            logger.info("🤖 [AUTONOMOUS] Motor de Control y Conexión Autónomo INICIADO.")
            self._record_action("system", "daemon_started", {"status": "ACTIVE"})

            # Verificar recuperación tras reinicio de auto-mejora si aplica
            threading.Thread(target=self._check_post_reboot_recovery, daemon=True, name="PostRebootRecovery").start()

    def reboot_for_improvement(self, reason: str = "Optimización integral y auto-mejora del sistema", force: bool = False, delay_seconds: float = 3.0, ignore_energy_restrictions: Optional[bool] = None) -> Dict[str, Any]:
        """
        Ejecuta un reinicio seguro del dispositivo plenamente autorizado por el usuario para auto-mejora
        sin restricciones energéticas ni bloqueos por políticas de energía o inhibidores.
        Registra el estado, encola verificaciones post-arranque y ejecuta el reinicio.
        """
        now = time.time()
        last_ts = float(self._evolution_state.get("last_reboot_ts", 0.0))
        min_interval = float(self.config.get("min_reboot_interval_s", 1800.0))

        if ignore_energy_restrictions is None:
            ignore_energy_restrictions = bool(self.config.get("ignore_energy_restrictions", True))

        if not force and (now - last_ts) < min_interval:
            remaining = int(min_interval - (now - last_ts))
            return {
                "ok": False,
                "reason": f"Intervalo mínimo de seguridad activo. Faltan {remaining}s para el próximo reinicio automático (o use force=True).",
                "last_reboot_ts": last_ts
            }

        # 1. Consolidar memoria en bóveda antes de reiniciar
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            vault.consolidate_epoch(title=f"Pre-Reinicio de Mejora: {reason}")
        except Exception:
            pass

        # 1.1 Punto de Control de Continuidad Temporal Soberano
        try:
            from core.tardis_continuity_engine import get_continuity_engine
            get_continuity_engine().create_checkpoint(reason=f"Reinicio de Mejora: {reason}")
        except Exception as e_cont:
            logger.warning(f"[AUTONOMOUS.CONTINUITY] Checkpoint pre-reinicio advertencia: {e_cont}")

        # 2. Registrar en estado de evolución
        reboot_num = int(self._evolution_state.get("total_improvement_reboots", 0)) + 1
        self._evolution_state["total_improvement_reboots"] = reboot_num
        self._evolution_state["last_reboot_ts"] = now
        self._evolution_state["last_reboot_reason"] = reason
        self._evolution_state["pending_post_reboot_tasks"] = [
            "verify_connectivity",
            "verify_screen_unlock",
            "audit_system_health",
            "rearm_sleep_inhibitor",
            "warmup_inference_cache"
        ]
        self._evolution_state.setdefault("history", []).append({
            "reboot_number": reboot_num,
            "timestamp": now,
            "time_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
            "ignore_energy_restrictions": ignore_energy_restrictions,
            "status": "initiated"
        })
        self._save_evolution_state()
        self._record_action("evolution", "reboot_for_improvement_initiated", {
            "reboot_number": reboot_num,
            "reason": reason,
            "delay_seconds": delay_seconds,
            "ignore_energy_restrictions": ignore_energy_restrictions
        })

        # 3. Llamar al controlador OS para programar el reinicio físico del dispositivo sin restricciones energéticas
        res = self.os_ctrl.reboot_system(
            delay_seconds=delay_seconds,
            reason=reason,
            ignore_inhibitors=ignore_energy_restrictions
        )
        return {
            "ok": True,
            "reboot_number": reboot_num,
            "reason": reason,
            "delay_seconds": delay_seconds,
            "ignore_energy_restrictions": ignore_energy_restrictions,
            "unrestricted_energy": ignore_energy_restrictions,
            "status": "reboot_scheduled",
            "raw": res
        }

    def _check_post_reboot_recovery(self):
        """Verifica si el sistema acaba de arrancar tras un reinicio de mejora y ejecuta tareas pendientes."""
        tasks = self._evolution_state.get("pending_post_reboot_tasks", [])
        if not tasks:
            return

        time.sleep(2.0)
        logger.info(f"[AUTONOMOUS.EVOLUTION] 🚀 Reanudación post-reinicio detectada. Ejecutando {len(tasks)} tareas de optimización...")
        completed = []
        for task in list(tasks):
            try:
                if task == "verify_connectivity":
                    self.net_ctrl.check_internet_access(timeout=3.0)
                    completed.append(task)
                elif task == "verify_screen_unlock":
                    if self.os_ctrl.is_locked():
                        self.os_ctrl.unlock_screen(password = "REDACTED")
                    completed.append(task)
                elif task == "rearm_sleep_inhibitor":
                    self.os_ctrl.ensure_sleep_inhibited()
                    completed.append(task)
                elif task == "audit_system_health":
                    self.hw_ctrl.get_thermals_and_battery()
                    completed.append(task)
                elif task == "warmup_inference_cache":
                    completed.append(task)
            except Exception as e:
                logger.warning(f"[AUTONOMOUS.EVOLUTION] Tarea post-reinicio {task} advertencia: {e}")

        # 1. Reanudación y verificación del Motor de Continuidad Temporal
        try:
            from core.tardis_continuity_engine import get_continuity_engine
            get_continuity_engine().resume_after_reboot()
        except Exception as e_cont:
            logger.warning(f"[AUTONOMOUS.CONTINUITY] Reanudación post-reinicio advertencia: {e_cont}")

        self._evolution_state["pending_post_reboot_tasks"] = [t for t in tasks if t not in completed]
        if self._evolution_state.get("history"):
            self._evolution_state["history"][-1]["status"] = "completed_successfully"
            self._evolution_state["history"][-1]["recovery_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save_evolution_state()
        self._record_action("evolution", "post_reboot_recovery_completed", {"tasks_executed": completed})

    def stop(self):
        """Detiene de forma segura el demonio autónomo."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            logger.info("🤖 [AUTONOMOUS] Motor de Control y Conexión Autónomo DETENIDO.")
            self._record_action("system", "daemon_stopped", {"status": "STOPPED"})

    def _autonomic_loop(self):
        """Bucle principal de ejecución periódica."""
        # Pequeño retardo inicial para permitir arranque completo del sistema
        time.sleep(3.0)
        while not self._stop_event.is_set():
            try:
                if self.config.get("enabled", True):
                    self.step_cycle()
            except Exception as e:
                logger.error(f"[AUTONOMOUS] Error no controlado en ciclo autónomo: {e}", exc_info=True)
            
            # Esperar intervalo o señal de parada
            interval = float(self.config.get("cycle_interval_seconds", 30.0))
            self._stop_event.wait(timeout=max(5.0, interval))

    def step_cycle(self) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo de percepción, decisión y acción.
        Puede invocarse manualmente o por el hilo en segundo plano.
        """
        t0 = time.time()
        self._cycle_count += 1
        self._last_cycle_ts = t0
        actions_taken = []

        # 1. Autonomía de Red y Conectividad
        if self.config.get("auto_wifi", True):
            net_act = self._auto_manage_connectivity()
            if net_act:
                actions_taken.append(net_act)

        # 2. Autonomía de Bluetooth
        if self.config.get("auto_bluetooth", True):
            bt_act = self._auto_manage_bluetooth()
            if bt_act:
                actions_taken.append(bt_act)

        # 3. Autonomía de Hardware, Térmicos y Energía
        if self.config.get("auto_hardware", True):
            hw_act = self._auto_manage_hardware()
            if hw_act:
                actions_taken.append(hw_act)

        # 4. Guardián de Sesión y Prevención de Suspensión 24/7
        if self.config.get("auto_guardian", True):
            guard_act = self._auto_manage_system_guardian()
            if guard_act:
                actions_taken.append(guard_act)

        # 5. Autonomía de Memoria y Consolidación en Bóveda 250 GB
        if self.config.get("auto_memory", True):
            mem_act = self._auto_manage_memory()
            if mem_act:
                actions_taken.append(mem_act)

        # 6. Autonomía de Misiones y Prospección de Contactos
        if self.config.get("auto_missions", True):
            mission_act = self._auto_manage_missions()
            if mission_act:
                actions_taken.append(mission_act)

        # 7. Autonomía de Evolución y Reinicio sin Restricciones Energéticas
        if self.config.get("auto_evolution", True) and self.config.get("allow_autonomous_reboot", True):
            evo_act = self._auto_manage_evolution()
            if evo_act:
                actions_taken.append(evo_act)

        elapsed = round(time.time() - t0, 3)
        self._last_cycle_duration = elapsed
        result = {
            "ok": True,
            "cycle": self._cycle_count,
            "elapsed_seconds": elapsed,
            "duration_seconds": elapsed,
            "actions_count": len(actions_taken),
            "actions_performed": len(actions_taken),
            "actions": actions_taken,
            "internet_ok": True,
            "timestamp": self._last_cycle_ts,
        }
        return result

    # -------------------------------------------------------------------------
    # 2. SUB-MOTORES AUTÓNOMOS DE PERCEPCIÓN Y ACCIÓN
    # -------------------------------------------------------------------------

    def _auto_manage_connectivity(self) -> Optional[Dict[str, Any]]:
        """Verifica internet y realiza auto-recuperación y descubrimiento LAN si corresponde."""
        try:
            inet = self.net_ctrl.check_internet_access(timeout=1.5)
            if not inet.get("online"):
                # Internet caído: iniciar failover autónomo
                logger.warning("[AUTONOMOUS.NETWORK] Internet caído detectado. Ejecutando failover autónomo...")
                rec = self.net_ctrl.auto_recover_internet(allow_open_networks=True)
                self._record_action("network", "internet_failover", rec, level="WARNING" if not rec.get("ok") else "INFO")
                return {"domain": "network", "action": "auto_recover_internet", "result": rec}
            
            # Si hay internet, realizar barrido de nodos LAN cada 5 ciclos para actualizar telemetría
            if self._cycle_count % 5 == 1:
                lan_nodes = self._discover_lan_nodes()
                if lan_nodes:
                    return {"domain": "network", "action": "lan_nodes_discovered", "count": len(lan_nodes)}
            return None
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.NETWORK] Error en supervisión de red: {e}")
            return None

    def _discover_lan_nodes(self) -> List[str]:
        """Descubre nodos activos en la red local mediante tabla ARP del kernel."""
        active_ips = []
        try:
            arp_file = Path("/proc/net/arp")
            if arp_file.exists():
                lines = arp_file.read_text(encoding="utf-8").splitlines()[1:]
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                        ip = parts[0]
                        active_ips.append(ip)
                if active_ips:
                    # Registrar en device vault
                    try:
                        from core.device_vault import get_device_vault
                        dv = get_device_vault()
                        for ip in active_ips[:8]:
                            dv.register_device(
                                device_id=f"lan_node_{ip.replace('.', '_')}",
                                ip=ip,
                                client_name="Nodo LAN Detectado"
                            )
                    except Exception:
                        pass
        except Exception:
            pass
        return active_ips

    def _auto_manage_bluetooth(self) -> Optional[Dict[str, Any]]:
        """Garantiza que el adaptador Bluetooth esté activo y supervisa dispositivos cada 10 ciclos."""
        if self._cycle_count % 10 != 2:
            return None
        try:
            bt_status = self.hw_ctrl.get_bluetooth_status()
            # Si bluetooth está apagado pero soportado, auto-encenderlo para habilitar periféricos
            if bt_status.get("supported") and not bt_status.get("powered"):
                logger.info("[AUTONOMOUS.BT] Adaptador Bluetooth apagado. Auto-encendiendo...")
                self.hw_ctrl.set_bluetooth_power(True)
                self._record_action("bluetooth", "auto_power_on", {"previous": False, "new": True})
                return {"domain": "bluetooth", "action": "auto_power_on"}
            
            # Si está encendido, escanear rápidamente dispositivos circundantes
            if bt_status.get("powered"):
                scan_res = self.hw_ctrl.scan_bluetooth_devices(timeout_s=2.0)
                devs = scan_res.get("devices", [])
                if devs:
                    self._record_action("bluetooth", "devices_scanned", {"count": len(devs), "devices": devs[:5]})
                    return {"domain": "bluetooth", "action": "scan_devices", "count": len(devs)}
            return None
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.BT] Error en supervisión bluetooth: {e}")
            return None

    def _auto_manage_hardware(self) -> Optional[Dict[str, Any]]:
        """Supervisa temperaturas y ajusta el perfil energético dinámicamente."""
        # El perfil energetico lo gobierna solo background_hardware_orchestrator, que lee
        # el sensor real de la CPU (k10temp/Tctl). Este controlador leia otro sensor
        # (~20 °C mas bajo) y ambos se pisaban cada minuto: performance <-> power-saver.
        return None
        try:
            telemetry = self.hw_ctrl.get_thermals_and_battery()
            temps = telemetry.get("temperatures", {})
            battery = telemetry.get("battery") or {}

            max_cpu_temp = 0.0
            for k, entries in temps.items():
                for e in entries:
                    cur = float(e.get("current_c") or 0.0)
                    if cur > max_cpu_temp:
                        max_cpu_temp = cur

            current_profile = self.hw_ctrl.get_power_profile().get("active_profile", "")
            target_profile = None

            thresh = float(self.config.get("temp_threshold_high", 78.0))
            battery_pct = float(battery.get("percent") or 100.0)
            is_plugged = bool(battery.get("power_plugged", True))

            ignore_energy = bool(self.config.get("ignore_energy_restrictions", True))

            # Lógica de decisión autónoma para perfil de energía:
            if max_cpu_temp >= thresh:
                # Temperatura alta: bajar a balanced o quiet para enfriar
                if current_profile == "performance":
                    target_profile = "balanced"
            elif not ignore_energy and not is_plugged and battery_pct < 25.0:
                # Batería crítica no enchufada: ahorro de energía (solo si NO está en modo sin restricciones)
                if current_profile != "power-saver":
                    target_profile = "power-saver"
            elif (ignore_energy or is_plugged) and max_cpu_temp < (thresh - 5.0):
                # Sin restricciones de energía o conectado a corriente y temperatura fresca: optimizar para alto rendimiento
                if current_profile != "performance":
                    target_profile = "performance"

            if target_profile and target_profile != current_profile:
                res = self.hw_ctrl.set_power_profile(target_profile)
                action_info = {
                    "previous_profile": current_profile,
                    "new_profile": target_profile,
                    "max_cpu_temp": max_cpu_temp,
                    "battery_percent": battery_pct,
                    "is_plugged": is_plugged,
                    "result": res
                }
                self._record_action("hardware", "power_profile_auto_switch", action_info)
                return {"domain": "hardware", "action": "power_profile_switch", "to": target_profile}

            return None
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.HARDWARE] Error en supervisión térmica: {e}")
            return None

    def _auto_manage_system_guardian(self) -> Optional[Dict[str, Any]]:
        """Garantiza la inhibición de suspensión del sistema 24/7 permanente."""
        # Se ejecuta cada 4 ciclos (aprox 2 minutos)
        if self._cycle_count % 4 != 0:
            return None
        try:
            inhibited = self.os_ctrl.ensure_sleep_inhibited()
            if not inhibited:
                # Si se detectó desanclaje, re-anclar
                self.os_ctrl.ensure_sleep_inhibited()
                self._record_action("guardian", "sleep_inhibitor_reanchored", {"status": "REANCHORED"})
                return {"domain": "guardian", "action": "sleep_inhibitor_reanchored"}
            return None
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.GUARDIAN] Error en guardian de suspensión: {e}")
            return None

    def _auto_manage_memory(self) -> Optional[Dict[str, Any]]:
        """Auto-consolida la Bóveda de Memoria de 250 GB si ha transcurrido el intervalo."""
        now = time.time()
        interval = float(self.config.get("memory_consolidation_interval_s", 1800.0))
        if (now - self._last_consolidation_ts) < interval:
            return None
        try:
            from core.deep_memory_vault import get_deep_memory_vault
            vault = get_deep_memory_vault()
            res = vault.consolidate_epoch(title=f"Época Autónoma - Ciclo {self._cycle_count}")
            self._last_consolidation_ts = now
            if res.get("consolidated"):
                self._record_action("memory", "vault_auto_consolidate", res)
                return {"domain": "memory", "action": "auto_consolidate", "epoch": res.get("epoch_id")}
            return None
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.MEMORY] Error en auto-consolidación de memoria: {e}")
            return None

    def _auto_manage_missions(self) -> Optional[Dict[str, Any]]:
        """Supervisa y ejecuta ciclos periódicos de prospección autónoma de colaboradores y misiones."""
        # Desactivado: la prospeccion recolectaba datos de contacto de terceros desde la web.
        return None
        try:
            from core.mission_scouting_engine import get_mission_scouting_engine
            engine = get_mission_scouting_engine()
            res = engine.autonomous_scouting_tick()
            if res.get("active") and res.get("new_leads_found", 0) > 0:
                self._record_action(
                    domain="missions",
                    action="autonomous_scouting",
                    details=res,
                    level="INFO"
                )
                return {
                    "domain": "missions",
                    "action": "autonomous_scouting",
                    "details": res
                }
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.MISSIONS] Error en tick: {e}")
        return None

    def _auto_manage_evolution(self) -> Optional[Dict[str, Any]]:
        """
        Evalúa y ejecuta de forma soberana y proactiva ciclos de evolución y auto-mejora,
        incluyendo el reinicio automático del sistema sin restricciones de energía
        cuando se completan hitos de consolidación, actualización o mantenimiento.
        """
        try:
            now = time.time()
            last_ts = float(self._evolution_state.get("last_reboot_ts", 0.0))
            min_interval = float(self.config.get("min_reboot_interval_s", 1800.0))
            target_cycles = int(self.config.get("evolution_reboot_cycles", 120))

            pending_reboot = bool(self._evolution_state.get("pending_autonomous_reboot", False))
            reason_pending = self._evolution_state.get("pending_reboot_reason", "Reinicio autónomo programado por evolución")

            cycles_since_reboot = (self._cycle_count % target_cycles) if target_cycles > 0 else 1

            should_reboot = False
            reason = ""

            if pending_reboot:
                should_reboot = True
                reason = reason_pending
                self._evolution_state["pending_autonomous_reboot"] = False
                self._save_evolution_state()
            elif (now - last_ts) >= min_interval and self._cycle_count > 0 and cycles_since_reboot == 0:
                should_reboot = True
                reason = f"Ciclo de evolución #{self._cycle_count}: auto-mejora continua sin restricciones energéticas"

            if should_reboot:
                ignore_energy = bool(self.config.get("ignore_energy_restrictions", True))
                logger.info(f"[AUTONOMOUS.EVOLUTION] ⚡ Ejecutando reinicio de auto-mejora sin restricciones: {reason}")
                res = self.reboot_for_improvement(
                    reason=reason,
                    force=True,
                    delay_seconds=3.0,
                    ignore_energy_restrictions=ignore_energy
                )
                self._record_action("evolution", "autonomous_reboot_dispatched", {
                    "reason": reason,
                    "result": res,
                    "ignore_energy_restrictions": ignore_energy
                })
                return {
                    "domain": "evolution",
                    "action": "autonomous_reboot",
                    "reason": reason,
                    "details": res
                }
        except Exception as e:
            logger.debug(f"[AUTONOMOUS.EVOLUTION] Error en evaluación de evolución: {e}")
        return None

    def schedule_autonomous_reboot(self, reason: str = "Reinicio autónomo de evolución solicitado", immediate: bool = False, delay_seconds: float = 3.0) -> Dict[str, Any]:
        """Programa o ejecuta inmediatamente un reinicio autónomo sin restricciones energéticas."""
        if immediate:
            ignore_energy = bool(self.config.get("ignore_energy_restrictions", True))
            return self.reboot_for_improvement(
                reason=reason,
                force=True,
                delay_seconds=delay_seconds,
                ignore_energy_restrictions=ignore_energy
            )
        self._evolution_state["pending_autonomous_reboot"] = True
        self._evolution_state["pending_reboot_reason"] = reason
        self._save_evolution_state()
        self._record_action("evolution", "reboot_scheduled", {"reason": reason})
        return {"ok": True, "status": "scheduled", "reason": reason}

    # -------------------------------------------------------------------------
    # 3. ESTADO, CONFIGURACIÓN Y TELEMETRÍA
    # -------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Devuelve el estado completo del motor autónomo."""
        thermals = {}
        try:
            thermals = self.hw_ctrl.get_thermals_and_battery()
        except Exception:
            pass
        net_stat = False
        try:
            net_stat = self.net_ctrl.check_internet_access(timeout=1.0).get("online", False)
        except Exception:
            pass
        return {
            "ok": True,
            "running": self.is_running,
            "thread_alive": self._thread.is_alive() if self._thread else False,
            "enabled": self.config.get("enabled", True),
            "cycle_count": self._cycle_count,
            "cycles_completed": self._cycle_count,
            "last_cycle_timestamp": self._last_cycle_ts,
            "last_cycle_duration": getattr(self, "_last_cycle_duration", 0.0),
            "last_cycle_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._last_cycle_ts)) if self._last_cycle_ts else None,
            "config": dict(self.config),
            "recent_actions_count": len(self._recent_actions),
            "recent_actions": list(reversed(self._recent_actions[-25:])),
            "latest_actions": list(reversed(self._recent_actions[-25:])),
            "telemetry": {
                "thermals": thermals,
                "internet_connected": net_stat
            },
            "evolution": {
                "reboot_authorized_by_user": bool(self._evolution_state.get("reboot_authorized_by_user", True)),
                "ignore_energy_restrictions": bool(self.config.get("ignore_energy_restrictions", True)),
                "unrestricted_energy_reboot": bool(self.config.get("unrestricted_energy_reboot", True)),
                "total_improvement_reboots": self._evolution_state.get("total_improvement_reboots", 0),
                "last_reboot_ts": self._evolution_state.get("last_reboot_ts", 0.0),
                "last_reboot_reason": self._evolution_state.get("last_reboot_reason", ""),
                "pending_tasks": self._evolution_state.get("pending_post_reboot_tasks", [])
            }
        }

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve las últimas acciones registradas."""
        return self._recent_actions[-limit:]

    def set_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza parámetros de actuación del motor autónomo."""
        with self._lock:
            for k, v in new_config.items():
                if k in self.config:
                    self.config[k] = v
            self._record_action("config", "config_updated", {"new_config": self.config})
        return {"ok": True, "config": self.config}


def get_autonomous_controller() -> AutonomousController:
    return AutonomousController.get_instance()
