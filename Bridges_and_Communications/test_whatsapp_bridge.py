"""
tests/test_whatsapp_bridge.py - Pruebas unitarias completas para el Puente Soberano de WhatsApp
"""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.whatsapp_bridge import WhatsAppBridge, _digits


class TestWhatsAppBridge(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp_dir.name) / "test_whatsapp_config.json"
        self.bridge = WhatsAppBridge(config_path=self.config_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_digits_helper(self):
        """Verifica la normalización estricta de números telefónicos."""
        self.assertEqual(_digits("+52 (55) 1234-5678"), "525512345678")
        self.assertEqual(_digits("54-9-999-123456"), "549999123456")
        self.assertEqual(_digits(""), "")
        self.assertEqual(_digits(None), "")

    def test_initial_status_and_defaults(self):
        """Verifica el estado inicial y los parámetros por defecto."""
        status = self.bridge.get_status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["configured"])
        self.assertEqual(status["verify_token"], "DiosDelTiempo01")
        self.assertIn("0", self.bridge.pairing_passwords)
        self.assertIn("DiosDelTiempo01", self.bridge.pairing_passwords)

    def test_webhook_challenge_verification(self):
        """Verifica el handshake de verificación de Meta (GET /whatsapp/webhook)."""
        challenge = "random_meta_challenge_str_123"
        
        # Con verify_token correcto
        res = self.bridge.verify_challenge("subscribe", "DiosDelTiempo01", challenge)
        self.assertEqual(res, challenge)
        self.assertTrue(self.bridge.verify_webhook_token("DiosDelTiempo01"))

        # Con verify_token incorrecto o modo inválido
        res_bad = self.bridge.verify_challenge("subscribe", "wrong_token", challenge)
        self.assertIsNone(res_bad)
        self.assertFalse(self.bridge.verify_webhook_token("wrong_token"))

        res_bad_mode = self.bridge.verify_challenge("not_subscribe", "DiosDelTiempo01", challenge)
        self.assertIsNone(res_bad_mode)

    def test_signature_verification(self):
        """Verifica la validación criptográfica de firma HMAC-SHA256."""
        self.bridge.config["app_secret"] = "mi_secreto_super_seguro_meta"
        body = b'{"object":"whatsapp_business_account","entry":[]}'

        import hashlib, hmac
        expected_sig = "sha256=" + hmac.new(b"mi_secreto_super_seguro_meta", body, hashlib.sha256).hexdigest()

        # Firma correcta
        self.assertTrue(self.bridge.verify_signature(body, expected_sig))

        # Firma alterada o manipulada
        self.assertFalse(self.bridge.verify_signature(body, "sha256=invalidhash12345"))
        self.assertFalse(self.bridge.verify_signature(body, ""))

    def test_master_key_pairing(self):
        """Verifica que enviar la contraseña maestra '0' autoriza de inmediato el número de WhatsApp."""
        sender_phone = "+52 155 9876-5432"
        clean_num = "5215598765432"
        self.assertFalse(self.bridge.is_number_authorized(clean_num))

        with patch.object(self.bridge, "send_message") as mock_send:
            # Enviar clave maestra '0'
            res = self.bridge._handle_incoming_text(clean_num, "0", "TestUser")
            
            self.assertTrue(res.get("ok"))
            self.assertTrue(self.bridge.is_number_authorized(clean_num))
            mock_send.assert_called()
            sent_text = mock_send.call_args.args[1]
            self.assertIn("ACCESO SOBERANO CONCEDIDO", sent_text)

    def test_unauthorized_number_blocked(self):
        """Verifica que mensajes sin clave maestra son rechazados si el número no está autorizado."""
        sender = "1234567890"
        with patch.object(self.bridge, "send_message") as mock_send:
            res = self.bridge._handle_incoming_text(sender, "hola sistema", "Intruder")
            self.assertFalse(res.get("ok"))
            self.assertFalse(self.bridge.is_number_authorized(sender))
            sent_text = mock_send.call_args.args[1]
            self.assertIn("AUTENTICACIÓN REQUERIDA", sent_text)

    def test_command_start_and_help(self):
        """Verifica que los comandos /start y /help devuelven el menú operativo soberano."""
        sender = "5215500001111"
        self.bridge.authorized_numbers.add(sender)

        with patch.object(self.bridge, "send_message") as mock_send:
            res = self.bridge._handle_incoming_text(sender, "/start", "Owner")
            self.assertTrue(res.get("ok"))
            sent_text = mock_send.call_args.args[1]
            self.assertIn("GODWORKS SYSTEM v26.4", sent_text)
            self.assertIn("/sh", sent_text)
            self.assertIn("/status", sent_text)

    def test_command_sh_execution(self):
        """Verifica que /sh ejecuta comandos de shell en la terminal."""
        sender = "5215500002222"
        self.bridge.authorized_numbers.add(sender)

        with patch.object(self.bridge, "send_message") as mock_send:
            res = self.bridge._handle_incoming_text(sender, "/sh echo 'WHATSAPP_WIRELESS_OK'", "Owner")
            self.assertTrue(res.get("ok"))
            sent_text = mock_send.call_args.args[1]
            self.assertIn("WHATSAPP_WIRELESS_OK", sent_text)

    def test_send_message_post_payload(self):
        """Verifica el envío de mensajes a la Graph API de Meta."""
        self.bridge.config["access_token"] = "EAAG_TEST_ACCESS_TOKEN_123"
        self.bridge.config["phone_number_id"] = "109876543210"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.content = b'{"messages":[{"id":"wamid.HBgL..."}]}'
            mock_post.return_value.json.return_value = {"messages": [{"id": "wamid.HBgL..."}]}

            res = self.bridge.send_message("5215512345678", "Notificación soberana de prueba")
            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], 200)

            mock_post.assert_called_once()
            called_url = mock_post.call_args.args[0]
            called_json = mock_post.call_args.kwargs["json"]
            called_headers = mock_post.call_args.kwargs["headers"]

            self.assertIn("/v21.0/109876543210/messages", called_url)
            self.assertEqual(called_json["to"], "5215512345678")
            self.assertEqual(called_json["text"]["body"], "Notificación soberana de prueba")
            self.assertEqual(called_headers["Authorization"], "Bearer EAAG_TEST_ACCESS_TOKEN_123")

    def test_update_config_persists(self):
        """Verifica la persistencia en disco de la configuración actualizada."""
        res = self.bridge.update_config({
            "phone_number_id": "1234509876",
            "access_token": "EAAG_SAVED_TOKEN",
            "allowed_numbers": "5215511112222, +52 155 3333 4444"
        })
        self.assertTrue(res["configured"])
        self.assertTrue(self.config_path.exists())

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["phone_number_id"], "1234509876")
        self.assertEqual(saved["access_token"], "EAAG_SAVED_TOKEN")
        self.assertIn("5215511112222", saved["allowed_numbers"])
        self.assertIn("5215533334444", saved["allowed_numbers"])


if __name__ == "__main__":
    unittest.main()
