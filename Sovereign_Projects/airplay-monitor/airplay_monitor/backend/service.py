"""
Módulo de Gestión del Servicio AirPlay (UxPlay / systemd)
Controla el ciclo de vida del servidor AirPlay en el espacio de usuario.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

SERVICE_NAME = "uxplay-airplay.service"
USER_SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"
SERVICE_FILE = USER_SYSTEMD_DIR / SERVICE_NAME


class AirPlayServiceManager:
    """Administra el demonio systemd de UxPlay."""

    def __init__(self):
        self.ensure_service_installed()

    def ensure_service_installed(self):
        """Asegura que el archivo de servicio systemd existe y está actualizado."""
        USER_SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
        uxplay_bin = shutil.which("uxplay") or "/usr/bin/uxplay"
        
        service_content = f"""[Unit]
Description=UxPlay - Servidor AirPlay Soberano para Duplicar Pantalla de iOS
After=network.target network-online.target avahi-daemon.service
Wants=network.target network-online.target

[Service]
Type=simple
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-0
Environment=XDG_RUNTIME_DIR=/run/user/{os.getuid()}
PassEnvironment=DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR XAUTHORITY
ExecStart={uxplay_bin}
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
        # Comprobar si necesita actualizarse
        needs_write = True
        if SERVICE_FILE.exists():
            try:
                curr = SERVICE_FILE.read_text(encoding="utf-8")
                if "ExecStart=" in curr and "PassEnvironment=" in curr:
                    needs_write = False
            except Exception:
                pass

        if needs_write:
            SERVICE_FILE.write_text(service_content, encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)

    def is_active(self) -> bool:
        """Devuelve True si el servicio AirPlay está corriendo."""
        res = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True, text=True
        )
        return res.stdout.strip() == "active"

    def get_status_details(self) -> dict:
        """Obtiene información detallada del estado del servicio."""
        active = self.is_active()
        enabled = self.is_autostart_enabled()
        pid = None
        memory = None
        cpu = None

        if active:
            res = subprocess.run(
                ["systemctl", "--user", "show", SERVICE_NAME, "--property=MainPID,MemoryCurrent,CPUUsageNSec"],
                capture_output=True, text=True
            )
            for line in res.stdout.splitlines():
                if line.startswith("MainPID="):
                    pid = line.split("=", 1)[1]
                elif line.startswith("MemoryCurrent="):
                    val = line.split("=", 1)[1]
                    if val and val.isdigit() and val != "[not set]":
                        mb = int(val) / (1024 * 1024)
                        memory = f"{mb:.1f} MB"
                elif line.startswith("CPUUsageNSec="):
                    val = line.split("=", 1)[1]
                    if val and val.isdigit():
                        sec = int(val) / 1_000_000_000
                        cpu = f"{sec:.2f}s"

        return {
            "active": active,
            "enabled": enabled,
            "pid": pid if pid and pid != "0" else None,
            "memory": memory or "0 MB",
            "cpu": cpu or "0s",
            "network_ips": self.get_network_ips(),
        }

    def start(self) -> tuple[bool, str]:
        res = subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True, text=True)
        if res.returncode == 0:
            return True, "Servidor AirPlay iniciado correctamente."
        return False, res.stderr.strip() or "Error al iniciar el servicio."

    def stop(self) -> tuple[bool, str]:
        res = subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], capture_output=True, text=True)
        if res.returncode == 0:
            return True, "Servidor AirPlay detenido."
        return False, res.stderr.strip() or "Error al detener el servicio."

    def restart(self) -> tuple[bool, str]:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        res = subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], capture_output=True, text=True)
        if res.returncode == 0:
            return True, "Servidor AirPlay reiniciado con éxito."
        return False, res.stderr.strip() or "Error al reiniciar el servicio."

    def is_autostart_enabled(self) -> bool:
        res = subprocess.run(["systemctl", "--user", "is-enabled", SERVICE_NAME], capture_output=True, text=True)
        return res.stdout.strip() == "enabled"

    def set_autostart(self, enable: bool) -> bool:
        cmd = "enable" if enable else "disable"
        res = subprocess.run(["systemctl", "--user", cmd, SERVICE_NAME], capture_output=True, text=True)
        return res.returncode == 0

    @staticmethod
    def get_network_ips() -> list[dict]:
        """Descubre las IPs y adaptadores de red activos en la máquina."""
        ips = []
        try:
            p = subprocess.run(["ip", "-j", "addr", "show"], capture_output=True, text=True, timeout=2.0)
            data = json.loads(p.stdout)
            for iface in data:
                name = iface.get("ifname", "")
                if name == "lo" or "docker" in name or "tailscale" in name:
                    continue
                for addr_info in iface.get("addr_info", []):
                    if addr_info.get("family") == "inet":
                        ip = addr_info.get("local")
                        iface_type = "Wi-Fi Hotspot" if name.startswith("wl") else ("Ethernet LAN" if name.startswith("en") else "Red")
                        ips.append({
                            "interface": name,
                            "ip": ip,
                            "type": iface_type
                        })
        except Exception:
            pass
        return ips
