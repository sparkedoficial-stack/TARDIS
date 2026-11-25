#!/usr/bin/env python3
"""
core/tardis_infinite_voice.py - Chat de Voz Infinito Full-Duplex 100% Local para TARDIS
=======================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS / FTL
Arquitecto: El Arquitecto (₪)

Motor conversacional de voz continuo y dictado inteligente sobre:
  Micrófono PipeWire (`pw-record` 16 kHz PCM mono)
    -> AdaptiveSpeechSegmenter (Silero VAD v6 neural + WebRTC VAD + piso adaptativo + Barge-In anti-eco)
    -> DSP Acústico (HPF 85 Hz + AGC) + SovereignLocalSTT (faster-whisper CUDA/CPU int8 + hotwords)
    -> UtteranceCoalescer (fusión fluida de frases entrecortadas / pausas reflexivas)
    -> VoiceAbstractionEngine (<15 ms: normalización de dictado, intenciones, entidades,
       resolución de anáforas multi-turno, modo dictado continuo, comandos instantáneos)
    -> Enrutador soberano (`programa ...` FTL, bóveda protegida, control por voz)
    -> LocalVoiceLLMRouter (TemporalBrain UDS si tiene slot libre, o carril GPU dedicado :11435)
    -> SovereignLocalTTS (Piper ONNX local 100% offline con caché LRU o híbrido edge-tts async)
    -> GaplessAudioPlayer (`pw-cat` PCM directo sin cortes entre oraciones + Barge-In <20 ms)
    -> Prioridad de Voz Local activa (abre recursos CPU durante la conversación)
    -> Persistencia y recuperación semántica en OfflineChatVault (continuidad infinita)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
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
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

VOICE_LIB = Path.home() / ".local" / "share" / "tardis-voice" / "lib"
if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
    sys.path.insert(0, str(VOICE_LIB))

from core.tardis_voice_engine import (
    DEFAULT_EDGE_VOICE,
    DEFAULT_LOCAL_VOICE,
    DEFAULT_TTS_MODE,
    VOICE_ALIASES as ENGINE_VOICE_ALIASES,
    AdaptiveSpeechSegmenter,
    DictationNormalizer,
    GaplessAudioPlayer,
    LocalVoiceLLMRouter,
    SegmenterConfig,
    SovereignLocalSTT,
    SovereignLocalTTS,
    SyncedSpeechSegment,
    UtteranceCoalescer,
    VoiceAbstraction,
    VoiceAbstractionEngine,
    WordTiming,
    extract_streaming_sentence,
    get_live_dictation_tracker,
    get_sovereign_stt,
    get_sovereign_tts,
    get_voice_llm_router,
    is_whisper_hallucination,
    prepare_text_for_speech,
    resolve_voice_spec,
)
from core.tardis_voice_local import (
    DEFAULT_VOICE,
    LocalSpeechToText,
    TARDIS_CHAT_URL,
    TARDIS_TOKEN_FILE,
    TextToSpeech,
    for_speech,
)

logger = logging.getLogger("TARDIS.InfiniteVoice")

TEMPORAL_BRAIN_SOCK = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

CANONICAL_GREETING = (
    "Un placer, soy TARDIS asistente de inteligencia artificial. "
    "Chat de voz local activo, te escucho."
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

VOICE_ALIASES = dict(ENGINE_VOICE_ALIASES)

C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_GOLD = "\033[38;5;220m"
C_MAGENTA = "\033[95m"


@dataclass
class InfiniteVoiceConfig:
    voice: str = DEFAULT_VOICE
    tts_mode: str = DEFAULT_TTS_MODE  # local | hybrid | edge
    speech_rate: str = "+6%"
    whisper_model: str = os.environ.get("TARDIS_VOICE_WHISPER_MODEL", "auto")
    whisper_device: str = os.environ.get("TARDIS_STT_DEVICE", "auto")
    whisper_threads: int = int(os.environ.get("TARDIS_VOICE_WHISPER_THREADS", "6"))
    language: str = os.environ.get("TARDIS_VOICE_LANG", "es")
    llm_lane: str = os.environ.get("TARDIS_VOICE_LLM_LANE", "auto")  # auto | temporal_brain | fast
    sample_rate: int = 16000
    frame_ms: int = 30
    vad_aggressiveness: int = 2
    silence_hold_ms: int = 740
    min_speech_ms: int = 240
    max_utterance_ms: int = 30000
    pre_roll_ms: int = 360
    barge_in: bool = True
    barge_in_rms: float = 0.068
    barge_in_frames: int = 8
    use_silero: bool = True
    coalesce_incomplete: bool = True
    dictation_mode: bool = False
    live_preview: bool = True
    live_preview_interval_s: float = 0.38
    sync_text_to_audio: bool = True
    enable_voice_priority: bool = True
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
    """Extrae una oración completa lista para TTS con mínima latencia inicial."""
    return extract_streaming_sentence(buffer, is_first=is_first)


def is_hallucination(text: str) -> bool:
    return is_whisper_hallucination(text)


class SpeechSegmenter(AdaptiveSpeechSegmenter):
    """
    Segmentador VAD compatible con la interfaz histórica de `tardis_infinite_voice`
    y potenciado con Silero VAD v6 neural + paciencia adaptativa + Barge-In anti-eco.
    """

    def __init__(self, cfg: InfiniteVoiceConfig):
        seg_cfg = SegmenterConfig(
            sample_rate=cfg.sample_rate,
            frame_ms=cfg.frame_ms,
            vad_aggressiveness=cfg.vad_aggressiveness,
            silence_hold_ms=cfg.silence_hold_ms,
            min_speech_ms=cfg.min_speech_ms,
            max_utterance_ms=cfg.max_utterance_ms,
            pre_roll_ms=cfg.pre_roll_ms,
            barge_in=cfg.barge_in,
            barge_in_rms=cfg.barge_in_rms,
            barge_in_frames=cfg.barge_in_frames,
            use_silero=cfg.use_silero,
            dictation_mode=cfg.dictation_mode,
        )
        super().__init__(seg_cfg)
        self.voice_cfg = cfg

    @property
    def _vad_compat(self):
        return self.vad

    def __setattr__(self, name: str, value: Any) -> None:
        # Compatibilidad con pruebas deterministas que asignan `seg.vad = None`
        if name == "vad" and value is None:
            object.__setattr__(self, "silero", None)
        object.__setattr__(self, name, value)


class PipeWireMicStream:
    """Captura continua 16 kHz s16le mono mediante pw-record / parecord / arecord."""

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
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
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
                time.sleep(0.20)
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


class StreamingAudioPlayer(GaplessAudioPlayer):
    """Alias retrocompatible de `GaplessAudioPlayer` con método `enqueue(Path)`."""

    def enqueue(self, audio_path: Path) -> None:
        self.enqueue_path(audio_path)


class InfiniteVoiceChat:
    """Orquestador del Chat de Voz Infinito 100% local de TARDIS."""

    def __init__(self, cfg: Optional[InfiniteVoiceConfig] = None):
        self.cfg = cfg or InfiniteVoiceConfig()
        self.stt = LocalSpeechToText(
            model_size=self.cfg.whisper_model,
            cpu_threads=self.cfg.whisper_threads,
            device=self.cfg.whisper_device,
        )
        self.tts = TextToSpeech(voice=self.cfg.voice, mode=self.cfg.tts_mode)
        self.sovereign_tts: SovereignLocalTTS = get_sovereign_tts(mode=self.cfg.tts_mode)
        self.abstractor = VoiceAbstractionEngine()
        self.abstractor.dictation_mode = bool(self.cfg.dictation_mode)
        self.coalescer = UtteranceCoalescer(normalizer=self.abstractor.normalizer, max_wait_s=1.9)
        self.llm_router: LocalVoiceLLMRouter = get_voice_llm_router()

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
        self._priority_active = False

        self._turn_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._active_turn_thread: Optional[threading.Thread] = None
        self._dictation_tracker = get_live_dictation_tracker()
        self._preview_lock = threading.Lock()
        self._preview_busy = False
        self._last_preview_ts = 0.0
        self._last_preview_text = ""
        self._preview_shown = False
        self._stdout_lock = threading.Lock()
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

    def _activate_local_voice_priority(self) -> None:
        if not self.cfg.enable_voice_priority or self._priority_active:
            return
        try:
            from core.telegram_call_priority import activate_call_priority
            activate_call_priority(
                source="local_voice_infinite",
                reason="Conversación de voz local fluida TARDIS",
            )
            self._priority_active = True
        except Exception as exc:
            logger.debug("Prioridad de voz local no activada: %s", exc)

    def _touch_local_voice_priority(self) -> None:
        if not self._priority_active:
            return
        try:
            from core.telegram_call_priority import touch_call_priority
            touch_call_priority(source="local_voice_infinite")
        except Exception:
            pass

    def _release_local_voice_priority(self) -> None:
        if not self._priority_active:
            return
        try:
            from core.telegram_call_priority import release_call_priority
            release_call_priority(source="local_voice_infinite")
        except Exception:
            pass
        self._priority_active = False

    def _log(self, msg: str) -> None:
        if self.cfg.daemon:
            logger.info(re.sub(r"\x1b\[[0-9;]*m", "", msg))
        else:
            print(msg, flush=True)

    def transcribe_pcm(self, pcm_bytes: bytes) -> Tuple[str, float]:
        hint = self.abstractor.get_stt_context_hint()
        return self.stt.transcribe_pcm(
            pcm_bytes,
            language=self.cfg.language,
            context_hint=hint,
            dictation_mode=self.abstractor.dictation_mode,
        )

    def _build_messages(self, user_text: str, abstraction: Optional[VoiceAbstraction] = None) -> List[Dict[str, str]]:
        max_sent = abstraction.max_sentences if abstraction else 4
        guidance = abstraction.system_guidance if abstraction else ""
        sys_prompt = (
            "Eres TARDIS, asistente de inteligencia artificial del Arquitecto (₪) "
            "en una CONVERSACIÓN DE VOZ LOCAL en vivo, fluida y manos libres. "
            f"Responde en español de México de forma natural, clara, cálida y conversacional "
            f"(máximo {max_sent} oraciones bien puntuadas para escucharse por bocinas, "
            "sin tablas Markdown, sin listas largas ni bloques de código)."
        )
        if guidance:
            sys_prompt += f"\n[ABSTRACCIÓN DEL TURNO]: {guidance}"

        if self._vault is not None and (abstraction is None or abstraction.intent not in ("greeting",)):
            try:
                ctx = self._vault.get_context_for_prompt(
                    query=(abstraction.resolved_query if abstraction else user_text),
                    k_relevant=3,
                    n_recent=2,
                    is_local=True,
                )
                if ctx:
                    sys_prompt += "\n\n[MEMORIA CONTINUA TARDIS]:\n" + ctx[:1200]
            except Exception:
                pass

        msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
        msgs.extend(self.history[-(self.cfg.max_history_turns * 2):])
        final_user = (abstraction.resolved_query if abstraction and abstraction.resolved_query else user_text)
        msgs.append({"role": "user", "content": final_user})
        return msgs

    def stream_llm(
        self,
        user_text: str,
        cancel_event: threading.Event,
        abstraction: Optional[VoiceAbstraction] = None,
    ) -> Iterator[str]:
        msgs = self._build_messages(user_text, abstraction=abstraction)
        max_tok = abstraction.max_tokens if abstraction else 260
        chosen_lane, token_iter = self.llm_router.stream_reply(
            msgs,
            user_text=user_text,
            client_id=self.cfg.client_id,
            max_tokens=max_tok,
            temperature=0.32,
            lane=self.cfg.llm_lane,
            cancel_event=cancel_event,
        )
        self._last_lane = chosen_lane
        yield from token_iter

    def _clear_live_preview_line(self) -> None:
        if self.cfg.daemon:
            return
        with self._stdout_lock:
            if self._preview_shown:
                sys.stdout.write("\r\033[2K")
                sys.stdout.flush()
                self._preview_shown = False

    def _render_live_preview(self, text: str, rms: float = 0.0) -> None:
        if self.cfg.daemon or not text:
            return
        bars = min(6, max(1, int(rms * 42)))
        meter = "▮" * bars + "▯" * (6 - bars)
        display = text if len(text) <= 96 else ("…" + text[-95:])
        with self._stdout_lock:
            sys.stdout.write(f"\r\033[2K{C_GOLD}🎙️  [{meter}] Registrando ▸{C_RESET} {display}")
            sys.stdout.flush()
            self._preview_shown = True

    def _maybe_schedule_live_preview(self, rms: float) -> None:
        """Transcribe de forma asíncrona y muestra en tiempo real lo que el usuario está dictando."""
        if not self.cfg.live_preview or self.paused or self.player.is_playing:
            return
        now = time.monotonic()
        if (now - self._last_preview_ts) < self.cfg.live_preview_interval_s:
            return
        with self._preview_lock:
            if self._preview_busy:
                return
            pcm, dur_s = self.segmenter.get_current_speech_pcm(max_seconds=10.0)
            if not pcm or dur_s < 0.35:
                return
            self._preview_busy = True
            self._last_preview_ts = now

        hint = self.abstractor.get_stt_context_hint()
        dict_mode = bool(self.abstractor.dictation_mode)

        def _preview_worker() -> None:
            try:
                txt, el = self.stt.transcribe_pcm_partial(
                    pcm,
                    language=self.cfg.language,
                    context_hint=hint,
                    dictation_mode=dict_mode,
                )
                if txt and self.segmenter.in_speech and not self.player.is_playing:
                    if txt != self._last_preview_text:
                        self._last_preview_text = txt
                        self._dictation_tracker.update_partial(
                            txt,
                            source="tardis_talk",
                            rms=rms,
                            stt_ms=int(round(el * 1000)),
                        )
                        self._render_live_preview(txt, rms=rms)
            except Exception as exc:
                logger.debug("Vista previa de dictado omitida: %s", exc)
            finally:
                with self._preview_lock:
                    self._preview_busy = False

        threading.Thread(target=_preview_worker, daemon=True, name="TARDIS-LivePreview").start()

    def _speak_sentence_direct(
        self,
        sentence: str,
        cancel_event: Optional[threading.Event] = None,
        *,
        style_hint: str = "",
        on_start=None,
        on_word=None,
        on_end=None,
    ) -> bool:
        """
        Sintetiza con prosodia expresiva + dicción es-MX y encola audio directamente en RAM.
        Si se proveen callbacks (`on_word`), sincroniza el texto palabra por palabra al sonido real.
        """
        if self.cfg.no_play:
            return False
        disp = (sentence or "").strip()
        clean = prepare_text_for_speech(disp)
        if not clean or (cancel_event and cancel_event.is_set()):
            return False

        try:
            seg = self.sovereign_tts.synthesize_synced_segment(
                disp,
                voice=self.tts.voice,
                rate=self.cfg.speech_rate,
                mode=self.cfg.tts_mode,
                style_hint=style_hint,
            )
            if seg is not None and not (cancel_event and cancel_event.is_set()):
                if on_start or on_word or on_end:
                    self.player.enqueue_synced(seg, on_start=on_start, on_word=on_word, on_end=on_end)
                elif seg.pcm:
                    self.player.enqueue_pcm(seg.pcm, sample_rate=seg.sample_rate)
                elif seg.encoded_bytes:
                    self.player.enqueue_bytes(seg.encoded_bytes, mime=seg.mime)
                return True
        except Exception as exc:
            logger.debug("Síntesis sincronizada falló (%s), usando fallback directo", exc)

        audio_bytes, mime, _sr = self.sovereign_tts.synthesize_bytes(
            clean, voice=self.tts.voice, rate=self.cfg.speech_rate, mode=self.cfg.tts_mode
        )
        if audio_bytes and not (cancel_event and cancel_event.is_set()):
            self.player.enqueue_bytes(audio_bytes, mime=mime)
            return True
        return False

    def _speak_text(
        self,
        text: str,
        cancel_event: Optional[threading.Event] = None,
        *,
        header: Optional[str] = None,
        style_hint: str = "",
    ) -> None:
        clean_disp = (text or "").strip()
        if not clean_disp:
            return
        sync_ui = (
            not self.cfg.no_play
            and self.cfg.sync_text_to_audio
            and not self.cfg.daemon
            and header is not None
        )
        if not sync_ui:
            if header is not None:
                self._log(f"{header} {clean_disp}")
            if not self.cfg.no_play:
                if self._speak_sentence_direct(clean_disp, cancel_event=cancel_event, style_hint=style_hint):
                    self.player.wait_idle(cancel_event=cancel_event)
            return

        started_flag = {"ok": False}

        def _on_start(_seg: SyncedSpeechSegment) -> None:
            started_flag["ok"] = True
            with self._stdout_lock:
                sys.stdout.write(f"{header} ")
                sys.stdout.flush()

        def _on_word(_seg: SyncedSpeechSegment, wt: WordTiming, idx: int) -> None:
            with self._stdout_lock:
                sys.stdout.write((" " if idx > 0 else "") + wt.word)
                sys.stdout.flush()

        def _on_end(_seg: SyncedSpeechSegment, interrupted: bool) -> None:
            with self._stdout_lock:
                if interrupted:
                    sys.stdout.write(f" {C_YELLOW}[⚡ interrumpido]{C_RESET}\n")
                else:
                    sys.stdout.write("\n")
                sys.stdout.flush()

        ok = self._speak_sentence_direct(
            clean_disp,
            cancel_event=cancel_event,
            style_hint=style_hint,
            on_start=_on_start,
            on_word=_on_word,
            on_end=_on_end,
        )
        if ok:
            self.player.wait_idle(cancel_event=cancel_event)
        elif not started_flag["ok"]:
            self._log(f"{header} {clean_disp}")

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
            self.abstractor.active_topic = ""
            return "Memoria de esta sesión reiniciada. Seguimos conversando."

        if low in ("finalizar chat de voz", "cerrar chat de voz", "apagar chat de voz"):
            self.running = False
            return "Cerrando sesión de voz infinita. Hasta pronto, Arquitecto."

        m_voice = re.search(r"cambia(?:r)?(?:\s+la)?\s+voz\s+a\s+([a-záéíóúñ]+)", low)
        if m_voice:
            alias = m_voice.group(1)
            new_voice = VOICE_ALIASES.get(alias)
            if new_voice:
                self.tts.voice = new_voice
                if new_voice.startswith("es_MX-"):
                    self.cfg.tts_mode = "local"
                    self.tts.mode = "local"
                else:
                    self.cfg.tts_mode = "hybrid"
                    self.tts.mode = "hybrid"
                return f"Voz cambiada a {alias}. ¿Cómo me escuchas ahora?"
            return f"No tengo registrada la voz {alias}. Puedo usar Claude, Ald, Dalia, Jorge, Elvira o Jenny."

        return None

    def _apply_abstraction_action(self, action: Optional[Dict[str, Any]]) -> None:
        if not action:
            return
        atype = action.get("type")
        if atype == "dictation_mode":
            enabled = bool(action.get("enabled"))
            self.segmenter.set_dictation_mode(enabled)
            if not enabled and action.get("text"):
                self._log(f"\n{C_MAGENTA}📝 [DICTADO FINAL]:{C_RESET}\n{action['text']}\n")
        elif atype == "dictation_append":
            self._log(f"{C_MAGENTA}📝 [dictado #{action.get('buffer_size')}]:{C_RESET} {action.get('text')}")
        elif atype == "set_tts_mode":
            mode = str(action.get("mode") or "local")
            self.cfg.tts_mode = mode
            self.tts.mode = mode
            self.sovereign_tts.mode = mode
            if mode == "local" and not self.tts.voice.startswith("es_MX-"):
                self.tts.voice = DEFAULT_LOCAL_VOICE
            elif mode == "hybrid" and self.tts.voice.startswith("es_MX-"):
                self.tts.voice = DEFAULT_EDGE_VOICE
        elif atype == "adjust_rate":
            delta = float(action.get("delta") or 0.0)
            m = re.match(r"^([+-]?\d+)%$", self.cfg.speech_rate.strip())
            cur_pct = int(m.group(1)) if m else 6
            new_pct = max(-25, min(35, cur_pct + int(round(delta * 100))))
            self.cfg.speech_rate = f"+{new_pct}%" if new_pct >= 0 else f"{new_pct}%"

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

        self._touch_local_voice_priority()

        # 1. Comandos de control de sesión (pausa, cambio de voz, reinicio, cierre)
        ctrl_reply = self._handle_control_intent(user_text)
        if ctrl_reply == "__PAUSED_IGNORE__":
            return ""
        if ctrl_reply is not None:
            self._speak_text(ctrl_reply, cancel_event=cancel_event, header=f"{C_CYAN}TARDIS >{C_RESET}")
            return ctrl_reply

        # 2. Normalización de dictado + Abstracción semántica (<15 ms)
        abs_res = self.abstractor.abstract(user_text, allow_system_actions=True)
        norm_text = abs_res.normalized_text or user_text
        if abs_res.action:
            self._apply_abstraction_action(abs_res.action)

        if abs_res.instant_reply is not None:
            if abs_res.instant_reply:
                self._speak_text(
                    abs_res.instant_reply,
                    cancel_event=cancel_event,
                    header=f"{C_CYAN}TARDIS [{abs_res.intent} · {abs_res.latency_ms:.1f}ms] >{C_RESET}",
                    style_hint=abs_res.response_style,
                )
            return abs_res.instant_reply

        # 3. Protección de identidad / datos sensibles
        try:
            from core.protected_users_vault import get_protected_denial_response, is_protected_info_query
            if is_protected_info_query(norm_text):
                denial = get_protected_denial_response()
                self._speak_text(denial, cancel_event=cancel_event, header=f"{C_CYAN}TARDIS >{C_RESET}")
                return denial
        except Exception:
            pass

        # 4. Enrutador del comando soberano "programa ..." (FTL)
        try:
            from core.tardis_voice_program import get_voice_program_router
            vp = get_voice_program_router().handle(
                norm_text,
                channel="infinite_voice_local",
                source="micrófono local (chat de voz infinito)",
            )
            if vp:
                reply = str(vp.get("reply") or "").strip()
                if reply:
                    self.history.append({"role": "user", "content": norm_text})
                    self.history.append({"role": "assistant", "content": reply})
                    self.turn_count += 1
                    self.abstractor.record_assistant_reply(reply)
                    self._record_turn_async(norm_text, reply)
                    self._speak_text(reply, cancel_event=cancel_event, header=f"{C_CYAN}TARDIS [FTL] >{C_RESET}")
                    return reply
        except Exception as exc:
            logger.debug("Aviso en voice_program_router: %s", exc)

        # 5. Streaming LLM + síntesis TTS paralela por oración sincronizada texto↔sonido
        t0 = time.perf_counter()
        self._last_lane = self.cfg.llm_lane
        sentence_q: "queue.Queue[Optional[str]]" = queue.Queue()
        sync_ui = (not self.cfg.no_play) and self.cfg.sync_text_to_audio and (not self.cfg.daemon)
        sync_state = {
            "header_printed": False,
            "words_printed": 0,
            "interrupted": False,
            "first_audio_s": 0.0,
        }
        tag_topic = f" ({abs_res.active_topic[:26]})" if abs_res.active_topic else ""

        def _ensure_header() -> None:
            if not sync_state["header_printed"]:
                sync_state["header_printed"] = True
                with self._stdout_lock:
                    sys.stdout.write(f"{C_CYAN}TARDIS{tag_topic} >{C_RESET} ")
                    sys.stdout.flush()

        def tts_producer() -> None:
            seg_num = 0
            while True:
                sent = sentence_q.get()
                if sent is None:
                    break
                if cancel_event.is_set():
                    continue
                cur_seg = seg_num
                seg_num += 1

                if sync_ui:
                    def _on_start(_seg: SyncedSpeechSegment, _idx: int = cur_seg) -> None:
                        if _idx == 0:
                            sync_state["first_audio_s"] = time.perf_counter() - t0
                        _ensure_header()

                    def _on_word(_seg: SyncedSpeechSegment, wt: WordTiming, _widx: int) -> None:
                        with self._stdout_lock:
                            sep = " " if sync_state["words_printed"] > 0 else ""
                            sys.stdout.write(sep + wt.word)
                            sys.stdout.flush()
                            sync_state["words_printed"] += 1

                    def _on_end(_seg: SyncedSpeechSegment, interrupted: bool) -> None:
                        if interrupted:
                            sync_state["interrupted"] = True

                    self._speak_sentence_direct(
                        sent,
                        cancel_event=cancel_event,
                        style_hint=abs_res.response_style,
                        on_start=_on_start,
                        on_word=_on_word,
                        on_end=_on_end,
                    )
                else:
                    ok = self._speak_sentence_direct(
                        sent,
                        cancel_event=cancel_event,
                        style_hint=abs_res.response_style,
                    )
                    if ok and sync_state["first_audio_s"] == 0.0:
                        sync_state["first_audio_s"] = time.perf_counter() - t0

        tts_thread = threading.Thread(target=tts_producer, daemon=True)
        if not self.cfg.no_play:
            tts_thread.start()

        full_reply = ""
        pending_buf = ""
        sent_idx = 0

        if not self.cfg.daemon and not sync_ui:
            _ensure_header()
        elif sync_ui:
            with self._stdout_lock:
                sys.stdout.write(f"{C_DIM}   [pensando y sincronizando voz…]{C_RESET}")
                sys.stdout.flush()

        # Permitir mocks que solo acepten `(user_text, cancel_event)`
        try:
            stream_iter = self.stream_llm(norm_text, cancel_event, abstraction=abs_res)
        except TypeError:
            stream_iter = self.stream_llm(norm_text, cancel_event)

        cleared_thinking = False
        for delta in stream_iter:
            if cancel_event.is_set():
                break
            full_reply += delta
            pending_buf += delta
            if not self.cfg.daemon and not sync_ui:
                with self._stdout_lock:
                    sys.stdout.write(delta)
                    sys.stdout.flush()

            if not self.cfg.no_play:
                while True:
                    ready, pending_buf = extract_ready_sentence(pending_buf, is_first=(sent_idx == 0))
                    if not ready:
                        break
                    if sync_ui and not cleared_thinking:
                        cleared_thinking = True
                        with self._stdout_lock:
                            sys.stdout.write("\r\033[2K")
                            sys.stdout.flush()
                    sentence_q.put(ready)
                    sent_idx += 1

        if not self.cfg.no_play:
            if not cancel_event.is_set():
                tail = pending_buf.strip()
                if tail:
                    if sync_ui and not cleared_thinking:
                        cleared_thinking = True
                        with self._stdout_lock:
                            sys.stdout.write("\r\033[2K")
                            sys.stdout.flush()
                    sentence_q.put(tail)
            sentence_q.put(None)
            tts_thread.join(timeout=60.0)

        self.player.wait_idle(cancel_event=cancel_event)

        if not self.cfg.daemon:
            with self._stdout_lock:
                if sync_ui and not sync_state["header_printed"] and full_reply.strip():
                    # Si TTS no pudo reproducir audio, mostrar texto completo como respaldo
                    sys.stdout.write(f"\r\033[2K{C_CYAN}TARDIS{tag_topic} >{C_RESET} {full_reply.strip()}")
                elif sync_ui and sync_state["interrupted"]:
                    sys.stdout.write(f" {C_YELLOW}[⚡ interrumpido]{C_RESET}")
                sys.stdout.write("\n")
                if sync_state["first_audio_s"] > 0.0:
                    sys.stdout.write(
                        f"{C_DIM}   [voz sincronizada · 1er audio {sync_state['first_audio_s']:.2f}s · "
                        f"carril={self._last_lane} · intent={abs_res.intent}]{C_RESET}\n"
                    )
                sys.stdout.flush()

        clean_reply = full_reply.strip()
        if clean_reply:
            self.history.append({"role": "user", "content": norm_text})
            self.history.append({"role": "assistant", "content": clean_reply})
            if len(self.history) > self.cfg.max_history_turns * 2:
                self.history = self.history[-(self.cfg.max_history_turns * 2):]
            self.turn_count += 1
            self.abstractor.record_assistant_reply(clean_reply)
            self._record_turn_async(norm_text, clean_reply)

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
                self._clear_live_preview_line()
                self._last_preview_text = ""
                if not text or cancel_ev.is_set():
                    self._dictation_tracker.clear_active()
                    return
                self._dictation_tracker.commit_final(
                    text, source="tardis_talk", stt_ms=int(round(stt_s * 1000))
                )
                # Coalescencia inteligente si el usuario dejó una frase inconclusa
                if self.cfg.coalesce_incomplete and not self.abstractor.dictation_mode and not self.paused:
                    merged, waiting = self.coalescer.push(text)
                    if waiting:
                        self._log(f"{C_DIM}   [esperando continuación: «{text}»…]{C_RESET}")
                        return
                    text = merged or text
                if not self.paused:
                    self._log(f"\n{C_GOLD}Arquitecto ₪ (voz · {stt_s*1000:.0f}ms) >{C_RESET} {text}")
                self.process_user_text(text, cancel_event=cancel_ev)
                if self.running and not self.cfg.daemon and not self.paused:
                    mode_lbl = "DICTADO ACTIVO" if self.abstractor.dictation_mode else "ESCUCHA LOCAL ACTIVA"
                    self._log(f"{C_GREEN}🎙️  [{mode_lbl} · Turno #{self.turn_count}]{C_RESET}")

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
                    self.abstractor.active_topic = ""
                    self._log(f"{C_DIM}(historial de sesión limpio){C_RESET}")
                    continue
                if low in ("/dictado", "/dictate"):
                    self.abstractor.dictation_mode = not self.abstractor.dictation_mode
                    self.segmenter.set_dictation_mode(self.abstractor.dictation_mode)
                    self._log(
                        f"{C_MAGENTA}Modo dictado: {'ACTIVO' if self.abstractor.dictation_mode else 'DESACTIVADO'}{C_RESET}"
                    )
                    continue
                if low.startswith("/tts "):
                    new_m = low.split(maxsplit=1)[1].strip()
                    if new_m in ("local", "hybrid", "edge"):
                        self.cfg.tts_mode = new_m
                        self.tts.mode = new_m
                        self.sovereign_tts.mode = new_m
                        self._log(f"{C_GREEN}✓ Motor TTS: {new_m}{C_RESET}")
                    continue
                self._log(f"{C_GOLD}Arquitecto ₪ (texto) >{C_RESET} {txt}")
                self._dispatch_text_turn(txt)
            except Exception:
                break

    def run(self) -> int:
        self.running = True
        self._activate_local_voice_priority()
        self._log(f"{C_CYAN}{C_BOLD}═══════════════════════════════════════════════════════════════{C_RESET}")
        self._log(f"{C_CYAN}{C_BOLD}  🌀 TARDIS · VOZ LOCAL FLUIDA FULL-DUPLEX + DICTADO v2 🌀{C_RESET}")
        self._log(f"{C_CYAN}{C_BOLD}═══════════════════════════════════════════════════════════════{C_RESET}")
        self._log(f"{C_GOLD}• VAD Neural:{C_RESET}    {'Silero VAD v6 (ONNX)' if self.segmenter.silero else 'WebRTC VAD + RMS'}")
        self._log(f"{C_GOLD}• TTS Motor:{C_RESET}     {self.cfg.tts_mode} ({self.tts.voice})")
        self._log(f"{C_GOLD}• Barge-In:{C_RESET}      {'ACTIVO' if self.cfg.barge_in else 'SOLO TECLADO'} (Enter=interrumpir · /dictado · /tts local|hybrid · /salir)")
        self._log(f"{C_GOLD}• Memoria:{C_RESET}       OfflineChatVault ({len(self.history)//2} turnos restaurados)")
        self._log(f"{C_DIM}  Precalentando STT local + Piper ONNX...{C_RESET}")

        try:
            t0 = time.perf_counter()
            self.stt.warmup()
            eng = self.stt._get_engine()
            tts_t = self.sovereign_tts.warmup(voice=self.tts.voice) if not self.cfg.no_play else 0.0
            self._log(
                f"{C_GREEN}✔ STT listo ({eng.model_size} @ {eng.active_device}/{eng.compute_type}) "
                f"+ TTS listo ({tts_t:.2f}s) en {time.perf_counter() - t0:.2f}s{C_RESET}"
            )
        except Exception as exc:
            self._log(f"{C_RED}Error inicializando motor de voz local: {exc}{C_RESET}")
            self._release_local_voice_priority()
            return 1

        if self.cfg.greeting and not self.cfg.no_play:
            self._speak_text(CANONICAL_GREETING, header=f"{C_CYAN}TARDIS >{C_RESET}", style_hint="expressive")

        self.mic.start()
        kb_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
        kb_thread.start()

        self._log(f"\n{C_GREEN}🎙️  [CONVERSACIÓN LOCAL ACTIVA]{C_RESET} Habla libremente (verás tu dictado en vivo y la respuesta sincronizada con la voz).\n")

        try:
            while self.running:
                frame = self.mic.read_frame()
                if frame is None:
                    if not self.running:
                        break
                    continue

                # Verificar si expiró un fragmento incompleto pendiente en el coalescer
                if self.cfg.coalesce_incomplete and not self.segmenter.in_speech:
                    flushed = self.coalescer.flush_if_expired()
                    if flushed:
                        self._log(f"\n{C_GOLD}Arquitecto ₪ (voz) >{C_RESET} {flushed}")
                        self._dispatch_text_turn(flushed)

                res = self.segmenter.process_frame(frame, ai_speaking=self.player.is_playing)
                if res["barge_in"]:
                    self._cancel_active_turn()
                    self._log(f"\n{C_YELLOW}⚡ Barge-In detectado — escuchando al Arquitecto...{C_RESET}")
                if res["utterance"]:
                    self._dispatch_audio_utterance(res["utterance"])
                elif res.get("in_speech"):
                    self._maybe_schedule_live_preview(float(res.get("rms") or 0.0))
        except KeyboardInterrupt:
            self._log(f"\n{C_YELLOW}Cerrando Chat de Voz Local TARDIS...{C_RESET}")
        finally:
            self.running = False
            self._clear_live_preview_line()
            self._dictation_tracker.clear_active()
            self._cancel_active_turn()
            self.mic.stop()
            self.player.shutdown()
            self._release_local_voice_priority()
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TARDIS · Chat de Voz Local Fluida Full-Duplex + Dictado en Vivo")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="Voz TTS (claude, ald, dalia, jorge, elvira, jenny)")
    ap.add_argument("--tts-mode", choices=["local", "hybrid", "edge"], default=DEFAULT_TTS_MODE, help="Motor TTS: local (Piper 100%% offline), hybrid o edge")
    ap.add_argument("--rate", default="+6%", help="Velocidad de habla (ej. +6%%, +12%%)")
    ap.add_argument("--whisper-model", default=os.environ.get("TARDIS_VOICE_WHISPER_MODEL", "auto"), help="Modelo Whisper (auto, small, base)")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default=os.environ.get("TARDIS_STT_DEVICE", "auto"))
    ap.add_argument("--lane", choices=["auto", "temporal_brain", "fast"], default=os.environ.get("TARDIS_VOICE_LLM_LANE", "auto"))
    ap.add_argument("--lang", default=os.environ.get("TARDIS_VOICE_LANG", "es"))
    ap.add_argument("--silence-ms", type=int, default=740, help="Silencio para cerrar turno en ms")
    ap.add_argument("--dictate", action="store_true", help="Iniciar directamente en modo dictado continuo")
    ap.add_argument("--no-live-preview", action="store_true", help="Desactivar vista previa en vivo mientras dictas")
    ap.add_argument("--no-sync-text", action="store_true", help="Mostrar texto del LLM sin sincronizarlo al audio")
    ap.add_argument("--no-barge-in", action="store_true", help="Desactivar interrupción por voz durante TTS")
    ap.add_argument("--barge-in-rms", type=float, default=0.068, help="Umbral RMS para Barge-In por voz")
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
        tts_mode=args.tts_mode,
        speech_rate=args.rate,
        whisper_model=args.whisper_model,
        whisper_device=args.device,
        llm_lane=args.lane,
        language=args.lang,
        silence_hold_ms=args.silence_ms,
        dictation_mode=args.dictate,
        live_preview=not args.no_live_preview,
        sync_text_to_audio=not args.no_sync_text,
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
