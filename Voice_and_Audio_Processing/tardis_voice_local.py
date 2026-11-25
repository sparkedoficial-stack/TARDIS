#!/usr/bin/env python3
"""
core/tardis_voice_local.py - Conversación de voz local es-MX para TARDIS (v2 Optimizada)
========================================================================================
Orquesta el pipeline 100% local de ultra-baja latencia sobre `core/tardis_voice_engine.py`:

  audio -> DSP (HPF 85Hz + AGC) -> faster-whisper (CUDA int8 / CPU int8 + hotwords)
        -> Normalizador de dictado + Abstracción Semántica (<15 ms)
        -> Enrutador soberano (`programa ...` FTL / comandos instantáneos / LLM multi-carril)
        -> Piper ONNX TTS 100% local en memoria (o híbrido edge-tts async)
        -> Reproducción gapless PipeWire (`pw-cat`/`pw-play`/`ffplay`)

Mantiene compatibilidad completa con las APIs previas (`LocalSpeechToText`,
`TextToSpeech`, `TardisChatClient`, `VoiceConversation`, `for_speech`, `split_sentences`).
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
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tardis_voice_engine import (
    DEFAULT_EDGE_VOICE,
    DEFAULT_LOCAL_VOICE,
    DEFAULT_TTS_MODE,
    MODEL_CACHE,
    SAMPLE_RATE,
    VOICE_LIB,
    VOICE_RUNTIME,
    GaplessAudioPlayer,
    SovereignLocalSTT,
    SovereignLocalTTS,
    VoiceAbstractionEngine,
    get_sovereign_stt,
    get_sovereign_tts,
    get_voice_abstractor,
    prepare_text_for_speech,
)

TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
TARDIS_TOKEN_FILE = Path(
    os.environ.get("TARDIS_TOKEN_FILE", str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"))
)
DEFAULT_VOICE = os.environ.get(
    "TARDIS_TTS_VOICE",
    DEFAULT_LOCAL_VOICE if DEFAULT_TTS_MODE == "local" else DEFAULT_EDGE_VOICE,
)

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
    abstraction: Optional[Dict[str, object]] = None

    def as_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {
            "transcript": self.transcript,
            "reply": self.reply,
            "stt_seconds": round(self.stt_seconds, 3),
            "llm_seconds": round(self.llm_seconds, 3),
            "audio_seconds": round(self.audio_seconds, 3),
            "first_audio_latency": round(self.first_audio_latency, 3),
            "audio_files": self.audio_files,
        }
        if self.abstraction is not None:
            out["abstraction"] = self.abstraction
        return out


class LocalSpeechToText:
    """
    Interfaz de transcripción local de alta precisión respaldada por `SovereignLocalSTT`
    (CUDA int8 automático con failover CPU int8, DSP acústico y normalización de dictado).
    """

    def __init__(self, model_size: str = "auto", cpu_threads: int = 6, device: str = "auto"):
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.device = device
        self._engine: Optional[SovereignLocalSTT] = None

    def _get_engine(self) -> SovereignLocalSTT:
        if self._engine is None:
            if self.model_size == "auto" and self.device == "auto":
                self._engine = get_sovereign_stt()
            else:
                self._engine = SovereignLocalSTT(
                    model_size=self.model_size,
                    device=self.device,
                    cpu_threads=self.cpu_threads,
                )
        return self._engine

    def _load(self):
        return self._get_engine()._load()

    def warmup(self) -> float:
        return self._get_engine().warmup()

    def _decode(self, audio_path: Path, sr: int = SAMPLE_RATE) -> bytes:
        raw = Path(audio_path).read_bytes()
        return self._get_engine().decode_to_pcm16k(raw, suffix=Path(audio_path).suffix or ".wav")

    def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        language: str = "es",
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        return self._get_engine().transcribe_pcm(
            pcm_bytes,
            language=language,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )

    def transcribe_pcm_partial(
        self,
        pcm_bytes: bytes,
        language: str = "es",
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        res = self._get_engine().transcribe_pcm_partial(
            pcm_bytes,
            language=language,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )
        return res.text, res.elapsed_s

    def transcribe(
        self,
        audio_path: str | Path,
        language: str = "es",
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        res = self._get_engine().transcribe_file(
            audio_path,
            language=language,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )
        return res.text, res.elapsed_s

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        suffix: str = ".wav",
        language: str = "es",
        context_hint: str = "",
        dictation_mode: bool = False,
    ) -> Tuple[str, float]:
        return self._get_engine().transcribe_audio_bytes(
            audio_bytes,
            audio_format=suffix.lstrip(".") or "wav",
            language=language,
            context_hint=context_hint,
            dictation_mode=dictation_mode,
        )


class TextToSpeech:
    """
    Sintetizador TTS de baja latencia respaldado por `SovereignLocalTTS`
    (Piper ONNX local 100% offline por defecto, o híbrido con `edge-tts` async en memoria).
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        out_dir: Optional[Path] = None,
        mode: Optional[str] = None,
    ):
        self.voice = voice
        self.mode = (mode or DEFAULT_TTS_MODE).strip().lower()
        self.out_dir = out_dir or Path(tempfile.gettempdir()) / "tardis_voice_out"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0
        self._tts = get_sovereign_tts(mode=self.mode)

    def _target(self, ext: str = ".wav") -> Path:
        self._counter += 1
        return self.out_dir / f"resp_{int(time.time() * 1000)}_{self._counter}{ext}"

    def synthesize_bytes(self, text: str, rate: str = "+8%") -> Tuple[Optional[bytes], str]:
        data, mime, _sr = self._tts.synthesize_bytes(
            text, voice=self.voice, rate=rate, mode=self.mode
        )
        return data, mime

    def synthesize(self, text: str, rate: str = "+8%") -> Optional[Path]:
        text = (text or "").strip()
        if not text:
            return None
        data, mime, _sr = self._tts.synthesize_bytes(
            text, voice=self.voice, rate=rate, mode=self.mode
        )
        if not data:
            return None
        ext = ".wav" if "wav" in mime else ".mp3"
        target = self._target(ext=ext)
        target.write_bytes(data)
        return target

    def speak(self, audio_file: Path, play: bool = True) -> None:
        if not play or not audio_file or not Path(audio_file).exists():
            return
        p = Path(audio_file)
        if p.suffix.lower() == ".wav" and shutil.which("pw-play"):
            cmd = ["pw-play", str(p)]
        elif shutil.which("ffplay"):
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(p)]
        elif shutil.which("mpv"):
            cmd = ["mpv", "--no-video", "--really-quiet", str(p)]
        elif shutil.which("pw-play"):
            cmd = ["pw-play", str(p)]
        else:
            return
        subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def for_speech(text: str) -> str:
    """Convierte Markdown/símbolos técnicos en prosa hablada natural."""
    return prepare_text_for_speech(text)


def split_sentences(text: str, first_chunk_min: int = _MIN_FIRST_CHUNK) -> List[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    if not parts:
        return []
    if len(parts[0]) < first_chunk_min and len(parts) > 1:
        parts[1] = f"{parts[0]} {parts[1]}"
        parts.pop(0)
    return parts


class TardisChatClient:
    def __init__(
        self,
        url: str = TARDIS_CHAT_URL,
        token_file: Path = TARDIS_TOKEN_FILE,
        client_id: str = "voice_local",
    ):
        self.url = url
        self.token_file = token_file
        self.client_id = client_id

    def _token(self) -> str:
        try:
            return self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return os.environ.get("GIA_TOKEN", "")

    def ask(self, message: str, timeout: float = 180.0) -> Tuple[str, float]:
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
    """Enlaza STT local + Abstracción Semántica (<15ms) + LLM de TARDIS + TTS solapado."""

    def __init__(
        self,
        stt: Optional[LocalSpeechToText] = None,
        tts: Optional[TextToSpeech] = None,
        chat: Optional[TardisChatClient] = None,
        abstractor: Optional[VoiceAbstractionEngine] = None,
        max_sentences: Optional[int] = None,
    ):
        self.stt = stt or LocalSpeechToText()
        self.tts = tts or TextToSpeech()
        self.chat = chat or TardisChatClient()
        self.abstractor = abstractor or get_voice_abstractor()
        self.max_sentences = (
            int(max_sentences)
            if max_sentences is not None
            else int(os.environ.get("TARDIS_VOICE_MAX_SENTENCES", "8"))
        )

    def handle_audio(self, audio_path: str | Path, play: bool = True) -> VoiceTurn:
        turn = VoiceTurn(transcript="", reply="")
        hint = self.abstractor.get_stt_context_hint()
        turn.transcript, turn.stt_seconds = self.stt.transcribe(audio_path, context_hint=hint)
        if not turn.transcript:
            return turn
        return self.handle_text(turn.transcript, play=play, turn=turn)

    def handle_text(self, text: str, play: bool = True, turn: Optional[VoiceTurn] = None) -> VoiceTurn:
        turn = turn or VoiceTurn(transcript=text, reply="")

        # 1. Normalización y abstracción semántica local (<15ms)
        abs_res = self.abstractor.abstract(text)
        turn.transcript = abs_res.normalized_text or text
        turn.abstraction = abs_res.to_dict()

        # 2. Comando soberano «programa» (FTL)
        voice_program = None
        try:
            from core.tardis_voice_program import get_voice_program_router
            voice_program = get_voice_program_router().handle(
                turn.transcript,
                channel="local_voice_conversation",
                source="micrófono local (VoiceConversation)",
            )
        except Exception:
            voice_program = None

        if voice_program:
            turn.reply = str(voice_program.get("reply") or "").strip()
            turn.llm_seconds = 0.0
        elif abs_res.instant_reply is not None:
            turn.reply = abs_res.instant_reply
            turn.llm_seconds = 0.0
        else:
            query_for_llm = abs_res.resolved_query or turn.transcript
            turn.reply, turn.llm_seconds = self.chat.ask(query_for_llm)

        if not turn.reply:
            return turn

        self.abstractor.record_assistant_reply(turn.reply)

        start = time.perf_counter()
        spoken = split_sentences(for_speech(turn.reply))
        if self.max_sentences > 0:
            spoken = spoken[: self.max_sentences]

        if not spoken:
            return turn

        # Síntesis solapada con reproducción en cola (reduce latencia percibida entre frases)
        player = GaplessAudioPlayer(enabled=play) if play else None
        try:
            for sentence in spoken:
                try:
                    audio_file = self.tts.synthesize(sentence)
                except Exception:
                    continue
                if not audio_file:
                    continue
                if not turn.audio_files:
                    turn.first_audio_latency = time.perf_counter() - start
                turn.audio_files.append(str(audio_file))
                if player is not None:
                    # Encolar sin borrar el archivo retornado en turn.audio_files
                    data = audio_file.read_bytes()
                    mime = "audio/wav" if audio_file.suffix.lower() == ".wav" else "audio/mpeg"
                    player.enqueue_bytes(data, mime=mime)
            if player is not None:
                player.wait_idle()
        finally:
            if player is not None:
                player.shutdown()

        turn.audio_seconds = time.perf_counter() - start
        return turn


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Conversación de voz local es-MX para TARDIS")
    parser.add_argument("audio", nargs="?", help="Archivo de audio a transcribir y responder")
    parser.add_argument("--text", help="Saltar el STT y usar este texto")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--tts-mode", choices=["local", "hybrid", "edge"], default=DEFAULT_TTS_MODE)
    parser.add_argument(
        "--max-sentences",
        type=int,
        default=None,
        help="Frases máximo sintetizadas por turno (voz corta; 0 = todas)",
    )
    parser.add_argument("--no-play", action="store_true", help="Generar audio sin reproducirlo")
    parser.add_argument("--warmup", action="store_true", help="Precargar STT + TTS local y salir")
    parser.add_argument("--infinite", action="store_true", help="Iniciar chat de voz infinito full-duplex")
    args, unknown = parser.parse_known_args(argv)

    if args.infinite:
        from core.tardis_infinite_voice import main as infinite_main

        inf_args = ["--voice", args.voice, "--tts-mode", args.tts_mode]
        if args.no_play:
            inf_args.append("--no-play")
        inf_args.extend(unknown)
        return infinite_main(inf_args)
    if unknown:
        parser.error(f"argumentos no reconocidos: {' '.join(unknown)}")

    conversation = VoiceConversation(
        tts=TextToSpeech(voice=args.voice, mode=args.tts_mode),
        max_sentences=args.max_sentences,
    )
    if args.warmup:
        started = time.perf_counter()
        stt_s = conversation.stt.warmup()
        tts_s = get_sovereign_tts(mode=args.tts_mode).warmup(voice=args.voice)
        print(json.dumps({
            "warmup_seconds": round(time.perf_counter() - started, 3),
            "stt_seconds": round(stt_s, 3),
            "tts_seconds": round(tts_s, 3),
            "stt_device": conversation.stt._get_engine().active_device,
            "stt_model": conversation.stt._get_engine().model_size,
            "tts_mode": args.tts_mode,
        }, ensure_ascii=False))
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
