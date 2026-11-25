#!/usr/bin/env python3
"""
core/mundo_sin_censura_voice.py - Motor de Conversación por Voz Continua (Full-Duplex)
======================================================================================
Exclusivo y estrictamente bloqueado al modelo soberano local `mundo-sin-censura`
(Llama 3.1 8B Q4_K_M, dual-lane TemporalBrain CUDA + Ollama) con persistencia
compartida en SQLite WAL (`data/mundo_sin_censura_chat.db`) y soporte Ring-0 `/hw`.

Capacidades:
  1. Captura continua manos libres vía PipeWire (`pw-record` 16kHz s16le mono) con
     VAD híbrido (`webrtcvad` + piso de ruido adaptativo + pre-roll 300ms).
  2. Detección de interrupción en caliente (Barge-In) durante reproducción TTS.
  3. Transcripción STT 100% local en memoria con `faster-whisper` (CPU int8,
     singleton precalentado, decodificación PCM directa sin ffmpeg y filtro de
     alucinaciones de Whisper).
  4. Streaming token-a-token desde `mundo-sin-censura` con síntesis TTS neuronal
     por oración en paralelo (`edge-tts` -> MP3 en memoria/disco, con fallback
     automático) para latencia mínima al primer audio.
  5. Doble interfaz de operación:
     - Modo interactivo de terminal (`mundo-voice` / `mundo-chat --voice` / `/voice`).
     - Modo NDJSON bidireccional (`--json-stream`) para la app nativa `mundo-desktop`.
  6. Primitivas reutilizables por los endpoints FastAPI (`/api/mundo_sin_censura/voice/*`
     y WebSocket `/api/mundo_sin_censura/voice/ws`).
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
import io
import json
import logging
import os
from pathlib import Path
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path("/home/m11/Escritorio/GODWORKS SYSTEM").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VOICE_RUNTIME = Path.home() / ".local" / "share" / "tardis-voice"
VOICE_LIB = VOICE_RUNTIME / "lib"
MODEL_CACHE = VOICE_RUNTIME / "models"
if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
    sys.path.insert(0, str(VOICE_LIB))

from core.mundo_sin_censura import MODEL_NAME
from core.mundo_sin_censura_chat import (
    MODEL_LOCK,
    VALID_LANES,
    enforce_model_lock,
    get_mundo_chat_store,
    normalize_lane,
)

try:
    import webrtcvad  # type: ignore[import-untyped]
    HAS_WEBRTCVAD = True
except Exception:
    webrtcvad = None
    HAS_WEBRTCVAD = False

try:
    import edge_tts  # type: ignore[import-untyped]
    HAS_EDGE_TTS = True
except Exception:
    edge_tts = None
    HAS_EDGE_TTS = False

try:
    import httpx
    HAS_HTTPX = True
except Exception:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

logger = logging.getLogger("TARDIS.MundoSinCensuraVoice")

SAMPLE_RATE = 16000
DEFAULT_VOICE = os.environ.get("MUNDO_TTS_VOICE", "es-MX-DaliaNeural")
DEFAULT_WHISPER_MODEL = os.environ.get("MUNDO_VOICE_WHISPER_MODEL", "base")
DEFAULT_WHISPER_THREADS = int(os.environ.get("MUNDO_VOICE_WHISPER_THREADS", "6"))
DEFAULT_LANGUAGE = os.environ.get("MUNDO_VOICE_LANG", "es")
DEFAULT_API_BASE = os.environ.get("TARDIS_API_URL", "http://127.0.0.1:8757").rstrip("/")
TARDIS_TOKEN_FILE = Path(
    os.environ.get(
        "TARDIS_TOKEN_FILE",
        str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"),
    )
)

AVAILABLE_VOICES: List[Dict[str, str]] = [
    {"id": "es-MX-DaliaNeural", "label": "Cortana · Dalia (es-MX)", "lang": "es-MX", "gender": "Female"},
    {"id": "es-MX-JorgeNeural", "label": "Jorge Neural (es-MX)", "lang": "es-MX", "gender": "Male"},
    {"id": "es-ES-ElviraNeural", "label": "Elvira Neural (es-ES)", "lang": "es-ES", "gender": "Female"},
    {"id": "es-ES-AlvaroNeural", "label": "Álvaro Neural (es-ES)", "lang": "es-ES", "gender": "Male"},
    {"id": "en-US-JennyNeural", "label": "Cortana · Jenny (en-US)", "lang": "en-US", "gender": "Female"},
]

VOICE_ALIASES: Dict[str, str] = {
    "dalia": "es-MX-DaliaNeural",
    "cortana": "es-MX-DaliaNeural",
    "jorge": "es-MX-JorgeNeural",
    "elvira": "es-ES-ElviraNeural",
    "alvaro": "es-ES-AlvaroNeural",
    "álvaro": "es-ES-AlvaroNeural",
    "jenny": "en-US-JennyNeural",
}

VOICE_CONVERSATION_SYSTEM_HINT = (
    "[MODO CONVERSACIÓN DE VOZ CONTINUA EN VIVO]: "
    "El usuario está hablando contigo por micrófono en una conversación fluida y continua. "
    "Responde de forma natural, clara, directa y conversacional pensada para escucharse en voz alta "
    "(oraciones bien puntuadas, sin tablas Markdown, sin listas largas ni bloques de código salvo que el "
    "usuario pida explícitamente código). Si ejecutas una acción de hardware con [[HW_ACTION:...]], "
    "confírmala verbalmente en una frase breve."
)

WHISPER_HALLUCINATIONS = frozenset({
    "subtitulos realizados por la comunidad de amara.org",
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulos por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "gracias por ver",
    "suscribete al canal",
    "suscríbete al canal",
    "suscribete",
    "suscríbete",
    "amara.org",
    "...",
    "..",
    ".",
    "you",
    "thank you",
    "thank you.",
    "thanks for watching",
    "thanks for watching.",
    "mbc",
    "bye.",
    "bye",
})

_THINK_RE = re.compile(r"<think>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
_HW_DIRECTIVE_RE = re.compile(r"\[\[HW_ACTION:[\s\S]*?\]\]", re.IGNORECASE)
_MD_CODE_BLOCK = re.compile(r"```[\s\S]*?(?:```|\Z)")
_MD_TABLE_ROW = re.compile(r"^\s*\|.*$", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_MARKS = re.compile(r"[`*_#>|~]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")

_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_EMERALD = "\033[38;5;48m"
_C_AMBER = "\033[38;5;214m"
_C_CYAN = "\033[38;5;51m"
_C_RED = "\033[38;5;203m"
_C_YELLOW = "\033[93m"


# ==============================================================================
# UTILIDADES DE TEXTO, DETECCIÓN DE ALUCINACIONES Y NORMALIZACIÓN DE VOZ
# ==============================================================================

def resolve_voice_id(voice: Optional[str]) -> str:
    raw = (voice or "").strip()
    if not raw:
        return DEFAULT_VOICE
    low = raw.lower()
    if low in VOICE_ALIASES:
        return VOICE_ALIASES[low]
    for item in AVAILABLE_VOICES:
        if item["id"].lower() == low:
            return item["id"]
    if re.match(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural$", raw):
        return raw
    return DEFAULT_VOICE


def normalize_speech_rate(rate: Optional[Any]) -> str:
    if rate is None or rate == "":
        return "+8%"
    if isinstance(rate, str):
        s = rate.strip()
        if re.match(r"^[+-]\d{1,2}%$", s):
            return s
        try:
            rate = float(s)
        except ValueError:
            return "+8%"
    try:
        val = float(rate)
        pct = int(round((max(0.6, min(1.6, val)) - 1.0) * 100))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return "+8%"


def clean_for_mundo_speech(text: str) -> str:
    """Limpia directivas internas, pensamiento y Markdown para locución natural."""
    if not text:
        return ""
    body = _THINK_RE.sub(" ", text)
    body = _HW_DIRECTIVE_RE.sub(" ", body)
    body = _MD_CODE_BLOCK.sub(" ", body)
    body = _MD_LINK.sub(r"\1", body)
    body = _MD_TABLE_ROW.sub(" ", body)
    body = _MD_MARKS.sub(" ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def extract_ready_sentence(buffer: str, is_first: bool = False) -> Tuple[Optional[str], str]:
    """Extrae la siguiente oración lista para TTS priorizando baja latencia inicial."""
    min_len = 16 if is_first else 38
    if len(buffer) < min_len:
        return None, buffer

    match = _SENTENCE_SPLIT_RE.search(buffer)
    if match and match.start() >= min_len:
        sentence = buffer[: match.start() + 1].strip()
        rest = buffer[match.end():]
        return sentence, rest

    if len(buffer) >= 84:
        comma_idx = buffer.find(", ", 46)
        if comma_idx != -1:
            sentence = buffer[: comma_idx + 1].strip()
            rest = buffer[comma_idx + 2:]
            return sentence, rest

    return None, buffer


def is_hallucination(text: str) -> bool:
    norm = re.sub(r"\s+", " ", (text or "").lower()).strip()
    norm_no_punct = re.sub(r"^[.,!?;:¡¿\-\s]+|[.,!?;:¡¿\-\s]+$", "", norm)
    if not norm_no_punct or len(norm_no_punct) < 2:
        return True
    return norm in WHISPER_HALLUCINATIONS or norm_no_punct in WHISPER_HALLUCINATIONS


# ==============================================================================
# SINGLETON STT LOCAL (faster-whisper CPU int8 + decodificación PCM/WAV directa)
# ==============================================================================

class MundoLocalSTT:
    """Wrapper thread-safe de faster-whisper en memoria con decodificación rápida."""

    def __init__(
        self,
        model_size: str = DEFAULT_WHISPER_MODEL,
        cpu_threads: int = DEFAULT_WHISPER_THREADS,
    ):
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._last_error: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _load(self):
        with self._load_lock:
            if self._model is not None:
                return self._model
            if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
                sys.path.insert(0, str(VOICE_LIB))
            from faster_whisper import WhisperModel

            MODEL_CACHE.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=self.cpu_threads,
                download_root=str(MODEL_CACHE),
            )
            self._last_error = None
            return self._model

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self._load()
        return time.perf_counter() - t0

    def _decode_to_pcm16k(self, audio_bytes: bytes, suffix: str = ".wav") -> bytes:
        # Ruta rápida sin subprocesos para WAV PCM 16-bit mono 16 kHz
        if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    if (
                        wf.getnchannels() == 1
                        and wf.getsampwidth() == 2
                        and wf.getframerate() == SAMPLE_RATE
                    ):
                        return wf.readframes(wf.getnframes())
            except Exception:
                pass

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg no disponible para decodificar audio")

        with tempfile.NamedTemporaryFile(suffix=suffix or ".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-loglevel", "error",
                    "-i", str(tmp_path),
                    "-ar", str(SAMPLE_RATE),
                    "-ac", "1",
                    "-f", "s16le",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode(errors='ignore')[:200]}")
            return proc.stdout
        finally:
            tmp_path.unlink(missing_ok=True)

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        language: str = DEFAULT_LANGUAGE,
        min_duration_s: float = 0.22,
    ) -> Tuple[str, float]:
        if not pcm_bytes:
            return "", 0.0
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size < int(SAMPLE_RATE * min_duration_s):
            return "", 0.0
        # Descartar buffers prácticamente silenciosos antes de invocar Whisper
        rms = float(np.sqrt(np.mean(pcm * pcm)))
        if rms < 0.0025:
            return "", 0.0

        model = self._load()
        lang_arg = None if (not language or language.lower() == "auto") else language.split("-")[0].lower()
        t0 = time.perf_counter()
        with self._infer_lock:
            segments, _ = model.transcribe(
                pcm,
                language=lang_arg,
                beam_size=1,
                best_of=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 180},
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0
        if is_hallucination(text):
            return "", elapsed
        return text, elapsed

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        *,
        audio_format: str = "wav",
        language: str = DEFAULT_LANGUAGE,
    ) -> Tuple[str, float]:
        if not audio_bytes:
            return "", 0.0
        fmt = (audio_format or "wav").strip().lower().lstrip(".")
        if fmt in ("pcm", "pcm16", "s16le", "raw"):
            return self.transcribe_pcm(audio_bytes, language=language)
        pcm_bytes = self._decode_to_pcm16k(audio_bytes, suffix=f".{fmt}")
        return self.transcribe_pcm(pcm_bytes, language=language)


_STT_SINGLETON_LOCK = threading.Lock()
_STT_SINGLETON: Optional[MundoLocalSTT] = None


def get_mundo_stt(model_size: str = DEFAULT_WHISPER_MODEL) -> MundoLocalSTT:
    global _STT_SINGLETON
    with _STT_SINGLETON_LOCK:
        if _STT_SINGLETON is None or _STT_SINGLETON.model_size != model_size:
            _STT_SINGLETON = MundoLocalSTT(model_size=model_size)
        return _STT_SINGLETON


# ==============================================================================
# SÍNTESIS TTS NEURONAL EN MEMORIA (ASÍNCRONA + SÍNCRONA)
# ==============================================================================

async def synthesize_tts_bytes_async(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: Optional[Any] = "+8%",
    pitch: str = "+0Hz",
) -> Tuple[Optional[bytes], str]:
    """Sintetiza texto limpio a audio MP3 en memoria usando edge-tts (o fallback)."""
    clean = clean_for_mundo_speech(text)
    if not clean:
        return None, "audio/mpeg"

    target_voice = resolve_voice_id(voice)
    rate_str = normalize_speech_rate(rate)

    if HAS_EDGE_TTS and edge_tts is not None:
        try:
            comm = edge_tts.Communicate(clean, target_voice, rate=rate_str, pitch=pitch)
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    buf.write(chunk["data"])
            data = buf.getvalue()
            if data:
                return data, "audio/mpeg"
        except Exception as exc:
            logger.debug("edge-tts async falló (%s), intentando fallback", exc)

    # Fallback: módulo voice.py del proyecto
    try:
        import voice as voice_mod
        if hasattr(voice_mod, "synthesize_to_bytes_async"):
            data = await voice_mod.synthesize_to_bytes_async(clean, voice=target_voice)
        else:
            data = voice_mod.synthesize_to_bytes(clean, voice=target_voice)
        if data:
            return data, "audio/mpeg"
    except Exception as exc:
        logger.debug("Fallback voice.py falló: %s", exc)

    # Fallback offline CLI: espeak-ng -> WAV
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        try:
            proc = await asyncio.create_subprocess_exec(
                espeak, "-v", "es-la", "--stdout", clean,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            if proc.returncode == 0 and out:
                return out, "audio/wav"
        except Exception:
            pass

    return None, "audio/mpeg"


def synthesize_tts_bytes(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: Optional[Any] = "+8%",
    pitch: str = "+0Hz",
) -> Tuple[Optional[bytes], str]:
    """Versión síncrona de síntesis TTS en memoria."""
    clean = clean_for_mundo_speech(text)
    if not clean:
        return None, "audio/mpeg"
    try:
        asyncio.get_running_loop()
        # Si ya hay loop activo en este hilo, ejecutar en hilo dedicado
        box: Dict[str, Any] = {}

        def _runner():
            box["res"] = asyncio.run(
                synthesize_tts_bytes_async(clean, voice=voice, rate=rate, pitch=pitch)
            )

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=45.0)
        return box.get("res", (None, "audio/mpeg"))
    except RuntimeError:
        return asyncio.run(
            synthesize_tts_bytes_async(clean, voice=voice, rate=rate, pitch=pitch)
        )


def get_mundo_voice_status() -> Dict[str, Any]:
    stt = _STT_SINGLETON
    has_fw = (VOICE_LIB / "faster_whisper").exists()
    if not has_fw:
        try:
            import importlib.util
            has_fw = importlib.util.find_spec("faster_whisper") is not None
        except Exception:
            has_fw = False
    return {
        "ok": bool(has_fw),
        "model": MODEL_LOCK,
        "continuous_voice": True,
        "barge_in_supported": True,
        "stt": {
            "engine": "faster-whisper",
            "available": bool(has_fw),
            "model": stt.model_size if stt else DEFAULT_WHISPER_MODEL,
            "loaded": bool(stt and stt.is_loaded),
            "sample_rate": SAMPLE_RATE,
        },
        "tts": {
            "engine": "edge-tts" if HAS_EDGE_TTS else "fallback",
            "available": bool(HAS_EDGE_TTS or shutil.which("edge-tts") or shutil.which("espeak-ng")),
            "default_voice": DEFAULT_VOICE,
            "voices": AVAILABLE_VOICES,
        },
        "vad": {
            "engine": "webrtcvad" if HAS_WEBRTCVAD else "rms_adaptive",
            "webrtcvad": HAS_WEBRTCVAD,
        },
        "audio_io": {
            "pw_record": bool(shutil.which("pw-record")),
            "parecord": bool(shutil.which("parecord")),
            "arecord": bool(shutil.which("arecord")),
            "ffplay": bool(shutil.which("ffplay")),
            "pw_play": bool(shutil.which("pw-play")),
            "ffmpeg": bool(shutil.which("ffmpeg")),
        },
        "endpoints": {
            "ws": "/api/mundo_sin_censura/voice/ws",
            "status": "/api/mundo_sin_censura/voice/status",
            "transcribe": "/api/mundo_sin_censura/voice/transcribe",
            "tts": "/api/mundo_sin_censura/voice/tts",
        },
    }


# ==============================================================================
# VAD + BARGE-IN + MICRÓFONO PIPEWIRE + REPRODUCTOR INTERRUPTIBLE
# ==============================================================================

@dataclass
class MundoVoiceConfig:
    session_id: Optional[str] = None
    lane: str = "auto"
    temperature: float = 0.25
    max_tokens: int = 512
    use_rag: bool = False
    hardware_control: bool = True
    voice: str = DEFAULT_VOICE
    speech_rate: str = "+8%"
    whisper_model: str = DEFAULT_WHISPER_MODEL
    whisper_threads: int = DEFAULT_WHISPER_THREADS
    language: str = DEFAULT_LANGUAGE
    sample_rate: int = SAMPLE_RATE
    frame_ms: int = 30
    vad_aggressiveness: int = 2
    silence_hold_ms: int = 800
    min_speech_ms: int = 270
    max_utterance_ms: int = 28000
    pre_roll_ms: int = 300
    barge_in: bool = True
    barge_in_rms: float = 0.075
    barge_in_frames: int = 9
    no_play: bool = False
    greeting: bool = False
    json_stream: bool = False
    api_base: str = DEFAULT_API_BASE
    prefer_api: bool = True

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000)

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2


class MundoSpeechSegmenter:
    """Segmentador VAD híbrido (WebRTC VAD + piso adaptativo) con soporte Barge-In."""

    def __init__(self, cfg: MundoVoiceConfig):
        self.cfg = cfg
        self.vad = webrtcvad.Vad(cfg.vad_aggressiveness) if HAS_WEBRTCVAD else None
        self.noise_floor = 0.008
        self.in_speech = False
        self.speech_frames: List[bytes] = []
        self.pre_roll: Deque[bytes] = deque(maxlen=max(1, cfg.pre_roll_ms // cfg.frame_ms))
        self.silence_frames = 0
        self.barge_streak = 0
        self._hold_frames = max(1, cfg.silence_hold_ms // cfg.frame_ms)
        self._min_frames = max(1, cfg.min_speech_ms // cfg.frame_ms)
        self._max_frames = max(10, cfg.max_utterance_ms // cfg.frame_ms)

    def reset_utterance(self) -> None:
        self.in_speech = False
        self.speech_frames.clear()
        self.silence_frames = 0
        self.barge_streak = 0

    @staticmethod
    def frame_rms(frame: bytes) -> float:
        pcm = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(pcm * pcm)))

    def _is_speech(self, frame: bytes, rms: float, threshold: float) -> bool:
        energy_ok = rms > threshold
        if self.vad is None:
            return energy_ok
        try:
            vad_ok = self.vad.is_speech(frame, self.cfg.sample_rate)
        except Exception:
            vad_ok = energy_ok
        return vad_ok and rms > (threshold * 0.72)

    def process_frame(self, frame: bytes, ai_speaking: bool = False) -> Dict[str, Any]:
        rms = self.frame_rms(frame)
        threshold = max(0.012, self.noise_floor * 2.5)

        if ai_speaking:
            if self.cfg.barge_in:
                barge_thresh = max(self.cfg.barge_in_rms, self.noise_floor * 5.0)
                vad_hit = True
                if self.vad is not None:
                    try:
                        vad_hit = self.vad.is_speech(frame, self.cfg.sample_rate)
                    except Exception:
                        vad_hit = True
                if rms >= barge_thresh and vad_hit:
                    self.barge_streak += 1
                    self.pre_roll.append(frame)
                    if self.barge_streak >= self.cfg.barge_in_frames:
                        self.in_speech = True
                        self.speech_frames = list(self.pre_roll)
                        self.silence_frames = 0
                        self.barge_streak = 0
                        return {
                            "utterance": None,
                            "barge_in": True,
                            "rms": rms,
                            "in_speech": True,
                        }
                else:
                    self.barge_streak = max(0, self.barge_streak - 1)
                    self.pre_roll.append(frame)
            else:
                self.pre_roll.append(frame)
            return {
                "utterance": None,
                "barge_in": False,
                "rms": rms,
                "in_speech": False,
            }

        self.barge_streak = 0
        is_voice = self._is_speech(frame, rms, threshold)

        if not self.in_speech:
            self.noise_floor = 0.98 * self.noise_floor + 0.02 * min(rms, 0.035)
            self.pre_roll.append(frame)
            if is_voice:
                self.in_speech = True
                self.speech_frames = list(self.pre_roll)
                self.silence_frames = 0
            return {
                "utterance": None,
                "barge_in": False,
                "rms": rms,
                "in_speech": self.in_speech,
            }

        self.speech_frames.append(frame)
        if is_voice:
            self.silence_frames = 0
        else:
            self.silence_frames += 1

        if self.silence_frames >= self._hold_frames or len(self.speech_frames) >= self._max_frames:
            frames = list(self.speech_frames)
            self.reset_utterance()
            if len(frames) >= self._min_frames:
                return {
                    "utterance": b"".join(frames),
                    "barge_in": False,
                    "rms": rms,
                    "in_speech": False,
                }
        return {
            "utterance": None,
            "barge_in": False,
            "rms": rms,
            "in_speech": self.in_speech,
        }


class MundoMicStream:
    """Captura continua PCM 16kHz s16le mono mediante PipeWire/PulseAudio/ALSA."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, frame_bytes: int = 960):
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._stop = threading.Event()

    def _build_cmd(self) -> List[str]:
        if shutil.which("pw-record"):
            return [
                "pw-record",
                "--raw",
                "--rate", str(self.sample_rate),
                "--channels", "1",
                "--format", "s16",
                "-",
            ]
        if shutil.which("parecord"):
            return [
                "parecord",
                "--raw",
                f"--rate={self.sample_rate}",
                "--channels=1",
                "--format=s16le",
            ]
        if shutil.which("arecord"):
            return [
                "arecord",
                "-q",
                "-t", "raw",
                "-f", "S16_LE",
                "-r", str(self.sample_rate),
                "-c", "1",
                "-",
            ]
        raise RuntimeError("No se encontró pw-record, parecord ni arecord para capturar micrófono.")

    def start(self) -> None:
        self._stop.clear()
        self._spawn()

    def _spawn(self) -> None:
        self._terminate_proc()
        self._proc = subprocess.Popen(
            self._build_cmd(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )

    def _terminate_proc(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=1.0)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def read_frame(self) -> Optional[bytes]:
        while not self._stop.is_set():
            if self._proc is None or self._proc.stdout is None or self._proc.poll() is not None:
                time.sleep(0.2)
                if self._stop.is_set():
                    return None
                try:
                    self._spawn()
                except Exception as exc:
                    logger.warning("Reintentando captura de micrófono: %s", exc)
                    time.sleep(1.0)
                    continue
            buf = bytearray()
            stdout = self._proc.stdout
            while len(buf) < self.frame_bytes and not self._stop.is_set():
                chunk = stdout.read(self.frame_bytes - len(buf))
                if not chunk:
                    break
                buf.extend(chunk)
            if len(buf) == self.frame_bytes:
                return bytes(buf)
            self._terminate_proc()
        return None

    def stop(self) -> None:
        self._stop.set()
        self._terminate_proc()


class MundoAudioPlayer:
    """Cola de reproducción de audio con interrupción inmediata (Barge-In)."""

    def __init__(self, enabled: bool = True, on_state: Optional[Callable[[bool], None]] = None):
        self.enabled = enabled
        self._on_state = on_state
        self._queue: "queue.Queue[Optional[Path]]" = queue.Queue()
        self._proc_lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._playing = False
        self._last_play_end = 0.0
        self._stop_flag = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @property
    def is_playing(self) -> bool:
        if self._playing or not self._queue.empty():
            return True
        return (time.monotonic() - self._last_play_end) < 0.22

    @staticmethod
    def _player_cmd(audio_path: Path) -> Optional[List[str]]:
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]
        if shutil.which("mpv"):
            return ["mpv", "--no-video", "--really-quiet", str(audio_path)]
        if shutil.which("pw-play"):
            return ["pw-play", str(audio_path)]
        return None

    def _notify(self, playing: bool) -> None:
        if self._on_state is not None:
            try:
                self._on_state(playing)
            except Exception:
                pass

    def _worker(self) -> None:
        while not self._stop_flag.is_set():
            path = self._queue.get()
            if path is None:
                break
            try:
                if not self.enabled or not path.exists():
                    continue
                cmd = self._player_cmd(path)
                if not cmd:
                    continue
                self._playing = True
                self._notify(True)
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    proc = self._proc
                proc.wait()
            except Exception as exc:
                logger.debug("Error reproduciendo audio: %s", exc)
            finally:
                with self._proc_lock:
                    self._proc = None
                self._playing = False
                self._last_play_end = time.monotonic()
                if self._queue.empty():
                    self._notify(False)
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def enqueue_bytes(self, audio_bytes: bytes, mime: str = "audio/mpeg") -> None:
        if not self.enabled or not audio_bytes:
            return
        ext = ".wav" if "wav" in mime else ".mp3"
        with tempfile.NamedTemporaryFile(prefix="mundo_tts_", suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            path = Path(tmp.name)
        self._queue.put(path)

    def interrupt(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
                if isinstance(item, Path):
                    item.unlink(missing_ok=True)
            except queue.Empty:
                break
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
        if self._playing:
            self._playing = False
            self._notify(False)

    def wait_idle(self, cancel_event: Optional[threading.Event] = None, timeout: float = 120.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event and cancel_event.is_set():
                return
            if not self._playing and self._queue.empty():
                return
            time.sleep(0.05)

    def shutdown(self) -> None:
        self.interrupt()
        self._stop_flag.set()
        self._queue.put(None)
        self._thread.join(timeout=1.5)


# ==============================================================================
# MOTOR DE CONVERSACIÓN CONTINUA EXCLUSIVO PARA "UN MUNDO SIN CENSURA"
# ==============================================================================

class MundoContinuousVoiceEngine:
    """
    Orquestador full-duplex manos libres bloqueado exclusivamente a `mundo-sin-censura`.
    Sincroniza cada turno con `data/mundo_sin_censura_chat.db` (vía API :8757 o
    `MundoSinCensuraChatStore` directo) y soporta tanto CLI interactiva como
    protocolo NDJSON bidireccional para `mundo-desktop`.
    """

    def __init__(self, cfg: Optional[MundoVoiceConfig] = None):
        self.cfg = cfg or MundoVoiceConfig()
        self.cfg.lane = normalize_lane(self.cfg.lane)
        self.cfg.voice = resolve_voice_id(self.cfg.voice)
        self.cfg.speech_rate = normalize_speech_rate(self.cfg.speech_rate)

        self.stt = get_mundo_stt(model_size=self.cfg.whisper_model)
        self.segmenter = MundoSpeechSegmenter(self.cfg)
        self.mic = MundoMicStream(
            sample_rate=self.cfg.sample_rate,
            frame_bytes=self.cfg.frame_bytes,
        )
        self.player = MundoAudioPlayer(
            enabled=not self.cfg.no_play,
            on_state=self._on_player_state,
        )

        self.running = False
        self.muted = False
        self.paused = False
        self.turn_count = 0
        self.session_id: Optional[str] = self.cfg.session_id
        self.session_title: str = "Un Mundo Sin Censura"
        self._voice_state: str = "idle"
        self._active_request_id: Optional[str] = None
        self._cancel_event = threading.Event()
        self._turn_lock = threading.Lock()
        self._active_turn_thread: Optional[threading.Thread] = None
        self._emit_lock = threading.Lock()
        self._last_level_emit = 0.0

    def _emit_json(self, payload: Dict[str, Any]) -> None:
        if not self.cfg.json_stream:
            return
        with self._emit_lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def _set_state(self, state: str, detail: str = "") -> None:
        if state == self._voice_state and not detail:
            return
        self._voice_state = state
        self._emit_json({
            "type": "voice_state",
            "state": state,
            "detail": detail,
            "muted": self.muted,
            "paused": self.paused,
            "voice": self.cfg.voice,
            "barge_in": self.cfg.barge_in,
            "session_id": self.session_id or "",
            "turn_count": self.turn_count,
        })

    def _log(self, msg: str) -> None:
        if not self.cfg.json_stream:
            print(msg, flush=True)

    def _on_player_state(self, playing: bool) -> None:
        if playing:
            self._set_state("speaking")
        elif self.running and not self.paused and not self.muted:
            if self._voice_state == "speaking":
                self._set_state("listening")

    @staticmethod
    def _read_token() -> str:
        env = os.environ.get("GIA_AUTH_TOKEN") or os.environ.get("GIA_TOKEN") or ""
        if env:
            return env.strip()
        try:
            if TARDIS_TOKEN_FILE.exists():
                return TARDIS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    def _cancel_remote_stream(self, request_id: Optional[str]) -> None:
        if not request_id or not self.cfg.prefer_api:
            return
        try:
            tok = self._read_token()
            headers = {"Content-Type": "application/json"}
            if tok:
                headers["X-GIA-Key"] = tok
                headers["Authorization"] = f"Bearer {tok}"
            req = urllib.request.Request(
                f"{self.cfg.api_base}/api/mundo_sin_censura/chat/cancel",
                data=json.dumps({"request_id": request_id}).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2.5).close()
        except Exception:
            pass

    def _stream_mundo_turn(
        self,
        user_text: str,
        cancel_event: threading.Event,
    ) -> Iterator[Dict[str, Any]]:
        """Ejecuta un turno SSE exclusivamente sobre `mundo-sin-censura` (API :8757 o Store local)."""
        enforce_model_lock(MODEL_LOCK)

        if self.cfg.prefer_api and HAS_HTTPX and httpx is not None:
            tok = self._read_token()
            headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
            if tok:
                headers["X-GIA-Key"] = tok
                headers["Authorization"] = f"Bearer {tok}"
            body: Dict[str, Any] = {
                "message": user_text,
                "model": MODEL_LOCK,
                "lane": self.cfg.lane,
                "temperature": self.cfg.temperature,
                "max_tokens": self.cfg.max_tokens,
                "use_rag": self.cfg.use_rag,
                "hardware_control": self.cfg.hardware_control,
                "voice_mode": True,
            }
            if self.session_id:
                body["session_id"] = self.session_id
            try:
                with httpx.Client(timeout=httpx.Timeout(180.0, connect=4.0)) as client:
                    with client.stream(
                        "POST",
                        f"{self.cfg.api_base}/api/mundo_sin_censura/chat/stream",
                        headers=headers,
                        json=body,
                    ) as resp:
                        if resp.status_code == 200:
                            for line in resp.iter_lines():
                                if cancel_event.is_set():
                                    self._cancel_remote_stream(self._active_request_id)
                                    return
                                if not line:
                                    continue
                                raw = line.strip()
                                if not raw.startswith("data:"):
                                    continue
                                payload_str = raw[5:].strip()
                                if not payload_str or payload_str == "[DONE]":
                                    continue
                                try:
                                    ev = json.loads(payload_str)
                                except Exception:
                                    continue
                                if isinstance(ev, dict):
                                    yield ev
                            return
            except Exception as exc:
                logger.debug("Fallback directo a MundoSinCensuraChatStore (API no accesible): %s", exc)

        # Fallback local directo sobre SQLite + Dual-Lane
        store = get_mundo_chat_store()
        local_rid: Optional[str] = None
        for ev in store.stream_turn(
            session_id=self.session_id,
            message=user_text,
            model=MODEL_LOCK,
            lane=self.cfg.lane,
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
            use_rag=self.cfg.use_rag,
            hardware_control=self.cfg.hardware_control,
            voice_mode=True,
            is_local_request=True,
        ):
            if ev.get("type") == "meta":
                local_rid = ev.get("request_id")
            if cancel_event.is_set():
                if local_rid:
                    store.cancel_stream(local_rid)
                return
            yield ev

    def _handle_voice_control_intent(self, text: str) -> Optional[str]:
        low = re.sub(r"[^\w\sáéíóúñü]", "", text.lower()).strip()

        if self.paused:
            if any(k in low for k in ("reanuda", "despierta", "escucha", "continua", "continúa", "vuelve")):
                self.paused = False
                self._set_state("listening", "Escucha continua reactivada")
                return "Escucha continua reactivada. Te escucho."
            return "__PAUSED_IGNORE__"

        if low in ("pausa voz", "pausar voz", "pausa el chat", "modo silencio", "silencio mundo"):
            self.paused = True
            self._set_state("paused", "En pausa silenciosa")
            return "Entendido, entro en pausa. Di reanuda voz cuando quieras seguir."

        if low in (
            "deten conversacion de voz",
            "detén conversación de voz",
            "finalizar conversacion de voz",
            "finalizar conversación de voz",
            "cerrar chat de voz",
            "apagar voz continua",
        ):
            self.running = False
            return "Cerrando conversación de voz continua."

        m_voice = re.search(r"cambia(?:r)?(?:\s+la)?\s+voz\s+a\s+([a-záéíóúñ]+)", low)
        if m_voice:
            alias = m_voice.group(1)
            if alias in VOICE_ALIASES:
                self.cfg.voice = VOICE_ALIASES[alias]
                self._set_state(self._voice_state, f"Voz: {alias}")
                return f"Voz cambiada a {alias}. ¿Cómo me escuchas ahora?"
            return f"No tengo registrada la voz {alias}. Puedo usar Dalia, Jorge, Elvira, Álvaro o Jenny."

        return None

    def _speak_immediate(self, text: str, cancel_event: Optional[threading.Event] = None) -> None:
        if self.cfg.no_play or not text.strip():
            return
        audio_bytes, mime = synthesize_tts_bytes(
            text,
            voice=self.cfg.voice,
            rate=self.cfg.speech_rate,
        )
        if audio_bytes and (cancel_event is None or not cancel_event.is_set()):
            self._emit_json({"type": "speaking_sentence", "text": text})
            self.player.enqueue_bytes(audio_bytes, mime=mime)
            self.player.wait_idle(cancel_event=cancel_event)

    def process_user_text(self, user_text: str, cancel_event: threading.Event) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            return ""

        ctrl_reply = self._handle_voice_control_intent(user_text)
        if ctrl_reply == "__PAUSED_IGNORE__":
            return ""
        if ctrl_reply is not None:
            self._log(f"{_C_EMERALD}mundo-sin-censura (control) ❯ {_C_RESET}{ctrl_reply}")
            self._emit_json({"type": "control_reply", "text": ctrl_reply})
            self._speak_immediate(ctrl_reply, cancel_event=cancel_event)
            return ctrl_reply

        self._set_state("thinking")
        t0 = time.perf_counter()
        sentence_q: "queue.Queue[Optional[str]]" = queue.Queue()
        first_audio_emitted = False

        def _tts_worker() -> None:
            nonlocal first_audio_emitted
            while True:
                sent = sentence_q.get()
                if sent is None:
                    break
                if cancel_event.is_set():
                    continue
                audio_bytes, mime = synthesize_tts_bytes(
                    sent,
                    voice=self.cfg.voice,
                    rate=self.cfg.speech_rate,
                )
                if audio_bytes and not cancel_event.is_set():
                    if not first_audio_emitted:
                        first_audio_emitted = True
                        ttfa = round(time.perf_counter() - t0, 2)
                        self._emit_json({"type": "first_audio", "seconds": ttfa})
                        if not self.cfg.json_stream:
                            self._log(f"{_C_DIM}  [primer audio en {ttfa:.2f}s]{_C_RESET}")
                    self._emit_json({"type": "speaking_sentence", "text": sent})
                    self.player.enqueue_bytes(audio_bytes, mime=mime)

        tts_thread = threading.Thread(target=_tts_worker, daemon=True)
        if not self.cfg.no_play:
            tts_thread.start()

        full_reply = ""
        pending_buf = ""
        sent_idx = 0

        if not self.cfg.json_stream:
            sys.stdout.write(f"{_C_BOLD}{_C_EMERALD}mundo-sin-censura ❯ {_C_RESET}")
            sys.stdout.flush()

        for ev in self._stream_mundo_turn(user_text, cancel_event=cancel_event):
            if cancel_event.is_set():
                break
            etype = ev.get("type")
            if etype == "meta":
                sid = ev.get("session_id")
                if sid:
                    self.session_id = str(sid)
                title = ev.get("title")
                if title:
                    self.session_title = str(title)
                self._active_request_id = ev.get("request_id")
                self._emit_json(ev)
            elif etype == "token":
                delta = str(ev.get("delta") or "")
                if not delta:
                    continue
                full_reply += delta
                pending_buf += delta
                self._emit_json(ev)
                if not self.cfg.json_stream:
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                if not self.cfg.no_play:
                    while True:
                        ready, pending_buf = extract_ready_sentence(pending_buf, is_first=(sent_idx == 0))
                        if not ready:
                            break
                        clean_sent = clean_for_mundo_speech(ready)
                        if clean_sent:
                            sentence_q.put(clean_sent)
                            sent_idx += 1
            elif etype in ("hardware_action", "hardware_result", "error"):
                self._emit_json(ev)
                if etype == "error" and not self.cfg.json_stream:
                    self._log(f"\n{_C_RED}⚠️ {ev.get('error')}{_C_RESET}")
            elif etype == "done":
                self._active_request_id = None
                self._emit_json(ev)
                if not self.cfg.json_stream:
                    sys.stdout.write(
                        f"\n{_C_DIM}  [{ev.get('lane')} · {ev.get('elapsed_s')}s]{_C_RESET}\n"
                    )
                    sys.stdout.flush()

        if not self.cfg.no_play:
            if not cancel_event.is_set():
                tail = clean_for_mundo_speech(pending_buf)
                if tail:
                    sentence_q.put(tail)
            sentence_q.put(None)
            tts_thread.join(timeout=60.0)
            self.player.wait_idle(cancel_event=cancel_event)

        self.turn_count += 1
        if self.running and not self.paused and not self.muted and not cancel_event.is_set():
            self._set_state("listening")
        return full_reply.strip()

    def interrupt_active_turn(self, reason: str = "manual") -> None:
        self._cancel_event.set()
        self._cancel_remote_stream(self._active_request_id)
        self.player.interrupt()
        t = self._active_turn_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.2)
        self._active_request_id = None
        if reason == "barge_in":
            self._emit_json({"type": "barge_in"})
        if self.running and not self.paused and not self.muted:
            self._set_state("listening")

    def _dispatch_audio_utterance(self, pcm_bytes: bytes) -> None:
        self.interrupt_active_turn(reason="new_utterance")
        self._cancel_event = threading.Event()
        cancel_ev = self._cancel_event

        def _worker() -> None:
            with self._turn_lock:
                self._set_state("transcribing")
                text, stt_s = self.stt.transcribe_pcm(pcm_bytes, language=self.cfg.language)
                if not text or cancel_ev.is_set():
                    if self.running and not self.paused and not self.muted:
                        self._set_state("listening")
                    return
                self._emit_json({
                    "type": "user_transcript",
                    "text": text,
                    "stt_ms": int(round(stt_s * 1000)),
                    "session_id": self.session_id or "",
                })
                if not self.paused and not self.cfg.json_stream:
                    self._log(f"\n{_C_BOLD}{_C_AMBER}tú (voz · {stt_s*1000:.0f}ms) ❯ {_C_RESET}{text}")
                self.process_user_text(text, cancel_event=cancel_ev)
                if self.running and not self.paused and not self.muted and not self.cfg.json_stream:
                    self._log(f"{_C_EMERALD}🎙️  [VOZ CONTINUA ACTIVA · Turno #{self.turn_count}]{_C_RESET}")

        t = threading.Thread(target=_worker, daemon=True)
        self._active_turn_thread = t
        t.start()

    def _dispatch_text_turn(self, text: str) -> None:
        self.interrupt_active_turn(reason="text_turn")
        self._cancel_event = threading.Event()
        cancel_ev = self._cancel_event

        def _worker() -> None:
            with self._turn_lock:
                self.process_user_text(text, cancel_event=cancel_ev)

        t = threading.Thread(target=_worker, daemon=True)
        self._active_turn_thread = t
        t.start()

    def _apply_control_command(self, cmd: Dict[str, Any]) -> None:
        action = str(cmd.get("cmd") or "").strip().lower()
        if action == "stop":
            self.running = False
            self.interrupt_active_turn(reason="stop")
        elif action == "interrupt":
            self.interrupt_active_turn(reason="manual")
        elif action == "mute":
            self.muted = bool(cmd.get("value", not self.muted))
            if self.muted:
                self.segmenter.reset_utterance()
                self._set_state("muted")
            else:
                self._set_state("paused" if self.paused else "listening")
        elif action == "pause":
            self.paused = bool(cmd.get("value", not self.paused))
            if self.paused:
                self.interrupt_active_turn(reason="pause")
                self._set_state("paused")
            else:
                self._set_state("muted" if self.muted else "listening")
        elif action == "config":
            if "session_id" in cmd:
                self.session_id = str(cmd["session_id"] or "") or None
            if "lane" in cmd:
                self.cfg.lane = normalize_lane(cmd["lane"])
            if "temperature" in cmd and cmd["temperature"] is not None:
                self.cfg.temperature = max(0.0, min(1.5, float(cmd["temperature"])))
            if "max_tokens" in cmd and cmd["max_tokens"] is not None:
                self.cfg.max_tokens = max(64, min(4096, int(cmd["max_tokens"])))
            if "use_rag" in cmd:
                self.cfg.use_rag = bool(cmd["use_rag"])
            if "hardware_control" in cmd:
                self.cfg.hardware_control = bool(cmd["hardware_control"])
            if "voice" in cmd and cmd["voice"]:
                self.cfg.voice = resolve_voice_id(str(cmd["voice"]))
            if "speech_rate" in cmd:
                self.cfg.speech_rate = normalize_speech_rate(cmd["speech_rate"])
            if "barge_in" in cmd:
                self.cfg.barge_in = bool(cmd["barge_in"])
            if "barge_in_rms" in cmd and cmd["barge_in_rms"] is not None:
                self.cfg.barge_in_rms = max(0.02, min(0.5, float(cmd["barge_in_rms"])))
            if "silence_hold_ms" in cmd and cmd["silence_hold_ms"] is not None:
                self.cfg.silence_hold_ms = max(350, min(3000, int(cmd["silence_hold_ms"])))
                self.segmenter._hold_frames = max(1, self.cfg.silence_hold_ms // self.cfg.frame_ms)
            if "mute" in cmd:
                self.muted = bool(cmd["mute"])
            self._set_state("muted" if self.muted else ("paused" if self.paused else self._voice_state))
        elif action == "send_text":
            txt = str(cmd.get("text") or "").strip()
            if txt:
                self._dispatch_text_turn(txt)

    def _stdin_control_loop(self) -> None:
        if not sys.stdin:
            return
        if self.cfg.json_stream:
            while self.running:
                try:
                    line = sys.stdin.readline()
                    if line == "":
                        self.running = False
                        break
                    raw = line.strip()
                    if not raw:
                        continue
                    cmd = json.loads(raw)
                    if isinstance(cmd, dict):
                        self._apply_control_command(cmd)
                except Exception:
                    continue
            return

        if not sys.stdin.isatty():
            return
        while self.running:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.25)
                if not ready:
                    continue
                line = sys.stdin.readline()
                if line == "":
                    self.running = False
                    break
                txt = line.strip()
                if not txt:
                    if self.player.is_playing or self._active_request_id:
                        self.interrupt_active_turn(reason="manual")
                        self._log(f"{_C_YELLOW}⏹️  Interrupción manual. Te escucho...{_C_RESET}")
                    elif self.paused:
                        self.paused = False
                        self._log(f"{_C_EMERALD}🎙️  Escucha reactivada.{_C_RESET}")
                    continue
                low = txt.lower()
                if low in ("/salir", "/exit", "/quit", "/q"):
                    self.running = False
                    break
                if low in ("/pausa", "/pause"):
                    self.paused = not self.paused
                    self._log(f"{_C_YELLOW}Estado: {'PAUSADO' if self.paused else 'ESCUCHANDO'}{_C_RESET}")
                    continue
                if low == "/mute":
                    self.muted = not self.muted
                    self._log(f"{_C_YELLOW}Micrófono: {'SILENCIADO' if self.muted else 'ACTIVO'}{_C_RESET}")
                    continue
                if low.startswith("/voz ") or low.startswith("/voice "):
                    alias = txt.split(maxsplit=1)[1].strip()
                    self.cfg.voice = resolve_voice_id(alias)
                    self._log(f"{_C_EMERALD}✓ Voz:{_C_RESET} {self.cfg.voice}")
                    continue
                if low == "/new":
                    self.session_id = None
                    self._log(f"{_C_EMERALD}✓ Próximo turno abrirá una nueva sesión exclusiva.{_C_RESET}")
                    continue
                self._log(f"{_C_AMBER}tú (texto) ❯ {_C_RESET}{txt}")
                self._dispatch_text_turn(txt)
            except Exception:
                break

    def run(self) -> int:
        self.running = True
        self._set_state("warming", f"Precalentando faster-whisper ({self.cfg.whisper_model})...")
        if not self.cfg.json_stream:
            self._log(f"\n{_C_BOLD}{_C_EMERALD}━━━ UN MUNDO SIN CENSURA · VOZ CONTINUA FULL-DUPLEX ━━━{_C_RESET}")
            self._log(
                f"{_C_DIM}Modelo bloqueado:{_C_RESET} {_C_BOLD}{MODEL_LOCK}{_C_RESET} "
                f"{_C_DIM}| STT:{_C_RESET} faster-whisper ({self.cfg.whisper_model}) "
                f"{_C_DIM}| Voz:{_C_RESET} {_C_CYAN}{self.cfg.voice}{_C_RESET} "
                f"{_C_DIM}| Barge-In:{_C_RESET} {'ON' if self.cfg.barge_in else 'OFF'}"
            )
            self._log(
                f"{_C_DIM}Atajos: Enter=interrumpir · /pausa · /mute · /voz <dalia|jorge|elvira|alvaro|jenny> · /salir{_C_RESET}"
            )
            self._log(f"{_C_DIM}Precalentando Whisper local...{_C_RESET}")

        try:
            warm_s = self.stt.warmup()
            if not self.cfg.json_stream:
                self._log(f"{_C_EMERALD}✓ Whisper listo en {warm_s:.2f}s{_C_RESET}")
        except Exception as exc:
            self._set_state("error", f"Error inicializando faster-whisper: {exc}")
            self._log(f"{_C_RED}Error inicializando faster-whisper: {exc}{_C_RESET}")
            return 1

        try:
            self.mic.start()
        except Exception as exc:
            self._set_state("error", str(exc))
            self._log(f"{_C_RED}Error abriendo micrófono: {exc}{_C_RESET}")
            return 1

        ctrl_thread = threading.Thread(target=self._stdin_control_loop, daemon=True)
        ctrl_thread.start()

        if self.cfg.greeting and not self.cfg.no_play:
            self._speak_immediate("Canal de voz continua de Un Mundo Sin Censura activo. Te escucho.")

        self._set_state("listening", "Escucha continua activa")
        if not self.cfg.json_stream:
            self._log(f"{_C_EMERALD}🎙️  [ESCUCHA CONTINUA ACTIVA]{_C_RESET} Habla libremente sin pulsar botones.\n")

        try:
            while self.running:
                frame = self.mic.read_frame()
                if frame is None:
                    if not self.running:
                        break
                    continue

                if self.muted:
                    now = time.monotonic()
                    if self.cfg.json_stream and (now - self._last_level_emit) >= 0.12:
                        self._last_level_emit = now
                        self._emit_json({"type": "level", "rms": 0.0, "in_speech": False, "ai_speaking": self.player.is_playing})
                    continue

                ai_speaking = self.player.is_playing
                res = self.segmenter.process_frame(frame, ai_speaking=ai_speaking)

                now = time.monotonic()
                if self.cfg.json_stream and (now - self._last_level_emit) >= 0.065:
                    self._last_level_emit = now
                    self._emit_json({
                        "type": "level",
                        "rms": round(min(1.0, float(res["rms"]) * 6.5), 3),
                        "in_speech": bool(res["in_speech"]),
                        "ai_speaking": ai_speaking,
                    })

                if res["barge_in"]:
                    self.interrupt_active_turn(reason="barge_in")
                    self._set_state("speech_detected", "Barge-In detectado")
                    self._log(f"\n{_C_YELLOW}⚡ Barge-In detectado — te escucho...{_C_RESET}")
                elif res["in_speech"] and self._voice_state == "listening" and not self.paused:
                    self._set_state("speech_detected")

                if res["utterance"]:
                    self._dispatch_audio_utterance(res["utterance"])
        except KeyboardInterrupt:
            self._log(f"\n{_C_YELLOW}Cerrando conversación de voz continua...{_C_RESET}")
        finally:
            self.running = False
            self.interrupt_active_turn(reason="shutdown")
            self.mic.stop()
            self.player.shutdown()
            self._set_state("stopped")
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mundo-voice",
        description="Conversación por voz continua full-duplex exclusiva de Un Mundo Sin Censura",
    )
    ap.add_argument("--session", default=None, help="ID de sesión SQLite existente")
    ap.add_argument("--lane", choices=list(VALID_LANES), default="auto")
    ap.add_argument("--temperature", type=float, default=0.25)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--use-rag", action="store_true")
    ap.add_argument("--no-hw", action="store_true", help="Desactivar control de hardware Ring-0")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="Voz TTS (ej. es-MX-DaliaNeural o alias: dalia, jorge, elvira, alvaro, jenny)")
    ap.add_argument("--rate", default="+8%", help="Velocidad TTS (ej. +8%%, +0%%, 1.1)")
    ap.add_argument("--whisper-model", default=DEFAULT_WHISPER_MODEL)
    ap.add_argument("--lang", default=DEFAULT_LANGUAGE)
    ap.add_argument("--silence-ms", type=int, default=800, help="Silencio para cerrar turno en ms")
    ap.add_argument("--no-barge-in", action="store_true", help="Desactivar interrupción por voz durante TTS")
    ap.add_argument("--barge-in-rms", type=float, default=0.075)
    ap.add_argument("--greeting", action="store_true", help="Saludo hablado al iniciar")
    ap.add_argument("--no-play", action="store_true", help="No reproducir audio TTS en bocinas")
    ap.add_argument("--no-api", action="store_true", help="Usar MundoSinCensuraChatStore local sin HTTP :8757")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE)
    ap.add_argument("--json-stream", action="store_true", help="Protocolo NDJSON bidireccional (mundo-desktop)")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.json_stream:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(asctime)s [%(levelname)s] [MundoVoice] %(message)s",
        )
    else:
        logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

    cfg = MundoVoiceConfig(
        session_id=args.session,
        lane=args.lane,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        use_rag=bool(args.use_rag),
        hardware_control=not args.no_hw,
        voice=resolve_voice_id(args.voice),
        speech_rate=normalize_speech_rate(args.rate),
        whisper_model=args.whisper_model,
        language=args.lang,
        silence_hold_ms=args.silence_ms,
        barge_in=not args.no_barge_in,
        barge_in_rms=args.barge_in_rms,
        greeting=bool(args.greeting),
        no_play=bool(args.no_play),
        json_stream=bool(args.json_stream),
        api_base=args.api_base.rstrip("/"),
        prefer_api=not args.no_api,
    )
    engine = MundoContinuousVoiceEngine(cfg)

    def _on_term(_sig, _frame):
        engine.running = False

    signal.signal(signal.SIGTERM, _on_term)
    return engine.run()


if __name__ == "__main__":
    raise SystemExit(main())
