"""
Pruebas integrales de validación soberana para capacidades de animación 2D y 3D en TARDIS.
Verifica generación procedural MP4, aceleración FFmpeg, ChronoVision y despacho en Telegram.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.render_3d_engine import Render3DEngine, get_render_3d_engine
from core.chronovision_engine import ChronoVisionEngine, get_chronovision_engine
from core.telegram_bridge import TelegramBridge, DEFAULT_CONFIG


class TestTardisAnimations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.render_engine = get_render_3d_engine()
        cls.chrono_engine = get_chronovision_engine()

    def test_01_3d_mesh_animation_dna(self):
        """Verifica generación de animación orbital MP4 para el modelo 3D de ADN con return_bytes=True."""
        mesh = self.render_engine.get_mesh("dna")
        self.assertIsNotNone(mesh)
        mp4_bytes = self.render_engine.render_mesh_animation(
            mesh,
            frames=24,
            fps=24,
            width=320,
            height=320,
            style="hologram",
            show_hud=True,
            return_bytes=True
        )
        self.assertIsNotNone(mp4_bytes)
        self.assertGreater(len(mp4_bytes), 1000)
        self.assertIn(b"ftyp", mp4_bytes[:32])

    def test_02_3d_animate_model_atom(self):
        """Verifica animate_model directo para modelo Bohr Atom con retorno estructurado (dict)."""
        anim_res = self.render_engine.animate_model(
            "atom",
            frames=24,
            fps=24,
            width=320,
            height=320,
            style="blueprint"
        )
        self.assertIsInstance(anim_res, dict)
        self.assertTrue(anim_res.get("ok"))
        mp4_bytes = anim_res.get("bytes_data")
        self.assertIsNotNone(mp4_bytes)
        self.assertGreater(len(mp4_bytes), 1000)
        self.assertIn(b"ftyp", mp4_bytes[:32])

    def test_03_chronovision_2d_animation_galaxy(self):
        """Verifica generación de animación 2D diferencial de galaxia espiral."""
        res = self.chrono_engine.render_animation("galaxia", is_3d=False)
        self.assertTrue(res.ok)
        self.assertEqual(res.media_type, "animation")
        self.assertIsNotNone(res.bytes_data)
        self.assertGreater(len(res.bytes_data), 1000)
        self.assertIn(b"ftyp", res.bytes_data[:32])

    def test_04_chronovision_2d_animation_temporal_clock(self):
        """Verifica animación de reloj temporal Gallifreyan de la TARDIS."""
        res = self.chrono_engine.render_animation("reloj temporal", is_3d=False)
        self.assertTrue(res.ok)
        self.assertEqual(res.media_type, "animation")
        self.assertIsNotNone(res.bytes_data)
        self.assertGreater(len(res.bytes_data), 1000)

    def test_05_chronovision_2d_animation_sacred_geometry(self):
        """Verifica animación de geometría sagrada y cubo de Metatrón."""
        res = self.chrono_engine.render_animation("metatron", is_3d=False)
        self.assertTrue(res.ok)
        self.assertEqual(res.media_type, "animation")
        self.assertIsNotNone(res.bytes_data)
        self.assertGreater(len(res.bytes_data), 1000)

    def test_06_chronovision_3d_animation_delegation(self):
        """Verifica delegación automática de ChronoVision a Render3DEngine para modelos 3D."""
        res = self.chrono_engine.render_animation("tesseract", is_3d=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.media_type, "animation")
        self.assertIsNotNone(res.bytes_data)
        self.assertGreater(len(res.bytes_data), 1000)

    def test_07_chronovision_process_request_with_preference(self):
        """Verifica que process_request con prefer_animation=True produzca animación."""
        res = self.chrono_engine.process_request("dibuja la flor de la vida", prefer_animation=True)
        self.assertTrue(res.ok)
        self.assertEqual(res.media_type, "animation")
        self.assertIsNotNone(res.bytes_data)

    def test_08_spontaneous_inspiration_prefers_animation(self):
        """Verifica que el generador espontáneo de arte respete prefer_animation=True."""
        item, res = self.chrono_engine.genesis.get_spontaneous_inspiration(prefer_animation=True)
        self.assertTrue(res.ok)
        self.assertIn(res.media_type, ("animation", "video"))
        self.assertIsNotNone(res.bytes_data)

    def test_09_telegram_bridge_config_defaults(self):
        """Verifica que la configuración de Telegram tenga soporte activo para animaciones a 240 FPS / 60 FPS 4K HDR."""
        self.assertIn("animations_enabled", DEFAULT_CONFIG)
        self.assertIn("prefer_animations_over_still_images", DEFAULT_CONFIG)
        self.assertIn("animation_delivery_type", DEFAULT_CONFIG)
        self.assertIn("animation_render_fps", DEFAULT_CONFIG)
        self.assertIn("animation_telegram_fps", DEFAULT_CONFIG)
        self.assertIn("animation_resolution", DEFAULT_CONFIG)
        self.assertIn("animation_hdr_enabled", DEFAULT_CONFIG)
        self.assertTrue(DEFAULT_CONFIG["animations_enabled"])
        self.assertTrue(DEFAULT_CONFIG["prefer_animations_over_still_images"])
        self.assertEqual(DEFAULT_CONFIG["animation_render_fps"], 240)
        self.assertEqual(DEFAULT_CONFIG["animation_telegram_fps"], 60)
        self.assertEqual(DEFAULT_CONFIG["animation_resolution"], "4K_HDR")
        self.assertEqual(DEFAULT_CONFIG["animation_width"], 3840)
        self.assertEqual(DEFAULT_CONFIG["animation_height"], 2160)
        self.assertTrue(DEFAULT_CONFIG["animation_hdr_enabled"])

    @patch("requests.post")
    def test_10_telegram_send_animation(self, mock_post):
        """Verifica que send_animation envíe la petición correcta al endpoint sendAnimation de Telegram."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 99999}}
        mock_post.return_value = mock_resp

        # Instanciar bridge sin arranque de red
        bridge = TelegramBridge.__new__(TelegramBridge)
        bridge.config = {
            "bot_token": "TEST_TOKEN_12345",
            "admin_chat_id": 7153384115,
            "allowed_chats": [7153384115],
            "prefer_animations_over_still_images": True,
            "animation_delivery_type": "animation",
            "animation_render_fps": 240,
            "animation_telegram_fps": 60,
            "animation_width": 3840,
            "animation_height": 2160,
            "animation_hdr_enabled": True
        }
        bridge.animation_render_fps = 240
        bridge.animation_telegram_fps = 60
        bridge.animation_width = 3840
        bridge.animation_height = 2160
        bridge.animation_hdr_enabled = True
        bridge._print_outgoing_response = MagicMock()

        sample_mp4 = b"ftypisom" + b"\x00" * 200
        res = bridge.send_animation(
            sample_mp4,
            caption="Test Animation",
            chat_id=7153384115,
            duration=3,
            width=3840,
            height=2160
        )

        self.assertTrue(res.get("ok"))
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("sendAnimation", args[0])
        self.assertEqual(kwargs["data"]["chat_id"], 7153384115)
        self.assertIn("animation", kwargs["files"])

    def test_11_render_default_240fps_4k_hdr(self):
        """Verifica que el renderizado de animación por defecto se ejecute a 240 FPS en 4K HDR y se portee a 60 FPS."""
        # 1. Motor 3D
        res_3d = self.render_engine.animate_model("atom", frames=24, style="blueprint")
        self.assertEqual(res_3d.get("fps"), 240)
        self.assertEqual(res_3d.get("ported_fps"), 60)
        self.assertTrue(res_3d.get("hdr"))
        self.assertEqual(res_3d.get("width"), 3840)
        self.assertEqual(res_3d.get("height"), 2160)
        self.assertIn("4K HDR", res_3d.get("resolution"))

        # 2. ChronoVision 2D
        res_2d = self.chrono_engine.render_animation("galaxia", is_3d=False, duration_sec=0.5)
        self.assertEqual(res_2d.fps, 240)
        self.assertEqual(res_2d.width, 3840)
        self.assertEqual(res_2d.height, 2160)

    def test_12_transcode_to_telegram_60fps(self):
        """Verifica que transcode_to_telegram_fps adapte videos de 240 FPS a 60 FPS exactos para Telegram."""
        import subprocess
        import tempfile

        bridge = TelegramBridge.__new__(TelegramBridge)
        bridge.config = {
            "bot_token": "TEST_TOKEN",
            "animation_render_fps": 240,
            "animation_telegram_fps": 60,
            "animation_width": 3840,
            "animation_height": 2160,
            "animation_hdr_enabled": True
        }
        bridge.animation_telegram_fps = 60
        bridge.animation_render_fps = 240
        bridge.animation_width = 3840
        bridge.animation_height = 2160
        bridge.animation_hdr_enabled = True

        # Crear video sintético de 1 segundo a 240 FPS
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x320:rate=240",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", f.name
            ], check=True, capture_output=True)
            video_240fps = Path(f.name).read_bytes()

        out_60fps = bridge.transcode_to_telegram_fps(video_240fps, target_fps=60)
        self.assertIsNotNone(out_60fps)
        self.assertGreater(len(out_60fps), 1000)

        # Comprobar framerate con ffprobe
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f_out:
            Path(f_out.name).write_bytes(out_60fps)
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate,avg_frame_rate",
                "-of", "default=noprint_wrappers=1:nokey=1", f_out.name
            ], check=True, capture_output=True, text=True)
            self.assertIn("60/1", probe.stdout)


if __name__ == "__main__":
    unittest.main()
