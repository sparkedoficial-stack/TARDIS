import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from omni_temporal_control import BridgeSupervisor, generate_qr_svg


class TestPermanentQRBridge(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.status_file = self.tmp_path / "bridge_status.json"
        self.url_file = self.tmp_path / "CURRENT_TUNNEL_URL.txt"
        self.tunnel_config_file = self.tmp_path / "tunnel_config.json"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_permanent_portal_url_invariant_across_reboots(self):
        """Verifica que el QR generado es estrictamente invariable aunque la URL del túnel cambie."""
        perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"
        
        # Simulación de Reinicio 1: Túnel A
        tunnel_url_boot_1 = "https://random-alpha-123.trycloudflare.com/?key=DiosDelTiempo01"
        # Simulación de Reinicio 2: Túnel B (completamente diferente)
        tunnel_url_boot_2 = "https://random-beta-999.trycloudflare.com/?key=DiosDelTiempo01"

        # Generar QR para el portal permanente en ambos reinicios
        qr_svg_boot_1 = generate_qr_svg(perm_url)
        qr_svg_boot_2 = generate_qr_svg(perm_url)

        # El SVG del QR DEBE ser 100% IDÉNTICO
        self.assertEqual(qr_svg_boot_1, qr_svg_boot_2)

        # Si se generara directamente del túnel cambiante, los QR diferirían
        qr_svg_tunnel_1 = generate_qr_svg(tunnel_url_boot_1)
        qr_svg_tunnel_2 = generate_qr_svg(tunnel_url_boot_2)
        self.assertNotEqual(qr_svg_tunnel_1, qr_svg_tunnel_2)

    def test_bridge_supervisor_status_structure(self):
        """Verifica que BridgeSupervisor exporta permanent_url y qr_url consistentes."""
        with patch("omni_temporal_control.STATUS_FILE", self.status_file), \
             patch("omni_temporal_control.URL_FILE", self.url_file):
            supervisor = BridgeSupervisor(port=8757, token = "REDACTED")
            supervisor.permanent_portal_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"
            
            # Escribir estado simulado con túnel activo
            dyn_public = "https://alpha-bravo-charlie.trycloudflare.com"
            supervisor._write_status(dyn_public, True)

            self.assertTrue(self.status_file.exists())
            status = json.loads(self.status_file.read_text(encoding="utf-8"))

            self.assertTrue(status["online"])
            self.assertEqual(status["permanent_url"], "https://ntfy.sh/godworks_sovereign_timemachine_portal")
            self.assertEqual(status["qr_url"], "https://ntfy.sh/godworks_sovereign_timemachine_portal")
            self.assertIn("DiosDelTiempo01", status["auth_url"])

    def test_sync_permanent_portal_dispatches_http(self):
        """Verifica que al activarse el túnel, la URL se publica en el portal permanente ntfy."""
        supervisor = BridgeSupervisor(port=8757, token = "REDACTED")
        supervisor.permanent_portal_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"
        
        test_auth_url = "https://test-reboot-tunnel.trycloudflare.com/?key=DiosDelTiempo01"
        with patch("omni_temporal_control.requests.post") as mock_post:
            supervisor._sync_permanent_portal(test_auth_url)
            
            self.assertTrue(mock_post.called)
            # El primer llamado es la publicación al portal permanente ntfy
            ntfy_call = mock_post.call_args_list[0]
            called_url = ntfy_call[0][0]
            called_headers = ntfy_call[1]["headers"]
            
            self.assertEqual(called_url, "https://ntfy.sh/godworks_sovereign_timemachine_portal")
            self.assertEqual(called_headers["Click"], test_auth_url)
            self.assertIn(test_auth_url, called_headers["Actions"])


if __name__ == "__main__":
    unittest.main()
