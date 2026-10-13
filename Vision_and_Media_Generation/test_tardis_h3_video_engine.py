#!/usr/bin/env python3
"""
tests/test_tardis_h3_video_engine.py - Validación Integral del Motor MiniMax H3
==============================================================================
GODWORKS SYSTEM v26.4 · Directiva Soberana del Arquitecto (₪)

Verifica:
  1. Parámetros arquitectónicos y de inferencia H3 (Configuración soberana).
  2. Integración ODE Flow Matching (Euler, Midpoint, Heun-Ancestral).
  3. Transformador DiT factorizado espaciotemporal y atención cruzada Audio-Visual.
  4. Decodificador por teselas (Tiled VAE) con bajo consumo de VRAM.
  5. Códec acústico nativo estéreo 32 kHz acoplado con frecuencias sintrópicas.
  6. Síntesis completa FastH3 en MP4 acelerada por NVENC y verificada con ffprobe.
  7. Evaluador perceptual de similitud 2D vs 3D.
  8. Integración con el pipeline del comando /v.
  9. Enrutamiento en ChronoVideoSynthesizer.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_h3_video_engine import (
    MiniMaxH3Config,
    MiniMaxH3FlowMatcher,
    MiniMaxH3DiTModel,
    TardisH3TiledDecoder,
    TardisH3NativeAudioCodec,
    FastH3Pipeline,
    get_h3_pipeline,
    render_h3_video
)
from tardis_v_engine.src.evaluator_nn import TARDISVisualEvaluator, get_similarity_score
from tardis_v_engine.src.pipeline import VCommandPipeline
from core.chronovision_engine import ChronoVideoSynthesizer


class TestTardisH3VideoEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = MiniMaxH3Config(
            video_channels=24,
            audio_channels=32,
            spatial_downsample=8,
            audio_sample_rate=32000,
            default_steps=6,
            tile_size=32
        )
        cls.pipeline = FastH3Pipeline(cls.config)

    def test_01_h3_config_specifications(self):
        """Verifica que la configuración respete las especificaciones clave de MiniMax H3."""
        cfg = self.config
        self.assertEqual(cfg.video_channels, 24, "MiniMax H3 debe emplear 24 canales latentes de video")
        self.assertEqual(cfg.audio_channels, 32, "MiniMax H3 debe emplear 32 canales latentes de audio")
        self.assertEqual(cfg.audio_sample_rate, 32000, "Audio estéreo nativo H3 debe ser 32 kHz")
        self.assertIn(cfg.flow_solver, ["euler", "midpoint", "heun_ancestral"])
        self.assertGreater(cfg.cfg_scale, 1.0)

    def test_02_flow_matcher_solvers(self):
        """Valida los solucionadores numéricos ODE para Flow Matching."""
        matcher = MiniMaxH3FlowMatcher(self.config)
        sched = matcher.get_time_schedule(steps=6)
        self.assertEqual(len(sched), 7)
        self.assertAlmostEqual(sched[0], 0.0)
        self.assertAlmostEqual(sched[-1], 1.0)

        # Probar paso de Euler
        x0 = np.ones((2, 24, 8, 8), dtype=np.float32)
        v = np.ones_like(x0) * 0.5
        x_next = matcher.euler_step(x0, v, dt=0.1)
        self.assertEqual(x_next.shape, x0.shape)
        self.assertAlmostEqual(float(x_next[0, 0, 0, 0]), 1.05)

        # Probar paso Midpoint RK2
        def dummy_v(x, t):
            return -0.2 * x

        x_mid = matcher.midpoint_step(x0, t=0.0, dt=0.1, velocity_fn=dummy_v)
        self.assertEqual(x_mid.shape, x0.shape)
        self.assertLess(float(x_mid[0, 0, 0, 0]), float(x0[0, 0, 0, 0]))

        # Probar paso Heun Ancestral
        x_heun = matcher.heun_ancestral_step(x0, t=0.0, dt=0.1, velocity_fn=dummy_v, stochastic_ratio=0.0)
        self.assertEqual(x_heun.shape, x0.shape)

    def test_03_dit_velocity_prediction(self):
        """Verifica la predicción conjunta de velocidades con atención cruzada Audio-Visual."""
        dit = MiniMaxH3DiTModel(self.config)
        T, H_l, W_l = 4, 16, 16
        L_a = 20
        z_v = np.random.randn(T, 24, H_l, W_l).astype(np.float32)
        z_a = np.random.randn(L_a, 32).astype(np.float32)

        context = {
            "prompt": "Quantum Field Theory and Syntropy",
            "audio_frequencies": [432.0, 528.0]
        }

        v_video, v_audio = dit.predict_velocity(z_v, z_a, t=0.5, context=context)
        self.assertEqual(v_video.shape, z_v.shape)
        self.assertEqual(v_audio.shape, z_a.shape)
        self.assertFalse(np.isnan(v_video).any())
        self.assertFalse(np.isnan(v_audio).any())

    def test_04_tiled_decoder_rgb(self):
        """Verifica la decodificación por teselas a resolución completa RGB."""
        decoder = TardisH3TiledDecoder(self.config)
        z_frame = np.random.randn(24, 16, 24).astype(np.float32)
        rgb_out = decoder.decode_frame_latents(
            z_frame=z_frame,
            target_height=360,
            target_width=640,
            hdr=True
        )
        self.assertEqual(rgb_out.shape, (360, 640, 3))
        self.assertEqual(rgb_out.dtype, np.uint8)
        self.assertGreaterEqual(rgb_out.min(), 0)
        self.assertLessEqual(rgb_out.max(), 255)

    def test_05_native_audio_codec_synthesis(self):
        """Verifica la síntesis acústica de 32 canales a audio estéreo 32 kHz."""
        codec = TardisH3NativeAudioCodec(self.config)
        L_a = 50
        z_audio = np.random.randn(L_a, 32).astype(np.float32)
        pcm_out, sr = codec.decode_audio_latents(z_audio, duration_sec=1.0, target_sr=32000)

        self.assertEqual(sr, 32000)
        self.assertEqual(pcm_out.shape, (32000, 2), "Debe ser estéreo con 32000 muestras para 1 segundo")
        self.assertEqual(pcm_out.dtype, np.int16)
        self.assertGreater(np.max(np.abs(pcm_out)), 500, "El audio no debe ser silencioso")

    def test_06_fast_h3_pipeline_full_synthesis(self):
        """Ejecuta síntesis completa FastH3 y valida los flujos MP4 de video y audio."""
        out_mp4, meta = self.pipeline.generate_video_and_audio(
            prompt="Entrelazamiento Cuantico ER=EPR Unit Test",
            duration_sec=0.5,
            fps=24,
            width=320,
            height=240,
            steps=4,
            output_prefix="test_h3"
        )
        self.assertTrue(out_mp4.exists(), f"El video generado debe existir: {out_mp4}")
        self.assertGreater(out_mp4.stat().st_size, 5000, "El video debe tener un tamaño válido")

        # Inspección con ffprobe
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "stream=index,codec_name,codec_type,width,height,sample_rate,channels",
            "-of", "json",
            str(out_mp4)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(res.stdout)
        streams = probe_data.get("streams", [])

        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        self.assertIsNotNone(v_stream, "El MP4 debe contener una pista de video")
        self.assertIsNotNone(a_stream, "El MP4 debe contener una pista de audio nativo")
        self.assertEqual(int(v_stream["width"]), 320)
        self.assertEqual(int(v_stream["height"]), 240)
        self.assertEqual(int(a_stream["sample_rate"]), 32000, "La tasa de muestreo del audio debe ser 32 kHz")
        self.assertEqual(int(a_stream["channels"]), 2, "La pista de audio debe ser estéreo")

        # Limpiar archivo de prueba
        if out_mp4.exists():
            out_mp4.unlink()

    def test_07_evaluator_nn(self):
        """Verifica el funcionamiento del evaluador perceptual visual."""
        evaluator = TARDISVisualEvaluator()
        img_a = np.full((128, 128, 3), 120, dtype=np.uint8)
        img_b = np.full((128, 128, 3), 125, dtype=np.uint8)
        score = evaluator.evaluate_similarity(img_a, img_b)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreater(score, 0.70, "Imágenes similares deben tener un score alto")

    def test_08_v_pipeline_integration(self):
        """Verifica la abstracción de contexto y generación del comando /v con H3."""
        v_pipe = VCommandPipeline("Atractor de Lorenz")
        ctx = v_pipe.abstract_context()
        self.assertEqual(ctx["concept"], "Lorenz Strange Attractor & Deterministic Chaos")
        self.assertIn("sigma", ctx["formula_latex"])
        self.assertEqual(len(ctx["color_palette"]), 3)

        sketch_path = v_pipe.generate_sketch(ctx)
        self.assertTrue(Path(sketch_path).exists())

        model_path, preview_path = v_pipe.generate_3d_model(ctx, sketch_path, iteration=0)
        self.assertTrue(Path(model_path).exists())
        self.assertTrue(Path(preview_path).exists())

        score = v_pipe.evaluate_3d_shapes(preview_path, sketch_path)
        self.assertGreater(score, 0.5)

    def test_09_chronovision_video_routing(self):
        """Verifica que ChronoVideoSynthesizer enrute solicitudes 'h3' hacia MiniMax H3."""
        synth = ChronoVideoSynthesizer()
        result = synth.render_dynamic_video(
            video_type="h3_quantum_wormhole",
            duration_sec=0.5,
            fps=24,
            width=320,
            height=240
        )
        self.assertTrue(result.ok)
        self.assertIn("MiniMax-H3", result.title)
        self.assertIsNotNone(result.file_path)
        self.assertTrue(Path(result.file_path).exists())
        # Limpiar
        if Path(result.file_path).exists():
            Path(result.file_path).unlink()


if __name__ == "__main__":
    unittest.main()
