"""
tests/test_tardis_pocket_zero_url.py
==============================================================================
Verifica la arquitectura Zero-URL y autonomía nativa de TARDIS-POCKET:
  1. TardisPocketBridge y gestión de telemetría/comandos.
  2. Resolución dinámica de rutas (Hotspot REDACTED_IP, LAN, Túnel).
  3. Existencia y consistencia de los componentes autónomos en mobile_terminal.
  4. Integridad del paquete flashable de la Custom ROM Zero-URL.
==============================================================================
"""

import json
import os
import unittest
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MOBILE_DIR = BASE_DIR / "mobile_terminal"
ROM_DIST = BASE_DIR / "tardis_custom_rom" / "dist" / "TARDIS_SOVEREIGN_OS_MOTO_X_PLAY.zip"


class TestTardisPocketZeroUrl(unittest.TestCase):

    def test_bridge_endpoints_and_telemetry(self):
        from core.tardis_pocket_tunnel_bridge import TardisPocketBridge, AUTHORIZED_SERIAL
        bridge = TardisPocketBridge.get_instance()

        endpoints = bridge.get_connection_endpoints()
        self.assertIn("routes", endpoints)
        self.assertEqual(endpoints["routes"]["priority_1_hotspot"], "http://REDACTED_IP:8757")
        self.assertEqual(endpoints["routes"]["local_daemon"], "http://REDACTED_IP:8080")

        # Test telemetry recording
        payload = {
            "serial": AUTHORIZED_SERIAL,
            "battery": {"level": 88, "charging": True},
            "gps": {"lat": 20.62, "lon": -87.07, "alt": 12},
            "route_mode": "DIRECT_HOTSPOT"
        }
        ok = bridge.record_telemetry(payload, client_ip="REDACTED_IP")
        self.assertTrue(ok)
        status = bridge.get_status()
        self.assertEqual(status["client_ip"], "REDACTED_IP")
        self.assertEqual(status["route_mode"], "DIRECT_HOTSPOT")

        # Test command queue
        cmd_id = bridge.queue_command("tts", {"text": "Prueba de voz autónoma"})
        self.assertTrue(cmd_id.startswith("cmd_"))
        pending = bridge.pop_commands(AUTHORIZED_SERIAL)
        self.assertTrue(any(c["id"] == cmd_id for c in pending))

    def test_mobile_terminal_files_exist_and_executable(self):
        daemon_py = MOBILE_DIR / "tardis_pocket_daemon.py"
        daemon_sh = MOBILE_DIR / "tardis_pocket_daemon.sh"
        start_sh = MOBILE_DIR / "start_tardis_terminal.sh"
        setup_sh = MOBILE_DIR / "setup_termux_boot.sh"
        html_ui = MOBILE_DIR / "tardis_pocket.html"
        sw_js = MOBILE_DIR / "sw.js"
        manifest_json = MOBILE_DIR / "manifest.json"

        for f in [daemon_py, daemon_sh, start_sh, setup_sh, html_ui, sw_js, manifest_json]:
            self.assertTrue(f.exists(), f"Falta archivo requerido: {f.name}")

        self.assertTrue(os.access(daemon_py, os.X_OK))
        self.assertTrue(os.access(daemon_sh, os.X_OK))
        self.assertTrue(os.access(start_sh, os.X_OK))
        self.assertTrue(os.access(setup_sh, os.X_OK))

    def test_custom_rom_zip_integrity(self):
        self.assertTrue(ROM_DIST.exists(), "El ZIP de la Custom ROM no existe.")
        with zipfile.ZipFile(ROM_DIST, "r") as z:
            names = z.namelist()
            self.assertIn("META-INF/com/google/android/update-binary", names)
            self.assertIn("TardisLauncher.apk", names)
            self.assertIn("tardis_pocket_daemon.py", names)
            self.assertIn("tardis_pocket.html", names)
            self.assertIn("sw.js", names)
            self.assertIn("start_tardis_terminal.sh", names)


if __name__ == "__main__":
    unittest.main()
