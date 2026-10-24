#!/usr/bin/env python3
"""
core/tardis_voice_local.py - Conversación de voz local es-MX para TARDIS
=======================================================================
Sustituye el STT en la nube (recognize_google) por Whisper local y encadena
la respuesta del LLM de TARDIS con edge-tts en frases, para que el audio
empiece a sonar antes de que el modelo termine de responder.

  audio -> ffmpeg (16 kHz mono) -> faster-whisper (local) -> /api/chat -> edge-tts (por frase)

No requiere GPU: faster-whisper corre en CPU con int8.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

VOICE_RUNTIME = Path.home() / ".local" / "share" / "tardis-voice"
VOICE_LIB = VOICE_RUNTIME / "lib"
MODEL_CACHE = VOICE_RUNTIME / "models"

TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
TARDIS_TOKEN_FILE = Path(
    os.environ.get("TARDIS_TOKEN_FILE", str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"))
)
DEFAULT_VOICE = os.environ.get("TARDIS_TTS_VOICE", "es-MX-DaliaNeural")
SAMPLE_RATE = 16000

# Frase terminada: produce el primer audio antes de que el LLM acabe.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
_MIN_FIRST_CHUNK = 12


@dataclass
class VoiceTurn:
    transcript: str
    reply: str
    stt_seconds: float = 0.0
    llm_seconds: float = 0.0
    audio_seconds: float = 0.0
    first_audio_latency: float = 0.0
    audio_files: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "transcript": self.transcript,
            "reply": self.reply,
            "stt_seconds": round(self.stt_seconds, 3),
            "llm_seconds": round(self.llm_seconds, 3),
            "audio_seconds": round(self.audio_seconds, 3),
            "first_audio_latency": round(self.first_audio_latency, 3),
            "audio_files": self.audio_files,
        }


class LocalSpeechToText:
    """Whisper local (faster-whisper) en CPU; decodifica con ffmpeg para no depender de PyAV."""

    def __init__(self, model_size: str = "base", cpu_threads: int = 6):
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            if str(VOICE_LIB) not in sys.path:
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
            return self._model

    def warmup(self) -> None:
        self._load()

    def _decode(self, audio_path: Path, sr: int) -> bytes:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg no está disponible; no se puede decodificar el audio")
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(audio_path),
             "-ar", str(sr), "-ac", "1", "-f", "s16le", "-"],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode(errors='ignore')[:200]}")
        return proc.stdout

    def transcribe(self, audio_path: str | Path, language: str = "es") -> tuple[str, float]:
        import numpy as np

        path = Path(audio_path)
        pcm = np.frombuffer(self._decode(path, SAMPLE_RATE), dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return "", 0.0

        model = self._load()
        started = time.perf_counter()
        segments, _info = model.transcribe(
            pcm,
            language=language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, time.perf_counter() - started

    def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".wav", language: str = "es") -> tuple[str, float]:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)
        try:
            return self.transcribe(tmp_path, language=language)
        finally:
            tmp_path.unlink(missing_ok=True)


class TextToSpeech:
    def __init__(self, voice: str = DEFAULT_VOICE, out_dir: Optional[Path] = None):
        self.voice = voice
        self.out_dir = out_dir or Path(tempfile.gettempdir()) / "tardis_voice_out"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def _target(self) -> Path:
        self._counter += 1
        return self.out_dir / f"resp_{int(time.time() * 1000)}_{self._counter}.mp3"

    def synthesize(self, text: str, rate: str = "+8%") -> Optional[Path]:
        text = text.strip()
        if not text:
            return None
        if not shutil.which("edge-tts"):
            raise RuntimeError("edge-tts no está instalado")
        target = self._target()
        proc = subprocess.run(
            ["edge-tts", "--voice", self.voice, "--rate", rate, "--text", text,
             "--write-media", str(target)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 or not target.exists():
            raise RuntimeError(f"edge-tts falló: {proc.stderr.strip()[:200]}")
        return target

    def speak(self, audio_file: Path, play: bool = True) -> None:
        if play and shutil.which("ffplay"):
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_file)],
                stdin=subprocess.DEVNULL,
            )


def split_sentences(text: str, first_chunk_min: int = _MIN_FIRST_CHUNK) -> List[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    if not parts:
        return []
    if len(parts[0]) < first_chunk_min and len(parts) > 1:
        parts[1] = f"{parts[0]} {parts[1]}"
        parts.pop(0)
    return parts


class TardisChatClient:
    def __init__(self, url: str = TARDIS_CHAT_URL, token_file: Path = TARDIS_TOKEN_FILE, client_id: str = "voice_local"):
        self.url = url
        self.token_file = token_file
        self.client_id = client_id

    def _token(self) -> str:
        try:
            return self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return os.environ.get("GIA_TOKEN", "")

    def ask(self, message: str, timeout: float = 180.0) -> tuple[str, float]:
        payload = json.dumps({"message": message, "client_id": self.client_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}?key={self._token()}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"TARDIS respondió HTTP {exc.code}") from exc
        elapsed = time.perf_counter() - started
        reply = data.get("response") or data.get("reply") or data.get("message") or ""
        if not reply and data.get("system_feedback"):
            reply = data["system_feedback"]
        return str(reply).strip(), elapsed


class VoiceConversation:
    """Enlaza STT local, el LLM de TARDIS y TTS en frases con reproducción solapada."""

    def __init__(self, stt: Optional[LocalSpeechToText] = None, tts: Optional[TextToSpeech] = None,
                 chat: Optional[TardisChatClient] = None):
        self.stt = stt or LocalSpeechToText()
        self.tts = tts or TextToSpeech()
        self.chat = chat or TardisChatClient()

    def handle_audio(self, audio_path: str | Path, play: bool = True) -> VoiceTurn:
        turn = VoiceTurn(transcript="", reply="")
        turn.transcript, turn.stt_seconds = self.stt.transcribe(audio_path)
        if not turn.transcript:
            return turn
        return self.handle_text(turn.transcript, play=play, turn=turn)

    def handle_text(self, text: str, play: bool = True, turn: Optional[VoiceTurn] = None) -> VoiceTurn:
        turn = turn or VoiceTurn(transcript=text, reply="")
        turn.reply, turn.llm_seconds = self.chat.ask(text)
        if not turn.reply:
            return turn

        start = time.perf_counter()
        sentence_queue: "queue.Queue[Optional[str]]" = queue.Queue()

        def producer():
            try:
                for sentence in split_sentences(turn.reply):
                    sentence_queue.put(sentence)
            finally:
                sentence_queue.put(None)

        threading.Thread(target=producer, daemon=True).start()

        while True:
            sentence = sentence_queue.get()
            if sentence is None:
                break
            try:
                audio_file = self.tts.synthesize(sentence)
            except Exception:
                continue
            if not audio_file:
                continue
            if not turn.audio_files:
                turn.first_audio_latency = time.perf_counter() - start
            turn.audio_files.append(str(audio_file))
            first = len(turn.audio_files) == 1
            if play:
                # La primera frase se reproduce ya; el resto se encola al terminar cada una.
                self.tts.speak(audio_file)
            elif first:
                turn.first_audio_latency = time.perf_counter() - start

        turn.audio_seconds = time.perf_counter() - start
        return turn


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Conversación de voz local es-MX para TARDIS")
    parser.add_argument("audio", nargs="?", help="Archivo de audio a transcribir y responder")
    parser.add_argument("--text", help="Saltar el STT y usar este texto")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--no-play", action="store_true", help="Generar audio sin reproducirlo")
    parser.add_argument("--warmup", action="store_true", help="Precargar el modelo y salir")
    args = parser.parse_args(argv)

    conversation = VoiceConversation(tts=TextToSpeech(voice=args.voice))
    if args.warmup:
        started = time.perf_counter()
        conversation.stt.warmup()
        print(json.dumps({"warmup_seconds": round(time.perf_counter() - started, 3)}))
        return 0
    if args.text:
        turn = conversation.handle_text(args.text, play=not args.no_play)
    elif args.audio:
        turn = conversation.handle_audio(args.audio, play=not args.no_play)
    else:
        parser.print_help()
        return 2
    print(json.dumps(turn.as_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
