"""
core/background_hardware_orchestrator.py - Orquestador Autónomo de Hardware en Segundo Plano Multi-Capa
GODWORKS SYSTEM - TARDIS-NEURAL-SPACE-KAIJU

Proporciona monitoreo, supervisión y modulación autónoma y continua de 5 capas de hardware y SO:
  1. Capa 1: Acústica y Audio (PipeWire / ALSA)
  2. Capa 2: Óptica y Pantalla (Brillo de pantalla, teclado ASUS TUF, DPMS, sesión)
  3. Capa 3: Potencia, Silicio y Térmica (CPU AMD Ryzen, GPU NVIDIA RTX, perfiles energéticos)
  4. Capa 4: Radiofrecuencia y Redes (Wi-Fi wlp3s0, Bluetooth, Hotspot Soberano TimeMachine)
  5. Capa 5: Memoria, Procesos y Silicio (Working Set 18 GB RAM, malloc_trim, watchdog systemd)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

from core.hardware_controller import get_hardware_controller, HardwareController
from core.network_controller import get_network_controller, NetworkController
from core.os_controller import get_os_controller, OSController

logger = logging.getLogger("godworks.background_hardware")

BRIGHTNESS_SYSFS_DIR = Path("/sys/class/backlight")


class BackgroundHardwareOrchestrator:
    """
    Orquestador autónomo que supervisa y modula el hardware físico en segundo plano
    a través de 5 capas operativas independientes.
    """

    _instance: Optional["BackgroundHardwareOrchestrator"] = None
    _lock = threading.Lock()

    def __init__(self, cycle_interval_seconds: float = 15.0):
        self.cycle_interval_seconds = cycle_interval_seconds
        self.hw: HardwareController = get_hardware_controller()
        self.net: NetworkController = get_network_controller()
        self.os_c: OSController = get_os_controller()

        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._telemetry_lock = threading.Lock()

        # Telemetría en vivo consolidada
        self._latest_telemetry: Dict[str, Any] = {
            "layer_1_audio": {},
            "layer_2_optical": {},
            "layer_3_power_thermals": {},
            "layer_4_rf_networks": {},
            "layer_5_silicon_memory": {},
            "timestamp": time.time(),
            "cycles_completed": 0,
            "anomalies_detected": []
        }

        # Configuración de políticas autónomas
        self.auto_power_profile_enabled = True
        self.auto_memory_trim_enabled = True
        self.auto_wifi_watchdog_enabled = True
        self.auto_keyboard_sync_enabled = True

        # Umbrales
        # Ryzen 7 4800H: Tjmax 105 °C; 80-85 °C bajo carga sostenida es normal en laptop
        self.temp_threshold_high_c = 88.0
        self.temp_threshold_critical_c = 95.0
        self.temp_restore_c = 78.0     # histeresis de 10 °C bajo el umbral alto

    @classmethod
    def get_instance(cls) -> "BackgroundHardwareOrchestrator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self) -> None:
        """Inicia el demonio de control de hardware en segundo plano."""
        with self._lock:
            if self._running and self._worker_thread and self._worker_thread.is_alive():
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._orchestration_loop,
                name="TARDIS-BackgroundHardwareOrchestrator",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("⚡ [BACKGROUND_HARDWARE] Orquestador de hardware multi-capa iniciado con éxito.")

    def stop(self) -> None:
        """Detiene el orquestador."""
        with self._lock:
            self._running = False

    def is_running(self) -> bool:
        return bool(self._running and self._worker_thread and self._worker_thread.is_alive())

    # =========================================================================
    # CAPA 1: ACÚSTICA Y AUDIO
    # =========================================================================

    def inspect_layer_1_audio(self) -> Dict[str, Any]:
        """Monitorea y regula el subsistema de audio PipeWire / ALSA."""
        vol_info = self.hw.get_volume()
        
        # Obtener sinks de audio activos si wpctl o pactl existen
        active_sinks = []
        try:
            if shutil.which("wpctl"):
                res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=2.0)
                active_sinks = [line.strip() for line in res.stdout.split("\n") if "*" in line and "Audio/Sink" in line]
        except Exception:
            pass

        return {
            "volume_percent": vol_info.get("volume_percent", 0),
            "muted": vol_info.get("muted", False),
            "active_sinks": active_sinks,
            "status": "normal"
        }

    # =========================================================================
    # CAPA 2: ÓPTICA, PANTALLA Y RETROILUMINACIÓN
    # =========================================================================

    def get_screen_brightness(self) -> Dict[str, Any]:
        """Obtiene el brillo actual y máximo de la pantalla."""
        # 1. Intentar brightnessctl
        if shutil.which("brightnessctl"):
            try:
                res = subprocess.run(["brightnessctl", "get"], capture_output=True, text=True, timeout=2.0)
                res_max = subprocess.run(["brightnessctl", "max"], capture_output=True, text=True, timeout=2.0)
                curr = int(res.stdout.strip())
                max_b = int(res_max.stdout.strip())
                pct = int(round((curr / float(max_b or 1)) * 100))
                return {"ok": True, "current": curr, "max": max_b, "percent": pct}
            except Exception:
                pass

        # 2. Fallback por sysfs
        try:
            for d in BRIGHTNESS_SYSFS_DIR.glob("*"):
                b_file = d / "brightness"
                m_file = d / "max_brightness"
                if b_file.exists() and m_file.exists():
                    curr = int(b_file.read_text().strip())
                    max_b = int(m_file.read_text().strip())
                    pct = int(round((curr / float(max_b or 1)) * 100))
                    return {"ok": True, "current": curr, "max": max_b, "percent": pct, "device": d.name}
        except Exception:
            pass

        return {"ok": False, "percent": 100, "error": "No backlight device detected"}

    def set_screen_brightness(self, percent: int | float) -> Dict[str, Any]:
        """Ajusta el brillo de pantalla (0 a 100%)."""
        pct = max(5, min(100, int(percent)))
        if shutil.which("brightnessctl"):
            try:
                subprocess.run(["brightnessctl", "set", f"{pct}%"], capture_output=True, text=True, timeout=2.0)
                return {"ok": True, "percent": pct, "method": "brightnessctl"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "brightnessctl no disponible"}

    def inspect_layer_2_optical(self) -> Dict[str, Any]:
        """Monitorea pantalla, teclado ASUS TUF y sesión visual."""
        screen_b = self.get_screen_brightness()
        kbd_b = self.hw.get_keyboard_brightness()
        is_locked = self.os_c.is_locked()
        w, h = self.os_c.get_screen_resolution()

        return {
            "screen_brightness_percent": screen_b.get("percent", 100),
            "keyboard_backlight_level": kbd_b.get("level", 0),
            "keyboard_max_level": kbd_b.get("max_level", 3),
            "screen_locked": is_locked,
            "resolution": f"{w}x{h}",
            "dpms_awake": True
        }

    # =========================================================================
    # CAPA 3: POTENCIA, SILICIO Y TÉRMICA
    # =========================================================================

    def inspect_layer_3_power_thermals(self) -> Dict[str, Any]:
        """Monitorea temperaturas de CPU/GPU, perfiles energéticos y batería."""
        pwr_profile = self.hw.get_power_profile()
        thermals_bat = self.hw.get_thermals_and_battery()
        bat = thermals_bat.get("battery") or {}
        temps = thermals_bat.get("temperatures") or {}

        max_cpu_temp = 0.0
        for name, entries in temps.items():
            for e in entries:
                if "cpu" in e.get("label", "").lower() or "tctl" in e.get("label", "").lower() or "k10temp" in name.lower():
                    max_cpu_temp = max(max_cpu_temp, float(e.get("current_c") or 0))

        # Modulación autónoma de perfil si está activado
        active_prof = pwr_profile.get("active_profile", "performance")
        switched = False
        action_note = ""

        if self.auto_power_profile_enabled:
            is_plugged = bat.get("power_plugged", True)
            if max_cpu_temp >= self.temp_threshold_critical_c:
                # Mitigar estrangulamiento térmico bajando a balanced o power-saver
                if active_prof != "power-saver":
                    self.hw.set_power_profile("power-saver")
                    switched = True
                    action_note = f"Degradado a power-saver por temperatura crítica ({max_cpu_temp:.1f}°C)"
            elif max_cpu_temp >= self.temp_threshold_high_c:
                if active_prof == "performance":
                    self.hw.set_power_profile("balanced")
                    switched = True
                    action_note = f"Degradado a balanced por alta temperatura ({max_cpu_temp:.1f}°C)"
            elif max_cpu_temp < self.temp_restore_c and is_plugged and active_prof != "performance":
                self.hw.set_power_profile("performance")
                switched = True
                action_note = f"Restaurado a performance (temperatura óptima {max_cpu_temp:.1f}°C y AC conectado)"

        return {
            "active_profile": active_prof,
            "max_cpu_temp_c": max_cpu_temp,
            "battery_percent": bat.get("percent", 100),
            "power_plugged": bat.get("power_plugged", True),
            "profile_auto_switched": switched,
            "policy_action": action_note
        }

    # =========================================================================
    # CAPA 4: RADIOFRECUENCIA Y REDES
    # =========================================================================

    def inspect_layer_4_rf_networks(self) -> Dict[str, Any]:
        """Monitorea la interfaz Wi-Fi, Bluetooth y Hotspot Soberano."""
        net_status = self.net.get_status()
        bt_status = self.hw.get_bluetooth_status()
        hotspot_status = self.net.get_hotspot_status()

        # Watchdog Wi-Fi: si no hay conexión activa, auto-recuperar
        recovered = False
        if self.auto_wifi_watchdog_enabled and not net_status.get("active_connection", {}).get("connection"):
            logger.info("⚠️ [RF_WATCHDOG] Wi-Fi sin conexión detectada, ejecutando auto-recuperación...")
            res_rec = self.net.auto_recover_internet(allow_open_networks=True)
            recovered = res_rec.get("ok", False)

        return {
            "wifi_connected": bool(net_status.get("active_connection", {}).get("connection")),
            "active_ssid": net_status.get("active_connection", {}).get("connection", "Desconectado"),
            "hotspot_active": hotspot_status.get("active", False),
            "hotspot_clients_count": hotspot_status.get("client_count", 0),
            "bluetooth_powered": bt_status.get("powered", False),
            "bluetooth_paired_count": bt_status.get("paired_count", 0),
            "wifi_recovered_this_cycle": recovered
        }

    # =========================================================================
    # CAPA 5: MEMORIA, PROCESOS Y SILICIO
    # =========================================================================

    def inspect_layer_5_silicon_memory(self) -> Dict[str, Any]:
        """Supervisa el consumo del Working Set de RAM (18 GB / 26 GB para 32 GB), swaps y glibc."""
        ram_percent = 0.0
        ram_used_gb = 0.0
        ram_total_gb = 24.0
        trimmed = False

        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            ram_percent = mem.percent
            ram_used_gb = round(mem.used / (1024 ** 3), 2)
            ram_total_gb = round(mem.total / (1024 ** 3), 2)

            # Si la memoria supera el 88% y la política está activa, ejecutar malloc_trim
            if self.auto_memory_trim_enabled and ram_percent > 88.0:
                try:
                    import ctypes
                    libc = ctypes.CDLL("libc.so.6")
                    libc.malloc_trim(0)
                    trimmed = True
                    logger.info(f"🧹 [MEMORY_TRIM] malloc_trim(0) ejecutado ante uso de RAM ({ram_percent}%)")
                except Exception:
                    pass

        # Cálculo dinámico del presupuesto de memoria (28 GB mlock para 32 GB de RAM, 18 GB para 24 GB)
        default_target = 28.0 if ram_total_gb >= 30.0 else (18.0 if ram_total_gb >= 22.0 else round(ram_total_gb * 0.75, 1))
        target_ws = float(os.environ.get("GIA_RAM_BUDGET_GB", str(default_target)))

        return {
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "ram_percent": ram_percent,
            "memory_trimmed_this_cycle": trimmed,
            "target_working_set_gb": target_ws
        }

    # =========================================================================
    # BUCLE PRINCIPAL DE ORQUESTACIÓN
    # =========================================================================

    def _orchestration_loop(self) -> None:
        """Ciclo continuo que ejecuta el monitoreo y modulación de las 5 capas."""
        while self._running:
            try:
                t1 = self.inspect_layer_1_audio()
                t2 = self.inspect_layer_2_optical()
                t3 = self.inspect_layer_3_power_thermals()
                t4 = self.inspect_layer_4_rf_networks()
                t5 = self.inspect_layer_5_silicon_memory()

                # Telemetría de presencia física sensorial
                presence_data = {}
                try:
                    from core.physical_presence_sensor import get_physical_presence_sensor
                    presence_data = get_physical_presence_sensor().get_presence_reading().to_dict()
                except Exception:
                    pass

                anomalies = []
                if t3.get("max_cpu_temp_c", 0) >= self.temp_threshold_high_c:
                    anomalies.append(f"Alta temperatura de CPU: {t3['max_cpu_temp_c']:.1f}°C")
                if not t4.get("wifi_connected"):
                    anomalies.append("Conexión Wi-Fi inactiva o intermitente")
                if t5.get("ram_percent", 0) > 90.0:
                    anomalies.append(f"Uso crítico de RAM: {t5['ram_percent']}%")

                with self._telemetry_lock:
                    self._latest_telemetry = {
                        "layer_1_audio": t1,
                        "layer_2_optical": t2,
                        "layer_3_power_thermals": t3,
                        "layer_4_rf_networks": t4,
                        "layer_5_silicon_memory": t5,
                        "physical_presence": presence_data,
                        "timestamp": time.time(),
                        "cycles_completed": self._latest_telemetry["cycles_completed"] + 1,
                        "anomalies_detected": anomalies
                    }

            except Exception as e:
                logger.error(f"Error en ciclo de BackgroundHardwareOrchestrator: {e}", exc_info=True)

            time.sleep(self.cycle_interval_seconds)

    def get_all_layers_telemetry(self) -> Dict[str, Any]:
        """Retorna la fotografía consolidada de todas las capas de hardware."""
        with self._telemetry_lock:
            return dict(self._latest_telemetry)


def get_background_hardware_orchestrator() -> BackgroundHardwareOrchestrator:
    return BackgroundHardwareOrchestrator.get_instance()
