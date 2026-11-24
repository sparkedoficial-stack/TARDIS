import base64
import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import AioHTTPTestCase
from PIL import Image, ImageDraw

from core.telegram_live_call_server import (
    build_live_videocall_url,
    create_app,
    sign_call_token,
)
from core.videocall_vision_engine import (
    SceneMemory,
    VideoCallVisionEngine,
    is_visual_question,
    sanitize_vlm_caption,
)


def _make_sample_jpeg(color=(30, 90, 180), size=(320, 240)) -> bytes:
    im = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(im)
    draw.rectangle([80, 60, 240, 190], fill=(220, 70, 50))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class TestVideoCallVisionEngineUnit(unittest.TestCase):
    def test_visual_question_detection(self):
        self.assertTrue(is_visual_question("¿Qué ves ahora mismo en mi cámara?"))
        self.assertTrue(is_visual_question("Mira esto que tengo en mi mano"))
        self.assertTrue(is_visual_question("¿Cómo me veo hoy?"))
        self.assertTrue(is_visual_question("Lee esto por favor"))
        self.assertTrue(is_visual_question("What do you see right now?"))
        self.assertFalse(is_visual_question("¿Qué hora es en Tokio?"))
        self.assertFalse(is_visual_question("Explícame la relatividad general"))

    def test_sanitize_vlm_caption_deduplicates_loops(self):
        noisy = "<think>razonamiento interno</think>Veo una persona, veo una persona, veo una persona, veo una persona frente al monitor."
        clean = sanitize_vlm_caption(noisy)
        self.assertNotIn("<think>", clean)
        self.assertIn("frente al monitor", clean)

    def test_fast_frame_telemetry_and_motion_detection(self):
        eng = VideoCallVisionEngine()
        scene = SceneMemory()

        f1 = _make_sample_jpeg(color=(15, 20, 35))
        t1 = eng.inspect_frame_fast(f1, scene, source="camera")
        self.assertEqual(t1.width, 320)
        self.assertEqual(t1.height, 240)
        self.assertEqual(scene.frames_received, 1)
        self.assertTrue(scene.needs_fresh_vlm())

        # Registrar observación VLM y verificar prompt context
        scene.record_vlm_observation("Un rectángulo rojo sobre fondo azul oscuro.", source="camera", elapsed_ms=1400)
        self.assertFalse(scene.needs_fresh_vlm(max_age_sec=10.0))
        ctx = scene.build_prompt_context()
        self.assertIn("VISIÓN EN VIVO DE VIDEOLLAMADA", ctx)
        self.assertIn("Un rectángulo rojo sobre fondo azul oscuro.", ctx)

        # Un fotograma radicalmente distinto dispara motion_score significativo
        f2 = _make_sample_jpeg(color=(230, 235, 240))
        t2 = eng.inspect_frame_fast(f2, scene, source="camera")
        self.assertGreater(t2.motion_score, 0.2)
        self.assertTrue(scene.significant_motion_since_vlm)

    def test_build_live_videocall_url(self):
        url = build_live_videocall_urlREDACTED_PHONE, "Arquitecto")
        if url:
            self.assertIn("/tg-call/video?ct=", url)


class TestVideoCallHTTPAndWebSocket(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_videocall_routes_and_health(self):
        resp = await self.client.request("GET", "/tg-call/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["video_call_ready"])
        self.assertIn("vlm_model", data)

        # Token inválido rechazado
        bad = await self.client.request("GET", "/tg-call/video?ct=invalido.00")
        self.assertEqual(bad.status, 403)

        # Token válido en /tg-call/video y /tg-videocall
        ct = sign_call_tokenREDACTED_PHONE, "Arquitecto")
        for path in (f"/tg-call/video?ct={ct}", f"/tg-videocall?ct={ct}", "/videollamada"):
            ok = await self.client.request("GET", path)
            self.assertEqual(ok.status, 200, f"Fallo cargando {path}")
            html = await ok.text()
            self.assertIn("INICIAR VIDEOLLAMADA EN VIVO", html)
            self.assertIn("avatarCanvas", html)
            self.assertIn("localVideo", html)
            self.assertIn("¿Qué ves?", html)
            self.assertIsNotNone(re.search(r'const INITIAL_CT = "[^"]+"', html))

    async def test_videocall_websocket_full_lifecycle(self):
        ct = sign_call_tokenREDACTED_PHONE, "Arquitecto")
        srv = self.app["server"]
        sample_b64 = base64.b64encode(_make_sample_jpeg()).decode("ascii")

        async def _fake_vlm(raw_bytes, question="", source="camera", timeout_sec=38.0):
            return {
                "ok": True,
                "description": "Se observa al Arquitecto frente a su estación de trabajo con iluminación óptima.",
                "model": "qwen3-vl:2b-instruct",
                "endpoint": "http://127.0.0.1:11435",
                "source": source,
                "elapsed_ms": 120,
            }

        async def _fake_stream(*args, **kwargs):
            yield "Te veo perfectamente en videollamada, Arquitecto."

        with patch.object(srv.vision, "analyze_frame_vlm", side_effect=_fake_vlm), \
             patch.object(srv.engine, "synthesize_mp3", new=AsyncMock(return_value=b"ID3_fake_mp3")), \
             patch("core.telegram_live_call_server.stream_llm_for_call", side_effect=_fake_stream), \
             patch("core.telegram_live_call_server.notify_telegram_call_ended", new=AsyncMock()):

            async with self.client.ws_connect(f"/tg-videocall/ws?ct={ct}") as ws:
                await ws.send_json({
                    "type": "hello",
                    "ct": ct,
                    "mode": "video",
                    "video_enabled": True,
                    "reconnect": True,
                })

                ready = await ws.receive_json(timeout=5)
                self.assertEqual(ready["type"], "call_ready")
                self.assertTrue(ready["video_supported"])
                self.assertEqual(ready["mode"], "video")
                self.assertTrue(ready["can_view_host_screen"])

                # Enviar fotograma en vivo y comprobar telemetría óptica + análisis VLM
                await ws.send_json({
                    "type": "video_frame",
                    "jpeg_b64": sample_b64,
                    "source": "camera",
                    "analyze_now": True,
                })

                got_telemetry = False
                got_vision = False
                for _ in range(8):
                    msg = await ws.receive_json(timeout=5)
                    if msg.get("type") == "vision_telemetry":
                        got_telemetry = True
                        self.assertEqual(msg["width"], 320)
                        self.assertEqual(msg["height"], 240)
                    elif msg.get("type") == "vision_update":
                        got_vision = True
                        self.assertIn("Arquitecto", msg["description"])
                    if got_telemetry and got_vision:
                        break
                self.assertTrue(got_telemetry)
                self.assertTrue(got_vision)

                # Turno conversacional enriquecido por la visión viva
                await ws.send_json({"type": "text_turn", "text": "¿Cómo me veo?", "turn_id": 1})
                got_delta = False
                got_done = False
                for _ in range(12):
                    raw_msg = await ws.receive(timeout=5)
                    if raw_msg.type.name == "TEXT":
                        payload = json.loads(raw_msg.data)
                        if payload.get("type") == "assistant_delta":
                            got_delta = True
                        elif payload.get("type") == "turn_done":
                            got_done = True
                            self.assertIn("videollamada", payload.get("full_text", "").lower())
                            break
                self.assertTrue(got_delta)
                self.assertTrue(got_done)

                # Colgar videollamada limpiamente
                await ws.send_json({"type": "hangup", "duration_sec": 12, "mode": "video"})


class TestTelegramBridgeVideoCallCommands(unittest.TestCase):
    def test_videollamada_command_and_natural_language(self):
        import tempfile
        from core.telegram_bridge import TelegramBridge

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "tg_cfg.json"
            cfg_path.write_text(json.dumps({
                "enabled": False,
                "bot_token": "REDACTED",
                "admin_chat_id": REDACTED_PHONE,
                "allowed_chats": [REDACTED_PHONE],
                "allow_public_chat": True,
            }), encoding="utf-8")
            bridge = TelegramBridge(config_path=cfg_path)
            chat_id = REDACTED_PHONE

            with patch.object(bridge, "send_message") as mock_msg, \
                 patch.object(bridge, "synthesize_speech", return_value=b"OggS_fake"), \
                 patch.object(bridge, "send_voice") as mock_voice, \
                 patch.object(bridge, "prioritize_system_for_telegram_call"), \
                 patch.object(bridge, "set_system_priority"):

                bridge._handle_incoming_text(chat_id, "/videollamada", "Arquitecto")
                self.assertIn(chat_id, bridge.active_calls)
                self.assertIn(chat_id, bridge.active_video_calls)
                mock_msg.assert_called()
                self.assertIn("VIDEOLLAMADA ENTRANTE DE TARDIS", mock_msg.call_args.args[0])
                mock_voice.assert_called()

                bridge._handle_incoming_text(chat_id, "/colgar", "Arquitecto")
                self.assertNotIn(chat_id, bridge.active_video_calls)
                self.assertNotIn(chat_id, bridge.active_calls)

            with patch.object(bridge, "start_video_call") as mock_vc:
                bridge._handle_incoming_text(chat_id, "TARDIS hazme una videollamada ahora", "Arquitecto")
                mock_vc.assert_called_once_with(chat_id, user_name="Arquitecto")


if __name__ == "__main__":
    unittest.main()
