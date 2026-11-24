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
from core.tardis_voice_program import get_voice_program_router
from core.telegram_call_priority import (
    activate_call_priority,
    boost_process_for_call,
    get_call_priority_status,
    is_call_priority_active,
    release_call_priority,
    touch_call_priority,
)
from core.videocall_vision_engine import (
    SceneMemory,
    get_videocall_vision_engine,
    is_visual_question,
)
from core.videocall_webapp_ui import render_live_call_and_video_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [TelegramLiveCall] %(message)s",
)
logger = logging.getLogger("TelegramLiveCall")

CONFIG_FILE = BASE_DIR / "telegram_config.json"
FTL_PUBLIC_URL_FILE = BASE_DIR / "FTL_PUBLIC_URL.txt"
LIVE_CALL_URL_FILE = BASE_DIR / "TELEGRAM_LIVE_CALL_URL.txt"
LIVE_VIDEOCALL_URL_FILE = BASE_DIR / "TELEGRAM_LIVE_VIDEOCALL_URL.txt"
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


def build_live_videocall_url(chat_id: int | str = "menu", user_name: str = "") -> str:
    """Construye el enlace HTTPS autenticado hacia la sala de videollamada en vivo de TARDIS."""
    base = get_public_tunnel_base()
    if not base:
        return ""
    ct = sign_call_token(chat_id=chat_id, user_name=user_name)
    return f"{base}/tg-call/video?{urlencode({'ct': ct})}"


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
            cmd = [
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
            ]
            # Durante llamadas prioritarias, ffmpeg se ejecuta con prioridad reforzada
            # para reducir la latencia de transcripción al primer token de respuesta.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if is_call_priority_active():
                try:
                    boost_process_for_call(proc)
                except Exception:
                    pass
            try:
                stdout, _stderr = proc.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=2)
                return "", 0.0
        finally:
            tmp_audio.unlink(missing_ok=True)
        if proc.returncode != 0 or not stdout:
            return "", 0.0

        pcm = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
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


_TEMPORAL_UDS_CLIENT: Optional[httpx.AsyncClient] = None


def _get_temporal_uds_client() -> httpx.AsyncClient:
    """Reutiliza un cliente HTTP keep-alive sobre `/tmp/temporal_brain.sock` para evitar handshakes por turno."""
    global _TEMPORAL_UDS_CLIENT
    if _TEMPORAL_UDS_CLIENT is None or _TEMPORAL_UDS_CLIENT.is_closed:
        transport = httpx.AsyncHTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
        _TEMPORAL_UDS_CLIENT = httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost",
            timeout=httpx.Timeout(connect=3.0, read=35.0, write=10.0, pool=5.0),
        )
    return _TEMPORAL_UDS_CLIENT


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

    call_priority = is_call_priority_active()
    # En llamada activa: menos tokens y contexto más corto = primer audio más rápido.
    max_tokens = 220 if call_priority else 380
    temperature = 0.32 if call_priority else 0.38
    call_messages = messages
    if call_priority and len(messages) > 10:
        # Preserva system prompt (si existe) + ventana reciente de diálogo.
        if messages and messages[0].get("role") == "system":
            call_messages = [messages[0]] + messages[-8:]
        else:
            call_messages = messages[-8:]

    if TEMPORAL_BRAIN_SOCK.exists():
        try:
            client = _get_temporal_uds_client()
            payload = {
                "messages": call_messages,
                "stream": True,
                "cache_prompt": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
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
    async with httpx.AsyncClient(timeout=35.0 if call_priority else 60.0) as client:
        r = await client.post(
            f"{TARDIS_CHAT_URL}?key={tok}",
            json={
                "message": user_text,
                "client_id": client_id,
                "use_web": not call_priority,
                "use_retro": not call_priority,
                "priority": bool(call_priority),
                "system_priority": bool(call_priority),
                "telegram_call_priority": bool(call_priority),
            },
        )
        data = r.json()
        reply = (data.get("response") or data.get("reply") or data.get("message") or "").strip()
        reply = _THINK_BLOCK_RE.sub("", reply).strip()
        if reply:
            yield reply


def load_recent_call_history(chat_id: str, limit: int = 8) -> List[Dict[str, str]]:
    """Recupera turnos previos desde OfflineChatVault para continuidad infinita."""
    try:
        from core.offline_chat_vault import get_offline_chat_vault

        cid = f"tg_call_{chat_id}"
        rows = get_offline_chat_vault().get_recent(limit=limit, client_id=cid, is_local=False)
        out: List[Dict[str, str]] = []
        for r in rows:
            u = str(r.get("user_message") or "").strip()
            # Limpia el prefijo de canal para mostrar/inyectar diálogo limpio
            u_clean = re.sub(r"^\[Llamada Telegram · [^\]]+\]:\s*", "", u).strip()
            a = str(r.get("assistant_reply") or "").strip()
            if u_clean:
                out.append({"role": "user", "content": u_clean})
            if a:
                out.append({"role": "assistant", "content": a})
        return out
    except Exception:
        return []


def get_call_vault_context(user_text: str, is_admin_caller: bool) -> str:
    """Obtiene contexto semántico relevante desde OfflineChatVault."""
    try:
        from core.offline_chat_vault import get_offline_chat_vault

        return get_offline_chat_vault().get_context_for_prompt(
            query=user_text,
            k_relevant=3,
            n_recent=2,
            is_local=is_admin_caller,
        ) or ""
    except Exception:
        return ""


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


async def notify_telegram_call_ended(
    chat_id: str,
    duration_sec: float,
    turns: int,
    mode: str = "voice",
    frames_received: int = 0,
    vision_analyses: int = 0,
) -> None:
    """Envía un resumen breve al chat de Telegram cuando concluye una llamada o videollamada."""
    if not str(chat_id).lstrip("-").isdigit() or (turns <= 0 and frames_received <= 0):
        return
    tok = get_bot_token()
    if not tok:
        return
    mins = int(duration_sec // 60)
    secs = int(duration_sec % 60)
    dur_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
    call_url = build_live_call_url(chat_id=chat_id)
    video_url = build_live_videocall_url(chat_id=chat_id)
    is_private = not str(chat_id).startswith("-")
    is_video = str(mode).lower() == "video" or frames_received > 0

    buttons = []
    if video_url:
        if is_private:
            buttons.append([{"text": "📹 Nueva Videollamada HD", "web_app": {"url": video_url}}])
        else:
            buttons.append([{"text": "📹 Nueva Videollamada HD", "url": video_url}])
    if call_url:
        if is_private:
            buttons.append([{"text": "📞 Volver a Llamar (Voz)", "web_app": {"url": call_url}}])
        else:
            buttons.append([{"text": "📞 Volver a Llamar (Voz)", "url": call_url}])

    if is_video:
        text = (
            "📹 *Videollamada con TARDIS finalizada*\n"
            f"• *Duración:* `{dur_str}`\n"
            f"• *Intercambios de voz:* `{turns}`\n"
            f"• *Fotogramas recibidos:* `{frames_received}` · *Análisis visuales VLM:* `{vision_analyses}`"
        )
    else:
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
# INTERFAZ MINI APP DE LLAMADA Y VIDEOLLAMADA EN VIVO
# ==============================================================================


def render_call_webapp_html(
    initial_ct: str,
    default_voice: str = DEFAULT_VOICE,
    initial_mode: str = "voice",
) -> str:
    return render_live_call_and_video_html(
        initial_ct=initial_ct,
        default_voice=default_voice,
        available_voices=AVAILABLE_VOICES,
        initial_mode=initial_mode,
    )


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
        self.vision = get_videocall_vision_engine()
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
        pub_video_url = build_live_videocall_url(chat_id="menu")
        priority = get_call_priority_status()
        active_video = sum(
            1 for s in self.active_sessions.values()
            if s.get("mode") == "video" or s.get("video_enabled")
        )
        return web.json_response(
            {
                "ok": True,
                "service": "tardis-telegram-live-call",
                "stt_ready": self.engine.stt_ready,
                "video_call_ready": True,
                "vlm_model": self.vision.vlm_model,
                "active_calls": len(self.active_sessions),
                "active_video_calls": active_video,
                "public_call_url": pub_url,
                "public_videocall_url": pub_video_url,
                "temporal_brain_socket": TEMPORAL_BRAIN_SOCK.exists(),
                "system_priority_active": priority.get("active", False),
                "call_priority": priority.get("active", False),
                "priority_mode": priority.get("priority_mode", "normal"),
                "priority_holders": priority.get("holder_count", 0),
            }
        )

    async def handle_priority_status(self, request: web.Request) -> web.Response:
        """Expone el estado del modo prioritario para supervisión local."""
        return web.json_response(get_call_priority_status())

    def _is_trusted_local_or_gateway(self, request: web.Request) -> bool:
        if request.headers.get("X-FTL-Gateway") == "1":
            return True
        remote = (request.remote or "").strip()
        return remote in ("127.0.0.1", "::1", "localhost")

    async def handle_call_page(self, request: web.Request) -> web.Response:
        ct = request.query.get("ct", "")
        # Permitir cargar la página si trae un token firmado válido o si se abre como WebApp de Telegram
        # (la validación estricta ocurre también en el handshake WebSocket con initData).
        if ct and not verify_call_token(ct):
            return web.Response(status=403, text="Enlace de llamada inválido o expirado.")
        path = request.path or ""
        is_video_route = (
            path.startswith(("/tg-call/video", "/tg-videocall", "/videollamada"))
            or request.query.get("mode", "").strip().lower() == "video"
        )
        if not ct and path.startswith(("/voz", "/videollamada")) and self._is_trusted_local_or_gateway(request):
            ct = sign_call_token(chat_id=ARCHITECT_TELEGRAM_ID, user_name="Arquitecto")
        cfg = load_telegram_config()
        pref_voice = str(cfg.get("cortana_voice", DEFAULT_VOICE))
        html_doc = render_call_webapp_html(
            initial_ct=ct,
            default_voice=pref_voice,
            initial_mode="video" if is_video_route else "voice",
        )
        return web.Response(
            text=html_doc,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_remote_feed_snapshot(self, request: web.Request) -> web.Response:
        """Entrega un fotograma JPEG en vivo de GOD-EYE C310 o de la pantalla del host (solo Arquitecto)."""
        ct = request.query.get("ct", "")
        init_data = request.headers.get("X-Telegram-Init-Data", "") or request.query.get("init_data", "")
        auth = self._authenticate_request(ct, init_data)
        if not auth:
            return web.Response(status=403, text="No autorizado")
        source = (request.query.get("source", "c310") or "c310").strip().lower()
        if source in ("screen", "host", "host_screen"):
            if not auth.get("is_admin"):
                return web.Response(status=403, text="Pantalla del host reservada exclusivamente al Arquitecto.")
            raw = await self.vision.capture_host_screen_bytes(max_width=1280, quality=72)
            if not raw:
                return web.Response(status=503, text="Pantalla bloqueada o captura no disponible.")
            return web.Response(
                body=raw,
                content_type="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )
        raw = await self.vision.fetch_c310_frame_bytes(width=960, quality=74, hud=True)
        if not raw:
            return web.Response(status=502, text="Cámara GOD-EYE C310 no disponible.")
        return web.Response(
            body=raw,
            content_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_analyze_frame_http(self, request: web.Request) -> web.Response:
        """Endpoint HTTP de respaldo para analizar un fotograma de videollamada con Qwen3-VL."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        ct = body.get("ct") or request.query.get("ct", "")
        init_data = body.get("init_data") or request.headers.get("X-Telegram-Init-Data", "")
        if not self._authenticate_request(ct, init_data):
            return web.json_response({"ok": False, "error": "No autorizado"}, status=403)
        b64_str = str(body.get("jpeg_b64") or "").strip()
        if not b64_str:
            return web.json_response({"ok": False, "error": "Falta jpeg_b64"}, status=400)
        try:
            raw = base64.b64decode(b64_str)
        except Exception:
            return web.json_response({"ok": False, "error": "Base64 inválido"}, status=400)
        prompt = str(body.get("prompt") or "").strip()
        source = str(body.get("source") or "camera").strip()
        res = await self.vision.analyze_frame_vlm(raw, question=prompt, source=source)
        return web.json_response(res)

    async def _dispatch_videocall_snapshot_to_telegram(
        self,
        chat_id: str,
        frame_bytes: bytes,
        description: str = "",
        source: str = "camera",
    ) -> Dict[str, Any]:
        tok = get_bot_token()
        if not tok or not frame_bytes:
            return {"ok": False, "error": "Bot o fotograma no disponible"}
        target_chat = chat_id if chat_id and str(chat_id) not in ("menu", "anon") else str(ARCHITECT_TELEGRAM_ID)
        ts_now = time.strftime("%Y-%m-%d %H:%M:%S")
        src_lbl = {
            "camera": "Cámara en Videollamada",
            "screen": "Pantalla Compartida",
            "c310": "GOD-EYE C310",
            "host_screen": "Pantalla Host TARDIS",
        }.get(source, source)
        caption = (
            f"📸 *[CAPTURA DE VIDEOLLAMADA · TARDIS]*\n"
            f"• *Fuente:* `{src_lbl}`\n"
            f"• *Hora:* `{ts_now}`"
        )
        if description:
            caption += f"\n• *Percepción Visual:* {description[:600]}"
        try:
            form = aiohttp.FormData()
            form.add_field("chat_id", str(target_chat))
            form.add_field("caption", caption)
            form.add_field("parse_mode", "Markdown")
            form.add_field(
                "photo",
                frame_bytes,
                filename=f"tardis_videocall_{int(time.time())}.jpg",
                content_type="image/jpeg",
            )
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"https://api.telegram.org/bot{tok}/sendPhoto",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as tg_r:
                    return await tg_r.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)

        query_ct = request.query.get("ct", "")
        session_id = f"call_{int(time.time() * 1000)}_{id(ws) & 0xFFFF:04x}"
        priority_source = f"live_call:{session_id}"
        priority_registered = False
        auth_info: Optional[Dict[str, Any]] = verify_call_token(query_ct) and self._authenticate_request(query_ct, "")
        user_name = (auth_info or {}).get("user_name", "Usuario")
        chat_id = (auth_info or {}).get("chat_id", "anon")
        is_admin_caller = bool((auth_info or {}).get("is_admin", False))
        voice_id = str(load_telegram_config().get("cortana_voice", DEFAULT_VOICE))

        # Prioridad temprana: si la conexión ya trae token válido, activar antes del hello.
        if auth_info:
            try:
                activate_call_priority(priority_source, chat_id=chat_id)
                priority_registered = True
            except Exception as exc:
                logger.debug(f"Aviso activando prioridad temprana en WS: {exc}")

        history: List[Dict[str, str]] = []
        current_turn_task: Optional[asyncio.Task] = None
        bg_vlm_task: Optional[asyncio.Task] = None
        remote_feed_task: Optional[asyncio.Task] = None
        pending_audio_turn_id = 0
        started_ts = time.time()
        turns_completed = 0
        call_mode = "video" if (request.path or "").startswith(("/tg-videocall", "/videollamada")) else "voice"
        video_enabled = False
        remote_feed = "avatar"
        scene = SceneMemory()
        last_bg_vlm_started = 0.0
        latest_remote_frame: Optional[bytes] = None

        async def cancel_active_turn() -> None:
            nonlocal current_turn_task
            if current_turn_task and not current_turn_task.done():
                current_turn_task.cancel()
                try:
                    await current_turn_task
                except (asyncio.CancelledError, Exception):
                    pass
            current_turn_task = None

        async def cancel_bg_vlm() -> None:
            nonlocal bg_vlm_task
            if bg_vlm_task and not bg_vlm_task.done():
                bg_vlm_task.cancel()
                try:
                    await bg_vlm_task
                except (asyncio.CancelledError, Exception):
                    pass
            bg_vlm_task = None

        async def stop_remote_feed() -> None:
            nonlocal remote_feed_task
            if remote_feed_task and not remote_feed_task.done():
                remote_feed_task.cancel()
                try:
                    await remote_feed_task
                except (asyncio.CancelledError, Exception):
                    pass
            remote_feed_task = None

        async def send_json(payload: Dict[str, Any]) -> None:
            if not ws.closed:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))

        async def speak_sentences(sentences: List[str], turn_id: int) -> None:
            for seq, s in enumerate(sentences):
                mp3 = await self.engine.synthesize_mp3(s, voice=voice_id)
                if mp3 and not ws.closed:
                    await send_json({"type": "tts_chunk", "turn_id": turn_id, "seq": seq, "text": s})
                    await ws.send_bytes(mp3)

        async def run_vlm_background(
            frame_bytes: bytes,
            source: str,
            prompt: str = "",
            explicit: bool = False,
            speak_after: bool = False,
            turn_id: int = 0,
        ) -> None:
            nonlocal turns_completed
            try:
                if explicit or speak_after:
                    await send_json({"type": "vision_scanning", "active": True})
                res = await self.vision.analyze_frame_vlm(frame_bytes, question=prompt, source=source)
                if res.get("ok"):
                    desc = str(res.get("description") or "").strip()
                    elapsed_ms = int(res.get("elapsed_ms") or 0)
                    scene.record_vlm_observation(desc, source=source, elapsed_ms=elapsed_ms)
                    await send_json(
                        {
                            "type": "vision_update",
                            "description": desc,
                            "source": source,
                            "model": res.get("model", self.vision.vlm_model),
                            "elapsed_ms": elapsed_ms,
                            "explicit": explicit,
                        }
                    )
                    if speak_after and desc:
                        history.append({"role": "user", "content": prompt or "¿Qué ves en mi cámara?"})
                        history.append({"role": "assistant", "content": desc})
                        turns_completed += 1
                        loop = asyncio.get_running_loop()
                        loop.run_in_executor(
                            None, record_call_turn, str(chat_id), user_name, prompt or "[Inspección visual]", desc
                        )
                        await send_json({"type": "assistant_delta", "turn_id": turn_id, "text": desc})
                        await speak_sentences([desc], turn_id=turn_id)
                        await send_json({"type": "turn_done", "turn_id": turn_id, "full_text": desc})
                elif explicit or speak_after:
                    err_txt = str(res.get("error") or "No pude analizar la imagen en este momento.")
                    await send_json({"type": "vision_scanning", "active": False})
                    await send_json({"type": "error", "message": err_txt})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(f"Aviso en análisis visual de videollamada: {exc}")
                await send_json({"type": "vision_scanning", "active": False})

        async def _remote_feed_loop(feed_name: str) -> None:
            nonlocal latest_remote_frame
            interval = 0.16 if feed_name == "c310" else 0.65
            try:
                while not ws.closed:
                    raw: Optional[bytes] = None
                    if feed_name == "c310":
                        raw = await self.vision.fetch_c310_frame_bytes(width=960, quality=72, hud=True)
                    elif feed_name == "screen" and is_admin_caller:
                        raw = await self.vision.capture_host_screen_bytes(max_width=1280, quality=70)
                    if raw and not ws.closed:
                        latest_remote_frame = raw
                        await send_json(
                            {
                                "type": "remote_frame",
                                "source": feed_name,
                                "jpeg_b64": base64.b64encode(raw).decode("ascii"),
                                "ts": round(time.time(), 3),
                            }
                        )
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(f"Loop remote_feed ({feed_name}) detenido: {exc}")

        async def run_turn(user_text: str, turn_id: int) -> None:
            nonlocal turns_completed
            try:
                # Renovar el TTL de la llamada: las conversaciones largas no deben
                # perder el modo prioritario por un timeout de seguridad.
                if priority_registered:
                    try:
                        touch_call_priority(priority_source, chat_id=chat_id)
                    except Exception:
                        pass
                # COMANDO DE VOZ SOBERANO «PROGRAMA»: se atiende antes que el LLM.
                # Funciona igual si el texto viene del micrófono de la llamada o
                # del teclado de la Mini App durante una llamada activa.
                voice_program = get_voice_program_router().handle(
                    user_text,
                    channel="telegram_live_call",
                    source=f"{user_name} · micrófono de {'videollamada' if call_mode == 'video' else 'llamada'}",
                    chat_id=chat_id,
                    metadata={"turn_id": turn_id, "mode": call_mode},
                )
                if voice_program:
                    reply = str(voice_program.get("reply") or "").strip()
                    if reply:
                        history.append({"role": "user", "content": user_text})
                        history.append({"role": "assistant", "content": reply})
                        turns_completed += 1
                        record_call_turn(str(chat_id), user_name, user_text, reply)
                        await send_json(
                            {"type": "assistant_delta", "turn_id": turn_id, "text": reply}
                        )
                        await speak_sentences([reply], turn_id=turn_id)
                        await send_json(
                            {"type": "turn_done", "turn_id": turn_id, "full_text": reply}
                        )
                    return

                # Si el usuario hace una pregunta visual durante la videollamada, garantizar percepción fresca
                if is_visual_question(user_text):
                    target_bytes: Optional[bytes] = None
                    target_src = scene.latest_source
                    if video_enabled and scene.latest_frame_bytes:
                        target_bytes = scene.latest_frame_bytes
                        target_src = scene.latest_source
                    elif remote_feed == "c310":
                        target_bytes = latest_remote_frame or await self.vision.fetch_c310_frame_bytes(width=640, quality=72)
                        target_src = "c310"
                    elif remote_feed == "screen" and is_admin_caller:
                        target_bytes = latest_remote_frame or await self.vision.capture_host_screen_bytes(max_width=960, quality=72)
                        target_src = "host_screen"
                    elif scene.latest_frame_bytes:
                        target_bytes = scene.latest_frame_bytes
                        target_src = scene.latest_source

                    if target_bytes and (scene.needs_fresh_vlm(max_age_sec=8.0) or target_src != scene.latest_vlm_source):
                        await send_json({"type": "vision_scanning", "active": True})
                        vlm_res = await self.vision.analyze_frame_vlm(
                            target_bytes, question=user_text, source=target_src
                        )
                        await send_json({"type": "vision_scanning", "active": False})
                        if vlm_res.get("ok"):
                            desc = str(vlm_res.get("description") or "").strip()
                            scene.record_vlm_observation(
                                desc,
                                source=target_src,
                                elapsed_ms=int(vlm_res.get("elapsed_ms") or 0),
                            )
                            await send_json(
                                {
                                    "type": "vision_update",
                                    "description": desc,
                                    "source": target_src,
                                    "model": vlm_res.get("model", self.vision.vlm_model),
                                    "elapsed_ms": int(vlm_res.get("elapsed_ms") or 0),
                                    "explicit": True,
                                }
                            )

                if call_mode == "video" or video_enabled:
                    sys_prompt = (
                        "Eres TARDIS, asistente de inteligencia artificial en una VIDEOLLAMADA EN VIVO "
                        f"full-duplex con {user_name}. Puedes ver a {user_name} y su entorno en tiempo real "
                        "mediante la percepción visual adjunta. Responde en español de manera cálida, natural, "
                        "clara y concisa (1 a 4 oraciones, sin tablas markdown ni bloques largos, listo para ser hablado)."
                    )
                    vis_ctx = scene.build_prompt_context()
                    if vis_ctx:
                        sys_prompt += "\n\n" + vis_ctx
                else:
                    sys_prompt = (
                        "Eres TARDIS, asistente de inteligencia artificial en un CHAT DE VOZ INFINITO EN VIVO "
                        f"con {user_name}. Responde en español de manera conversacional, fluida, clara y concisa "
                        "(idealmente de 1 a 4 oraciones, sin tablas markdown ni bloques de código largos, listo para ser hablado en voz alta)."
                    )
                loop = asyncio.get_running_loop()
                try:
                    vault_ctx = await asyncio.wait_for(
                        loop.run_in_executor(None, get_call_vault_context, user_text, is_admin_caller),
                        timeout=1.5,
                    )
                except Exception:
                    vault_ctx = ""
                if vault_ctx:
                    sys_prompt += "\n\n[MEMORIA CONTINUA]:\n" + vault_ctx[:1600]
                msgs: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
                msgs.extend(history[-14:])
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
                    loop.run_in_executor(None, record_call_turn, str(chat_id), user_name, user_text, clean_reply)

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

        self.active_sessions[session_id] = {
            "chat_id": chat_id,
            "started_at": started_ts,
            "mode": call_mode,
            "video_enabled": video_enabled,
        }
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
                        if str(data.get("mode") or "").lower() == "video" or bool(data.get("video_enabled")):
                            call_mode = "video"
                        video_enabled = bool(data.get("video_enabled", False))
                        req_feed = str(data.get("remote_feed") or "avatar").lower()
                        if req_feed in ("avatar", "c310", "screen"):
                            remote_feed = req_feed if (req_feed != "screen" or is_admin_caller) else "avatar"
                        self.active_sessions[session_id].update(
                            {
                                "chat_id": chat_id,
                                "user_name": user_name,
                                "mode": call_mode,
                                "video_enabled": video_enabled,
                            }
                        )

                        # Prioridad soberana del sistema y sus funciones desde el
                        # primer instante de la llamada/videollamada en vivo.
                        try:
                            activate_call_priority(priority_source, chat_id=chat_id)
                            priority_registered = True
                        except Exception as exc:
                            logger.debug(f"Aviso activando prioridad en llamada en vivo: {exc}")

                        if not history:
                            history.extend(load_recent_call_history(str(chat_id), limit=6))

                        await send_json(
                            {
                                "type": "call_ready",
                                "chat_id": chat_id,
                                "user_name": user_name,
                                "voice": voice_id,
                                "mode": call_mode,
                                "video_supported": True,
                                "video_enabled": video_enabled,
                                "vlm_model": self.vision.vlm_model,
                                "can_view_host_screen": bool(is_admin_caller),
                                "priority_active": priority_registered,
                            }
                        )
                        if remote_feed in ("c310", "screen"):
                            await stop_remote_feed()
                            remote_feed_task = asyncio.create_task(_remote_feed_loop(remote_feed))

                        if history and not data.get("reconnect"):
                            await send_json({"type": "history_sync", "turns": history[-6:]})

                        if not data.get("reconnect"):
                            if call_mode == "video":
                                greeting = (
                                    f"Hola {user_name}, videollamada en vivo conectada. "
                                    "Te veo y te escucho en tiempo real, dime qué necesitas."
                                )
                            else:
                                greeting = (
                                    f"Hola {user_name}, línea de voz infinita conectada. "
                                    "Te escucho en vivo, dime qué necesitas."
                                )
                            await send_json({"type": "assistant_delta", "turn_id": 0, "text": greeting})
                            current_turn_task = asyncio.create_task(speak_sentences([greeting], turn_id=0))

                    elif mtype == "video_state":
                        video_enabled = bool(data.get("enabled", False))
                        if video_enabled:
                            call_mode = "video"
                        self.active_sessions[session_id].update(
                            {"mode": call_mode, "video_enabled": video_enabled}
                        )
                        if priority_registered:
                            try:
                                touch_call_priority(priority_source, chat_id=chat_id)
                            except Exception:
                                pass

                    elif mtype == "video_frame":
                        if not auth_info and chat_id == "anon":
                            continue
                        b64_str = str(data.get("jpeg_b64") or "")
                        if not b64_str or len(b64_str) > 4 * 1024 * 1024:
                            continue
                        try:
                            frame_bytes = base64.b64decode(b64_str)
                        except Exception:
                            continue
                        src_name = str(data.get("source") or "camera").strip().lower()
                        if src_name not in ("camera", "screen"):
                            src_name = "camera"
                        video_enabled = True
                        call_mode = "video"
                        self.active_sessions[session_id].update({"mode": "video", "video_enabled": True})

                        loop = asyncio.get_running_loop()
                        tel = await loop.run_in_executor(
                            None, self.vision.inspect_frame_fast, frame_bytes, scene, src_name
                        )
                        await send_json({"type": "vision_telemetry", **tel.to_dict()})

                        analyze_now = bool(data.get("analyze_now", False))
                        prompt_txt = str(data.get("prompt") or "").strip()
                        now_ts = time.time()
                        should_bg_vlm = (
                            (scene.vlm_analyses == 0 and (now_ts - last_bg_vlm_started) >= 2.0)
                            or (scene.significant_motion_since_vlm and (now_ts - last_bg_vlm_started) >= 9.0)
                            or ((now_ts - last_bg_vlm_started) >= 18.0)
                        )
                        if analyze_now and prompt_txt:
                            await cancel_active_turn()
                            await cancel_bg_vlm()
                            last_bg_vlm_started = now_ts
                            tid = turns_completed + 1
                            current_turn_task = asyncio.create_task(
                                run_vlm_background(
                                    frame_bytes,
                                    source=src_name,
                                    prompt=prompt_txt,
                                    explicit=True,
                                    speak_after=True,
                                    turn_id=tid,
                                )
                            )
                        elif (analyze_now or should_bg_vlm) and (bg_vlm_task is None or bg_vlm_task.done()):
                            last_bg_vlm_started = now_ts
                            bg_vlm_task = asyncio.create_task(
                                run_vlm_background(
                                    frame_bytes,
                                    source=src_name,
                                    prompt=prompt_txt,
                                    explicit=analyze_now,
                                    speak_after=False,
                                )
                            )

                    elif mtype == "analyze_vision":
                        if not auth_info and chat_id == "anon":
                            continue
                        req_src = str(data.get("source") or "user").strip().lower()
                        prompt_txt = str(data.get("prompt") or "Describe en voz alta lo que ves ahora mismo.").strip()
                        speak_flag = bool(data.get("speak", True))
                        target_bytes: Optional[bytes] = None
                        resolved_src = scene.latest_source
                        if req_src == "c310":
                            target_bytes = latest_remote_frame or await self.vision.fetch_c310_frame_bytes(width=640, quality=75)
                            resolved_src = "c310"
                        elif req_src in ("screen", "host_screen") and is_admin_caller:
                            target_bytes = latest_remote_frame or await self.vision.capture_host_screen_bytes(max_width=1024, quality=75)
                            resolved_src = "host_screen"
                        else:
                            target_bytes = scene.latest_frame_bytes
                            resolved_src = scene.latest_source
                        if not target_bytes:
                            await send_json({"type": "vision_scanning", "active": False})
                            await send_json({"type": "error", "message": "Enciende la cámara o elige GOD-EYE para analizar video."})
                        else:
                            await cancel_active_turn()
                            await cancel_bg_vlm()
                            last_bg_vlm_started = time.time()
                            tid = turns_completed + 1
                            current_turn_task = asyncio.create_task(
                                run_vlm_background(
                                    target_bytes,
                                    source=resolved_src,
                                    prompt=prompt_txt,
                                    explicit=True,
                                    speak_after=speak_flag,
                                    turn_id=tid,
                                )
                            )

                    elif mtype == "set_remote_feed":
                        req_feed = str(data.get("feed") or "avatar").strip().lower()
                        if req_feed == "screen" and not is_admin_caller:
                            await send_json({"type": "error", "message": "Pantalla del host reservada al Arquitecto."})
                            continue
                        if req_feed not in ("avatar", "c310", "screen"):
                            req_feed = "avatar"
                        remote_feed = req_feed
                        await stop_remote_feed()
                        if remote_feed in ("c310", "screen"):
                            call_mode = "video"
                            self.active_sessions[session_id]["mode"] = "video"
                            remote_feed_task = asyncio.create_task(_remote_feed_loop(remote_feed))

                    elif mtype == "send_snapshot_to_chat":
                        if not auth_info and chat_id == "anon":
                            continue
                        req_src = str(data.get("source") or "user").strip().lower()
                        snap_bytes: Optional[bytes] = None
                        snap_src = scene.latest_source
                        if req_src == "c310":
                            snap_bytes = latest_remote_frame or await self.vision.fetch_c310_frame_bytes(width=1280, quality=84)
                            snap_src = "c310"
                        elif req_src in ("screen", "host_screen") and is_admin_caller:
                            snap_bytes = latest_remote_frame or await self.vision.capture_host_screen_bytes(max_width=1440, quality=82)
                            snap_src = "host_screen"
                        else:
                            snap_bytes = scene.latest_frame_bytes
                            snap_src = scene.latest_source
                        if not snap_bytes:
                            await send_json({"type": "snapshot_sent", "ok": False, "error": "Sin fotograma activo"})
                        else:
                            self.vision.save_snapshot(snap_bytes, str(chat_id), source=snap_src)
                            tg_res = await self._dispatch_videocall_snapshot_to_telegram(
                                str(chat_id), snap_bytes, description=scene.latest_description, source=snap_src
                            )
                            await send_json(
                                {
                                    "type": "snapshot_sent",
                                    "ok": bool(tg_res.get("ok")),
                                    "error": str(tg_res.get("error") or tg_res.get("description") or ""),
                                }
                            )

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
                        if str(data.get("mode") or "").lower() == "video":
                            call_mode = "video"
                        if priority_registered:
                            try:
                                release_call_priority(priority_source)
                                priority_registered = False
                            except Exception as exc:
                                logger.debug(f"Aviso liberando prioridad al colgar: {exc}")
                        await cancel_active_turn()
                        await cancel_bg_vlm()
                        await stop_remote_feed()
                        dur = float(data.get("duration_sec") or (time.time() - started_ts))
                        append_call_history_log(
                            {
                                "timestamp": int(time.time()),
                                "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "chat_id": chat_id,
                                "user_name": user_name,
                                "duration_sec": round(dur, 1),
                                "turns": turns_completed,
                                "mode": call_mode,
                                "frames_received": scene.frames_received,
                                "vision_analyses": scene.vlm_analyses,
                                "channel": "telegram_live_videocall" if call_mode == "video" else "telegram_live_webapp",
                            }
                        )
                        asyncio.create_task(
                            notify_telegram_call_ended(
                                str(chat_id),
                                dur,
                                turns_completed,
                                mode=call_mode,
                                frames_received=scene.frames_received,
                                vision_analyses=scene.vlm_analyses,
                            )
                        )
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
            await cancel_bg_vlm()
            await stop_remote_feed()
            self.active_sessions.pop(session_id, None)
            if priority_registered:
                try:
                    release_call_priority(priority_source)
                except Exception as exc:
                    logger.debug(f"Aviso liberando prioridad al cerrar llamada: {exc}")
            if not hangup_reported and (turns_completed > 0 or scene.frames_received > 0):
                dur = time.time() - started_ts
                append_call_history_log(
                    {
                        "timestamp": int(time.time()),
                        "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "chat_id": chat_id,
                        "user_name": user_name,
                        "duration_sec": round(dur, 1),
                        "turns": turns_completed,
                        "mode": call_mode,
                        "frames_received": scene.frames_received,
                        "vision_analyses": scene.vlm_analyses,
                        "channel": "telegram_live_videocall" if call_mode == "video" else "telegram_live_webapp",
                    }
                )
                asyncio.create_task(
                    notify_telegram_call_ended(
                        str(chat_id),
                        dur,
                        turns_completed,
                        mode=call_mode,
                        frames_received=scene.frames_received,
                        vision_analyses=scene.vlm_analyses,
                    )
                )
        return ws

    async def sync_telegram_menu_button(self) -> None:
        """
        Vigila `FTL_PUBLIC_URL.txt` y actualiza automáticamente el botón `📞 Llamar / Video`
        en Telegram (`setChatMenuButton`) cada vez que cambia el túnel Cloudflare.
        """
        while True:
            try:
                base = get_public_tunnel_base()
                tok = get_bot_token()
                if base and tok and base != self.last_synced_tunnel_url:
                    menu_url = build_live_call_url(chat_id="menu")
                    LIVE_CALL_URL_FILE.write_text(menu_url + "\n", encoding="utf-8")
                    videocall_url = build_live_videocall_url(chat_id="menu")
                    if videocall_url:
                        LIVE_VIDEOCALL_URL_FILE.write_text(videocall_url + "\n", encoding="utf-8")
                    cam_url = build_live_camera_url(chat_id=ARCHITECT_TELEGRAM_ID, user_name="Arquitecto")
                    if cam_url:
                        LIVE_CAM_URL_FILE.write_text(cam_url + "\n", encoding="utf-8")
                    async with aiohttp.ClientSession() as sess:
                        resp = await sess.post(
                            f"https://api.telegram.org/bot{tok}/setChatMenuButton",
                            json={
                                "menu_button": {
                                    "type": "web_app",
                                    "text": "📹 Videollamar",
                                    "web_app": {"url": videocall_url or menu_url},
                                }
                            },
                            timeout=aiohttp.ClientTimeout(total=10),
                        )
                        res_json = await resp.json()
                        if res_json.get("ok"):
                            self.last_synced_tunnel_url = base
                            logger.info(
                                f"📲 Botón '📹 Videollamar' sincronizado en Telegram -> {base}/tg-call/video"
                            )
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
    app.router.add_get("/tg-call/priority", srv.handle_priority_status)
    app.router.add_get("/tg-call", srv.handle_call_page)
    app.router.add_get("/tg-call/", srv.handle_call_page)
    app.router.add_get("/tg-call/video", srv.handle_call_page)
    app.router.add_get("/tg-call/video/", srv.handle_call_page)
    app.router.add_get("/tg-call/ws", srv.handle_ws)
    app.router.add_get("/tg-call/remote-feed.jpg", srv.handle_remote_feed_snapshot)
    app.router.add_post("/tg-call/analyze-frame", srv.handle_analyze_frame_http)
    app.router.add_get("/tg-videocall", srv.handle_call_page)
    app.router.add_get("/tg-videocall/", srv.handle_call_page)
    app.router.add_get("/tg-videocall/ws", srv.handle_ws)
    app.router.add_get("/videollamada", srv.handle_call_page)
    app.router.add_get("/videollamada/", srv.handle_call_page)
    app.router.add_get("/videollamada/ws", srv.handle_ws)
    app.router.add_get("/voz", srv.handle_call_page)
    app.router.add_get("/voz/", srv.handle_call_page)
    app.router.add_get("/voz/ws", srv.handle_ws)
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
