"""Subpaquete modular del Motor Unificado de Voz Local de TARDIS (extraído de core/tardis_voice_engine.py)."""
from core.voice.common import *
from core.voice.vad_segmentation import (
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
from core.voice.abstraction import VoiceAbstraction, VoiceAbstractionEngine
from core.voice.stt import TranscriptionResult, SovereignLocalSTT
from core.voice.tts_prosody import (
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
