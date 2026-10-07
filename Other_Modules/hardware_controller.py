"""
core/hardware_controller.py - Controlador Maestro de Hardware Soberano Unificado
================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Proporciona control integral sobre el hardware físico del equipo (ASUS TUF FA506IC / Linux):
  1. Audio & Multimedia: volumen exacto (0-100%), mute/unmute (PipeWire `wpctl` / ALSA `amixer`).
  2. Teclado ASUS TUF: niveles de iluminación 0 (apagado) a 3 (máximo) por DBus y sysfs.
  3. Radio Bluetooth: encendido, apagado, estado y escaneo de periféricos (`bluetoothctl`).
  4. Perfiles Energéticos & Térmicos: rendimiento/balanceado/ahorro (`powerprofilesctl`), batería y temperaturas.
  5. Redes & Wi-Fi: escaneo circundante, conexión, diagnóstico y failover (integrado con `NetworkController`).
  6. Pantalla & Sesión: bloqueo, desbloqueo, inhibición 24/7 y captura de pantalla.
  7. Despachador Universal: interfaz unificada `dispatch_action(action, params)` para el Chat Agéntico y API REST.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

from core.network_controller import get_network_controller, NetworkController
from core.network_shield import get_network_shield, NetworkShield
from core.os_controller import get_os_controller, OSController

logger = logging.getLogger("godworks.hardware")

ASUS_KBD_PATH = Path("/sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight/brightness")
ASUS_KBD_MAX_PATH = Path("/sys/devices/platform/asus-nb-wmi/leds/asus::kbd_backlight/max_brightness")


class HardwareController:
    """Controlador unificado de todo el hardware físico del dispositivo."""

    _instance: Optional["HardwareController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.os_ctrl: OSController = get_os_controller()
        self.net_ctrl: NetworkController = get_network_controller()
        self.shield: NetworkShield = get_network_shield()

    @classmethod
    def get_instance(cls) -> "HardwareController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # -------------------------------------------------------------------------
    # 1. AUDIO Y MULTIMEDIA (wpctl / amixer)
    # -------------------------------------------------------------------------

    def get_volume(self) -> Dict[str, Any]:
        """Obtiene el volumen actual y estado de silencio."""
        return self.os_ctrl.get_volume()

    def set_volume(self, percent: Union[int, float]) -> Dict[str, Any]:
        """Ajusta el volumen del sistema al porcentaje dado (0 a 100)."""
        return self.os_ctrl.set_volume(percent)

    def toggle_mute(self) -> Dict[str, Any]:
        """Alterna silencio (mute/unmute)."""
        return self.os_ctrl.toggle_mute()

    def set_mute(self, muted: bool) -> Dict[str, Any]:
        """Fuerza silencio o sonido."""
        vol_info = self.get_volume()
        if vol_info.get("muted") != muted:
            return self.toggle_mute()
        return vol_info

    # -------------------------------------------------------------------------
    # 2. TECLADO RETROILUMINADO ASUS TUF (DBus & sysfs)
    # -------------------------------------------------------------------------

    def get_keyboard_brightness(self) -> Dict[str, Any]:
        """Lee el nivel actual de retroiluminación del teclado (0 a 3)."""
        level = 0
        max_level = 3
        if ASUS_KBD_PATH.exists():
            try:
                level = int(ASUS_KBD_PATH.read_text().strip())
            except Exception:
                pass
        if ASUS_KBD_MAX_PATH.exists():
            try:
                max_level = int(ASUS_KBD_MAX_PATH.read_text().strip())
            except Exception:
                pass

        return {
            "ok": True,
            "level": level,
            "max_level": max_level,
            "percent": int(round((level / float(max_level or 3)) * 100)),
            "state_label": "APAGADO" if level == 0 else f"NIVEL {level}/{max_level}"
        }

    def set_keyboard_brightness(self, level: Union[int, float]) -> Dict[str, Any]:
        """
        Ajusta el nivel de brillo del teclado ASUS TUF.
        level: 0 (apagado), 1 (bajo), 2 (medio), 3 (máximo).
        """
        target = max(0, min(3, int(level)))
        curr = self.get_keyboard_brightness().get("level", 0)

        # 1. Si son iguales, no hacer nada
        if curr == target:
            return self.get_keyboard_brightness()

        # 2. Intentar ajuste mediante DBus GNOME Power Keyboard
        # El método StepUp/StepDown cicla de forma confiable
        diff = target - curr
        method = "StepUp" if diff > 0 else "StepDown"
        for _ in range(abs(diff)):
            try:
                subprocess.run(
                    [
                        "gdbus", "call", "--session",
                        "--dest", "org.gnome.SettingsDaemon.Power",
                        "--object-path", "/org/gnome/SettingsDaemon/Power",
                        "--method", f"org.gnome.SettingsDaemon.Power.Keyboard.{method}"
                    ],
                    capture_output=True, timeout=2.0
                )
            except Exception:
                break

        # 3. Fallback directo sysfs si fuera escribible
        try:
            if ASUS_KBD_PATH.exists():
                ASUS_KBD_PATH.write_text(str(target))
        except Exception:
            pass

        return self.get_keyboard_brightness()

    def toggle_keyboard_brightness(self) -> Dict[str, Any]:
        """Alterna la luz del teclado entre apagado y el último nivel encendido."""
        curr = self.get_keyboard_brightness().get("level", 0)
        if curr == 0:
            return self.set_keyboard_brightness(3)
        else:
            return self.set_keyboard_brightness(0)

    # -------------------------------------------------------------------------
    # 3. RADIO BLUETOOTH (bluetoothctl)
    # -------------------------------------------------------------------------

    def get_bluetooth_status(self) -> Dict[str, Any]:
        """Obtiene el estado del controlador Bluetooth y dispositivos emparejados."""
        exe = shutil.which("bluetoothctl")
        if not exe:
            return {"ok": False, "error": "bluetoothctl no disponible"}

        try:
            res = subprocess.run([exe, "show"], capture_output=True, text=True, timeout=3.0)
            powered = "Powered: yes" in res.stdout
            discovering = "Discovering: yes" in res.stdout

            # Dispositivos emparejados
            dev_res = subprocess.run([exe, "devices"], capture_output=True, text=True, timeout=3.0)
            paired = []
            for line in dev_res.stdout.strip().split("\n"):
                if line.startswith("Device "):
                    parts = line.split(" ", 2)
                    paired.append({"mac": parts[1], "name": parts[2] if len(parts) > 2 else "Dispositivo Desconocido"})

            return {
                "ok": True,
                "powered": powered,
                "discovering": discovering,
                "paired_devices": paired,
                "paired_count": len(paired),
                "state_label": "ENCENDIDO" if powered else "APAGADO"
            }
        except Exception as e:
            return {"ok": False, "error": f"Error consultando Bluetooth: {e}"}

    def set_bluetooth_power(self, power_on: bool) -> Dict[str, Any]:
        """Enciende o apaga el controlador Bluetooth."""
        exe = shutil.which("bluetoothctl")
        if not exe:
            return {"ok": False, "error": "bluetoothctl no disponible"}

        action = "on" if power_on else "off"
        try:
            res = subprocess.run([exe, "power", action], capture_output=True, text=True, timeout=4.0)
            return {
                "ok": res.returncode == 0,
                "powered": power_on,
                "stdout": res.stdout.strip(),
                "status": self.get_bluetooth_status()
            }
        except Exception as e:
            return {"ok": False, "error": f"Fallo al cambiar estado Bluetooth: {e}"}

    def scan_bluetooth_devices(self, timeout_s: float = 4.0) -> Dict[str, Any]:
        """Escanea dispositivos Bluetooth activos en el entorno."""
        exe = shutil.which("bluetoothctl")
        if not exe:
            return {"ok": False, "error": "bluetoothctl no disponible"}

        try:
            # Iniciar escaneo con timeout
            subprocess.run([exe, "--timeout", str(int(timeout_s)), "scan", "on"], capture_output=True, text=True, timeout=timeout_s + 2.0)
            dev_res = subprocess.run([exe, "devices"], capture_output=True, text=True, timeout=3.0)
            devices = []
            for line in dev_res.stdout.strip().split("\n"):
                if line.startswith("Device "):
                    p = line.split(" ", 2)
                    devices.append({"mac": p[1], "name": p[2] if len(p) > 2 else "Desconocido"})

            return {"ok": True, "devices": devices, "count": len(devices), "scan_duration_s": timeout_s}
        except Exception as e:
            return {"ok": False, "error": f"Fallo escaneando Bluetooth: {e}"}

    # -------------------------------------------------------------------------
    # 4. PERFILES ENERGÉTICOS Y SENSORES TÉRMICOS (powerprofilesctl & psutil)
    # -------------------------------------------------------------------------

    def get_power_profile(self) -> Dict[str, Any]:
        """Obtiene el perfil energético activo de la CPU (performance, balanced, power-saver)."""
        exe = shutil.which("powerprofilesctl")
        if not exe:
            return {"ok": False, "profile": "unknown", "error": "powerprofilesctl no instalado"}

        try:
            res = subprocess.run([exe, "get"], capture_output=True, text=True, timeout=2.0)
            active = res.stdout.strip()
            list_res = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=2.0)
            profiles = []
            for line in list_res.stdout.split("\n"):
                m = re.match(r"^\s*\*?\s*([a-zA-Z0-9\-]+):", line)
                if m:
                    profiles.append(m.group(1))

            return {
                "ok": True,
                "active_profile": active,
                "available_profiles": profiles or ["performance", "balanced", "power-saver"]
            }
        except Exception as e:
            return {"ok": False, "error": f"Error leyendo perfil energético: {e}"}

    def set_power_profile(self, profile: str) -> Dict[str, Any]:
        """
        Ajusta el perfil energético del procesador.
        profile: 'performance', 'balanced', 'power-saver'
        """
        exe = shutil.which("powerprofilesctl")
        if not exe:
            return {"ok": False, "error": "powerprofilesctl no instalado"}

        profile = profile.lower().strip()
        aliases = {
            "rendimiento": "performance",
            "alto rendimiento": "performance",
            "turbo": "performance",
            "max": "performance",
            "balanceado": "balanced",
            "equilibrado": "balanced",
            "normal": "balanced",
            "ahorro": "power-saver",
            "bajo consumo": "power-saver",
            "eco": "power-saver",
            "quiet": "power-saver"
        }
        target = aliases.get(profile, profile)

        try:
            res = subprocess.run([exe, "set", target], capture_output=True, text=True, timeout=3.0)
            return {
                "ok": res.returncode == 0,
                "active_profile": target,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip()
            }
        except Exception as e:
            return {"ok": False, "error": f"Fallo al aplicar perfil '{target}': {e}"}

    def get_thermals_and_battery(self) -> Dict[str, Any]:
        """Obtiene la telemetría térmica y estado de batería."""
        out: Dict[str, Any] = {"ok": True, "battery": None, "temperatures": {}}
        if HAS_PSUTIL:
            try:
                bat = psutil.sensors_battery()
                if bat:
                    out["battery"] = {
                        "percent": bat.percent,
                        "power_plugged": bat.power_plugged,
                        "status": "Cargando/Conectado" if bat.power_plugged else "En batería"
                    }
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    out["temperatures"][name] = [
                        {"label": e.label or name, "current_c": e.current, "high_c": e.high, "critical_c": e.critical}
                        for e in entries
                    ]
            except Exception:
                pass
        return out

    # -------------------------------------------------------------------------
    # 5. DIAGNÓSTICO INTEGRAL DE TODO EL HARDWARE
    # -------------------------------------------------------------------------

    def get_full_diagnostic(self) -> Dict[str, Any]:
        """Recopila el diagnóstico simultáneo de todo el hardware físico."""
        vol = self.get_volume()
        kbd = self.get_keyboard_brightness()
        bt = self.get_bluetooth_status()
        pwr = self.get_power_profile()
        therm_bat = self.get_thermals_and_battery()
        net = self.net_ctrl.get_status()
        res_w, res_h = self.os_ctrl.get_screen_resolution()
        locked = self.os_ctrl.is_locked()

        return {
            "ok": True,
            "audio": vol,
            "keyboard": kbd,
            "bluetooth": bt,
            "power_profile": pwr,
            "battery": therm_bat.get("battery"),
            "temperatures": therm_bat.get("temperatures"),
            "network": net,
            "display": {
                "width": res_w,
                "height": res_h,
                "locked": locked
            },
            "timestamp": time.time()
        }

    # -------------------------------------------------------------------------
    # 6. DESPACHADOR UNIVERSAL DE ACCIONES DE HARDWARE (Chat / REST API)
    # -------------------------------------------------------------------------

    def dispatch_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Ejecuta cualquier acción de hardware por nombre clave.
        Diseñado para invocación directa desde el Chat Agéntico y la API HTTP.
        """
        action = (action or "").lower().strip()
        params = params or {}

        # --- A. Redes y Wi-Fi ---
        if action in ("wifi_scan", "scan_wifi", "scan_networks"):
            rescan = bool(params.get("rescan", True))
            return self.net_ctrl.scan_networks(rescan=rescan)

        elif action in ("wifi_connect", "connect_wifi"):
            ssid = params.get("ssid", "")
            pwd = params.get("password") or params.get("key")
            return self.net_ctrl.connect(ssid=ssid, password=pwd)

        elif action in ("wifi_status", "network_status"):
            return self.net_ctrl.get_status()

        elif action in ("wifi_recover", "auto_recover_internet", "recover_internet"):
            allow_open = bool(params.get("allow_open", True))
            return self.net_ctrl.auto_recover_internet(allow_open_networks=allow_open)

        elif action in ("hotspot_status", "wifi_ap_status", "ap_status"):
            return self.net_ctrl.get_hotspot_status()

        elif action in ("hotspot_start", "start_hotspot", "hotspot_ensure", "ensure_hotspot"):
            ssid = params.get("ssid", "TimeMachine")
            pwd = params.get("password", "987654321")
            return self.net_ctrl.ensure_hotspot_active(ssid=ssid, password=pwd)

        elif action in ("hotspot_stop", "stop_hotspot"):
            return self.net_ctrl.stop_hotspot()

        elif action in ("hotspot_restart", "restart_hotspot"):
            self.net_ctrl.stop_hotspot()
            time.sleep(1)
            return self.net_ctrl.ensure_hotspot_active()

        elif action in ("hotspot_clients", "ap_clients", "wifi_clients"):
            return {
                "ok": True,
                "clients": self.net_ctrl.get_connected_hotspot_clients()
            }

        # --- B. Audio y Volumen ---
        elif action in ("set_volume", "volume_set"):
            level = params.get("level", params.get("percent", params.get("value", 50)))
            return self.set_volume(level)

        elif action in ("get_volume", "volume_get"):
            return self.get_volume()

        elif action in ("mute", "mute_audio"):
            return self.set_mute(True)

        elif action in ("unmute", "unmute_audio"):
            return self.set_mute(False)

        elif action in ("toggle_mute", "mute_toggle"):
            return self.toggle_mute()

        # --- C. Teclado ASUS TUF ---
        elif action in ("set_keyboard", "set_keyboard_brightness", "keyboard_brightness"):
            level = params.get("level", params.get("value", 3))
            return self.set_keyboard_brightness(level)

        elif action in ("get_keyboard", "get_keyboard_brightness"):
            return self.get_keyboard_brightness()

        elif action in ("toggle_keyboard", "toggle_keyboard_brightness"):
            return self.toggle_keyboard_brightness()

        # --- D. Bluetooth ---
        elif action in ("set_bluetooth", "bluetooth_power"):
            power = bool(params.get("power", params.get("enabled", True)))
            return self.set_bluetooth_power(power)

        elif action in ("get_bluetooth", "bluetooth_status"):
            return self.get_bluetooth_status()

        elif action in ("scan_bluetooth", "bluetooth_scan"):
            dur = float(params.get("duration", 4.0))
            return self.scan_bluetooth_devices(timeout_s=dur)

        # --- E. Perfil Energético ---
        elif action in ("set_power_profile", "power_profile"):
            profile = params.get("profile", params.get("mode", "performance"))
            return self.set_power_profile(profile)

        elif action in ("get_power_profile", "power_profile_get"):
            return self.get_power_profile()

        # --- F. Pantalla y Bloqueo ---
        elif action in ("lock_screen", "screen_lock"):
            ok = self.os_ctrl.lock_screen()
            return {"ok": ok, "locked": self.os_ctrl.is_locked()}

        elif action in ("unlock_screen", "screen_unlock"):
            pwd = params.get("password", "0") if params else "0"
            ok = self.os_ctrl.unlock_screen(password=pwd)
            return {"ok": ok, "locked": self.os_ctrl.is_locked(), "unlocked": not self.os_ctrl.is_locked()}

        # --- G. Captura de Pantalla & Multimedia ---
        elif action in ("screenshot", "capture_screenshot", "take_screenshot"):
            try:
                raw_bytes, data_uri = self.os_ctrl.capture_screenshot()
                out_path = "/home/timemachine/Escritorio/screenshot_reciente.png"
                try:
                    with open(out_path, "wb") as f:
                        f.write(raw_bytes)
                except Exception:
                    pass
                return {"ok": True, "path": out_path, "bytes_len": len(raw_bytes), "data_uri_len": len(data_uri) if data_uri else 0}
            except Exception as e_sc:
                return {"ok": False, "error": str(e_sc)}

        # --- H. Reinicio y Energía del Sistema ---
        elif action in ("reboot", "system_reboot", "reboot_system"):
            delay = float(params.get("delay", 2.0))
            reason = str(params.get("reason", "Reinicio solicitado por chat soberano"))
            return self.os_ctrl.reboot_system(delay_seconds=delay, reason=reason)

        elif action in ("keep_awake", "inhibit_sleep", "awake"):
            enabled = bool(params.get("enabled", True))
            if enabled:
                ok = self.os_ctrl.ensure_sleep_inhibited()
                return {"ok": ok, "inhibited": True}
            else:
                self.os_ctrl.release_sleep_inhibit()
                return {"ok": True, "inhibited": False}

        # --- I. Aplicaciones y Teclas ---
        elif action in ("launch_app", "open_app", "start_app"):
            target = params.get("target", params.get("app", ""))
            return self.os_ctrl.launch_app(target)

        elif action in ("kill_app", "close_app", "stop_app"):
            target = params.get("target", params.get("app", ""))
            return self.os_ctrl.run_shell(f"pkill -f '{target}'")

        elif action in ("press_keys", "hotkey", "keyboard_action"):
            keys = params.get("keys", [])
            return self.os_ctrl.keyboard_action(action="hotkey", keys=keys)

        # --- J. Diagnóstico Consolidado ---
        elif action in ("status", "diagnostics", "full_diagnostic", "hardware_status"):
            return self.get_full_diagnostic()

        # --- K. Shell y Terminal Inalámbrico Auditado ---
        elif action in ("run_shell", "shell", "command", "bash", "terminal_exec", "sh"):
            cmd = params.get("command", params.get("cmd", ""))
            timeout = float(params.get("timeout", 25.0))
            return self.os_ctrl.execute_terminal_command(cmd, timeout=timeout)

        # --- L. Google Antigravity IDE (Control Inalámbrico) ---
        elif action in ("antigravity_status", "get_antigravity", "agy_status"):
            return self.os_ctrl.get_antigravity_status()

        elif action in ("antigravity_launch", "launch_antigravity", "open_antigravity", "agy_launch"):
            ws = params.get("workspace")
            return self.os_ctrl.launch_antigravity(workspace=ws)

        # --- M. Escudo de Red, DNS Sinkhole & Auditoría Soberana ---
        elif action in ("shield_status", "network_shield_status", "shield"):
            return self.shield.get_status()

        elif action in ("shield_audit", "network_audit", "audit_network", "auditar"):
            return self.shield.audit_network()

        elif action in ("shield_toggle_adblock", "adblock_toggle", "set_adblock"):
            enabled = bool(params.get("enabled", True)) if params else True
            return self.shield.toggle_adblock(enabled)

        elif action in ("shield_toggle_antispy", "antispy_toggle", "set_antispy"):
            enabled = bool(params.get("enabled", True)) if params else True
            return self.shield.toggle_antispy(enabled)

        # --- N. Tráfico en Vivo & Accesos a Dispositivos ---
        elif action in ("traffic_status", "traffic_flows", "trafico", "conexiones", "accesos", "device_access_audit"):
            from core.traffic_monitor import get_traffic_monitor
            return get_traffic_monitor().analyze_traffic_and_accesses()

        elif action in ("recurring_traffic", "recurrentes", "top_trafico", "frecuentes", "traffic_destinations"):
            from core.traffic_monitor import get_traffic_monitor
            return get_traffic_monitor().get_recurring_traffic_report()

        else:
            return {"ok": False, "error": f"Acción de hardware desconocida: '{action}'"}


# Instancia Global
def get_hardware_controller() -> HardwareController:
    return HardwareController.get_instance()
