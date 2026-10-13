"""
core/hotspot_watchdog.py - Centinela y Guardián Continuo de la Red Wi-Fi Soberana
=================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Supervisa 24/7 que el punto de acceso inalámbrico 'TimeMachine' permanezca activo,
inmune a caídas, suspensiones del sistema o desconexiones accidentales.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from typing import Optional

from core.network_controller import get_network_controller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [HotspotWatchdog] %(message)s"
)
logger = logging.getLogger("godworks.hotspot_watchdog")


class HotspotWatchdog:
    """Demonio centinela que supervisa y mantiene la red Wi-Fi TimeMachine activa 24/7."""

    def __init__(
        self,
        ssid: str = "TimeMachine",
        password: str = "987654321",
        ifname: str = "wlp3s0",
        check_interval: float = 8.0
    ):
        self.ssid = ssid
        self.password = password
        self.ifname = ifname
        self.interval = check_interval
        self.running = False
        self.net_ctrl = get_network_controller()

    def _enable_ip_forwarding(self):
        """Asegura que el reenvío de paquetes IPv4 esté habilitado para NAT."""
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "r") as f:
                val = f.read().strip()
            if val != "1":
                # Intentar habilitar con sudo si está configurado
                subprocess.run(
                    ["sudo", "-S", "sysctl", "-w", "net.ipv4.ip_forward=1"],
                    input="0\n",
                    text=True,
                    capture_output=True,
                    timeout=5
                )
                logger.info("IP forwarding activado (net.ipv4.ip_forward=1).")
        except Exception as e:
            logger.warning(f"No se pudo verificar IP forwarding: {e}")

    def run(self):
        """Bucle principal de supervisión y auto-curación."""
        self.running = True
        logger.info(f"Iniciando Centinela de Red Wi-Fi Soberana para SSID: '{self.ssid}' en '{self.ifname}'...")

        self._enable_ip_forwarding()

        # Primer arranque forzado
        try:
            self.net_ctrl.ensure_hotspot_active(
                ssid=self.ssid,
                password=self.password,
                ifname=self.ifname
            )
        except Exception as e:
            logger.error(f"Error en arranque inicial de hotspot: {e}")

        consecutive_errors = 0

        while self.running:
            try:
                st = self.net_ctrl.get_hotspot_status(
                    con_name=f"{self.ssid}-Hotspot",
                    ifname=self.ifname
                )

                if not st.get("active"):
                    consecutive_errors += 1
                    logger.warning(
                        f"🚨 Red Wi-Fi '{self.ssid}' caída o desconectada (incidente #{consecutive_errors}). "
                        f"Reactivando punto de acceso..."
                    )
                    res = self.net_ctrl.ensure_hotspot_active(
                        ssid=self.ssid,
                        password=self.password,
                        ifname=self.ifname
                    )
                    if res.get("ok"):
                        logger.info(f"✅ Red Wi-Fi '{self.ssid}' restablecida con éxito!")
                        consecutive_errors = 0
                else:
                    consecutive_errors = 0
                    client_cnt = st.get("client_count", 0)
                    if client_cnt > 0:
                        logger.debug(f"Punto de acceso '{self.ssid}' activo con {client_cnt} cliente(s) conectado(s).")

            except Exception as e:
                logger.error(f"Error en ciclo de vigilancia: {e}")

            time.sleep(self.interval)

    def stop(self):
        """Detiene el bucle de vigilancia."""
        self.running = False
        logger.info("Centinela de Red Wi-Fi detenido.")


def main():
    watchdog = HotspotWatchdog()

    def handle_sig(sig, frame):
        logger.info("Señal de terminación recibida. Deteniendo...")
        watchdog.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    watchdog.run()


if __name__ == "__main__":
    main()
