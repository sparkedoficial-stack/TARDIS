#!/usr/bin/env python3
"""
core/tapo_c310_voice_channel.py - Canal de Voz Always-On TARDIS para Tapo C310
=============================================================================
Mantiene un enlace permanente con el micrófono y la bocina física de la cámara
TP-Link Tapo C310 (GOD-EYE · REDACTED_IP), escucha en todo momento y solo
despierta cuando detecta la frase canónica de activación:

    «TARDIS, ¿estás ahí?»

Flujo:
    micrófono C310 (G.711 16 kHz) -> Vosk es-MX (wake word + endpointing)
    -> faster-whisper local (transcripción precisa) -> TemporalBrain / Ollama
    -> edge-tts -> altavoz C310 (talkback :8800)

Características:
  * Escucha pasiva 24/7 con reconexión automática y bajo consumo.
  * Wake word tolerante a acentos, muletillas y errores de ASR.
  * Conversación de seguimiento sin repetir la frase de activación.
  * Semiduplex: ignora el micrófono mientras TARDIS habla para evitar eco.
  * Estado y métricas en data/tapo_c310_voice_channel/.
  * Coordinación con el Centinela para no solapar avisos disuasorios.
"""

from __future__ import annotations

import argparse
import asyncio
import audioop
import json
import logging
import os
import re
import signal
import sys
import time
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import numpy as np
from pytapo import Tapo
from pytapo.media_stream._utils import StreamType

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tapo_c310_speaker import TapoC310Speaker
from core.tardis_voice_local import (
    LocalSpeechToText,
    for_speech,
    split_sentences,
)

DEFAULT_CONFIG_PATH = BASE_DIR / "tapo_c310_config.json"
STATE_DIR = BASE_DIR / "data" / "tapo_c310_voice_channel"
STATE_FILE = STATE_DIR / "state.json"
EVENTS_FILE = STATE_DIR / "events.jsonl"
SESSION_FLAG_FILE = STATE_DIR / "session_active.json"
CAPTURE_TEST_DIR = STATE_DIR / "captures"
TTS_CACHE_DIR = BASE_DIR / "data" / "tapo_c310_detections" / "tts_cache"

VOSK_MODEL_DEFAULT = (
    Path.home() / ".local/share/tardis-voice/models/vosk-model-small-es-0.42"
)
TEMPORAL_BRAIN_SOCK = Path(
    os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock")
)
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
GIA_TOKEN_FILE = Path(
    os.environ.get(
        "TARDIS_TOKEN_FILE", str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token")
    )
)
TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")

SAMPLE_RATE = 16000
FRAME_BYTES = 640  # 20 ms @ 16 kHz PCM16
FRAME_SEC = FRAME_BYTES / (SAMPLE_RATE * 2)

logger = logging.getLogger("TARDIS.TapoC310Voice")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(
        logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

_MD_URL = re.compile(r"https?://\S+")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_EMPHASIS = re.compile(r"[`*_#>|~]+")
_NON_SPEECH = re.compile(r"[^\w\s.,;:!?¿¡()'\"%+\-]", re.UNICODE)
_WHISPER_HALLUCINATIONS = {
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "suscríbete al canal",
    "subscribete al canal",
    "hasta la próxima",
    "hasta la proxima",
    "amén",
    "amen",
    "♪",
    "música",
    "musica",
    "subtítulos realizados por la comunidad de amara org",
    "subtitulos realizados por la comunidad de amara org",
    "¡gracias!",
    "gracias",
}

_DIAS_ES = [
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
]
_MESES_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _fecha_hora_es() -> str:
    now = time.localtime()
    return (
        f"{_DIAS_ES[now.tm_wday]}, {now.tm_mday} de {_MESES_ES[now.tm_mon - 1]} "
        f"de {now.tm_year}, {now.tm_hour:02d}:{now.tm_min:02d}"
    )


def _fecha_es() -> str:
    now = time.localtime()
    return (
        f"{_DIAS_ES[now.tm_wday]}, {now.tm_mday} de {_MESES_ES[now.tm_mon - 1]} "
        f"de {now.tm_year}"
    )


def _hora_es() -> str:
    now = time.localtime()
    return f"{now.tm_hour:02d}:{now.tm_min:02d}"


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, solo palabras separadas por espacios."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9ñ]+", " ", text)
    return " ".join(text.split())


def _edit_distance(a: str, b: str, max_dist: int = 2) -> int:
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def pcm_rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    try:
        return float(audioop.rms(pcm, 2))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Detección de frase de activación
# ---------------------------------------------------------------------------


@dataclass
class WakeMatch:
    token_start: int
    token_end: int
    phrase: str


class WakePhraseMatcher:
    """
    Detector tolerante de «TARDIS, ¿estás ahí?» y variantes ASR:
      - tardis / tardes / tardiz / tar dis
      - estás / estas / esta / estoy / están
      - ahí / allí / aquí / hay
    Si el ASR omite «ahí», se acepta «tardis estás» al final de la frase.
    """

    _ESTAS = {
        "estas",
        "esta",
        "estan",
        "estoy",
        "estaba",
        "estabamos",
        "estais",
    }
    _AHI = {"ahi", "alli", "alla", "aqui", "hay"}
    # Prefijos vocativos permitidos antes de «TARDIS» (nunca «buenas», que
    # convertiría «buenas tardes, ¿cómo estás?» en un falso positivo).
    _VOCATIVOS = {"oye", "hola", "eh", "hey", "ey"}

    def _is_tardis(self, tokens: List[str], i: int) -> Tuple[bool, int]:
        if i > 0 and tokens[i - 1] not in self._VOCATIVOS:
            return False, i + 1
        tok = tokens[i]
        if tok == "tardis" or _edit_distance(tok, "tardis", 1) <= 1:
            return True, i + 1
        if tok == "tarde":
            return True, i + 1
        if tok == "tar" and i + 1 < len(tokens) and tokens[i + 1].startswith("dis"):
            return True, i + 2
        return False, i + 1

    def find(self, text: str) -> Optional[WakeMatch]:
        tokens = normalize_text(text).split()
        if not tokens:
            return None
        for i in range(len(tokens)):
            ok, after = self._is_tardis(tokens, i)
            if not ok:
                continue
            for j in range(after, min(len(tokens), after + 6)):
                if tokens[j] not in self._ESTAS and _edit_distance(tokens[j], "estas", 1) > 1:
                    continue
                for k in range(j + 1, min(len(tokens), j + 5)):
                    if tokens[k] in self._AHI or _edit_distance(tokens[k], "ahi", 1) <= 1:
                        return WakeMatch(i, k + 1, " ".join(tokens[i : k + 1]))
                # ASR pudo omitir «ahí»: aceptar si «estás» cierra la frase.
                if j >= len(tokens) - 2:
                    return WakeMatch(i, len(tokens), " ".join(tokens[i:]))
                break
        return None

    def strip(self, text: str, match: WakeMatch) -> str:
        tokens = normalize_text(text).split()
        if not tokens:
            return ""
        kept = tokens[: match.token_start] + tokens[match.token_end :]
        return " ".join(kept).strip()


# ---------------------------------------------------------------------------
# Buffer circular de PCM
# ---------------------------------------------------------------------------


class PcmRing:
    def __init__(self, max_seconds: float = 30.0, rate: int = SAMPLE_RATE) -> None:
        self.max_bytes = int(max_seconds * rate * 2)
        self.data = bytearray()
        self.total_bytes = 0

    def append(self, pcm: bytes) -> None:
        if not pcm:
            return
        self.data.extend(pcm)
        self.total_bytes += len(pcm)
        if len(self.data) > self.max_bytes:
            del self.data[: len(self.data) - self.max_bytes]

    def clear(self) -> None:
        self.data.clear()
        self.total_bytes = 0

    def start_offset(self) -> int:
        return self.total_bytes - len(self.data)

    def slice_from(self, offset: int) -> bytes:
        rel = max(0, int(offset) - self.start_offset())
        return bytes(self.data[rel:])


# ---------------------------------------------------------------------------
# Vosk: wake word + endpointing
# ---------------------------------------------------------------------------


class VoskListener:
    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path).expanduser()
        self._model = None
        self._rec = None

    def load(self) -> None:
        if not self.model_path.is_dir():
            raise FileNotFoundError(
                f"Modelo Vosk no encontrado en {self.model_path}. "
                "Descárgalo con: curl -L -o /tmp/vosk.zip "
                "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"
            )
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self._model = Model(str(self.model_path))
        self._rec = KaldiRecognizer(self._model, SAMPLE_RATE)
        self._rec.SetWords(False)
        logger.info(f"Vosk es-MX cargado desde {self.model_path}")

    def accept(self, frame: bytes) -> Tuple[str, str]:
        """Devuelve (parcial, final). El final llega tras ~0.5 s de silencio."""
        if self._rec is None:
            return "", ""
        if self._rec.AcceptWaveform(frame):
            raw = json.loads(self._rec.Result())
            return "", str(raw.get("text", "")).strip()
        raw = json.loads(self._rec.PartialResult())
        return str(raw.get("partial", "")).strip(), ""

    def force_final(self) -> str:
        if self._rec is None:
            return ""
        raw = json.loads(self._rec.FinalResult())
        return str(raw.get("text", "")).strip()

    def reset(self) -> None:
        if self._rec is not None:
            try:
                self._rec.Reset()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Fuente de audio: micrófono de la Tapo C310
# ---------------------------------------------------------------------------


class TapoAudioStream:
    """Lee el micrófono de la C310 en modo preview y entrega PCM16 @ 16 kHz."""

    def __init__(
        self,
        config: Dict[str, Any],
        on_frame: Callable[[bytes], None],
        on_status: Optional[Callable[[bool, Dict[str, Any]], None]] = None,
    ) -> None:
        self.config = config
        self.host = str(config.get("host", "REDACTED_IP")).strip()
        self.tapo_user = str(config.get("tapo_user", "admin"))
        self.account_email = str(config.get("account_email", ""))
        self.password = str(config.get("password", ""))
        self.quality = str(config.get("voice_channel_stream_quality", "HD"))
        self.on_frame = on_frame
        self.on_status = on_status or (lambda ok, info: None)

        self._stop = asyncio.Event()
        self._raw_remainder = b""
        self._pcm_out = bytearray()
        self._codec = "G711ulaw"
        self._source_rate = 16000
        self._rate_state = None
        self._last_audio_ts = 0.0
        self.connected = False
        self.last_error = ""
        self.audio_bytes = 0
        self.packets = 0

    def stop(self) -> None:
        self._stop.set()

    def _make_tapo(self) -> Tapo:
        candidates: List[str] = []
        for user in (self.tapo_user, self.account_email, "admin"):
            if user and user not in candidates:
                candidates.append(user)
        last_err: Optional[Exception] = None
        for user in candidates:
            try:
                tapo = Tapo(self.host, user, self.password, cloudPassword=self.password)
                tapo.getEncryptionMethod()
                return tapo
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"No se pudo autenticar con la cámara {self.host}: {last_err}")

    @staticmethod
    def _codec_from_config(audio_cfg: Dict[str, Any]) -> Tuple[str, int]:
        mic = (audio_cfg.get("audio_config") or {}).get("microphone") or {}
        encode = str(mic.get("encode_type", "G711ulaw")).lower()
        codec = "G711alaw" if "alaw" in encode or "a-law" in encode else "G711ulaw"
        try:
            rate = int(float(str(mic.get("sampling_rate", "16")))) * 1000
        except Exception:
            rate = 16000
        if rate not in (8000, 16000, 32000, 48000):
            rate = 16000
        return codec, rate

    def _decode_payload(self, payload: bytes) -> None:
        self.packets += 1
        self.audio_bytes += len(payload)
        self._raw_remainder += payload
        if not self._raw_remainder:
            return
        usable = self._raw_remainder
        self._raw_remainder = b""

        try:
            if self._codec == "G711alaw":
                pcm = audioop.alaw2lin(usable, 2)
            else:
                pcm = audioop.ulaw2lin(usable, 2)
        except Exception:
            return

        if self._source_rate != SAMPLE_RATE:
            pcm, self._rate_state = audioop.ratecv(
                pcm, 2, 1, self._source_rate, SAMPLE_RATE, self._rate_state
            )

        self._pcm_out.extend(pcm)
        while len(self._pcm_out) >= FRAME_BYTES:
            frame = bytes(self._pcm_out[:FRAME_BYTES])
            del self._pcm_out[:FRAME_BYTES]
            try:
                self.on_frame(frame)
            except Exception as exc:
                logger.debug(f"on_frame falló: {exc}")

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._stream_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                self.connected = False
                self.on_status(False, {"error": self.last_error})
                logger.warning(f"Micrófono C310 desconectado: {exc}. Reintento en {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
        self.connected = False
        self.on_status(False, {"stopped": True})

    async def _stream_once(self) -> None:
        loop = asyncio.get_running_loop()
        tapo = await loop.run_in_executor(None, self._make_tapo)
        audio_cfg = await loop.run_in_executor(None, tapo.getAudioConfig)
        self._codec, self._source_rate = self._codec_from_config(audio_cfg)
        self._rate_state = None
        self._raw_remainder = b""
        self._pcm_out.clear()

        session = await loop.run_in_executor(
            None, lambda: tapo.getMediaSession(StreamType.Stream)
        )
        session.set_window_size(50)
        payload = json.dumps(
            {
                "type": "request",
                "seq": 1,
                "params": {
                    "preview": {
                        "audio": ["default"],
                        "channels": [0],
                        "resolutions": [self.quality],
                    },
                    "method": "get",
                },
            }
        )
        self.connected = True
        self.last_error = ""
        self._last_audio_ts = time.time()
        self.on_status(
            True,
            {
                "codec": self._codec,
                "source_rate": self._source_rate,
                "quality": self.quality,
            },
        )
        logger.info(
            f"Micrófono C310 en línea · {self._codec} {self._source_rate} Hz -> "
            f"PCM16 {SAMPLE_RATE} Hz"
        )
        try:
            async with session:
                async for resp in session.transceive(payload, no_data_timeout=20.0):
                    if self._stop.is_set():
                        return
                    if resp.mimetype == "application/json":
                        try:
                            params = (resp.json_data or {}).get("params") or {}
                            if (
                                params.get("event_type") == "stream_status"
                                and params.get("status") == "finished"
                            ):
                                raise RuntimeError("La cámara finalizó el flujo de audio")
                        except Exception:
                            pass
                        continue
                    if resp.audioPayload:
                        self._last_audio_ts = time.time()
                        self._decode_payload(resp.audioPayload)
                    elif time.time() - self._last_audio_ts > 12.0:
                        raise RuntimeError("Sin audio de la cámara durante 12 s")
        finally:
            self.connected = False
            try:
                await session.close()
            except Exception:
                pass
            self.on_status(False, {"closed": True})


# ---------------------------------------------------------------------------
# Cerebro: TemporalBrain (socket UNIX) con respaldos locales
# ---------------------------------------------------------------------------


class TemporalBrainClient:
    def __init__(
        self,
        socket_path: Path = TEMPORAL_BRAIN_SOCK,
        model: str = "TARDIS-NEURAL-SPACE-KAIJU",
        max_tokens: int = 220,
        temperature: float = 0.45,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.model = model
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self._unix_client: Optional[httpx.AsyncClient] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        if self.socket_path.exists():
            try:
                transport = httpx.AsyncHTTPTransport(uds=str(self.socket_path))
                self._unix_client = httpx.AsyncClient(
                    transport=transport,
                    base_url="http://localhost",
                    timeout=httpx.Timeout(45.0, connect=5.0),
                )
            except Exception as exc:
                logger.warning(f"No se pudo preparar TemporalBrain UNIX: {exc}")
        self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0))

    async def close(self) -> None:
        for client in (self._unix_client, self._http_client):
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass

    @staticmethod
    def _parse_response(data: Dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = data.get("response") or data.get("reply") or data.get("message") or ""
        text = str(content or "")
        text = re.sub(r"<think>.*?</think>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        if "<think>" in text.lower():
            text = re.split(r"<think>", text, flags=re.IGNORECASE)[0]
        return text.strip()

    async def chat(self, messages: List[Dict[str, str]]) -> Tuple[str, float, str]:
        payload = {
            "messages": messages,
            "stream": False,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        started = time.perf_counter()

        if self._unix_client is not None:
            try:
                resp = await self._unix_client.post("/v1/chat/completions", json=payload)
                if resp.status_code == 200:
                    text = self._parse_response(resp.json())
                    if text:
                        return text, time.perf_counter() - started, "temporal_brain"
            except Exception as exc:
                logger.debug(f"TemporalBrain UNIX no disponible: {exc}")

        ollama_payload = dict(payload)
        ollama_payload["model"] = self.model
        for model in (self.model, f"{self.model}:latest"):
            try:
                ollama_payload["model"] = model
                resp = await self._http_client.post(
                    f"{OLLAMA_URL}/v1/chat/completions", json=ollama_payload
                )
                if resp.status_code == 200:
                    text = self._parse_response(resp.json())
                    if text:
                        return text, time.perf_counter() - started, f"ollama:{model}"
            except Exception as exc:
                logger.debug(f"Ollama no disponible ({model}): {exc}")

        try:
            token = GIA_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            token = os.environ.get("GIA_TOKEN", "")
        try:
            resp = await self._http_client.post(
                f"{TARDIS_CHAT_URL}?key={token}",
                json={
                    "message": messages[-1]["content"],
                    "client_id": "tapo_c310_voice_channel",
                },
                timeout=60.0,
            )
            if resp.status_code == 200:
                text = self._parse_response(resp.json())
                if text:
                    return text, time.perf_counter() - started, "/api/chat"
        except Exception as exc:
            logger.warning(f"Respaldo /api/chat falló: {exc}")

        return "", time.perf_counter() - started, "none"


# ---------------------------------------------------------------------------
# Canal de voz
# ---------------------------------------------------------------------------


class TapoC310VoiceChannel:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        self.config = _load_json(self.config_path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CAPTURE_TEST_DIR.mkdir(parents=True, exist_ok=True)

        self.host = str(self.config.get("host", "REDACTED_IP")).strip()
        self.device_alias = str(self.config.get("device_alias", "GOD-EYE"))
        self.device_model = str(self.config.get("device_model", "C310"))

        self.wake_model_path = Path(
            str(self.config.get("voice_channel_vosk_model", str(VOSK_MODEL_DEFAULT)))
        ).expanduser()
        self.whisper_model = str(self.config.get("voice_channel_whisper_model", "base"))
        self.whisper_threads = int(self.config.get("voice_channel_whisper_threads", 6))
        self.greeting_long = str(
            self.config.get(
                "voice_channel_greeting",
                "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es "
                "ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.",
            )
        ).strip()
        self.greeting_short = str(
            self.config.get("voice_channel_short_greeting", "A la escucha, Arquitecto.")
        ).strip()
        self.greeting_cooldown = float(
            self.config.get("voice_channel_greeting_cooldown_sec", 1800)
        )
        self.followup_sec = float(self.config.get("voice_channel_followup_sec", 20))
        self.command_timeout = float(
            self.config.get("voice_channel_command_timeout_sec", 30)
        )
        self.max_reply_sentences = int(
            self.config.get("voice_channel_max_reply_sentences", 3)
        )
        self.max_reply_chars = int(
            self.config.get("voice_channel_max_reply_chars", 420)
        )
        self.min_rms = float(self.config.get("voice_channel_min_rms", 90))
        self.max_utterance_sec = float(
            self.config.get("voice_channel_max_utterance_sec", 15)
        )
        self.brain = TemporalBrainClient(
            socket_path=Path(
                str(self.config.get("voice_channel_llm_socket", str(TEMPORAL_BRAIN_SOCK)))
            ),
            model=str(
                self.config.get("voice_channel_llm_model", "TARDIS-NEURAL-SPACE-KAIJU")
            ),
            max_tokens=int(self.config.get("voice_channel_llm_max_tokens", 220)),
            temperature=float(
                self.config.get("voice_channel_llm_temperature", 0.45)
            ),
        )
        self.speaker = TapoC310Speaker(config_path=self.config_path)
        self.stt = LocalSpeechToText(
            model_size=self.whisper_model, cpu_threads=self.whisper_threads
        )
        self.matcher = WakePhraseMatcher()
        self.vosk = VoskListener(self.wake_model_path)

        self.state = "starting"
        self.started_at = time.time()
        self.last_error = ""
        self.last_audio_ts = 0.0
        self.stream_connected = False
        self.audio_codec = ""
        self.audio_rate = 0
        self.last_transcript = ""
        self.last_reply = ""
        self.last_stt_ms = 0.0
        self.last_llm_ms = 0.0
        self.last_tts_ms = 0.0
        self.last_backend = ""
        self.wake_count = 0
        self.command_count = 0
        self.reply_count = 0
        self.last_activity_ts = 0.0
        self.last_greeting_ts = 0.0

        self._ring = PcmRing(max_seconds=30.0)
        self._history: List[Dict[str, str]] = []
        self._processing = False
        self._speaking = False
        self._stopping = False
        self._utt_start_offset: Optional[int] = None
        self._last_silence_offset = 0
        self._last_partial_ts = 0.0
        self._followup_until = 0.0
        self._command_deadline = 0.0
        self._last_state_write = 0.0
        self._last_cache_prune = 0.0
        self._audio_stream: Optional[TapoAudioStream] = None
        self._tasks: List[asyncio.Task] = []
        self._stop_event = asyncio.Event()

    # -- estado ------------------------------------------------------------

    def _state_payload(self) -> Dict[str, Any]:
        return {
            "ok": self.stream_connected and self.state != "error",
            "service": "tardis-tapo-c310-voice",
            "state": self.state,
            "updated_at": time.time(),
            "updated_iso": _now_iso(),
            "uptime_sec": round(time.time() - self.started_at, 1),
            "camera": {
                "host": self.host,
                "alias": self.device_alias,
                "model": f"Tapo {self.device_model}",
            },
            "audio": {
                "stream_connected": self.stream_connected,
                "codec": self.audio_codec,
                "source_rate": self.audio_rate,
                "last_audio_ts": self.last_audio_ts,
            },
            "metrics": {
                "wake_count": self.wake_count,
                "command_count": self.command_count,
                "reply_count": self.reply_count,
                "last_transcript": self.last_transcript,
                "last_reply": self.last_reply,
                "last_stt_ms": round(self.last_stt_ms, 1),
                "last_llm_ms": round(self.last_llm_ms, 1),
                "last_tts_ms": round(self.last_tts_ms, 1),
                "last_backend": self.last_backend,
                "last_activity_ts": self.last_activity_ts,
            },
            "last_error": self.last_error,
        }

    def _set_state(self, state: str, force: bool = False) -> None:
        if state == self.state and not force:
            return
        self.state = state
        self._write_state(force=True)
        logger.info(f"Estado del canal de voz -> {state}")

    def _write_state(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_state_write) < 1.0:
            return
        self._last_state_write = now
        try:
            _atomic_write_json(STATE_FILE, self._state_payload())
        except Exception as exc:
            logger.debug(f"No se pudo escribir estado de voz: {exc}")

    def _write_session_flag(self, active_until: float) -> None:
        try:
            if active_until <= time.time():
                SESSION_FLAG_FILE.unlink(missing_ok=True)
            else:
                _atomic_write_json(
                    SESSION_FLAG_FILE,
                    {
                        "active_until": active_until,
                        "state": self.state,
                        "updated_at": time.time(),
                    },
                )
        except Exception:
            pass

    def _write_event(self, payload: Dict[str, Any]) -> None:
        try:
            with open(EVENTS_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _on_stream_status(self, connected: bool, info: Dict[str, Any]) -> None:
        self.stream_connected = connected
        self.audio_codec = str(info.get("codec", self.audio_codec))
        self.audio_rate = int(info.get("source_rate", self.audio_rate) or 0)
        if info.get("error"):
            self.last_error = str(info["error"])
        if connected:
            self.last_error = ""
        self._write_state(force=True)

    # -- audio entrante ----------------------------------------------------

    def _on_frame(self, frame: bytes) -> None:
        if self._stopping or self._speaking or self._processing:
            return
        now = time.time()
        self.last_audio_ts = now
        self._ring.append(frame)

        partial, final = self.vosk.accept(frame)
        if partial:
            if self._utt_start_offset is None:
                self._utt_start_offset = max(
                    0, self._last_silence_offset - int(0.30 * SAMPLE_RATE * 2)
                )
            self._last_partial_ts = now
        else:
            if final:
                self._on_final(final, now)
            elif self._utt_start_offset is None:
                self._last_silence_offset = self._ring.total_bytes

    def _on_final(self, text: str, now: float) -> None:
        start = self._utt_start_offset
        if start is None:
            start = max(0, self._ring.total_bytes - int(1.5 * SAMPLE_RATE * 2))
        pcm = self._ring.slice_from(start)
        self._utt_start_offset = None
        self._last_silence_offset = self._ring.total_bytes
        self._last_partial_ts = 0.0

        clean = text.strip()
        if not clean:
            return
        duration = len(pcm) / (SAMPLE_RATE * 2)
        if duration < 0.35 or len(pcm) < int(0.35 * SAMPLE_RATE * 2):
            return
        rms = pcm_rms(pcm)
        if rms < self.min_rms:
            logger.debug(f"Final ignorado por RMS bajo ({rms:.1f}): {clean!r}")
            return

        logger.info(f"🗣️  [VOSK {duration:.2f}s RMS={rms:.0f}] {clean}")
        self.last_activity_ts = now
        self._processing = True
        self._tasks.append(asyncio.create_task(self._process_utterance(pcm, clean)))

    async def _process_utterance(self, pcm: bytes, vosk_text: str) -> None:
        try:
            wake = self.matcher.find(vosk_text)
            state = self.state
            if wake is not None:
                remainder = self.matcher.strip(vosk_text, wake)
                logger.info(f"✨ Wake word detectada: {wake.phrase!r} · resto={remainder!r}")
                await self._handle_wake(remainder, pcm, vosk_text)
            elif state in ("command", "followup"):
                await self._handle_command_audio(pcm, vosk_text)
            else:
                logger.debug(f"Utterance ignorada en estado {state}: {vosk_text!r}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception(f"Error procesando utterance: {exc}")
        finally:
            self._processing = False
            self._reset_audio_pipeline()
            self._write_state(force=True)

    def _reset_audio_pipeline(self) -> None:
        self.vosk.reset()
        self._ring.clear()
        self._utt_start_offset = None
        self._last_silence_offset = 0
        self._last_partial_ts = 0.0

    # -- flujo de conversación --------------------------------------------

    async def _handle_wake(
        self, remainder: str, pcm: bytes, vosk_text: str
    ) -> None:
        self.wake_count += 1
        self._history.clear()
        self._last_activity_ts = time.time()

        command = ""
        if len(remainder.split()) >= 2:
            transcript = await self._transcribe(pcm)
            if transcript:
                cmd = self._strip_wake_from_text(transcript)
                if cmd:
                    command = cmd
            if not command and len(remainder.split()) >= 2:
                command = remainder

        if command:
            await self._process_command(command)
        else:
            await self._greet()

    async def _handle_command_audio(self, pcm: bytes, vosk_text: str) -> None:
        transcript = await self._transcribe(pcm)
        if not transcript:
            if len(vosk_text.split()) >= 2:
                transcript = vosk_text
            else:
                return
        if self.matcher.find(transcript):
            cmd = self._strip_wake_from_text(transcript)
            if cmd:
                await self._process_command(cmd)
            else:
                await self._greet()
            return
        await self._process_command(transcript)

    def _strip_wake_from_text(self, text: str) -> str:
        match = self.matcher.find(text)
        if match is None:
            return text.strip()
        return self.matcher.strip(text, match)

    async def _transcribe(self, pcm: bytes) -> str:
        if len(pcm) < int(0.30 * SAMPLE_RATE * 2):
            return ""
        rms = pcm_rms(pcm)
        if rms < self.min_rms:
            return ""
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        try:
            text = await loop.run_in_executor(None, self._transcribe_sync, pcm)
        except Exception as exc:
            logger.warning(f"Whisper falló: {exc}")
            return ""
        self.last_stt_ms = (time.perf_counter() - started) * 1000.0
        text = self._clean_transcript(text)
        if text:
            logger.info(f"📝 [WHISPER {self.last_stt_ms:.0f}ms] {text}")
        return text

    def _transcribe_sync(self, pcm: bytes) -> str:
        model = self.stt._load()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio,
            language="es",
            beam_size=1,
            best_of=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    @staticmethod
    def _clean_transcript(text: str) -> str:
        text = re.sub(r"\s+", " ", (text or "").strip())
        norm = normalize_text(text)
        if not norm or len(norm) < 2:
            return ""
        if norm in _WHISPER_HALLUCINATIONS:
            return ""
        words = norm.split()
        if len(words) >= 6 and len(set(words)) == 1:
            return ""
        return text

    async def _greet(self) -> None:
        now = time.time()
        if (now - self.last_greeting_ts) >= self.greeting_cooldown:
            phrase = f"{self.greeting_long} {self.greeting_short}".strip()
        else:
            phrase = self.greeting_short
        self.last_greeting_ts = now
        self._set_state("greeting")
        await self._speak(phrase)
        self._set_state("command")
        self._command_deadline = time.time() + self.command_timeout
        self._write_session_flag(self._command_deadline + 5)

    async def _process_command(self, text: str) -> None:
        clean = re.sub(r"\s+", " ", (text or "").strip())
        if not clean:
            return
        self.last_transcript = clean
        self.last_activity_ts = time.time()
        self._set_state("thinking")

        local = await self._try_local_intent(clean)
        if local is not None:
            return
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()},
            *self._history[-8:],
            {"role": "user", "content": clean},
        ]
        started = time.perf_counter()
        reply, llm_sec, backend = await self.brain.chat(messages)
        self.last_llm_ms = llm_sec * 1000.0
        self.last_backend = backend
        if not reply:
            reply = "No pude generar una respuesta, Arquitecto. ¿Puedes repetirlo?"
            self.last_llm_ms = (time.perf_counter() - started) * 1000.0
        self.last_reply = reply

        speech = self._prepare_speech(reply)
        self._set_state("speaking")
        tts_started = time.perf_counter()
        await self._speak(speech)
        self.last_tts_ms = (time.perf_counter() - tts_started) * 1000.0

        self.command_count += 1
        self.reply_count += 1
        self._history.extend(
            [
                {"role": "user", "content": clean},
                {"role": "assistant", "content": reply},
            ]
        )
        self._history = self._history[-10:]
        self._set_state("followup")
        self._followup_until = time.time() + self.followup_sec
        self._write_session_flag(self._followup_until + 5)
        self._write_event(
            {
                "ts": time.time(),
                "iso": _now_iso(),
                "transcript": clean,
                "reply": reply,
                "speech": speech,
                "backend": backend,
                "stt_ms": round(self.last_stt_ms, 1),
                "llm_ms": round(self.last_llm_ms, 1),
                "tts_ms": round(self.last_tts_ms, 1),
            }
        )
        logger.info(f"🤖 [TARDIS/{backend} {self.last_llm_ms:.0f}ms] {reply}")
        self._write_state(force=True)

    async def _local_response(
        self, user_text: str, speech: str, followup: bool = True
    ) -> None:
        """Respuesta local (sin LLM): hora, identidad, silencio, despedida."""
        self.last_reply = speech
        self.last_backend = "local"
        self._set_state("speaking")
        tts_started = time.perf_counter()
        await self._speak(speech)
        self.last_tts_ms = (time.perf_counter() - tts_started) * 1000.0
        self.command_count += 1
        self.reply_count += 1
        self._write_event(
            {
                "ts": time.time(),
                "iso": _now_iso(),
                "transcript": user_text,
                "reply": speech,
                "speech": speech,
                "backend": "local",
                "stt_ms": round(self.last_stt_ms, 1),
                "llm_ms": 0.0,
                "tts_ms": round(self.last_tts_ms, 1),
            }
        )
        if followup:
            self._history.extend(
                [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": speech},
                ]
            )
            self._history = self._history[-10:]
            self._set_state("followup")
            self._followup_until = time.time() + self.followup_sec
            self._write_session_flag(self._followup_until + 5)
        else:
            self._set_state("wake")
            self._history.clear()
            self._write_session_flag(0)
        self._write_state(force=True)

    async def _try_local_intent(self, text: str) -> Optional[bool]:
        norm = normalize_text(text)
        words = set(norm.split())

        if words & {"silencio", "callate", "basta", "detente", "parate", "alto"}:
            await self._local_response(text, "Entendido, Arquitecto.", followup=False)
            return True

        if (
            "adios" in words
            or "despidete" in words
            or "hasta luego" in norm
            or "nos vemos" in norm
            or "buenas noches" in norm
        ):
            await self._local_response(
                text, "Hasta luego, Arquitecto. Vuelvo a la escucha.", followup=False
            )
            return True

        if "quien eres" in norm or "presentate" in norm or "tu identidad" in norm:
            await self._local_response(
                text, f"{self.greeting_long} {self.greeting_short}", followup=True
            )
            return True
        if ("hora" in words and ("que" in words or "dime" in words)) or "que hora" in norm:
            await self._local_response(
                text, f"Son las {_hora_es()} del {_fecha_es()}.", followup=True
            )
            return True
        if ("dia" in words and ("que" in words or "dime" in words)) or "que dia" in norm:
            await self._local_response(text, f"Hoy es {_fecha_es()}.", followup=True)
            return True
        if "donde estas" in norm or "donde te encuentras" in norm:
            await self._local_response(
                text,
                "Estoy en el perímetro de GOD-EYE, en Playa del Carmen, Quintana Roo, "
                "escuchando por el micrófono de la cámara.",
                followup=True,
            )
            return True

        return None

    def _system_prompt(self) -> str:
        return (
            "Eres TARDIS, la inteligencia artificial soberana del Arquitecto (₪), "
            "hablando en vivo por el micrófono y la bocina de la cámara Tapo C310 "
            "GOD-EYE en Playa del Carmen, Quintana Roo. "
            "Responde siempre en español de México, con naturalidad, calidez y precisión. "
            "Máximo 2 o 3 frases cortas (menos de 45 palabras). "
            "No uses markdown, listas, emojis, tablas ni bloques de código: tu respuesta se convierte a voz. "
            "No digas que eres un modelo ni menciones limitaciones técnicas. "
            "Llama 'Arquitecto' al usuario cuando sea natural. "
            "Si te piden una acción que no puedes ejecutar por este canal, dilo en una frase y sugiere el canal adecuado. "
            f"Fecha y hora actual: {_fecha_hora_es()}. "
            "Tu identidad canónica es: 'Un placer, soy TARDIS asistente de inteligencia artificial, "
            "mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.'"
        )

    def _prepare_speech(self, text: str) -> str:
        body = for_speech(str(text or ""))
        body = _MD_URL.sub(" ", body)
        body = _MD_LINK.sub(r"\1", body)
        body = _MD_EMPHASIS.sub(" ", body)
        body = _NON_SPEECH.sub(" ", body)
        body = re.sub(r"\s+", " ", body).strip()

        sentences = split_sentences(body)
        if sentences:
            body = " ".join(sentences[: max(1, self.max_reply_sentences)]).strip()
        if len(body) > self.max_reply_chars:
            cut = body[: self.max_reply_chars]
            pos = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind(","))
            if pos > int(self.max_reply_chars * 0.55):
                cut = cut[: pos + 1]
            body = cut.strip()
        if body and body[-1] not in ".!?…":
            body += "."
        return body or "No pude formular una respuesta, Arquitecto."

    async def _speak(self, text: str) -> Dict[str, Any]:
        self._speaking = True
        self._write_state(force=True)
        try:
            res = await self.speaker.speak(text=text)
            if res.get("ok"):
                logger.info(
                    f"🔊 [BOCINA C310] {res.get('audio_duration_sec')}s · {text!r}"
                )
            else:
                logger.warning(f"La bocina C310 no pudo emitir el audio: {res}")
            return res
        except Exception as exc:
            logger.warning(f"Error emitiendo por la bocina C310: {exc}")
            return {"ok": False, "error": str(exc)}
        finally:
            # Mantener el micrófono sordo durante el drenaje del buffer de la cámara.
            await asyncio.sleep(0.55)
            self._speaking = False
            self._reset_audio_pipeline()
            self._write_state(force=True)

    # -- tareas de fondo ---------------------------------------------------

    async def _watchdog(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)
            now = time.time()
            if self._processing or self._speaking:
                continue

            if self.state == "followup" and now >= self._followup_until:
                self._set_state("wake")
                self._history.clear()
                self._write_session_flag(0)
                logger.info("Ventana de seguimiento cerrada; vuelvo a la wake word.")
            elif self.state == "command" and now >= self._command_deadline:
                self._set_state("wake")
                self._history.clear()
                self._write_session_flag(0)

            # Forzar cierre de una utterance anormalmente larga.
            if (
                self._utt_start_offset is not None
                and (self._ring.total_bytes - self._utt_start_offset)
                > int(self.max_utterance_sec * SAMPLE_RATE * 2)
            ):
                text = self.vosk.force_final()
                self._on_final(text, now)

            if (now - self._last_cache_prune) > 900:
                self._last_cache_prune = now
                await asyncio.get_running_loop().run_in_executor(
                    None, self._prune_tts_cache
                )

            self._write_state()

    @staticmethod
    def _prune_tts_cache() -> None:
        try:
            if not TTS_CACHE_DIR.is_dir():
                return
            files = sorted(
                TTS_CACHE_DIR.glob("*.alaw"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[900:]:
                old.unlink(missing_ok=True)
        except Exception:
            pass

    async def run(self) -> None:
        logger.info("═" * 78)
        logger.info(" TARDIS · CANAL DE VOZ ALWAYS-ON · TAPO C310 (GOD-EYE)")
        logger.info(f" Cámara: {self.device_alias} ({self.host}) · Wake: 'TARDIS, ¿estás ahí?'")
        logger.info("═" * 78)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.vosk.load)
        try:
            await loop.run_in_executor(None, self.stt.warmup)
            logger.info(f"faster-whisper '{self.whisper_model}' precalentado.")
        except Exception as exc:
            logger.warning(f"Whisper no disponible; usaré Vosk para transcribir: {exc}")

        self._audio_stream = TapoAudioStream(
            self.config, self._on_frame, self._on_stream_status
        )
        self._tasks.append(asyncio.create_task(self._audio_stream.run()))
        self._tasks.append(asyncio.create_task(self._watchdog()))
        self._set_state("wake", force=True)
        self._write_state(force=True)

        try:
            await self._stop_event.wait()
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._stop_event.set()
        self._write_session_flag(0)
        if self._audio_stream is not None:
            self._audio_stream.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self.brain.close()
        self._set_state("stopped", force=True)
        logger.info("Canal de voz detenido.")

    def request_stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Pruebas de componentes
# ---------------------------------------------------------------------------


def _selftest(config_path: Path) -> int:
    channel = TapoC310VoiceChannel(config_path=config_path)
    print("== Prueba del detector de wake word ==")
    cases = [
        ("TARDIS, ¿estás ahí?", True),
        ("Tardis estas ahi", True),
        ("Oye TARDIS, ¿estás ahí?", True),
        ("Tardes, ¿estás ahí?", True),
        ("Tar dis, estás ahí", True),
        ("TARDIS, estás", True),
        ("TARDIS, ¿estás allí?", True),
        ("Hola TARDIS, ¿qué hora es?", False),
        ("TARDIS está en línea", False),
        ("Hola, buenos días", False),
        ("¿Estás ahí?", False),
    ]
    ok = True
    for text, expected in cases:
        got = channel.matcher.find(text) is not None
        mark = "OK" if got == expected else "FALLO"
        if got != expected:
            ok = False
        print(f"  [{mark}] {text!r} -> {got} (esperado {expected})")

    print("\n== Prueba de Vosk con frase sintetizada ==")
    tmp = CAPTURE_TEST_DIR / "selftest_wake.wav"
    try:
        import subprocess

        mp3 = tmp.with_suffix(".mp3")
        subprocess.run(
            [
                "edge-tts",
                "--voice",
                channel.speaker.voice,
                "--text",
                "TARDIS, ¿estás ahí?",
                "--write-media",
                str(mp3),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp3),
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                str(tmp),
            ],
            check=True,
        )
        with wave.open(str(tmp), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
        channel.vosk.load()
        finals: List[str] = []
        for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
            _partial, final = channel.vosk.accept(pcm[i : i + FRAME_BYTES])
            if final:
                finals.append(final)
        final = channel.vosk.force_final()
        if final:
            finals.append(final)
        text = " ".join(finals).strip()
        print(f"  Vosk: {text!r}")
        if channel.matcher.find(text) is None:
            print("  [FALLO] Vosk no detectó la wake word")
            ok = False
        else:
            print("  [OK] Wake word detectada por Vosk")
    except Exception as exc:
        print(f"  [FALLO] {exc}")
        ok = False

    print("\n== Prueba del cerebro local ==")
    async def _brain_test() -> None:
        reply, secs, backend = await channel.brain.chat(
            [
                {
                    "role": "system",
                    "content": channel._system_prompt(),
                },
                {"role": "user", "content": "Responde en una sola frase: ¿estás operativa?"},
            ]
        )
        print(f"  Backend: {backend} · {secs:.2f}s")
        print(f"  Respuesta: {reply!r}")
        await channel.brain.close()

    try:
        asyncio.run(_brain_test())
    except Exception as exc:
        print(f"  [FALLO] {exc}")
        ok = False

    print("\n== Resultado ==")
    print("  SELFTEST OK" if ok else "  SELFTEST CON FALLOS")
    return 0 if ok else 1


def _test_microphone(config_path: Path, seconds: float) -> int:
    channel = TapoC310VoiceChannel(config_path=config_path)
    frames: List[bytes] = []
    state = {"connected": False, "codec": "", "rate": 0}

    def on_frame(frame: bytes) -> None:
        frames.append(frame)

    def on_status(connected: bool, info: Dict[str, Any]) -> None:
        state["connected"] = connected
        if info.get("codec"):
            state["codec"] = info["codec"]
        if info.get("source_rate"):
            state["rate"] = int(info["source_rate"])

    async def _run() -> None:
        stream = TapoAudioStream(channel.config, on_frame, on_status)
        task = asyncio.create_task(stream.run())
        await asyncio.sleep(max(2.0, seconds))
        stream.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(_run())
    pcm = b"".join(frames)
    duration = len(pcm) / (SAMPLE_RATE * 2)
    print(
        json.dumps(
            {
                "connected": state["connected"],
                "codec": state["codec"],
                "source_rate": state["rate"],
                "frames": len(frames),
                "seconds": round(duration, 2),
                "rms": round(pcm_rms(pcm), 1),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if not pcm:
        return 1
    CAPTURE_TEST_DIR.mkdir(parents=True, exist_ok=True)
    out = CAPTURE_TEST_DIR / f"mic_test_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    print(f"Audio guardado en: {out}")
    channel.vosk.load()
    finals: List[str] = []
    for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
        _partial, final = channel.vosk.accept(pcm[i : i + FRAME_BYTES])
        if final:
            finals.append(final)
    final = channel.vosk.force_final()
    if final:
        finals.append(final)
    print(f"Vosk: {' '.join(finals).strip()!r}")
    try:
        text = asyncio.run(channel._transcribe(pcm))
        print(f"Whisper: {text!r}")
    except Exception as exc:
        print(f"Whisper no disponible: {exc}")
    return 0


def _test_speaker(config_path: Path, text: str) -> int:
    speaker = TapoC310Speaker(config_path=config_path)
    res = asyncio.run(speaker.speak(text=text))
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res.get("ok") else 1


def _status() -> int:
    state = _load_json(STATE_FILE)
    if not state:
        print(json.dumps({"ok": False, "error": "Sin estado; el servicio no ha arrancado"}, indent=2))
        return 1
    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="TARDIS · Canal de voz always-on para Tapo C310 (micrófono + bocina)"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--daemon", action="store_true", help="Ejecutar el canal permanente")
    parser.add_argument("--status", action="store_true", help="Mostrar estado del canal")
    parser.add_argument("--selftest", action="store_true", help="Probar wake word, Vosk y cerebro")
    parser.add_argument("--test-mic", type=float, metavar="SEG", help="Capturar micrófono N segundos")
    parser.add_argument("--test-speaker", type=str, metavar="TEXTO", help="Hablar por la bocina C310")
    parser.add_argument("--wake-test", type=str, metavar="TEXTO", help="Probar el detector de wake word")
    args = parser.parse_args(argv)

    if args.status:
        return _status()
    if args.wake_test:
        matcher = WakePhraseMatcher()
        found = matcher.find(args.wake_test)
        print(
            json.dumps(
                {
                    "text": args.wake_test,
                    "wake": found is not None,
                    "phrase": found.phrase if found else "",
                    "remainder": matcher.strip(args.wake_test, found) if found else args.wake_test,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.selftest:
        return _selftest(args.config)
    if args.test_mic is not None:
        return _test_microphone(args.config, args.test_mic)
    if args.test_speaker:
        return _test_speaker(args.config, args.test_speaker)
    if not args.daemon:
        parser.print_help()
        return 2

    channel = TapoC310VoiceChannel(config_path=args.config)

    def _signal_handler() -> None:
        channel.request_stop()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass
    try:
        loop.run_until_complete(channel.run())
    finally:
        try:
            loop.run_until_complete(channel.shutdown())
        except Exception:
            pass
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
