"""
tests/test_speaking_video_generator.py - Pruebas del Generador de Video del Sistema Hablando
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.speaking_video_generator import SpeakingVideoGenerator, get_speaking_video_generator


class TestSpeakingVideoGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.generator = SpeakingVideoGenerator(output_dir=Path(self.tmp_dir.name))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_singleton_instance(self):
        gen1 = get_speaking_video_generator()
        gen2 = get_speaking_video_generator()
        self.assertIs(gen1, gen2)

    def test_clean_text_for_speech(self):
        raw = "### Título\n```python\nprint('hola')\n```\nTexto con **negrita**, _cursiva_ y [enlace](https://example.com)!"
        clean = self.generator.clean_text_for_speech(raw)
        self.assertNotIn("```", clean)
        self.assertNotIn("**", clean)
        self.assertNotIn("###", clean)
        self.assertNotIn("[enlace]", clean)
        self.assertIn("Código:", clean)
        self.assertIn("enlace", clean)

    def test_create_overlay_image(self):
        overlay = self.generator.create_overlay_image("Hola mundo, prueba de subtítulos.", width=480, height=480)
        self.assertEqual(overlay.size, (480, 480))
        self.assertEqual(overlay.mode, "RGBA")

    def test_generate_speaking_video_with_synthetic_audio(self):
        # Crear audio sintético de 2 segundos con ffmpeg
        dummy_audio_path = Path(self.tmp_dir.name) / "dummy.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame", str(dummy_audio_path)],
            check=True,
            capture_output=True
        )
        audio_bytes = dummy_audio_path.read_bytes()

        res = self.generator.generate_speaking_video(
            text="Esta es una prueba de video generado por el sistema.",
            audio_bytes=audio_bytes
        )

        self.assertTrue(res["ok"], f"Fallo al generar video: {res.get('error')}")
        self.assertTrue(os.path.exists(res["video_path"]))
        self.assertGreater(res["file_size"], 1000)
        self.assertEqual(res["width"], 480)
        self.assertEqual(res["height"], 480)
        self.assertAlmostEqual(res["duration"], 2.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
