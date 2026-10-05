import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.telegram_bridge import TelegramBridge


class TestTelegramBridge(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp_dir.name) / "test_telegram_config.json"
        self.bridge = TelegramBridge(config_path=self.config_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_initial_status_and_defaults(self):
        """Verifica el estado inicial y las llaves de seguridad."""
        status = self.bridge.get_status()
        self.assertFalse(status["polling_active"])
        self.assertFalse(status["bot_token_configured"])
        self.assertEqual(len(status["authorized_chat_ids"]), 0)
        self.assertIn("0", self.bridge.pairing_passwords)
        self.assertIn("DiosDelTiempo01", self.bridge.pairing_passwords)

    def test_master_key_pairing(self):
        """Verifica que enviar la contraseña maestra '0' autoriza de inmediato el chat de Telegram."""
        chat_id = 987654321
        self.assertFalse(self.bridge.is_chat_authorized(chat_id))

        with patch.object(self.bridge, "send_message") as mock_send:
            # Enviar clave maestra '0'
            self.bridge._handle_incoming_text(chat_id, "0", "TestUser")
            
            # El chat debe quedar autorizado permanentemente
            self.assertTrue(self.bridge.is_chat_authorized(chat_id))
            mock_send.assert_called()
            sent_text = mock_send.call_args.args[0]
            self.assertIn("ACCESO SOBERANO CONCEDIDO", sent_text)

    def test_unauthorized_chat_blocked(self):
        """Verifica que mensajes sin clave maestra son rechazados si el chat no está autorizado."""
        chat_id = 11223344
        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(chat_id, "hola sistema", "Intruder")
            self.assertFalse(self.bridge.is_chat_authorized(chat_id))
            sent_text = mock_send.call_args.args[0]
            self.assertIn("AUTENTICACIÓN REQUERIDA", sent_text)

    def test_command_start_and_help(self):
        """Verifica que los comandos /start y /help devuelven el menú operativo soberano."""
        chat_id = 55555
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(chat_id, "/start", "Owner")
            sent_text = mock_send.call_args.args[0]
            self.assertIn("GODWORKS SYSTEM v26.4", sent_text)
            self.assertIn("/sh", sent_text)
            self.assertIn("/status", sent_text)

    def test_command_sh_execution(self):
        """Verifica que /sh ejecuta comandos del shell de forma inalámbrica."""
        chat_id = 77777
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(chat_id, "/sh echo 'TELEGRAM_WIRELESS_OK'", "Owner")
            sent_text = mock_send.call_args.args[0]
            self.assertIn("TELEGRAM_WIRELESS_OK", sent_text)

    def test_configure_token_persists(self):
        """Verifica que configurar el token persiste en archivo y recarga."""
        test_token = "123456789:ABCDEF_mock_telegram_token"
        ok = self.bridge.configure_token(test_token, enabled=False)
        self.assertTrue(ok)
        self.assertEqual(self.bridge.bot_token, test_token)
        self.assertTrue(self.config_path.exists())

        loaded_data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded_data["bot_token"], test_token)

    def test_start_and_end_call_commands(self):
        """Verifica que /llamar o /call inicia el modo llamada y /colgar lo finaliza."""
        chat_id = 999111
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "send_message") as mock_msg, \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_fake_audio"), \
             patch.object(self.bridge, "send_voice") as mock_voice:

            # Iniciar llamada
            self.bridge._handle_incoming_text(chat_id, "/llamar", "Owner")
            self.assertIn(chat_id, self.bridge.active_calls)
            mock_msg.assert_called()
            self.assertIn("LLAMADA ENTRANTE DE GIA", mock_msg.call_args.args[0])
            mock_voice.assert_called()

            # Finalizar llamada
            self.bridge._handle_incoming_text(chat_id, "/colgar", "Owner")
            self.assertNotIn(chat_id, self.bridge.active_calls)
            self.assertIn("LLAMADA FINALIZADA", mock_msg.call_args.args[0])

    def test_natural_language_call_trigger(self):
        """Verifica que frases como 'hazme una llamada' o 'llámame' activan la llamada."""
        chat_id = 888222
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "start_call") as mock_start:
            self.bridge._handle_incoming_text(chat_id, "GIA, por favor llámame ahora", "Owner")
            mock_start.assert_called_with(chat_id, user_name="Owner")

    def test_incoming_voice_message_transcription_and_reply(self):
        """Verifica el flujo completo de nota de voz: descarga, transcripción STT y respuesta por voz."""
        chat_id = 777333
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.video_mode_always = False
        self.bridge.voice_mode_always = True

        fake_voice_bytes = b"OggS_test_voice_bytes"
        mock_chat_reply = {"reply": "Comando de voz recibido y procesado correctamente."}

        with patch.object(self.bridge, "download_telegram_file", return_value=fake_voice_bytes), \
             patch.object(self.bridge, "transcribe_audio", return_value="cómo está el sistema"), \
             patch("omni_temporal_control.process_agentic_chat", return_value=mock_chat_reply), \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_response_audio"), \
             patch.object(self.bridge, "send_voice") as mock_voice, \
             patch.object(self.bridge, "send_photo"):

            self.bridge._handle_incoming_voice(chat_id, file_id="voice_xyz_123", user_name="Owner")

            # Debe haber quedado en active_calls
            self.assertIn(chat_id, self.bridge.active_calls)
            # Debe haber respondido con send_voice
            mock_voice.assert_called()
            sent_caption = mock_voice.call_args.kwargs.get("caption", "")
            self.assertIn("Comando de voz recibido", sent_caption)

    def test_active_call_responds_with_voice_to_text(self):
        """Verifica que si el chat está en active_calls, responderá con send_voice a mensajes de texto."""
        chat_id = 666444
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.active_calls.add(chat_id)
        self.bridge.video_mode_always = False
        self.bridge.voice_mode_always = True

        mock_chat_reply = {"reply": "Respondiendo a tu consulta en modo llamada."}

        with patch("omni_temporal_control.process_agentic_chat", return_value=mock_chat_reply), \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_call_audio"), \
             patch.object(self.bridge, "send_voice") as mock_voice, \
             patch.object(self.bridge, "send_photo"):

            self.bridge._handle_incoming_text(chat_id, "Hola GIA, ¿me escuchas?", "Owner")
            mock_voice.assert_called()
            sent_caption = mock_voice.call_args.kwargs.get("caption", "")
            self.assertIn("Respondiendo a tu consulta", sent_caption)

    def test_send_reply_with_voice_simultaneous(self):
        """Verifica que el sistema envía el texto y sintetiza con Cortana enviando el audio a la vez."""
        chat_id = 123999
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.voice_mode_always = True

        test_reply = "Hola Miguel, el sistema está 100% operativo y seguro."

        with patch.object(self.bridge, "send_message") as mock_msg, \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_cortana_audio") as mock_synth, \
             patch.object(self.bridge, "send_voice") as mock_voice:

            res = self.bridge.send_reply_with_voice(test_reply, chat_id=chat_id)
            self.assertTrue(res["ok"])

            # 1. Envió el mensaje de texto
            mock_msg.assert_called_once()
            self.assertEqual(mock_msg.call_args.args[0], test_reply)

            # 2. Sintetizó todo el texto con Cortana
            mock_synth.assert_called_once_with(test_reply)

            # 3. Envió el audio a la vez
            mock_voice.assert_called_once()
            self.assertEqual(mock_voice.call_args.args[0], b"OggS_cortana_audio")

    def test_send_voice_api_call(self):
        """Verifica que send_voice llama a la API de Telegram con formato multipart y OggS."""
        self.bridge.config["bot_token"] = "mock_token_123"
        self.bridge.config["admin_chat_id"] = 12345

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 99}}

            res = self.bridge.send_voice(b"OggS_fake_audio_content", caption="Prueba de voz", chat_id=12345)
            self.assertTrue(res.get("ok"))
            mock_post.assert_called()
            call_url = mock_post.call_args.args[0]
            self.assertIn("https://api.telegram.org/botmock_token_123/sendVoice", call_url)

    def test_send_video_api_call(self):
        """Verifica que send_video llama a la API de Telegram sendVideo con los parámetros correctos."""
        self.bridge.config["bot_token"] = "mock_token_123"
        self.bridge.config["admin_chat_id"] = 12345

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 101}}

            res = self.bridge.send_video(b"fake_mp4_bytes", caption="Prueba de video", chat_id=12345, duration=5)
            self.assertTrue(res.get("ok"))
            mock_post.assert_called()
            call_url = mock_post.call_args.args[0]
            self.assertIn("https://api.telegram.org/botmock_token_123/sendVideo", call_url)
            call_data = mock_post.call_args.kwargs.get("data", {})
            self.assertEqual(call_data.get("chat_id"), 12345)
            self.assertEqual(call_data.get("duration"), 5)

    def test_send_video_note_api_call(self):
        """Verifica que send_video_note llama a sendVideoNote para videomensajes circulares."""
        self.bridge.config["bot_token"] = "mock_token_123"
        self.bridge.config["admin_chat_id"] = 12345

        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 102}}

            res = self.bridge.send_video_note(b"fake_video_note_bytes", chat_id=12345, duration=4)
            self.assertTrue(res.get("ok"))
            mock_post.assert_called()
            call_url = mock_post.call_args.args[0]
            self.assertIn("https://api.telegram.org/botmock_token_123/sendVideoNote", call_url)
            call_data = mock_post.call_args.kwargs.get("data", {})
            self.assertEqual(call_data.get("length"), 480)

    def test_send_reply_with_video_exclusive(self):
        """Verifica que send_reply_with_video genera el video del sistema hablando y lo envía como videonota."""
        chat_id = 12345
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.video_delivery_type = "video_note"

        mock_vid_res = {
            "ok": True,
            "video_bytes": b"fake_rendered_speaking_mp4",
            "duration": 5.2,
            "width": 480,
            "height": 480
        }

        with patch("core.speaking_video_generator.SpeakingVideoGenerator.generate_speaking_video", return_value=mock_vid_res), \
             patch.object(self.bridge, "send_video_note", return_value={"ok": True}) as mock_vn, \
             patch.object(self.bridge, "send_voice") as mock_voice, \
             patch.object(self.bridge, "send_message") as mock_msg:

            res = self.bridge.send_reply_with_video("Hola desde el nodo soberano en video.", chat_id=chat_id)
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("type"), "video_note")
            mock_vn.assert_called_once()
            # NO debe enviar texto ni voz suelta
            mock_voice.assert_not_called()

    def test_command_video_and_modo_toggles(self):
        """Verifica la conmutación de modos /video y /modo."""
        chat_id = 54321
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "send_message") as mock_msg:
            # /video on
            self.bridge._handle_incoming_text(chat_id, "/video on", "Owner")
            self.assertTrue(self.bridge.video_mode_always)
            self.assertIn("MODO VIDEO ACTIVADO", mock_msg.call_args.args[0])

            # /video off
            self.bridge._handle_incoming_text(chat_id, "/video off", "Owner")
            self.assertFalse(self.bridge.video_mode_always)
            self.assertIn("MODO VIDEO DESACTIVADO", mock_msg.call_args.args[0])

            # /modo video
            self.bridge._handle_incoming_text(chat_id, "/modo video", "Owner")
            self.assertTrue(self.bridge.video_mode_always)
            self.assertFalse(self.bridge.voice_mode_always)

    def test_conversational_chat_dispatches_video_exclusively(self):
        """Verifica que una consulta normal en modo video despacha send_reply_with_video y no texto/voz."""
        chat_id = 998877
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.video_mode_always = True

        with patch.object(self.bridge, "send_reply_with_video") as mock_video_reply, \
             patch.object(self.bridge, "send_reply_with_voice") as mock_voice_reply, \
             patch("omni_temporal_control.process_agentic_chat", return_value={"reply": "Respuesta soberana en video"}):

            self.bridge._handle_incoming_text(chat_id, "¿Cómo estás hoy?", "Owner")

            # Debe haber llamado a send_reply_with_video
            mock_video_reply.assert_called_once()
            self.assertEqual(mock_video_reply.call_args.args[0], "Respuesta soberana en video")
            # NO debe haber llamado a send_reply_with_voice
            mock_voice_reply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
