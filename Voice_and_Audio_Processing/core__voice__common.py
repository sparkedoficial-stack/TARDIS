"""core/voice/common.py - Constantes, rutas, dependencias y utilidades CUDA/VRAM para el motor de voz."""
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
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
