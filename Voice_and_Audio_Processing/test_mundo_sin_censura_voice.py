"""
tests/test_mundo_sin_censura_voice.py - Pruebas de Voz Continua para Un Mundo Sin Censura
=========================================================================================
Verifica:
  1. Limpieza de texto para locución, extracción de oraciones, filtro de alucinaciones y voces.
  2. Segmentador VAD (`MundoSpeechSegmenter`): emisión de enunciado y detección de Barge-In.
  3. Motor continuo (`MundoContinuousVoiceEngine`): comandos de control por voz y persistencia
     exclusiva en SQLite (`voice_mode=True`).
  4. Endpoints FastAPI REST (`/api/mundo_sin_censura/voice/status`, `/transcribe`, `/tts`)
     con bloqueo estricto de modelo (HTTP 403 ante modelos externos).
  5. WebSocket full-duplex (`/api/mundo_sin_censura/voice/ws`): config, bloqueo 403, turno de
     audio WAV -> STT -> streaming LLM -> audio_chunk TTS -> persistencia SQLite e interrupción.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import threading
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.mundo_sin_censura_chat as mchat
import core.mundo_sin_censura_voice as mvoice


def _tone_pcm_frame(amplitude: float, freq_hz: float = 280.0, sample_rate: int = 16000, frame_ms: int = 30) -> bytes:
    n = int(sample_rate * frame_ms / 1000)
    t = np.arange(n, dtype=np.float32) / float(sample_rate)
    wave_data = np.clip(amplitude * np.sin(2.0 * np.pi * freq_hz * t), -1.0, 1.0)
    return (wave_data * 32767.0).astype(np.int16).tobytes()


def _make_wav_16k(duration_s: float = 0.4, amplitude: float = 0.2) -> bytes:
    n = int(16000 * duration_s)
    t = np.arange(n, dtype=np.float32) / 16000.0
    pcm = (np.clip(amplitude * np.sin(2.0 * np.pi * 320.0 * t), -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)
    return buf.getvalue()


def test_text_cleaning_sentences_hallucinations_and_voice_aliases():
    dirty = "<think>secreto</think>Hola **Arquitecto** [[HW_ACTION:{\"action\":\"psi\"}]] mira ```py\nx=1\n``` listo."
    clean = mvoice.clean_for_mundo_speech(dirty)
    assert "secreto" not in clean
    assert "HW_ACTION" not in clean
    assert "x=1" not in clean
    assert "Hola Arquitecto" in clean

    sent, rest = mvoice.extract_ready_sentence("Hola mundo, todo listo. Seguimos hablando.", is_first=True)
    assert sent == "Hola mundo, todo listo."
    assert rest == "Seguimos hablando."

    assert mvoice.is_hallucination("Subtítulos realizados por la comunidad de Amara.org")
    assert mvoice.is_hallucination("...")
    assert not mvoice.is_hallucination("Hola mundo sin censura")

    assert mvoice.resolve_voice_id("jorge") == "es-MX-JorgeNeural"
    assert mvoice.resolve_voice_id("cortana") == "es-MX-DaliaNeural"
    assert mvoice.normalize_speech_rate(1.1) == "+10%"
    assert mvoice.normalize_speech_rate("+12%") == "+12%"


def test_speech_segmenter_utterance_and_barge_in():
    cfg = mvoice.MundoVoiceConfig(
        vad_aggressiveness=1,
        silence_hold_ms=150,
        min_speech_ms=120,
        barge_in=True,
        barge_in_rms=0.06,
        barge_in_frames=4,
    )
    seg = mvoice.MundoSpeechSegmenter(cfg)
    seg.vad = None  # determinista sobre señal senoidal sintética

    silence = _tone_pcm_frame(0.001)
    speech = _tone_pcm_frame(0.16)

    for _ in range(5):
        out = seg.process_frame(silence, ai_speaking=False)
        assert out["utterance"] is None

    for _ in range(8):
        out = seg.process_frame(speech, ai_speaking=False)
        assert out["utterance"] is None
        assert out["in_speech"] is True

    emitted = None
    for _ in range(8):
        out = seg.process_frame(silence, ai_speaking=False)
        if out["utterance"] is not None:
            emitted = out["utterance"]
            break
    assert emitted is not None
    assert len(emitted) >= cfg.frame_bytes * 6

    # Barge-In durante locución de la IA
    barge_hit = False
    loud = _tone_pcm_frame(0.26)
    for _ in range(6):
        out = seg.process_frame(loud, ai_speaking=True)
        if out["barge_in"]:
            barge_hit = True
            break
    assert barge_hit is True
    assert seg.in_speech is True


def test_continuous_voice_engine_intents_and_direct_turn(tmp_path, monkeypatch):
    store = mchat.MundoSinCensuraChatStore(db_path=tmp_path / "voice_chat.db")
    monkeypatch.setattr(mchat, "_CHAT_STORE", store)

    seen_extra = {}

    class _FakeAgent:
        def inspect_temporal_brain(self, timeout=1.0):
            return {"ready": True}

        def chat_stream(self, messages, **kwargs):
            seen_extra["extra_system"] = kwargs.get("extra_system", "")
            yield "Hola Arquitecto. "
            yield "Voz continua operativa."
            return "Hola Arquitecto. Voz continua operativa."

    cfg = mvoice.MundoVoiceConfig(no_play=True, prefer_api=False, json_stream=False)
    engine = mvoice.MundoContinuousVoiceEngine(cfg)
    ev = threading.Event()

    r_voice = engine.process_user_text("cambia la voz a jorge", ev)
    assert "jorge" in r_voice.lower()
    assert engine.cfg.voice == "es-MX-JorgeNeural"

    r_pause = engine.process_user_text("pausa voz", ev)
    assert engine.paused is True
    assert "pausa" in r_pause.lower()
    assert engine.process_user_text("cualquier cosa ignorada", ev) == ""

    r_resume = engine.process_user_text("reanuda voz", ev)
    assert engine.paused is False
    assert "reactivada" in r_resume.lower()

    with patch.object(mchat, "get_mundo_sin_censura", return_value=_FakeAgent()):
        reply = engine.process_user_text("¿Confirmas conversación continua?", ev)

    assert reply == "Hola Arquitecto. Voz continua operativa."
    assert engine.session_id is not None
    assert "CONVERSACIÓN DE VOZ CONTINUA" in seen_extra.get("extra_system", "")
    sess = store.get_session(engine.session_id)
    assert sess is not None and len(sess["messages"]) == 2
    assert sess["messages"][0]["content"] == "¿Confirmas conversación continua?"
    assert sess["messages"][1]["content"] == "Hola Arquitecto. Voz continua operativa."


def test_fastapi_voice_rest_and_websocket_full_duplex(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server.api import create_app

    store = mchat.MundoSinCensuraChatStore(db_path=tmp_path / "ws_voice.db")
    monkeypatch.setattr(mchat, "_CHAT_STORE", store)

    class _FakeSTT:
        model_size = "base"
        is_loaded = True

        def warmup(self):
            return 0.01

        def transcribe_audio_bytes(self, audio_bytes, *, audio_format="wav", language="es"):
            return ("Hola desde micrófono continuo", 0.12)

    class _FakeAgent:
        def inspect_temporal_brain(self, timeout=1.0):
            return {"ready": True}

        def chat_stream(self, messages, **kwargs):
            yield "Recibido en vivo. "
            yield "Conversación continua lista."
            return "Recibido en vivo. Conversación continua lista."

    app = create_app()
    client = TestClient(app)

    # 1. HTML incluye UI de voz continua
    r_ui = client.get("/mundo-sin-censura")
    assert r_ui.status_code == 200
    assert "btnContinuousVoice" in r_ui.text
    assert "/api/mundo_sin_censura/voice/ws" in r_ui.text

    # 2. Estado de voz
    r_st = client.get("/api/mundo_sin_censura/voice/status")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["model"] == "mundo-sin-censura"
    assert st["continuous_voice"] is True

    # 3. Bloqueo de modelo HTTP 403 en transcribe y tts
    wav_b64 = base64.b64encode(_make_wav_16k()).decode("ascii")
    assert client.post(
        "/api/mundo_sin_censura/voice/transcribe",
        json={"model": "gpt-4o", "audio_base64": wav_b64},
    ).status_code == 403
    assert client.post(
        "/api/mundo_sin_censura/voice/tts",
        json={"model": "deepseek-r1:7b", "text": "Hola"},
    ).status_code == 403

    fake_mp3 = b"ID3FAKE_MP3_STREAM_BYTES"
    with (
        patch.object(mvoice, "get_mundo_stt", return_value=_FakeSTT()),
        patch.object(mvoice, "synthesize_tts_bytes_async", new=AsyncMock(return_value=(fake_mp3, "audio/mpeg"))),
        patch.object(mchat, "get_mundo_sin_censura", return_value=_FakeAgent()),
    ):
        # 4. REST transcribe y TTS válidos
        r_tr = client.post(
            "/api/mundo_sin_censura/voice/transcribe",
            json={"model": "mundo-sin-censura", "audio_base64": wav_b64, "format": "wav"},
        )
        assert r_tr.status_code == 200
        assert r_tr.json()["text"] == "Hola desde micrófono continuo"

        r_tts = client.post(
            "/api/mundo_sin_censura/voice/tts",
            json={"model": "mundo-sin-censura", "text": "Prueba de audio"},
        )
        assert r_tts.status_code == 200
        assert r_tts.content == fake_mp3

        # 5. WebSocket full-duplex continuo
        with client.websocket_connect("/api/mundo_sin_censura/voice/ws") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["model"] == "mundo-sin-censura"

            # Rechazo de modelo externo en config WS
            ws.send_json({"type": "config", "model": "claude-opus"})
            err = ws.receive_json()
            assert err["type"] == "error" and err["code"] == 403

            # Config válida
            ws.send_json({
                "type": "config",
                "model": "mundo-sin-censura",
                "voice": "jorge",
                "lane": "auto",
                "tts_enabled": True,
            })
            ack = ws.receive_json()
            assert ack["type"] == "config_ack"
            assert ack["config"]["voice"] == "es-MX-JorgeNeural"

            # Envío de audio binario WAV 16kHz -> turno completo con streaming + audio_chunk
            ws.send_bytes(_make_wav_16k())
            received = []
            for _ in range(30):
                ev = ws.receive_json()
                received.append(ev)
                if ev["type"] == "done":
                    break

            types = [e["type"] for e in received]
            assert "transcript" in types
            assert "meta" in types
            assert "token" in types
            assert "audio_chunk" in types
            assert "done" in types

            tr_ev = next(e for e in received if e["type"] == "transcript")
            assert tr_ev["text"] == "Hola desde micrófono continuo"
            audio_ev = next(e for e in received if e["type"] == "audio_chunk")
            assert base64.b64decode(audio_ev["data"]) == fake_mp3

            meta_ev = next(e for e in received if e["type"] == "meta")
            sid = meta_ev["session_id"]
            saved_sess = store.get_session(sid)
            assert saved_sess is not None
            assert len(saved_sess["messages"]) == 2
            assert saved_sess["messages"][0]["content"] == "Hola desde micrófono continuo"
            assert "Conversación continua lista." in saved_sess["messages"][1]["content"]

            # Interrupción (Barge-In / manual)
            ws.send_json({"type": "interrupt"})
            intr = ws.receive_json()
            assert intr["type"] == "interrupted"
