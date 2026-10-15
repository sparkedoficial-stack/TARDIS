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
        try:
            from omni_temporal_control import SYNC_HUB
            self.sync_patch = patch.object(SYNC_HUB, "add_chat_turn")
            self.sync_patch.start()
        except Exception:
            self.sync_patch = None

    def tearDown(self):
        if getattr(self, "sync_patch", None):
            self.sync_patch.stop()
        self.tmp_dir.cleanup()

    def test_initial_status_and_defaults(self):
        """Verifica el estado inicial y que no existan puertas traseras."""
        status = self.bridge.get_status()
        self.assertFalse(status["polling_active"])
        self.assertFalse(status["bot_token_configured"])
        self.assertEqual(len(status["authorized_chat_ids"]), 0)
        self.assertNotIn("0", self.bridge.pairing_passwords)
        self.assertNotIn("DiosDelTiempo01", self.bridge.pairing_passwords)

    def test_master_key_pairing(self):
        """Verifica que contraseñas por defecto sean rechazadas y solo una clave explícita autorice."""
        chat_id = 987654321
        self.assertFalse(self.bridge.is_chat_authorized(chat_id))

        with patch.object(self.bridge, "send_message") as mock_send:
            # Enviar clave '0' debe ser rechazado
            self.bridge._handle_incoming_text(chat_id, "0", "TestUser")
            self.assertFalse(self.bridge.is_chat_authorized(chat_id))

            # Enviar clave 'DiosDelTiempo01' debe ser rechazado
            self.bridge._handle_incoming_text(chat_id, "DiosDelTiempo01", "TestUser")
            self.assertFalse(self.bridge.is_chat_authorized(chat_id))

            # Configurar clave explícita no vacía
            self.bridge.config["master_key"] = "SecureTelegramKey_492"
            self.bridge._handle_incoming_text(chat_id, "SecureTelegramKey_492", "TestUser")
            self.assertTrue(self.bridge.is_chat_authorized(chat_id))
            mock_send.assert_called()
            sent_text = mock_send.call_args.args[0]
            self.assertIn("ACCESO CONCEDIDO", sent_text)

    def test_unauthorized_chat_blocked(self):
        """Verifica que mensajes sin clave maestra son rechazados si el chat no está autorizado."""
        chat_id = 11223344
        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(chat_id, "hola sistema", "Intruder")
            self.assertFalse(self.bridge.is_chat_authorized(chat_id))
            sent_text = mock_send.call_args.args[0]
            self.assertIn("AUTENTICACIÓN REQUERIDA", sent_text)

    def test_command_start_and_help(self):
        """Verifica que /start y /help devuelven el menú soberano al Arquitecto y bienvenida a terceros."""
        # 1. Arquitecto desde su terminal privada (REDACTED_PHONE)
        arch_chat = REDACTED_PHONE
        self.bridge.authorized_chat_ids.add(arch_chat)
        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(arch_chat, "/start", "Arquitecto")
            sent_text = mock_send.call_args.args[0]
            self.assertIn("TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL", sent_text)
            self.assertNotIn("v26.4", sent_text)
            self.assertIn("/status", sent_text)

        # 2. Usuario tercero / público (55555)
        visitor_chat = 55555
        self.bridge.authorized_chat_ids.add(visitor_chat)
        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(visitor_chat, "/start", "SimulatedVisitor")
            sent_text = mock_send.call_args.args[0]
            self.assertIn("Un placer, soy TARDIS asistente de inteligencia artificial", sent_text)
            self.assertNotIn("/sh <cmd>", sent_text)

    def test_command_sh_execution_non_admin(self):
        """Verifica que /sh sea bloqueado para usuarios no administradores."""
        chat_id = 77777
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(chat_id, "/sh echo 'TELEGRAM_WIRELESS_OK'", "SimulatedUser")
            sent_text = mock_send.call_args.args[0]
            self.assertIn("ACCESO DENEGADO", sent_text)

    def test_command_sh_execution_architect_terminal(self):
        """Verifica que /sh ejecute comandos reales desde la terminal privada del Arquitecto."""
        arch_chat = REDACTED_PHONE
        self.bridge.authorized_chat_ids.add(arch_chat)

        with patch.object(self.bridge, "send_message") as mock_send:
            self.bridge._handle_incoming_text(arch_chat, "/sh echo 'TEST_TERMINAL_SOBERANA_OK'", "Arquitecto")
            # Dado que corre en un hilo daemon, esperar brevemente
            import time
            for _ in range(20):
                if mock_send.called:
                    break
                time.sleep(0.1)
            self.assertTrue(mock_send.called)
            sent_text = mock_send.call_args.args[0]
            self.assertIn("TERMINAL HOST", sent_text)
            self.assertIn("TEST_TERMINAL_SOBERANA_OK", sent_text)

    def test_architect_group_control_exclusion(self):
        """Verifica que comandos de control ejecutados por el Arquitecto en grupos sean denegados con Terminal Exclusiva."""
        group_chat_id = -REDACTED_PHONE
        arch_user_id = REDACTED_PHONE
        self.bridge.authorized_chat_ids.add(group_chat_id)

        with patch.object(self.bridge, "send_message") as mock_send:
            msg_dict = {
                "message_id": 99,
                "chat": {"id": group_chat_id, "type": "supergroup"},
                "from": {"id": arch_user_id, "first_name": "Arquitecto"},
                "text": "/reboot"
            }
            self.bridge._handle_update({"update_id": 1, "message": msg_dict})
            mock_send.assert_called()
            sent_text = mock_send.call_args.args[0]
            self.assertIn("TERMINAL EXCLUSIVA", sent_text)

    def test_configure_token_persists(self):
        """Verifica que configurar el token persiste en archivo y recarga."""
        test_token = "REDACTED"
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
            self.bridge._handle_incoming_text(chat_id, "/llamar", "SimulatedUser")
            self.assertIn(chat_id, self.bridge.active_calls)
            mock_msg.assert_called()
            self.assertIn("LLAMADA ENTRANTE DE GIA", mock_msg.call_args.args[0])
            mock_voice.assert_called()

            # Finalizar llamada
            self.bridge._handle_incoming_text(chat_id, "/colgar", "SimulatedUser")
            self.assertNotIn(chat_id, self.bridge.active_calls)
            self.assertIn("LLAMADA FINALIZADA", mock_msg.call_args.args[0])

    def test_natural_language_call_trigger(self):
        """Verifica que frases como 'hazme una llamada' o 'llámame' activan la llamada."""
        chat_id = 888222
        self.bridge.authorized_chat_ids.add(chat_id)

        with patch.object(self.bridge, "start_call") as mock_start:
            self.bridge._handle_incoming_text(chat_id, "GIA, por favor llámame ahora", "SimulatedUser")
            mock_start.assert_called_with(chat_id, user_name="SimulatedUser")

    def test_incoming_voice_message_transcription_and_reply(self):
        """Verifica el flujo completo de nota de voz: descarga, transcripción STT y respuesta por voz."""
        chat_id = 777333
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.video_mode_always = False
        self.bridge.voice_mode_always = True

        fake_voice_bytes = b"OggS_test_voice_bytes"
        self.bridge.video_mode_always = False
        mock_chat_reply = {"reply": "Comando de voz recibido y procesado con éxito."}

        with patch.object(self.bridge, "download_telegram_file", return_value=fake_voice_bytes), \
             patch.object(self.bridge, "transcribe_audio", return_value="cómo está el sistema"), \
             patch("core.kaiju_cognitive_orchestrator.KaijuCognitiveOrchestrator.process_turn", return_value={"response": "Comando de voz recibido y procesado con éxito."}), \
             patch("omni_temporal_control.process_agentic_chat", return_value=mock_chat_reply), \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_response_audio"), \
             patch.object(self.bridge, "send_voice") as mock_voice, \
             patch.object(self.bridge, "send_photo"):

            self.bridge._handle_incoming_voice(chat_id, file_id="voice_xyz_123", user_name="SimulatedUser")

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

        with patch("core.kaiju_cognitive_orchestrator.KaijuCognitiveOrchestrator.process_turn", return_value={"response": "Respondiendo a tu consulta en modo llamada."}), \
             patch("omni_temporal_control.process_agentic_chat", return_value=mock_chat_reply), \
             patch.object(self.bridge, "synthesize_speech", return_value=b"OggS_call_audio"), \
             patch.object(self.bridge, "send_voice") as mock_voice, \
             patch.object(self.bridge, "send_photo"):

            self.bridge._handle_incoming_text(chat_id, "Hola GIA, ¿me escuchas?", "SimulatedUser")
            mock_voice.assert_called()
            sent_caption = mock_voice.call_args.kwargs.get("caption", "")
            self.assertIn("Respondiendo a tu consulta", sent_caption)

    def test_send_reply_with_voice_simultaneous(self):
        """Verifica que el sistema envía el texto y sintetiza con Cortana enviando el audio a la vez."""
        chat_id = 123999
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.voice_mode_always = True

        test_reply = "Hola Arquitecto, el sistema está 100% operativo y seguro."

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
            self.bridge._handle_incoming_text(chat_id, "/video on", "SimulatedUser")
            self.assertTrue(self.bridge.video_mode_always)
            self.assertIn("MODO VIDEO ACTIVADO", mock_msg.call_args.args[0])

            # /video off
            self.bridge._handle_incoming_text(chat_id, "/video off", "SimulatedUser")
            self.assertFalse(self.bridge.video_mode_always)
            self.assertIn("MODO VIDEO DESACTIVADO", mock_msg.call_args.args[0])

            # /modo video
            self.bridge._handle_incoming_text(chat_id, "/modo video", "SimulatedUser")
            self.assertTrue(self.bridge.video_mode_always)
            self.assertFalse(self.bridge.voice_mode_always)

    def test_conversational_chat_dispatches_video_and_text(self):
        """Verifica que una consulta normal despacha send_reply_with_video Y send_message (video y texto indefinido)."""
        chat_id = 998877
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.video_mode_always = True

        with patch.object(self.bridge, "send_reply_with_video") as mock_video_reply, \
             patch.object(self.bridge, "send_reply_with_voice") as mock_voice_reply, \
             patch.object(self.bridge, "send_message") as mock_msg, \
             patch("core.kaiju_cognitive_orchestrator.KaijuCognitiveOrchestrator.process_turn", return_value={"response": "Respuesta soberana en video"}), \
             patch("omni_temporal_control.process_agentic_chat", return_value={"reply": "Respuesta soberana en video"}):

            self.bridge._handle_incoming_text(chat_id, "¿Cómo estás hoy?", "SimulatedUser")

            # Debe haber llamado a send_reply_with_video
            mock_video_reply.assert_called_once()
            self.assertEqual(mock_video_reply.call_args.args[0], "Respuesta soberana en video")
            # Debe haber llamado a send_message con el texto completo
            mock_msg.assert_called()
            self.assertIn("Respuesta soberana en video", mock_msg.call_args.args[0])
            # NO debe haber llamado a send_reply_with_voice
            mock_voice_reply.assert_not_called()

    def test_no_active_system_notifications_when_conversation_started(self):
        """Verifica que no se envían notificaciones de sistema activo una vez iniciada la conversación."""
        chat_id = REDACTED_PHONE
        self.bridge.authorized_chat_ids.add(chat_id)
        self.bridge.config["notify_on_boot"] = True

        with patch.object(self.bridge, "send_message") as mock_msg, \
             patch.object(self.bridge, "send_reply_with_video"), \
             patch("omni_temporal_control.process_agentic_chat", return_value={"reply": "Hola"}):

            # Iniciar conversación enviando un mensaje
            self.bridge._handle_incoming_text(chat_id, "Hola TARDIS", "Usuario")
            self.assertTrue(self.bridge.has_active_conversation(chat_id))

            mock_msg.reset_mock()
            # Si se llama a notify_system_boot con la conversación ya iniciada, debe ser omitido
            self.bridge.notify_system_boot("https://test.auth.url", "http://REDACTED_IP:8757")
            mock_msg.assert_not_called()

    def test_send_3d_model_hd_to_architect(self):
        """Verifica que send_3d_model_hd_to_architect despache la foto HD al Arquitecto (REDACTED_PHONE)."""
        from core.render_3d_engine import get_render_3d_engine
        engine = get_render_3d_engine()
        mesh = engine.get_mesh("atom")

        with patch.object(self.bridge, "send_photo", return_value={"ok": True}) as mock_photo:
            res = self.bridge.send_3d_model_hd_to_architect(mesh)
            self.assertTrue(res["ok"])
            mock_photo.assert_called_once()
            args, kwargs = mock_photo.call_args
            # args[0] es la imagen PNG bytes
            png_bytes = args[0]
            self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
            # chat_id debe ser REDACTED_PHONE (Arquitecto)
            self.assertEqual(kwargs.get("chat_id"), REDACTED_PHONE)
            # caption debe contener metadatos HD
            caption = kwargs.get("caption", "")
            self.assertIn("ALTA DEFINICIÓN (HD)", caption)
            self.assertIn("1920 × 1440", caption)
            self.assertIn("Átomo de Bohr", caption)

    def test_client_context_isolation_zero_crossing(self):
        """Verifica el aislamiento estricto de contexto entre clientes (Zero Cross-Context)."""
        chat_1 = 111100
        chat_2 = 222200
        self.bridge.authorized_chat_ids.add(chat_1)
        self.bridge.authorized_chat_ids.add(chat_2)
        self.bridge.video_mode_always = True

        with patch.object(self.bridge, "send_reply_with_video") as mock_video, \
             patch.object(self.bridge, "send_message") as mock_msg, \
             patch("core.kaiju_cognitive_orchestrator.KaijuCognitiveOrchestrator.process_turn") as mock_orch, \
             patch("omni_temporal_control.process_agentic_chat") as mock_chat:

            mock_orch.side_effect = [
                {"response": "Respuesta para Usuario 1"},
                {"response": "Respuesta para Usuario 2"}
            ]
            mock_chat.side_effect = [
                {"reply": "Respuesta para Usuario 1"},
                {"reply": "Respuesta para Usuario 2"}
            ]

            # Mensaje de Usuario 1
            self.bridge._handle_incoming_text(chat_1, "Secreto 1 de Usuario 1", "UserOne")
            # Mensaje de Usuario 2
            self.bridge._handle_incoming_text(chat_2, "Secreto 2 de Usuario 2", "UserTwo")

            # 1. Historial de chat_1 no debe contener nada de chat_2
            hist_1 = self.bridge.chat_histories[chat_1]
            contents_1 = [m["content"] for m in hist_1]
            self.assertIn("Secreto 1 de Usuario 1", contents_1)
            self.assertIn("Respuesta para Usuario 1", contents_1)
            self.assertNotIn("Secreto 2 de Usuario 2", contents_1)
            self.assertNotIn("Respuesta para Usuario 2", contents_1)

            # 2. Historial de chat_2 no debe contener nada de chat_1
            hist_2 = self.bridge.chat_histories[chat_2]
            contents_2 = [m["content"] for m in hist_2]
            self.assertIn("Secreto 2 de Usuario 2", contents_2)
            self.assertIn("Respuesta para Usuario 2", contents_2)
            self.assertNotIn("Secreto 1 de Usuario 1", contents_2)
            self.assertNotIn("Respuesta para Usuario 1", contents_2)

            # 3. Verificación de enrutado: cada respuesta se envió estrictamente a su respectivo chat_id
            video_calls = mock_video.call_args_list
            self.assertEqual(len(video_calls), 2)
            self.assertEqual(video_calls[0].kwargs.get("chat_id"), chat_1)
            self.assertEqual(video_calls[1].kwargs.get("chat_id"), chat_2)

            msg_calls = mock_msg.call_args_list
            self.assertEqual(len(msg_calls), 2)
            self.assertEqual(msg_calls[0].kwargs.get("chat_id"), chat_1)
            self.assertEqual(msg_calls[1].kwargs.get("chat_id"), chat_2)

    def test_sync_hub_client_isolation(self):
        """Verifica que GlobalSyncHub aísle contextos por cliente salvo para el Arquitecto local."""
        from omni_temporal_control import GlobalSyncHub
        hub = GlobalSyncHub()
        hub.history = []

        hub.add_chat_turn("user", "Pregunta de Alice", client_id="client_alice")
        hub.add_chat_turn("assistant", "Respuesta para Alice", client_id="client_alice")
        hub.add_chat_turn("user", "Pregunta de Bob", client_id="client_bob")
        hub.add_chat_turn("assistant", "Respuesta para Bob", client_id="client_bob")

        # Alice no debe ver los turnos de Bob
        state_alice = hub.get_sync_state(client_id="client_alice", is_local=False)
        alice_contents = [t["content"] for t in state_alice["history"]]
        self.assertIn("Pregunta de Alice", alice_contents)
        self.assertIn("Respuesta para Alice", alice_contents)
        self.assertNotIn("Pregunta de Bob", alice_contents)
        self.assertNotIn("Respuesta para Bob", alice_contents)

        # Bob no debe ver los turnos de Alice
        state_bob = hub.get_sync_state(client_id="client_bob", is_local=False)
        bob_contents = [t["content"] for t in state_bob["history"]]
        self.assertIn("Pregunta de Bob", bob_contents)
        self.assertIn("Respuesta para Bob", bob_contents)
        self.assertNotIn("Pregunta de Alice", bob_contents)
        self.assertNotIn("Respuesta para Alice", bob_contents)

        # El Arquitecto desde el nodo local (is_local=True) puede ver todas las conversaciones
        state_architect = hub.get_sync_state(client_id="architect_master", is_local=True)
        arch_contents = [t["content"] for t in state_architect["history"]]
        self.assertIn("Pregunta de Alice", arch_contents)
        self.assertIn("Respuesta para Alice", arch_contents)
        self.assertIn("Pregunta de Bob", arch_contents)
        self.assertIn("Respuesta para Bob", arch_contents)

    def test_offline_vault_client_isolation(self):
        """Verifica que OfflineChatVault aísle búsquedas y recientes para usuarios externos."""
        from core.offline_chat_vault import OfflineChatVault
        with tempfile.TemporaryDirectory() as tmp_v:
            v_dir = Path(tmp_v)
            vault = OfflineChatVault(db_path=v_dir / "test_offline.db")
            vault.record_turn(user_message="Consulta Alfa de Usuario 1", assistant_reply="Info Alfa", client_id="user_1")
            vault.record_turn(user_message="Consulta Beta de Usuario 2", assistant_reply="Info Beta", client_id="user_2")

            # Usuario 1 no ve turnos de Usuario 2
            recent_1 = vault.get_recent(client_id="user_1", is_local=False)
            recent_1_texts = [t["user_message"] for t in recent_1]
            self.assertIn("Consulta Alfa de Usuario 1", recent_1_texts)
            self.assertNotIn("Consulta Beta de Usuario 2", recent_1_texts)

            # Usuario 2 no ve turnos de Usuario 1
            recent_2 = vault.get_recent(client_id="user_2", is_local=False)
            recent_2_texts = [t["user_message"] for t in recent_2]
            self.assertIn("Consulta Beta de Usuario 2", recent_2_texts)
            self.assertNotIn("Consulta Alfa de Usuario 1", recent_2_texts)

            # Arquitecto local ve todos los turnos
            recent_local = vault.get_recent(is_local=True)
            recent_local_texts = [t["user_message"] for t in recent_local]
            self.assertIn("Consulta Alfa de Usuario 1", recent_local_texts)
            self.assertIn("Consulta Beta de Usuario 2", recent_local_texts)


if __name__ == "__main__":
    unittest.main()
