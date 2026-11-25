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

import asyncio
from collections import OrderedDict, deque
import ctypes
from dataclasses import dataclass, field
import datetime
import io
import json
import logging
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VOICE_RUNTIME = Path.home() / ".local" / "share" / "tardis-voice"
VOICE_LIB = VOICE_RUNTIME / "lib"
MODEL_CACHE = VOICE_RUNTIME / "models"
PIPER_MODELS_DIR = VOICE_RUNTIME / "piper"

if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
    sys.path.insert(0, str(VOICE_LIB))

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

try:
    from scipy import signal as scipy_signal
    HAS_SCIPY = True
except Exception:
    scipy_signal = None  # type: ignore[assignment]
    HAS_SCIPY = False

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore[assignment]
    HAS_PSUTIL = False

logger = logging.getLogger("TARDIS.VoiceEngine")

SAMPLE_RATE = 16000
PIPER_SAMPLE_RATE = 22050
TEMPORAL_BRAIN_SOCK = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
VOICE_OLLAMA_URL = os.environ.get("TARDIS_VOICE_OLLAMA_URL", "http://127.0.0.1:11435").rstrip("/")
VOICE_OLLAMA_MODEL = os.environ.get("TARDIS_VOICE_OLLAMA_MODEL", "qwen3-vl:2b-instruct")
VOICE_OLLAMA_NUM_CTX = int(os.environ.get("TARDIS_VOICE_OLLAMA_CTX", "3072"))
VOICE_OLLAMA_NUM_GPU = int(os.environ.get("TARDIS_VOICE_OLLAMA_NUM_GPU", "22"))
MAIN_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
TARDIS_TOKEN_FILE = Path(
    os.environ.get(
        "TARDIS_TOKEN_FILE",
        str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"),
    )
)

DEFAULT_TTS_MODE = os.environ.get("TARDIS_TTS_MODE", "local").strip().lower()
DEFAULT_LOCAL_VOICE = os.environ.get("TARDIS_LOCAL_VOICE", "es_MX-claude-high")
DEFAULT_EDGE_VOICE = os.environ.get("TARDIS_TTS_VOICE", "es-MX-DaliaNeural")
DEFAULT_STT_MODEL = os.environ.get("TARDIS_STT_MODEL", "auto")
DEFAULT_STT_DEVICE = os.environ.get("TARDIS_STT_DEVICE", "auto")
DEFAULT_LANGUAGE = os.environ.get("TARDIS_VOICE_LANG", "es")

# Vocabulario soberano para sesgar el decodificador de Whisper hacia términos reales del ecosistema
SOVEREIGN_DOMAIN_PROMPT = (
    "Conversación y dictado en español de México con TARDIS, el asistente del Arquitecto. "
    "Términos frecuentes: TARDIS, Arquitecto, FTL, KAIJU, GIA, GODWORKS, Ollama, PipeWire, "
    "TemporalBrain, Whisper, Piper, Silero, Hyprland, RTX 3050, Tapo C310, Antigravity, "
    "Lentes EVOIR, Bluetooth, Linux, Python, systemd, kernel, PSI, CPU, GPU, RAM, VRAM, "
    "Wi-Fi, GitHub, API, WebSocket, programa, dictado."
)

SOVEREIGN_HOTWORDS = (
    "TARDIS Arquitecto FTL KAIJU GIA GODWORKS Ollama PipeWire TemporalBrain "
    "Whisper Piper Hyprland EVOIR Tapo C310 Antigravity systemd"
)

LOCAL_PIPER_VOICES: Dict[str, Dict[str, Any]] = {
    "es_MX-claude-high": {
        "id": "es_MX-claude-high",
        "label": "TARDIS Local · Claude (es-MX Neural Offline)",
        "lang": "es-MX",
        "gender": "Female",
        "engine": "piper",
        "file": "es_MX-claude-high.onnx",
        "sample_rate": 22050,
    },
    "es_MX-ald-medium": {
        "id": "es_MX-ald-medium",
        "label": "TARDIS Local · Ald (es-MX Neural Offline)",
        "lang": "es-MX",
        "gender": "Male",
        "engine": "piper",
        "file": "es_MX-ald-medium.onnx",
        "sample_rate": 22050,
    },
}

EDGE_VOICES: List[Dict[str, str]] = [
    {"id": "es-MX-DaliaNeural", "label": "Cortana · Dalia (es-MX Edge)", "lang": "es-MX", "gender": "Female", "engine": "edge-tts"},
    {"id": "es-MX-JorgeNeural", "label": "Jorge Neural (es-MX Edge)", "lang": "es-MX", "gender": "Male", "engine": "edge-tts"},
    {"id": "es-ES-ElviraNeural", "label": "Elvira Neural (es-ES Edge)", "lang": "es-ES", "gender": "Female", "engine": "edge-tts"},
    {"id": "es-ES-AlvaroNeural", "label": "Álvaro Neural (es-ES Edge)", "lang": "es-ES", "gender": "Male", "engine": "edge-tts"},
    {"id": "en-US-JennyNeural", "label": "Cortana · Jenny (en-US Edge)", "lang": "en-US", "gender": "Female", "engine": "edge-tts"},
]

VOICE_ALIASES: Dict[str, str] = {
    "local": "es_MX-claude-high",
    "piper": "es_MX-claude-high",
    "claude": "es_MX-claude-high",
    "tardis": "es_MX-claude-high",
    "femenina": "es_MX-claude-high",
    "ald": "es_MX-ald-medium",
    "masculina": "es_MX-ald-medium",
    "dalia": "es-MX-DaliaNeural",
    "cortana": "es-MX-DaliaNeural",
    "jorge": "es-MX-JorgeNeural",
    "elvira": "es-ES-ElviraNeural",
    "alvaro": "es-ES-AlvaroNeural",
    "álvaro": "es-ES-AlvaroNeural",
    "jenny": "en-US-JennyNeural",
}

EXTENDED_WHISPER_HALLUCINATIONS = frozenset({
    "subtitulos realizados por la comunidad de amara.org",
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulos por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "subtitulos realizados por la comunidad de amara org",
    "subtítulos realizados por la comunidad de amara org",
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "gracias por ver",
    "gracias por ver este video",
    "gracias por ver este vídeo",
    "suscribete al canal",
    "suscríbete al canal",
    "suscribete",
    "suscríbete",
    "no olvides suscribirte",
    "dale like",
    "hasta la proxima",
    "hasta la próxima",
    "amara.org",
    "amara org",
    "musica",
    "música",
    "aplausos",
    "silencio",
    "amen",
    "amén",
    "...",
    "..",
    ".",
    "you",
    "thank you",
    "thank you.",
    "thanks for watching",
    "thanks for watching.",
    "mbc",
    "bye",
    "bye.",
    "transcripcion",
    "transcripción",
})


# ==============================================================================
# 1. UTILIDADES CUDA / HARDWARE / VRAM SEGURA
# ==============================================================================

_CUDA_LIBS_PRELOADED = False
_CUDA_LOCK = threading.Lock()
_VRAM_CACHE: Tuple[float, int, int] = (0.0, 0, 0)  # (ts, used_mb, free_mb)


def preload_cuda_libraries() -> bool:
    """
    Precarga libcublas.so.12 / libcublasLt.so.12 desde las rutas locales de TARDIS
    usando RTLD_GLOBAL para que CTranslate2/faster-whisper acceda a CUDA sin requerir
    LD_LIBRARY_PATH externo.
    """
    global _CUDA_LIBS_PRELOADED
    with _CUDA_LOCK:
        if _CUDA_LIBS_PRELOADED:
            return True
        search_dirs = [
            Path.home() / ".local" / "lib" / "temporal_brain" / "cuda_v12",
            Path.home() / ".local" / "lib" / "ollama" / "cuda_v12",
            Path.home() / ".local" / "lib" / "temporal_brain",
        ]
        loaded_any = False
        for d in search_dirs:
            if not d.is_dir():
                continue
            for lib_name in ("libcublasLt.so.12", "libcublas.so.12"):
                candidate = d / lib_name
                if candidate.is_file():
                    try:
                        ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                        loaded_any = True
                    except OSError:
                        pass
            if loaded_any:
                break
        _CUDA_LIBS_PRELOADED = loaded_any
        return loaded_any


def query_gpu_vram_mb(cache_ttl: float = 4.0) -> Tuple[int, int]:
    """Devuelve (used_mb, free_mb) de la GPU NVIDIA o (0, 0) si no está disponible."""
    global _VRAM_CACHE
    now = time.monotonic()
    if (now - _VRAM_CACHE[0]) < cache_ttl and _VRAM_CACHE[0] > 0:
        return _VRAM_CACHE[1], _VRAM_CACHE[2]
    if not shutil.which("nvidia-smi"):
        return 0, 0
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            stdin=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        ).strip()
        first = out.splitlines()[0]
        used_s, free_s = [x.strip() for x in first.split(",")[:2]]
        used_mb, free_mb = int(used_s), int(free_s)
        _VRAM_CACHE = (now, used_mb, free_mb)
        return used_mb, free_mb
    except Exception:
        return 0, 0


def query_cpu_freq_mhz() -> float:
    try:
        raw = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read_text(encoding="ascii").strip()
        return round(float(raw) / 1000.0, 1)
    except Exception:
        return 0.0


# ==============================================================================
# 2. PREPROCESAMIENTO ACÚSTICO DSP PARA STT DE ALTA PRECISIÓN
# ==============================================================================

_HPF_SOS = None
if HAS_SCIPY and scipy_signal is not None:
    try:
        # Filtro pasa-altos Butterworth 2do orden @ 85 Hz para 16 kHz
        _HPF_SOS = scipy_signal.butter(2, 85.0 / (SAMPLE_RATE * 0.5), btype="highpass", output="sos")
    except Exception:
        _HPF_SOS = None


def preprocess_pcm_for_stt(
    pcm_bytes: bytes,
    sample_rate: int = SAMPLE_RATE,
    apply_hpf: bool = True,
    apply_agc: bool = True,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Acondiciona audio PCM16 mono 16 kHz antes de Whisper:
      1. Conversión int16 -> float32 [-1, 1] y remoción de DC offset.
      2. Filtro pasa-altos 85 Hz (suprime ventilador, retumbo y artefactos HFP).
      3. Estimación de ruido y ganancia adaptativa (AGC suave) sobre señal activa
         con limitación suave tanh para no recortar picos.
    """
    if not pcm_bytes:
        return np.zeros(0, dtype=np.float32), {"rms_in": 0.0, "rms_out": 0.0, "peak": 0.0, "duration_s": 0.0, "gain": 1.0}

    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    audio = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        return audio, {"rms_in": 0.0, "rms_out": 0.0, "peak": 0.0, "duration_s": 0.0, "gain": 1.0}

    # 1. Quitar offset DC
    audio = audio - float(np.mean(audio))
    rms_in = float(np.sqrt(np.mean(audio * audio)))

    # 2. Pasa-altos Butterworth 85 Hz
    if apply_hpf and audio.size >= 64:
        if _HPF_SOS is not None and sample_rate == SAMPLE_RATE and scipy_signal is not None:
            try:
                audio = scipy_signal.sosfilt(_HPF_SOS, audio).astype(np.float32)
            except Exception:
                pass
        else:
            # Filtro pasa-altos de primer orden ligero en NumPy puro si no hay scipy
            alpha = 0.965
            out = np.empty_like(audio)
            out[0] = audio[0]
            out[1:] = audio[1:] - alpha * audio[:-1]
            audio = out

    # 3. AGC suave basado en energía de tramas activas (top 30% RMS)
    gain = 1.0
    snr_est_db = 0.0
    if apply_agc and audio.size >= 320:
        frame_len = 320  # 20ms @ 16kHz
        n_frames = audio.size // frame_len
        if n_frames >= 3:
            framed = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
            frame_rms = np.sqrt(np.mean(framed * framed, axis=1))
            noise_est = float(np.percentile(frame_rms, 15))
            speech_est = float(np.percentile(frame_rms, 85))
            if noise_est > 1e-6:
                snr_est_db = float(20.0 * np.log10(max(speech_est, 1e-6) / noise_est))
            # Solo amplificar si hay señal vocal real por encima del piso de ruido
            if speech_est > 0.0045:
                target_rms = 0.095
                desired_gain = target_rms / max(speech_est, 1e-4)
                # Limitar ganancia a [0.65, 6.0] (+15.5 dB max) para no disparar ruido
                gain = float(np.clip(desired_gain, 0.65, 6.0))
                if abs(gain - 1.0) > 0.08:
                    audio = audio * gain
                    # Limitador suave para evitar clipping duro en picos
                    peak_after = float(np.max(np.abs(audio)))
                    if peak_after > 0.92:
                        audio = (0.95 * np.tanh(audio / 0.95)).astype(np.float32)

    rms_out = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    metrics = {
        "rms_in": round(rms_in, 5),
        "rms_out": round(rms_out, 5),
        "peak": round(peak, 4),
        "duration_s": round(audio.size / float(sample_rate), 3),
        "gain": round(gain, 2),
        "snr_est_db": round(snr_est_db, 1),
    }
    return audio.astype(np.float32, copy=False), metrics


# ==============================================================================
# 3. SILERO VAD v6 NEURAL STREAMING + SEGMENTADOR ADAPTATIVO CON BARGE-IN
# ==============================================================================

class SileroVadStream:
    """
    Detector de actividad vocal neural Silero VAD v6 (ONNX Runtime CPU, 1 hilo).
    Consume tramas PCM16 de cualquier tamaño (30 ms, 20 ms, 32 ms) y actualiza
    el estado LSTM (h, c) en bloques exactos de 512 muestras + 64 de contexto.
    """

    WINDOW_SAMPLES = 512
    CONTEXT_SAMPLES = 64

    def __init__(self, onnx_path: Optional[Path] = None):
        self._session = None
        self._onnx_path = onnx_path or self._find_model_path()
        self._ctx = np.zeros((1, self.CONTEXT_SAMPLES), dtype=np.float32)
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._last_prob = 0.0
        self._lock = threading.Lock()
        self._init_session()

    @staticmethod
    def _find_model_path() -> Optional[Path]:
        candidates = [
            VOICE_LIB / "faster_whisper" / "assets" / "silero_vad_v6.onnx",
            VOICE_RUNTIME / "models" / "silero_vad_v6.onnx",
        ]
        for c in candidates:
            if c.is_file():
                return c
        try:
            import faster_whisper
            p = Path(faster_whisper.__file__).resolve().parent / "assets" / "silero_vad_v6.onnx"
            if p.is_file():
                return p
        except Exception:
            pass
        return None

    def _init_session(self) -> None:
        if not self._onnx_path or not self._onnx_path.is_file():
            return
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3
            self._session = ort.InferenceSession(
                str(self._onnx_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
        except Exception as exc:
            logger.debug("Silero VAD v6 no pudo cargarse (%s); usando respaldo", exc)
            self._session = None

    @property
    def available(self) -> bool:
        return self._session is not None

    def reset(self) -> None:
        with self._lock:
            self._ctx.fill(0.0)
            self._h.fill(0.0)
            self._c.fill(0.0)
            self._pending = np.zeros(0, dtype=np.float32)
            self._last_prob = 0.0

    def speech_probability(self, pcm_bytes: bytes) -> float:
        """Devuelve probabilidad vocal [0.0, 1.0] para la trama PCM16 mono 16kHz."""
        if self._session is None or not pcm_bytes:
            return 0.0
        usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
        if usable <= 0:
            return self._last_prob
        samples = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            buf = np.concatenate([self._pending, samples]) if self._pending.size else samples
            max_prob = 0.0
            ran = False
            offset = 0
            while (buf.size - offset) >= self.WINDOW_SAMPLES:
                chunk = buf[offset : offset + self.WINDOW_SAMPLES].reshape(1, self.WINDOW_SAMPLES)
                inp = np.concatenate([self._ctx, chunk], axis=1)
                probs, hn, cn = self._session.run(
                    None,
                    {"input": inp, "h": self._h, "c": self._c},
                )
                self._h = hn
                self._c = cn
                self._ctx = chunk[:, -self.CONTEXT_SAMPLES :]
                p = float(probs.reshape(-1)[0])
                if p > max_prob:
                    max_prob = p
                ran = True
                offset += self.WINDOW_SAMPLES
            self._pending = buf[offset:]
            if ran:
                self._last_prob = max_prob
            return self._last_prob


@dataclass
class SegmenterConfig:
    sample_rate: int = SAMPLE_RATE
    frame_ms: int = 30
    vad_aggressiveness: int = 2
    silence_hold_ms: int = 740
    long_speech_hold_ms: int = 1080
    dictation_hold_ms: int = 1350
    min_speech_ms: int = 240
    max_utterance_ms: int = 30000
    pre_roll_ms: int = 360
    barge_in: bool = True
    barge_in_rms: float = 0.068
    barge_in_frames: int = 8
    silero_start_prob: float = 0.46
    silero_cont_prob: float = 0.28
    silero_barge_prob: float = 0.72
    use_silero: bool = True
    dictation_mode: bool = False


class AdaptiveSpeechSegmenter:
    """
    Segmentador híbrido neural (Silero VAD v6 + WebRTC VAD + RMS adaptativo) con:
      - Pre-roll 360 ms para no truncar consonantes iniciales.
      - Paciencia adaptativa: cierre ágil (~740ms) en frases cortas y paciencia
        extendida (~1.08s-1.35s) en dictados largos para no cortar pausas naturales.
      - Barge-In anti-eco calibrado para bocinas y Lentes EVOIR Bluetooth.
    """

    def __init__(self, cfg: Optional[SegmenterConfig] = None, silero: Optional[SileroVadStream] = None):
        self.cfg = cfg or SegmenterConfig()
        self.silero = silero if silero is not None else (SileroVadStream() if self.cfg.use_silero else None)
        if self.silero is not None and not self.silero.available:
            self.silero = None
        self.vad = webrtcvad.Vad(self.cfg.vad_aggressiveness) if HAS_WEBRTCVAD else None
        self.noise_floor = 0.008
        self.in_speech = False
        self.speech_frames: List[bytes] = []
        self.voiced_frame_count = 0
        self.pre_roll: Deque[bytes] = deque(maxlen=max(1, self.cfg.pre_roll_ms // self.cfg.frame_ms))
        self.silence_frames = 0
        self.barge_streak = 0
        self._update_frame_budgets()

    def _update_frame_budgets(self) -> None:
        fm = max(10, self.cfg.frame_ms)
        self._base_hold_frames = max(1, self.cfg.silence_hold_ms // fm)
        self._long_hold_frames = max(self._base_hold_frames, self.cfg.long_speech_hold_ms // fm)
        self._dictation_hold_frames = max(self._long_hold_frames, self.cfg.dictation_hold_ms // fm)
        self._min_frames = max(1, self.cfg.min_speech_ms // fm)
        self._max_frames = max(10, self.cfg.max_utterance_ms // fm)

    def set_silence_hold_ms(self, ms: int) -> None:
        self.cfg.silence_hold_ms = max(350, min(3000, int(ms)))
        self.cfg.long_speech_hold_ms = max(self.cfg.silence_hold_ms, int(self.cfg.silence_hold_ms * 1.42))
        self._update_frame_budgets()

    def set_dictation_mode(self, enabled: bool) -> None:
        self.cfg.dictation_mode = bool(enabled)

    def reset_utterance(self) -> None:
        self.in_speech = False
        self.speech_frames.clear()
        self.voiced_frame_count = 0
        self.silence_frames = 0
        self.barge_streak = 0
        if self.silero is not None:
            self.silero.reset()

    def get_current_speech_pcm(self, max_seconds: float = 12.0) -> Tuple[bytes, float]:
        """Devuelve una instantánea segura del audio hablado en curso para vista previa en vivo."""
        if not self.in_speech or not self.speech_frames:
            return b"", 0.0
        frames = list(self.speech_frames)
        max_frames = max(1, int((max_seconds * 1000.0) / max(10, self.cfg.frame_ms)))
        if len(frames) > max_frames:
            frames = frames[-max_frames:]
        pcm = b"".join(frames)
        dur_s = len(pcm) / float(max(1, self.cfg.sample_rate) * 2)
        return pcm, dur_s

    @staticmethod
    def frame_rms(frame: bytes) -> float:
        if not frame or len(frame) < 2:
            return 0.0
        usable = len(frame) - (len(frame) % 2)
        pcm = np.frombuffer(frame[:usable], dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(pcm * pcm)))

    def _detect_voice(self, frame: bytes, rms: float, threshold: float, continuing: bool) -> Tuple[bool, float]:
        prob = 0.0
        if self.silero is not None:
            prob = self.silero.speech_probability(frame)
            p_thresh = self.cfg.silero_cont_prob if continuing else self.cfg.silero_start_prob
            # Exige probabilidad neural Silero + un piso energético mínimo para ignorar ruido eléctrico
            min_e = threshold * (0.45 if continuing else 0.62)
            return (prob >= p_thresh and rms >= max(0.0055, min_e)), prob

        energy_ok = rms > threshold
        if self.vad is None:
            return energy_ok, (1.0 if energy_ok else 0.0)
        try:
            vad_ok = self.vad.is_speech(frame, self.cfg.sample_rate)
        except Exception:
            vad_ok = energy_ok
        ok = vad_ok and rms > (threshold * (0.62 if continuing else 0.72))
        return ok, (0.85 if ok else 0.05)

    def _effective_hold_frames(self) -> int:
        if self.cfg.dictation_mode:
            return self._dictation_hold_frames
        # Tras >2.4s de locución continua, ampliar paciencia para pausas reflexivas
        speech_ms = len(self.speech_frames) * self.cfg.frame_ms
        if speech_ms >= 2400:
            return self._long_hold_frames
        return self._base_hold_frames

    def process_frame(self, frame: bytes, ai_speaking: bool = False) -> Dict[str, Any]:
        rms = self.frame_rms(frame)
        threshold = max(0.010, self.noise_floor * 2.35)

        if ai_speaking:
            if self.cfg.barge_in:
                barge_thresh = max(self.cfg.barge_in_rms, self.noise_floor * 4.6)
                prob = 0.0
                if self.silero is not None:
                    prob = self.silero.speech_probability(frame)
                    voice_hit = (prob >= self.cfg.silero_barge_prob) and (rms >= barge_thresh)
                else:
                    vad_hit = True
                    if self.vad is not None:
                        try:
                            vad_hit = self.vad.is_speech(frame, self.cfg.sample_rate)
                        except Exception:
                            vad_hit = True
                    voice_hit = vad_hit and (rms >= barge_thresh)

                if voice_hit:
                    self.barge_streak += 1
                    self.pre_roll.append(frame)
                    if self.barge_streak >= self.cfg.barge_in_frames:
                        self.in_speech = True
                        self.speech_frames = list(self.pre_roll)
                        self.voiced_frame_count = self.barge_streak
                        self.silence_frames = 0
                        self.barge_streak = 0
                        return {
                            "utterance": None,
                            "barge_in": True,
                            "rms": rms,
                            "vad_prob": prob,
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
                "vad_prob": 0.0,
                "in_speech": False,
            }

        self.barge_streak = 0
        is_voice, prob = self._detect_voice(frame, rms, threshold, continuing=self.in_speech)

        if not self.in_speech:
            self.noise_floor = 0.98 * self.noise_floor + 0.02 * min(rms, 0.032)
            self.pre_roll.append(frame)
            if is_voice:
                self.in_speech = True
                self.speech_frames = list(self.pre_roll)
                self.voiced_frame_count = 1
                self.silence_frames = 0
            return {
                "utterance": None,
                "barge_in": False,
                "rms": rms,
                "vad_prob": prob,
                "in_speech": self.in_speech,
            }

        self.speech_frames.append(frame)
        if is_voice:
            self.voiced_frame_count += 1
            self.silence_frames = 0
        else:
            self.silence_frames += 1

        hold_limit = self._effective_hold_frames()
        if self.silence_frames >= hold_limit or len(self.speech_frames) >= self._max_frames:
            frames = list(self.speech_frames)
            voiced = self.voiced_frame_count
            self.reset_utterance()
            # Descartar micro-ruidos sin suficientes tramas vocales reales
            min_voiced = max(2, self._min_frames // 2)
            if len(frames) >= self._min_frames and voiced >= min_voiced:
                return {
                    "utterance": b"".join(frames),
                    "barge_in": False,
                    "rms": rms,
                    "vad_prob": prob,
                    "in_speech": False,
                }
        return {
            "utterance": None,
            "barge_in": False,
            "rms": rms,
            "vad_prob": prob,
            "in_speech": self.in_speech,
        }


# ==============================================================================
# 4. NORMALIZACIÓN DE DICTADO Y FILTRO ANTI-ALUCINACIONES
# ==============================================================================

def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_key(text: str) -> str:
    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9ñ]+", " ", s)
    return " ".join(s.split())


def is_whisper_hallucination(text: str) -> bool:
    """Detecta alucinaciones clásicas de Whisper y bucles repetitivos degenerados."""
    raw = (text or "").strip()
    if not raw:
        return True
    norm = re.sub(r"\s+", " ", raw.lower()).strip()
    norm_clean = re.sub(r"^[.,!?;:¡¿\-–—\s\"'()]+|[.,!?;:¡¿\-–—\s\"'()]+$", "", norm)
    if not norm_clean or len(norm_clean) < 2:
        return True
    if norm in EXTENDED_WHISPER_HALLUCINATIONS or norm_clean in EXTENDED_WHISPER_HALLUCINATIONS:
        return True
    if strip_accents(norm_clean) in EXTENDED_WHISPER_HALLUCINATIONS:
        return True

    # Detección de bucles repetitivos (ej. "gracias gracias gracias gracias")
    words = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9]+", norm_clean)
    if len(words) >= 5:
        unique_ratio = len(set(words)) / float(len(words))
        if unique_ratio <= 0.25:
            return True
    # Repetición exacta de la misma palabra 4+ veces seguidas
    if re.search(r"\b(\w{2,})(?:\s+\1){3,}\b", norm_clean):
        return True
    return False


class DictationNormalizer:
    """
    Normaliza transcripciones de dictado por voz en español mexicano/técnico:
      - Correcciones fonéticas conscientes del contexto (sin tocar 'buenas tardes').
      - Limpieza de muletillas vacilantes y duplicaciones por tartamudeo.
      - Comandos hablados de puntuación/formato en modo dictado.
      - Detección de enunciados incompletos para coalescencia fluida.
    """

    # Correcciones seguras aplicables siempre (términos inequívocos mal transcritos)
    _DOMAIN_SUBS: Tuple[Tuple[re.Pattern[str], str], ...] = (
        # Vocativos y usos de "TARDIS" mal transcritos como "tardes" / "tardiz" / "tar dis"
        (re.compile(r"(?i)\b(?:hola|oye|hey|ey|oiga|escucha)\s+tardes\b"), lambda m: m.group(0).split()[0] + " TARDIS"),  # type: ignore[arg-type]
        (re.compile(r"(?i)^tardes(?=\s*[,:?¿!¡]|\s+(?:est[aá]s|dime|explica|expl[ií]came|analiza|busca|investiga|programa|ay[uú]dame|abre|cierra|pausa|despierta|silencio|cu[eé]ntame|resume|haz|crea|ejecuta|activa|desactiva))"), "TARDIS"),
        (re.compile(r"(?i)\b(?:tardiz|tard[ií]s|tar\s+dis)\b"), "TARDIS"),
        # Ecosistema GODWORKS / FTL / KAIJU / GIA / Linux / Hardware
        (re.compile(r"(?i)\b(?:efe\s+te\s+ele|f\s+t\s+l|fetel|efetel)\b"), "FTL"),
        (re.compile(r"(?i)\b(?:kaiyu|cay[uú]|caillou|kayu|kaichu|kai\s+ju)\b"), "KAIJU"),
        (re.compile(r"(?i)\b(?:o\s+llama|holama|olama|o-llama)\b"), "Ollama"),
        (re.compile(r"(?i)\b(?:paip\s*guayer|pipe\s+wire|paip\s+wire|paipewire)\b"), "PipeWire"),
        (re.compile(r"(?i)\b(?:g[uü]isper|wisper|guisper|whis\s+per)\b"), "Whisper"),
        (re.compile(r"(?i)\b(?:paiper\s+t\s*t\s*s|piper\s+t\s*t\s*s)\b"), "Piper TTS"),
        (re.compile(r"(?i)\b(?:hiperland|hyper\s+land|haiperland)\b"), "Hyprland"),
        (re.compile(r"(?i)\b(?:antigraviti|anti\s+gravity|antigravity\s+cli)\b"), "Antigravity"),
        (re.compile(r"(?i)\b(?:god\s+works|godworx|god\s+worx)\b"), "GODWORKS"),
        (re.compile(r"(?i)\b(?:ge\s+i\s+a|g\s+i\s+a)\b"), "GIA"),
        (re.compile(r"(?i)\b(?:c\s+trescientos\s+diez|ce\s+310|c\s+310)\b"), "C310"),
        (re.compile(r"(?i)\b(?:r\s*t\s*x\s+tres\s+mil\s+cincuenta|r\s+t\s+x\s+3050)\b"), "RTX 3050"),
        (re.compile(r"(?i)\b(?:lentes\s+(?:e\s*voir|ebor|evo\s*ir|evoyr))\b"), "lentes EVOIR"),
        (re.compile(r"(?i)\b(?:system\s+d|sisten\s+d)\b"), "systemd"),
        (re.compile(r"(?i)\b(?:ge\s+pe\s+u|g\s+p\s+u)\b"), "GPU"),
        (re.compile(r"(?i)\b(?:ce\s+pe\s+u|c\s+p\s+u)\b"), "CPU"),
        (re.compile(r"(?i)\b(?:u\s+ve\s+ram|v\s+ram|uve\s+ram)\b"), "VRAM"),
        (re.compile(r"(?i)\b(?:te\s+te\s+ese|t\s+t\s+s)\b"), "TTS"),
        (re.compile(r"(?i)\b(?:ese\s+te\s+te|s\s+t\s+t)\b"), "STT"),
        (re.compile(r"(?i)\b(?:ve\s+a\s+de|v\s+a\s+d)\b"), "VAD"),
    )

    # Muletillas iniciales comunes al comenzar a hablar
    _LEADING_FILLERS = re.compile(
        r"^(?:(?:eh+|emm+|mmm+|amm+|ahh+|umm+|este+|bueno\s+este)\s*[,….\s]+)+",
        re.IGNORECASE,
    )
    # Palabras cortas repetidas accidentalmente por vacilación ("quiero quiero" -> "quiero")
    _STUTTER_RE = re.compile(
        r"(?i)\b(el|la|los|las|un|una|de|que|en|y|o|pero|para|por|con|a|me|te|se|lo|mi|tu|es|quiero|puedes|como|cómo)\s+\1\b"
    )

    # Comandos de puntuación hablados (aplicados en modo dictado)
    _DICTATION_PUNCT: Tuple[Tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+aparte|nueva\s+l[ií]nea|salto\s+de\s+l[ií]nea)\b\s*"), ".\n"),
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+seguido|punto\s+final)\b\s*"), ". "),
        (re.compile(r"(?i)\s*\b(?:dos\s+puntos)\b\s*"), ": "),
        (re.compile(r"(?i)\s*\b(?:punto\s+y\s+coma)\b\s*"), "; "),
        (re.compile(r"(?i)\s*\b(?:abre\s+par[eé]ntesis|abrir\s+par[eé]ntesis)\b\s*"), " ("),
        (re.compile(r"(?i)\s*\b(?:cierra\s+par[eé]ntesis|cerrar\s+par[eé]ntesis)\b\s*"), ") "),
        (re.compile(r"(?i)\s*\b(?:signo\s+de\s+interrogaci[oó]n)\b\s*"), "? "),
        (re.compile(r"(?i)\s*\b(?:signo\s+de\s+exclamaci[oó]n)\b\s*"), "! "),
        (re.compile(r"(?i)\s*,\s*\bcoma\b\s*|\s+\bcoma\b(?=\s|$)"), ", "),
    )

    # Conectores abiertos que indican que el usuario probablemente va a continuar la frase
    _TRAILING_CONNECTORS = frozenset({
        "y", "e", "o", "u", "pero", "sino", "porque", "aunque", "que",
        "para", "por", "con", "sin", "sobre", "entre", "hacia", "desde",
        "de", "del", "al", "el", "la", "los", "las", "un", "una", "unos", "unas",
        "como", "cuando", "donde", "si", "entonces", "ademas", "tambien",
        "mientras", "cuyo", "cuya", "mi", "tu", "su",
    })

    _ALONE_STARTERS = frozenset({
        "oye", "mira", "espera", "escucha", "este", "bueno", "entonces", "pues",
    })

    def normalize(self, text: str, dictation_mode: bool = False) -> Tuple[str, List[str]]:
        """Aplica corrección de dictado y devuelve (texto_normalizado, correcciones_aplicadas)."""
        raw = re.sub(r"\s+", " ", (text or "").strip())
        if not raw:
            return "", []

        corrections: List[str] = []
        out = raw

        # 1. Limpiar muletillas al inicio
        cleaned_fillers = self._LEADING_FILLERS.sub("", out).strip()
        if cleaned_fillers and cleaned_fillers != out:
            corrections.append("fillers_trimmed")
            out = cleaned_fillers

        # 2. Correcciones fonéticas de dominio TARDIS/técnico
        for pattern, repl in self._DOMAIN_SUBS:
            new_out = pattern.sub(repl, out)
            if new_out != out:
                corrections.append(f"domain:{repl if isinstance(repl, str) else 'vocative_TARDIS'}")
                out = new_out

        # 3. Quitar duplicaciones por tartamudeo de dictado
        dedup = self._STUTTER_RE.sub(r"\1", out)
        if dedup != out:
            corrections.append("stutter_collapsed")
            out = dedup

        # 4. Puntuación dictada explícita (solo en modo dictado o frases con comandos claros)
        if dictation_mode:
            for pattern, repl in self._DICTATION_PUNCT:
                new_out = pattern.sub(repl, out)
                if new_out != out:
                    corrections.append("dictation_punct")
                    out = new_out

        # 5. Limpieza tipográfica y capitalización
        out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)
        out = re.sub(r"\.{2,}", ".", out)
        out = re.sub(r"[ \t]{2,}", " ", out).strip()
        if out and out[0].islower():
            out = out[0].upper() + out[1:]

        return out, corrections

    def is_incomplete_utterance(self, text: str) -> bool:
        """
        Determina si el texto dictado parece una frase a medio decir (para esperar
        brevemente la continuación y fusionarla en vez de cortar la conversación).
        """
        s = (text or "").strip()
        if not s:
            return False
        # Si cierra con signo de interrogación o exclamación, es un turno completo
        if s.endswith(("?", "!")):
            return False
        tokens = normalize_key(s).split()
        if not tokens:
            return False
        # Un saludo o comando corto válido NO es incompleto
        if len(tokens) == 1 and tokens[0] in ("hola", "tardis", "gracias", "ok", "si", "no", "para", "pausa", "silencio", "repite", "salir"):
            return False
        if len(tokens) == 1 and tokens[0] in self._ALONE_STARTERS:
            return True
        if len(tokens) <= 2 and tokens[0] in ("oye", "hola", "hey") and tokens[-1] == "tardis":
            # "Oye TARDIS" -> puede continuar inmediatamente con la pregunta, salvo pausa
            return True
        if tokens[-1] in self._TRAILING_CONNECTORS and len(tokens) >= 2:
            return True
        return False


class UtteranceCoalescer:
    """
    Fusiona fragmentos consecutivos de dictado entrecortado dentro de una ventana corta
    (ej. 'Oye TARDIS, explícame sobre...' + [pausa 1s] + '...los agujeros negros').
    """

    def __init__(self, normalizer: Optional[DictationNormalizer] = None, max_wait_s: float = 2.0):
        self.normalizer = normalizer or DictationNormalizer()
        self.max_wait_s = max_wait_s
        self._buffer: List[str] = []
        self._last_ts: float = 0.0
        self._lock = threading.Lock()

    def push(self, fragment: str) -> Tuple[Optional[str], bool]:
        """
        Agrega un fragmento transcrito.
        Retorna (texto_listo_o_None, esperando_continuacion).
        """
        frag = (fragment or "").strip()
        if not frag:
            return None, False
        now = time.monotonic()
        with self._lock:
            if self._buffer and (now - self._last_ts) > (self.max_wait_s + 1.5):
                # Expiró el fragmento viejo
                self._buffer.clear()
            self._buffer.append(frag)
            self._last_ts = now
            merged = " ".join(self._buffer).strip()
            # No retener más de 2 fragmentos acumulados o enunciados ya largos
            if len(self._buffer) < 2 and len(merged) < 110 and self.normalizer.is_incomplete_utterance(merged):
                return None, True
            self._buffer.clear()
            return merged, False

    def flush_if_expired(self) -> Optional[str]:
        now = time.monotonic()
        with self._lock:
            if not self._buffer:
                return None
            if (now - self._last_ts) >= self.max_wait_s:
                merged = " ".join(self._buffer).strip()
                self._buffer.clear()
                return merged
            return None

    def flush_now(self) -> Optional[str]:
        with self._lock:
            if not self._buffer:
                return None
            merged = " ".join(self._buffer).strip()
            self._buffer.clear()
            return merged


# ==============================================================================
# 5. MOTOR DE ABSTRACCIÓN SEMÁNTICA EN TIEMPO REAL (<15 ms, 100% LOCAL)
# ==============================================================================

@dataclass
class VoiceAbstraction:
    raw_text: str
    normalized_text: str
    intent: str
    sub_intent: str = ""
    entities: List[str] = field(default_factory=list)
    active_topic: str = ""
    resolved_query: str = ""
    needs_web: bool = False
    web_query: str = ""
    response_style: str = "balanced"  # concise | balanced | detailed | step_by_step
    max_tokens: int = 240
    max_sentences: int = 4
    instant_reply: Optional[str] = None
    action: Optional[Dict[str, Any]] = None
    system_guidance: str = ""
    corrections: List[str] = field(default_factory=list)
    is_incomplete: bool = False
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent": self.intent,
            "sub_intent": self.sub_intent,
            "entities": self.entities,
            "active_topic": self.active_topic,
            "resolved_query": self.resolved_query,
            "needs_web": self.needs_web,
            "web_query": self.web_query,
            "response_style": self.response_style,
            "max_tokens": self.max_tokens,
            "max_sentences": self.max_sentences,
            "has_instant_reply": self.instant_reply is not None,
            "action": self.action,
            "corrections": self.corrections,
            "is_incomplete": self.is_incomplete,
            "latency_ms": round(self.latency_ms, 2),
        }


class VoiceAbstractionEngine:
    """
    Motor de abstracción cognitiva de ultra-baja latencia (<15ms) para conversación
    y dictado por voz:
      - Normaliza dictado (DictationNormalizer).
      - Clasifica intención y sub-intención con alta precisión en español.
      - Extrae entidades y mantiene memoria de tópico activo multi-turno.
      - Resuelve referencias anafóricas ("eso", "explícalo más simple", "dame un ejemplo",
        "profundiza", "hazlo más corto", "repite").
      - Resuelve instantáneamente comandos deterministas locales (hora, telemetría,
        volumen, motor de voz, modo dictado) sin esperar inferencia LLM.
      - Ajusta dinámicamente estilo y presupuesto de tokens para máxima fluidez hablada.
    """

    _STOPWORDS = frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
        "en", "con", "sin", "por", "para", "sobre", "entre", "hacia", "desde", "que",
        "cual", "cuales", "quien", "quienes", "como", "cuando", "donde", "porque",
        "pero", "mas", "muy", "poco", "mucho", "todo", "toda", "todos", "todas",
        "esto", "esta", "estos", "estas", "eso", "esa", "esos", "esas", "algo",
        "hola", "oye", "hey", "tardis", "por", "favor", "dime", "puedes", "podrias",
        "quiero", "necesito", "explicame", "explica", "cuentame", "hablame", "me",
        "te", "se", "nos", "le", "les", "mi", "tu", "su", "es", "son", "esta", "estan",
        "fue", "ser", "estar", "hacer", "tener", "hay", "ver", "saber", "aqui", "ahi",
    })

    _ANAPHORA_MARKERS = (
        "eso", "esto", "lo anterior", "el anterior", "la anterior", "ese tema",
        "esa idea", "lo mismo", "de nuevo", "otra vez", "mas sobre", "más sobre",
        "y su ", "y sus ", "al respecto",
    )

    _WEB_KEYWORDS = (
        "hoy", "actual", "actualmente", "ultima hora", "última hora", "noticias",
        "precio de", "cuanto cuesta", "cuánto cuesta", "cotizacion", "cotización",
        "clima en", "tiempo en", "temperatura en", "pronostico", "pronóstico",
        "resultado del partido", "quien gano", "quién ganó", "version actual",
        "versión actual", "busca en internet", "investiga en la web", "googlea",
    )

    def __init__(self, normalizer: Optional[DictationNormalizer] = None):
        self.normalizer = normalizer or DictationNormalizer()
        self.active_topic: str = ""
        self.recent_entities: Deque[str] = deque(maxlen=12)
        self.recent_topics: Deque[str] = deque(maxlen=6)
        self.last_user_text: str = ""
        self.last_assistant_reply: str = ""
        self.dictation_mode: bool = False
        self.dictation_buffer: List[str] = []

    def record_assistant_reply(self, reply: str) -> None:
        if reply and reply.strip():
            self.last_assistant_reply = reply.strip()

    def get_stt_context_hint(self) -> str:
        """Construye una pista léxica compacta para el prompt de Whisper sin causar bucles."""
        parts: List[str] = []
        if self.active_topic:
            parts.append(f"Tema actual: {self.active_topic}.")
        if self.recent_entities:
            ents = ", ".join(list(dict.fromkeys(self.recent_entities))[-8:])
            parts.append(f"Palabras clave recientes: {ents}.")
        if self.last_user_text:
            tail = " ".join(self.last_user_text.split()[-14:])
            parts.append(tail)
        return " ".join(parts).strip()[:220]

    def _extract_entities(self, text: str) -> List[str]:
        entities: List[str] = []
        # Acrónimos, términos técnicos con dígitos o CamelCase/Mayúsculas
        for m in re.finditer(r"\b(?:[A-Z]{2,}[0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z]+[0-9]{2,})\b", text):
            tok = m.group(0)
            if tok.lower() not in self._STOPWORDS and tok not in entities:
                entities.append(tok)
        # Sustantivos significativos (>=4 letras no stopword)
        for tok in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\-]{4,}", text):
            low = strip_accents(tok).lower()
            if low not in self._STOPWORDS and tok not in entities:
                entities.append(tok)
            if len(entities) >= 8:
                break
        return entities

    def _extract_topic(self, normalized_text: str, entities: List[str]) -> str:
        # Intenta capturar complemento después de "sobre", "acerca de", "qué es", "cómo funciona"
        m = re.search(
            r"(?i)(?:sobre|acerca\s+de|qu[eé]\s+es|c[oó]mo\s+funciona|expl[ií]came|h[aá]blame\s+de|investiga)\s+([^?.!]{3,70})",
            normalized_text,
        )
        if m:
            cand = m.group(1).strip(" ,.;:¡¿")
            if len(cand.split()) >= 1 and normalize_key(cand) not in ("eso", "esto", "lo anterior"):
                return cand[:70]
        if entities:
            return ", ".join(entities[:3])
        return self.active_topic

    @staticmethod
    def _instant_time_date(only_time: bool = False, only_date: bool = False) -> str:
        now = datetime.datetime.now()
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = [
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        hora = now.strftime("%I:%M %p").lstrip("0")
        fecha = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}"
        if only_time:
            return f"Son las {hora}."
        if only_date:
            return f"Hoy es {fecha}."
        return f"Son las {hora} del {fecha}."

    @staticmethod
    def _instant_telemetry() -> str:
        cpu_pct = psutil.cpu_percent(interval=0.05) if HAS_PSUTIL and psutil else 0.0
        mem = psutil.virtual_memory() if HAS_PSUTIL and psutil else None
        ram_str = (
            f"{mem.used / (1024**3):.1f} de {mem.total / (1024**3):.0f} gigabytes de memoria RAM"
            if mem else "memoria operativa"
        )
        freq = query_cpu_freq_mhz()
        freq_str = f" a {freq:.0f} megahercios" if freq > 0 else ""

        cpu_temp = ""
        try:
            for h in Path("/sys/class/hwmon").glob("hwmon*"):
                if (h / "name").read_text(encoding="utf-8").strip() == "k10temp":
                    t = int((h / "temp1_input").read_text(encoding="utf-8").strip()) // 1000
                    cpu_temp = f", CPU en {t} grados"
                    break
        except Exception:
            pass

        gpu_str = ""
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=2.0,
                ).strip().splitlines()[0]
                gt, gu, gtot = [x.strip() for x in out.split(",")]
                gpu_str = f" y GPU RTX 3050 en {gt} grados usando {gu} de {gtot} megabytes de VRAM"
            except Exception:
                pass

        return (
            f"El sistema TARDIS está operativo. Procesador al {cpu_pct:.0f} por ciento{freq_str}{cpu_temp}, "
            f"{ram_str}{gpu_str}."
        )

    @staticmethod
    def _adjust_volume(op: str) -> str:
        if not shutil.which("pactl"):
            return "No encontré pactl para controlar el volumen."
        try:
            if op == "up":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+12%"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Volumen subido."
            if op == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-12%"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Volumen bajado."
            if op == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Audio silenciado."
            if op == "unmute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True)
                return "Audio restaurado."
        except Exception as exc:
            return f"No pude ajustar el volumen: {exc}"
        return "Listo."

    @staticmethod
    def _copy_to_clipboard(text: str) -> bool:
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(
                        cmd, input=text.encode("utf-8"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3, check=True,
                    )
                    return True
                except Exception:
                    continue
        return False

    def abstract(self, raw_text: str, allow_system_actions: bool = True) -> VoiceAbstraction:
        """Normaliza y abstrae la consulta por voz en <15 ms."""
        t0 = time.perf_counter()
        normalized, corrections = self.normalizer.normalize(raw_text, dictation_mode=self.dictation_mode)
        low = normalize_key(normalized)
        is_inc = self.normalizer.is_incomplete_utterance(normalized)
        entities = self._extract_entities(normalized)

        # 0. Control de modo dictado
        if any(k in low for k in ("activa modo dictado", "activar modo dictado", "modo dictado", "inicia dictado", "iniciar dictado")):
            self.dictation_mode = True
            self.dictation_buffer.clear()
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="dictation_mode", sub_intent="start",
                active_topic=self.active_topic,
                instant_reply="Modo dictado continuo activado. Dicta con libertad y di termina dictado cuando finalices.",
                action={"type": "dictation_mode", "enabled": True},
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        if self.dictation_mode:
            if any(k in low for k in ("termina dictado", "terminar dictado", "fin de dictado", "salir de dictado", "modo conversacion", "deten dictado")):
                self.dictation_mode = False
                full_doc = "\n".join(self.dictation_buffer).strip()
                copied = self._copy_to_clipboard(full_doc) if full_doc else False
                word_cnt = len(full_doc.split()) if full_doc else 0
                note = " y lo copié al portapapeles" if copied else ""
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="stop",
                    active_topic=self.active_topic,
                    instant_reply=f"Dictado finalizado con {word_cnt} palabras{note}. Volvemos a conversación normal.",
                    action={"type": "dictation_mode", "enabled": False, "text": full_doc, "copied": copied},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("borra lo ultimo", "borra la ultima frase", "deshaz lo ultimo")):
                if self.dictation_buffer:
                    self.dictation_buffer.pop()
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="undo",
                    instant_reply="Último fragmento borrado. Continúa dictando.",
                    action={"type": "dictation_undo"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("lee el dictado", "leer dictado", "que llevo dictado")):
                doc = " ".join(self.dictation_buffer).strip()
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="dictation_mode", sub_intent="read",
                    instant_reply=doc or "Aún no has dictado texto.",
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            # Captura pura de dictado sin molestar al LLM
            self.dictation_buffer.append(normalized)
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="dictation_capture", sub_intent="append",
                instant_reply="",  # Silencioso para fluidez del dictado
                action={"type": "dictation_append", "text": normalized, "buffer_size": len(self.dictation_buffer)},
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # 1. Comandos instantáneos de control de voz/TTS (exigen frase corta imperativa para cero falsos positivos)
        n_words = len(low.split())
        if n_words <= 7:
            if any(k in low for k in ("usa voz local", "activa voz local", "cambia a voz local", "usa piper", "activa piper", "cambia a piper", "modo voz local", "modo offline")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="tts_local",
                    instant_reply="Voz neuronal local Piper activada. Operando cien por ciento local y sin latencia de red.",
                    action={"type": "set_tts_mode", "mode": "local"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("usa voz cortana", "activa voz cortana", "cambia a cortana", "usa cortana", "usa voz edge", "activa modo hibrido", "cambia a modo hibrido")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="tts_hybrid",
                    instant_reply="Modo híbrido con voz Cortana activado y respaldo local Piper listo.",
                    action={"type": "set_tts_mode", "mode": "hybrid"},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("habla mas rapido", "acelera la voz", "sube velocidad de voz")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="rate_up",
                    instant_reply="Perfecto, aumento un poco la velocidad al hablar.",
                    action={"type": "adjust_rate", "delta": 0.10},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("habla mas lento", "habla mas despacio", "baja la velocidad de voz")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="voice_control", sub_intent="rate_down",
                    instant_reply="Entendido, hablaré con un ritmo más pausado.",
                    action={"type": "adjust_rate", "delta": -0.10},
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
        if low in ("repite", "repitelo", "repite eso", "repite lo ultimo", "que dijiste", "no te escuche"):
            rep = self.last_assistant_reply or "Aún no he dicho nada en esta sesión."
            return VoiceAbstraction(
                raw_text=raw_text, normalized_text=normalized,
                intent="voice_control", sub_intent="repeat",
                instant_reply=rep,
                corrections=corrections,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # 2. Comandos instantáneos de sistema/hardware (solo si permitidos y frase corta directa)
        if allow_system_actions and len(low.split()) <= 10:
            if any(k in low for k in ("que hora es", "dime la hora", "hora actual")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="time",
                    instant_reply=self._instant_time_date(only_time=True),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("que dia es", "que fecha es", "fecha de hoy")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="date",
                    instant_reply=self._instant_time_date(only_date=True),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("sube el volumen", "subir volumen", "mas volumen")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="volume_up",
                    instant_reply=self._adjust_volume("up"),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("baja el volumen", "bajar volumen", "menos volumen")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="system_command", sub_intent="volume_down",
                    instant_reply=self._adjust_volume("down"),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )
            if any(k in low for k in ("estado del sistema", "telemetria del sistema", "temperatura de la gpu", "temperatura del cpu", "como esta el sistema")):
                return VoiceAbstraction(
                    raw_text=raw_text, normalized_text=normalized,
                    intent="hardware_telemetry", sub_intent="status",
                    instant_reply=self._instant_telemetry(),
                    corrections=corrections,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                )

        # 3. Clasificación de refinamiento / seguimiento anafórico
        sub_intent = ""
        response_style = "balanced"
        max_tokens = 240
        max_sentences = 4
        guidance_parts: List[str] = []

        if any(k in low for k in ("mas simple", "mas sencillo", "facil", "para principiantes", "sin tecnicismos")):
            intent = "followup_refinement"
            sub_intent = "simplify"
            response_style = "concise"
            max_tokens = 180
            max_sentences = 3
            guidance_parts.append("Explica el mismo tema con lenguaje muy simple, cotidiano y una analogía clara.")
        elif any(k in low for k in ("mas corto", "resumelo", "en resumen", "breve", "en una frase")):
            intent = "followup_refinement"
            sub_intent = "shorter"
            response_style = "concise"
            max_tokens = 110
            max_sentences = 2
            guidance_parts.append("Responde en máximo 1 o 2 frases ultra concisas.")
        elif any(k in low for k in ("dame un ejemplo", "pon un ejemplo", "ejemplo practico", "como se aplica")):
            intent = "followup_refinement"
            sub_intent = "example"
            response_style = "balanced"
            max_tokens = 220
            max_sentences = 4
            guidance_parts.append("Da un ejemplo concreto, práctico y fácil de imaginar en voz alta.")
        elif any(k in low for k in ("profundiza", "mas detalle", "explica mejor", "a fondo", "tecnicamente")):
            intent = "followup_refinement"
            sub_intent = "deepen"
            response_style = "detailed"
            max_tokens = 380
            max_sentences = 6
            guidance_parts.append("Profundiza con rigor técnico claro y bien articulado para escucharse por voz.")
        elif any(k in low for k in ("paso a paso", "como hago para", "como puedo", "guia")):
            intent = "technical_explanation"
            sub_intent = "step_by_step"
            response_style = "step_by_step"
            max_tokens = 300
            max_sentences = 5
            guidance_parts.append("Explica en pasos breves y secuenciales hablados (primero, luego, finalmente).")
        elif low in ("hola", "hola tardis", "buenos dias", "buenas tardes", "buenas noches", "oye tardis", "estas ahi", "tardis estas ahi"):
            intent = "greeting"
            response_style = "concise"
            max_tokens = 90
            max_sentences = 2
            guidance_parts.append("Saluda con calidez y brevedad en 1 o 2 frases directas.")
        elif any(k in low for k in ("explica", "como funciona", "que es", "por que", "diferencia entre", "analiza")):
            intent = "technical_explanation"
            response_style = "balanced"
            max_tokens = 280
            max_sentences = 4
        elif "?" in normalized or any(low.startswith(p) for p in ("que ", "como ", "cuando ", "donde ", "quien ", "cuanto ", "cual ")):
            intent = "factual_question"
            response_style = "concise"
            max_tokens = 190
            max_sentences = 3
        else:
            intent = "conversation"
            response_style = "balanced"
            max_tokens = 220
            max_sentences = 4

        # 4. Resolución de anáforas y memoria de tópico
        has_anaphora = (
            intent == "followup_refinement"
            or any(m in f" {low} " for m in self._ANAPHORA_MARKERS)
        )
        new_topic = self._extract_topic(normalized, entities)
        if not has_anaphora and new_topic:
            self.active_topic = new_topic
            if new_topic not in self.recent_topics:
                self.recent_topics.append(new_topic)
        for ent in entities:
            self.recent_entities.append(ent)

        resolved_query = normalized
        if has_anaphora and self.active_topic and normalize_key(self.active_topic) not in low:
            resolved_query = f"{normalized} (referido al tema activo: {self.active_topic})"
            guidance_parts.append(
                f"El usuario hace referencia al tema en curso: «{self.active_topic}». Mantén continuidad exacta."
            )

        # 5. Detección ligera de necesidad de internet
        needs_web = any(k in low for k in self._WEB_KEYWORDS)
        web_query = f"{normalized} {self.active_topic}".strip() if (needs_web and has_anaphora) else normalized

        self.last_user_text = normalized

        if self.active_topic:
            guidance_parts.append(f"Tópico activo: {self.active_topic}.")
        guidance_parts.append(
            f"Estilo hablado: {response_style} (idealmente <= {max_sentences} oraciones naturales sin Markdown ni tablas)."
        )

        return VoiceAbstraction(
            raw_text=raw_text,
            normalized_text=normalized,
            intent=intent,
            sub_intent=sub_intent,
            entities=entities,
            active_topic=self.active_topic,
            resolved_query=resolved_query,
            needs_web=needs_web,
            web_query=web_query if needs_web else "",
            response_style=response_style,
            max_tokens=max_tokens,
            max_sentences=max_sentences,
            instant_reply=None,
            action=None,
            system_guidance=" ".join(guidance_parts),
            corrections=corrections,
            is_incomplete=is_inc,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


# ==============================================================================
# 6. STT SOBERANO LOCAL (CUDA int8 AUTOMÁTICO + CPU FALLBACK + DSP + PROMPT)
# ==============================================================================

@dataclass
class TranscriptionResult:
    text: str
    raw_text: str
    elapsed_s: float
    device: str
    model: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    audio_metrics: Dict[str, float] = field(default_factory=dict)
    corrections: List[str] = field(default_factory=list)


class SovereignLocalSTT:
    """
    Motor STT singleton de alta precisión con faster-whisper:
      - Selección inteligente de dispositivo (`cuda` int8 si hay >=480 MiB VRAM libre
        para `small` o >=280 MiB para `base`; failover limpio a `cpu` int8).
      - Preprocesamiento DSP (pasa-altos 85 Hz + AGC suave).
      - Prompt de dominio dinámico + hotwords + beam_size=2.
      - Normalización de dictado y filtro anti-alucinación por confianza.
    """

    def __init__(
        self,
        model_size: str = DEFAULT_STT_MODEL,
        device: str = DEFAULT_STT_DEVICE,
        cpu_threads: int = int(os.environ.get("TARDIS_VOICE_WHISPER_THREADS", "6")),
    ):
        self.requested_model = model_size or "auto"
        self.requested_device = device or "auto"
        self.cpu_threads = max(2, int(cpu_threads))
        self.model_size: str = "base"
        self.active_device: str = "cpu"
        self.compute_type: str = "int8"
        self._model = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._normalizer = DictationNormalizer()
        self._last_error: Optional[str] = None
        self._stats = {"count": 0, "total_ms": 0.0, "last_ms": 0.0}

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _choose_backend(self) -> Tuple[str, str, str]:
        """Decide (model_size, device, compute_type) óptimo según hardware y VRAM libre."""
        req_m = self.requested_model.strip().lower()
        req_d = self.requested_device.strip().lower()

        can_cuda = False
        free_vram = 0
        if req_d in ("auto", "cuda", "gpu"):
            preload_cuda_libraries()
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    _, free_vram = query_gpu_vram_mb(cache_ttl=1.0)
                    # Margen conservador en RTX 3050 4 GB
                    can_cuda = free_vram >= 320 or req_d == "cuda"
            except Exception:
                can_cuda = False

        if req_d == "cpu":
            can_cuda = False

        if can_cuda:
            if req_m == "auto":
                # small usa ~288 MiB VRAM y da mucha mayor precisión en español dictado
                chosen_model = "small" if free_vram >= 520 else "base"
            else:
                chosen_model = req_m
            return chosen_model, "cuda", "int8"

        # CPU fallback: si CPU está en powersave (<1.2 GHz), priorizar base para fluidez;
        # si CPU tiene buen reloj y el usuario pidió small, usar small.
        if req_m == "auto":
            freq = query_cpu_freq_mhz()
            chosen_model = "small" if (freq == 0.0 or freq >= 1800.0) else "base"
        else:
            chosen_model = req_m
        return chosen_model, "cpu", "int8"

    def _load(self):
        with self._load_lock:
            if self._model is not None:
                return self._model
            if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
                sys.path.insert(0, str(VOICE_LIB))
            from faster_whisper import WhisperModel

            MODEL_CACHE.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

            model_name, dev, ctype = self._choose_backend()
            try:
                self._model = WhisperModel(
                    model_name,
                    device=dev,
                    compute_type=ctype,
                    cpu_threads=self.cpu_threads,
                    download_root=str(MODEL_CACHE),
                )
                self.model_size = model_name
                self.active_device = dev
                self.compute_type = ctype
                self._last_error = None
                logger.info(
                    "⚡ STT Whisper cargado: model=%s device=%s compute=%s",
                    self.model_size, self.active_device, self.compute_type,
                )
                return self._model
            except Exception as exc:
                logger.warning("Fallo cargando Whisper (%s/%s): %s; usando CPU base int8", model_name, dev, exc)
                self._last_error = str(exc)
                fallback_model = "base"
                self._model = WhisperModel(
                    fallback_model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads,
                    download_root=str(MODEL_CACHE),
                )
                self.model_size = fallback_model
                self.active_device = "cpu"
                self.compute_type = "int8"
                return self._model

    def warmup(self) -> float:
        t0 = time.perf_counter()
        self._load()
        return time.perf_counter() - t0

    def decode_to_pcm16k(self, audio_bytes: bytes, suffix: str = ".wav") -> bytes:
        """Decodifica cualquier formato de audio a PCM 16-bit mono 16 kHz (ruta zero-spawn para WAV 16k)."""
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

        shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
        tmp_path = shm_dir / f"tardis_stt_{os.getpid()}_{time.time_ns()}{suffix or '.wav'}"
        try:
            tmp_path.write_bytes(audio_bytes)
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
                timeout=25,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode(errors='ignore')[:200]}")
            return proc.stdout
        finally:
            tmp_path.unlink(missing_ok=True)

    def transcribe_pcm_detailed(
        self,
        pcm_bytes: bytes,
        *,
        language: str = DEFAULT_LANGUAGE,
        min_duration_s: float = 0.20,
        context_hint: str = "",
        dictation_mode: bool = False,
        beam_size: Optional[int] = None,
    ) -> TranscriptionResult:
        if not pcm_bytes:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size)

        audio_f32, metrics = preprocess_pcm_for_stt(pcm_bytes, sample_rate=SAMPLE_RATE)
        if audio_f32.size < int(SAMPLE_RATE * min_duration_s):
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        if metrics["rms_out"] < 0.0022:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        model = self._load()
        lang_arg = None if (not language or language.lower() == "auto") else language.split("-")[0].lower()

        # En CUDA podemos usar beam_size=2 (o 3 en dictado) con latencia mínima;
        # en CPU int8, beam_size=2 para frases cortas/medias y 1 si hay estrangulamiento.
        if beam_size is None:
            if self.active_device == "cuda":
                eff_beam = 3 if dictation_mode else 2
            else:
                freq = query_cpu_freq_mhz()
                eff_beam = 2 if (freq == 0.0 or freq >= 1600.0) else 1
        else:
            eff_beam = max(1, int(beam_size))

        prompt = SOVEREIGN_DOMAIN_PROMPT
        if context_hint:
            prompt = f"{SOVEREIGN_DOMAIN_PROMPT} {context_hint.strip()}"[:440]

        t0 = time.perf_counter()
        with self._infer_lock:
            kwargs: Dict[str, Any] = {
                "language": lang_arg,
                "beam_size": eff_beam,
                "best_of": eff_beam,
                "temperature": [0.0, 0.2],
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.38,
                    "min_silence_duration_ms": 280,
                    "speech_pad_ms": 180,
                },
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.62,
                "compression_ratio_threshold": 2.25,
                "log_prob_threshold": -1.15,
                "initial_prompt": prompt,
                "hotwords": SOVEREIGN_HOTWORDS,
            }
            try:
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
            except TypeError:
                # Compatibilidad con versiones antiguas sin `hotwords`
                kwargs.pop("hotwords", None)
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)

        elapsed = time.perf_counter() - t0
        kept_texts: List[str] = []
        logprobs: List[float] = []
        no_speech_probs: List[float] = []
        for seg in segments:
            seg_txt = (seg.text or "").strip()
            if not seg_txt:
                continue
            nsp = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            alp = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            # Descartar segmentos que el propio modelo considera ruido/no-habla con baja confianza
            if nsp > 0.78 and alp < -1.0:
                continue
            if is_whisper_hallucination(seg_txt):
                continue
            kept_texts.append(seg_txt)
            logprobs.append(alp)
            no_speech_probs.append(nsp)

        raw_text = " ".join(kept_texts).strip()
        avg_lp = float(np.mean(logprobs)) if logprobs else 0.0
        avg_nsp = float(np.mean(no_speech_probs)) if no_speech_probs else 0.0

        if not raw_text or is_whisper_hallucination(raw_text):
            return TranscriptionResult(
                "", raw_text, elapsed, self.active_device, self.model_size,
                avg_logprob=avg_lp, no_speech_prob=avg_nsp, audio_metrics=metrics,
            )

        norm_text, corrections = self._normalizer.normalize(raw_text, dictation_mode=dictation_mode)
        self._stats["count"] += 1
        self._stats["last_ms"] = round(elapsed * 1000.0, 1)
        self._stats["total_ms"] += elapsed * 1000.0

        return TranscriptionResult(
            text=norm_text,
            raw_text=raw_text,
            elapsed_s=elapsed,
            device=self.active_device,
            model=self.model_size,
            avg_logprob=round(avg_lp, 3),
            no_speech_prob=round(avg_nsp, 3),
            audio_metrics=metrics,
            corrections=corrections,
        )

    def transcribe_pcm_partial(
        self,
        pcm_bytes: bytes,
        *,
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
        max_window_s: float = 10.0,
    ) -> TranscriptionResult:
        """
        Transcripción parcial ultrarrápida (<250 ms en CUDA) para mostrar al instante
        la voz convertida a texto mientras el usuario sigue dictando.
        """
        if not pcm_bytes:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size)

        max_bytes = int(max(2.0, float(max_window_s)) * SAMPLE_RATE * 2)
        if len(pcm_bytes) > max_bytes:
            pcm_bytes = pcm_bytes[-max_bytes:]

        audio_f32, metrics = preprocess_pcm_for_stt(pcm_bytes, sample_rate=SAMPLE_RATE)
        if audio_f32.size < int(SAMPLE_RATE * 0.28) or metrics["rms_out"] < 0.0028:
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)

        model = self._load()
        lang_arg = None if (not language or language.lower() == "auto") else language.split("-")[0].lower()
        prompt = SOVEREIGN_DOMAIN_PROMPT
        if context_hint:
            prompt = f"{SOVEREIGN_DOMAIN_PROMPT} {context_hint.strip()}"[:360]

        t0 = time.perf_counter()
        # Si hay una transcripción final ocupando el lock, no bloquear el hilo de vista previa
        if not self._infer_lock.acquire(timeout=0.08):
            return TranscriptionResult("", "", 0.0, self.active_device, self.model_size, audio_metrics=metrics)
        try:
            kwargs: Dict[str, Any] = {
                "language": lang_arg,
                "beam_size": 1,
                "best_of": 1,
                "temperature": 0.0,
                "vad_filter": False,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.68,
                "compression_ratio_threshold": 2.35,
                "log_prob_threshold": -1.25,
                "initial_prompt": prompt,
                "hotwords": SOVEREIGN_HOTWORDS,
            }
            try:
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
            except TypeError:
                kwargs.pop("hotwords", None)
                segments_iter, _info = model.transcribe(audio_f32, **kwargs)
                segments = list(segments_iter)
        finally:
            self._infer_lock.release()

        elapsed = time.perf_counter() - t0
        kept: List[str] = []
        for seg in segments:
            seg_txt = (seg.text or "").strip()
            if not seg_txt or is_whisper_hallucination(seg_txt):
                continue
            nsp = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
            alp = float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            if nsp > 0.80 and alp < -1.05:
                continue
            kept.append(seg_txt)

        raw_text = " ".join(kept).strip()
        if not raw_text or is_whisper_hallucination(raw_text):
            return TranscriptionResult("", raw_text, elapsed, self.active_device, self.model_size, audio_metrics=metrics)

        norm_text, corrections = self._normalizer.normalize(raw_text, dictation_mode=dictation_mode)
        return TranscriptionResult(
            text=norm_text,
            raw_text=raw_text,
            elapsed_s=elapsed,
            device=self.active_device,
            model=self.model_size,
            audio_metrics=metrics,
            corrections=corrections,
        )

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        language: str = DEFAULT_LANGUAGE,
        min_duration_s: float = 0.20,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        res = self.transcribe_pcm_detailed(
            pcm_bytes,
            language=language,
            min_duration_s=min_duration_s,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )
        return res.text, res.elapsed_s

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        *,
        audio_format: str = "wav",
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        if not audio_bytes:
            return "", 0.0
        fmt = (audio_format or "wav").strip().lower().lstrip(".")
        if fmt in ("pcm", "pcm16", "s16le", "raw"):
            return self.transcribe_pcm(
                audio_bytes, language=language, context_hint=context_hint, dictation_mode=dictation_mode
            )
        pcm_bytes = self.decode_to_pcm16k(audio_bytes, suffix=f".{fmt}")
        return self.transcribe_pcm(
            pcm_bytes, language=language, context_hint=context_hint, dictation_mode=dictation_mode
        )

    def transcribe_file(
        self,
        audio_path: str | Path,
        *,
        language: str = DEFAULT_LANGUAGE,
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> TranscriptionResult:
        p = Path(audio_path)
        raw = p.read_bytes()
        pcm = self.decode_to_pcm16k(raw, suffix=p.suffix or ".wav")
        return self.transcribe_pcm_detailed(
            pcm, language=language, context_hint=context_hint, dictation_mode=dictation_mode
        )

    def get_status(self) -> Dict[str, Any]:
        avg_ms = (self._stats["total_ms"] / self._stats["count"]) if self._stats["count"] else 0.0
        used_vram, free_vram = query_gpu_vram_mb()
        return {
            "engine": "faster-whisper",
            "loaded": self.is_loaded,
            "model": self.model_size if self.is_loaded else self.requested_model,
            "device": self.active_device,
            "compute_type": self.compute_type,
            "sample_rate": SAMPLE_RATE,
            "transcriptions": self._stats["count"],
            "last_ms": self._stats["last_ms"],
            "avg_ms": round(avg_ms, 1),
            "vram_used_mb": used_vram,
            "vram_free_mb": free_vram,
            "last_error": self._last_error,
        }


# ==============================================================================
# 7. SANITIZACIÓN PROSÓDICA + PIPER ONNX TTS LOCAL + HÍBRIDO EDGE-TTS
# ==============================================================================

_RE_THINK = re.compile(r"<think>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
_RE_HW_DIRECTIVE = re.compile(r"\[\[HW_ACTION:[\s\S]*?\]\]", re.IGNORECASE)
_RE_MD_CODE = re.compile(r"```[\s\S]*?(?:```|\Z)")
_RE_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_RE_MD_TABLE = re.compile(r"^\s*\|.*$", re.MULTILINE)
_RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_RE_URL = re.compile(r"https?://\S+")
_RE_HTML = re.compile(r"</?[a-zA-Z][^>]*>")
_RE_MD_CHARS = re.compile(r"[*_#>|~•●▪►₪]+")
_RE_NON_LATIN = re.compile(r"[^\x20-\x7E\u00A0-\u00FF\u0100-\u017F\u2010-\u2027\u2030-\u205E\n]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")


# Mapa de dicción fonética para espeak-ng / Piper es-MX:
# Corrige anglicismos, acrónimos técnicos y nombres del ecosistema para una
# pronunciación cálida, fluida y natural en español de México.
_ES_MX_PHONETIC_DICTION: List[Tuple[re.Pattern, str]] = [
    # Nombres de herramientas / subsistemas que espeak es-MX lee literal mal
    (re.compile(r"\bBluetooth\b", re.IGNORECASE), "blutuz"),
    (re.compile(r"\bPipeWire\b", re.IGNORECASE), "paip guayer"),
    (re.compile(r"\bWhisper\b", re.IGNORECASE), "güísper"),
    (re.compile(r"\bfaster[\s-]?whisper\b", re.IGNORECASE), "fáster güísper"),
    (re.compile(r"\bOllama\b", re.IGNORECASE), "olama"),
    (re.compile(r"\bHyprland\b", re.IGNORECASE), "jáiperland"),
    (re.compile(r"\bWayland\b", re.IGNORECASE), "güéiland"),
    (re.compile(r"\bWi[\s-]?Fi\b", re.IGNORECASE), "guái fai"),
    (re.compile(r"\bPython\b", re.IGNORECASE), "páiton"),
    (re.compile(r"\bGitHub\b", re.IGNORECASE), "guítjab"),
    (re.compile(r"\bWebSocket\b", re.IGNORECASE), "güebsóquet"),
    (re.compile(r"\bFastAPI\b", re.IGNORECASE), "fast api"),
    (re.compile(r"\bONNX\b", re.IGNORECASE), "ónix"),
    (re.compile(r"\bNVIDIA\b", re.IGNORECASE), "envidia"),
    (re.compile(r"\bRyzen\b", re.IGNORECASE), "ráisen"),
    (re.compile(r"\bPiper\b", re.IGNORECASE), "páiper"),
    (re.compile(r"\bSilero\b", re.IGNORECASE), "siléro"),
    (re.compile(r"\bAntigravity\b", re.IGNORECASE), "antigráviti"),
    (re.compile(r"\bGODWORKS\b", re.IGNORECASE), "god güorks"),
    (re.compile(r"\bTemporalBrain\b", re.IGNORECASE), "temporal brein"),
    (re.compile(r"\bKAIJU\b", re.IGNORECASE), "kaiyu"),
    (re.compile(r"\bEVOIR\b", re.IGNORECASE), "evuár"),
    (re.compile(r"\bBarge[\s-]?In\b", re.IGNORECASE), "barch in"),
    (re.compile(r"\bsystemd\b", re.IGNORECASE), "sístem de"),
    (re.compile(r"\bkernel\b", re.IGNORECASE), "quérnel"),
    (re.compile(r"\bJSON\b"), "yéison"),
    (re.compile(r"\bLinux\b", re.IGNORECASE), "línux"),
    (re.compile(r"\bVRAM\b"), "ve ram"),
    (re.compile(r"\bCPU\b"), "ce pe u"),
    (re.compile(r"\bGPU\b"), "ge pe u"),
    (re.compile(r"\bSTT\b"), "ese te te"),
    (re.compile(r"\bTTS\b"), "te te ese"),
    (re.compile(r"\bVAD\b"), "ve a de"),
    (re.compile(r"\bLLM\b"), "ele ele eme"),
    (re.compile(r"\bCLI\b"), "ce ele i"),
    (re.compile(r"\bAPI\b"), "api"),
    (re.compile(r"\bUSB\b"), "u ese be"),
    (re.compile(r"\bSSD\b"), "ese ese de"),
    (re.compile(r"\bHFP\b"), "hache efe pe"),
    (re.compile(r"\bA2DP\b"), "a dos de pe"),
    (re.compile(r"\bPCM\b"), "pe ce eme"),
    (re.compile(r"\bWAV\b"), "guav"),
    (re.compile(r"\bMP3\b", re.IGNORECASE), "eme pe tres"),
    # Abreviaturas frecuentes del español hablado
    (re.compile(r"\bp\.\s*ej\.", re.IGNORECASE), "por ejemplo"),
    (re.compile(r"\bej\.", re.IGNORECASE), "por ejemplo"),
    (re.compile(r"\betc\.", re.IGNORECASE), "etcétera"),
    (re.compile(r"\bvs\.?\b", re.IGNORECASE), "versus"),
    (re.compile(r"\baprox\.", re.IGNORECASE), "aproximadamente"),
    (re.compile(r"\bmáx\.", re.IGNORECASE), "máximo"),
    (re.compile(r"\bmín\.", re.IGNORECASE), "mínimo"),
    (re.compile(r"\bseg\.", re.IGNORECASE), "segundos"),
]


def prepare_text_for_speech(text: str, *, phonetic_diction: bool = True) -> str:
    """
    Convierte texto técnico/Markdown en prosa hablada natural en español mexicano
    para Piper ONNX y Edge TTS (expande unidades, limpia código/URLs/pensamiento
    y optimiza la dicción fonética de términos técnicos y anglicismos).
    """
    if not text:
        return ""
    body = _RE_THINK.sub(" ", text)
    body = _RE_HW_DIRECTIVE.sub(" ", body)
    body = _RE_MD_CODE.sub(" ", body)
    body = _RE_MD_TABLE.sub(" ", body)
    body = _RE_MD_LINK.sub(r"\1", body)
    body = _RE_URL.sub(" ", body)
    body = _RE_HTML.sub(" ", body)
    body = _RE_MD_INLINE_CODE.sub(r"\1", body)
    # Preservar ritmo en saltos de línea convirtiéndolos en pausas naturales si falta puntuación
    body = re.sub(r"([A-Za-zÁÉÍÓÚáéíóúÑñ0-9])\s*\n+\s*", r"\1. ", body)
    body = _RE_MD_CHARS.sub(" ", body)

    # Versiones técnicas tipo v26.4 -> versión 26 punto 4
    body = re.sub(r"\bv(\d+)\.(\d+)(?:\.(\d+))?\b", lambda m: (
        f"versión {m.group(1)} punto {m.group(2)}" + (f" punto {m.group(3)}" if m.group(3) else "")
    ), body, flags=re.IGNORECASE)
    # Fracciones tipo 22/29 -> 22 de 29
    body = re.sub(r"\b(\d{1,3})/(\d{1,3})\b", r"\1 de \2", body)

    # Expansiones prosódicas naturales para unidades técnicas
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*°\s*C\b", r"\1 grados Celsius", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*°\s*F\b", r"\1 grados Fahrenheit", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", r"\1 por ciento", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*GHz\b", r"\1 gigahercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*MHz\b", r"\1 megahercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*kHz\b", r"\1 kilohercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*Hz\b", r"\1 hercios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:GiB|GB)\b", r"\1 gigabytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:MiB|MB)\b", r"\1 megabytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*(?:KiB|KB)\b", r"\1 kilobytes", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*ms\b", r"\1 milisegundos", body)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*RPM\b", r"\1 revoluciones por minuto", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*dBFS\b", r"\1 decibelios", body, flags=re.IGNORECASE)
    body = re.sub(r"(\d+(?:[.,]\d+)?)\s*dB\b", r"\1 decibelios", body)
    body = re.sub(r"\bkm/h\b", "kilómetros por hora", body, flags=re.IGNORECASE)
    body = re.sub(r"\btok/s\b", "tokens por segundo", body, flags=re.IGNORECASE)

    if phonetic_diction:
        for pat, rep in _ES_MX_PHONETIC_DICTION:
            body = pat.sub(rep, body)

    # Mejorar pausas expresivas alrededor de guiones largos y paréntesis
    body = re.sub(r"\s*[—–]\s*", ", ", body)
    body = re.sub(r"\(([^()]{1,90})\)", r", \1, ", body)
    body = body.replace("...", "… ")

    body = _RE_NON_LATIN.sub(" ", body)
    body = re.sub(r"\s+([.,;:!?…])", r"\1", body)
    body = re.sub(r",\s*,+", ", ", body)
    body = re.sub(r"\.{2,}", ".", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


@dataclass
class ExpressiveProsody:
    """Parámetros expresivos dinámicos para Piper ONNX por oración/cláusula."""
    style: str = "warm"
    length_scale: float = 0.96
    noise_scale: float = 0.64
    noise_w_scale: float = 0.80
    trailing_pause_ms: int = 210


def analyze_expressive_prosody(
    text: str,
    *,
    base_rate: Any = "+6%",
    style_hint: str = "",
) -> ExpressiveProsody:
    """
    Calcula la prosodia expresiva óptima para la dicción de TARDIS según
    puntuación, tono discursivo e intención (pregunta, exclamación, técnico, cálido).
    """
    base_ls = _rate_to_length_scale(base_rate)
    s = (text or "").strip()
    low = normalize_key(s)
    hint = (style_hint or "").strip().lower()

    # Determinar pausa natural de respiración al cierre de la cláusula
    if s.endswith(("?", "!", "…")):
        pause_ms = 240
    elif s.endswith("."):
        pause_ms = 210
    elif s.endswith((":", ";")):
        pause_ms = 175
    elif s.endswith(","):
        pause_ms = 120
    else:
        pause_ms = 160

    if "?" in s or "¿" in s:
        return ExpressiveProsody(
            style="inquisitive",
            length_scale=round(max(0.74, min(1.22, base_ls * 0.98)), 3),
            noise_scale=0.69,
            noise_w_scale=0.85,
            trailing_pause_ms=pause_ms,
        )
    if "!" in s or "¡" in s or any(g in low for g in ("un placer", "arquitecto", "excelente", "listo", "perfecto")):
        return ExpressiveProsody(
            style="expressive",
            length_scale=round(max(0.74, min(1.22, base_ls * 0.96)), 3),
            noise_scale=0.70,
            noise_w_scale=0.86,
            trailing_pause_ms=pause_ms,
        )
    if hint in ("detailed", "step_by_step", "technical", "dictation") or any(
        k in low for k in ("primero", "segundo", "paso", "temperatura", "frecuencia", "megahercios", "gigabytes", "milisegundos")
    ):
        return ExpressiveProsody(
            style="articulate",
            length_scale=round(max(0.80, min(1.25, base_ls * 1.04)), 3),
            noise_scale=0.56,
            noise_w_scale=0.72,
            trailing_pause_ms=max(pause_ms, 220),
        )
    if hint in ("calm", "concise") or len(s) <= 32:
        return ExpressiveProsody(
            style="calm",
            length_scale=round(max(0.76, min(1.22, base_ls * 1.00)), 3),
            noise_scale=0.60,
            noise_w_scale=0.76,
            trailing_pause_ms=pause_ms,
        )
    return ExpressiveProsody(
        style="warm",
        length_scale=round(max(0.76, min(1.22, base_ls * 0.99)), 3),
        noise_scale=0.64,
        noise_w_scale=0.80,
        trailing_pause_ms=pause_ms,
    )


def polish_tts_pcm(
    pcm_bytes: bytes,
    sample_rate: int = PIPER_SAMPLE_RATE,
    *,
    trailing_pause_ms: int = 190,
) -> bytes:
    """
    Pulido acústico de calidad estudio para el PCM generado por Piper ONNX:
      - Recorta silencio muerto excesivo al inicio/fin conservando ataque natural.
      - Normaliza sonoridad suavemente hacia -18 dBFS con limitador tanh anti-clipping.
      - Aplica rampa fade-in (12 ms) y fade-out (18 ms) para eliminar clics en Bluetooth EVOIR.
      - Añade pausa prosódica natural entre cláusulas/oraciones.
    """
    if not pcm_bytes or len(pcm_bytes) < 64:
        return pcm_bytes
    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    samples = np.frombuffer(pcm_bytes[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size < 64:
        return pcm_bytes

    # 1. Recorte suave de silencio muerto inicial/final
    abs_s = np.abs(samples)
    active = np.where(abs_s > 0.0045)[0]
    if active.size > 0:
        lead_pad = int(sample_rate * 0.025)
        tail_pad = int(sample_rate * 0.055)
        s_idx = max(0, int(active[0]) - lead_pad)
        e_idx = min(samples.size, int(active[-1]) + tail_pad)
        if e_idx > s_idx + 32:
            samples = samples[s_idx:e_idx]

    # 2. Nivelación RMS suave hacia -18 dBFS (0.126) evitando picos bruscos
    rms = float(np.sqrt(np.mean(samples * samples)))
    if 0.008 < rms:
        target_rms = 0.135
        gain = min(2.2, max(0.65, target_rms / rms))
        samples = samples * gain
        peak = float(np.max(np.abs(samples)))
        if peak > 0.90:
            samples = np.tanh(samples * 1.08) * 0.92

    # 3. Fade-in 12 ms / Fade-out 18 ms anti-pop
    fi = min(int(sample_rate * 0.012), samples.size // 4)
    fo = min(int(sample_rate * 0.018), samples.size // 4)
    if fi > 2:
        samples[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
    if fo > 2:
        samples[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)

    # 4. Pausa prosódica controlada al cierre
    pause_samples = max(0, int(sample_rate * max(0, min(600, int(trailing_pause_ms))) / 1000.0))
    if pause_samples > 0:
        samples = np.concatenate([samples, np.zeros(pause_samples, dtype=np.float32)])

    pcm_i16 = np.clip(samples * 32767.0, -32768.0, 32767.0).astype(np.int16)
    return pcm_i16.tobytes()


@dataclass
class WordTiming:
    """Marca temporal exacta de una palabra sincronizada con el audio PCM."""
    word: str
    start_ms: int
    end_ms: int
    char_start: int
    char_end: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass
class SyncedSpeechSegment:
    """Segmento hablado con audio PCM, prosodia y mapa palabra-a-milisegundo."""
    display_text: str
    spoken_text: str
    pcm: bytes
    sample_rate: int
    duration_ms: int
    prosody: ExpressiveProsody
    word_timings: List[WordTiming] = field(default_factory=list)
    mime: str = "audio/wav"
    encoded_bytes: Optional[bytes] = None
    char_offset: int = 0  # desplazamiento respecto al texto completo de la respuesta

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "display_text": self.display_text,
            "spoken_text": self.spoken_text,
            "sample_rate": self.sample_rate,
            "duration_ms": self.duration_ms,
            "prosody": self.prosody.style,
            "char_offset": self.char_offset,
            "word_timings": [w.to_dict() for w in self.word_timings],
        }


_VOWEL_GROUPS_RE = re.compile(r"[aeiouáéíóúü]+", re.IGNORECASE)
_WORD_SPAN_RE = re.compile(r"\S+")


def compute_word_timings(
    display_text: str,
    duration_ms: int,
    *,
    start_offset_ms: int = 0,
    trailing_pause_ms: int = 180,
) -> List[WordTiming]:
    """
    Calcula marcas temporales palabra por palabra sincronizadas a la duración real
    del PCM generado, ponderando sílabas en español y pausas de puntuación.
    Conserva los índices exactos `char_start`/`char_end` dentro de `display_text`.
    """
    if not display_text or duration_ms <= 0:
        return []
    matches = list(_WORD_SPAN_RE.finditer(display_text))
    if not matches:
        return []

    # Reservar la pausa prosódica final para que la última palabra termine justo antes del silencio
    active_ms = max(int(duration_ms * 0.55), duration_ms - max(0, min(trailing_pause_ms, duration_ms // 3)))
    lead_ms = min(25, active_ms // 10)
    usable_ms = max(40, active_ms - lead_ms)

    weights: List[float] = []
    for m in matches:
        tok = m.group(0)
        core = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", tok)
        syllables = max(1, len(_VOWEL_GROUPS_RE.findall(core))) if core else 1
        # Peso acústico = sílabas + longitud consonántica + pausa por puntuación
        w = 0.85 * syllables + 0.18 * max(1, len(core))
        if any(ch.isdigit() for ch in tok):
            w += 1.4  # los números en español toman más sílabas al leerse
        if tok.endswith((",", ";", "—", "–")):
            w += 1.35
        elif tok.endswith((":", ".", "!", "?", "…")):
            w += 2.15
        weights.append(max(0.6, w))

    total_w = sum(weights) or 1.0
    timings: List[WordTiming] = []
    cursor = float(start_offset_ms + lead_ms)
    for m, w in zip(matches, weights):
        span_ms = (w / total_w) * usable_ms
        t_start = int(round(cursor))
        cursor += span_ms
        t_end = max(t_start + 15, int(round(cursor)))
        timings.append(
            WordTiming(
                word=m.group(0),
                start_ms=t_start,
                end_ms=t_end,
                char_start=m.start(),
                char_end=m.end(),
            )
        )
    if timings:
        timings[-1].end_ms = max(timings[-1].start_ms + 20, start_offset_ms + active_ms)
    return timings


def extract_streaming_sentence(buffer: str, is_first: bool = False) -> Tuple[Optional[str], str]:
    """
    Extrae la siguiente oración lista para TTS minimizando el tiempo al primer audio (TTFA).
    Primera oración: umbral agresivo (14 chars) para empezar a sonar casi al instante.
    """
    min_len = 14 if is_first else 34
    if len(buffer) < min_len:
        return None, buffer

    match = _SENTENCE_SPLIT_RE.search(buffer)
    if match and match.start() >= min_len:
        sentence = buffer[: match.start() + 1].strip()
        rest = buffer[match.end() :]
        return sentence, rest

    if len(buffer) >= (64 if is_first else 96):
        comma_idx = buffer.find(", ", 28 if is_first else 48)
        if comma_idx != -1:
            sentence = buffer[: comma_idx + 1].strip()
            rest = buffer[comma_idx + 2 :]
            return sentence, rest

    return None, buffer


def resolve_voice_spec(voice: Optional[str], mode: str = DEFAULT_TTS_MODE) -> Tuple[str, str]:
    """
    Resuelve (engine, voice_id) a partir de un nombre/alias y el modo ('local'|'hybrid'|'edge').
    """
    raw = (voice or "").strip()
    low = raw.lower()
    m = (mode or "local").strip().lower()

    if low in VOICE_ALIASES:
        resolved = VOICE_ALIASES[low]
    elif raw in LOCAL_PIPER_VOICES:
        resolved = raw
    elif re.match(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural$", raw):
        resolved = raw
    else:
        resolved = DEFAULT_LOCAL_VOICE if m == "local" else DEFAULT_EDGE_VOICE

    if resolved in LOCAL_PIPER_VOICES:
        return "piper", resolved
    if m == "local":
        # En modo 100% local, mapear voces masculinas Edge a ald-medium y femeninas a claude-high
        if any(k in resolved.lower() for k in ("jorge", "alvaro", "álvaro")):
            return "piper", "es_MX-ald-medium"
        return "piper", "es_MX-claude-high"
    return "edge-tts", resolved


def _rate_to_length_scale(rate: Any) -> float:
    """Convierte velocidad tipo '+8%', '-10%' o 1.15 en length_scale de Piper (<1 = más rápido)."""
    if rate is None or rate == "":
        return 0.94  # ligeramente ágil y natural
    factor = 1.0
    if isinstance(rate, (int, float)):
        factor = float(rate)
    elif isinstance(rate, str):
        s = rate.strip()
        m = re.match(r"^([+-]?\d+(?:\.\d+)?)%$", s)
        if m:
            factor = 1.0 + float(m.group(1)) / 100.0
        else:
            try:
                factor = float(s)
            except ValueError:
                factor = 1.0
    factor = max(0.65, min(1.55, factor))
    return round(1.0 / factor, 3)


def _normalize_edge_rate(rate: Any) -> str:
    if rate is None or rate == "":
        return "+8%"
    if isinstance(rate, str) and re.match(r"^[+-]\d{1,2}%$", rate.strip()):
        return rate.strip()
    try:
        pct = int(round((max(0.65, min(1.55, float(rate))) - 1.0) * 100))
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return "+8%"


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int = PIPER_SAMPLE_RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class SovereignLocalTTS:
    """
    Sintetizador TTS residente de ultra-baja latencia:
      - Piper ONNX residente en memoria (100% offline, ~80-250ms, sin subprocesos).
      - Caché LRU en RAM para frases frecuentes (0ms).
      - Soporte híbrido con `edge-tts` async en memoria y failover inmediato a Piper.
    """

    def __init__(
        self,
        mode: str = DEFAULT_TTS_MODE,
        default_voice: Optional[str] = None,
        onnx_threads: int = 4,
        cache_max_items: int = 64,
    ):
        self.mode = (mode or "local").strip().lower()
        self.default_voice = default_voice or (
            DEFAULT_LOCAL_VOICE if self.mode == "local" else DEFAULT_EDGE_VOICE
        )
        self.onnx_threads = max(1, min(8, int(onnx_threads)))
        self._piper_voices: Dict[str, Any] = {}
        self._piper_lock = threading.Lock()
        self._synth_lock = threading.Lock()
        self._cache: "OrderedDict[Tuple[str, str, str], Tuple[bytes, str, int]]" = OrderedDict()
        self._cache_max = cache_max_items
        self._stats = {"local_count": 0, "edge_count": 0, "cache_hits": 0, "last_ms": 0.0}

    def available_piper_voices(self) -> List[Dict[str, Any]]:
        out = []
        for vid, info in LOCAL_PIPER_VOICES.items():
            p = PIPER_MODELS_DIR / info["file"]
            if p.is_file():
                out.append({**info, "path": str(p), "installed": True})
        return out

    def is_piper_available(self) -> bool:
        return bool(self.available_piper_voices())

    def list_all_voices(self) -> List[Dict[str, Any]]:
        return self.available_piper_voices() + list(EDGE_VOICES)

    def _load_piper_voice(self, voice_id: str):
        with self._piper_lock:
            if voice_id in self._piper_voices:
                return self._piper_voices[voice_id]
            info = LOCAL_PIPER_VOICES.get(voice_id) or LOCAL_PIPER_VOICES[DEFAULT_LOCAL_VOICE]
            model_path = PIPER_MODELS_DIR / info["file"]
            if not model_path.is_file():
                # Buscar cualquier .onnx instalado
                installed = self.available_piper_voices()
                if not installed:
                    raise FileNotFoundError(f"No hay modelos Piper en {PIPER_MODELS_DIR}")
                model_path = Path(installed[0]["path"])
                voice_id = installed[0]["id"]
                if voice_id in self._piper_voices:
                    return self._piper_voices[voice_id]

            if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
                sys.path.insert(0, str(VOICE_LIB))
            import onnxruntime as ort
            from piper.config import PiperConfig
            from piper.voice import PiperVoice

            cfg_path = Path(str(model_path) + ".json")
            with cfg_path.open("r", encoding="utf-8") as fh:
                config_dict = json.load(fh)

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = self.onnx_threads
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.log_severity_level = 3

            session = ort.InferenceSession(
                str(model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            voice_obj = PiperVoice(session=session, config=PiperConfig.from_dict(config_dict))
            self._piper_voices[voice_id] = voice_obj
            logger.info("🔊 Piper ONNX local cargado: %s (%d threads)", voice_id, self.onnx_threads)
            return voice_obj

    def warmup(self, voice: Optional[str] = None) -> float:
        t0 = time.perf_counter()
        eng, vid = resolve_voice_spec(voice or self.default_voice, mode="local")
        if self.is_piper_available():
            self._load_piper_voice(vid)
        return time.perf_counter() - t0

    def synthesize_piper_pcm(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+6%",
        style_hint: str = "",
        prosody: Optional[ExpressiveProsody] = None,
    ) -> Tuple[bytes, int]:
        """
        Sintetiza texto limpio a PCM16 mono raw usando Piper ONNX local en memoria,
        aplicando prosodia expresiva dinámica y pulido acústico anti-clic.
        """
        clean = prepare_text_for_speech(text)
        if not clean:
            return b"", PIPER_SAMPLE_RATE

        _, vid = resolve_voice_spec(voice or self.default_voice, mode="local")
        eff_prosody = prosody or analyze_expressive_prosody(text, base_rate=rate, style_hint=style_hint)
        cache_key = (
            "piper_pcm_v2",
            vid,
            f"{eff_prosody.style}:{eff_prosody.length_scale}:{eff_prosody.trailing_pause_ms}:{clean}",
        )
        if len(clean) <= 180 and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            self._stats["cache_hits"] += 1
            data, _, sr = self._cache[cache_key]
            return data, sr

        from piper.config import SynthesisConfig

        voice_obj = self._load_piper_voice(vid)
        syn_cfg = SynthesisConfig(
            length_scale=eff_prosody.length_scale,
            noise_scale=eff_prosody.noise_scale,
            noise_w_scale=eff_prosody.noise_w_scale,
            normalize_audio=True,
            volume=1.0,
        )
        t0 = time.perf_counter()
        with self._synth_lock:
            chunks = list(voice_obj.synthesize(clean, syn_config=syn_cfg))
        raw_pcm = b"".join(c.audio_int16_bytes for c in chunks)
        sr = chunks[0].sample_rate if chunks else voice_obj.config.sample_rate
        pcm = polish_tts_pcm(raw_pcm, sample_rate=sr, trailing_pause_ms=eff_prosody.trailing_pause_ms) if raw_pcm else b""
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._stats["local_count"] += 1
        self._stats["last_ms"] = round(dt_ms, 1)

        if pcm and len(clean) <= 180:
            self._cache[cache_key] = (pcm, "audio/pcm", sr)
            if len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)
        return pcm, sr

    def synthesize_synced_segment(
        self,
        display_text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+6%",
        mode: Optional[str] = None,
        style_hint: str = "",
        char_offset: int = 0,
    ) -> Optional[SyncedSpeechSegment]:
        """
        Sintetiza un segmento hablado con prosodia expresiva y calcula los timestamps
        exactos palabra por palabra sincronizados a la duración real del audio generado.
        """
        disp = (display_text or "").strip()
        if not disp:
            return None
        spoken = prepare_text_for_speech(disp)
        if not spoken:
            return None

        eff_mode = (mode or self.mode or "local").strip().lower()
        prosody = analyze_expressive_prosody(disp, base_rate=rate, style_hint=style_hint)
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)

        if engine == "piper" and self.is_piper_available():
            pcm, sr = self.synthesize_piper_pcm(
                disp, voice=vid, rate=rate, style_hint=style_hint, prosody=prosody
            )
            if pcm:
                dur_ms = max(80, int(round(len(pcm) / float(max(1, sr) * 2) * 1000.0)))
                timings = compute_word_timings(
                    disp, dur_ms, trailing_pause_ms=prosody.trailing_pause_ms
                )
                return SyncedSpeechSegment(
                    display_text=disp,
                    spoken_text=spoken,
                    pcm=pcm,
                    sample_rate=sr,
                    duration_ms=dur_ms,
                    prosody=prosody,
                    word_timings=timings,
                    mime="audio/wav",
                    encoded_bytes=pcm_to_wav_bytes(pcm, sample_rate=sr),
                    char_offset=char_offset,
                )

        # Ruta híbrida / edge-tts (con estimación acústica fiel o decodificación WAV exacta)
        audio_bytes, mime, sr = self.synthesize_bytes(
            disp, voice=voice, rate=rate, mode=eff_mode
        )
        if not audio_bytes:
            return None
        pcm = b""
        dur_ms = 0
        if "wav" in mime and audio_bytes[:4] == b"RIFF":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    sr = wf.getframerate()
                    pcm = wf.readframes(wf.getnframes())
                    dur_ms = max(80, int(round(wf.getnframes() / float(max(1, sr)) * 1000.0)))
            except Exception:
                dur_ms = 0
        if dur_ms <= 0:
            # Estimación precisa para MP3 24kbps-48kbps según ritmo de sílabas (~62 ms/carácter en español)
            words = max(1, len(disp.split()))
            dur_ms = max(320, int(words * 365 * prosody.length_scale))
        timings = compute_word_timings(disp, dur_ms, trailing_pause_ms=prosody.trailing_pause_ms)
        return SyncedSpeechSegment(
            display_text=disp,
            spoken_text=spoken,
            pcm=pcm,
            sample_rate=sr,
            duration_ms=dur_ms,
            prosody=prosody,
            word_timings=timings,
            mime=mime,
            encoded_bytes=audio_bytes,
            char_offset=char_offset,
        )

    async def synthesize_bytes_async(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+8%",
        pitch: str = "+0Hz",
        mode: Optional[str] = None,
        edge_timeout_s: float = 2.6,
    ) -> Tuple[Optional[bytes], str, int]:
        """
        Sintetiza texto limpio a bytes reproducibles:
          - Modo 'local' o voz Piper -> WAV PCM16 22050 Hz (100% offline).
          - Modo 'hybrid' / 'edge' con voz Edge -> MP3 async con failover inmediato a Piper.
        Retorna (audio_bytes, mime, sample_rate).
        """
        clean = prepare_text_for_speech(text)
        if not clean:
            return None, "audio/wav", PIPER_SAMPLE_RATE

        eff_mode = (mode or self.mode or "local").strip().lower()
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)

        if engine == "piper" and self.is_piper_available():
            loop = asyncio.get_running_loop()
            pcm, sr = await loop.run_in_executor(
                None, lambda: self.synthesize_piper_pcm(clean, voice=vid, rate=rate)
            )
            if pcm:
                return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr

        # Intento Edge TTS en memoria (async, sin subprocesos CLI)
        if HAS_EDGE_TTS and edge_tts is not None and engine == "edge-tts":
            rate_str = _normalize_edge_rate(rate)
            cache_key = ("edge_mp3", vid, f"{rate_str}:{pitch}:{clean}")
            if len(clean) <= 180 and cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                self._stats["cache_hits"] += 1
                data, mime, sr = self._cache[cache_key]
                return data, mime, sr
            try:
                t0 = time.perf_counter()

                async def _stream_edge() -> bytes:
                    comm = edge_tts.Communicate(clean, vid, rate=rate_str, pitch=pitch)
                    buf = io.BytesIO()
                    async for chunk in comm.stream():
                        if chunk.get("type") == "audio":
                            buf.write(chunk["data"])
                    return buf.getvalue()

                timeout_val = edge_timeout_s if eff_mode == "hybrid" else 18.0
                data = await asyncio.wait_for(_stream_edge(), timeout=timeout_val)
                if data:
                    self._stats["edge_count"] += 1
                    self._stats["last_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
                    if len(clean) <= 180:
                        self._cache[cache_key] = (data, "audio/mpeg", 24000)
                        if len(self._cache) > self._cache_max:
                            self._cache.popitem(last=False)
                    return data, "audio/mpeg", 24000
            except Exception as exc:
                logger.debug("edge-tts async falló o excedió timeout (%s); failover a Piper local", exc)

        # Failover soberano 100% local a Piper ONNX
        if self.is_piper_available():
            try:
                loop = asyncio.get_running_loop()
                pcm, sr = await loop.run_in_executor(
                    None, lambda: self.synthesize_piper_pcm(clean, voice=voice, rate=rate)
                )
                if pcm:
                    return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr
            except Exception as exc:
                logger.warning("Fallback Piper local falló: %s", exc)

        return None, "audio/wav", PIPER_SAMPLE_RATE

    def synthesize_bytes(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Any = "+8%",
        pitch: str = "+0Hz",
        mode: Optional[str] = None,
    ) -> Tuple[Optional[bytes], str, int]:
        """Versión síncrona segura desde cualquier hilo."""
        clean = prepare_text_for_speech(text)
        if not clean:
            return None, "audio/wav", PIPER_SAMPLE_RATE

        eff_mode = (mode or self.mode or "local").strip().lower()
        engine, vid = resolve_voice_spec(voice or self.default_voice, mode=eff_mode)
        if engine == "piper" and self.is_piper_available():
            pcm, sr = self.synthesize_piper_pcm(clean, voice=vid, rate=rate)
            if pcm:
                return pcm_to_wav_bytes(pcm, sample_rate=sr), "audio/wav", sr

        try:
            asyncio.get_running_loop()
            box: Dict[str, Any] = {}

            def _run() -> None:
                box["res"] = asyncio.run(
                    self.synthesize_bytes_async(clean, voice=voice, rate=rate, pitch=pitch, mode=eff_mode)
                )

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=35.0)
            return box.get("res", (None, "audio/wav", PIPER_SAMPLE_RATE))
        except RuntimeError:
            return asyncio.run(
                self.synthesize_bytes_async(clean, voice=voice, rate=rate, pitch=pitch, mode=eff_mode)
            )

    def get_status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "default_voice": self.default_voice,
            "piper_available": self.is_piper_available(),
            "piper_loaded_voices": list(self._piper_voices.keys()),
            "edge_tts_available": HAS_EDGE_TTS,
            "voices": self.list_all_voices(),
            "stats": dict(self._stats),
        }


class GaplessAudioPlayer:
    """
    Reproductor de audio de ultra-baja latencia con soporte de:
      - PCM raw directo a PipeWire (`pw-cat`/`pacat`) sin cortes ni archivos temporales.
      - MP3/WAV comprimido con `ffplay`/`mpv`/`pw-play`.
      - Interrupción Barge-In inmediata (<20ms) sin procesos huérfanos.
      - Ventana anti-eco post-locución (240 ms) calibrada para Lentes EVOIR / bocinas.
    """

    def __init__(
        self,
        enabled: bool = True,
        echo_guard_s: float = 0.24,
        on_state: Optional[Callable[[bool], None]] = None,
    ):
        self.enabled = enabled
        self.echo_guard_s = max(0.05, float(echo_guard_s))
        self._on_state = on_state
        self._queue: "queue.Queue[Optional[Tuple[str, Any, int]]]" = queue.Queue()
        self._proc_lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._playing = False
        self._last_play_end = 0.0
        self._stop_flag = threading.Event()
        self._interrupted = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="TARDIS-AudioPlayer")
        self._thread.start()

    @property
    def is_playing(self) -> bool:
        if self._playing or not self._queue.empty():
            return True
        return (time.monotonic() - self._last_play_end) < self.echo_guard_s

    def _notify(self, playing: bool) -> None:
        if self._on_state is not None:
            try:
                self._on_state(playing)
            except Exception:
                pass

    @staticmethod
    def _raw_pcm_cmd(sample_rate: int) -> Optional[List[str]]:
        if shutil.which("pw-cat"):
            return [
                "pw-cat", "--playback", "--raw",
                "--rate", str(sample_rate),
                "--channels", "1",
                "--format", "s16",
                "-",
            ]
        if shutil.which("pacat"):
            return [
                "pacat", "--playback", "--raw",
                f"--rate={sample_rate}",
                "--channels=1",
                "--format=s16le",
            ]
        if shutil.which("aplay"):
            return [
                "aplay", "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(sample_rate), "-c", "1", "-",
            ]
        return None

    @staticmethod
    def _file_player_cmd(path: Path) -> Optional[List[str]]:
        if path.suffix.lower() == ".wav" and shutil.which("pw-play"):
            return ["pw-play", str(path)]
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        if shutil.which("mpv"):
            return ["mpv", "--no-video", "--really-quiet", str(path)]
        if shutil.which("pw-play"):
            return ["pw-play", str(path)]
        return None

    def _play_pcm(self, pcm: bytes, sample_rate: int) -> None:
        cmd = self._raw_pcm_cmd(sample_rate)
        if not cmd:
            # Fallback a WAV en archivo temporal
            wav = pcm_to_wav_bytes(pcm, sample_rate=sample_rate)
            self._play_bytes_file(wav, ".wav")
            return
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with self._proc_lock:
            self._proc = proc
        try:
            if proc.stdin is not None:
                # Escribir en bloques pequeños de ~60ms para responder a Barge-In al instante
                chunk_bytes = max(1024, int(sample_rate * 2 * 0.06))
                for off in range(0, len(pcm), chunk_bytes):
                    if self._interrupted.is_set() or proc.poll() is not None:
                        break
                    try:
                        proc.stdin.write(pcm[off : off + chunk_bytes])
                        proc.stdin.flush()
                    except BrokenPipeError:
                        break
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            proc.wait()
        finally:
            with self._proc_lock:
                self._proc = None

    def _play_bytes_file(self, data: bytes, suffix: str) -> None:
        shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
        tmp = shm_dir / f"tardis_play_{os.getpid()}_{time.time_ns()}{suffix}"
        try:
            tmp.write_bytes(data)
            self._play_path(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _play_path(self, path: Path) -> None:
        cmd = self._file_player_cmd(path)
        if not cmd:
            return
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with self._proc_lock:
            self._proc = proc
        try:
            proc.wait()
        finally:
            with self._proc_lock:
                self._proc = None

    def _run_word_sync_clock(
        self,
        segment: SyncedSpeechSegment,
        stop_ev: threading.Event,
        on_start: Optional[Callable[[SyncedSpeechSegment], None]] = None,
        on_word: Optional[Callable[[SyncedSpeechSegment, WordTiming, int], None]] = None,
        on_end: Optional[Callable[[SyncedSpeechSegment, bool], None]] = None,
        pipewire_lead_ms: int = 35,
    ) -> None:
        """
        Reloj de sincronización texto↔sonido: dispara `on_word` en el instante exacto
        en que cada palabra sale por PipeWire, y se detiene al milisegundo ante Barge-In.
        """
        if on_start is not None:
            try:
                on_start(segment)
            except Exception:
                pass
        t0 = time.monotonic() + (max(0, pipewire_lead_ms) / 1000.0)
        timings = segment.word_timings
        interrupted = False
        for idx, wt in enumerate(timings):
            target = t0 + (wt.start_ms / 1000.0)
            while True:
                if stop_ev.is_set() or self._interrupted.is_set():
                    interrupted = True
                    break
                rem = target - time.monotonic()
                if rem <= 0.004:
                    break
                time.sleep(min(0.020, rem))
            if interrupted:
                break
            if on_word is not None:
                try:
                    on_word(segment, wt, idx)
                except Exception:
                    pass
        if on_end is not None:
            try:
                on_end(segment, interrupted)
            except Exception:
                pass

    def _play_synced(self, payload: Dict[str, Any]) -> None:
        segment: SyncedSpeechSegment = payload["segment"]
        on_start = payload.get("on_start")
        on_word = payload.get("on_word")
        on_end = payload.get("on_end")
        stop_ev = threading.Event()
        sync_thread = threading.Thread(
            target=self._run_word_sync_clock,
            args=(segment, stop_ev, on_start, on_word, on_end),
            daemon=True,
            name="TARDIS-WordSync",
        )
        sync_thread.start()
        try:
            if segment.pcm:
                self._play_pcm(segment.pcm, segment.sample_rate)
            elif segment.encoded_bytes:
                ext = ".wav" if "wav" in segment.mime else ".mp3"
                self._play_bytes_file(segment.encoded_bytes, ext)
        finally:
            if self._interrupted.is_set():
                stop_ev.set()
            sync_thread.join(timeout=max(0.4, (segment.duration_ms / 1000.0) + 0.35))
            stop_ev.set()

    def _worker(self) -> None:
        while not self._stop_flag.is_set():
            item = self._queue.get()
            if item is None:
                break
            kind, payload, sr = item
            if not self.enabled or self._interrupted.is_set():
                if kind == "path" and isinstance(payload, Path):
                    payload.unlink(missing_ok=True)
                continue
            try:
                self._playing = True
                self._notify(True)
                if kind == "synced":
                    self._play_synced(payload)
                elif kind == "pcm":
                    self._play_pcm(payload, sr)
                elif kind == "bytes":
                    self._play_bytes_file(payload, ".wav" if sr == -1 else ".mp3")
                elif kind == "path" and isinstance(payload, Path) and payload.exists():
                    self._play_path(payload)
            except Exception as exc:
                logger.debug("Error reproduciendo audio: %s", exc)
            finally:
                self._playing = False
                self._last_play_end = time.monotonic()
                if self._queue.empty():
                    self._notify(False)
                if kind == "path" and isinstance(payload, Path):
                    payload.unlink(missing_ok=True)

    def enqueue_synced(
        self,
        segment: SyncedSpeechSegment,
        *,
        on_start: Optional[Callable[[SyncedSpeechSegment], None]] = None,
        on_word: Optional[Callable[[SyncedSpeechSegment, WordTiming, int], None]] = None,
        on_end: Optional[Callable[[SyncedSpeechSegment, bool], None]] = None,
    ) -> None:
        """Encola un segmento hablado sincronizado palabra por palabra con el audio real."""
        if not self.enabled or segment is None:
            return
        if not segment.pcm and not segment.encoded_bytes:
            return
        self._interrupted.clear()
        self._queue.put((
            "synced",
            {
                "segment": segment,
                "on_start": on_start,
                "on_word": on_word,
                "on_end": on_end,
            },
            segment.sample_rate,
        ))

    def enqueue_pcm(self, pcm: bytes, sample_rate: int = PIPER_SAMPLE_RATE) -> None:
        if not self.enabled or not pcm:
            return
        self._interrupted.clear()
        self._queue.put(("pcm", pcm, int(sample_rate)))

    def enqueue_bytes(self, audio_bytes: bytes, mime: str = "audio/wav") -> None:
        if not self.enabled or not audio_bytes:
            return
        self._interrupted.clear()
        if "wav" in mime and audio_bytes[:4] == b"RIFF":
            try:
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    if wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                        pcm = wf.readframes(wf.getnframes())
                        self._queue.put(("pcm", pcm, wf.getframerate()))
                        return
            except Exception:
                pass
        self._queue.put(("bytes", audio_bytes, -1 if "wav" in mime else 0))

    def enqueue_path(self, path: Path) -> None:
        if not self.enabled or not path:
            return
        self._interrupted.clear()
        self._queue.put(("path", path, 0))

    def interrupt(self) -> None:
        self._interrupted.set()
        while True:
            try:
                item = self._queue.get_nowait()
                if item and item[0] == "path" and isinstance(item[1], Path):
                    item[1].unlink(missing_ok=True)
            except queue.Empty:
                break
        with self._proc_lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                except Exception:
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
            time.sleep(0.04)

    def shutdown(self) -> None:
        self.interrupt()
        self._stop_flag.set()
        self._queue.put(None)
        self._thread.join(timeout=1.5)


# ==============================================================================
# 8. ENRUTADOR MULTI-CARRIL LLM DE BAJA LATENCIA PARA VOZ LOCAL
# ==============================================================================

class LocalVoiceLLMRouter:
    """
    Enruta cada turno de voz al carril local más rápido y disponible:
      1. Verifica `/slots` de TemporalBrain UDS en <80 ms.
         - Si hay al menos 1 slot libre -> streaming directo en `TARDIS-NEURAL-SPACE-KAIJU` (8B).
      2. Si TemporalBrain está saturado (todos los slots ocupados en tareas largas):
         - Usa el carril GPU dedicado `127.0.0.1:11435` (`qwen3-vl:2b-instruct`,
           siempre con `num_ctx=3072` y `keep_alive=-1` para CERO recargas).
      3. Respaldo a `:8757/api/chat` o Ollama `:11434`.
    """

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

    @staticmethod
    def inspect_temporal_brain_slots(timeout: float = 0.15) -> Dict[str, Any]:
        if not HAS_HTTPX or httpx is None or not TEMPORAL_BRAIN_SOCK.exists():
            return {"available": False, "free_slots": 0, "total_slots": 0}
        try:
            transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
            with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
                r = client.get("/slots")
                if r.status_code != 200:
                    return {"available": False, "free_slots": 0, "total_slots": 0}
                slots = r.json()
                total = len(slots) if isinstance(slots, list) else 0
                free = sum(1 for s in slots if isinstance(s, dict) and not s.get("is_processing"))
                return {"available": True, "free_slots": free, "total_slots": total}
        except Exception:
            return {"available": False, "free_slots": 0, "total_slots": 0}

    @staticmethod
    def inspect_voice_ollama_lane(timeout: float = 0.25) -> Dict[str, Any]:
        if not HAS_HTTPX or httpx is None:
            return {"available": False, "model_loaded": False}
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(f"{VOICE_OLLAMA_URL}/api/ps")
                if r.status_code != 200:
                    return {"available": False, "model_loaded": False}
                models = (r.json() or {}).get("models") or []
                loaded = any(VOICE_OLLAMA_MODEL in str(m.get("name", "")) for m in models)
                return {"available": True, "model_loaded": loaded, "models": [m.get("name") for m in models]}
        except Exception:
            return {"available": False, "model_loaded": False}

    def _stream_temporal_brain(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        cancel_event: threading.Event,
    ) -> Iterator[str]:
        if not HAS_HTTPX or httpx is None or not TEMPORAL_BRAIN_SOCK.exists():
            return
        transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
        with httpx.Client(transport=transport, base_url="http://localhost", timeout=httpx.Timeout(60.0, connect=2.0)) as client:
            payload = {
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "cache_prompt": True,
            }
            with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    return
                in_think = False
                for line in resp.iter_lines():
                    if cancel_event.is_set():
                        return
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    delta = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                    if not delta:
                        continue
                    if "<think>" in delta:
                        in_think = True
                        delta = delta.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in delta:
                            in_think = False
                            delta = delta.split("</think>", 1)[1]
                        else:
                            continue
                    if delta:
                        yield delta

    def _stream_ollama(
        self,
        base_url: str,
        model: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        num_ctx: int,
        cancel_event: threading.Event,
        *,
        num_gpu: Optional[int] = None,
    ) -> Iterator[str]:
        if not HAS_HTTPX or httpx is None:
            return
        options: Dict[str, Any] = {
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
            "temperature": temperature,
        }
        if num_gpu is not None and int(num_gpu) >= 0:
            options["num_gpu"] = int(num_gpu)
        with httpx.Client(timeout=httpx.Timeout(45.0, connect=2.5)) as client:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                "keep_alive": -1,
                "options": options,
            }
            with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    return
                in_think = False
                for line in resp.iter_lines():
                    if cancel_event.is_set():
                        return
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    delta = (obj.get("message") or {}).get("content") or ""
                    if not delta:
                        continue
                    if "<think>" in delta:
                        in_think = True
                        delta = delta.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in delta:
                            in_think = False
                            delta = delta.split("</think>", 1)[1]
                        else:
                            continue
                    if delta:
                        yield delta

    def stream_reply(
        self,
        messages: List[Dict[str, str]],
        *,
        user_text: str,
        client_id: str = "infinite_voice_local",
        max_tokens: int = 240,
        temperature: float = 0.30,
        lane: str = "auto",
        cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[str, Iterator[str]]:
        """
        Elige el carril óptimo y devuelve (lane_name, token_iterator).
        """
        ev = cancel_event or threading.Event()
        tb = self.inspect_temporal_brain_slots()
        vl = self.inspect_voice_ollama_lane()

        # Construir orden dinámico de carriles priorizando latencia conversacional real:
        # En RTX 3050 4 GB con tareas autónomas activas, el carril GPU dedicado :11435
        # (qwen3-vl:2b-instruct con num_gpu=22 y num_ctx=3072 alineado con C310/VLM)
        # ofrece TTFT <1s sin competir con slots de TemporalBrain 8B.
        order: List[str] = []
        if lane == "fast" or lane == "voice_gpu":
            order = ["voice_gpu", "temporal_brain", "api_chat", "ollama_main"]
        elif lane == "temporal_brain":
            order = ["temporal_brain", "voice_gpu", "api_chat", "ollama_main"]
        else:
            if vl["available"]:
                order = ["voice_gpu", "temporal_brain", "api_chat", "ollama_main"]
            elif tb["available"] and tb["free_slots"] > 0:
                order = ["temporal_brain", "api_chat", "ollama_main"]
            elif tb["available"]:
                order = ["temporal_brain", "api_chat", "ollama_main"]
            else:
                order = ["api_chat", "ollama_main"]

        chosen = order[0]

        def _gen() -> Iterator[str]:
            for cand in order:
                if ev.is_set():
                    return
                emitted = False
                try:
                    if cand == "temporal_brain" and tb["available"]:
                        for tok in self._stream_temporal_brain(messages, max_tokens, temperature, ev):
                            emitted = True
                            yield tok
                    elif cand == "voice_gpu" and vl["available"]:
                        for tok in self._stream_ollama(
                            VOICE_OLLAMA_URL, VOICE_OLLAMA_MODEL, messages,
                            max_tokens, temperature, VOICE_OLLAMA_NUM_CTX, ev,
                            num_gpu=VOICE_OLLAMA_NUM_GPU,
                        ):
                            emitted = True
                            yield tok
                    elif cand == "ollama_main":
                        model = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
                        for tok in self._stream_ollama(
                            MAIN_OLLAMA_URL, model, messages,
                            max_tokens, temperature, 4096, ev,
                        ):
                            emitted = True
                            yield tok
                    elif cand == "api_chat":
                        tok = self._read_token()
                        payload = json.dumps({"message": user_text, "client_id": client_id}).encode("utf-8")
                        req = urllib.request.Request(
                            f"{TARDIS_CHAT_URL}?key={tok}",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=60.0) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        rep = str(data.get("response") or data.get("reply") or data.get("message") or "").strip()
                        rep = _RE_THINK.sub("", rep).strip()
                        if rep:
                            emitted = True
                            yield rep
                except Exception as exc:
                    logger.warning("Carril LLM '%s' falló: %s", cand, exc)
                if emitted:
                    return
            if not ev.is_set():
                yield "Los motores locales están ocupados en este instante. Inténtalo de nuevo en unos segundos."

        return chosen, _gen()


# ==============================================================================
# 9. SINGLETONS GLOBALES Y TELEMETRÍA CONSOLIDADA
# ==============================================================================

class LiveDictationTracker:
    """
    Registro inmediato en memoria y disco atómico de la voz dictada en curso.
    Permite que CLI, tardis-desktop, mundo-desktop y API consulten en tiempo real
    exactamente qué palabras está capturando el sistema mientras hablas.
    """

    def __init__(self, state_path: Optional[Path] = None):
        data_dir = PROJECT_ROOT / "data"
        self.json_path = state_path or (data_dir / "voice_dictation_live.json")
        self.txt_path = self.json_path.with_suffix(".txt")
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "active": False,
            "partial_text": "",
            "final_text": "",
            "source": "",
            "rms": 0.0,
            "stt_ms": 0,
            "seq": 0,
            "updated_at": 0.0,
            "history": [],
        }

    def _persist_locked(self) -> None:
        try:
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_j = self.json_path.with_suffix(".json.tmp")
            tmp_j.write_text(json.dumps(self._state, ensure_ascii=False), encoding="utf-8")
            tmp_j.replace(self.json_path)
            live_line = self._state["partial_text"] if self._state["active"] else self._state["final_text"]
            tmp_t = self.txt_path.with_suffix(".txt.tmp")
            tmp_t.write_text(live_line or "", encoding="utf-8")
            tmp_t.replace(self.txt_path)
        except OSError:
            pass

    def update_partial(self, text: str, *, source: str = "local", rms: float = 0.0, stt_ms: int = 0) -> Dict[str, Any]:
        with self._lock:
            self._state["active"] = True
            self._state["partial_text"] = (text or "").strip()
            self._state["source"] = source
            self._state["rms"] = round(float(rms), 4)
            self._state["stt_ms"] = int(stt_ms)
            self._state["seq"] = int(self._state["seq"]) + 1
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()
            return dict(self._state)

    def commit_final(self, text: str, *, source: str = "local", stt_ms: int = 0) -> Dict[str, Any]:
        clean = (text or "").strip()
        with self._lock:
            self._state["active"] = False
            self._state["partial_text"] = ""
            if clean:
                self._state["final_text"] = clean
                hist = list(self._state.get("history") or [])
                hist.append({"text": clean, "ts": round(time.time(), 3), "source": source, "stt_ms": int(stt_ms)})
                self._state["history"] = hist[-25:]
            self._state["source"] = source
            self._state["stt_ms"] = int(stt_ms)
            self._state["seq"] = int(self._state["seq"]) + 1
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()
            return dict(self._state)

    def clear_active(self) -> None:
        with self._lock:
            if not self._state["active"] and not self._state["partial_text"]:
                return
            self._state["active"] = False
            self._state["partial_text"] = ""
            self._state["updated_at"] = round(time.time(), 3)
            self._persist_locked()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)


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
