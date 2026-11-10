#!/usr/bin/env python3
"""
core/telegram_live_call_server.py - Servidor de Llamadas de Voz en Vivo para Telegram
=====================================================================================
Habilita llamadas de voz bidireccionales en tiempo real (manos libres / full-duplex)
directamente dentro de Telegram mediante Mini App nativa (Telegram WebApp + WebSocket):

  Micrófono (Telegram Mini App) -> VAD inteligente + Opus/MP4/WAV -> WebSocket (/tg-call/ws)
  -> ffmpeg 16kHz PCM en memoria -> faster-whisper local (CPU int8)
  -> TemporalBrain streaming (/tmp/temporal_brain.sock) -> edge-tts por oración -> Audio en vivo

Características principales:
  1. Autenticación criptográfica doble: validación oficial HMAC-SHA256 de Telegram
     `WebApp.initData` + tokens firmados (`ct`) para apertura directa desde `/llamar`.
  2. Latencia ultrabaja (~1.2 - 1.6 s al primer audio) mediante segmentación por oraciones
     en paralelo con la generación del modelo.
  3. Soporte de interrupción en caliente (Barge-In), silencio de micrófono (Mute),
     modo Manos Libres (VAD) o Pulsar para Hablar (PTT), y cambio de voz en vivo.
  4. Sincronización automática del botón `📞 Llamar` en Telegram (`setChatMenuButton`)
     cada vez que se actualiza el túnel HTTPS de Cloudflare (`FTL_PUBLIC_URL.txt`).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode

import aiohttp
from aiohttp import WSMsgType, web
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

VOICE_LIB = Path.home() / ".local" / "share" / "tardis-voice" / "lib"
if VOICE_LIB.exists() and str(VOICE_LIB) not in sys.path:
    sys.path.insert(0, str(VOICE_LIB))

from core.protected_users_vault import (
    ARCHITECT_TELEGRAM_ID,
    get_protected_denial_response,
    is_architect,
    is_protected_info_query,
)
from core.tardis_voice_local import LocalSpeechToText, for_speech

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TelegramLiveCall] %(message)s",
)
logger = logging.getLogger("TelegramLiveCall")

CONFIG_FILE = BASE_DIR / "telegram_config.json"
FTL_PUBLIC_URL_FILE = BASE_DIR / "FTL_PUBLIC_URL.txt"
LIVE_CALL_URL_FILE = BASE_DIR / "TELEGRAM_LIVE_CALL_URL.txt"
CALLS_LOG_FILE = BASE_DIR / "data" / "telephony" / "telegram_calls_history.json"
TEMPORAL_BRAIN_SOCK = Path(os.environ.get("TEMPORAL_BRAIN_SOCKET", "/tmp/temporal_brain.sock"))
TARDIS_CHAT_URL = os.environ.get("TARDIS_CHAT_URL", "http://127.0.0.1:8757/api/chat")
GIA_TOKEN_FILE = Path.home() / ".config" / "tardis" / "secrets" / "gia_token"

DEFAULT_PORT = int(os.environ.get("TARDIS_TG_CALL_PORT", "8796"))
DEFAULT_HOST = os.environ.get("TARDIS_TG_CALL_HOST", "127.0.0.1")
DEFAULT_VOICE = "es-MX-DaliaNeural"
SENTINEL_HUB_URL = os.environ.get("TARDIS_C310_HUB_URL", "http://127.0.0.1:8797").rstrip("/")
LIVE_CAM_URL_FILE = BASE_DIR / "TELEGRAM_LIVE_CAM_URL.txt"

AVAILABLE_VOICES = [
    {"id": "es-MX-DaliaNeural", "label": "Cortana · Dalia (es-MX)"},
    {"id": "es-MX-JorgeNeural", "label": "Jorge Neural (es-MX)"},
    {"id": "es-ES-ElviraNeural", "label": "Elvira Neural (es-ES)"},
    {"id": "en-US-JennyNeural", "label": "Cortana · Jenny (en-US)"},
]

# Alucinaciones típicas de Whisper ante silencio o ruido de fondo
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
}

_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?(?:</think>|\Z)", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…:;])\s+|\n+")


# ==============================================================================
# UTILIDADES DE CONFIGURACIÓN, CRIPTOGRAFÍA Y ENLACES
# ==============================================================================


def load_telegram_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Error leyendo {CONFIG_FILE}: {exc}")
    return {}


def get_bot_token() -> str:
    env_tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env_tok:
        return env_tok
    return str(load_telegram_config().get("bot_token", "")).strip()


def get_gia_token() -> str:
    try:
        if GIA_TOKEN_FILE.exists():
            return GIA_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return os.environ.get("GIA_TOKEN", "")


def _hmac_secret() -> bytes:
    tok = get_bot_token() or get_gia_token() or "tardis-sovereign-call-secret"
    return hashlib.sha256(f"tardis-tg-call::{tok}".encode("utf-8")).digest()


def sign_call_token(
    chat_id: int | str = "menu",
    user_name: str = "",
    ttl_sec: int = 0,
) -> str:
    """
    Genera un token URL-safe firmado con HMAC-SHA256 para abrir `/tg-call`.
    Si `ttl_sec == 0`, el token no caduca (útil para el botón persistente de menú).
    """
    payload: Dict[str, Any] = {"c": str(chat_id)}
    if user_name:
        payload["n"] = str(user_name)[:48]
    if ttl_sec > 0:
        payload["exp"] = int(time.time()) + int(ttl_sec)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_hmac_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{b64}.{sig}"


def verify_call_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token or "." not in token:
        return None
    b64, sig = token.rsplit(".", 1)
    expected = hmac.new(_hmac_secret(), b64.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    pad = "=" * (-len(b64) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(b64 + pad).decode("utf-8"))
    except Exception:
        return None
    exp = data.get("exp")
    if exp and time.time() > float(exp):
        return None
    return data


def verify_telegram_init_data(init_data: str, bot_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Valida `Telegram.WebApp.initData` según la especificación oficial de Telegram."""
    if not init_data:
        return None
    tok = (bot_token or get_bot_token()).strip()
    if not tok:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", tok.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, received_hash):
            return None
        user_raw = pairs.get("user")
        user_obj = json.loads(user_raw) if user_raw else {}
        return {
            "user": user_obj,
            "chat_instance": pairs.get("chat_instance"),
            "auth_date": int(pairs.get("auth_date", "0") or 0),
        }
    except Exception as exc:
        logger.warning(f"Error verificando initData de Telegram: {exc}")
        return None


def is_caller_authorized(chat_id: Any) -> bool:
    cfg = load_telegram_config()
    if cfg.get("allow_public_chat", True):
        return True
    if str(chat_id) == str(ARCHITECT_TELEGRAM_ID):
        return True
    allowed = {str(x) for x in cfg.get("allowed_chats", [])}
    return str(chat_id) in allowed


def get_public_tunnel_base() -> str:
    """Obtiene la URL HTTPS viva del túnel público Cloudflare hacia `:7690`."""
    env_url = os.environ.get("TARDIS_PUBLIC_CALL_BASE", "").strip().rstrip("/")
    if env_url.startswith("https://"):
        return env_url
    if FTL_PUBLIC_URL_FILE.exists():
        try:
            u = FTL_PUBLIC_URL_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip().rstrip("/")
            if u.startswith("https://"):
                return u
        except Exception:
            pass
    gw_cfg = Path.home() / ".config" / "ftl" / "public_gateway.json"
    if gw_cfg.exists():
        try:
            u = str(json.loads(gw_cfg.read_text(encoding="utf-8")).get("public_url", "")).strip().rstrip("/")
            if u.startswith("https://"):
                return u
        except Exception:
            pass
    return ""


def build_live_call_url(chat_id: int | str = "menu", user_name: str = "") -> str:
    """Construye el enlace HTTPS autenticado hacia la sala de llamada en vivo de Telegram."""
    base = get_public_tunnel_base()
    if not base:
        return ""
    ct = sign_call_token(chat_id=chat_id, user_name=user_name)
    return f"{base}/tg-call?{urlencode({'ct': ct})}"


def build_live_camera_url(chat_id: int | str = "menu", user_name: str = "") -> str:
    """Construye el enlace HTTPS autenticado hacia el Monitor de Video en Vivo de la Cámara C310 en Telegram."""
    base = get_public_tunnel_base()
    if not base:
        return ""
    ct = sign_call_token(chat_id=chat_id, user_name=user_name)
    return f"{base}/tg-cam?{urlencode({'ct': ct})}"


# ==============================================================================
# PROCESAMIENTO DE VOZ EN TIEMPO REAL (STT + STREAMING LLM + STREAMING TTS)
# ==============================================================================


class RealtimeVoiceEngine:
    def __init__(self):
        self.stt = LocalSpeechToText(
            model_size=os.environ.get("TARDIS_CALL_WHISPER_MODEL", "base"),
            cpu_threads=int(os.environ.get("TARDIS_CALL_WHISPER_THREADS", "6")),
        )
        self.stt_ready = False
        self._stt_sem = asyncio.Semaphore(2)

    async def warmup(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            t0 = time.perf_counter()
            await loop.run_in_executor(None, self.stt.warmup)
            self.stt_ready = True
            logger.info(f"⚡ Modelo STT faster-whisper ({self.stt.model_size}) precalentado en {time.perf_counter() - t0:.2f}s")
        except Exception as exc:
            logger.error(f"No se pudo precalentar faster-whisper: {exc}")

    def _transcribe_bytes_sync(self, audio_bytes: bytes, language: str = "es") -> Tuple[str, float]:
        import numpy as np

        if not audio_bytes or len(audio_bytes) < 400:
            return "", 0.0
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg no disponible")

        t0 = time.perf_counter()
        shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path("/tmp")
        tmp_audio = shm_dir / f"tardis_tgcall_{os.getpid()}_{time.time_ns()}.bin"
        try:
            tmp_audio.write_bytes(audio_bytes)
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-i",
                    str(tmp_audio),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-f",
                    "s16le",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=15,
            )
        finally:
            tmp_audio.unlink(missing_ok=True)
        if proc.returncode != 0 or not proc.stdout:
            return "", 0.0

        pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        # Ignorar fragmentos menores a ~0.28s o con energía casi nula
        if pcm.size < 4500:
            return "", 0.0
        rms = float(np.sqrt(np.mean(pcm * pcm)))
        if rms < 0.0025:
            return "", 0.0

        model = self.stt._load()
        segments, _ = model.transcribe(
            pcm,
            language=language,
            beam_size=1,
            best_of=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 200},
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.perf_counter() - t0

        norm = re.sub(r"\s+", " ", text.lower()).strip()
        if not norm or norm in WHISPER_HALLUCINATIONS or len(norm) < 2:
            return "", elapsed
        return text, elapsed

    async def transcribe(self, audio_bytes: bytes, language: str = "es") -> Tuple[str, float]:
        async with self._stt_sem:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._transcribe_bytes_sync, audio_bytes, language)

    async def synthesize_mp3(self, text: str, voice: str = DEFAULT_VOICE) -> bytes:
        clean = for_speech(text)
        if not clean:
            return b""
        try:
            import edge_tts

            comm = edge_tts.Communicate(clean, voice or DEFAULT_VOICE, rate="+6%", pitch="+2Hz")
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    buf.write(chunk["data"])
            data = buf.getvalue()
            if data:
                return data
        except Exception as exc:
            logger.warning(f"edge_tts async falló, usando respaldo voice.py: {exc}")

        loop = asyncio.get_running_loop()
        import voice as _voice_mod

        res = await loop.run_in_executor(None, _voice_mod.synthesize_to_bytes, clean, voice)
        return res or b""


def _extract_ready_sentence(buffer: str, is_first: bool) -> Tuple[Optional[str], str]:
    """Extrae una oración completa lista para TTS manteniendo baja latencia en el primer fragmento."""
    min_len = 24 if is_first else 45
    if len(buffer) < min_len:
        return None, buffer

    match = _SENTENCE_SPLIT_RE.search(buffer)
    if match and match.start() >= min_len:
        sentence = buffer[: match.start() + 1].strip()
        rest = buffer[match.end() :]
        return sentence, rest

    # Si una oración es muy larga sin punto, cortar en coma tras ~85 caracteres
    if len(buffer) >= 90:
        comma_idx = buffer.find(", ", 55)
        if comma_idx != -1:
            sentence = buffer[: comma_idx + 1].strip()
            rest = buffer[comma_idx + 2 :]
            return sentence, rest

    return None, buffer


async def stream_llm_for_call(
    messages: List[Dict[str, str]],
    user_text: str,
    is_admin_caller: bool,
    client_id: str,
):
    """
    Generador asíncrono de fragmentos de texto de TARDIS optimizado para llamada en vivo.
    Intenta primero el socket UNIX de baja latencia `/tmp/temporal_brain.sock` y cae
    en `/api/chat` si fuera necesario.
    """
    if is_protected_info_query(user_text):
        yield get_protected_denial_response()
        return

    if TEMPORAL_BRAIN_SOCK.exists():
        try:
            transport = httpx.AsyncHTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost", timeout=45.0) as client:
                payload = {
                    "messages": messages,
                    "stream": True,
                    "max_tokens": 380,
                    "temperature": 0.38,
                }
                async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
                    if resp.status_code == 200:
                        in_think = False
                        emitted_any = False
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            raw_data = line[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                obj = json.loads(raw_data)
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
                                emitted_any = True
                                yield delta
                        if emitted_any:
                            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Fallback desde TemporalBrain socket en llamada: {exc}")

    # Respaldo HTTP local `/api/chat`
    tok = get_gia_token()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{TARDIS_CHAT_URL}?key={tok}",
            json={"message": user_text, "client_id": client_id},
        )
        data = r.json()
        reply = (data.get("response") or data.get("reply") or data.get("message") or "").strip()
        reply = _THINK_BLOCK_RE.sub("", reply).strip()
        if reply:
            yield reply


def record_call_turn(chat_id: str, user_name: str, user_text: str, assistant_text: str) -> None:
    """Registra cada turno de la llamada en OfflineChatVault para memoria continua."""
    try:
        from core.offline_chat_vault import get_offline_chat_vault

        cid = f"tg_call_{chat_id}"
        get_offline_chat_vault().record_turn(
            user_message=f"[Llamada Telegram · {user_name}]: {user_text}",
            assistant_reply=assistant_text,
            session_id=cid,
            client_id=cid,
            model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
            direction="present",
        )
    except Exception as exc:
        logger.debug(f"Aviso guardando turno en OfflineChatVault: {exc}")


def append_call_history_log(entry: Dict[str, Any]) -> None:
    try:
        CALLS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        history: List[Dict[str, Any]] = []
        if CALLS_LOG_FILE.exists():
            try:
                history = json.loads(CALLS_LOG_FILE.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append(entry)
        CALLS_LOG_FILE.write_text(
            json.dumps(history[-250:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"Error guardando historial de llamadas Telegram: {exc}")


async def notify_telegram_call_ended(chat_id: str, duration_sec: float, turns: int) -> None:
    """Envía un resumen breve al chat de Telegram cuando concluye una llamada con diálogo."""
    if not str(chat_id).lstrip("-").isdigit() or turns <= 0:
        return
    tok = get_bot_token()
    if not tok:
        return
    mins = int(duration_sec // 60)
    secs = int(duration_sec % 60)
    dur_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
    call_url = build_live_call_url(chat_id=chat_id)
    is_private = not str(chat_id).startswith("-")

    buttons = []
    if call_url:
        if is_private:
            buttons.append([{"text": "📞 Volver a Llamar", "web_app": {"url": call_url}}])
        else:
            buttons.append([{"text": "📞 Volver a Llamar", "url": call_url}])

    text = (
        "📵 *Llamada con TARDIS finalizada*\n"
        f"• *Duración:* `{dur_str}`\n"
        f"• *Intercambios de voz:* `{turns}`"
    )
    payload: Dict[str, Any] = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "Markdown",
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        async with aiohttp.ClientSession() as sess:
            await sess.post(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=8),
            )
    except Exception as exc:
        logger.debug(f"Aviso notificando fin de llamada a Telegram: {exc}")


# ==============================================================================
# INTERFAZ MINI APP DE LLAMADA EN VIVO (HTML5 + TELEGRAM WEBAPP + WEBAUDIO VAD)
# ==============================================================================


def render_call_webapp_html(initial_ct: str, default_voice: str = DEFAULT_VOICE) -> str:
    voices_options = "\n".join(
        f'<option value="{v["id"]}" {"selected" if v["id"] == default_voice else ""}>{v["label"]}</option>'
        for v in AVAILABLE_VOICES
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>TARDIS · Llamada en Vivo</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {{
    color-scheme: dark;
    --bg0: #04070f;
    --bg1: #0b1628;
    --cyan: #00f0ff;
    --emerald: #00e699;
    --amber: #ffb020;
    --red: #ff3b5c;
    --text: #eef6ff;
    --muted: #8aa0bc;
  }}
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  html, body {{
    margin: 0; padding: 0; height: 100%; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif;
    background: radial-gradient(circle at 50% 22%, #13294b 0%, var(--bg1) 42%, var(--bg0) 100%);
    color: var(--text);
    user-select: none;
  }}
  .call-shell {{
    display: flex; flex-direction: column; justify-content: space-between;
    height: 100%; max-width: 520px; margin: 0 auto;
    padding: max(16px, env(safe-area-inset-top)) 18px max(20px, env(safe-area-inset-bottom));
  }}
  .top-bar {{
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
  }}
  .badge {{
    display: inline-flex; align-items: center; gap: 7px;
    padding: 6px 12px; border-radius: 999px;
    background: rgba(0, 240, 255, 0.1); border: 1px solid rgba(0, 240, 255, 0.28);
    font-size: 0.76rem; font-weight: 600; letter-spacing: 0.04em; color: var(--cyan);
  }}
  .dot {{
    width: 8px; height: 8px; border-radius: 50%; background: var(--emerald);
    box-shadow: 0 0 10px var(--emerald);
  }}
  .timer {{
    font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.95rem; color: var(--muted); font-weight: 600;
  }}
  .voice-select {{
    background: rgba(15, 25, 42, 0.85); color: var(--text);
    border: 1px solid rgba(138, 160, 188, 0.28); border-radius: 10px;
    padding: 5px 8px; font-size: 0.74rem; outline: none; max-width: 170px;
  }}
  .center-stage {{
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; flex: 1; min-height: 0; gap: 14px;
  }}
  .caller-title {{
    margin: 0; font-size: 1.5rem; font-weight: 800; letter-spacing: 0.06em;
    background: linear-gradient(135deg, #ffffff, #8be9ff);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }}
  .state-label {{
    font-size: 0.9rem; color: var(--cyan); font-weight: 600; min-height: 1.3em;
    transition: color 0.2s ease;
  }}
  .orb-wrap {{
    position: relative; width: 176px; height: 176px;
    display: grid; place-items: center; margin: 6px 0; cursor: pointer;
  }}
  .orb-ring {{
    position: absolute; inset: 0; border-radius: 50%;
    border: 2px solid rgba(0, 240, 255, 0.35);
    box-shadow: 0 0 40px rgba(0, 240, 255, 0.18), inset 0 0 30px rgba(0, 240, 255, 0.12);
    transition: transform 0.08s linear, border-color 0.2s ease, box-shadow 0.2s ease;
  }}
  .orb-core {{
    width: 126px; height: 126px; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, #48f5ff 0%, #0077b6 52%, #061a38 100%);
    box-shadow: 0 0 45px rgba(0, 240, 255, 0.42);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    font-size: 2.1rem; transition: transform 0.1s ease, background 0.25s ease;
  }}
  .orb-hint {{
    font-size: 0.65rem; letter-spacing: 0.05em; text-transform: uppercase;
    color: rgba(255,255,255,0.88); margin-top: 4px; font-weight: 700;
  }}
  body[data-state="user_speaking"] .orb-ring {{
    border-color: var(--emerald);
    box-shadow: 0 0 55px rgba(0, 230, 153, 0.45), inset 0 0 35px rgba(0, 230, 153, 0.25);
  }}
  body[data-state="user_speaking"] .state-label {{ color: var(--emerald); }}
  body[data-state="thinking"] .orb-ring {{
    border-color: var(--amber);
    animation: spinPulse 1.3s infinite ease-in-out;
  }}
  body[data-state="thinking"] .state-label {{ color: var(--amber); }}
  body[data-state="ai_speaking"] .orb-ring {{
    border-color: #a855f7;
    box-shadow: 0 0 60px rgba(168, 85, 247, 0.5), inset 0 0 35px rgba(0, 240, 255, 0.28);
  }}
  @keyframes spinPulse {{
    0%, 100% {{ transform: scale(1.0); opacity: 0.85; }}
    50% {{ transform: scale(1.1); opacity: 1; }}
  }}
  .transcript-box {{
    width: 100%; max-height: 150px; min-height: 82px; overflow-y: auto;
    padding: 12px 14px; border-radius: 16px; text-align: left;
    background: rgba(8, 15, 28, 0.76); border: 1px solid rgba(138, 160, 188, 0.18);
    backdrop-filter: blur(10px); font-size: 0.86rem; line-height: 1.45;
    user-select: text;
  }}
  .turn-you {{ color: #7ef7c4; margin-bottom: 6px; }}
  .turn-ai {{ color: #e8f3ff; }}
  .quick-row {{
    display: flex; gap: 8px; width: 100%; margin-top: 6px;
  }}
  .quick-input {{
    flex: 1; padding: 10px 13px; border-radius: 12px;
    border: 1px solid rgba(138, 160, 188, 0.25); background: rgba(8, 15, 28, 0.85);
    color: var(--text); font-size: 0.86rem; outline: none;
  }}
  .quick-send {{
    padding: 0 14px; border-radius: 12px; border: 0;
    background: rgba(0, 240, 255, 0.18); color: var(--cyan);
    font-weight: 700; cursor: pointer;
  }}
  .controls {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; padding-top: 10px;
  }}
  .ctrl-btn {{
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 5px; padding: 12px 6px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.12);
    background: rgba(16, 28, 48, 0.82); color: var(--text); cursor: pointer;
    font-size: 0.72rem; font-weight: 600; transition: transform 0.1s ease, background 0.2s;
  }}
  .ctrl-btn:active {{ transform: scale(0.95); }}
  .ctrl-btn .ico {{ font-size: 1.35rem; }}
  .ctrl-btn.active {{
    background: rgba(0, 240, 255, 0.2); border-color: var(--cyan); color: var(--cyan);
  }}
  .ctrl-btn.muted {{
    background: rgba(255, 176, 32, 0.22); border-color: var(--amber); color: var(--amber);
  }}
  .ctrl-btn.hangup {{
    background: linear-gradient(135deg, #ff3b5c, #d91b42);
    border-color: rgba(255, 90, 115, 0.6); color: #fff;
    box-shadow: 0 6px 22px rgba(255, 59, 92, 0.38);
  }}
  .start-overlay {{
    position: fixed; inset: 0; z-index: 20;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 18px; padding: 28px; text-align: center;
    background: radial-gradient(circle at 50% 30%, rgba(16, 40, 72, 0.96), rgba(4, 7, 15, 0.99));
  }}
  .start-overlay.hidden {{ display: none; }}
  .answer-btn {{
    padding: 16px 34px; border-radius: 999px; border: 0;
    background: linear-gradient(135deg, #00e699, #00b8d4);
    color: #031512; font-size: 1.08rem; font-weight: 800; letter-spacing: 0.04em;
    box-shadow: 0 0 38px rgba(0, 230, 153, 0.45); cursor: pointer;
  }}
</style>
</head>
<body data-state="idle">
  <div class="start-overlay" id="startOverlay">
    <div style="font-size:3.3rem">📞</div>
    <h2 style="margin:0;font-size:1.45rem;letter-spacing:0.05em">T.A.R.D.I.S · Canal de Voz</h2>
    <p style="margin:0;color:var(--muted);max-width:320px;font-size:0.9rem;line-height:1.5">
      Llamada bidireccional manos libres en tiempo real con detección automática de voz y síntesis neural Cortana.
    </p>
    <button class="answer-btn" id="answerBtn">🎙️ INICIAR LLAMADA EN VIVO</button>
  </div>

  <div class="call-shell">
    <div class="top-bar">
      <div class="badge"><span class="dot" id="connDot"></span><span id="connText">EN LÍNEA</span></div>
      <div class="timer" id="callTimer">00:00</div>
      <select class="voice-select" id="voiceSelect" title="Voz de TARDIS">
        {voices_options}
      </select>
    </div>

    <div class="center-stage">
      <div>
        <h1 class="caller-title">T.A.R.D.I.S</h1>
        <div class="state-label" id="stateLabel">Listo para conectar</div>
      </div>

      <div class="orb-wrap" id="orbBtn" title="Toca para enviar lo dicho o interrumpir">
        <div class="orb-ring" id="orbRing"></div>
        <div class="orb-core" id="orbCore">
          <span id="orbEmoji">🎙️</span>
          <span class="orb-hint" id="orbHint">MANOS LIBRES</span>
        </div>
      </div>

      <div style="width:100%">
        <div class="transcript-box" id="transcriptBox">
          <div class="turn-ai" id="aiCaption">Toca «Iniciar llamada en vivo» para activar micrófono y altavoz.</div>
        </div>
        <form class="quick-row" id="quickForm">
          <input class="quick-input" id="quickInput" type="text" placeholder="O escribe aquí durante la llamada…" autocomplete="off">
          <button class="quick-send" type="submit">Enviar</button>
        </form>
      </div>
    </div>

    <div class="controls">
      <button class="ctrl-btn" id="muteBtn" type="button">
        <span class="ico" id="muteIco">🎙️</span>
        <span id="muteLbl">Mic Activo</span>
      </button>
      <button class="ctrl-btn active" id="vadBtn" type="button">
        <span class="ico">🗣️</span>
        <span id="vadLbl">Auto VAD</span>
      </button>
      <button class="ctrl-btn" id="interruptBtn" type="button">
        <span class="ico">✋</span>
        <span>Interrumpir</span>
      </button>
      <button class="ctrl-btn hangup" id="hangupBtn" type="button">
        <span class="ico">📵</span>
        <span>Colgar</span>
      </button>
    </div>
  </div>

<script>
(() => {{
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {{
    try {{ tg.ready(); tg.expand(); }} catch (_) {{}}
  }}

  const INITIAL_CT = {json.dumps(initial_ct)};
  const urlParams = new URLSearchParams(window.location.search);
  const callToken = urlParams.get("ct") || INITIAL_CT;

  const startOverlay = document.getElementById("startOverlay");
  const answerBtn = document.getElementById("answerBtn");
  const stateLabel = document.getElementById("stateLabel");
  const connText = document.getElementById("connText");
  const connDot = document.getElementById("connDot");
  const callTimer = document.getElementById("callTimer");
  const orbBtn = document.getElementById("orbBtn");
  const orbRing = document.getElementById("orbRing");
  const orbEmoji = document.getElementById("orbEmoji");
  const orbHint = document.getElementById("orbHint");
  const transcriptBox = document.getElementById("transcriptBox");
  const muteBtn = document.getElementById("muteBtn");
  const muteIco = document.getElementById("muteIco");
  const muteLbl = document.getElementById("muteLbl");
  const vadBtn = document.getElementById("vadBtn");
  const vadLbl = document.getElementById("vadLbl");
  const interruptBtn = document.getElementById("interruptBtn");
  const hangupBtn = document.getElementById("hangupBtn");
  const voiceSelect = document.getElementById("voiceSelect");
  const quickForm = document.getElementById("quickForm");
  const quickInput = document.getElementById("quickInput");

  let ws = null;
  let audioCtx = null;
  let micStream = null;
  let analyser = null;
  let mediaRecorder = null;
  let recChunks = [];
  let recMime = "";
  let isMuted = false;
  let autoVad = true;
  let isSpeaking = false;
  let isAiSpeaking = false;
  let isThinking = false;
  let speechStartAt = 0;
  let lastVoiceAt = 0;
  let noiseFloor = 0.012;
  let turnSeq = 0;
  let activeTurnId = 0;
  let callStartedAt = 0;
  let timerInterval = null;
  let vadRaf = null;
  let closedIntentionally = false;

  // Cola de reproducción continua usando elemento Audio desbloqueado (compatible con iOS WKWebView)
  const player = new Audio();
  player.playsInline = true;
  const audioQueue = [];
  let playingChunk = false;
  let currentAiElem = null;

  function haptic(kind = "light") {{
    try {{
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred(kind);
    }} catch (_) {{}}
  }}

  function setState(mode, label) {{
    document.body.dataset.state = mode;
    if (label) stateLabel.textContent = label;
    if (mode === "user_speaking") {{
      orbEmoji.textContent = "🟢";
      orbHint.textContent = "TOCA PARA ENVIAR";
    }} else if (mode === "thinking") {{
      orbEmoji.textContent = "🧠";
      orbHint.textContent = "PROCESANDO";
    }} else if (mode === "ai_speaking") {{
      orbEmoji.textContent = "🔊";
      orbHint.textContent = "TOCA · INTERRUMPIR";
    }} else {{
      orbEmoji.textContent = isMuted ? "🔇" : "🎙️";
      orbHint.textContent = autoVad ? "ESCUCHANDO" : "TOCA PARA HABLAR";
    }}
  }}

  function appendUserLine(text) {{
    const div = document.createElement("div");
    div.className = "turn-you";
    div.textContent = "🗣️ Tú: " + text;
    transcriptBox.appendChild(div);
    currentAiElem = null;
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }}

  function updateAiLine(delta, replace = false) {{
    if (!currentAiElem) {{
      currentAiElem = document.createElement("div");
      currentAiElem.className = "turn-ai";
      currentAiElem.textContent = "🤖 TARDIS: ";
      transcriptBox.appendChild(currentAiElem);
    }}
    if (replace) {{
      currentAiElem.textContent = "🤖 TARDIS: " + delta;
    }} else {{
      currentAiElem.textContent += delta;
    }}
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
  }}

  function stopPlaybackQueue() {{
    while (audioQueue.length) {{
      const u = audioQueue.shift();
      try {{ URL.revokeObjectURL(u); }} catch (_) {{}}
    }}
    try {{
      player.pause();
      player.removeAttribute("src");
    }} catch (_) {{}}
    playingChunk = false;
    isAiSpeaking = false;
    if (!isThinking && !isSpeaking) {{
      setState("idle", isMuted ? "Micrófono en silencio" : "Escuchando en vivo…");
    }}
  }}

  function playNextChunk() {{
    if (playingChunk || audioQueue.length === 0) {{
      if (!playingChunk && audioQueue.length === 0) {{
        isAiSpeaking = false;
        if (!isThinking) {{
          setState("idle", isMuted ? "Micrófono en silencio" : "Escuchando en vivo…");
        }}
      }}
      return;
    }}
    playingChunk = true;
    isAiSpeaking = true;
    setState("ai_speaking", "TARDIS hablando…");
    const blobUrl = audioQueue.shift();
    player.src = blobUrl;
    player.onended = () => {{
      try {{ URL.revokeObjectURL(blobUrl); }} catch (_) {{}}
      playingChunk = false;
      playNextChunk();
    }};
    player.onerror = () => {{
      try {{ URL.revokeObjectURL(blobUrl); }} catch (_) {{}}
      playingChunk = false;
      playNextChunk();
    }};
    player.play().catch(() => {{
      playingChunk = false;
      playNextChunk();
    }});
  }}

  function pickSupportedMime() {{
    if (!window.MediaRecorder) return "";
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4"
    ];
    for (const c of candidates) {{
      try {{
        if (MediaRecorder.isTypeSupported(c)) return c;
      }} catch (_) {{}}
    }}
    return "";
  }}

  function beginUtteranceCapture() {{
    if (!micStream || isMuted || isSpeaking) return;
    recChunks = [];
    try {{
      mediaRecorder = recMime ? new MediaRecorder(micStream, {{ mimeType: recMime }}) : new MediaRecorder(micStream);
    }} catch (e) {{
      mediaRecorder = new MediaRecorder(micStream);
    }}
    mediaRecorder.ondataavailable = (ev) => {{
      if (ev.data && ev.data.size > 0) recChunks.push(ev.data);
    }};
    mediaRecorder.onstop = async () => {{
      const chunks = recChunks;
      recChunks = [];
      if (!chunks.length) return;
      const blob = new Blob(chunks, {{ type: mediaRecorder.mimeType || recMime || "audio/webm" }});
      if (blob.size < 600 || !ws || ws.readyState !== WebSocket.OPEN) return;
      turnSeq += 1;
      activeTurnId = turnSeq;
      isThinking = true;
      setState("thinking", "Transcribiendo y pensando…");
      ws.send(JSON.stringify({{ type: "audio_meta", mime: blob.type, turn_id: activeTurnId }}));
      const buf = await blob.arrayBuffer();
      ws.send(buf);
    }};
    mediaRecorder.start(120);
    isSpeaking = true;
    speechStartAt = performance.now();
    lastVoiceAt = speechStartAt;
    setState("user_speaking", "Te escucho…");
  }}

  function finishUtteranceCapture(discard = false) {{
    if (!isSpeaking) return;
    isSpeaking = false;
    if (!mediaRecorder) return;
    if (discard) {{
      mediaRecorder.ondataavailable = null;
      mediaRecorder.onstop = null;
    }}
    try {{
      if (mediaRecorder.state !== "inactive") mediaRecorder.stop();
    }} catch (_) {{}}
  }}

  function startVadLoop() {{
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const SILENCE_HOLD_MS = 820;
    const MIN_SPEECH_MS = 320;
    const MAX_UTTERANCE_MS = 22000;

    const tick = () => {{
      analyser.getFloatTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      const rms = Math.sqrt(sum / data.length);

      // Animación reactiva del orbe
      const scale = Math.min(1.26, 1 + rms * (isAiSpeaking ? 1.5 : 3.2));
      orbRing.style.transform = `scale(${{scale.toFixed(3)}})`;

      const now = performance.now();
      if (!isSpeaking && !isAiSpeaking && !isMuted) {{
        noiseFloor = noiseFloor * 0.985 + Math.min(rms, 0.04) * 0.015;
      }}
      const threshold = Math.max(0.017, noiseFloor * 2.6);

      if (autoVad && !isMuted && !isAiSpeaking && !isThinking) {{
        if (!isSpeaking) {{
          if (rms > threshold) {{
            beginUtteranceCapture();
          }}
        }} else {{
          if (rms > threshold * 0.82) {{
            lastVoiceAt = now;
          }}
          if ((now - lastVoiceAt > SILENCE_HOLD_MS && now - speechStartAt > MIN_SPEECH_MS) ||
              (now - speechStartAt > MAX_UTTERANCE_MS)) {{
            finishUtteranceCapture(false);
          }}
        }}
      }}
      vadRaf = requestAnimationFrame(tick);
    }};
    vadRaf = requestAnimationFrame(tick);
  }}

  function connectWebSocket() {{
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${{proto}}//${{window.location.host}}/tg-call/ws?ct=${{encodeURIComponent(callToken)}}`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    let expectingAudioMeta = null;

    ws.onopen = () => {{
      connText.textContent = "EN LLAMADA";
      connDot.style.background = "#00e699";
      ws.send(JSON.stringify({{
        type: "hello",
        ct: callToken,
        init_data: (tg && tg.initData) ? tg.initData : "",
        voice: voiceSelect.value
      }}));
    }};

    ws.onmessage = (ev) => {{
      if (typeof ev.data === "string") {{
        let msg = {{}};
        try {{ msg = JSON.parse(ev.data); }} catch (_) {{ return; }}
        if (msg.type === "call_ready") {{
          currentAiElem = null;
          setState("idle", `Conectado con ${{msg.user_name || "TARDIS"}} · Escuchando`);
        }} else if (msg.type === "transcript") {{
          if (msg.text) {{
            appendUserLine(msg.text);
            setState("thinking", "TARDIS respondiendo…");
          }} else {{
            isThinking = false;
            setState("idle", "Escuchando en vivo…");
          }}
        }} else if (msg.type === "assistant_delta") {{
          updateAiLine(msg.text || "", false);
        }} else if (msg.type === "tts_chunk") {{
          expectingAudioMeta = msg;
        }} else if (msg.type === "turn_done") {{
          isThinking = false;
          if (!playingChunk && audioQueue.length === 0) {{
            setState("idle", isMuted ? "Micrófono en silencio" : "Escuchando en vivo…");
          }}
        }} else if (msg.type === "error") {{
          isThinking = false;
          setState("idle", msg.message || "Aviso en canal de voz");
        }}
      }} else if (ev.data instanceof ArrayBuffer) {{
        if (expectingAudioMeta) {{
          expectingAudioMeta = null;
        }}
        const blob = new Blob([ev.data], {{ type: "audio/mpeg" }});
        const url = URL.createObjectURL(blob);
        audioQueue.push(url);
        isThinking = false;
        playNextChunk();
      }}
    }};

    ws.onclose = () => {{
      if (closedIntentionally) return;
      connText.textContent = "RECONECTANDO…";
      connDot.style.background = "#ffb020";
      setTimeout(connectWebSocket, 1800);
    }};
  }}

  async function startCall() {{
    haptic("medium");
    answerBtn.disabled = true;
    answerBtn.textContent = "Conectando micrófono…";

    // Desbloquear reproducción de audio en iOS/Android
    try {{
      player.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
      await player.play().catch(() => {{}});
    }} catch (_) {{}}

    try {{
      micStream = await navigator.mediaDevices.getUserMedia({{
        audio: {{
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1
        }}
      }});
    }} catch (err) {{
      answerBtn.disabled = false;
      answerBtn.textContent = "🎙️ REINTENTAR PERMISO DE MICRÓFONO";
      alert("Permite el acceso al micrófono en Telegram para hablar en vivo con TARDIS: " + err.message);
      return;
    }}

    recMime = pickSupportedMime();
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaStreamSource(micStream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    src.connect(analyser);

    startOverlay.classList.add("hidden");
    transcriptBox.innerHTML = "";
    callStartedAt = Date.now();
    timerInterval = setInterval(() => {{
      const sec = Math.floor((Date.now() - callStartedAt) / 1000);
      const m = String(Math.floor(sec / 60)).padStart(2, "0");
      const s = String(sec % 60).padStart(2, "0");
      callTimer.textContent = `${{m}}:${{s}}`;
    }}, 1000);

    startVadLoop();
    connectWebSocket();
  }}

  function sendInterrupt() {{
    haptic("light");
    stopPlaybackQueue();
    isThinking = false;
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "interrupt" }}));
    }}
    setState("idle", "Escuchando en vivo…");
  }}

  answerBtn.addEventListener("click", startCall);

  orbBtn.addEventListener("click", () => {{
    haptic("light");
    if (isAiSpeaking || isThinking) {{
      sendInterrupt();
      return;
    }}
    if (isSpeaking) {{
      finishUtteranceCapture(false);
    }} else if (!isMuted) {{
      beginUtteranceCapture();
    }}
  }});

  muteBtn.addEventListener("click", () => {{
    haptic("light");
    isMuted = !isMuted;
    if (isMuted) finishUtteranceCapture(true);
    if (micStream) micStream.getAudioTracks().forEach(t => t.enabled = !isMuted);
    muteBtn.classList.toggle("muted", isMuted);
    muteIco.textContent = isMuted ? "🔇" : "🎙️";
    muteLbl.textContent = isMuted ? "Silenciado" : "Mic Activo";
    setState("idle", isMuted ? "Micrófono en silencio" : "Escuchando en vivo…");
  }});

  vadBtn.addEventListener("click", () => {{
    haptic("light");
    autoVad = !autoVad;
    if (!autoVad && isSpeaking) finishUtteranceCapture(false);
    vadBtn.classList.toggle("active", autoVad);
    vadLbl.textContent = autoVad ? "Auto VAD" : "Manual";
    setState("idle", autoVad ? "Escuchando en vivo…" : "Toca el orbe para hablar");
  }});

  interruptBtn.addEventListener("click", sendInterrupt);

  voiceSelect.addEventListener("change", () => {{
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "set_voice", voice: voiceSelect.value }}));
    }}
  }});

  quickForm.addEventListener("submit", (ev) => {{
    ev.preventDefault();
    const txt = quickInput.value.trim();
    if (!txt || !ws || ws.readyState !== WebSocket.OPEN) return;
    quickInput.value = "";
    stopPlaybackQueue();
    appendUserLine(txt);
    turnSeq += 1;
    activeTurnId = turnSeq;
    isThinking = true;
    setState("thinking", "TARDIS respondiendo…");
    ws.send(JSON.stringify({{ type: "text_turn", text: txt, turn_id: activeTurnId }}));
  }});

  hangupBtn.addEventListener("click", () => {{
    haptic("heavy");
    closedIntentionally = true;
    stopPlaybackQueue();
    finishUtteranceCapture(true);
    if (vadRaf) cancelAnimationFrame(vadRaf);
    if (timerInterval) clearInterval(timerInterval);
    const durSec = callStartedAt ? Math.round((Date.now() - callStartedAt) / 1000) : 0;
    try {{
      if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{ type: "hangup", duration_sec: durSec }}));
        ws.close();
      }}
    }} catch (_) {{}}
    try {{
      if (micStream) micStream.getTracks().forEach(t => t.stop());
    }} catch (_) {{}}
    setState("idle", "Llamada finalizada");
    connText.textContent = "FINALIZADA";
    connDot.style.background = "#ff3b5c";
    if (tg) {{
      setTimeout(() => {{ try {{ tg.close(); }} catch (_) {{}} }}, 350);
    }} else {{
      startOverlay.classList.remove("hidden");
      answerBtn.disabled = false;
      answerBtn.textContent = "🎙️ VOLVER A LLAMAR";
    }}
  }});
}})();
</script>
</body>
</html>"""


def render_camera_webapp_html(initial_ct: str = "") -> str:
    """Renderiza la Mini App de Transmisión en Vivo de la Cámara Tapo C310 (GOD-EYE) para Telegram."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>TARDIS · GOD-EYE C310 EN VIVO</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {{
    color-scheme: dark;
    --bg: #050811;
    --card: rgba(12, 18, 32, 0.88);
    --cyan: #00f0ff;
    --green: #00e699;
    --amber: #ffb020;
    --red: #ff3b5c;
    --text: #e6f1ff;
    --muted: #8b9bb4;
  }}
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  body {{
    margin: 0; padding: 10px; min-height: 100vh;
    background: radial-gradient(circle at 50% 0%, #0d1d35 0%, #060912 60%, #03050a 100%);
    color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    display: flex; flex-direction: column; gap: 10px;
  }}
  .top-bar {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; border-radius: 14px;
    background: var(--card); border: 1px solid rgba(0, 240, 255, 0.25);
  }}
  .brand {{
    display: flex; align-items: center; gap: 8px; font-weight: 800; font-size: 0.92rem; letter-spacing: 0.04em;
    color: var(--cyan);
  }}
  .live-pill {{
    display: flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
    background: rgba(255, 59, 92, 0.16); border: 1px solid rgba(255, 59, 92, 0.5);
    font-size: 0.74rem; font-weight: 700; color: #ff6b84;
  }}
  .dot {{
    width: 8px; height: 8px; border-radius: 50%; background: var(--red);
    box-shadow: 0 0 8px var(--red); animation: pulse 1.2s infinite;
  }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}
  .video-card {{
    position: relative; width: 100%; aspect-ratio: 16 / 9; border-radius: 16px; overflow: hidden;
    background: #020408; border: 1px solid rgba(0, 240, 255, 0.35);
    box-shadow: 0 0 35px rgba(0, 240, 255, 0.08);
    display: flex; align-items: center; justify-content: center;
  }}
  #liveImg {{
    width: 100%; height: 100%; object-fit: contain; display: block;
  }}
  .hud-badge {{
    position: absolute; bottom: 8px; left: 10px; right: 10px;
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 10px; border-radius: 10px;
    background: rgba(5, 10, 20, 0.76); backdrop-filter: blur(8px);
    border: 1px solid rgba(0, 240, 255, 0.22); font-size: 0.73rem; font-family: ui-monospace, monospace;
  }}
  .metrics-grid {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
  }}
  .metric-box {{
    padding: 9px 10px; border-radius: 12px; background: var(--card);
    border: 1px solid rgba(255, 255, 255, 0.08); text-align: center;
  }}
  .metric-val {{ font-size: 1.02rem; font-weight: 800; color: var(--cyan); font-family: ui-monospace, monospace; }}
  .metric-lbl {{ font-size: 0.68rem; color: var(--muted); margin-top: 2px; }}
  .controls-grid {{
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;
  }}
  button {{
    padding: 11px 12px; border-radius: 12px; border: 1px solid rgba(0, 240, 255, 0.28);
    background: rgba(14, 24, 42, 0.92); color: var(--text); font-weight: 700; font-size: 0.80rem;
    cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px;
  }}
  button:active {{ transform: scale(0.98); }}
  button.primary {{
    background: linear-gradient(135deg, rgba(0, 240, 255, 0.22), rgba(0, 180, 255, 0.14));
    border-color: var(--cyan); color: #fff;
  }}
  button.warn {{
    background: rgba(255, 59, 92, 0.16); border-color: rgba(255, 59, 92, 0.5); color: #ff8da0;
  }}
  .talk-box {{
    display: flex; gap: 8px; padding: 10px; border-radius: 14px;
    background: var(--card); border: 1px solid rgba(0, 240, 255, 0.22);
  }}
  .talk-box input {{
    flex: 1; padding: 10px 12px; border-radius: 10px; border: 1px solid #22324c;
    background: #070c16; color: var(--text); font-size: 0.84rem; outline: none;
  }}
  .status-line {{
    font-size: 0.76rem; color: var(--muted); text-align: center; padding: 4px;
  }}
</style>
</head>
<body>
  <div class="top-bar">
    <div class="brand">👁️ TARDIS · GOD-EYE C310 (REDACTED_IP)</div>
    <div class="live-pill"><span class="dot" id="liveDot"></span><span id="liveStatus">CONECTANDO</span></div>
  </div>

  <div class="video-card" id="videoCard">
    <img id="liveImg" alt="Transmisión en Vivo GOD-EYE C310" />
    <div class="hud-badge">
      <span id="hudClock">--:--:--</span>
      <span id="hudRes">2304×1296 → 1280×720 HD</span>
      <span id="hudFps">-- FPS</span>
    </div>
  </div>

  <div class="metrics-grid">
    <div class="metric-box">
      <div class="metric-val" id="mPersons">0</div>
      <div class="metric-lbl">INDIVIDUOS (YOLOv8s)</div>
    </div>
    <div class="metric-box">
      <div class="metric-val" id="mLatency">-- ms</div>
      <div class="metric-lbl">INFERENCIA IA</div>
    </div>
    <div class="metric-box">
      <div class="metric-val" id="mSeq">#0</div>
      <div class="metric-lbl">FOTOGRAMA</div>
    </div>
  </div>

  <div class="controls-grid">
    <button class="primary" id="btnSnapChat">📸 Enviar Foto 2K al Chat</button>
    <button class="primary" id="btnClipChat">🎬 Enviar Video 6s al Chat</button>
    <button id="btnToggleHud">🎯 HUD Táctico: ON</button>
    <button id="btnToggleRes">📐 Modo: 720p Fluido</button>
    <button class="warn" id="btnSpeakAlert" style="grid-column: span 2;">🔊 Emitir Aviso Vocal TARDIS por Bocina C310</button>
  </div>

  <form class="talk-box" id="talkForm">
    <input type="text" id="talkInput" placeholder="Hablar por la bocina de la cámara C310…" />
    <button type="submit" class="primary">🗣️ Hablar</button>
  </form>

  <div class="status-line" id="statusMsg">Canal óptico cifrado (:8800 → TARDIS Sentinel → Telegram)</div>

<script>
(() => {{
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {{
    try {{ tg.ready(); tg.expand(); }} catch (_) {{}}
  }}
  const params = new URLSearchParams(window.location.search);
  const callToken = params.get("ct") || {json.dumps(initial_ct)};
  const initData = (tg && tg.initData) ? tg.initData : "";

  const liveImg = document.getElementById("liveImg");
  const liveDot = document.getElementById("liveDot");
  const liveStatus = document.getElementById("liveStatus");
  const hudClock = document.getElementById("hudClock");
  const hudRes = document.getElementById("hudRes");
  const hudFps = document.getElementById("hudFps");
  const mPersons = document.getElementById("mPersons");
  const mLatency = document.getElementById("mLatency");
  const mSeq = document.getElementById("mSeq");
  const statusMsg = document.getElementById("statusMsg");

  const btnSnapChat = document.getElementById("btnSnapChat");
  const btnClipChat = document.getElementById("btnClipChat");
  const btnToggleHud = document.getElementById("btnToggleHud");
  const btnToggleRes = document.getElementById("btnToggleRes");
  const btnSpeakAlert = document.getElementById("btnSpeakAlert");
  const talkForm = document.getElementById("talkForm");
  const talkInput = document.getElementById("talkInput");

  let ws = null;
  let hudEnabled = true;
  let streamWidth = 1280;
  let lastBlobUrl = null;
  let frameCountWindow = 0;
  let lastFpsCalc = performance.now();

  function setStatus(txt) {{
    statusMsg.textContent = txt;
  }}

  function startMjpegFallback() {{
    liveStatus.textContent = "EN VIVO (MJPEG)";
    liveDot.style.background = "#00e699";
    liveImg.src = `/tg-cam/stream.mjpg?ct=${{encodeURIComponent(callToken)}}&hud=${{hudEnabled ? 1 : 0}}&width=${{streamWidth}}&fps=10&t=${{Date.now()}}`;
  }}

  function connectWs() {{
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${{proto}}//${{window.location.host}}/tg-cam/ws?ct=${{encodeURIComponent(callToken)}}&hud=${{hudEnabled ? 1 : 0}}&width=${{streamWidth}}&fps=12`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {{
      liveStatus.textContent = "EN VIVO";
      liveDot.style.background = "#00e699";
      ws.send(JSON.stringify({{ type: "hello", ct: callToken, init_data: initData }}));
    }};

    ws.onmessage = (ev) => {{
      if (typeof ev.data === "string") {{
        try {{
          const msg = JSON.parse(ev.data);
          if (msg.type === "frame_meta") {{
            hudClock.textContent = msg.iso_time || "--:--:--";
            mPersons.textContent = String(msg.persons ?? 0);
            mPersons.style.color = (msg.persons > 0) ? "#ff3b5c" : "#00f0ff";
            mLatency.textContent = `${{msg.inference_ms ?? 0}} ms`;
            mSeq.textContent = `#${{msg.seq ?? 0}}`;
          }} else if (msg.type === "speak_result") {{
            setStatus(msg.ok ? `🔊 Reproducido en C310 (${{msg.audio_duration_sec}}s)` : `⚠️ Error de voz: ${{msg.error}}`);
          }} else if (msg.type === "snapshot_sent") {{
            setStatus(msg.ok ? "✅ Fotografía 2K enviada a tu chat de Telegram." : "⚠️ No se pudo enviar la captura.");
          }} else if (msg.type === "clip_sent") {{
            setStatus(msg.ok ? `✅ Clip en vivo (${{msg.duration}}s) enviado a tu chat de Telegram.` : "⚠️ Error enviando clip.");
          }}
        }} catch (_) {{}}
      }} else if (ev.data instanceof ArrayBuffer) {{
        const blob = new Blob([ev.data], {{ type: "image/jpeg" }});
        const url = URL.createObjectURL(blob);
        liveImg.src = url;
        if (lastBlobUrl) {{
          try {{ URL.revokeObjectURL(lastBlobUrl); }} catch (_) {{}}
        }}
        lastBlobUrl = url;
        frameCountWindow += 1;
        const now = performance.now();
        if (now - lastFpsCalc >= 1000) {{
          const fps = (frameCountWindow * 1000) / (now - lastFpsCalc);
          hudFps.textContent = `${{fps.toFixed(1)}} FPS`;
          frameCountWindow = 0;
          lastFpsCalc = now;
        }}
      }}
    }};

    ws.onerror = () => {{
      startMjpegFallback();
    }};

    ws.onclose = () => {{
      liveStatus.textContent = "RECONECTANDO…";
      liveDot.style.background = "#ffb020";
      setTimeout(connectWs, 2000);
    }};
  }}

  async function postAction(payload) {{
    const resp = await fetch("/tg-cam/action", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ ct: callToken, init_data: initData, ...payload }})
    }});
    return await resp.json();
  }}

  btnToggleHud.addEventListener("click", () => {{
    hudEnabled = !hudEnabled;
    btnToggleHud.textContent = `🎯 HUD Táctico: ${{hudEnabled ? "ON" : "OFF"}}`;
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "set_options", hud: hudEnabled }}));
    }} else {{
      startMjpegFallback();
    }}
  }});

  btnToggleRes.addEventListener("click", () => {{
    streamWidth = (streamWidth === 1280) ? 2304 : 1280;
    btnToggleRes.textContent = (streamWidth === 2304) ? "📐 Modo: 2K QHD Nativo" : "📐 Modo: 720p Fluido";
    hudRes.textContent = (streamWidth === 2304) ? "2304×1296 2K QHD" : "2304×1296 → 1280×720 HD";
    if (ws && ws.readyState === WebSocket.OPEN) {{
      ws.send(JSON.stringify({{ type: "set_options", width: streamWidth }}));
    }} else {{
      startMjpegFallback();
    }}
  }});

  btnSnapChat.addEventListener("click", async () => {{
    btnSnapChat.disabled = true;
    setStatus("📸 Enviando captura 2K QHD al chat de Telegram…");
    try {{
      const r = await postAction({{ action: "send_snapshot" }});
      setStatus(r.ok ? "✅ Fotografía 2K enviada a tu chat de Telegram." : `⚠️ Error: ${{r.error || "Fallo"}}`);
    }} catch (e) {{
      setStatus("⚠️ Error de red enviando captura.");
    }} finally {{
      btnSnapChat.disabled = false;
    }}
  }});

  btnClipChat.addEventListener("click", async () => {{
    btnClipChat.disabled = true;
    setStatus("🎬 Grabando y transmitiendo clip en vivo de 6s al chat de Telegram…");
    try {{
      const r = await postAction({{ action: "send_clip", duration: 6.0 }});
      setStatus(r.ok ? "✅ Video MP4 en vivo enviado a tu chat de Telegram." : `⚠️ Error: ${{r.error || "Fallo"}}`);
    }} catch (e) {{
      setStatus("⚠️ Error grabando clip en vivo.");
    }} finally {{
      btnClipChat.disabled = false;
    }}
  }});

  btnSpeakAlert.addEventListener("click", async () => {{
    btnSpeakAlert.disabled = true;
    setStatus("🔊 Emitiendo aviso vocal TARDIS por el altavoz de la cámara C310…");
    try {{
      const r = await postAction({{ action: "speak", text: "" }});
      setStatus(r.ok ? `🔊 Aviso vocal reproducido (${{r.audio_duration_sec}}s).` : `⚠️ Error: ${{r.error}}`);
    }} catch (e) {{
      setStatus("⚠️ Error contactando altavoz C310.");
    }} finally {{
      btnSpeakAlert.disabled = false;
    }}
  }});

  talkForm.addEventListener("submit", async (ev) => {{
    ev.preventDefault();
    const txt = talkInput.value.trim();
    if (!txt) return;
    talkInput.value = "";
    setStatus(`🗣️ Transmitiendo voz a la cámara C310: "${{txt}}"…`);
    try {{
      const r = await postAction({{ action: "speak", text: txt }});
      setStatus(r.ok ? `🔊 Voz reproducida en C310 (${{r.audio_duration_sec}}s).` : `⚠️ Error: ${{r.error}}`);
    }} catch (e) {{
      setStatus("⚠️ Error transmitiendo voz.");
    }}
  }});

  connectWs();
}})();
</script>
</body>
</html>"""


# ==============================================================================
# SERVIDOR AIOHTTP Y PROTOCOLO WEBSOCKET DE LLAMADA EN VIVO
# ==============================================================================


class TelegramLiveCallServer:
    def __init__(self):
        self.engine = RealtimeVoiceEngine()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.last_synced_tunnel_url: str = ""
        self._watcher_task: Optional[asyncio.Task] = None

    def _authenticate_request(
        self,
        ct: Optional[str],
        init_data: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        tg_verified = verify_telegram_init_data(init_data or "")
        tok_verified = verify_call_token(ct)

        if not tg_verified and not tok_verified:
            return None

        chat_id = "anon"
        user_name = "Usuario"
        verified_by_tg = False

        if tok_verified:
            chat_id = str(tok_verified.get("c") or "anon")
            user_name = str(tok_verified.get("n") or user_name)

        if tg_verified:
            u = tg_verified.get("user") or {}
            if u.get("id"):
                chat_id = str(u["id"])
                verified_by_tg = True
            if u.get("first_name"):
                user_name = str(u["first_name"])

        if str(chat_id) == str(ARCHITECT_TELEGRAM_ID):
            user_name = "Arquitecto"

        if chat_id != "menu" and not is_caller_authorized(chat_id):
            return None

        return {
            "chat_id": chat_id,
            "user_name": user_name,
            "is_admin": is_architect(chat_id) and (verified_by_tg or (tok_verified and str(tok_verified.get("c")) == str(ARCHITECT_TELEGRAM_ID))),
        }

    async def handle_health(self, request: web.Request) -> web.Response:
        pub_url = build_live_call_url(chat_id="menu")
        return web.json_response(
            {
                "ok": True,
                "service": "tardis-telegram-live-call",
                "stt_ready": self.engine.stt_ready,
                "active_calls": len(self.active_sessions),
                "public_call_url": pub_url,
                "temporal_brain_socket": TEMPORAL_BRAIN_SOCK.exists(),
            }
        )

    async def handle_call_page(self, request: web.Request) -> web.Response:
        ct = request.query.get("ct", "")
        # Permitir cargar la página si trae un token firmado válido o si se abre como WebApp de Telegram
        # (la validación estricta ocurre también en el handshake WebSocket con initData).
        if ct and not verify_call_token(ct):
            return web.Response(status=403, text="Enlace de llamada inválido o expirado.")
        cfg = load_telegram_config()
        pref_voice = str(cfg.get("cortana_voice", DEFAULT_VOICE))
        html_doc = render_call_webapp_html(initial_ct=ct, default_voice=pref_voice)
        return web.Response(
            text=html_doc,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)

        query_ct = request.query.get("ct", "")
        session_id = f"call_{int(time.time() * 1000)}_{id(ws) & 0xFFFF:04x}"
        auth_info: Optional[Dict[str, Any]] = verify_call_token(query_ct) and self._authenticate_request(query_ct, "")
        user_name = (auth_info or {}).get("user_name", "Usuario")
        chat_id = (auth_info or {}).get("chat_id", "anon")
        is_admin_caller = bool((auth_info or {}).get("is_admin", False))
        voice_id = str(load_telegram_config().get("cortana_voice", DEFAULT_VOICE))

        history: List[Dict[str, str]] = []
        current_turn_task: Optional[asyncio.Task] = None
        pending_audio_turn_id = 0
        started_ts = time.time()
        turns_completed = 0

        async def cancel_active_turn() -> None:
            nonlocal current_turn_task
            if current_turn_task and not current_turn_task.done():
                current_turn_task.cancel()
                try:
                    await current_turn_task
                except (asyncio.CancelledError, Exception):
                    pass
            current_turn_task = None

        async def send_json(payload: Dict[str, Any]) -> None:
            if not ws.closed:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))

        async def speak_sentences(sentences: List[str], turn_id: int) -> None:
            for seq, s in enumerate(sentences):
                mp3 = await self.engine.synthesize_mp3(s, voice=voice_id)
                if mp3 and not ws.closed:
                    await send_json({"type": "tts_chunk", "turn_id": turn_id, "seq": seq, "text": s})
                    await ws.send_bytes(mp3)

        async def run_turn(user_text: str, turn_id: int) -> None:
            nonlocal turns_completed
            try:
                sys_prompt = (
                    "Eres TARDIS, asistente de inteligencia artificial en una LLAMADA DE VOZ EN VIVO por Telegram "
                    f"con {user_name}. Responde en español de manera conversacional, fluida, clara y concisa "
                    "(idealmente de 1 a 4 oraciones, sin tablas markdown ni bloques de código largos, listo para ser hablado en voz alta)."
                )
                msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
                msgs.extend(history[-10:])
                msgs.append({"role": "user", "content": user_text})

                tts_queue: asyncio.Queue[Optional[Tuple[int, str, asyncio.Task]]] = asyncio.Queue()

                async def tts_sender() -> None:
                    while True:
                        item = await tts_queue.get()
                        if item is None:
                            break
                        seq_idx, sent_txt, synth_task = item
                        mp3_bytes = await synth_task
                        if mp3_bytes and not ws.closed:
                            await send_json(
                                {"type": "tts_chunk", "turn_id": turn_id, "seq": seq_idx, "text": sent_txt}
                            )
                            await ws.send_bytes(mp3_bytes)

                sender_task = asyncio.create_task(tts_sender())
                full_reply = ""
                pending_buf = ""
                seq_counter = 0

                try:
                    async for delta in stream_llm_for_call(
                        messages=msgs,
                        user_text=user_text,
                        is_admin_caller=is_admin_caller,
                        client_id=f"tg_call_{chat_id}",
                    ):
                        full_reply += delta
                        pending_buf += delta
                        await send_json({"type": "assistant_delta", "turn_id": turn_id, "text": delta})

                        while True:
                            ready_sent, pending_buf = _extract_ready_sentence(
                                pending_buf, is_first=(seq_counter == 0)
                            )
                            if not ready_sent:
                                break
                            synth_task = asyncio.create_task(
                                self.engine.synthesize_mp3(ready_sent, voice=voice_id)
                            )
                            await tts_queue.put((seq_counter, ready_sent, synth_task))
                            seq_counter += 1

                    tail = pending_buf.strip()
                    if tail:
                        synth_task = asyncio.create_task(self.engine.synthesize_mp3(tail, voice=voice_id))
                        await tts_queue.put((seq_counter, tail, synth_task))
                finally:
                    await tts_queue.put(None)
                    await sender_task

                clean_reply = full_reply.strip()
                if clean_reply:
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": clean_reply})
                    turns_completed += 1
                    record_call_turn(str(chat_id), user_name, user_text, clean_reply)

                await send_json({"type": "turn_done", "turn_id": turn_id, "full_text": clean_reply})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Error ejecutando turno de llamada: {exc}")
                await send_json({"type": "error", "message": f"Error en turno: {exc}"})

        async def handle_audio_utterance(audio_bytes: bytes, turn_id: int) -> None:
            try:
                transcript, stt_sec = await self.engine.transcribe(audio_bytes, language="es")
                await send_json(
                    {
                        "type": "transcript",
                        "turn_id": turn_id,
                        "text": transcript,
                        "stt_ms": int(stt_sec * 1000),
                    }
                )
                if not transcript:
                    return
                logger.info(f"🎙️ [{user_name} · {chat_id}] ({stt_sec*1000:.0f}ms): {transcript}")
                await run_turn(transcript, turn_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"Error procesando audio de llamada: {exc}")
                await send_json({"type": "error", "message": "No pude procesar ese fragmento de voz."})

        self.active_sessions[session_id] = {"chat_id": chat_id, "started_at": started_ts}
        hangup_reported = False
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    mtype = data.get("type")

                    if mtype == "hello":
                        verified = self._authenticate_request(
                            data.get("ct") or query_ct,
                            data.get("init_data") or "",
                        )
                        if not verified:
                            await send_json({"type": "error", "message": "No autorizado para iniciar llamada."})
                            await ws.close()
                            break
                        chat_id = verified["chat_id"]
                        user_name = verified["user_name"]
                        is_admin_caller = verified["is_admin"]
                        if data.get("voice"):
                            voice_id = str(data["voice"])
                        self.active_sessions[session_id].update({"chat_id": chat_id, "user_name": user_name})

                        greeting = (
                            f"Hola {user_name}, línea de voz conectada. "
                            "Te escucho en vivo, dime qué necesitas."
                        )
                        await send_json(
                            {
                                "type": "call_ready",
                                "chat_id": chat_id,
                                "user_name": user_name,
                                "voice": voice_id,
                            }
                        )
                        await send_json({"type": "assistant_delta", "turn_id": 0, "text": greeting})
                        current_turn_task = asyncio.create_task(speak_sentences([greeting], turn_id=0))

                    elif mtype == "audio_meta":
                        pending_audio_turn_id = int(data.get("turn_id") or (turns_completed + 1))

                    elif mtype == "text_turn":
                        txt = str(data.get("text") or "").strip()
                        tid = int(data.get("turn_id") or (turns_completed + 1))
                        if txt:
                            await cancel_active_turn()
                            current_turn_task = asyncio.create_task(run_turn(txt, tid))

                    elif mtype == "interrupt":
                        await cancel_active_turn()

                    elif mtype == "set_voice":
                        v = str(data.get("voice") or "").strip()
                        if v:
                            voice_id = v

                    elif mtype == "hangup":
                        hangup_reported = True
                        await cancel_active_turn()
                        dur = float(data.get("duration_sec") or (time.time() - started_ts))
                        append_call_history_log(
                            {
                                "timestamp": int(time.time()),
                                "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "chat_id": chat_id,
                                "user_name": user_name,
                                "duration_sec": round(dur, 1),
                                "turns": turns_completed,
                                "channel": "telegram_live_webapp",
                            }
                        )
                        asyncio.create_task(notify_telegram_call_ended(str(chat_id), dur, turns_completed))
                        break

                elif msg.type == WSMsgType.BINARY:
                    if not auth_info and chat_id == "anon":
                        continue
                    await cancel_active_turn()
                    tid = pending_audio_turn_id or (turns_completed + 1)
                    current_turn_task = asyncio.create_task(handle_audio_utterance(bytes(msg.data), tid))

                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            await cancel_active_turn()
            self.active_sessions.pop(session_id, None)
            if not hangup_reported and turns_completed > 0:
                dur = time.time() - started_ts
                append_call_history_log(
                    {
                        "timestamp": int(time.time()),
                        "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "chat_id": chat_id,
                        "user_name": user_name,
                        "duration_sec": round(dur, 1),
                        "turns": turns_completed,
                        "channel": "telegram_live_webapp",
                    }
                )
                asyncio.create_task(notify_telegram_call_ended(str(chat_id), dur, turns_completed))
        return ws

    async def sync_telegram_menu_button(self) -> None:
        """
        Vigila `FTL_PUBLIC_URL.txt` y actualiza automáticamente el botón `📞 Llamar`
        en Telegram (`setChatMenuButton`) cada vez que cambia el túnel Cloudflare.
        """
        while True:
            try:
                base = get_public_tunnel_base()
                tok = get_bot_token()
                if base and tok and base != self.last_synced_tunnel_url:
                    menu_url = build_live_call_url(chat_id="menu")
                    LIVE_CALL_URL_FILE.write_text(menu_url + "\n", encoding="utf-8")
                    cam_url = build_live_camera_url(chat_id=ARCHITECT_TELEGRAM_ID, user_name="Arquitecto")
                    if cam_url:
                        LIVE_CAM_URL_FILE.write_text(cam_url + "\n", encoding="utf-8")
                    async with aiohttp.ClientSession() as sess:
                        resp = await sess.post(
                            f"https://api.telegram.org/bot{tok}/setChatMenuButton",
                            json={
                                "menu_button": {
                                    "type": "web_app",
                                    "text": "📞 Llamar",
                                    "web_app": {"url": menu_url},
                                }
                            },
                            timeout=aiohttp.ClientTimeout(total=10),
                        )
                        res_json = await resp.json()
                        if res_json.get("ok"):
                            self.last_synced_tunnel_url = base
                            logger.info(f"📲 Botón '📞 Llamar' sincronizado en Telegram -> {base}/tg-call")
                        else:
                            logger.warning(f"Aviso setChatMenuButton: {res_json}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Error en watcher de botón Telegram: {exc}")
            await asyncio.sleep(15)

    # --------------------------------------------------------------------------
    # MONITOR DE VIDEO EN VIVO DE LA CÁMARA TAPO C310 PARA TELEGRAM (/tg-cam)
    # --------------------------------------------------------------------------

    async def handle_cam_page(self, request: web.Request) -> web.Response:
        ct = request.query.get("ct", "")
        if ct and not verify_call_token(ct):
            return web.Response(status=403, text="Enlace de cámara en vivo inválido o expirado.")
        html_doc = render_camera_webapp_html(initial_ct=ct)
        return web.Response(
            text=html_doc,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_cam_snapshot(self, request: web.Request) -> web.Response:
        ct = request.query.get("ct", "")
        init_data = request.headers.get("X-Telegram-Init-Data", "") or request.query.get("init_data", "")
        if not self._authenticate_request(ct, init_data):
            return web.Response(status=403, text="No autorizado")
        hud = request.query.get("hud", "1")
        width = request.query.get("width", "1280")
        quality = request.query.get("quality", "85")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{SENTINEL_HUB_URL}/c310/snapshot.jpg",
                    params={"hud": hud, "width": width, "quality": quality},
                    timeout=aiohttp.ClientTimeout(total=6),
                ) as up:
                    body = await up.read()
                    return web.Response(
                        status=up.status,
                        body=body,
                        content_type="image/jpeg",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
                    )
        except Exception as exc:
            return web.Response(status=502, text=f"Error obteniendo snapshot C310: {exc}")

    async def handle_cam_mjpeg(self, request: web.Request) -> web.StreamResponse:
        ct = request.query.get("ct", "")
        init_data = request.query.get("init_data", "")
        if not self._authenticate_request(ct, init_data):
            return web.Response(status=403, text="No autorizado")
        hud = request.query.get("hud", "1")
        width = request.query.get("width", "1280")
        fps = request.query.get("fps", "10")
        quality = request.query.get("quality", "78")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
        await resp.prepare(request)
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=6, sock_read=30)
            ) as sess:
                async with sess.get(
                    f"{SENTINEL_HUB_URL}/c310/stream.mjpg",
                    params={"hud": hud, "width": width, "fps": fps, "quality": quality},
                ) as up:
                    async for chunk in up.content.iter_chunked(16384):
                        if chunk:
                            await resp.write(chunk)
        except (ConnectionResetError, asyncio.CancelledError, Exception):
            pass
        return resp

    async def _dispatch_cam_snapshot_to_telegram(self, chat_id: str) -> Dict[str, Any]:
        tok = get_bot_token()
        target_chat = chat_id if chat_id and chat_id not in ("menu", "anon") else str(ARCHITECT_TELEGRAM_ID)
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{SENTINEL_HUB_URL}/c310/snapshot.jpg",
                    params={"hud": "1", "width": "2304", "quality": "92"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as r_snap:
                    if r_snap.status != 200:
                        return {"ok": False, "error": f"HTTP {r_snap.status}"}
                    jpg_bytes = await r_snap.read()
                    persons = r_snap.headers.get("X-Persons-Detected", "0")

                ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
                caption = (
                    f"📸 *[CAPTURA EN VIVO · GOD-EYE C310]*\n"
                    f"• *Cámara:* `GOD-EYE (TP-Link Tapo C310 @ REDACTED_IP)`\n"
                    f"• *Resolución:* `2304×1296 (2K QHD)`\n"
                    f"• *Individuos en escena:* `{persons}`\n"
                    f"• *Hora:* `{ts_now}`"
                )
                form = aiohttp.FormData()
                form.add_field("chat_id", str(target_chat))
                form.add_field("caption", caption)
                form.add_field("parse_mode", "Markdown")
                form.add_field(
                    "photo",
                    jpg_bytes,
                    filename=f"godeye_live_{int(time.time())}.jpg",
                    content_type="image/jpeg",
                )
                async with sess.post(
                    f"https://api.telegram.org/bot{tok}/sendPhoto",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as tg_r:
                    return await tg_r.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _dispatch_cam_clip_to_telegram(
        self, chat_id: str, duration: float = 6.0
    ) -> Dict[str, Any]:
        tok = get_bot_token()
        target_chat = chat_id if chat_id and chat_id not in ("menu", "anon") else str(ARCHITECT_TELEGRAM_ID)
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{SENTINEL_HUB_URL}/c310/record_clip",
                    json={"duration": duration, "fps": 12, "width": 1280, "hud": True},
                    timeout=aiohttp.ClientTimeout(total=duration + 22.0),
                ) as r_clip:
                    clip_meta = await r_clip.json()
                if not clip_meta.get("ok") or not clip_meta.get("path"):
                    return {"ok": False, "error": clip_meta.get("error", "Fallo grabando clip")}
                mp4_path = Path(clip_meta["path"])
                if not mp4_path.is_file():
                    return {"ok": False, "error": "Archivo MP4 no encontrado"}

                ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
                caption = (
                    f"🔴 *[TRANSMISIÓN DE VIDEO EN VIVO · GOD-EYE C310]*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• *Cámara:* `GOD-EYE (TP-Link Tapo C310 @ REDACTED_IP)`\n"
                    f"• *Resolución / FPS:* `{clip_meta.get('width', 1280)}×{clip_meta.get('height', 720)}` @ `{clip_meta.get('fps', 12)} FPS`\n"
                    f"• *Duración:* `{clip_meta.get('duration_sec', duration)}s` (`{clip_meta.get('frames', 0)} fotogramas`)\n"
                    f"• *Individuos detectados (YOLOv8s):* `{clip_meta.get('persons_detected', 0)}`\n"
                    f"• *Hora local:* `{ts_now}`"
                )
                form = aiohttp.FormData()
                form.add_field("chat_id", str(target_chat))
                form.add_field("caption", caption)
                form.add_field("parse_mode", "Markdown")
                form.add_field("width", str(clip_meta.get("width", 1280)))
                form.add_field("height", str(clip_meta.get("height", 720)))
                form.add_field("duration", str(int(round(float(clip_meta.get("duration_sec", duration))))))
                form.add_field("supports_streaming", "true")
                form.add_field(
                    "video",
                    mp4_path.read_bytes(),
                    filename=mp4_path.name,
                    content_type="video/mp4",
                )
                async with sess.post(
                    f"https://api.telegram.org/bot{tok}/sendVideo",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as tg_r:
                    res_tg = await tg_r.json()
                    return {"ok": bool(res_tg.get("ok")), "clip": clip_meta, "telegram": res_tg}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def handle_cam_action(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        ct = body.get("ct") or request.query.get("ct", "")
        init_data = body.get("init_data") or request.headers.get("X-Telegram-Init-Data", "")
        auth = self._authenticate_request(ct, init_data)
        if not auth:
            return web.json_response({"ok": False, "error": "No autorizado"}, status=403)

        chat_id = str(auth.get("chat_id") or ARCHITECT_TELEGRAM_ID)
        action = str(body.get("action") or "").strip().lower()

        if action == "speak":
            text = str(body.get("text") or "").strip()
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(
                        f"{SENTINEL_HUB_URL}/c310/speak",
                        json={"text": text} if text else {},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as r_spk:
                        res_spk = await r_spk.json()
                        return web.json_response(res_spk)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=500)

        if action == "send_snapshot":
            res_s = await self._dispatch_cam_snapshot_to_telegram(chat_id)
            return web.json_response(res_s)

        if action == "send_clip":
            dur = float(body.get("duration", 6.0) or 6.0)
            res_c = await self._dispatch_cam_clip_to_telegram(chat_id, duration=dur)
            return web.json_response(res_c)

        return web.json_response({"ok": False, "error": f"Acción desconocida: {action}"}, status=400)

    async def handle_cam_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws_client = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await ws_client.prepare(request)

        query_ct = request.query.get("ct", "")
        auth_info = self._authenticate_request(query_ct, "")
        chat_id = str((auth_info or {}).get("chat_id") or ARCHITECT_TELEGRAM_ID)

        hud = request.query.get("hud", "1")
        width = request.query.get("width", "1280")
        fps = request.query.get("fps", "10")
        quality = request.query.get("quality", "78")
        ws_upstream_url = (
            f"{SENTINEL_HUB_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/c310/ws"
            f"?hud={hud}&width={width}&fps={fps}&quality={quality}"
        )

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.ws_connect(ws_upstream_url, heartbeat=20) as ws_up:
                    async def _client_to_up() -> None:
                        nonlocal auth_info, chat_id
                        try:
                            async for msg in ws_client:
                                if msg.type == WSMsgType.TEXT:
                                    try:
                                        data = json.loads(msg.data)
                                    except Exception:
                                        continue
                                    mtype = data.get("type")
                                    if mtype == "hello":
                                        verified = self._authenticate_request(
                                            data.get("ct") or query_ct,
                                            data.get("init_data") or "",
                                        )
                                        if not verified:
                                            await ws_client.send_str(
                                                json.dumps({"type": "error", "message": "No autorizado"})
                                            )
                                            await ws_client.close()
                                            break
                                        auth_info = verified
                                        chat_id = str(verified.get("chat_id") or ARCHITECT_TELEGRAM_ID)
                                        await ws_client.send_str(
                                            json.dumps(
                                                {
                                                    "type": "cam_ready",
                                                    "chat_id": chat_id,
                                                    "user_name": verified.get("user_name", "Arquitecto"),
                                                }
                                            )
                                        )
                                    elif mtype in ("set_options", "speak"):
                                        if not ws_up.closed:
                                            await ws_up.send_str(msg.data)
                                    elif mtype == "send_snapshot":
                                        res = await self._dispatch_cam_snapshot_to_telegram(chat_id)
                                        if not ws_client.closed:
                                            await ws_client.send_str(
                                                json.dumps({"type": "snapshot_sent", "ok": bool(res.get("ok"))})
                                            )
                                    elif mtype == "send_clip":
                                        dur = float(data.get("duration", 6.0) or 6.0)
                                        res = await self._dispatch_cam_clip_to_telegram(chat_id, duration=dur)
                                        if not ws_client.closed:
                                            await ws_client.send_str(
                                                json.dumps(
                                                    {
                                                        "type": "clip_sent",
                                                        "ok": bool(res.get("ok")),
                                                        "duration": dur,
                                                    }
                                                )
                                            )
                                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                    break
                        finally:
                            if not ws_up.closed:
                                await ws_up.close()

                    async def _up_to_client() -> None:
                        try:
                            async for msg in ws_up:
                                if ws_client.closed:
                                    break
                                if msg.type == WSMsgType.TEXT:
                                    await ws_client.send_str(msg.data)
                                elif msg.type == WSMsgType.BINARY:
                                    await ws_client.send_bytes(msg.data)
                                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                    break
                        finally:
                            if not ws_client.closed:
                                await ws_client.close()

                    await asyncio.gather(_client_to_up(), _up_to_client())
        except Exception as exc:
            logger.debug(f"WebSocket /tg-cam/ws finalizado: {exc}")
        finally:
            if not ws_client.closed:
                await ws_client.close()
        return ws_client

    async def on_startup(self, app: web.Application) -> None:
        asyncio.create_task(self.engine.warmup())
        self._watcher_task = asyncio.create_task(self.sync_telegram_menu_button())

    async def on_cleanup(self, app: web.Application) -> None:
        if self._watcher_task:
            self._watcher_task.cancel()


def create_app() -> web.Application:
    srv = TelegramLiveCallServer()
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app["server"] = srv
    app.router.add_get("/health", srv.handle_health)
    app.router.add_get("/tg-call/health", srv.handle_health)
    app.router.add_get("/tg-call", srv.handle_call_page)
    app.router.add_get("/tg-call/", srv.handle_call_page)
    app.router.add_get("/tg-call/ws", srv.handle_ws)
    app.router.add_get("/tg-cam", srv.handle_cam_page)
    app.router.add_get("/tg-cam/", srv.handle_cam_page)
    app.router.add_get("/tg-cam/ws", srv.handle_cam_ws)
    app.router.add_get("/tg-cam/stream.mjpg", srv.handle_cam_mjpeg)
    app.router.add_get("/tg-cam/snapshot.jpg", srv.handle_cam_snapshot)
    app.router.add_post("/tg-cam/action", srv.handle_cam_action)
    app.on_startup.append(srv.on_startup)
    app.on_cleanup.append(srv.on_cleanup)
    return app


def main() -> None:
    logger.info(f"🚀 Iniciando TARDIS Telegram Live Call Server en {DEFAULT_HOST}:{DEFAULT_PORT}")
    web.run_app(create_app(), host=DEFAULT_HOST, port=DEFAULT_PORT, print=None)


if __name__ == "__main__":
    main()
