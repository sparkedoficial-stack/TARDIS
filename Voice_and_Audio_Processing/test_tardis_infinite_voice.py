import threading
import unittest
from unittest.mock import MagicMock

import numpy as np
from aiohttp.test_utils import AioHTTPTestCase

from core.tardis_infinite_voice import (
    InfiniteVoiceChat,
    InfiniteVoiceConfig,
    SpeechSegmenter,
    extract_ready_sentence,
    is_hallucination,
)
from core.telegram_live_call_server import create_app


def _tone_frame(amplitude: float, freq_hz: float = 280.0, sample_rate: int = 16000, frame_ms: int = 30) -> bytes:
    n = int(sample_rate * frame_ms / 1000)
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    wave = np.clip(amplitude * np.sin(2.0 * np.pi * freq_hz * t), -1.0, 1.0)
    return (wave * 32767.0).astype(np.int16).tobytes()


class TestInfiniteVoiceUnit(unittest.TestCase):
    def test_extract_ready_sentence_and_hallucinations(self):
        sent, rest = extract_ready_sentence("Hola Arquitecto, todo listo. Seguimos.", is_first=True)
        self.assertEqual(sent, "Hola Arquitecto, todo listo.")
        self.assertEqual(rest, "Seguimos.")
        self.assertTrue(is_hallucination("Subtítulos realizados por la comunidad de Amara.org"))
        self.assertTrue(is_hallucination("..."))
        self.assertFalse(is_hallucination("Hola TARDIS"))

    def test_speech_segmenter_utterance_and_barge_in(self):
        cfg = InfiniteVoiceConfig(
            vad_aggressiveness=1,
            silence_hold_ms=150,
            min_speech_ms=120,
            barge_in=True,
            barge_in_rms=0.06,
            barge_in_frames=4,
        )
        seg = SpeechSegmenter(cfg)
        # Disable webrtcvad dependency in deterministic synthetic sine wave test
        seg.vad = None

        silence = _tone_frame(0.001)
        speech = _tone_frame(0.15)

        for _ in range(5):
            out = seg.process_frame(silence, ai_speaking=False)
            self.assertIsNone(out["utterance"])

        for _ in range(8):
            out = seg.process_frame(speech, ai_speaking=False)
            self.assertIsNone(out["utterance"])

        emitted = None
        for _ in range(8):
            out = seg.process_frame(silence, ai_speaking=False)
            if out["utterance"] is not None:
                emitted = out["utterance"]
                break
        self.assertIsNotNone(emitted)
        self.assertGreater(len(emitted), cfg.frame_bytes * 6)

        # Barge-in test during AI playback
        barge_triggered = False
        loud_barge = _tone_frame(0.25)
        for _ in range(6):
            out = seg.process_frame(loud_barge, ai_speaking=True)
            if out["barge_in"]:
                barge_triggered = True
                break
        self.assertTrue(barge_triggered)
        self.assertTrue(seg.in_speech)

    def test_control_intents_and_streaming_turn(self):
        cfg = InfiniteVoiceConfig(no_play=True, greeting=False, fresh=True, daemon=True)
        chat = InfiniteVoiceChat(cfg)
        chat._vault = None

        ev = threading.Event()
        # Voice change
        r_voice = chat.process_user_text("cambia la voz a jorge", ev)
        self.assertIn("jorge", r_voice.lower())
        self.assertEqual(chat.tts.voice, "es-MX-JorgeNeural")

        # Pause & resume
        r_pause = chat.process_user_text("tardis pausa", ev)
        self.assertTrue(chat.paused)
        self.assertIn("pausa", r_pause.lower())
        self.assertEqual(chat.process_user_text("ruido cualquiera", ev), "")
        r_resume = chat.process_user_text("tardis despierta", ev)
        self.assertFalse(chat.paused)
        self.assertIn("reactivada", r_resume.lower())

        # Streaming LLM turn
        chat.stream_llm = MagicMock(return_value=iter(["Hola Arquitecto. ", "Operando en modo infinito."]))
        reply = chat.process_user_text("¿Cómo estás?", ev)
        self.assertEqual(reply, "Hola Arquitecto. Operando en modo infinito.")
        self.assertEqual(chat.turn_count, 1)
        self.assertEqual(len(chat.history), 2)


class TestVozWebEndpoint(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_voz_local_page_and_ws_handshake(self):
        resp = await self.client.request("GET", "/voz")
        self.assertEqual(resp.status, 200)
        html = await resp.text()
        self.assertIn("INICIAR LLAMADA EN VIVO", html)
        self.assertIn("Barge-In", html)

        # Extraer token inicial embebido en el HTML de /voz para validar el WebSocket
        import re
        m = re.search(r'const INITIAL_CT = "([^"]+)"', html)
        self.assertIsNotNone(m)
        ct = m.group(1)

        async with self.client.ws_connect(f"/voz/ws?ct={ct}") as ws:
            await ws.send_json({"type": "hello", "ct": ct, "voice": "es-MX-DaliaNeural", "reconnect": True})
            ready = await ws.receive_json()
            self.assertEqual(ready["type"], "call_ready")
            self.assertEqual(ready["user_name"], "Arquitecto")


if __name__ == "__main__":
    unittest.main()
