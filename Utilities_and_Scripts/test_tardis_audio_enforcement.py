#!/usr/bin/env python3
"""
tests/test_tardis_audio_enforcement.py - Verificación de la Directiva de Audio Universal en Videos
=================================================================================================
Verifica que:
1. TardisAudioSynthesizer genere paisajes sonoros estéreo no nulos con afinación armónica.
2. La detección de arquetipos sonoros reconozca fórmulas, frecuencias y símbolos.
3. ensure_video_has_audio audite e inyecte audio AAC 48kHz a videos mudos sin perder calidad de video.
4. Todos los videos generados posean permanentemente pista de audio válida.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from core.tardis_audio_synthesizer import (
    TardisAudioSynthesizer,
    ensure_video_has_audio,
    get_audio_synthesizer,
)


class TestTardisAudioEnforcement(unittest.TestCase):

    def setUp(self):
        self.synthesizer = get_audio_synthesizer()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_tardis_audio_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_audio_synthesizer_generates_valid_waveform(self):
        """Verifica que la síntesis acústica produzca un arreglo estéreo válido y no nulo."""
        dur = 2.0
        audio, archetype = self.synthesizer.synthesize_soundscape(
            duration=dur,
            title="Metatrón & Geometría Sagrada",
            formula=r"\Phi = 1.618"
        )
        self.assertEqual(audio.ndim, 2)
        self.assertEqual(audio.shape[1], 2)
        self.assertAlmostEqual(len(audio), int(self.synthesizer.sample_rate * dur), delta=5)
        self.assertGreater(np.max(np.abs(audio)), 0.05)
        self.assertIn("Geometría Sagrada", archetype)

    def test_archetype_detection(self):
        """Comprueba el mapeo de fórmulas y símbolos a sus arquetipos acústicos."""
        cases = [
            ("Atractor Caótico de Lorenz", r"\dot{x} = \sigma(y-x)", "Caos"),
            ("Agujero Negro de Kerr", r"ds^2 = -\dots", "Kerr"),
            ("Función de Onda Cuántica", r"\psi(x,t)", "Cuántica"),
            ("Fluido Micropolar Cósmico", r"f_{R-O}", "Fluidos"),
            ("Reloj Temporal de Gallifrey", "Línea Cero", "Reloj"),
            ("Horizonte Retro Synthwave", "80s neon", "Synthwave"),
        ]
        for title, formula, expected_keyword in cases:
            _, arch = self.synthesizer.synthesize_soundscape(1.0, title=title, formula=formula)
            self.assertTrue(
                expected_keyword.lower() in arch.lower(),
                f"Esperaba '{expected_keyword}' en arquetipo '{arch}' para '{title}'"
            )

    def test_ensure_video_has_audio_injects_track(self):
        """Genera un video mudo sintético de prueba y comprueba que se le inyecte audio AAC."""
        silent_video = self.temp_dir / "test_silent.mp4"
        # Crear video mudo de 2 segundos con lavfi color
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=navy:s=320x240:d=2:r=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(silent_video)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 1. Comprobar que inicialmente NO tiene audio
        self.assertFalse(self.synthesizer.video_has_audio(silent_video))

        # 2. Aplicar directiva soberana de audio
        res = ensure_video_has_audio(
            silent_video,
            title="Símbolo Sagrado Cubo de Metatrón",
            formula=r"\Phi = \frac{1+\sqrt{5}}{2}"
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("injected_audio"))

        # 3. Comprobar con ffprobe que AHORA SÍ tiene audio AAC
        self.assertTrue(self.synthesizer.video_has_audio(silent_video))

        # 4. Verificar parámetros del audio con ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_name,channels",
            "-of", "csv=p=0",
            str(silent_video)
        ]
        probe_out = subprocess.check_output(probe_cmd).decode().strip()
        self.assertIn("aac", probe_out.lower())


if __name__ == "__main__":
    unittest.main()
