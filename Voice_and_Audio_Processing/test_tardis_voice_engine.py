"""
tests/test_tardis_voice_engine.py - Pruebas del Motor Unificado de Voz Local, Dictado y Abstracción
===================================================================================================
Valida:
  1. Preprocesado DSP acústico (remoción DC, pasa-altos 85 Hz, AGC suave y limitador anti-clip).
  2. Silero VAD v6 neural streaming ONNX + AdaptiveSpeechSegmenter (endpointing adaptativo + Barge-In).
  3. DictationNormalizer (correcciones de dominio TARDIS/FTL/KAIJU/Ollama/PipeWire protegiendo
     'buenas tardes', limpieza de muletillas/tartamudeos, puntuación dictada, detección de frase incompleta).
  4. UtteranceCoalescer (fusión fluida de fragmentos entrecortados).
  5. VoiceAbstractionEngine (intenciones, entidades, resolución de anáforas multi-turno,
     modo dictado continuo, comandos instantáneos <15 ms).
  6. SovereignLocalTTS con Piper ONNX real 100% offline (WAV PCM16 22050 Hz + caché LRU).
  7. Endpoints FastAPI `/api/voice/local/*` (status, abstract, tts, transcribe) y WebSocket `/api/voice/local/ws`.
"""

from __future__ import annotations

import base64
import io
import sys
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.tardis_voice_engine as tve


def _sine_pcm(duration_s: float, freq_hz: float = 300.0, amplitude: float = 0.2, sr: int = 16000) -> bytes:
    n = int(sr * duration_s)
    t = np.arange(n, dtype=np.float32) / float(sr)
    sig = np.clip(amplitude * np.sin(2.0 * np.pi * freq_hz * t), -1.0, 1.0)
    return (sig * 32767.0).astype(np.int16).tobytes()


def _pcm_to_wav(pcm: bytes, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm)
    return buf.getvalue()


def test_dsp_highpass_and_agc_amplifies_quiet_voice_safely():
    # Señal muy baja (~0.015) con DC offset y componente de baja frecuencia 30 Hz
    n = 16000
    t = np.arange(n, dtype=np.float32) / 16000.0
    quiet_voice = 0.015 * np.sin(2.0 * np.pi * 440.0 * t)
    rumble = 0.08 * np.sin(2.0 * np.pi * 25.0 * t) + 0.05
    raw = (np.clip(quiet_voice + rumble, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    audio_f32, metrics = tve.preprocess_pcm_for_stt(raw)
    assert audio_f32.dtype == np.float32
    assert audio_f32.size == n
    assert abs(float(np.mean(audio_f32))) < 0.01  # DC eliminado
    assert metrics["gain"] > 1.5  # AGC amplificó voz débil
    assert metrics["peak"] <= 0.98  # sin saturación/clipping duro


def test_silero_vad_v6_and_adaptive_segmenter():
    sv = tve.SileroVadStream()
    assert sv.available is True
    # Silencio puro debe dar probabilidad muy baja
    silence_frame = np.zeros(480, dtype=np.int16).tobytes()
    probs = [sv.speech_probability(silence_frame) for _ in range(5)]
    assert max(probs) < 0.25

    # Segmentador determinista (sin Silero/webrtcvad sobre onda sintética)
    cfg = tve.SegmenterConfig(
        silence_hold_ms=150,
        min_speech_ms=120,
        barge_in=True,
        barge_in_rms=0.06,
        barge_in_frames=4,
        use_silero=False,
    )
    seg = tve.AdaptiveSpeechSegmenter(cfg)
    seg.vad = None
    sil = _sine_pcm(0.03, amplitude=0.001)
    vox = _sine_pcm(0.03, amplitude=0.18)

    for _ in range(5):
        assert seg.process_frame(sil)["utterance"] is None
    for _ in range(8):
        out = seg.process_frame(vox)
        assert out["in_speech"] is True
        assert out["utterance"] is None
    emitted = None
    for _ in range(8):
        out = seg.process_frame(sil)
        if out["utterance"] is not None:
            emitted = out["utterance"]
            break
    assert emitted is not None and len(emitted) > 4000

    # Barge-in sostenido
    loud = _sine_pcm(0.03, amplitude=0.28)
    barge = False
    for _ in range(6):
        if seg.process_frame(loud, ai_speaking=True)["barge_in"]:
            barge = True
            break
    assert barge is True


def test_dictation_normalizer_domain_and_anti_false_positives():
    norm = tve.DictationNormalizer()

    # Vocativo "Hola tardes" -> "Hola TARDIS"
    t1, corr1 = norm.normalize("ehh... hola tardes, revisa efe te ele y paipguayer en la ge pe u")
    assert "TARDIS" in t1
    assert "FTL" in t1
    assert "PipeWire" in t1
    assert "GPU" in t1
    assert not t1.lower().startswith("ehh")
    assert len(corr1) >= 3

    # Protección estricta: "Buenas tardes" NO debe cambiarse a "Buenas TARDIS"
    t2, _ = norm.normalize("Buenas tardes, nos vemos en la tarde o más tarde")
    assert "TARDIS" not in t2
    assert "Buenas tardes" in t2

    # Tartamudeo de dictado
    t3, _ = norm.normalize("quiero quiero que revises o llama y güisper")
    assert "quiero quiero" not in t3.lower()
    assert "Ollama" in t3
    assert "Whisper" in t3

    # Puntuación en modo dictado
    t4, _ = norm.normalize("primera idea coma segunda idea punto y aparte nuevo párrafo", dictation_mode=True)
    assert "Primera idea, segunda idea.\n" in t4

    # Detección de frases incompletas y coalescencia
    assert norm.is_incomplete_utterance("Oye TARDIS, explícame sobre") is True
    assert norm.is_incomplete_utterance("¿Qué hora es?") is False
    assert norm.is_incomplete_utterance("Hola") is False

    coal = tve.UtteranceCoalescer(norm, max_wait_s=1.5)
    m1, wait1 = coal.push("Oye TARDIS, explícame sobre")
    assert m1 is None and wait1 is True
    m2, wait2 = coal.push("la física cuántica")
    assert wait2 is False
    assert m2 == "Oye TARDIS, explícame sobre la física cuántica"


def test_voice_abstraction_anaphora_dictation_and_instant_commands():
    eng = tve.VoiceAbstractionEngine()

    # Turno 1: explicación técnica fija el tópico activo
    a1 = eng.abstract("TARDIS explícame cómo funciona la relatividad general")
    assert a1.intent == "technical_explanation"
    assert "relatividad general" in a1.active_topic.lower()
    assert a1.instant_reply is None
    assert a1.latency_ms < 50.0

    # Turno 2: referencia anafórica resuelve explícitamente al tópico anterior
    a2 = eng.abstract("Explícalo más simple y dame un ejemplo de eso")
    assert a2.intent == "followup_refinement"
    assert "relatividad general" in a2.resolved_query.lower()

    # Comando instantáneo de hora
    a3 = eng.abstract("¿Qué hora es?", allow_system_actions=True)
    assert a3.intent == "system_command" and a3.sub_intent == "time"
    assert a3.instant_reply is not None and "Son las" in a3.instant_reply

    # Modo dictado continuo: activar -> dictar -> deshacer -> finalizar
    d1 = eng.abstract("activa modo dictado")
    assert eng.dictation_mode is True
    assert d1.instant_reply and "dictado" in d1.instant_reply.lower()

    d2 = eng.abstract("Primera oración del documento")
    assert d2.intent == "dictation_capture"
    assert d2.instant_reply == ""
    d3 = eng.abstract("Segunda oración de prueba")
    assert len(eng.dictation_buffer) == 2

    eng.abstract("borra lo último")
    assert len(eng.dictation_buffer) == 1

    d_end = eng.abstract("termina dictado")
    assert eng.dictation_mode is False
    assert d_end.action and "Primera oración" in d_end.action["text"]


def test_piper_local_tts_offline_and_speech_preparation():
    prepared = tve.prepare_text_for_speech("<think>oculto</think>CPU a 78°C y 45% en 120ms con **16 GB** ```py\nx=1\n```")
    assert "oculto" not in prepared
    assert "78 grados" in prepared
    assert "45 por ciento" in prepared
    assert "120 milisegundos" in prepared
    assert "16 gigabytes" in prepared
    assert "x=1" not in prepared

    tts = tve.get_sovereign_tts(mode="local")
    assert tts.is_piper_available() is True
    wav_bytes, mime, sr = tts.synthesize_bytes("Hola Arquitecto, prueba local.", voice="es_MX-claude-high", mode="local")
    assert wav_bytes is not None and len(wav_bytes) > 4000
    assert mime == "audio/wav"
    assert wav_bytes[:4] == b"RIFF"
    assert sr == 22050


def test_fastapi_local_voice_endpoints_and_ws():
    from fastapi.testclient import TestClient
    from server.api import create_app

    app = create_app()
    client = TestClient(app)

    r_st = client.get("/api/voice/local/status")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["ok"] is True
    assert st["tts"]["piper_available"] is True
    assert st["vad"]["silero_v6_available"] is True

    r_abs = client.post("/api/voice/local/abstract", json={"text": "Hola tardes, revisa efe te ele"})
    assert r_abs.status_code == 200
    aj = r_abs.json()
    assert "TARDIS" in aj["normalized_text"]
    assert "FTL" in aj["normalized_text"]

    r_tts = client.post("/api/voice/local/tts", json={"text": "Audio local verificado.", "mode": "local"})
    assert r_tts.status_code == 200
    assert r_tts.headers["content-type"].startswith("audio/wav")
    assert r_tts.content[:4] == b"RIFF"

    class _FakeRouter:
        def inspect_temporal_brain_slots(self, timeout=0.15):
            return {"available": True, "free_slots": 2, "total_slots": 2}

        def inspect_voice_ollama_lane(self, timeout=0.25):
            return {"available": True, "model_loaded": True}

        def stream_reply(self, messages, **kwargs):
            return "temporal_brain", iter(["Hola Arquitecto. ", "Conversación local activa."])

    with patch.object(tve, "get_voice_llm_router", return_value=_FakeRouter()):
        with client.websocket_connect("/api/voice/local/ws") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            ws.send_json({"type": "config", "tts_mode": "local", "tts_enabled": True})
            ack = ws.receive_json()
            assert ack["type"] == "config_ack"
            ws.send_json({"type": "text", "text": "Hola tardes, explica la luz"})
            events = []
            for _ in range(25):
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "done":
                    break
            types = [e["type"] for e in events]
            assert "abstraction" in types
            assert "token" in types
            assert "audio_chunk" in types
            assert "done" in types
            chunk = next(e for e in events if e["type"] == "audio_chunk")
            assert base64.b64decode(chunk["data"])[:4] == b"RIFF"


def test_voice_llm_router_aligns_num_gpu_and_num_ctx():
    router = tve.LocalVoiceLLMRouter()
    captured = {}

    def _fake_stream_ollama(base_url, model, messages, max_tokens, temperature, num_ctx, cancel_event, *, num_gpu=None):
        captured.update({
            "base_url": base_url,
            "model": model,
            "num_ctx": num_ctx,
            "num_gpu": num_gpu,
        })
        yield "Respuesta rápida en GPU."

    with patch.object(router, "inspect_temporal_brain_slots", return_value={"available": True, "free_slots": 1, "total_slots": 2}), \
         patch.object(router, "inspect_voice_ollama_lane", return_value={"available": True, "model_loaded": True}), \
         patch.object(router, "_stream_ollama", side_effect=_fake_stream_ollama):
        lane, it = router.stream_reply(
            [{"role": "user", "content": "hola"}],
            user_text="hola",
            lane="auto",
        )
        text = "".join(it)
        assert lane == "voice_gpu"
        assert text == "Respuesta rápida en GPU."
        assert captured["num_ctx"] == tve.VOICE_OLLAMA_NUM_CTX
        assert captured["num_gpu"] == tve.VOICE_OLLAMA_NUM_GPU
