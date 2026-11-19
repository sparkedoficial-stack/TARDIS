#!/usr/bin/env python3
"""
core/tardis_infinite_voice.py - Chat de Voz Infinito Full-Duplex para TARDIS
=============================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL
Arquitecto: El Arquitecto (₪)

Motor conversacional de voz continuo (sin chasquidos, sin pulsaciones repetidas
y sin límite de turnos) sobre PipeWire + faster-whisper local + TemporalBrain
streaming + edge-tts por oración + memoria continua en OfflineChatVault.

Flujo full-duplex:
  Micrófono PipeWire (pw-record 16kHz PCM)
    -> SpeechSegmenter (WebRTC VAD + piso de ruido adaptativo + Barge-In)
    -> faster-whisper local en memoria (CPU int8, filtro de alucinaciones)
    -> Enrutador soberano (`programa ...` FTL, bóveda protegida, comandos de voz)
    -> TemporalBrain SSE (/tmp/temporal_brain.sock) con fallback :8757 / Ollama
    -> Síntesis TTS por oración en paralelo (edge-tts Cortana Neural)
    -> Reproducción continua (ffplay/pw-play) con interrupción instantánea (Barge-In)
    -> Persistencia y recuperación semántica en OfflineChatVault (continuidad infinita)
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
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
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VOICE_LIB = Path.home() / ".local" / "share" / "tardis-voice" / "lib"
if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
    sys.path.insert(0, str(VOICE_LIB))

from core.tardis_voice_local import (
    DEFAULT_VOICE,
    LocalSpeechToText,
    TARDIS_CHAT_URL,
    TARDIS_TOKEN_FILE,
    TextToSpeech,
    for_speech,
)

try:
    import webrtcvad  # type: ignore[import-untyped]
    HAS_WEBRTCVAD = True
except Exception:
    webrtcvad = None
    HAS_WEBRTCVAD = False

try:
    import httpx
    HAS_HTTPX = True
except Exception:
    httpx = None  # type: ignore[assignment]
    HAS_HTTPX = False

logger = logging.getLogger("TARDIS.InfiniteVoice")

TEMPORAL_BRAIN_SOCK = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, "
    "mi tarea es ayudarte a explorar las maravillas de la realidad "
    "y todas las dimensiones temporales. Chat de voz infinito activo, te escucho."
)

WHISPER_HALLUCINATIONS = {
    "subtitulos realizados por la comunidad de amara.org",
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulos por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "gracias por ver el video",
    "gracias por ver",
    "suscribete al canal",
    "suscríbete al canal",
    "amara.org",
    "...",
    ".",
    "you",
    "thank you.",
    "mbc",
}

VOICE_ALIASES = {
    "dalia": "es-MX-DaliaNeural",
    "cortana": "es-MX-DaliaNeural",
    "jorge": "es-MX-JorgeNeural",
    "elvira": "es-ES-ElviraNeural",
    "jenny": "en-US-JennyNeural",
}

_THINK_RE = re.compile(r"<think>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")

C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_GOLD = "\033[38;5;220m"


@dataclass
class InfiniteVoiceConfig:
    voice: str = DEFAULT_VOICE
    whisper_model: str = os.environ.get("TARDIS_VOICE_WHISPER_MODEL", "base")
    whisper_threads: int = int(os.environ.get("TARDIS_VOICE_WHISPER_THREADS", "6"))
    language: str = os.environ.get("TARDIS_VOICE_LANG", "es")
    sample_rate: int = 16000
    frame_ms: int = 30
    vad_aggressiveness: int = 2
    silence_hold_ms: int = 850
    min_speech_ms: int = 300
    max_utterance_ms: int = 25000
    pre_roll_ms: int = 300
    barge_in: bool = True
    barge_in_rms: float = 0.075
    barge_in_frames: int = 10
    client_id: str = "infinite_voice_local"
    session_id: str = "infinite_voice_local"
    max_history_turns: int = 20
    daemon: bool = False
    greeting: bool = True
    no_play: bool = False
    fresh: bool = False

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000)

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2


def extract_ready_sentence(buffer: str, is_first: bool = False) -> Tuple[Optional[str], str]:
    """Extrae una oración completa lista para TTS con baja latencia en el primer fragmento."""
    min_len = 20 if is_first else 42
    if len(buffer) < min_len:
        return None, buffer

    match = _SENTENCE_SPLIT_RE.search(buffer)
    if match and match.start() >= min_len:
        sentence = buffer[: match.start() + 1].strip()
        rest = buffer[match.end():]
        return sentence, rest

    if len(buffer) >= 90:
        comma_idx = buffer.find(", ", 52)
        if comma_idx != -1:
            sentence = buffer[: comma_idx + 1].strip()
            rest = buffer[comma_idx + 2:]
            return sentence, rest

    return None, buffer


def is_hallucination(text: str) -> bool:
    norm = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return not norm or len(norm) < 2 or norm in WHISPER_HALLUCINATIONS


class SpeechSegmenter:
    """
    Máquina de estados VAD + piso de ruido adaptativo sobre tramas PCM 16kHz s16le.
    Separa enunciados completos del usuario y detecta Barge-In sostenido durante TTS.
    """

    def __init__(self, cfg: InfiniteVoiceConfig):
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

    def _frame_rms(self, frame: bytes) -> float:
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
        """
        Procesa una trama de `frame_bytes` bytes.
        Retorna: {"utterance": Optional[bytes], "barge_in": bool, "rms": float}
        """
        rms = self._frame_rms(frame)
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
                        return {"utterance": None, "barge_in": True, "rms": rms}
                else:
                    self.barge_streak = max(0, self.barge_streak - 1)
                    self.pre_roll.append(frame)
            else:
                self.pre_roll.append(frame)
            return {"utterance": None, "barge_in": False, "rms": rms}

        self.barge_streak = 0
        is_voice = self._is_speech(frame, rms, threshold)

        if not self.in_speech:
            self.noise_floor = 0.98 * self.noise_floor + 0.02 * min(rms, 0.035)
            self.pre_roll.append(frame)
            if is_voice:
                self.in_speech = True
                self.speech_frames = list(self.pre_roll)
                self.silence_frames = 0
            return {"utterance": None, "barge_in": False, "rms": rms}

        self.speech_frames.append(frame)
        if is_voice:
            self.silence_frames = 0
        else:
            self.silence_frames += 1

        if self.silence_frames >= self._hold_frames or len(self.speech_frames) >= self._max_frames:
            frames = self.speech_frames
            self.reset_utterance()
            if len(frames) >= self._min_frames:
                return {"utterance": b"".join(frames), "barge_in": False, "rms": rms}
        return {"utterance": None, "barge_in": False, "rms": rms}


class PipeWireMicStream:
    """Captura continua 16kHz s16le mono mediante pw-record (o arecord como respaldo)."""

    def __init__(self, sample_rate: int = 16000, frame_bytes: int = 960):
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
        raise RuntimeError("No se encontró pw-record ni arecord para capturar micrófono.")

    def start(self) -> None:
        self._stop.clear()
        self._spawn()

    def _spawn(self) -> None:
        self._terminate_proc()
        cmd = self._build_cmd()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
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
                time.sleep(0.25)
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
            # Proceso terminado o corte transitorio: reiniciar automáticamente
            self._terminate_proc()
        return None

    def stop(self) -> None:
        self._stop.set()
        self._terminate_proc()


class StreamingAudioPlayer:
    """Reproductor en cola con soporte de interrupción instantánea (Barge-In)."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
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
        # Pequeña ventana de guarda contra eco residual de bocinas (180ms)
        return (time.monotonic() - self._last_play_end) < 0.18

    def _player_cmd(self, audio_path: Path) -> Optional[List[str]]:
        if shutil.which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]
        if shutil.which("pw-play"):
            return ["pw-play", str(audio_path)]
        return None

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
                with self._proc_lock:
                    self._proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
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
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def enqueue(self, audio_path: Path) -> None:
        self._queue.put(audio_path)

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
        self._playing = False

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


class InfiniteVoiceChat:
    """Orquestador del Chat de Voz Infinito local de TARDIS."""

    def __init__(self, cfg: Optional[InfiniteVoiceConfig] = None):
        self.cfg = cfg or InfiniteVoiceConfig()
        self.stt = LocalSpeechToText(
            model_size=self.cfg.whisper_model,
            cpu_threads=self.cfg.whisper_threads,
        )
        self.tts = TextToSpeech(voice=self.cfg.voice)
        self.player = StreamingAudioPlayer(enabled=not self.cfg.no_play)
        self.segmenter = SpeechSegmenter(self.cfg)
        self.mic = PipeWireMicStream(
            sample_rate=self.cfg.sample_rate,
            frame_bytes=self.cfg.frame_bytes,
        )
        self.history: List[Dict[str, str]] = []
        self.turn_count = 0
        self.started_at = time.time()
        self.paused = False
        self.running = False

        self._turn_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._active_turn_thread: Optional[threading.Thread] = None
        self._vault = self._init_vault()
        if not self.cfg.fresh:
            self._restore_recent_history()

    def _init_vault(self):
        try:
            from core.offline_chat_vault import get_offline_chat_vault
            return get_offline_chat_vault()
        except Exception as exc:
            logger.debug("OfflineChatVault no disponible: %s", exc)
            return None

    def _restore_recent_history(self, n_turns: int = 6) -> None:
        if self._vault is None:
            return
        try:
            rows = self._vault.get_recent(
                limit=n_turns,
                client_id=self.cfg.client_id,
                is_local=False,
            )
            for r in rows:
                u = (r.get("user_message") or "").strip()
                a = (r.get("assistant_reply") or "").strip()
                if u:
                    self.history.append({"role": "user", "content": u})
                if a:
                    self.history.append({"role": "assistant", "content": a})
        except Exception as exc:
            logger.debug("No se pudo restaurar historial de voz: %s", exc)

    def _log(self, msg: str) -> None:
        if self.cfg.daemon:
            logger.info(re.sub(r"\x1b\[[0-9;]*m", "", msg))
        else:
            print(msg, flush=True)

    def _get_token(self) -> str:
        try:
            if TARDIS_TOKEN_FILE.exists():
                return TARDIS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return os.environ.get("GIA_AUTH_TOKEN") or os.environ.get("GIA_TOKEN", "")

    def transcribe_pcm(self, pcm_bytes: bytes) -> Tuple[str, float]:
        if not pcm_bytes:
            return "", 0.0
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size < int(self.cfg.sample_rate * 0.25):
            return "", 0.0
        model = self.stt._load()
        t0 = time.perf_counter()
        segments, _ = model.transcribe(
            pcm,
            language=self.cfg.language,
            beam_size=1,
            best_of=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 320, "speech_pad_ms": 180},
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0
        if is_hallucination(text):
            return "", elapsed
        return text, elapsed

    def _build_messages(self, user_text: str) -> List[Dict[str, str]]:
        sys_prompt = (
            "Eres TARDIS, asistente de inteligencia artificial del Arquitecto (₪) "
            "en un CHAT DE VOZ INFINITO en vivo, continuo y manos libres. "
            "Responde en español de forma clara, natural, cálida y conversacional "
            "(idealmente 1 a 4 oraciones directas para escucharse por bocinas, sin tablas ni bloques de código)."
        )
        if self._vault is not None:
            try:
                ctx = self._vault.get_context_for_prompt(
                    query=user_text,
                    k_relevant=4,
                    n_recent=3,
                    is_local=True,
                )
                if ctx:
                    sys_prompt += "\n\n[MEMORIA CONTINUA TARDIS]:\n" + ctx[:1800]
            except Exception:
                pass

        msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
        msgs.extend(self.history[-(self.cfg.max_history_turns * 2):])
        msgs.append({"role": "user", "content": user_text})
        return msgs

    def stream_llm(self, user_text: str, cancel_event: threading.Event) -> Iterator[str]:
        msgs = self._build_messages(user_text)

        # 1. TemporalBrain UNIX Socket (máxima velocidad por streaming SSE)
        if HAS_HTTPX and TEMPORAL_BRAIN_SOCK.exists():
            try:
                transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
                with httpx.Client(transport=transport, base_url="http://localhost", timeout=60.0) as client:
                    payload = {
                        "messages": msgs,
                        "stream": True,
                        "max_tokens": 380,
                        "temperature": 0.38,
                    }
                    with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                        if resp.status_code == 200:
                            in_think = False
                            emitted = False
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
                                    emitted = True
                                    yield delta
                            if emitted:
                                return
            except Exception as exc:
                logger.warning("Fallback desde TemporalBrain: %s", exc)

        # 2. Servidor GIA / TARDIS local (:8757/api/chat)
        try:
            tok = self._get_token()
            payload = json.dumps({"message": user_text, "client_id": self.cfg.client_id}).encode("utf-8")
            req = urllib.request.Request(
                f"{TARDIS_CHAT_URL}?key={tok}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            reply = str(data.get("response") or data.get("reply") or data.get("message") or "").strip()
            reply = _THINK_RE.sub("", reply).strip()
            if reply:
                yield reply
                return
        except Exception as exc:
            logger.warning("Fallback desde :8757/api/chat: %s", exc)

        # 3. Ollama local directo (:11434)
        if HAS_HTTPX:
            try:
                model = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
                with httpx.Client(timeout=90.0) as client:
                    with client.stream(
                        "POST",
                        f"{OLLAMA_URL}/api/chat",
                        json={"model": model, "messages": msgs, "stream": True},
                    ) as resp:
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
                            if delta:
                                yield delta
            except Exception as exc:
                yield f"No logré contactar con los motores locales: {exc}"

    def _synthesize_to_file(self, sentence: str) -> Optional[Path]:
        clean = for_speech(sentence)
        if not clean:
            return None
        try:
            return self.tts.synthesize(clean)
        except Exception as exc:
            logger.debug("edge-tts no disponible (%s), intentando respaldo local", exc)
            try:
                import voice as voice_mod
                data = voice_mod.synthesize_to_bytes(clean, self.tts.voice)
                if data:
                    out = self.tts._target().with_suffix(".wav")
                    out.write_bytes(data)
                    return out
            except Exception:
                pass
        return None

    def _speak_text(self, text: str, cancel_event: Optional[threading.Event] = None) -> None:
        if self.cfg.no_play or not text.strip():
            return
        audio_path = self._synthesize_to_file(text)
        if audio_path:
            self.player.enqueue(audio_path)
            self.player.wait_idle(cancel_event=cancel_event)

    def _handle_control_intent(self, text: str) -> Optional[str]:
        low = re.sub(r"[^\w\sáéíóúñü]", "", text.lower()).strip()

        if self.paused:
            if any(k in low for k in ("despierta", "escucha", "reanuda", "vuelve", "tardis")):
                self.paused = False
                return "Aquí estoy de nuevo, Arquitecto. Escucha continua reactivada."
            return "__PAUSED_IGNORE__"

        if low in ("tardis pausa", "pausa el chat", "pausa voz", "modo silencio", "silencio tardis"):
            self.paused = True
            return "Entendido, entro en pausa silenciosa. Di TARDIS despierta cuando quieras continuar."

        if low in ("borra historial", "nueva conversacion", "nueva conversación", "reinicia sesion", "reinicia sesión"):
            self.history.clear()
            return "Memoria de esta sesión reiniciada. Seguimos conversando."

        if low in ("finalizar chat de voz", "cerrar chat de voz", "apagar chat de voz"):
            self.running = False
            return "Cerrando sesión de voz infinita. Hasta pronto, Arquitecto."

        m_voice = re.search(r"cambia(?:r)?(?:\s+la)?\s+voz\s+a\s+(\w+)", low)
        if m_voice:
            alias = m_voice.group(1)
            new_voice = VOICE_ALIASES.get(alias)
            if new_voice:
                self.tts.voice = new_voice
                return f"Voz cambiada a {alias}. ¿Cómo me escuchas ahora?"
            return f"No tengo registrada la voz {alias}. Puedo usar Dalia, Jorge, Elvira o Jenny."

        return None

    def _record_turn_async(self, user_text: str, assistant_reply: str) -> None:
        if self._vault is None or not assistant_reply.strip():
            return

        def _save() -> None:
            try:
                self._vault.record_turn(
                    user_message=user_text,
                    assistant_reply=assistant_reply,
                    session_id=self.cfg.session_id,
                    client_id=self.cfg.client_id,
                    model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                    direction="present",
                )
            except Exception as exc:
                logger.debug("Error guardando turno en OfflineChatVault: %s", exc)

        threading.Thread(target=_save, daemon=True).start()

    def process_user_text(self, user_text: str, cancel_event: threading.Event) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            return ""

        ctrl_reply = self._handle_control_intent(user_text)
        if ctrl_reply == "__PAUSED_IGNORE__":
            return ""
        if ctrl_reply is not None:
            self._log(f"{C_CYAN}TARDIS >{C_RESET} {ctrl_reply}")
            self._speak_text(ctrl_reply, cancel_event=cancel_event)
            return ctrl_reply

        # Protección de identidad / datos sensibles
        try:
            from core.protected_users_vault import get_protected_denial_response, is_protected_info_query
            if is_protected_info_query(user_text):
                denial = get_protected_denial_response()
                self._log(f"{C_CYAN}TARDIS >{C_RESET} {denial}")
                self._speak_text(denial, cancel_event=cancel_event)
                return denial
        except Exception:
            pass

        # Enrutador del comando soberano "programa ..." (FTL)
        try:
            from core.tardis_voice_program import get_voice_program_router
            vp = get_voice_program_router().handle(
                user_text,
                channel="infinite_voice_local",
                source="micrófono local (chat de voz infinito)",
            )
            if vp:
                reply = str(vp.get("reply") or "").strip()
                if reply:
                    self._log(f"{C_CYAN}TARDIS [FTL] >{C_RESET} {reply}")
                    self.history.append({"role": "user", "content": user_text})
                    self.history.append({"role": "assistant", "content": reply})
                    self.turn_count += 1
                    self._record_turn_async(user_text, reply)
                    self._speak_text(reply, cancel_event=cancel_event)
                    return reply
        except Exception as exc:
            logger.debug("Aviso en voice_program_router: %s", exc)

        # Streaming LLM + síntesis por oración en paralelo
        t0 = time.perf_counter()
        sentence_q: "queue.Queue[Optional[str]]" = queue.Queue()
        first_audio_logged = False

        def tts_producer() -> None:
            nonlocal first_audio_logged
            while True:
                sent = sentence_q.get()
                if sent is None:
                    break
                if cancel_event.is_set():
                    continue
                audio_path = self._synthesize_to_file(sent)
                if audio_path and not cancel_event.is_set():
                    if not first_audio_logged:
                        first_audio_logged = True
                        self._log(f"{C_DIM}   [primer audio en {time.perf_counter() - t0:.2f}s]{C_RESET}")
                    self.player.enqueue(audio_path)

        tts_thread = threading.Thread(target=tts_producer, daemon=True)
        tts_thread.start()

        full_reply = ""
        pending_buf = ""
        sent_idx = 0

        if not self.cfg.daemon:
            sys.stdout.write(f"{C_CYAN}TARDIS >{C_RESET} ")
            sys.stdout.flush()

        for delta in self.stream_llm(user_text, cancel_event=cancel_event):
            if cancel_event.is_set():
                break
            full_reply += delta
            pending_buf += delta
            if not self.cfg.daemon:
                sys.stdout.write(delta)
                sys.stdout.flush()

            while True:
                ready, pending_buf = extract_ready_sentence(pending_buf, is_first=(sent_idx == 0))
                if not ready:
                    break
                sentence_q.put(ready)
                sent_idx += 1

        if not cancel_event.is_set():
            tail = pending_buf.strip()
            if tail:
                sentence_q.put(tail)

        sentence_q.put(None)
        tts_thread.join(timeout=60.0)
        if not self.cfg.daemon:
            sys.stdout.write("\n")
            sys.stdout.flush()

        clean_reply = full_reply.strip()
        if clean_reply:
            self.history.append({"role": "user", "content": user_text})
            self.history.append({"role": "assistant", "content": clean_reply})
            if len(self.history) > self.cfg.max_history_turns * 2:
                self.history = self.history[-(self.cfg.max_history_turns * 2):]
            self.turn_count += 1
            self._record_turn_async(user_text, clean_reply)

        self.player.wait_idle(cancel_event=cancel_event)
        return clean_reply

    def _cancel_active_turn(self) -> None:
        self._cancel_event.set()
        self.player.interrupt()
        t = self._active_turn_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)

    def _dispatch_audio_utterance(self, pcm_bytes: bytes) -> None:
        self._cancel_active_turn()
        self._cancel_event = threading.Event()
        cancel_ev = self._cancel_event

        def _worker() -> None:
            with self._turn_lock:
                text, stt_s = self.transcribe_pcm(pcm_bytes)
                if not text or cancel_ev.is_set():
                    return
                if not self.paused:
                    self._log(f"\n{C_GOLD}Arquitecto ₪ (voz · {stt_s*1000:.0f}ms) >{C_RESET} {text}")
                self.process_user_text(text, cancel_event=cancel_ev)
                if self.running and not self.cfg.daemon and not self.paused:
                    self._log(f"{C_GREEN}🎙️  [ESCUCHA INFINITA ACTIVA · Turno #{self.turn_count}]{C_RESET}")

        t = threading.Thread(target=_worker, daemon=True)
        self._active_turn_thread = t
        t.start()

    def _dispatch_text_turn(self, text: str) -> None:
        self._cancel_active_turn()
        self._cancel_event = threading.Event()
        cancel_ev = self._cancel_event

        def _worker() -> None:
            with self._turn_lock:
                self.process_user_text(text, cancel_event=cancel_ev)

        t = threading.Thread(target=_worker, daemon=True)
        self._active_turn_thread = t
        t.start()

    def _keyboard_loop(self) -> None:
        if self.cfg.daemon or not sys.stdin or not sys.stdin.isatty():
            return
        while self.running:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.25)
                if not ready:
                    continue
                line = sys.stdin.readline()
                if line == "":
                    break
                txt = line.strip()
                if not txt:
                    if self.player.is_playing:
                        self._cancel_active_turn()
                        self._log(f"{C_YELLOW}⏹️  Interrupción manual (Barge-In). Te escucho...{C_RESET}")
                    elif self.paused:
                        self.paused = False
                        self._log(f"{C_GREEN}🎙️  Escucha reactivada.{C_RESET}")
                    continue
                low = txt.lower()
                if low in ("/salir", "/exit", "/quit"):
                    self.running = False
                    break
                if low == "/pausa":
                    self.paused = not self.paused
                    self._log(f"{C_YELLOW}Estado: {'PAUSADO' if self.paused else 'ESCUCHANDO'}{C_RESET}")
                    continue
                if low == "/clear":
                    self.history.clear()
                    self._log(f"{C_DIM}(historial de sesión limpio){C_RESET}")
                    continue
                self._log(f"{C_GOLD}Arquitecto ₪ (texto) >{C_RESET} {txt}")
                self._dispatch_text_turn(txt)
            except Exception:
                break

    def run(self) -> int:
        self.running = True
        self._log(f"{C_CYAN}{C_BOLD}═══════════════════════════════════════════════════════════════{C_RESET}")
        self._log(f"{C_CYAN}{C_BOLD}  🌀 TARDIS · CHAT DE VOZ INFINITO (FULL-DUPLEX MANOS LIBRES) 🌀{C_RESET}")
        self._log(f"{C_CYAN}{C_BOLD}═══════════════════════════════════════════════════════════════{C_RESET}")
        self._log(f"{C_GOLD}• STT Local:{C_RESET}     faster-whisper ({self.cfg.whisper_model}, CPU int8)")
        self._log(f"{C_GOLD}• TTS Streaming:{C_RESET} {self.tts.voice}")
        self._log(f"{C_GOLD}• Barge-In:{C_RESET}      {'ACTIVO' if self.cfg.barge_in else 'SOLO TECLADO'} (Enter = interrumpir, texto = enviar)")
        self._log(f"{C_GOLD}• Memoria:{C_RESET}       OfflineChatVault ({len(self.history)//2} turnos restaurados)")
        self._log(f"{C_DIM}  Precalentando faster-whisper...{C_RESET}")

        try:
            t0 = time.perf_counter()
            self.stt.warmup()
            self._log(f"{C_GREEN}✔ Whisper listo en {time.perf_counter() - t0:.2f}s{C_RESET}")
        except Exception as exc:
            self._log(f"{C_RED}Error inicializando faster-whisper: {exc}{C_RESET}")
            return 1

        if self.cfg.greeting and not self.cfg.no_play:
            self._log(f"{C_CYAN}TARDIS >{C_RESET} {CANONICAL_GREETING}")
            self._speak_text(CANONICAL_GREETING)

        self.mic.start()
        kb_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
        kb_thread.start()

        self._log(f"\n{C_GREEN}🎙️  [ESCUCHA INFINITA ACTIVA]{C_RESET} Habla libremente (sin chasquidos ni botones).\n")

        try:
            while self.running:
                frame = self.mic.read_frame()
                if frame is None:
                    if not self.running:
                        break
                    continue
                res = self.segmenter.process_frame(frame, ai_speaking=self.player.is_playing)
                if res["barge_in"]:
                    self._cancel_active_turn()
                    self._log(f"\n{C_YELLOW}⚡ Barge-In detectado — escuchando al Arquitecto...{C_RESET}")
                if res["utterance"]:
                    self._dispatch_audio_utterance(res["utterance"])
        except KeyboardInterrupt:
            self._log(f"\n{C_YELLOW}Cerrando Chat de Voz Infinito...{C_RESET}")
        finally:
            self.running = False
            self._cancel_active_turn()
            self.mic.stop()
            self.player.shutdown()
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TARDIS · Chat de Voz Infinito Full-Duplex")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="Voz TTS (ej. es-MX-DaliaNeural)")
    ap.add_argument("--whisper-model", default=os.environ.get("TARDIS_VOICE_WHISPER_MODEL", "base"))
    ap.add_argument("--lang", default=os.environ.get("TARDIS_VOICE_LANG", "es"))
    ap.add_argument("--no-barge-in", action="store_true", help="Desactivar interrupción por voz durante TTS")
    ap.add_argument("--barge-in-rms", type=float, default=0.075, help="Umbral RMS para Barge-In por voz")
    ap.add_argument("--no-greeting", action="store_true", help="Omitir saludo inicial al arrancar")
    ap.add_argument("--no-play", action="store_true", help="Solo transcripción y texto sin reproducir bocinas")
    ap.add_argument("--fresh", action="store_true", help="Iniciar sin restaurar turnos previos en contexto RAM")
    ap.add_argument("--daemon", action="store_true", help="Modo demonio sin entrada interactiva de teclado")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [TardisInfiniteVoice] %(message)s",
    )
    args = build_arg_parser().parse_args(argv)
    cfg = InfiniteVoiceConfig(
        voice=args.voice,
        whisper_model=args.whisper_model,
        language=args.lang,
        barge_in=not args.no_barge_in,
        barge_in_rms=args.barge_in_rms,
        greeting=not args.no_greeting,
        no_play=args.no_play,
        fresh=args.fresh,
        daemon=args.daemon,
    )
    chat = InfiniteVoiceChat(cfg)

    def _handle_sig(_signum, _frame):
        chat.running = False

    signal.signal(signal.SIGTERM, _handle_sig)
    return chat.run()


if __name__ == "__main__":
    raise SystemExit(main())
