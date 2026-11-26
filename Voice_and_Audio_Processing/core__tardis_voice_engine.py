#!/usr/bin/env python3
"""
core/tardis_voice_engine.py - Motor Unificado de Voz Local, Dictado y Abstracción de TARDIS
===========================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL

Arquitectura 100% local-first de ultra-baja latencia y alta precisión en español:
  1. DSP Acústico (`preprocess_pcm_for_stt`):
     - Eliminación de DC offset + filtro pasa-altos Butterworth 85 Hz (scipy).
     - AGC suave hacia -18 dBFS con limitador soft-clip (ideal para Bluetooth HFP
       como Lentes EVOIR y micrófonos lejanos) + puerta de piso de ruido.
  2. Silero VAD v6 Neural Streaming (`SileroVadStream` + `AdaptiveSpeechSegmenter`):
     - Inferencia ONNX en tiempo real (<2 ms por ventana de 32 ms) sobre
       `silero_vad_v6.onnx` con respaldo `webrtcvad` + RMS adaptativo.
     - Endpointing inteligente (paciencia adaptativa para frases largas/dictado)
       y Barge-In anti-eco robusto.
  3. STT Soberano Local (`SovereignLocalSTT`):
     - `faster-whisper` singleton precalentado con aceleración automática CUDA int8
       (verificando VRAM libre para evitar OOM en RTX 3050 4 GB) y failover a CPU int8.
     - Prompt de dominio dinámico + hotwords TARDIS/FTL/Linux + filtro anti-alucinación
       y anti-repetición por métricas de confianza (`avg_logprob`, `no_speech_prob`).
  4. Normalización de Dictado y Abstracción Semántica (`DictationNormalizer`,
     `VoiceAbstractionEngine`, `UtteranceCoalescer`) (<15 ms, 0 llamadas LLM extra):
     - Corrección fonética contextual sin falsos positivos (protege "buenas tardes").
     - Limpieza de muletillas/tartamudeos y comandos hablados de puntuación/dictado.
     - Detección de frases incompletas y coalescencia fluida de dictado continuo.
     - Extracción de intención, entidades, tópico activo, resolución de anáforas
       multi-turno ("eso", "más simple", "dame un ejemplo") y comandos instantáneos.
  5. TTS Neuronal 100% Local (`SovereignLocalTTS` + `GaplessAudioPlayer`):
     - Piper ONNX residente en memoria (`es_MX-claude-high`, `es_MX-ald-medium`)
       con caché LRU en RAM y cero subprocesos por oración.
     - Modo híbrido con `edge-tts` async en memoria y failover instantáneo a Piper.
     - Reproducción gapless PCM vía `pw-cat`/`pacat` con corte Barge-In <20 ms.
  6. Enrutador Multi-Carril LLM (`LocalVoiceLLMRouter`):
     - Selecciona automáticamente TemporalBrain UDS si tiene slot libre o el carril
       GPU dedicado `:11435` (`qwen3-vl:2b-instruct`, `num_ctx=3072`) si TemporalBrain
       está saturado por demonios de fondo.
"""
from __future__ import annotations

# Fachada soberana retrocompatible respaldada por subpaquete modular `core.voice` (COEV-20261123-93393A).
from core.voice.common import *
from core.voice.common import _CUDA_LIBS_PRELOADED, _CUDA_LOCK, _VRAM_CACHE
from core.voice.vad_segmentation import (
    _HPF_SOS,
    preprocess_pcm_for_stt,
    SileroVadStream,
    SegmenterConfig,
    AdaptiveSpeechSegmenter,
    strip_accents,
    normalize_key,
    is_whisper_hallucination,
    DictationNormalizer,
    UtteranceCoalescer,
)
from core.voice.abstraction import (
    VoiceAbstraction,
    VoiceAbstractionEngine,
)
from core.voice.stt import (
    TranscriptionResult,
    SovereignLocalSTT,
)
from core.voice.tts_prosody import (
    _RE_THINK,
    _RE_HW_DIRECTIVE,
    _RE_MD_CODE,
    _RE_MD_INLINE_CODE,
    _RE_MD_TABLE,
    _RE_MD_LINK,
    _RE_URL,
    _RE_HTML,
    _RE_MD_CHARS,
    _RE_NON_LATIN,
    _SENTENCE_SPLIT_RE,
    _ES_MX_PHONETIC_DICTION,
    _VOWEL_GROUPS_RE,
    _WORD_SPAN_RE,
    prepare_text_for_speech,
    ExpressiveProsody,
    analyze_expressive_prosody,
    polish_tts_pcm,
    WordTiming,
    SyncedSpeechSegment,
    compute_word_timings,
    extract_streaming_sentence,
    resolve_voice_spec,
    _rate_to_length_scale,
    _normalize_edge_rate,
    pcm_to_wav_bytes,
    SovereignLocalTTS,
)
from core.voice.playback_router import (
    GaplessAudioPlayer,
    LocalVoiceLLMRouter,
    LiveDictationTracker,
)

_SINGLETON_LOCK = threading.Lock()
_STT_SINGLETON: Optional[SovereignLocalSTT] = None
_TTS_SINGLETON: Optional[SovereignLocalTTS] = None
_ABSTRACTOR_SINGLETON: Optional[VoiceAbstractionEngine] = None
_ROUTER_SINGLETON: Optional[LocalVoiceLLMRouter] = None
_DICTATION_TRACKER_SINGLETON: Optional[LiveDictationTracker] = None


def get_live_dictation_tracker() -> LiveDictationTracker:
    global _DICTATION_TRACKER_SINGLETON
    with _SINGLETON_LOCK:
        if _DICTATION_TRACKER_SINGLETON is None:
            _DICTATION_TRACKER_SINGLETON = LiveDictationTracker()
        return _DICTATION_TRACKER_SINGLETON


def get_sovereign_stt(
    model_size: Optional[str] = None,
    device: Optional[str] = None,
) -> SovereignLocalSTT:
    global _STT_SINGLETON
    req_m = model_size or DEFAULT_STT_MODEL
    req_d = device or DEFAULT_STT_DEVICE
    with _SINGLETON_LOCK:
        if (
            _STT_SINGLETON is None
            or (model_size and _STT_SINGLETON.requested_model != req_m)
            or (device and _STT_SINGLETON.requested_device != req_d)
        ):
            _STT_SINGLETON = SovereignLocalSTT(model_size=req_m, device=req_d)
        return _STT_SINGLETON


def get_sovereign_tts(mode: Optional[str] = None) -> SovereignLocalTTS:
    global _TTS_SINGLETON
    with _SINGLETON_LOCK:
        if _TTS_SINGLETON is None:
            _TTS_SINGLETON = SovereignLocalTTS(mode=mode or DEFAULT_TTS_MODE)
        elif mode:
            _TTS_SINGLETON.mode = mode.strip().lower()
        return _TTS_SINGLETON


def get_voice_abstractor() -> VoiceAbstractionEngine:
    global _ABSTRACTOR_SINGLETON
    with _SINGLETON_LOCK:
        if _ABSTRACTOR_SINGLETON is None:
            _ABSTRACTOR_SINGLETON = VoiceAbstractionEngine()
        return _ABSTRACTOR_SINGLETON


def get_voice_llm_router() -> LocalVoiceLLMRouter:
    global _ROUTER_SINGLETON
    with _SINGLETON_LOCK:
        if _ROUTER_SINGLETON is None:
            _ROUTER_SINGLETON = LocalVoiceLLMRouter()
        return _ROUTER_SINGLETON


def get_sovereign_voice_status() -> Dict[str, Any]:
    stt = get_sovereign_stt()
    tts = get_sovereign_tts()
    router = get_voice_llm_router()
    silero_ok = SileroVadStream._find_model_path() is not None
    return {
        "ok": True,
        "engine_version": "2.0-sovereign-local",
        "stt": stt.get_status(),
        "tts": tts.get_status(),
        "vad": {
            "silero_v6_available": silero_ok,
            "webrtcvad_available": HAS_WEBRTCVAD,
            "dsp_scipy": HAS_SCIPY,
        },
        "llm_lanes": {
            "temporal_brain": router.inspect_temporal_brain_slots(),
            "voice_gpu_ollama": router.inspect_voice_ollama_lane(),
        },
        "abstraction": {
            "active_topic": get_voice_abstractor().active_topic,
            "dictation_mode": get_voice_abstractor().dictation_mode,
        },
        "live_dictation": get_live_dictation_tracker().snapshot(),
        "sync_speech": {
            "enabled": True,
            "word_timings": True,
            "expressive_prosody": True,
            "phonetic_diction_es_mx": True,
        },
        "cpu_freq_mhz": query_cpu_freq_mhz(),
        "audio_io": {
            "pw_record": bool(shutil.which("pw-record")),
            "pw_cat": bool(shutil.which("pw-cat")),
            "pw_play": bool(shutil.which("pw-play")),
            "pacat": bool(shutil.which("pacat")),
            "ffplay": bool(shutil.which("ffplay")),
            "ffmpeg": bool(shutil.which("ffmpeg")),
        },
    }
