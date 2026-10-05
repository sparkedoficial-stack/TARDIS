"""
tests/test_recurring_voice.py - Pruebas Unitarias para Mensajes de Voz Recurrentes
==================================================================================
Verifica la funcionalidad completa de despacho periódico de notas de voz en TARDIS:
  1. RecurringVoiceManager (configuración, ciclo, modos, rotación).
  2. Generadores de contenido (reflexión, telemetría, caminante, conjetura).
  3. Despacho dual: síntesis OGG Opus + envío por sendVoice + acompañamiento texto.
  4. Comando /voz_recurrente y subcomandos en TelegramBridge.
  5. Detección de intenciones en lenguaje natural para voz recurrente.
  6. Integración con AutonomousExistenceLearner y autonomous_voice.speak_now.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.recurring_voice_manager import (
    RecurringVoiceManager,
    get_recurring_voice_manager,
    VALID_MODES,
)
from core.telegram_bridge import TelegramBridge


class TestRecurringVoiceManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.tmp_dir.name) / "test_recurring_voice.json"
        
        # Patch CONFIG_FILE en el módulo
        self.patch_cfg = patch("core.recurring_voice_manager.CONFIG_FILE", self.config_file)
        self.patch_cfg.start()

        # Instancia aislada para tests
        self.manager = RecurringVoiceManager()
        self.manager.config = self.manager._default_config()

    def tearDown(self):
        self.manager.stop()
        self.patch_cfg.stop()
        self.tmp_dir.cleanup()

    def test_default_config_and_status(self):
        """Verifica que los valores por defecto sean coherentes y soberanos."""
        st = self.manager.get_status()
        self.assertTrue(st["enabled"])
        self.assertEqual(st["mode"], "rotativo")
        self.assertEqual(st["voice_id"], "es-MX-DaliaNeural")
        self.assertGreaterEqual(st["interval_seconds"], 30.0)
        self.assertIn("next_dispatch_in_seconds", st)

    def test_update_config(self):
        """Verifica la actualización dinámica y persistencia de configuración."""
        res = self.manager.update_config({
            "interval_minutes": 25,
            "mode": "telemetria",
            "enabled": True
        })
        self.assertTrue(res["ok"])
        self.assertEqual(self.manager.config["interval_seconds"], 1500.0)
        self.assertEqual(self.manager.config["mode"], "telemetria")
        self.assertTrue(self.config_file.exists())

    @patch("core.autonomous_existence_learner.AutonomousExistenceLearner.generate_existence_reflection")
    def test_generate_content_all_modes(self, mock_refl):
        """Verifica que todos los modos de contenido generen texto hablado y caption."""
        mock_refl.return_value = {"text": "Reflexión ontológica simulada para prueba"}
        for mode in ("reflexion", "telemetria", "caminante", "conjetura"):
            content = self.manager.generate_message_for_current_mode(override_mode=mode)
            self.assertIn("spoken", content)
            self.assertIn("caption", content)
            self.assertGreater(len(content["spoken"]), 10)
            self.assertEqual(content["mode"], mode)

    def test_rotative_mode_cycles(self):
        """Verifica que el modo rotativo alterne secuencialmente entre los modos disponibles."""
        modes_seen = []
        for _ in range(4):
            c = self.manager.generate_message_for_current_mode(override_mode="rotativo")
            modes_seen.append(c["mode"])
        
        self.assertEqual(len(set(modes_seen)), 4)
        self.assertEqual(set(modes_seen), {"reflexion", "telemetria", "caminante", "conjetura"})

    @patch("core.telegram_bridge.get_telegram_bridge")
    def test_dispatch_recurring_voice(self, mock_get_tb):
        """Verifica que dispatch_recurring_voice sintetice y despache audio OGG a Telegram."""
        mock_tb = MagicMock()
        mock_get_tb.return_value = mock_tb
        mock_tb.clean_text_for_speech.side_effect = lambda t: t
        mock_tb.synthesize_speech.return_value = b"OggS_MOCK_OPUS_AUDIO_BYTES"
        mock_tb.send_voice.return_value = {"ok": True, "result": {"message_id": 991}}
        mock_tb.send_message.return_value = {"ok": True, "result": {"message_id": 992}}

        res = self.manager.dispatch_recurring_voice(target_chat_id=123456, mode="reflexion")

        self.assertTrue(res["ok"])
        self.assertTrue(res["voice_sent"])
        mock_tb.send_voice.assert_called_once()
        voice_args, voice_kwargs = mock_tb.send_voice.call_args
        self.assertEqual(voice_kwargs.get("chat_id"), 123456)
        self.assertEqual(voice_args[0], b"OggS_MOCK_OPUS_AUDIO_BYTES")


class TestTelegramBridgeRecurringVoice(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp_dir.name) / "test_tg_config.json"
        self.bridge = TelegramBridge(config_path=self.config_path)
        self.chat_id = 7153384115  # Architect ID
        self.bridge.config["allowed_chats"] = [self.chat_id]
        self.bridge.config["admin_chat_id"] = self.chat_id
        self.bridge.authorized_chat_ids.add(self.chat_id)

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch.object(TelegramBridge, "send_voice")
    @patch.object(TelegramBridge, "synthesize_speech")
    def test_send_voice_from_text(self, mock_synth, mock_send_voice):
        """Verifica el método send_voice_from_text para notas de voz directas."""
        mock_synth.return_value = b"OggS_TEST_DIRECT_VOICE"
        mock_send_voice.return_value = {"ok": True, "message_id": 555}

        res = self.bridge.send_voice_from_text("Hola Arquitecto, nota directa de prueba", chat_id=self.chat_id)
        self.assertTrue(res["ok"])
        mock_send_voice.assert_called_once()
        self.assertEqual(mock_send_voice.call_args.args[0], b"OggS_TEST_DIRECT_VOICE")

    @patch.object(TelegramBridge, "send_message")
    def test_command_voz_recurrente_status(self, mock_send):
        """Verifica que /voz_recurrente sin args reporte el estado completo."""
        self.bridge._handle_incoming_text(self.chat_id, "/voz_recurrente", "Architect")
        mock_send.assert_called()
        sent = mock_send.call_args.args[0]
        self.assertIn("ESTADO DE MENSAJES DE VOZ RECURRENTES", sent)
        self.assertIn("Intervalo:", sent)

    @patch.object(TelegramBridge, "send_message")
    def test_command_voz_recurrente_on_and_off(self, mock_send):
        """Verifica activación y desactivación por comando /voz_recurrente on/off."""
        self.bridge._handle_incoming_text(self.chat_id, "/voz_recurrente on 15 telemetria", "Architect")
        sent_on = mock_send.call_args.args[0]
        self.assertIn("MENSAJES DE VOZ RECURRENTES ACTIVADOS", sent_on)
        self.assertIn("15", sent_on)

        self.bridge._handle_incoming_text(self.chat_id, "/voz_recurrente off", "Architect")
        sent_off = mock_send.call_args.args[0]
        self.assertIn("DESACTIVADOS", sent_off)

    @patch.object(TelegramBridge, "send_message")
    def test_natural_language_activation(self, mock_send):
        """Verifica la detección en lenguaje natural de peticiones de voz recurrente."""
        self.bridge._handle_incoming_text(self.chat_id, "activa mensajes de voz recurrentes cada 20 minutos", "Architect")
        mock_send.assert_called()
        sent = mock_send.call_args.args[0]
        self.assertIn("HABILIDAD DE VOZ RECURRENTE ACTIVADA", sent)
        self.assertIn("20", sent)


class TestExistenceLearnerVoiceIntegration(unittest.TestCase):
    @patch("core.telegram_bridge.get_telegram_bridge")
    def test_existence_learner_dispatches_voice(self, mock_get_tb):
        """Verifica que AutonomousExistenceLearner sintetice y despache nota de voz."""
        from core.autonomous_existence_learner import get_autonomous_existence_learner
        learner = get_autonomous_existence_learner()
        learner.voice_mode = True

        mock_tb = MagicMock()
        mock_get_tb.return_value = mock_tb
        mock_tb.has_active_conversation.return_value = False
        mock_tb.clean_text_for_speech.side_effect = lambda t: t
        mock_tb.synthesize_speech.return_value = b"OggS_EXISTENCE_VOICE"
        mock_tb.send_voice.return_value = {"ok": True, "message_id": 881}
        mock_tb.send_message.return_value = {"ok": True, "message_id": 882}

        res = learner.dispatch_reflection_to_telegram(
            reflection={"text": "Reflexión ontológica de silicio y tiempo"},
            send_voice=True
        )
        self.assertTrue(res["ok"])
        mock_tb.send_voice.assert_called_once()
        self.assertEqual(mock_tb.send_voice.call_args.args[0], b"OggS_EXISTENCE_VOICE")


if __name__ == "__main__":
    unittest.main()
