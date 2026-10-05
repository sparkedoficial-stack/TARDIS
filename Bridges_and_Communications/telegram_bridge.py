"""
core/telegram_bridge.py - Puente Soberano de Telegram para GODWORKS SYSTEM v26.4
================================================================================
Permite la interacción total y bidireccional con el sistema a través de Telegram:
  1. Conversación con el modelo central Hermes 3 (8B).
  2. Sincronización transversal de contexto en SYNC_HUB con todas las terminales.
  3. Ejecución inalámbrica de comandos bash en terminal (/sh, /bash).
  4. Control de hardware: bloqueo, desbloqueo (clave 0), captura de pantalla, reinicio.
  5. Envío inmediato del enlace web activo y código QR (/link, /qr).
  6. Notificaciones proactivas de arranque y reconexión del sistema.
  7. Long-polling autónomo: no requiere abrir puertos ni dominios en el router.
"""

from __future__ import annotations

import copy
import datetime
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CONFIG_FILE = BASE_DIR / "telegram_config.json"
logger = logging.getLogger("TelegramBridge")

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "bot_token": "",
    "allowed_chats": [],
    "admin_chat_id": None,
    "master_password": "0",
    "master_key": "DiosDelTiempo01",
    "notify_on_boot": True,
    "last_public_url": "",
    "bot_username": "",
    "voice_mode_always": False,
    "video_mode_always": True,
    "video_delivery_type": "video_note",
    "cortana_voice": "es-MX-DaliaNeural",
}


class ChatActionKeeper:
    """Mantiene el indicador de acción (ej: 'record_voice') activo en Telegram periódicamente mientras se procesa."""

    def __init__(self, bridge: "TelegramBridge", chat_id: int | str, action: str = "record_voice"):
        self.bridge = bridge
        self.chat_id = chat_id
        self.action = action
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="ChatActionKeeper")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.bridge.send_chat_action(self.action, self.chat_id)
            except Exception:
                pass
            self.stop_event.wait(4.0)


class TelegramBridge:
    """Gestor soberano de integración y supervisión de Telegram Bot."""

    _instance: Optional[TelegramBridge] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> TelegramBridge:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, config_path: Optional[Path | str] = None):
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self.config = self._load_config()
        self.pairing_passwords = ["0", "DiosDelTiempo01"]
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.last_update_id = 0
        self.bot_info: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.messages_processed = 0
        self.active_calls: Set[int | str] = set()
        self.voice_mode_always: bool = bool(self.config.get("voice_mode_always", False))
        self.video_mode_always: bool = bool(self.config.get("video_mode_always", True))
        self.video_delivery_type: str = str(self.config.get("video_delivery_type", "video_note"))

        # Iniciar si hay token configurado
        if self.config.get("enabled") and self.config.get("bot_token"):
            self.start()

    @property
    def active_model_label(self) -> str:
        act = os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated")
        if "dolphin" in act.lower():
            return "Dolphin 3.0 (8B)"
        return act

    @property
    def bot_token(self) -> str:
        return self.config.get("bot_token", "")

    @property
    def authorized_chat_ids(self) -> set:
        class _ChatSet(set):
            def __init__(outer_self, bridge):
                super().__init__(bridge.config.get("allowed_chats", []))
                outer_self._bridge = bridge
            def add(outer_self, item):
                super().add(item)
                outer_self._bridge.authorize_chat(item)
            def remove(outer_self, item):
                super().remove(item)
                allowed = outer_self._bridge.config.setdefault("allowed_chats", [])
                if item in allowed:
                    allowed.remove(item)
                outer_self._bridge.save_config()
            def discard(outer_self, item):
                super().discard(item)
                allowed = outer_self._bridge.config.setdefault("allowed_chats", [])
                if item in allowed:
                    allowed.remove(item)
                outer_self._bridge.save_config()
        return _ChatSet(self)

    @authorized_chat_ids.setter
    def authorized_chat_ids(self, val):
        self.config["allowed_chats"] = list(val)
        self.save_config()

    def authorize_chat(self, chat_id: int | str):
        try:
            cid = int(chat_id)
        except Exception:
            cid = chat_id
        allowed = self.config.setdefault("allowed_chats", [])
        if cid not in allowed:
            allowed.append(cid)
        self.config["admin_chat_id"] = cid
        self.save_config()

    def is_chat_authorized(self, chat_id: int | str) -> bool:
        allowed = self.config.get("allowed_chats", [])
        if not allowed:
            return False
        try:
            cid = int(chat_id)
            return cid in [int(c) for c in allowed]
        except Exception:
            return chat_id in allowed

    def configure_token(self, token: str, enabled: bool = True) -> bool:
        res = self.update_config({"bot_token": token, "enabled": enabled})
        return res.get("configured", False) or bool(self.config.get("bot_token"))

    # --------------------------------------------------------------------------
    # CONFIGURACIÓN Y PERSISTENCIA
    # --------------------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        # Leer primero de variables de entorno si existen
        env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if env_token:
            cfg["bot_token"] = env_token

        if getattr(self, "config_path", None) and self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                cfg.update(data)
            except Exception as e:
                logger.error(f"Error cargando {self.config_path}: {e}")

        return cfg

    def save_config(self) -> bool:
        try:
            target = getattr(self, "config_path", None) or CONFIG_FILE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            self.last_error = f"Error guardando configuración: {e}"
            return False

    def update_config(self, new_cfg: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            token_changed = "bot_token" in new_cfg and new_cfg["bot_token"] != self.config.get("bot_token")
            self.config.update(new_cfg)
            self.save_config()

            if token_changed:
                self.stop()
                if self.config.get("bot_token") and self.config.get("enabled", True):
                    self.start()

            return self.get_status()

            return self.get_status()

    # --------------------------------------------------------------------------
    # CICLO DE VIDA (START / STOP)
    # --------------------------------------------------------------------------

    def start(self) -> bool:
        token = self.config.get("bot_token", "").strip()
        if not token:
            self.last_error = "No hay bot_token configurado."
            return False

        if self.running and self.worker_thread and self.worker_thread.is_alive():
            return True

        # Validar token con getMe
        try:
            url = f"https://api.telegram.org/bot{token}/getMe"
            resp = requests.get(url, timeout=10.0).json()
            if not resp.get("ok"):
                self.last_error = f"Token inválido: {resp.get('description', 'Error getMe')}"
                return False

            self.bot_info = resp.get("result", {})
            self.config["bot_username"] = self.bot_info.get("username", "")
            self.config["bot_name"] = self.bot_info.get("first_name", "GODWORKS Bot")
            self.save_config()
            self.last_error = None
        except Exception as e:
            self.last_error = f"Error conectando a Telegram: {e}"
            return False

        self.running = True
        self.worker_thread = threading.Thread(target=self._polling_loop, daemon=True, name="TelegramPollingWorker")
        self.worker_thread.start()
        logger.info(f"TelegramBridge iniciado con @{self.config.get('bot_username')}")
        return True

    def stop(self):
        self.running = False
        if self.worker_thread:
            # Esperar retorno seguro sin bloquear indefinidamente
            self.worker_thread = None

    # --------------------------------------------------------------------------
    # VISUALIZACIÓN EN TERMINAL LOCAL & COMUNICACIÓN DE SALIDA (SEND API)
    # --------------------------------------------------------------------------

    def _print_incoming_request(self, user_name: str, chat_id: Any, req_type: str, content: str, username: str = ""):
        """Imprime un banner ANSI de alta visibilidad en la terminal local ante cada petición recibida por Telegram."""
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user_label = f"{user_name} (@{username})" if username else str(user_name)
            clean_lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            preview = clean_lines[0] if clean_lines else "(vacío)"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if len(clean_lines) > 1:
                preview += f" [+{len(clean_lines)-1} líneas]"

            banner = (
                f"\n\033[1;36m╔══════════════════════════════════════════════════════════════════════════════╗\033[0m\n"
                f"\033[1;36m║\033[1;97;44m 📱 [TELEGRAM -> TERMINAL LOCAL] PETICIÓN ENTRANTE                             \033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m╠══════════════════════════════════════════════════════════════════════════════╣\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Remitente:\033[0m \033[1;97m{user_label:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Chat ID  :\033[0m \033[1;97m{str(chat_id):<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Tipo     :\033[0m \033[1;92m{req_type:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Petición :\033[0m \033[1;93m\"{preview}\"\033[0m\n"
                f"\033[1;36m║\033[0m \033[1;33m• Timestamp:\033[0m \033[0;37m{now_str:<63}\033[0m\033[1;36m║\033[0m\n"
                f"\033[1;36m╚══════════════════════════════════════════════════════════════════════════════╝\033[0m\n"
            )
            sys.stdout.write(banner)
            sys.stdout.flush()
        except Exception as e:
            logger.debug(f"Error imprimiendo banner telegram entrante: {e}")

    def _print_outgoing_response(self, target_chat: Any, res_type: str, content: str):
        """Imprime un banner ANSI de alta visibilidad en la terminal local ante cada respuesta despachada hacia Telegram."""
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            clean_lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            preview = clean_lines[0] if clean_lines else "(vacío)"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if len(clean_lines) > 1:
                preview += f" [+{len(clean_lines)-1} líneas]"

            banner = (
                f"\n\033[1;32m╔══════════════════════════════════════════════════════════════════════════════╗\033[0m\n"
                f"\033[1;32m║\033[1;97;42m 🤖 [TARDIS -> TELEGRAM] RESPUESTA DESPACHADA                                  \033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m╠══════════════════════════════════════════════════════════════════════════════╣\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Destino  :\033[0m \033[1;97mChat ID {str(target_chat):<55}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Tipo     :\033[0m \033[1;96m{res_type:<63}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Respuesta:\033[0m \033[1;92m\"{preview}\"\033[0m\n"
                f"\033[1;32m║\033[0m \033[1;33m• Timestamp:\033[0m \033[0;37m{now_str:<63}\033[0m\033[1;32m║\033[0m\n"
                f"\033[1;32m╚══════════════════════════════════════════════════════════════════════════════╝\033[0m\n"
            )
            sys.stdout.write(banner)
            sys.stdout.flush()
        except Exception as e:
            logger.debug(f"Error imprimiendo banner telegram saliente: {e}")

    def send_message(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token configured"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id available"}

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        # Visualizar respuesta en la terminal local
        self._print_outgoing_response(target_chat, "💬 TEXTO MARKDOWN", text)

        try:
            resp = requests.post(url, json=payload, timeout=12.0)
            data = resp.json()
            if not data.get("ok"):
                # Fallback sin parse_mode si falla por markdown
                payload.pop("parse_mode", None)
                resp_fb = requests.post(url, json=payload, timeout=12.0)
                data = resp_fb.json()
            return data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_photo(
        self,
        photo: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None
    ) -> Dict[str, Any]:
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        # Visualizar despacho de imagen en la terminal local
        self._print_outgoing_response(target_chat, "📸 IMAGEN / CAPTURA", caption or "Imagen enviada")

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        data = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"

        try:
            files = {}
            if isinstance(photo, (str, Path)):
                p = Path(photo)
                if p.is_file():
                    files["photo"] = open(p, "rb")
                else:
                    return {"ok": False, "error": f"Archivo no encontrado: {photo}"}
            elif isinstance(photo, bytes):
                files["photo"] = ("screenshot.png", photo, "image/png")
            elif isinstance(photo, io.BytesIO):
                files["photo"] = ("image.png", photo.getvalue(), "image/png")

            resp = requests.post(url, data=data, files=files, timeout=20.0)
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_chat_action(self, action: str = "record_voice", chat_id: Optional[int | str] = None) -> bool:
        """Envía indicador de acción a Telegram (record_voice, typing, upload_voice)."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return False

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return False

        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        try:
            resp = requests.post(url, json={"chat_id": target_chat, "action": action}, timeout=8.0)
            return bool(resp.json().get("ok"))
        except Exception:
            return False

    def convert_to_wav(self, audio_bytes: bytes) -> Optional[bytes]:
        """Convierte cualquier formato de audio recibido (OGG, MP3, etc.) a WAV 16kHz mono para STT."""
        try:
            cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            wav_out, _ = proc.communicate(input=audio_bytes, timeout=15.0)
            if proc.returncode == 0 and wav_out:
                return wav_out
        except Exception as e:
            logger.error(f"Error convirtiendo audio a WAV con ffmpeg: {e}")
        return None

    def convert_to_ogg(self, audio_bytes: bytes) -> Optional[bytes]:
        """Convierte audio (MP3 o WAV) a OGG Opus nativo para Telegram Voice Notes."""
        try:
            cmd = ["ffmpeg", "-y", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-vbr", "on", "-f", "ogg", "pipe:1"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            ogg_out, _ = proc.communicate(input=audio_bytes, timeout=15.0)
            if proc.returncode == 0 and ogg_out:
                return ogg_out
        except Exception as e:
            logger.error(f"Error convirtiendo audio a OGG Opus con ffmpeg: {e}")
        return None

    def download_telegram_file(self, file_id: str) -> Optional[bytes]:
        """Descarga un archivo (nota de voz/audio) directamente desde los servidores de Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token or not file_id:
            return None
        try:
            gf_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            res = requests.get(gf_url, timeout=15.0).json()
            if not res.get("ok"):
                return None
            file_path = res.get("result", {}).get("file_path")
            if not file_path:
                return None
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            resp = requests.get(dl_url, timeout=30.0)
            if resp.status_code == 200:
                return resp.content
        except Exception as e:
            logger.error(f"Error descargando archivo {file_id} de Telegram: {e}")
        return None

    def transcribe_audio(self, audio_bytes: bytes, lang: str = "es-MX") -> Optional[str]:
        """Transcribe bytes de voz a texto usando SpeechRecognition con Google STT."""
        wav_bytes = self.convert_to_wav(audio_bytes)
        if not wav_bytes:
            return None

        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = recognizer.record(source)

            # Intento primario con idioma configurado
            try:
                text = recognizer.recognize_google(audio_data, language=lang)
                if text and text.strip():
                    return text.strip()
            except sr.UnknownValueError:
                pass
            except sr.RequestError as re:
                logger.warning(f"Google STT request error ({lang}): {re}")

            # Intento secundario con español genérico
            try:
                text = recognizer.recognize_google(audio_data, language="es-ES")
                if text and text.strip():
                    return text.strip()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error procesando transcripción STT: {e}")

        return None

    def clean_text_for_speech(self, text: str) -> str:
        """Limpia markdown y caracteres de interfaz para una lectura natural y fluida con Cortana."""
        if not text:
            return ""
        t = text
        # Simplificar bloques de código multilínea para que Cortana los mencione de manera natural
        t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r" Código en pantalla: \1 ", t)
        t = re.sub(r"```", " ", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        # Convertir enlaces markdown [Texto](URL) a solo Texto
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
        # Quitar formato de negrita y cursiva
        t = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", t)
        t = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", t)
        # Quitar numerales de encabezados
        t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
        # Quitar separadores gráficos repetidos
        t = re.sub(r"[━─=_\-]{3,}", " ", t)
        # Normalizar espacios
        t = re.sub(r"[ \t]+", " ", t)
        return t.strip()

    def synthesize_speech(self, text: str, voice_id: Optional[str] = None) -> Optional[bytes]:
        """Sintetiza texto completo a voz usando voice.py (Cortana Neural / Edge-TTS) y genera OGG Opus."""
        text_clean = self.clean_text_for_speech(text)
        if not text_clean:
            return None
        target_voice = voice_id or self.config.get("cortana_voice", "es-MX-DaliaNeural")
        try:
            import voice as _v
            # Asegurar locución con la voz de Cortana Neural
            mp3_bytes = _v.synthesize_to_bytes(text_clean, voice=target_voice)
            if mp3_bytes:
                ogg_bytes = self.convert_to_ogg(mp3_bytes)
                return ogg_bytes or mp3_bytes
        except Exception as e:
            logger.error(f"Error sintetizando voz de Cortana para Telegram: {e}")
        return None

    def send_reply_with_voice(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        caption_voice: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envía la respuesta de texto a Telegram y simultáneamente sintetiza un audio
        leyendo todo el texto con la voz de Cortana, enviándolo a la vez que el texto.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        # 1. Enviar el mensaje de texto de inmediato
        res_msg = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)

        # 2. Sintetizar la lectura completa con Cortana y enviarla a la vez si está activado
        res_voice = None
        cid_int = int(target_chat) if str(target_chat).lstrip("-").isdigit() else target_chat
        should_voice = self.voice_mode_always or (cid_int in self.active_calls)

        if should_voice:
            with ChatActionKeeper(self, target_chat, "record_voice"):
                ogg_audio = self.synthesize_speech(text)
                if ogg_audio:
                    voice_caption = caption_voice or f"🎙️ {text}"
                    res_voice = self.send_voice(
                        ogg_audio,
                        caption=voice_caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id
                    )

        return {"ok": True, "message_result": res_msg, "voice_result": res_voice}

    def send_voice(
        self,
        voice: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """Envía una nota de voz nativa (sendVoice) a Telegram con reproductor de audio integrado."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        voice_bytes = None
        if isinstance(voice, (str, Path)):
            p = Path(voice)
            if p.is_file():
                voice_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {voice}"}
        elif isinstance(voice, io.BytesIO):
            voice_bytes = voice.getvalue()
        elif isinstance(voice, bytes):
            voice_bytes = voice

        if not voice_bytes:
            return {"ok": False, "error": "Audio vacío"}

        # Convertir a OGG si no tiene cabecera OggS
        if not voice_bytes.startswith(b"OggS"):
            ogg_conv = self.convert_to_ogg(voice_bytes)
            if ogg_conv:
                voice_bytes = ogg_conv

        url = f"https://api.telegram.org/bot{token}/sendVoice"
        data: Dict[str, Any] = {"chat_id": target_chat}
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)

        files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}

        # Visualizar despacho de nota de voz en la terminal local
        self._print_outgoing_response(target_chat, "🎙️ NOTA DE VOZ (OPUS OGG)", caption or "Nota de voz enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=30.0)
            res_data = resp.json()
            if not res_data.get("ok") and caption and "parse_mode" in data:
                data.pop("parse_mode", None)
                files = {"voice": ("voice.ogg", voice_bytes, "audio/ogg")}
                res_data = requests.post(url, data=data, files=files, timeout=30.0).json()
            return res_data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_video(
        self,
        video: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        width: int = 480,
        height: int = 480,
        supports_streaming: bool = True
    ) -> Dict[str, Any]:
        """Envía un video estándar (sendVideo) a Telegram con reproductor de video integrado y subtítulo."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        video_bytes = None
        if isinstance(video, (str, Path)):
            p = Path(video)
            if p.is_file():
                video_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {video}"}
        elif isinstance(video, io.BytesIO):
            video_bytes = video.getvalue()
        elif isinstance(video, bytes):
            video_bytes = video

        if not video_bytes:
            return {"ok": False, "error": "Video vacío"}

        url = f"https://api.telegram.org/bot{token}/sendVideo"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "width": int(width),
            "height": int(height),
            "supports_streaming": bool(supports_streaming)
        }
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)

        files = {"video": ("speaking_system.mp4", video_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "🎬 VIDEO DEL SISTEMA HABLANDO", caption or "Video de locución enviado")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            res_data = resp.json()
            if not res_data.get("ok") and caption and "parse_mode" in data:
                data.pop("parse_mode", None)
                files = {"video": ("speaking_system.mp4", video_bytes, "video/mp4")}
                res_data = requests.post(url, data=data, files=files, timeout=45.0).json()
            return res_data
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_video_note(
        self,
        video_note: bytes | io.BytesIO | str | Path,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        length: int = 480
    ) -> Dict[str, Any]:
        """Envía un videomensaje circular nativo (sendVideoNote / telescopio) de Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        vn_bytes = None
        if isinstance(video_note, (str, Path)):
            p = Path(video_note)
            if p.is_file():
                vn_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {video_note}"}
        elif isinstance(video_note, io.BytesIO):
            vn_bytes = video_note.getvalue()
        elif isinstance(video_note, bytes):
            vn_bytes = video_note

        if not vn_bytes:
            return {"ok": False, "error": "Videonota vacía"}

        url = f"https://api.telegram.org/bot{token}/sendVideoNote"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "length": int(length)
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)

        files = {"video_note": ("video_note.mp4", vn_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "📹 VIDEONOTA CIRCULAR (SISTEMA HABLANDO)", "Videonota redonda enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_reply_with_video(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sintetiza la respuesta y renderiza un video dinámico del sistema hablando.
        Despacha exclusivamente el video a Telegram (sustituyendo texto plano y notas de voz).
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat"}

        use_note = (self.video_delivery_type == "video_note")
        action = "record_video_note" if use_note else "upload_video"

        with ChatActionKeeper(self, target_chat, action):
            try:
                from core.speaking_video_generator import get_speaking_video_generator
                gen = get_speaking_video_generator()
                v_res = gen.generate_speaking_video(text, voice_id=self.config.get("cortana_voice"))

                if v_res and v_res.get("ok") and v_res.get("video_bytes"):
                    dur = int(v_res.get("duration", 4))
                    # Si es videonota y dura <= 60s (límite API Telegram para video notes)
                    if use_note and dur <= 60:
                        res_send = self.send_video_note(
                            v_res["video_bytes"],
                            chat_id=target_chat,
                            reply_to_message_id=reply_to_message_id,
                            duration=dur
                        )
                        if res_send and res_send.get("ok"):
                            return {"ok": True, "type": "video_note", "result": res_send}
                        logger.warning(f"sendVideoNote falló ({res_send}), reintentando como sendVideo...")

                    # Enviar como video regular MP4 con subtítulo
                    vid_cap = caption or f"🎬 **GIA:** {text}"
                    res_send = self.send_video(
                        v_res["video_bytes"],
                        caption=vid_cap,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=dur
                    )
                    return {"ok": True, "type": "video", "result": res_send}

                else:
                    logger.warning(f"Error generando video hablando: {v_res.get('error')}. Fallback a voz...")
            except Exception as e:
                logger.error(f"Excepción en send_reply_with_video: {e}. Fallback a voz...")

        # Fallback de seguridad en caso de falla crítica
        return self.send_reply_with_voice(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)

    def start_call(self, chat_id: int | str, user_name: str = "Usuario", initial_speech: Optional[str] = None) -> Dict[str, Any]:
        """Inicia una llamada interactiva con el usuario de Telegram."""
        cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        self.active_calls.add(cid)

        auth_url = ""
        try:
            from omni_temporal_control import BRIDGE
            auth_url = BRIDGE.get_status().get("auth_url", "")
        except Exception:
            pass

        greeting_text = initial_speech or (
            f"Hola {user_name}, he conectado la llamada soberana contigo. "
            "Te estoy escuchando en tiempo real. Envíame tus notas de voz o instrucciones "
            "y te responderé con mi voz en cada turno. ¿Qué directiva tienes para mí?"
        )

        call_banner = (
            "📞 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 **[LLAMADA ENTRANTE DE GIA · CANAL SOBERANO]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Interlocutor:** {user_name} (ID: `{chat_id}`)\n"
            "🎙️ **Estado:** Conexión de voz activa 24/7.\n"
            "🗣️ **Voz de GIA:** Cortana Neural (Microsoft Dalia)\n"
            f"⚡ **Cerebro:** {self.active_model_label} [Soberano]\n\n"
            "💬 *Puedes hablarme presionando el micrófono y enviando una nota de voz. GIA te responderá por voz a cada turno.*\n"
            "*(Para finalizar la llamada en cualquier momento, envía `/colgar` o `/endcall`)*"
        )
        if auth_url:
            call_banner += f"\n\n🌐 **Sala Web de Audio en Vivo:**\n{auth_url}"

        self.send_message(call_banner, chat_id=chat_id)

        with ChatActionKeeper(self, chat_id, "record_voice"):
            ogg = self.synthesize_speech(greeting_text)
            if ogg:
                self.send_voice(ogg, caption=f"🎙️ {greeting_text}", chat_id=chat_id)
            else:
                self.send_message(f"🗣️ {greeting_text}", chat_id=chat_id)

        return {"ok": True, "call_active": True, "chat_id": chat_id}

    def end_call(self, chat_id: int | str) -> Dict[str, Any]:
        """Finaliza la llamada activa en Telegram."""
        cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        if cid in self.active_calls:
            self.active_calls.discard(cid)

        farewell = "Llamada finalizada. El canal de voz se cierra. Puedes seguir comunicándote por texto o reactivar la llamada con /llamar."
        self.send_message(
            "📵 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 **[LLAMADA FINALIZADA · CANAL CERRADO]**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Sesión de diálogo por voz concluida.\n"
            "💬 Para volver a llamar en cualquier momento, envía `/llamar` o `/call`.",
            chat_id=chat_id
        )
        ogg = self.synthesize_speech(farewell)
        if ogg:
            self.send_voice(ogg, caption=f"🎙️ {farewell}", chat_id=chat_id)
        return {"ok": True, "call_active": False}

    def make_call(self, chat_id: Optional[int | str] = None, initial_speech: Optional[str] = None) -> Dict[str, Any]:
        """Realiza una llamada proactiva hacia el usuario autorizado."""
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No hay chat_id destino disponible"}
        return self.start_call(target_chat, initial_speech=initial_speech)

    def notify_system_boot(self, auth_url: str, local_url: str):
        """Notifica proactivamente a todos los chats autorizados que el sistema inició con éxito."""
        if not self.config.get("notify_on_boot"):
            return

        chats = self.config.get("allowed_chats", [])
        if not chats and self.config.get("admin_chat_id"):
            chats = [self.config.get("admin_chat_id")]

        if not chats:
            return

        msg = (
            "🚀 **GODWORKS SYSTEM v26.4 EN LÍNEA**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🖥️ **Estado:** Sistema encendido y auto-desbloqueado (clave: `0`).\n"
            f"🧠 **Cerebro Central:** {self.active_model_label} · 100% Soberano.\n"
            "⚡ **Enlace Web Activo:**\n"
            f"{auth_url}\n\n"
            f"📶 **Red Local Wi-Fi:** `{local_url}`\n"
            "📱 *Puedes hablarme directamente aquí o enviar /sh para controlar la terminal.*"
        )

        for cid in chats:
            try:
                self.send_message(msg, chat_id=cid, parse_mode="Markdown")
            except Exception:
                pass

    # --------------------------------------------------------------------------
    # BUCLE DE POLLING (LONG-POLLING WORKER)
    # --------------------------------------------------------------------------

    def _polling_loop(self):
        token = self.config.get("bot_token", "").strip()
        retry_delay = 2

        while self.running:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates"
                params = {
                    "offset": self.last_update_id + 1 if self.last_update_id > 0 else None,
                    "timeout": 20,
                    "allowed_updates": ["message"]
                }
                resp = requests.get(url, params=params, timeout=25.0)
                if resp.status_code == 200:
                    data = resp.json()
                    retry_delay = 2
                    if data.get("ok"):
                        for update in data.get("result", []):
                            if not self.running:
                                break
                            up_id = update.get("update_id")
                            if up_id:
                                self.last_update_id = max(self.last_update_id, up_id)
                            self._handle_update(update)
                else:
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
            except requests.Timeout:
                continue
            except Exception as e:
                self.last_error = f"Error en polling: {e}"
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    # --------------------------------------------------------------------------
    # PROCESAMIENTO DE MENSAJES Y DESPACHO A HERMES / HARDWARE
    # --------------------------------------------------------------------------

    def _handle_incoming_text(self, chat_id: int | str, text: str, user_name: str = "Usuario", msg_id: Optional[int] = None):
        """Helper para pruebas y despacho directo de texto entrante."""
        update = {
            "update_id": 0,
            "message": {
                "message_id": msg_id or 1,
                "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id},
                "from": {"first_name": user_name},
                "text": text
            }
        }
        return self._handle_update(update)

    def _handle_incoming_voice(self, chat_id: int | str, file_id: str = "voice_file_123", user_name: str = "Usuario", msg_id: Optional[int] = None):
        """Helper para pruebas y despacho directo de nota de voz entrante."""
        update = {
            "update_id": 0,
            "message": {
                "message_id": msg_id or 1,
                "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id},
                "from": {"first_name": user_name},
                "voice": {
                    "file_id": file_id,
                    "duration": 4,
                    "mime_type": "audio/ogg"
                }
            }
        }
        return self._handle_update(update)

    def _handle_update(self, update: Dict[str, Any]):
        msg = update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        user = msg.get("from", {})
        user_name = user.get("first_name", "Usuario")
        username = user.get("username", "")
        msg_id = msg.get("message_id")

        voice_info = msg.get("voice") or msg.get("audio") or msg.get("video_note")
        is_voice_message = bool(voice_info)
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if not text and not is_voice_message:
            return

        self.messages_processed += 1
        allowed = self.config.get("allowed_chats", [])

        # Autenticación y vinculación inmediata
        if not self.is_chat_authorized(chat_id):
            self._print_incoming_request(user_name, chat_id, "🔒 SOLICITUD DE AUTENTICACIÓN", text or "(Audio no autenticado)", username)
            # Si envía la contraseña maestra, autorizar automáticamente
            if text in (self.config.get("master_password"), self.config.get("master_key"), "0", "DiosDelTiempo01"):
                self.authorize_chat(chat_id)
                reply = (
                    "👑 **¡ACCESO SOBERANO CONCEDIDO!**\n\n"
                    f"Bienvenido, {user_name}. Tu cuenta de Telegram ha sido autorizada como nodo soberano de GODWORKS SYSTEM v26.4.\n\n"
                    "• Tienes acceso perpetuo y control total del equipo.\n"
                    f"• Cerebro Central: **{self.active_model_label}**.\n"
                    "• Puedes escribir directivas, enviar notas de voz o usar `/llamar` para iniciar una llamada."
                )
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return
            elif not allowed:
                # Si no hay ningún chat configurado, pedir autenticación
                reply = (
                    "🔒 **AUTENTICACIÓN REQUERIDA · CONTROL SOBERANO**\n\n"
                    f"Hola {user_name}. Para autorizar este chat de Telegram, introduce la contraseña del sistema (clave: `0` o `DiosDelTiempo01`)."
                )
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return
            else:
                self.send_message("🔒 **AUTENTICACIÓN REQUERIDA**: Acceso no autorizado. Introduce la clave maestra del sistema (clave: `0`).", chat_id=chat_id)
                return

        # Si es un mensaje de voz, transcribirlo con STT
        if is_voice_message:
            self._print_incoming_request(user_name, chat_id, "🎙️ NOTA DE VOZ (DESCARGANDO & TRANSCRIBIENDO)", "Descargando audio de Telegram...", username)
            file_id = voice_info.get("file_id") if isinstance(voice_info, dict) else None
            if file_id:
                with ChatActionKeeper(self, chat_id, "record_voice"):
                    raw_audio = self.download_telegram_file(file_id)
                    if not raw_audio:
                        self.send_message("⚠️ No fue posible descargar el audio de Telegram.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return
                    transcribed = self.transcribe_audio(raw_audio)
                    if not transcribed:
                        not_heard = "No logré captar claramente tus palabras en la nota de voz. ¿Podrías repetirlo o enviarlo por texto?"
                        ogg_fail = self.synthesize_speech(not_heard)
                        if ogg_fail:
                            self.send_voice(ogg_fail, caption=f"🎙️ {not_heard}", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            self.send_message(f"🎙️ {not_heard}", chat_id=chat_id, reply_to_message_id=msg_id)
                        return
                    text = transcribed
                    self._print_incoming_request(user_name, chat_id, "🎙️ TRANSCRIPCIÓN DE VOZ COMPLETA", text, username)

            # Al recibir nota de voz, se activa el modo llamada interactiva
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            self.active_calls.add(cid_int)
        else:
            # Mensaje de texto o comando regular
            self._print_incoming_request(user_name, chat_id, "⚡ COMANDO DE CONTROL" if text.startswith("/") else "💬 PETICIÓN / CHAT", text, username)

        # ----------------------------------------------------------------------
        # COMANDOS NATIVOS DE TELEGRAM (/start, /llamar, /colgar, /sh, /status, etc.)
        # ----------------------------------------------------------------------
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        arg_str = " ".join(args).strip()

        # Detección de intenciones de llamada en lenguaje natural
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in ("hazme una llamada", "inicia una llamada", "iniciar llamada", "llámame", "llamame", "haz una llamada")):
            self.start_call(chat_id, user_name=user_name)
            return

        if any(phrase in text_lower for phrase in ("cuelga la llamada", "colgar llamada", "termina la llamada", "terminar llamada", "cuelga")):
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            if cid_int in self.active_calls:
                self.end_call(chat_id)
                return

        if cmd in ("/llamar", "/call", "/llamada", "/iniciar_llamada", "/marcar"):
            self.start_call(chat_id, user_name=user_name)
            return

        if cmd in ("/colgar", "/endcall", "/terminar", "/colgar_llamada", "/fin"):
            self.end_call(chat_id)
            return

        if cmd in ("/voz_modo", "/voz_forzada"):
            if arg_str.lower() in ("on", "1", "activar", "si", "true"):
                self.voice_mode_always = True
                self.send_message("🗣️ Modo de respuesta por voz forzada activado para todos los mensajes.", chat_id=chat_id)
            elif arg_str.lower() in ("off", "0", "desactivar", "no", "false"):
                self.voice_mode_always = False
                self.send_message("🔇 Modo de respuesta por voz forzada desactivado.", chat_id=chat_id)
            else:
                st = "🟢 ACTIVADO" if self.voice_mode_always else "🔴 DESACTIVADO"
                self.send_message(f"🗣️ Modo de voz forzada: {st}. Usa `/voz_modo on` o `/voz_modo off`.", chat_id=chat_id)
            return

        if cmd in ("/video", "/video_modo", "/videonota"):
            arg_l = arg_str.lower()
            if arg_l in ("on", "1", "activar", "si", "true"):
                self.video_mode_always = True
                self.config["video_mode_always"] = True
                self.save_config()
                self.send_message("🎬 **MODO VIDEO ACTIVADO**: A partir de ahora responderé exclusivamente con video del sistema hablando (sin texto plano ni voz suelta).", chat_id=chat_id)
            elif arg_l in ("off", "0", "desactivar", "no", "false"):
                self.video_mode_always = False
                self.config["video_mode_always"] = False
                self.save_config()
                self.send_message("🔇 **MODO VIDEO DESACTIVADO**: Volviendo al modo de texto o voz regular.", chat_id=chat_id)
            elif arg_l in ("nota", "circular", "redondo"):
                self.video_delivery_type = "video_note"
                self.config["video_delivery_type"] = "video_note"
                self.save_config()
                self.send_message("📹 **FORMATO CONFIGURADO**: Videonota circular (telescopio de Telegram).", chat_id=chat_id)
            elif arg_l in ("estandar", "video", "mp4", "cuadrado"):
                self.video_delivery_type = "video"
                self.config["video_delivery_type"] = "video"
                self.save_config()
                self.send_message("🎬 **FORMATO CONFIGURADO**: Video MP4 estándar con subtítulo.", chat_id=chat_id)
            else:
                st = "🟢 ACTIVADO" if self.video_mode_always else "🔴 DESACTIVADO"
                fmt = "Videonota Circular (sendVideoNote)" if self.video_delivery_type == "video_note" else "Video Estándar (sendVideo)"
                self.send_message(
                    f"🎬 **ESTADO DEL MODO VIDEO**\n\n"
                    f"• **Respuesta exclusiva en video:** {st}\n"
                    f"• **Formato de entrega:** `{fmt}`\n\n"
                    f"💡 *Comandos disponibles:*\n"
                    f"• `/video on` : Activar video exclusivo\n"
                    f"• `/video off` : Desactivar modo video\n"
                    f"• `/video nota` : Usar videonota redonda\n"
                    f"• `/video estandar` : Usar video MP4 estándar",
                    chat_id=chat_id
                )
            return

        if cmd in ("/modo", "/mode"):
            arg_l = arg_str.lower()
            if "vid" in arg_l:
                self.video_mode_always = True
                self.voice_mode_always = False
                self.config["video_mode_always"] = True
                self.config["voice_mode_always"] = False
                self.save_config()
                self.send_message("🎬 **MODO DE RESPUESTA: VIDEO DEL SISTEMA HABLANDO** (Texto y voz suelta omitidos).", chat_id=chat_id)
            elif "voz" in arg_l or "audio" in arg_l:
                self.video_mode_always = False
                self.voice_mode_always = True
                self.config["video_mode_always"] = False
                self.config["voice_mode_always"] = True
                self.save_config()
                self.send_message("🎙️ **MODO DE RESPUESTA: VOZ NEURAL (CORTANA)**.", chat_id=chat_id)
            elif "txt" in arg_l or "text" in arg_l:
                self.video_mode_always = False
                self.voice_mode_always = False
                self.config["video_mode_always"] = False
                self.config["voice_mode_always"] = False
                self.save_config()
                self.send_message("💬 **MODO DE RESPUESTA: SOLO TEXTO**.", chat_id=chat_id)
            else:
                act = "🎬 Video del Sistema Hablando" if self.video_mode_always else ("🎙️ Voz Neural" if self.voice_mode_always else "💬 Solo Texto")
                self.send_message(
                    f"⚙️ **MODO ACTIVO DE RESPUESTA:** `{act}`\n\n"
                    f"Cambia de modo con:\n"
                    f"• `/modo video` : Responder exclusivamente con video del sistema hablando\n"
                    f"• `/modo voz` : Responder con audio de voz Cortana\n"
                    f"• `/modo texto` : Responder únicamente con texto",
                    chat_id=chat_id
                )
            return

        if any(phrase in text_lower for phrase in ("manda video", "mandame video", "responde con video", "habla en video", "modo video")):
            self.video_mode_always = True
            self.voice_mode_always = False
            self.config["video_mode_always"] = True
            self.config["voice_mode_always"] = False
            self.save_config()
            self.send_reply_with_video("He activado el modo de video exclusivo. A partir de ahora te responderé siempre con un video mío hablando.", chat_id=chat_id)
            return

        if any(phrase in text_lower for phrase in ("solo texto", "desactiva video", "apaga video", "modo texto")):
            self.video_mode_always = False
            self.voice_mode_always = False
            self.config["video_mode_always"] = False
            self.config["voice_mode_always"] = False
            self.save_config()
            self.send_message("💬 He desactivado el modo video. Ahora te responderé únicamente con texto.", chat_id=chat_id)
            return

        if cmd in ("/start", "/help", "/ayuda"):
            help_msg = (
                f"👑 **GODWORKS SYSTEM v26.4 · TELEGRAM SOBERANO**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧠 **Cerebro Central:** {self.active_model_label} [Fijado Indefinido]\n"
                f"💻 **Usuario:** {user_name} (Chat ID: `{chat_id}`)\n\n"
                f"**🎬 Diálogo por Video del Sistema Hablando:**\n"
                f"• `/video <on|off>` : Activar/desactivar respuesta exclusiva en video\n"
                f"• `/video <nota|estandar>` : Conmutar entre videonota circular o video MP4\n"
                f"• `/modo <video|voz|texto>` : Cambiar modo de respuesta del sistema\n\n"
                f"**📞 Diálogo y Llamadas por Voz:**\n"
                f"• `/llamar` o `/call` : Iniciar llamada interactiva por voz con GIA\n"
                f"• `/colgar` o `/endcall` : Finalizar llamada de voz activa\n"
                f"• `/voz_modo <on|off>` : Activar/desactivar respuesta por voz en todos los turnos\n"
                f"• *Notas de Voz:* Envía cualquier nota de voz y GIA te responderá por video o voz hablada.\n\n"
                f"**🎮 Comandos de Control Maestro:**\n"
                f"• `/link` o `/qr` : Enlace web activo y código QR\n"
                f"• `/sh <cmd>` : Ejecutar comando en la terminal Linux\n"
                f"• `/status` : Telemetría completa (CPU, 18GB RAM, GPU, batería, Wi-Fi)\n"
                f"• `/shot` : Tomar captura de pantalla y enviarla aquí\n"
                f"• `/lock` / `/unlock` : Bloquear / Desbloquear pantalla (clave 0)\n"
                f"• `/vol <0-100>` : Ajustar volumen de la laptop\n"
                f"• `/mute` / `/unmute` : Silenciar o activar audio\n"
                f"• `/kbd <0-3>` : Controlar brillo del teclado ASUS TUF\n"
                f"• `/wifi` o `/hotspot` : Red Wi-Fi Soberana TimeMachine (SSID, Clave, Clientes)\n"
                f"• `/auditar` o `/shield` : Auditoría de red, dispositivos, filtro adblock y anti-espionaje\n"
                f"• `/trafico` o `/accesos` : Auditoría de flujos en vivo, quién accede a tus dispositivos y conexiones\n"
                f"• `/recurrentes` o `/frecuentes` : Entidades que reciben tu tráfico recurrentemente y motivo causal\n"
                f"• `/adblock` : Alternar filtro DNS Sinkhole de publicidad\n"
                f"• `/mente` o `/ruido` : Espectrograma 2D de ruido cognitivo y fase de pensamiento\n"
                f"• `/say <texto>` : Síntesis de voz hablada en los altavoces de la PC\n"
                f"• `/reboot` : Reiniciar el equipo para auto-mejora continua\n"
                f"• `/agy` : Estado y arranque de Google Antigravity\n\n"
                f"💬 *También puedes hablarle directamente por audio o escribir cualquier directiva. {self.active_model_label} responderá de inmediato.*"
            )
            self.send_message(help_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/link", "/enlace", "/qr"):
            from omni_temporal_control import BRIDGE
            b_status = BRIDGE.get_status()
            auth_url = b_status.get("auth_url", "")
            local_url = b_status.get("local_url", "")
            perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"

            msg_link = (
                f"🌐 **ENLACE Y ACCESO PERMANENTE A GODWORKS**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 **Enlace Directo del Túnel:**\n{auth_url}\n\n"
                f"🏛️ **Enlace Permanente Invariable (Portal):**\n{perm_url}\n\n"
                f"📶 **Red Local Wi-Fi:**\n`{local_url}`\n\n"
                f"🔑 **Clave Maestra:** `DiosDelTiempo01`"
            )
            self.send_message(msg_link, chat_id=chat_id, reply_to_message_id=msg_id)

            # Generar QR y enviarlo como imagen
            try:
                import qrcode
                qr_img = qrcode.make(auth_url or perm_url)
                buf = io.BytesIO()
                qr_img.save(buf, format="PNG")
                buf.seek(0)
                self.send_photo(buf.getvalue(), caption="📱 Escanea este código QR para abrir el sistema", chat_id=chat_id)
            except Exception as e:
                logger.error(f"Error generando QR: {e}")
            return

        if cmd in ("/sh", "/bash", "/cmd", "/terminal"):
            if not arg_str:
                self.send_message("💻 Especifica el comando a ejecutar. Ejemplo: `/sh uname -a` o `/sh free -h`", chat_id=chat_id)
                return

            from core.os_controller import get_os_controller
            os_c = get_os_controller()
            res = os_c.execute_terminal_command(arg_str, timeout=35.0)

            out = res.get("stdout", "").strip()
            err = res.get("stderr", "").strip()
            rc = res.get("returncode", 0)
            elapsed = res.get("elapsed_s", 0.0)

            body_out = []
            if out:
                body_out.append(out)
            if err:
                body_out.append(f"[stderr]\n{err}")
            res_str = "\n".join(body_out) if body_out else "(Sin salida estándar)"

            # Limitar tamaño para Telegram (máx 4096 caracteres)
            if len(res_str) > 3500:
                res_str = res_str[:3500] + "\n... [Salida truncada]"

            reply = (
                f"💻 **Terminal Linux (`{arg_str}`)**\n"
                f"• Código: `{rc}` | Tiempo: `{elapsed}s`\n"
                f"```\n{res_str}\n```"
            )
            self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/status", "/estado"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            diag = hw.get_full_diagnostic()
            cpu = diag.get("system", {}).get("cpu_percent", 0)
            ram = diag.get("system", {}).get("ram_percent", 0)
            bat = diag.get("battery", {})
            net = diag.get("network", {})
            pwr = diag.get("power_profile", {}).get("active_profile", "performance")

            st_msg = (
                f"🖥️ **DIAGNÓSTICO SOBERANO DEL SISTEMA**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧠 **Modelo:** {self.active_model_label} [Indefinido]\n"
                f"⚡ **CPU / Perfil:** {cpu}% · {pwr.upper()}\n"
                f"💾 **RAM (18 GB Dedicada):** {ram}% en uso\n"
                f"🔋 **Batería:** {bat.get('percent', 100):.1f}% ({bat.get('status', 'Conectado')})\n"
                f"📶 **Red Wi-Fi:** {net.get('active_connection', {}).get('connection', 'Conectado')}\n"
                f"🔒 **Pantalla Bloqueada:** {'SÍ' if diag.get('display', {}).get('locked') else 'NO'}\n"
                f"🚀 **Google Antigravity:** {'ACTIVO' if diag.get('antigravity', {}).get('running') else 'DETENIDO'}"
            )
            self.send_message(st_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/shot", "/screenshot", "/captura"):
            from core.os_controller import get_os_controller
            os_c = get_os_controller()
            res = os_c.capture_screenshot()
            raw_bytes = res.get("raw_bytes")
            if raw_bytes:
                self.send_photo(raw_bytes, caption="📸 Captura de pantalla actual del sistema", chat_id=chat_id)
            else:
                self.send_message("⚠️ No fue posible capturar la pantalla en este momento.", chat_id=chat_id)
            return

        if cmd in ("/lock", "/bloquear"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            hw.dispatch_action("lock_screen")
            self.send_message("🔒 Pantalla y sesión del sistema bloqueadas.", chat_id=chat_id)
            return

        if cmd in ("/unlock", "/desbloquear"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            hw.dispatch_action("unlock_screen", {"password": "0"})
            self.send_message("🔓 Pantalla desbloqueada con éxito (clave: 0).", chat_id=chat_id)
            return

        if cmd in ("/reboot", "/reiniciar"):
            from core.autonomous_controller import get_autonomous_controller
            ac = get_autonomous_controller()
            self.send_message("🔄 Reinicio de optimización programado en 3 segundos. El bot se reconectará y te notificará al arrancar.", chat_id=chat_id)
            ac.reboot_for_improvement(reason="Reinicio ordenado desde Telegram", force=True)
            return

        if cmd in ("/agy", "/antigravity"):
            from core.os_controller import get_os_controller
            os_c = get_os_controller()
            if arg_str in ("start", "open", "iniciar", "abrir"):
                res = os_c.launch_antigravity()
                self.send_message(f"🪐 Antigravity lanzado en pantalla (PID: {res.get('status', {}).get('pids')}).", chat_id=chat_id)
            else:
                res = os_c.get_antigravity_status()
                st_lbl = "🟢 EN EJECUCIÓN" if res.get("running") else "🔴 DETENIDO"
                self.send_message(f"🪐 Google Antigravity: {st_lbl} (PIDs: {res.get('pids')})", chat_id=chat_id)
            return

        if cmd in ("/vol", "/volumen"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            if arg_str:
                try:
                    lvl = int(arg_str)
                    res = hw.set_volume(lvl)
                    self.send_message(f"🔊 Volumen ajustado a {res.get('volume_percent', lvl)}%.", chat_id=chat_id)
                except ValueError:
                    self.send_message("🔊 Usa `/vol <0-100>`. Ejemplo: `/vol 75`", chat_id=chat_id)
            else:
                res = hw.get_volume()
                self.send_message(f"🔊 Volumen actual: {res.get('volume_percent', 0)}% (Mute: {res.get('muted')})", chat_id=chat_id)
            return

        if cmd in ("/mute", "/silencio"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            res = hw.set_mute(True)
            self.send_message("🔇 Audio silenciado.", chat_id=chat_id)
            return

        if cmd in ("/unmute", "/desilenciar"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            res = hw.set_mute(False)
            self.send_message("🔊 Audio activado.", chat_id=chat_id)
            return

        if cmd in ("/kbd", "/teclado"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            if arg_str:
                try:
                    lvl = int(arg_str)
                    res = hw.set_keyboard_brightness(lvl)
                    self.send_message(f"💡 Brillo de teclado ASUS TUF ajustado a nivel {res.get('brightness', lvl)}/3.", chat_id=chat_id)
                except ValueError:
                    self.send_message("💡 Usa `/kbd <0-3>`. Ejemplo: `/kbd 3`", chat_id=chat_id)
            else:
                res = hw.get_keyboard_brightness()
                self.send_message(f"💡 Brillo de teclado actual: nivel {res.get('brightness', 0)}/3.", chat_id=chat_id)
            return

        if cmd in ("/power", "/perfil"):
            from core.hardware_controller import get_hardware_controller
            hw = get_hardware_controller()
            if arg_str in ("performance", "balanced", "power-saver"):
                res = hw.set_power_profile(arg_str)
                self.send_message(f"⚡ Perfil energético establecido a `{arg_str.upper()}`.", chat_id=chat_id)
            else:
                res = hw.get_power_profile()
                self.send_message(f"⚡ Perfil activo: `{res.get('active_profile', 'desconocido')}`. Opciones: `performance`, `balanced`, `power-saver`.", chat_id=chat_id)
            return

        if cmd in ("/say", "/habla", "/voz"):
            if not arg_str:
                self.send_message("🗣️ Usa `/say <texto a pronunciar>`. Ejemplo: `/say Hola Miguel`", chat_id=chat_id)
                return
            try:
                from autonomous_voice import speak_now
                speak_now(arg_str)
                self.send_message(f"🗣️ Voz reproducida en la PC: \"{arg_str}\"", chat_id=chat_id)
            except Exception:
                subprocess.Popen(["espeak", "-v", "es", arg_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.send_message(f"🗣️ Voz sintetizada en la PC: \"{arg_str}\"", chat_id=chat_id)
            return

        if cmd in ("/hotspot", "/wifi_ap", "/ap", "/wifi", "/red"):
            from core.network_controller import get_network_controller
            net = get_network_controller()
            st = net.get_hotspot_status()
            clients_str = ""
            if st.get("clients"):
                c_items = [f"   • `{c['ip']}` ({c['mac']})" for c in st["clients"]]
                clients_str = "\n" + "\n".join(c_items)
            else:
                clients_str = " Ninguno"

            msg = (
                f"📶 **[RED WI-FI SOBERANA · TIMEMACHINE]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **SSID:** `{st['ssid']}`\n"
                f"• **Contraseña:** `{st['raw_password']}`\n"
                f"• **Estado:** {'🟢 ACTIVA 24/7 (Inmune a Caídas)' if st['active'] else '🔴 INACTIVA'}\n"
                f"• **Gateway:** `{st['gateway_ip']}`\n"
                f"• **HUD Local:** `{st['hud_url']}`\n"
                f"• **Clientes Conectados ({st['client_count']}):**{clients_str}\n"
                f"• **Centinela:** `godworks-hotspot.service` (Activo)"
            )
            self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/auditar", "/shield", "/seguridad", "/escanear_red"):
            from core.network_shield import get_network_shield
            shield = get_network_shield()
            audit = shield.audit_network()
            dev_lines = []
            for d in audit.get("devices", []):
                risk = "🚨 Riesgo" if not d.get("is_safe") else "✅ Seguro"
                dev_lines.append(f"   • `{d['ip']}` | {d['hostname']} ({d['vendor']}) [{risk}]")
            dev_str = "\n".join(dev_lines) if dev_lines else "   Ninguno"
            alerts_str = "\n".join([f"   ⚠️ {a}" for a in audit.get("alerts", [])]) or "   ✅ Red blindada sin anomalías"

            msg = (
                f"🛡️ **[ESCUDO SOBERANO · AUDITORÍA DE RED]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Puntuación de Seguridad:** `{audit['security_score']}%` ({audit['grade']})\n"
                f"• **Filtro DNS Sinkhole:** {'🟢 ACTIVO (REDACTED_IP)' if audit['adblock_active'] else '🔴 INACTIVO'}\n"
                f"• **Anti-Espionaje & Telemetría:** {'🟢 ACTIVO' if audit['antispy_active'] else '🔴 INACTIVO'}\n"
                f"• **Dominios Bloqueados:** `{audit['blocked_domains_count']}`\n"
                f"• **Dispositivos Asociados ({audit['devices_count']}):**\n{dev_str}\n\n"
                f"• **Alertas:**\n{alerts_str}\n\n"
                f"• **Causalidad:** {audit['recommendation']}"
            )
            self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/adblock", "/bloquear_anuncios"):
            from core.network_shield import get_network_shield
            shield = get_network_shield()
            if arg_str.lower() in ("off", "0", "desactivar", "apagar"):
                res = shield.toggle_adblock(False)
                state = "🔴 Desactivado"
            else:
                res = shield.toggle_adblock(True)
                state = "🟢 Activado"
            msg = (
                f"🛡️ **Filtro DNS Sinkhole (AdBlock):** {state}\n"
                f"• Dominios bloqueados: `{res.get('blocked_domains_count', 0)}`"
            )
            self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/trafico", "/accesos", "/conexiones", "/flows"):
            from core.traffic_monitor import get_traffic_monitor
            tm = get_traffic_monitor()
            data = tm.analyze_traffic_and_accesses()

            dev_activity = []
            for dev, count in data.get("traffic_summary_by_device", {}).items():
                dev_activity.append(f"   • **{dev}**: `{count}` sesiones activas")
            dev_str = "\n".join(dev_activity) if dev_activity else "   Ninguno"

            inbound_lines = []
            for f in data.get("inbound_accesses", [])[:4]:
                inbound_lines.append(f"   • `{f['src_ip']}` -> `{f['dst_name']}` ({f['service']})")
            inbound_str = "\n".join(inbound_lines) if inbound_lines else "   ✅ Ningún acceso externo no autorizado"

            msg = (
                f"📡 **[AUDITORÍA DE TRÁFICO & ACCESOS A DISPOSITIVOS]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Flujos Totales:** `{data['total_active_flows']}`\n"
                f"• **Accesos Entrantes:** `{data['inbound_access_count']}`\n"
                f"• **Destinos Remotos:** `{data['remote_endpoints_contacted']}`\n\n"
                f"📱 **Actividad por Dispositivo:**\n{dev_str}\n\n"
                f"🛡️ **Accesos Entrantes Inbound:**\n{inbound_str}\n\n"
                f"• **Veredicto:** {data['assessment']}"
            )
            self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/recurrentes", "/frecuentes", "/top_trafico", "/destinos"):
            from core.traffic_monitor import get_traffic_monitor
            rep = get_traffic_monitor().get_recurring_traffic_report()
            self.send_message(rep.get("formatted_report", ""), chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/offline", "/boveda", "/historial_offline", "/chats_offline"):
            from core.offline_chat_vault import get_offline_chat_vault
            vault = get_offline_chat_vault()
            total = vault.get_total_count()
            msg = (
                f"💾 **[BÓVEDA SOBERANA DE CHATS OFFLINE]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Turnos Almacenados Inmutables:** `{total}`\n"
                f"• **Base de Datos Local:** `data/offline_chats.db`\n"
                f"• **Visor Autónomo Fuera de Línea:** Abre directamente `HISTORIAL_CHATS_OFFLINE.html` en el Escritorio de tu PC aún con el servidor apagado.\n"
                f"• **RAG Cognitivo:** {self.active_model_label} consulta este historial antes de formular cada respuesta."
            )
            self.send_message(msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/mente", "/ruido", "/simbolos", "/metacognicion", "/pensamiento", "/spectrogram"):
            from core.thought_noise_engine import get_thought_noise_engine
            engine = get_thought_noise_engine()
            target_prompt = arg_str or "Introspección soberana y análisis de sistemas de pensamiento"
            frame = engine.generate_thought_frame(prompt=target_prompt, model_name=self.active_model_label, active_step="METAPENSAMIENTO BAJO DEMANDA")
            
            caption = (
                f"🧠 **[METAPENSAMIENTO SOBERANO · RUIDO & SÍMBOLOS]**\n"
                f"• **Entropía de Shannon:** `{frame['entropy_shannon']:.2f} bits`\n"
                f"• **Sintropía / Coherencia:** `{frame['syntropy_coherence_pct']}%`\n"
                f"• **Símbolos Activos:** {', '.join(frame['active_symbols'][:4])}\n"
                f"• **Interpretación:** El sistema auto-observa su flujo neural como ruido cuántico estructurado colapsando hacia certidumbre contextual."
            )
            self.send_photo(frame["png_bytes"], caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        # ----------------------------------------------------------------------
        # PROCESAMIENTO CONVERSACIONAL Y ACCIONES DE HARDWARE POR CHAT
        # ----------------------------------------------------------------------
        try:
            from omni_temporal_control import (
                CFG,
                SYNC_HUB,
                process_agentic_chat,
                process_hardware_chat_intent
            )

            # 1. Verificar si es una acción de hardware o sistema
            hw_res = process_hardware_chat_intent(text)
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            is_call_active = (cid_int in self.active_calls) or self.voice_mode_always or is_voice_message

            if hw_res and hw_res.get("executed") and hw_res.get("direct_return"):
                fb = hw_res.get("system_feedback", "Acción ejecutada.")
                if self.video_mode_always:
                    self.send_reply_with_video(fb, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_reply_with_voice(fb, chat_id=chat_id, reply_to_message_id=msg_id)

                # Sincronizar en el Hub Transversal
                SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Video: {self.video_mode_always})")
                SYNC_HUB.add_chat_turn("assistant", fb, meta=f"{self.active_model_label} · Control Soberano")
                return

            # 2. Despachar imagen de ruido cognitivo y símbolos en vivo mientras procesa
            from core.thought_noise_engine import get_thought_noise_engine
            engine = get_thought_noise_engine()
            thought_frame = engine.generate_thought_frame(
                prompt=text,
                model_name=self.active_model_label,
                active_step="INFERENCIA & ANÁLISIS SINTÁCTICO EN VIVO"
            )

            live_caption = (
                f"🧠 **[METAPENSAMIENTO EN VIVO · SISTEMAS EN PROCESO]**\n"
                f"• **Ruido Neural:** Fluctuación cuántica/estocástica ({thought_frame['syntropy_coherence_pct']}% coherencia)\n"
                f"• **Símbolos Activos:** {', '.join(thought_frame['active_symbols'][:3])}\n"
                f"• **Entropía:** `{thought_frame['entropy_shannon']:.2f} bits`\n"
                f"⏳ *{self.active_model_label} procesando colapso de pensamiento...*"
            )
            try:
                self.send_photo(thought_frame["png_bytes"], caption=live_caption, chat_id=chat_id)
            except Exception as pe:
                logger.warning(f"No se pudo enviar foto preliminar de ruido: {pe}")

            # 3. Despachar al núcleo soberano con contexto transversal manteniendo indicador continuo
            action_type = "record_video_note" if self.video_mode_always else ("record_voice" if is_call_active else "typing")
            SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Video: {self.video_mode_always})")

            with ChatActionKeeper(self, chat_id, action_type):
                with SYNC_HUB._lock:
                    chat_hist = [
                        {"role": m["role"], "content": m["content"]}
                        for m in SYNC_HUB.history
                        if m.get("role") in ("user", "assistant") and m.get("content")
                    ]

                resp_chat = process_agentic_chat(
                    message=text,
                    history=chat_hist[-12:],
                    model=os.environ.get("GIA_MODEL", "huihui_ai/llama3.1-8b-instruct-abliterated"),
                    num_ctx=4096,
                    use_web=True
                )

                hermes_reply = resp_chat.get("reply", "Respuesta recibida.").strip()
                SYNC_HUB.add_chat_turn("assistant", hermes_reply, meta=f"{self.active_model_label} · Núcleo Soberano")

                # Si está activado el modo video, enviar exclusivamente video del sistema hablando
                if self.video_mode_always:
                    self.send_reply_with_video(hermes_reply, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_reply_with_voice(hermes_reply, chat_id=chat_id, reply_to_message_id=msg_id)

        except Exception as e:
            logger.error(f"Error procesando mensaje en Telegram: {e}")
            self.send_message(f"⚠️ Error procesando directiva: {e}", chat_id=chat_id)

    # --------------------------------------------------------------------------
    # ESTADO Y DIAGNÓSTICO
    # --------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        running = self.running and bool(self.worker_thread and self.worker_thread.is_alive())
        configured = bool(self.config.get("bot_token"))
        allowed = self.config.get("allowed_chats", [])
        return {
            "ok": True,
            "enabled": bool(self.config.get("enabled")),
            "running": running,
            "polling_active": running,
            "configured": configured,
            "bot_token_configured": configured,
            "bot_username": self.config.get("bot_username", ""),
            "bot_name": self.config.get("bot_name", ""),
            "allowed_chats": allowed,
            "authorized_chat_ids": allowed,
            "allowed_chats_count": len(allowed),
            "authorized_chats_count": len(allowed),
            "admin_chat_id": self.config.get("admin_chat_id"),
            "active_calls": list(self.active_calls),
            "active_calls_count": len(self.active_calls),
            "voice_mode_always": self.voice_mode_always,
            "video_mode_always": self.video_mode_always,
            "video_delivery_type": self.video_delivery_type,
            "messages_processed": self.messages_processed,
            "last_error": self.last_error
        }


# Instancia Global
def get_telegram_bridge() -> TelegramBridge:
    return TelegramBridge.get_instance()
