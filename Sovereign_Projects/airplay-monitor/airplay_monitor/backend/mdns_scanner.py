"""
Módulo de Escáner mDNS para Detección de Dispositivos Apple y AirPlay en Red Local
Utiliza avahi-browse y sondeos socket para telemetría de red.
"""
from __future__ import annotations

import socket
import subprocess
import threading
from typing import Callable

LOCKDOWN_PORT = 62078


class AppleNetworkScanner:
    """Escanea y reporta dispositivos Apple y servicios AirPlay en la LAN / Wi-Fi."""

    @staticmethod
    def scan_all_services(callback: Callable[[list[dict]], None] | None = None) -> list[dict]:
        """Ejecuta un escaneo completo de los servicios _airplay, _raop y _companion-link."""
        devices = []
        services = ["_airplay._tcp", "_raop._tcp", "_companion-link._tcp"]
        seen_keys = set()

        for srv in services:
            try:
                p = subprocess.run(
                    ["avahi-browse", "-r", "-t", "-p", srv],
                    capture_output=True, text=True, timeout=3.5
                )
                for line in p.stdout.splitlines():
                    # Formato parseable: =;interface;protocol;name;type;domain;hostname;ip;port;txt
                    parts = line.split(";")
                    if len(parts) >= 9 and parts[0] == "=":
                        iface = parts[1]
                        proto = parts[2]
                        name = parts[3]
                        stype = parts[4]
                        domain = parts[5]
                        hostname = parts[6]
                        ip = parts[7]
                        port = parts[8]
                        txt = parts[9] if len(parts) > 9 else ""

                        # Identificador único
                        key = (name, ip, port)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                        # Modelo / metadata desde TXT
                        model = "Apple / AirPlay Device"
                        if "model=" in txt:
                            for item in txt.split('"'):
                                if item.startswith("model="):
                                    model = item.split("=")[1]
                        elif "am=" in txt:
                            for item in txt.split('"'):
                                if item.startswith("am="):
                                    model = item.split("=")[1]

                        # Tipo amigable
                        service_friendly = "AirPlay Receptor"
                        if "_companion-link" in stype:
                            service_friendly = "Apple Companion-Link"
                        elif "_raop" in stype:
                            service_friendly = "AirTunes (Audio)"
                        elif "_airplay" in stype:
                            service_friendly = "AirPlay (Video/Mirroring)"

                        # Lockdown port check rápido
                        lockdown_open = False
                        if proto == "IPv4" and ip not in ("127.0.0.1", "::1"):
                            try:
                                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                s.settimeout(0.25)
                                lockdown_open = (s.connect_ex((ip, LOCKDOWN_PORT)) == 0)
                                s.close()
                            except Exception:
                                pass

                        devices.append({
                            "name": name.replace("\\064", "@"),
                            "hostname": hostname,
                            "ip": ip,
                            "port": port,
                            "interface": iface,
                            "protocol": proto,
                            "service_type": service_friendly,
                            "model": model,
                            "lockdown_port": "ABIERTO" if lockdown_open else "CERRADO",
                            "is_local_host": ip in ("127.0.0.1", "::1") or hostname.startswith("TimeMachine")
                        })
            except Exception:
                pass

        if callback:
            callback(devices)
        return devices

    @classmethod
    def scan_async(cls, callback: Callable[[list[dict]], None]):
        """Ejecuta el escaneo en segundo plano sin congelar la interfaz."""
        th = threading.Thread(target=cls.scan_all_services, args=(callback,), daemon=True)
        th.start()
