#!/usr/bin/env python3
"""
core/tardis_voice_channel_c310.py - Canal de Voz Soberano TARDIS sobre TP-Link Tapo C310 (REDACTED_IP)
=========================================================================================================
Canal abierto permanente usando el micr\u00f3fono y la bocina de la c\u00e1mara GOD-EYE (REDACTED_IP).
Siempre en espera, se activa \u00danicamente al escuchar: "TARDIS \u00bfest\u00e1s ah\u00ed?".
Responde por la bocina f\u00edsica de la c\u00e1mara y se mantiene abierto para di\u00e1logo hasta el silencio.

Arquitectura (todo local, nada sale a la nube salvo el n\u00facleo TARDIS en localhost:8757):
  - Captura de micr\u00f3fono v\u00eda `arecord` (ALSA, 16 kHz mono S16_LE) -> sin depender de sounddevice.
  - Detección de actividad (VAD) con numpy sobre RMS.
  - Reconocimiento de voz OFFLINE con Vosk (modelo español small-es-0.42 cacheado).
  - Síntesis y emisión por la bocina de la C310 v\u00eda TapoC310Speaker
    (edge-tts Cortana es-MX-DaliaNeural, MPEG-TS G.711 :8800, caché de TTS).
  - Respuestas: comandos locales instantáneos (identidad canónica, hora) o Núcleo TARDIS
    http://127.0.0.1:8757/api/chat con fallback local si el núcleo no responde.
  - Escribe data/tapo_c310_voice_channel/session_active.json mientras el canal está activo,
    para que el Centinela C310 (tapo_c310_sentinel._voice_channel_is_active) no emita
    avisos disuasorios mientras el Arquitecto conversa.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

from vosk import Model, KaldiRecognizer

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tapo_c310_speaker import TapoC310Speaker  # noqa: E402

# -----------------------------------------------------------------------------
# Rutas y configuración
# -----------------------------------------------------------------------------
CONFIG_PATH = BASE_DIR / "tapo_c310_config.json"
VOICE_DIR = BASE_DIR / "data" / "tapo_c310_voice_channel"
VOICE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FLAG = VOICE_DIR / "session_active.json"
LOG_FILE = VOICE_DIR / "voice_channel.log"
VOSK_MODEL = Path(os.path.expanduser(
    "~/.local/share/tardis-voice/models/vosk-model-small-es-0.42"
))
if not VOSK_MODEL.exists():
    for _cand in (Path("/home/m11/.local/share/tardis-voice/models/vosk-model-small-es-0.42"),
                  Path("/home/timemachine/.local/share/tardis-voice/models/vosk-model-small-es-0.42")):
        if _cand.exists():
            VOSK_MODEL = _cand
            break
TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
TARDIS_TOKEN_FILE = Path(
    os.environ.get("TARDIS_TOKEN_FILE", str(Path.home() / ".config" / "tardis" / "secrets" / "gia_token"))
)

GREETING_CANONICO = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, "
    "mi tarea es ayudarte a explorar las maravillas de la realidad "
    "y todas las dimensiones temporales."
)
GREETING_CORTO = "A la escucha, Arquitecto."
FRASE_DESPERTAR = "tardis ¿estás ahí"
FRASE_CIERRE = "A la orden, Arquitecto. Canal de voz cerrado."

SAMPLE_RATE = 16000
CHUNK_MS = 200
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_MS / 1000) * 2  # 16 bits = 2 bytes por muestra

DEFAULT_CONFIG = {
    "host": "REDACTED_IP",
    "wake_phrase": FRASE_DESPERTAR,
    "followup_sec": 20.0,
    "min_rms": 0.02,
    "vad_silence_sec": 1.6,
    "max_utterance_sec": 12.0,
    "llm_timeout_sec": 25.0,
    "max_reply_chars": 420,
    "max_reply_sentences": 3,
    "voice": "es-MX-DaliaNeural",
    "language": "es",
}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    try:
        base = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.is_file() else {}
        cfg.update({
            "host": str(base.get("host", cfg["host"])),
            "voice": str(base.get("speaker_voice", cfg["voice"])),
            "followup_sec": float(base.get("voice_channel_followup_sec", cfg["followup_sec"])),
            "min_rms": float(base.get("voice_channel_min_rms", cfg["min_rms"])) / 1000.0,
            "max_reply_sentences": int(base.get("voice_channel_max_reply_sentences", cfg["max_reply_sentences"])),
            "max_reply_chars": int(base.get("voice_channel_max_reply_chars", cfg["max_reply_chars"])),
            "llm_timeout_sec": float(base.get("voice_channel_command_timeout_sec", cfg["llm_timeout_sec"])),
        })
    except Exception:
        pass
    return cfg


# -----------------------------------------------------------------------------
# Bandera de canal activo (integración con el Centinela C310)
# -----------------------------------------------------------------------------
def flag_active(active: bool, reason: str = "") -> None:
    payload = {
        "active": bool(active),
        "reason": reason,
        "host": "REDACTED_IP",
        "active_until": (time.time() + 3600) if active else 0.0,
        "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        tmp = SESSION_FLAG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, SESSION_FLAG)
    except Exception as e:
        log(f"[FLAG] no se pudo escribir {SESSION_FLAG}: {e}")


# -----------------------------------------------------------------------------
# Síntesis por bocina de la C310 (un solo speaker + un solo event loop persistente)
# -----------------------------------------------------------------------------
class SpeakerBox:
    """Reutiliza una única TapoC310Speaker sobre un event loop dedicado en segundo plano."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.speaker = TapoC310Speaker(config_path=config_path)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="tardis-c310-speaker-loop")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def say(self, text: str, timeout: float = 60.0) -> dict:
        if not text or not text.strip():
            return {"ok": False, "skipped": True, "reason": "texto vacío"}
        coro = self.speaker.speak(text=text.strip())
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Captura de micrófono vía arecord (ALSA) en segundo plano
# -----------------------------------------------------------------------------
class MicCapture:
    """Lee chunks de PCM S16_LE 16 kHz mono desde `arecord` y los pone en una cola."""

    def __init__(self, device: Optional[str] = None) -> None:
        self.device = device
        self._proc: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=25)
        self._thread: Optional[threading.Thread] = None
        self._stop = False

    def start(self) -> None:
        self._stop = False
        cmd = ["arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw", "-"]
        if self.device:
            cmd = ["arecord", "-D", self.device, "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw", "-"]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        self._thread = threading.Thread(target=self._pump, daemon=True, name="tardis-mic-capture")
        self._thread.start()

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout
        while not self._stop:
            try:
                chunk = self._proc.stdout.read(CHUNK_BYTES)
            except Exception:
                break
            if not chunk:
                break
            try:
                self._queue.put_nowait(chunk)
            except Exception:
                # Cola llena: descartar el más viejo para mantener tiempo real
                try:
                    self._queue.get_nowait()
                except Exception:
                    pass
                try:
                    self._queue.put_nowait(chunk)
                except Exception:
                    pass

    def read(self, timeout: float = 0.5) -> Optional[bytes]:
        try:
            return self._queue.get(timeout=timeout)
        except Exception:
            return None

    def stop(self) -> None:
        self._stop = True
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass


# -----------------------------------------------------------------------------
# Utilidades de voz
# -----------------------------------------------------------------------------
def strip_accents(text: str) -> str:
    import unicodedata, re
    t = "".join(
        c for c in unicodedata.normalize("NFD", text or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9\s]", " ", t.lower())


def is_wake_phrase(text: str, wake: str) -> bool:
    norm = strip_accents(text)
    wake_norm = strip_accents(wake)
    tokens_wake = [t for t in wake_norm.split() if t]
    return bool(tokens_wake) and all(tok in norm for tok in tokens_wake)


def split_sentences(text: str, max_sentences: int) -> list[str]:
    import re
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text) if p.strip()]
    if not parts:
        return []
    if max_sentences > 0:
        parts = parts[:max_sentences]
    return parts


def cap_reply(text: str, max_chars: int, max_sentences: int) -> str:
    parts = split_sentences(text, max_sentences)
    out = " ".join(parts)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "..."
    return out or text[:max_chars]


# -----------------------------------------------------------------------------
# Respuesta: comandos locales instantáneos + Núcleo TARDIS con fallback
# -----------------------------------------------------------------------------
class TardisMind:
    @staticmethod
    def _token() -> str:
        try:
            return TARDIS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return os.environ.get("GIA_TOKEN", "")

    @classmethod
    def local_reply(cls, text: str) -> Optional[str]:
        t = (text or "").strip().lower()
        if not t:
            return None
        if any(k in t for k in ["quién eres", "quien eres", "cuál es tu tarea", "cual es tu tarea",
                                 "tu función", "preséntate", "presentate", "identifícate", "quién es"]):
            return GREETING_CANONICO
        if any(k in t for k in ["qué hora es", "que hora es", "la hora", "qué día es", "que dia es", "fecha de hoy"]):
            import datetime
            now = datetime.datetime.now()
            dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                     "septiembre", "octubre", "noviembre", "diciembre"]
            return f"Son las {now.strftime('%I:%M %p')} del {dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}, aquí en Playa del Carmen."
        if any(k in t for k in ["silencio", "cállate", "callate", "para", "detén", "deten", "mute", "cierra el canal"]):
            return "__CLOSE_CHANNEL__"
        if t in ["hola", "buenos días", "buenas tardes", "buenas noches", "tardis"]:
            return f"A la escucha, Arquitecto. ¿En qué maravilla dimensional trabajamos hoy?"
        return None

    @classmethod
    def llm_reply(cls, text: str, timeout: float) -> str:
        local = cls.local_reply(text)
        if local is not None:
            if local == "__CLOSE_CHANNEL__":
                return "__CLOSE_CHANNEL__"
            return local
        token = cls._token()
        prompt = (
            f"El Arquitecto te habla por el canal de voz de la cámara C310 (GOD-EYE @ REDACTED_IP): \"{text}\". "
            "Responde de forma natural, breve (1 o 2 frases claras para ser escuchadas por bocina), "
            "sin listas, sin markdown, en español de México. Sé directo y útil."
        )
        payload = json.dumps({
            "message": prompt, "client_id": "tardis-voice-c310",
            "stream": False, "num_predict": 160,
        }).encode("utf-8")
        url = f"{TARDIS_CHAT_URL}?key={token}"
        req = urllib.request.Request(url, data=payload,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data.get("reply") or data.get("response") or ""
                if reply.strip():
                    return cap_reply(reply, 420, 3)
        except Exception as e:
            log(f"[LLM] núcleo no respondió: {e}")
        return "Entendido, Arquitecto. Tu consulta está siendo procesada por el núcleo TARDIS. Repítela si lo deseas."


# -----------------------------------------------------------------------------
# Orquestador del canal de voz
# -----------------------------------------------------------------------------
class TardisVoiceChannelC310:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config = _load_config()
        self.cfg = self.config
        self.host = str(self.cfg["host"])
        self.wake = str(self.cfg["wake_phrase"])
        self.followup_sec = float(self.cfg["followup_sec"])
        self.min_rms = float(self.cfg["min_rms"])
        self.vad_silence_sec = float(self.cfg["vad_silence_sec"])
        self.max_utterance_sec = float(self.cfg["max_utterance_sec"])
        self.llm_timeout = float(self.cfg["llm_timeout_sec"])

        log(f"[INIT] Cargando modelo Vosk {VOSK_MODEL}")
        self.model = Model(str(VOSK_MODEL))
        self.rec = KaldiRecognizer(self.model, SAMPLE_RATE)
        self.speaker = SpeakerBox(CONFIG_PATH)
        self.mic = MicCapture()
        self.mind = TardisMind()

        self.running = False
        self.state = "IDLE"  # IDLE | ACTIVE
        self.active_until = 0.0
        self.last_speech_ts = 0.0
        self.utterance_start = 0.0
        self.in_utterance = False
        self._stop_event = threading.Event()
        signal.signal(signal.SIGTERM, self._sigterm)
        signal.signal(signal.SIGINT, self._sigterm)

    def _sigterm(self, *a) -> None:
        self._stop_event.set()

    def _rms(self, chunk: bytes) -> float:
        arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        if arr.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(arr ** 2)))

    def _transcribe_final(self) -> str:
        try:
            res = json.loads(self.rec.FinalResult())
            return (res.get("text") or "").strip()
        except Exception:
            return ""

    def _reset_recognizer(self) -> None:
        self.rec = KaldiRecognizer(self.model, SAMPLE_RATE)
        self.in_utterance = False

    def _speak_via_camera(self, text: str) -> None:
        res = self.speaker.say(text, timeout=60.0)
        if not res.get("ok"):
            log(f"[TTS] error emitiendo en C310 {self.host}: {res.get('error') or res}")

    def _open_channel(self) -> None:
        self.state = "ACTIVE"
        self.active_until = time.time() + self.followup_sec
        self.last_speech_ts = time.time()
        flag_active(True, reason="wake_word")
        log(f"[CANAL] ABIERTO - despertar detectado: '{self.wake}' (cerrado automático en {self.followup_sec}s)")
        self._speak_via_camera(GREETING_CORTO)
        self._reset_recognizer()

    def _close_channel(self) -> None:
        self.state = "IDLE"
        self.active_until = 0.0
        flag_active(False, reason="timeout")
        log("[CANAL] CERRADO - retorno a espera de despertar")
        self._speak_via_camera(FRASE_CIERRE)
        self._reset_recognizer()

    def _handle_turn(self, transcript: str) -> None:
        if not transcript:
            return
        log(f"[USUARIO] {transcript}")
        reply = self.mind.llm_reply(transcript, self.llm_timeout)
        if reply == "__CLOSE_CHANNEL__":
            self._close_channel()
            return
        reply = cap_reply(reply, int(self.cfg["max_reply_chars"]), int(self.cfg["max_reply_sentences"]))
        log(f"[TARDIS] {reply}")
        self._speak_via_camera(reply)
        # Extender ventana de diálogo tras cada respuesta
        self.active_until = time.time() + self.followup_sec
        self.last_speech_ts = time.time()
        self._reset_recognizer()

    def run(self) -> int:
        self.running = True
        self.mic.start()
        log(f"[CANAL] TARDIS voz C310 en espera. Despertar: '{self.wake}'. Host: {self.host}")
        log(f"[CANAL] Modelo Vosk listo. Bocina: {self.host} (edge-tts {self.cfg['voice']})")

        last_vad_log = 0.0
        try:
            while not self._stop_event.is_set():
                now = time.time()
                chunk = self.mic.read(timeout=0.5)
                if chunk is None:
                    # Sin datos de micrófono: si el canal está activo y pasó la ventana, cerrar
                    if self.state == "ACTIVE" and now > self.active_until:
                        self._close_channel()
                    continue

                rms = self._rms(chunk)
                is_speech = rms > self.min_rms

                # Alimentar siempre al reconocedor para detección de despertar y transcripción
                try:
                    if self.rec.AcceptWaveform(chunk):
                        final = json.loads(self.rec.Result())
                        text = (final.get("text") or "").strip()
                        if text:
                            if self.state == "IDLE":
                                if is_wake_phrase(text, self.wake):
                                    self._open_channel()
                                else:
                                    self._reset_recognizer()
                            else:
                                self._handle_turn(text)
                    else:
                        partial = json.loads(self.rec.PartialResult())
                        ptext = (partial.get("partial") or "").strip()
                        if self.state == "IDLE" and ptext and is_wake_phrase(ptext, self.wake):
                            self._open_channel()
                        elif self.state == "ACTIVE":
                            # Seguimiento de actividad de voz para cerrar por silencio
                            if is_speech:
                                self.last_speech_ts = now
                                self.in_utterance = True
                            elif self.in_utterance and (now - self.last_speech_ts) > self.vad_silence_sec:
                                # Fin posible de frase por silencio: forzar transcripción de lo acumulado
                                text = self._transcribe_final()
                                if text:
                                    self._handle_turn(text)
                                else:
                                    self._reset_recognizer()
                                self.in_utterance = False
                            # Cerrar canal por ventana de diálogo agotada
                            if now > self.active_until:
                                self._close_channel()
                except Exception as e:
                    log(f"[VOSK] error: {e}")
                    self._reset_recognizer()

                if now - last_vad_log > 5.0:
                    last_vad_log = now
                    log(f"[VAD] estado={self.state} rms={rms:.3f} umbral={self.min_rms:.3f} "
                        f"cerrado_en={max(0, self.active_until - now):.0f}s")
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.mic.stop()
            self.speaker.stop()
            flag_active(False, reason="shutdown")
            log("[CANAL] Detenido.")
        return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="TARDIS Canal de Voz C310 (despertar por voz)")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--device", type=str, default=None, help="Dispositivo ALSA de entrada (arecord -D)")
    parser.add_argument("--test-wake", action="store_true", help="Simula activación por despertar y sale")
    parser.add_argument("--say", type=str, default=None, help="Prueba directa: decir texto por bocina C310")
    args = parser.parse_args()

    cfg_path = args.config
    if args.say:
        speaker = SpeakerBox(CONFIG_PATH)
        res = speaker.say(args.say)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        speaker.stop()
        return 0 if res.get("ok") else 1

    if args.test_wake:
        ch = TardisVoiceChannelC310(config_path=cfg_path)
        ch._open_channel()
        time.sleep(2.0)
        ch._close_channel()
        return 0

    channel = TardisVoiceChannelC310(config_path=cfg_path)
    if args.device:
        channel.mic = MicCapture(device=args.device)
    return channel.run()


if __name__ == "__main__":
    raise SystemExit(main())
