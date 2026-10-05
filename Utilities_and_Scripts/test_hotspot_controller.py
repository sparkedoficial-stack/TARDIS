import unittest
from unittest.mock import MagicMock, patch

from core.network_controller import get_network_controller
from core.hardware_controller import get_hardware_controller
from omni_temporal_control import process_hardware_chat_intent


class TestHotspotController(unittest.TestCase):
    def setUp(self):
        self.net_ctrl = get_network_controller()
        self.hw_ctrl = get_hardware_controller()

    def test_hotspot_status_structure(self):
        """Verifica la estructura y campos del estado de la red Wi-Fi Soberana."""
        st = self.net_ctrl.get_hotspot_status()
        self.assertTrue(st.get("ok"))
        self.assertEqual(st.get("ssid"), "TimeMachine")
        self.assertEqual(st.get("raw_password"), "987654321")
        self.assertIn("10.42.0", st.get("gateway_ip", ""))
        self.assertEqual(st.get("ifname"), "wlp3s0")
        self.assertIn("hud_url", st)
        self.assertIsInstance(st.get("clients"), list)
        self.assertIsInstance(st.get("client_count"), int)

    def test_hardware_controller_dispatch_hotspot(self):
        """Verifica que HardwareController despacha las acciones de hotspot correctamente."""
        res = self.hw_ctrl.dispatch_action("hotspot_status")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("ssid"), "TimeMachine")

        clients_res = self.hw_ctrl.dispatch_action("hotspot_clients")
        self.assertTrue(clients_res.get("ok"))
        self.assertIn("clients", clients_res)

    def test_slash_command_hotspot(self):
        """Verifica que el comando /hotspot genera la ficha técnica completa."""
        res = process_hardware_chat_intent("/hotspot")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("executed"))
        self.assertEqual(res.get("action"), "hotspot_status")
        fb = res.get("system_feedback", "")
        self.assertIn("TimeMachine", fb)
        self.assertIn("987654321", fb)
        self.assertIn("REDACTED_IP", fb)

    def test_natural_language_hotspot_intents(self):
        """Verifica que consultas en lenguaje natural detecten el estado del punto de acceso."""
        queries = [
            "estado de la red wifi",
            "dame la clave wifi",
            "contraseña del wifi",
            "quién está conectado a la red wifi"
        ]
        for q in queries:
            res = process_hardware_chat_intent(q)
            self.assertIsNotNone(res, f"Fallo al reconocer: '{q}'")
            self.assertTrue(res.get("executed"))
            self.assertEqual(res.get("action"), "hotspot_status")
            self.assertIn("TimeMachine", res.get("system_feedback", ""))

    def test_telegram_bridge_hotspot_command(self):
        """Verifica que TelegramBridge responda al comando /hotspot con la tarjeta de red."""
        from core.telegram_bridge import TelegramBridge
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "tg_test_cfg.json"
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = 123456
            bridge.authorized_chat_ids.add(chat_id)

            with patch.object(bridge, "send_message") as mock_msg:
                bridge._handle_incoming_text(chat_id, "/hotspot", "SovereignUser")
                mock_msg.assert_called_once()
                args, _ = mock_msg.call_args
                msg_text = args[0]
                self.assertIn("RED WI-FI SOBERANA", msg_text)
                self.assertIn("TimeMachine", msg_text)
                self.assertIn("987654321", msg_text)


if __name__ == "__main__":
    unittest.main()
