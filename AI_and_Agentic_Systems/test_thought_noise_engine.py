import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from core.thought_noise_engine import ThoughtNoiseEngine, get_thought_noise_engine
from omni_temporal_control import process_hardware_chat_intent


class TestThoughtNoiseEngine(unittest.TestCase):
    def setUp(self):
        self.engine = get_thought_noise_engine()

    def test_singleton_engine(self):
        """Verifica que get_thought_noise_engine retorna siempre la misma instancia."""
        e2 = get_thought_noise_engine()
        self.assertIs(self.engine, e2)
        self.assertEqual(self.engine.width, 720)
        self.assertEqual(self.engine.height, 480)

    def test_calculate_prompt_entropy(self):
        """Verifica el cálculo de entropía de Shannon para diferentes estímulos."""
        e_empty = self.engine._calculate_prompt_entropy("")
        self.assertGreaterEqual(e_empty, 1.2)

        e_rep = self.engine._calculate_prompt_entropy("aaaaaaa")
        self.assertLessEqual(e_rep, 2.5)

        e_complex = self.engine._calculate_prompt_entropy(
            "Interpretación cuántica de Wheeler-Feynman con atractor sintrópico y función de onda Ψ"
        )
        self.assertGreater(e_complex, e_rep)

    def test_noise_matrix_generation(self):
        """Verifica que la matriz de ruido cognitivo 2D tenga dimensiones y normalización correctas."""
        mat = self.engine._generate_noise_matrix(entropy=3.5, seed=42, syntropy_phase=0.8)
        self.assertEqual(mat.shape, (480, 720))
        self.assertGreaterEqual(mat.min(), 0.0)
        self.assertLessEqual(mat.max(), 1.0)
        self.assertTrue(np.issubdtype(mat.dtype, np.floating))

    def test_generate_thought_frame(self):
        """Verifica la generación de la imagen de espectrograma y metadatos de metapensamiento."""
        frame = self.engine.generate_thought_frame(
            prompt="Ecuación de Wheeler-Feynman y resonancia causal",
            model_name="Hermes 3 (8B)",
            active_step="TEST COGNITIVO"
        )

        self.assertTrue(frame["ok"])
        self.assertIsInstance(frame["png_bytes"], bytes)
        # Magic bytes de un archivo PNG válido
        self.assertEqual(frame["png_bytes"][:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(frame["data_uri"].startswith("data:image/png;base64,"))
        self.assertGreater(frame["entropy_shannon"], 0.0)
        self.assertGreater(frame["syntropy_coherence_pct"], 0.0)
        self.assertIsInstance(frame["active_symbols"], list)
        self.assertGreaterEqual(len(frame["active_symbols"]), 3)
        self.assertIn("Hermes 3 (8B)", frame["diagnostic_text"])
        self.assertIn("Ψ", frame["diagnostic_text"])

    def test_get_latest_frame_cache(self):
        """Verifica la persistencia y recuperación del último frame generado."""
        frame1 = self.engine.generate_thought_frame(prompt="Prueba de cache")
        latest = self.engine.get_latest_frame()
        self.assertIsNotNone(latest)
        self.assertEqual(frame1["timestamp"], latest["timestamp"])
        self.assertEqual(frame1["png_bytes"], latest["png_bytes"])

    def test_hardware_chat_intent_ruido(self):
        """Verifica que los comandos de chat /ruido y /mente activen la síntesis de metapensamiento."""
        res_slash = process_hardware_chat_intent("/ruido")
        self.assertIsNotNone(res_slash)
        self.assertTrue(res_slash.get("executed"))
        self.assertEqual(res_slash.get("action"), "cognitive_thought_noise")
        self.assertIn("thought_frame", res_slash)
        self.assertTrue(res_slash["thought_frame"]["png_bytes"].startswith(b"\x89PNG"))

        # Lenguaje natural en español
        res_nl = process_hardware_chat_intent("analiza tu propio pensamiento y dibuja el ruido")
        self.assertIsNotNone(res_nl)
        self.assertTrue(res_nl.get("executed"))
        self.assertEqual(res_nl.get("action"), "cognitive_thought_noise")
        self.assertIn("thought_frame", res_nl)

    def test_telegram_bridge_ruido_command(self):
        """Verifica que TelegramBridge despache la imagen con /ruido a un chat autorizado."""
        from core.telegram_bridge import TelegramBridge
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "tg_test_cfg.json"
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = 999111
            bridge.authorized_chat_ids.add(chat_id)

            with patch.object(bridge, "send_photo") as mock_photo:
                bridge._handle_incoming_text(chat_id, "/ruido", "MasterUser")
                mock_photo.assert_called_once()
                args, kwargs = mock_photo.call_args
                photo_bytes = args[0]
                self.assertEqual(photo_bytes[:8], b"\x89PNG\r\n\x1a\n")
                self.assertIn("METAPENSAMIENTO SOBERANO", kwargs.get("caption", ""))


if __name__ == "__main__":
    unittest.main()
