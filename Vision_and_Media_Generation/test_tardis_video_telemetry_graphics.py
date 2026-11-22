"""
tests/test_tardis_video_telemetry_graphics.py
=============================================
Valida la actualización integral de animaciones 3D y gráficos de datos vivos de TARDIS
para el pipeline de video respuestas en Telegram (4K UHD @ 60 FPS y videonotas 1024x1024).
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.character_3d_renderer import Character3DRenderer
from core.speaking_video_generator import SpeakingVideoGenerator
from core.tardis_telemetry_snapshot import (
    _sanitize_text,
    collect_tardis_snapshot,
    default_snapshot,
    format_caption_telemetry,
    resolve_font_path,
    summarize_snapshot,
)
from core.video_pipeline_4k import (
    HudRenderer,
    compute_vocal_state,
    extract_audio_features,
    render_video_4k,
)


class TestTardisVideoTelemetryGraphics(unittest.TestCase):
    def test_01_snapshot_structure_and_aegis_sanitization(self):
        snap = default_snapshot()
        for key in (
            "core", "visual_manifest", "causal", "cognitive",
            "vault", "aegis", "hardware", "rf_radar",
            "atmospheric", "music", "subsystems",
        ):
            self.assertIn(key, snap)

        # Sanitización AEGIS: sin nombre confidencial ni versión legacy v26.4
        cleaned = _sanitize_text("TARDIS v26.4 · prueba")
        self.assertNotIn("v26", cleaned.lower())

        summary = summarize_snapshot(snap)
        self.assertIn("psi", summary)
        self.assertIn("aegis_score", summary)
        cap = format_caption_telemetry(summary)
        self.assertIn("Ψ", cap)
        self.assertIn("AEGIS", cap)

        # Verificar resolución de fuentes TrueType en el sistema
        self.assertIsNotNone(resolve_font_path("mono_bold"))
        self.assertIsNotNone(resolve_font_path("sans_bold"))

    def test_02_character_3d_renderer_manifest_and_entities(self):
        snap = default_snapshot()
        snap["causal"]["q_topo"] = 6
        snap["aegis"]["score"] = 92
        snap["hardware"]["cpu_temp_c"] = 66.0
        snap["visual_manifest"]["palette"]["primary"] = "#00f0ff"
        snap["visual_manifest"]["palette"]["field"] = "#00ff88"

        renderer = Character3DRenderer(
            quality="medium",
            manifest=snap["visual_manifest"],
            telemetry=snap,
        )
        part_names = set(renderer.index.keys())
        self.assertIn("time_core", part_names)
        self.assertIn("oct_edge_0", part_names)
        self.assertIn("oct_edge_11", part_names)
        self.assertIn("aegis_ring", part_names)
        self.assertIn("aegis_hex_0", part_names)
        self.assertIn("thermal_seg_0", part_names)
        self.assertIn("soliton_0", part_names)
        self.assertIn("astrolabe_outer", part_names)

        st1 = compute_vocal_state(0.2, [], 3.0, audio_rms=0.25, audio_bands=[0.4] * 16)
        st2 = compute_vocal_state(1.1, [], 3.0, audio_rms=0.85, audio_bands=[0.9] * 16)
        f1 = renderer.render_frame(0.2, 640, 360, st1, char_scale=0.78, center=(0.5, 0.42)).copy()
        f2 = renderer.render_frame(1.1, 640, 360, st2, char_scale=0.78, center=(0.5, 0.42)).copy()
        self.assertEqual(f1.shape, (360, 640, 3))
        self.assertEqual(f1.dtype, np.uint8)
        # Los cuadros en tiempos distintos deben animarse visiblemente
        self.assertGreater(float(np.mean(np.abs(f1.astype(np.float32) - f2.astype(np.float32)))), 1.0)

    def test_03_hud_renderer_live_data_graphics(self):
        snap = default_snapshot()
        snap["vault"]["total_events"] = 5490
        snap["vault"]["hierarchical_epochs"] = 2997
        snap["subsystems"].update({"online": 34, "degraded": 3, "offline": 1, "total": 38})
        snap["atmospheric"].update({
            "available": True, "temperature_c": 29.8,
            "apparent_temperature_c": 34.0, "relative_humidity_pct": 62,
            "surface_pressure_hpa": 1013.1, "wind_speed_kmh": 9.7,
            "weather_description": "Mayormente Despejado",
        })
        snap["music"].update({"playing": True, "media_title": "Sons of War", "progress": 65.0})

        hud = HudRenderer(1920, 1080, title="TARDIS · MENSAJE SOBERANO", telemetry=snap)
        self.assertTrue(hud.wide)
        for geom_key in ("radar", "psi_wave", "akashic_bars", "entropy_spark", "gauges", "hw_curve", "rf_radar", "audio_vu", "flux_paths"):
            self.assertIn(geom_key, hud._geom)

        lines = [{"text": "Un placer, soy TARDIS asistente de inteligencia artificial.", "start": 0.0, "end": 3.0}]
        st1 = compute_vocal_state(0.3, [], 3.0, audio_rms=0.35, audio_bands=[0.3 + 0.04 * i for i in range(16)])
        st2 = compute_vocal_state(1.4, [], 3.0, audio_rms=0.88, audio_bands=[0.8 - 0.03 * i for i in range(16)])

        bg1 = np.full((1080, 1920, 3), 6, dtype=np.uint8)
        bg2 = np.full((1080, 1920, 3), 6, dtype=np.uint8)
        out1 = hud.composite(bg1, 0.3, lines, st1)
        out2 = hud.composite(bg2, 1.4, lines, st2)

        # Verificar que las alas izquierda y derecha contienen gráficos reales (no negro plano)
        left_mean = float(out1[250:780, 60:460].mean())
        right_mean = float(out1[250:780, 1460:1860].mean())
        self.assertGreater(left_mean, 12.0)
        self.assertGreater(right_mean, 12.0)
        # Verificar animación en los gráficos entre t=0.3 y t=1.4
        self.assertGreater(float(np.mean(np.abs(out1.astype(np.float32) - out2.astype(np.float32)))), 0.3)

    def test_04_audio_feature_extraction_and_4k_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            wav = tmp_p / "tone.wav"
            mp4 = tmp_p / "out_720p.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=520:duration=1.2", str(wav)],
                check=True, capture_output=True,
            )
            env, bands = extract_audio_features(wav, total_frames=36, fps=30)
            self.assertIsNotNone(env)
            self.assertIsNotNone(bands)
            self.assertEqual(len(env), 36)
            self.assertEqual(len(bands), 36)
            self.assertEqual(len(bands[0]), 16)
            self.assertGreater(max(env), 100)

            snap = default_snapshot()
            res = render_video_4k(
                audio_path=wav,
                word_timings=[{"word": "TARDIS", "start": 0.0, "end": 1.1, "duration": 1.1, "syllables": 2, "target_open": 0.75, "target_width": 1.0}],
                duration=1.0,
                output_path=mp4,
                width=1280,
                height=720,
                fps=30,
                quality="low",
                workers=1,
                telemetry=snap,
            )
            self.assertTrue(res["ok"], res.get("error"))
            self.assertTrue(res.get("audio_reactive"))
            self.assertIn("telemetry_summary", res)
            self.assertTrue(mp4.is_file() and mp4.stat().st_size > 5000)

    def test_05_telegram_bridge_passes_real_dimensions_and_tardis_caption(self):
        from core.telegram_bridge import TelegramBridge

        bridge = TelegramBridge.__new__(TelegramBridge)
        bridge.config = {"bot_token": "REDACTED", "admin_chat_id": 12345, "allowed_chats": [12345]}
        bridge.video_delivery_type = "video"
        bridge.send_chat_action = MagicMock()

        mock_v = {
            "ok": True,
            "video_bytes": b"ftypmp42" + b"\x00" * 128,
            "duration": 5.0,
            "width": 3840,
            "height": 2160,
            "fps": 60,
            "telemetry_summary": {"psi": 1.0, "aegis_score": 88, "subsystems_online": 34, "subsystems_total": 38, "cpu_temp_c": 65.0},
        }
        with patch("core.speaking_video_generator.SpeakingVideoGenerator.generate_speaking_video", return_value=mock_v), \
             patch.object(bridge, "send_video", return_value={"ok": True}) as mock_sv:
            out = bridge.send_reply_with_video("Telemetría sincronizada.", chat_id=12345)
            self.assertTrue(out.get("ok"))
            mock_sv.assert_called_once()
            _, kw = mock_sv.call_args
            self.assertEqual(kw["width"], 3840)
            self.assertEqual(kw["height"], 2160)
            self.assertTrue(kw["supports_streaming"])
            self.assertIn("TARDIS", kw["caption"])
            self.assertIn("AEGIS 88/100", kw["caption"])
            self.assertNotIn("**GIA**", kw["caption"])


if __name__ == "__main__":
    unittest.main()
