"""
Módulo de Gestión de Dispositivos Apple por Cable USB / Lightning / Tipo-C
Interactúa con usbmuxd, idevicepair, ideviceinfo e ifuse para almacenamiento.
"""
from __future__ import annotations

import os
import plistlib
import socket
import struct
import subprocess
from pathlib import Path

USBMUX_SOCKET_PATH = "/var/run/usbmuxd"
MOUNT_DIR = Path.home() / "Dispositivos" / "Apple_iOS"


class AppleUsbManager:
    """Control de dispositivos Apple físicos conectados por USB."""

    def __init__(self, socket_path: str = USBMUX_SOCKET_PATH):
        self.socket_path = socket_path
        MOUNT_DIR.mkdir(parents=True, exist_ok=True)

    def query_usb_devices(self) -> list[dict]:
        """Consulta el socket usbmuxd para listar iPhones/iPads conectados por cable."""
        devices = []
        if not os.path.exists(self.socket_path):
            return devices

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.5)
            s.connect(self.socket_path)

            payload = plistlib.dumps({
                "MessageType": "ListDevices",
                "ClientVersionString": "AirPlay-Monitor-Manager",
                "ProgName": "airplay-monitor"
            }, fmt=plistlib.FMT_XML)

            hdr = struct.pack("<IIII", len(payload) + 16, 1, 8, 1)
            s.sendall(hdr + payload)

            resp_hdr = s.recv(16)
            if len(resp_hdr) == 16:
                resp_len, ver, req_type, tag = struct.unpack("<IIII", resp_hdr)
                body = s.recv(resp_len - 16)
                data = plistlib.loads(body)
                device_list = data.get("DeviceList", [])
                for d in device_list:
                    props = d.get("Properties", {})
                    devices.append({
                        "connection_type": "USB Cable",
                        "device_id": props.get("DeviceID"),
                        "udid": props.get("SerialNumber"),
                        "product_type": props.get("ProductType", "Apple Device"),
                        "connection_speed": props.get("ConnectionSpeed")
                    })
            s.close()
        except Exception:
            pass
        return devices

    def get_paired_udids(self) -> list[str]:
        try:
            res = subprocess.run(["idevicepair", "list"], capture_output=True, text=True, timeout=2.0)
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def pair_device(self) -> tuple[bool, str]:
        """Solicita el emparejamiento y verificación de confianza."""
        try:
            res = subprocess.run(["idevicepair", "pair"], capture_output=True, text=True, timeout=10.0)
            out = res.stdout.strip()
            err = res.stderr.strip()
            if res.returncode == 0 and "SUCCESS" in (out + err).upper():
                return True, "¡Emparejamiento exitoso! Dispositivo de confianza registrado."
            if "trust" in (out + err).lower():
                return False, "Por favor desbloquea el iPhone/iPad y pulsa 'Confiar en este ordenador' en su pantalla."
            return False, out or err or "No se pudo completar el emparejamiento."
        except Exception as e:
            return False, str(e)

    def get_device_info(self) -> dict:
        """Extrae telemetría y especificaciones mediante ideviceinfo."""
        info = {
            "name": "Dispositivo Desconocido",
            "model": "Apple Device",
            "ios_version": "-",
            "battery_percent": None,
            "battery_charging": None,
            "serial": "-",
            "udid": "-",
            "wifi_mac": "-",
            "connected": False
        }
        try:
            res = subprocess.run(["ideviceinfo"], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0 and res.stdout.strip():
                info["connected"] = True
                for line in res.stdout.splitlines():
                    if line.startswith("DeviceName:"):
                        info["name"] = line.split(":", 1)[1].strip()
                    elif line.startswith("ProductType:"):
                        info["model"] = line.split(":", 1)[1].strip()
                    elif line.startswith("ProductVersion:"):
                        info["ios_version"] = f"iOS {line.split(':', 1)[1].strip()}"
                    elif line.startswith("BatteryCurrentCapacity:"):
                        val = line.split(":", 1)[1].strip()
                        if val.isdigit():
                            info["battery_percent"] = int(val)
                    elif line.startswith("BatteryIsCharging:"):
                        info["battery_charging"] = line.split(":", 1)[1].strip().lower() == "true"
                    elif line.startswith("SerialNumber:"):
                        info["serial"] = line.split(":", 1)[1].strip()
                    elif line.startswith("UniqueDeviceID:"):
                        info["udid"] = line.split(":", 1)[1].strip()
                    elif line.startswith("WiFiAddress:"):
                        info["wifi_mac"] = line.split(":", 1)[1].strip()
        except Exception:
            pass
        return info

    def is_mounted(self) -> bool:
        return os.path.ismount(MOUNT_DIR)

    def mount_storage(self) -> tuple[bool, str]:
        if self.is_mounted():
            return True, f"El almacenamiento ya está montado en {MOUNT_DIR}."
        try:
            res = subprocess.run(["ifuse", str(MOUNT_DIR)], capture_output=True, text=True, timeout=5.0)
            if res.returncode == 0:
                # Abrir explorador de archivos nautilus
                subprocess.Popen(["xdg-open", str(MOUNT_DIR)])
                return True, f"Almacenamiento iOS montado con éxito en: {MOUNT_DIR}"
            return False, res.stderr.strip() or "Error al montar mediante ifuse."
        except Exception as e:
            return False, str(e)

    def unmount_storage(self) -> tuple[bool, str]:
        if not self.is_mounted():
            return True, "No había ninguna unidad montada."
        try:
            res = subprocess.run(["fusermount", "-u", str(MOUNT_DIR)], capture_output=True, text=True, timeout=4.0)
            if res.returncode == 0:
                return True, "Almacenamiento desmontado de forma segura."
            return False, res.stderr.strip() or "Error al desmontar."
        except Exception as e:
            return False, str(e)
