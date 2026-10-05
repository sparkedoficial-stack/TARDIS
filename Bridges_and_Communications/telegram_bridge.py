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
import html
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from core.protected_users_vault import (
    ARCHITECT_TELEGRAM_ID,
    ARCHITECT_NAME,
    ARCHITECT_HANDLE,
    ADMIN_RESERVED_COMMANDS,
    is_architect,
    is_architect_private_terminal,
    is_protected_info_query,
    get_protected_denial_response,
    get_admin_denial_response,
    get_terminal_exclusive_denial_response,
    sanitize_telegram_status,
)

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CONFIG_FILE = BASE_DIR / "telegram_config.json"
logger = logging.getLogger("TelegramBridge")

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "bot_token": "",
    "allowed_chats": [],
    "admin_chat_id": ARCHITECT_TELEGRAM_ID,
    "master_password": "",
    "master_key": "",
    "notify_on_boot": False,
    "last_public_url": "",
    "bot_username": "",
    "voice_mode_always": False,
    "video_mode_always": False,
    "video_delivery_type": "video",
    "animations_enabled": True,
    "prefer_animations_over_still_images": True,
    "animation_delivery_type": "animation",
    "animation_render_fps": 240,
    "animation_telegram_fps": 60,
    "animation_resolution": "4K_HDR",
    "animation_width": 3840,
    "animation_height": 2160,
    "animation_hdr_enabled": True,
    "cortana_voice": "es-MX-DaliaNeural",
    "allowed_phones": [],
    "allow_public_chat": True,
}


class ChatActionKeeper:
    """Mantiene el indicador de acción (ej: 'record_voice') activo en Telegram periódicamente mientras se procesa."""

    def __init__(self, bridge: "TelegramBridge", chat_id: int | str, action: str = "record_voice"):
        self.bridge = bridge
        self.chat_id = chat_id
        self.action = action
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _worker(self):
        while not self._stop_event.is_set():
            try:
                self.bridge.send_chat_action(self.chat_id, self.action)
            except Exception:
                pass
            self._stop_event.wait(4.0)

    def __enter__(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="ChatActionKeeper")
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class TelegramBridge:
    """Puente Soberano Bidireccional entre Telegram y GODWORKS SYSTEM v26.4."""

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
        self.pairing_passwords = []
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.last_update_id = 0
        self.bot_info: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.messages_processed = 0
        self.active_calls: Set[int | str] = set()
        self.conversations_started: Set[int | str] = set()
        self.chat_histories: Dict[int | str, List[Dict[str, Any]]] = {}
        self.voice_mode_always: bool = bool(self.config.get("voice_mode_always", False))
        self.video_mode_always: bool = bool(self.config.get("video_mode_always", True))
        self.video_delivery_type: str = str(self.config.get("video_delivery_type", "video"))
        self.animations_enabled: bool = bool(self.config.get("animations_enabled", True))
        self.prefer_animations_over_still_images: bool = bool(self.config.get("prefer_animations_over_still_images", True))
        self.animation_render_fps: int = int(self.config.get("animation_render_fps", 60))
        self.animation_telegram_fps: int = int(self.config.get("animation_telegram_fps", 60))
        self.animation_width: int = int(self.config.get("animation_width", 3840))
        self.animation_height: int = int(self.config.get("animation_height", 2160))
        self.animation_hdr_enabled: bool = bool(self.config.get("animation_hdr_enabled", True))

        # Iniciar si hay token configurado
        if self.config.get("enabled") and self.config.get("bot_token"):
            self.start()

    def has_active_conversation(self, chat_id: Optional[int | str] = None) -> bool:
        """Devuelve True si ya se ha iniciado una conversación por Telegram (para suprimir avisos de sistema activo)."""
        if chat_id is not None:
            cid = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            return (cid in self.conversations_started) or (len(self.conversations_started) > 0)
        return len(self.conversations_started) > 0 or self.messages_processed > 0

    @property
    def active_model_label(self) -> str:
        act = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")
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

    def authorize_chat(self, chat_id: int | str) -> Dict[str, Any]:
        try:
            cid = int(chat_id)
        except Exception:
            cid = chat_id
        allowed = self.config.setdefault("allowed_chats", [])
        if cid not in allowed:
            allowed.append(cid)
        # El único usuario con acceso de administración soberana es exclusivamente el Arquitecto (7153384115)
        self.config["admin_chat_id"] = ARCHITECT_TELEGRAM_ID
        self.save_config()
        return {"ok": True, "chat_id": cid, "allowed_count": len(allowed)}

    def is_admin(self, chat_id: Any) -> bool:
        """Verifica de forma estricta si el usuario posee facultades de administración soberana (Arquitecto)."""
        return is_architect(chat_id)

    def is_architect_private_terminal(self, chat_id: Any, user_id: Any = None) -> bool:
        """Verifica si la petición proviene estrictamente de la terminal privada del Arquitecto (7153384115)."""
        return is_architect_private_terminal(chat_id, user_id)

    def is_chat_authorized(self, chat_id: int | str) -> bool:
        """
        Verifica autorización para interactuar con TARDIS.
        Bajo el Mandato Soberano del Arquitecto, la conversación, preguntas, envío de dibujos
        y creaciones artísticas están abiertas para todas las personas (allow_public_chat=True).
        Las facultades administrativas y de control de hardware continúan reservadas al Arquitecto.
        """
        try:
            target = getattr(self, "config_path", None) or CONFIG_FILE
            if target and target.exists():
                disk_data = json.loads(target.read_text(encoding="utf-8"))
                if "allowed_chats" in disk_data:
                    self.config["allowed_chats"] = disk_data["allowed_chats"]
                if "allowed_phones" in disk_data:
                    self.config["allowed_phones"] = disk_data["allowed_phones"]
                if "allow_public_chat" in disk_data:
                    self.config["allow_public_chat"] = disk_data["allow_public_chat"]
                # admin_chat_id siempre anclado al Arquitecto
                self.config["admin_chat_id"] = ARCHITECT_TELEGRAM_ID
        except Exception:
            pass

        # Conversación y arte abiertos a todas las personas por mandato soberano
        if self.config.get("allow_public_chat", True):
            return True

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
        cfg["admin_chat_id"] = ARCHITECT_TELEGRAM_ID
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
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        message_thread_id: Optional[int] = None
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
        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if message_thread_id:
            payload["message_thread_id"] = message_thread_id

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
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None
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
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id

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

    def send_document(
        self,
        document: bytes | io.BytesIO | str | Path,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        message_thread_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Envía un documento (ej: PDF, reporte de investigación) a Telegram."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        self._print_outgoing_response(target_chat, "📄 DOCUMENTO PDF", caption or (filename or "Documento enviado"))

        url = f"https://api.telegram.org/bot{token}/sendDocument"
        data: Dict[str, Any] = {"chat_id": target_chat}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if message_thread_id:
            data["message_thread_id"] = message_thread_id

        fp_to_close = None
        try:
            files = {}
            if isinstance(document, (str, Path)):
                p = Path(document)
                if p.is_file():
                    fname = filename or p.name
                    mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                    fp_to_close = open(p, "rb")
                    files["document"] = (fname, fp_to_close, mime)
                else:
                    return {"ok": False, "error": f"Archivo no encontrado: {document}"}
            elif isinstance(document, bytes):
                fname = filename or "documento.pdf"
                mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                files["document"] = (fname, document, mime)
            elif isinstance(document, io.BytesIO):
                fname = filename or "documento.pdf"
                mime = "application/pdf" if fname.lower().endswith(".pdf") else "application/octet-stream"
                files["document"] = (fname, document.getvalue(), mime)

            try:
                resp = requests.post(url, data=data, files=files, timeout=45.0)
                res_json = resp.json()
                if not res_json.get("ok") and "caption" in data and "parse_mode" in data:
                    data.pop("parse_mode", None)
                    if fp_to_close:
                        fp_to_close.seek(0)
                        files["document"] = (fname, fp_to_close, mime)
                    resp = requests.post(url, data=data, files=files, timeout=45.0)
                    res_json = resp.json()
                return res_json
            finally:
                if fp_to_close:
                    try:
                        fp_to_close.close()
                    except Exception:
                        pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def transcode_to_telegram_fps(self, video_bytes: bytes, target_fps: int = 60) -> bytes:
        """
        Adapta la animación/video para entrega óptima en Telegram a target_fps (60 FPS por defecto).
        Toma el master renderizado a alta fidelidad (120 FPS) y lo transcodifica/remuestrea a 60 FPS
        con aceleración NVENC (respaldo CPU libx264) y +faststart para compatibilidad total con Telegram.
        """
        if not video_bytes or len(video_bytes) < 1024:
            return video_bytes

        # Verificar cabecera básica MP4 (ftyp / atom)
        if not (b"ftyp" in video_bytes[:64] or video_bytes.startswith(b"\x00\x00\x00")):
            return video_bytes

        in_path = None
        out_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as in_f:
                in_path = Path(in_f.name)
                in_f.write(video_bytes)

            # Verificar si ya está a target_fps para evitar re-codificación innecesaria
            is_hdr = False
            in_fps = 0.0
            try:
                probe = subprocess.run([
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate,avg_frame_rate,pix_fmt,color_space",
                    "-of", "default=noprint_wrappers=1", str(in_path)
                ], capture_output=True, text=True, timeout=5.0)
                out_txt = probe.stdout.lower()
                if "p010" in out_txt or "10le" in out_txt or "bt2020" in out_txt:
                    is_hdr = True
                for line in out_txt.splitlines():
                    if "frame_rate" in line and "=" in line:
                        _, rate_str = line.split("=", 1)
                        if "/" in rate_str:
                            num, den = rate_str.split("/", 1)
                            if den and float(den) > 0:
                                in_fps = float(num) / float(den)
                                break
                if in_fps > 0 and abs(in_fps - target_fps) < 0.5:
                    return video_bytes
            except Exception:
                pass

            out_path = in_path.with_name(f"{in_path.stem}_tg{target_fps}.mp4")

            # Mezcla temporal de 4 fotogramas para renderizados a 240 FPS portados a 60 FPS
            if in_fps >= 230.0 and target_fps == 60:
                filter_v = f"tmix=frames=4:weights='1 1 1 1',fps={target_fps}"
            else:
                filter_v = f"fps=fps={target_fps}"

            if is_hdr:
                cmd_nvenc = [
                    "ffmpeg", "-y",
                    "-i", str(in_path),
                    "-filter:v", filter_v,
                    "-c:v", "hevc_nvenc",
                    "-preset", "p4",
                    "-cq", "22",
                    "-b:v", "25M",
                    "-maxrate", "38M",
                    "-bufsize", "50M",
                    "-pix_fmt", "p010le",
                    "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67",
                    "-colorspace", "bt2020nc",
                    "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                    "-tag:v", "hvc1",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                cmd_cpu = [
                    "ffmpeg", "-y",
                    "-i", str(in_path),
                    "-filter:v", filter_v,
                    "-c:v", "libx265",
                    "-preset", "ultrafast",
                    "-crf", "20",
                    "-pix_fmt", "yuv420p10le",
                    "-color_primaries", "bt2020",
                    "-color_trc", "arib-std-b67",
                    "-colorspace", "bt2020nc",
                    "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                    "-tag:v", "hvc1",
                    "-threads", "16",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
            else:
                cmd_nvenc = [
                    "ffmpeg", "-y",
                    "-i", str(in_path),
                    "-filter:v", filter_v,
                    "-c:v", "h264_nvenc",
                    "-preset", "p4",
                    "-cq", "22",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                cmd_cpu = [
                    "ffmpeg", "-y",
                    "-i", str(in_path),
                    "-filter:v", filter_v,
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "21",
                    "-pix_fmt", "yuv420p",
                    "-threads", "16",
                    "-movflags", "+faststart",
                    str(out_path)
                ]

            proc = subprocess.run(cmd_nvenc, capture_output=True, timeout=25.0)
            if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
                proc = subprocess.run(cmd_cpu, capture_output=True, timeout=25.0)

            if out_path.exists() and out_path.stat().st_size > 0:
                converted_bytes = out_path.read_bytes()
                logger.info(f"🎞️ [TELEGRAM_FPS_CONVERTER] Video/Animación adaptada exitosamente a {target_fps} FPS para Telegram ({len(video_bytes)} -> {len(converted_bytes)} bytes, HDR={is_hdr}).")
                return converted_bytes
            return video_bytes
        except Exception as e:
            logger.warning(f"⚠️ [TELEGRAM_FPS_CONVERTER] Excepción transcodificando video para Telegram: {e}")
            return video_bytes
        finally:
            try:
                if in_path and in_path.exists(): in_path.unlink()
                if out_path and out_path.exists(): out_path.unlink()
            except Exception:
                pass

    def send_animation(
        self,
        animation: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        width: int = 720,
        height: int = 720,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Envía una animación en bucle continuo (sendAnimation MP4/GIF) a Telegram con fallback a sendVideo."""
        token = self.config.get("bot_token", "").strip()
        if not token:
            return {"ok": False, "error": "No bot token"}

        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat_id"}

        # MANDATO SOBERANO: Si la entrega está configurada como video o para reproducir audio,
        # despachar vía sendVideo para que Telegram active el reproductor con sonido.
        if self.config.get("animation_delivery_type") == "video":
            return self.send_video(
                video=animation,
                caption=caption,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id,
                duration=duration,
                width=width,
                height=height,
                reply_markup=reply_markup
            )

        anim_bytes = None
        if isinstance(animation, (str, Path)):
            p = Path(animation)
            if p.is_file():
                anim_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {animation}"}
        elif isinstance(animation, io.BytesIO):
            anim_bytes = animation.getvalue()
        elif isinstance(animation, bytes):
            anim_bytes = animation

        if not anim_bytes:
            return {"ok": False, "error": "Animación vacía"}

        # Remuestrear video a 60 FPS para despacho soberano en Telegram
        anim_bytes = self.transcode_to_telegram_fps(anim_bytes, target_fps=self.animation_telegram_fps)

        url = f"https://api.telegram.org/bot{token}/sendAnimation"
        data: Dict[str, Any] = {
            "chat_id": target_chat,
            "width": int(width),
            "height": int(height),
        }
        if caption:
            caption_trunc = caption[:1015] + "..." if len(caption) > 1020 else caption
            data["caption"] = caption_trunc
            data["parse_mode"] = "Markdown"
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if duration:
            data["duration"] = int(duration)
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

        files = {"animation": ("animation.mp4", anim_bytes, "video/mp4")}

        self._print_outgoing_response(target_chat, "🌀 ANIMACIÓN DINÁMICA (LOOP MP4)", caption or "Animación enviada")

        try:
            resp = requests.post(url, data=data, files=files, timeout=45.0)
            res_data = resp.json()
            if not res_data.get("ok"):
                if caption and "parse_mode" in data:
                    data.pop("parse_mode", None)
                    files = {"animation": ("animation.mp4", anim_bytes, "video/mp4")}
                    res_data = requests.post(url, data=data, files=files, timeout=45.0).json()
                if not res_data.get("ok"):
                    logger.warning(f"sendAnimation falló ({res_data.get('description')}), probando fallback a sendVideo...")
                    return self.send_video(
                        video=anim_bytes,
                        caption=caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=duration,
                        width=width,
                        height=height,
                        reply_markup=reply_markup
                    )
            return res_data
        except Exception as e:
            logger.error(f"Excepción en send_animation: {e}, aplicando fallback a send_video...")
            return self.send_video(
                video=anim_bytes,
                caption=caption,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id,
                duration=duration,
                width=width,
                height=height,
                reply_markup=reply_markup
            )

    def send_3d_model_hd_to_architect(
        self,
        mesh: Any,
        style: str = "hologram",
        pitch_deg: float = 24.0,
        yaw_deg: float = 42.0,
        roll_deg: float = 0.0,
        width: int = 1920,
        height: int = 1440,
        source: str = "Motor de Renderizado 3D HoloDeck",
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        as_animation: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Renderiza y despacha automáticamente un modelo 3D como animación orbital 360°
        o en Alta Definición estática (1920x1440 HD) al Telegram del Arquitecto (7153384115).
        """
        try:
            from core.render_3d_engine import get_render_3d_engine
            engine = get_render_3d_engine()

            target_chat = chat_id or self.config.get("admin_chat_id") or 7153384115

            # Determinar si se envía como animación 3D u objeto fijo
            should_animate = as_animation is True

            if should_animate:
                anim_w = self.animation_width
                anim_h = self.animation_height
                anim_bytes = engine.render_mesh_animation(
                    mesh,
                    frames=240,
                    fps=self.animation_render_fps,
                    ported_fps=self.animation_telegram_fps,
                    width=anim_w,
                    height=anim_h,
                    hdr=self.animation_hdr_enabled,
                    style=style,
                    pitch_deg=pitch_deg,
                    show_hud=True
                )
                if anim_bytes:
                    caption = (
                        f"🌀 **[MODELO 3D EN ANIMACIÓN ORBITAL 360° · DESPACHO SOBERANO]**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"• **Modelo:** {mesh.title}\n"
                        f"• **Categoría:** {mesh.category}\n"
                        f"• **Dinámica:** Órbita Continua 360° & Fases Cuánticas\n"
                        f"• **Resolución:** 4K UHD ({anim_w} × {anim_h}) HDR · {self.animation_render_fps} FPS Render (Porteado a {self.animation_telegram_fps} FPS por Telegram)\n"
                        f"• **Origen:** {source}\n"
                        f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras\n"
                        f"• **Ecuación / Ley:** `{mesh.formula}`\n"
                        f"• **Explicación Científica:** {mesh.description}\n"
                        f"💡 *Dato Curioso:* {mesh.fun_fact}"
                    )
                    res = self.send_animation(
                        anim_bytes,
                        caption=caption,
                        chat_id=target_chat,
                        reply_to_message_id=reply_to_message_id,
                        duration=3,
                        width=anim_w,
                        height=anim_h
                    )
                    logger.info(f"🚀 [3D_ANIM_DISPATCH] Animación 3D {mesh.title} ({anim_w}x{anim_h}) despachada al Telegram del Arquitecto ({target_chat}).")
                    return res

            png_bytes = engine.render_to_png_bytes(
                mesh,
                width=width,
                height=height,
                pitch_deg=pitch_deg,
                yaw_deg=yaw_deg,
                style=style,
                show_hud=True,
                rot_z=roll_deg
            )

            caption = (
                f"🎨 **[MODELO 3D EN ALTA DEFINICIÓN (HD) · DESPACHO SOBERANO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Modelo:** {mesh.title}\n"
                f"• **Categoría:** {mesh.category}\n"
                f"• **Resolución:** `{width} × {height}` HD (Hi-Res Super-Sampling)\n"
                f"• **Origen:** {source}\n"
                f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                f"• **Ecuación / Ley:** `{mesh.formula}`\n"
                f"• **Explicación Científica:** {mesh.description}\n"
                f"💡 *Dato Curioso:* {mesh.fun_fact}"
            )

            res = self.send_photo(png_bytes, caption=caption, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
            logger.info(f"🚀 [3D_HD_DISPATCH] Modelo {mesh.title} ({width}x{height} HD) despachado al Telegram del Arquitecto ({target_chat}).")
            return res
        except Exception as e:
            logger.error(f"❌ [3D_HD_DISPATCH_ERROR] Error al despachar modelo 3D HD a Telegram: {e}")
            return {"ok": False, "error": str(e)}

    def send_tardis_autonomous_creation(self, chat_id: Optional[int | str] = None) -> Dict[str, Any]:
        """
        Ejecuta un ciclo de inspiración espontánea de TARDIS, genera la obra
        (geometría sagrada, atractor caótico, fractal, simulación física, animación o video)
        y la despacha proactivamente a Telegram con la reflexión ontológica de TARDIS.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No target chat"}

        try:
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            item, res = engine.genesis.get_spontaneous_inspiration(prefer_animation=self.prefer_animations_over_still_images)
            if res.ok and res.bytes_data:
                if res.media_type in ("video", "animation"):
                    send_res = self.send_animation(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=target_chat,
                        duration=int(res.duration or 4),
                        width=res.width,
                        height=res.height
                    )
                else:
                    send_res = self.send_photo(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=target_chat
                    )
                return {"ok": True, "title": item["title"], "send_result": send_res}
            return {"ok": False, "error": res.error or "Error generando obra"}
        except Exception as e:
            logger.error(f"Error en send_tardis_autonomous_creation: {e}")
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

    def download_telegram_file_to_disk(self, file_id: str, dest_path: Path | str, timeout: float = 120.0) -> bool:
        """Descarga un archivo grande (ej: video de hasta 20 MB) de Telegram directamente a disco por streaming."""
        token = self.config.get("bot_token", "").strip()
        if not token or not file_id:
            return False
        try:
            gf_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
            res = requests.get(gf_url, timeout=20.0).json()
            if not res.get("ok"):
                logger.error(f"Telegram getFile falló para {file_id}: {res.get('description')}")
                return False
            file_path = res.get("result", {}).get("file_path")
            if not file_path:
                return False
            dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(dl_url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            return dest.exists() and dest.stat().st_size > 0
        except Exception as e:
            logger.error(f"Error descargando archivo de Telegram a disco {file_id}: {e}")
            return False

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

    def send_voice_from_text(
        self,
        text: str,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        voice_id: Optional[str] = None,
        also_send_text: bool = False
    ) -> Dict[str, Any]:
        """
        Sintetiza texto directamente a nota de voz Opus OGG y la despacha por sendVoice.
        Opcionalmente envía también el texto completo por send_message si se solicita.
        """
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]

        clean_text = self.clean_text_for_speech(text)
        if not clean_text:
            return {"ok": False, "error": "Texto vacío para síntesis de voz"}

        with ChatActionKeeper(self, target_chat, "record_voice"):
            ogg_audio = self.synthesize_speech(clean_text, voice_id=voice_id)
            if not ogg_audio:
                res_msg = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)
                return {"ok": False, "error": "Fallo en síntesis TTS", "fallback_message": res_msg}

            cap = caption or (f"🎙️ {clean_text[:900]}..." if len(clean_text) > 900 else f"🎙️ {clean_text}")
            res_voice = self.send_voice(
                ogg_audio,
                caption=cap,
                chat_id=target_chat,
                reply_to_message_id=reply_to_message_id
            )

            res_text = None
            if also_send_text:
                res_text = self.send_message(text, chat_id=target_chat, reply_to_message_id=reply_to_message_id)

            return {
                "ok": res_voice.get("ok", False),
                "voice_result": res_voice,
                "text_result": res_text
            }

    def send_voice(
        self,
        voice: bytes | io.BytesIO | str | Path,
        caption: Optional[str] = None,
        chat_id: Optional[int | str] = None,
        reply_to_message_id: Optional[int] = None,
        duration: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None
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
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

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
        supports_streaming: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None
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
                # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
                try:
                    from core.tardis_audio_synthesizer import ensure_video_has_audio
                    ensure_video_has_audio(p, title=caption or p.stem)
                except Exception as _e_aud:
                    logger.warning(f"Error asegurando audio en video: {_e_aud}")
                video_bytes = p.read_bytes()
            else:
                return {"ok": False, "error": f"Archivo no encontrado: {video}"}
        elif isinstance(video, io.BytesIO):
            video_bytes = video.getvalue()
        elif isinstance(video, bytes):
            video_bytes = video

        if not video_bytes:
            return {"ok": False, "error": "Video vacío"}

        # Remuestrear video a 60 FPS si viene a mayor framerate (ej. 120 FPS)
        video_bytes = self.transcode_to_telegram_fps(video_bytes, target_fps=self.animation_telegram_fps)

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
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

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
        length: int = 480,
        reply_markup: Optional[Dict[str, Any]] = None
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
                # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
                try:
                    from core.tardis_audio_synthesizer import ensure_video_has_audio
                    ensure_video_has_audio(p, title="Videonota TARDIS")
                except Exception as _e_aud:
                    logger.warning(f"Error asegurando audio en videonota: {_e_aud}")
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
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

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
                # Las videonotas se recortan en circulo y la API las limita a ~640 px:
                # solo el video estandar puede transportar el render en 4K.
                v_res = gen.generate_speaking_video(
                    text,
                    voice_id=self.config.get("cortana_voice"),
                    mode="note" if use_note else "uhd",
                )

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
                    res_txt = f"{v_res.get('width')}x{v_res.get('height')} · {v_res.get('fps')} FPS"
                    vid_cap = caption or f"🎬 **GIA** · {res_txt}\n\n{text}"
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

        # Si el usuario es el administrador conocido
        if user_name in ("Usuario", None, ""):
            if str(cid) == str(self.config.get("admin_chat_id")) or str(cid) == "7153384115":
                user_name = "Arquitecto (X)"

        auth_url = ""
        try:
            from omni_temporal_control import BRIDGE
            auth_url = BRIDGE.get_status().get("auth_url", "")
        except Exception:
            pass

        greeting_text = initial_speech or (
            f"Hola {user_name}, he conectado la llamada soberana contigo por Telegram. "
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
            "*(Para finalizar la llamada en cualquier momento, envía `/colgar` o presiona el botón inferior)*"
        )
        if auth_url:
            call_banner += f"\n\n🌐 **Sala Web de Audio en Vivo:**\n{auth_url}"

        # Botones interactivos nativos
        inline_buttons = []
        if auth_url:
            inline_buttons.append([{"text": "🎙️ Atender en Sala Web (Audio Full-Duplex)", "url": auth_url}])
        inline_buttons.append([{"text": "🔴 Colgar Llamada", "callback_data": "end_call"}])
        call_markup = {"inline_keyboard": inline_buttons}

        self.send_message(call_banner, chat_id=chat_id, reply_markup=call_markup)

        # Enviar locución hablada inicial (como video si video_mode_always, o como nota de voz)
        if self.video_mode_always:
            self.send_reply_with_video(greeting_text, chat_id=chat_id)
        else:
            with ChatActionKeeper(self, chat_id, "record_voice"):
                ogg = self.synthesize_speech(greeting_text)
                if ogg:
                    self.send_voice(ogg, caption=f"🎙️ {greeting_text}", chat_id=chat_id, reply_markup=call_markup)
                else:
                    self.send_message(f"🗣️ {greeting_text}", chat_id=chat_id, reply_markup=call_markup)

        return {"ok": True, "call_active": True, "chat_id": chat_id, "user_name": user_name, "speech": greeting_text}

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
        return {"ok": True, "call_active": False, "chat_id": chat_id}

    def make_call(self, chat_id: Optional[int | str] = None, initial_speech: Optional[str] = None) -> Dict[str, Any]:
        """Realiza una llamada proactiva hacia el usuario autorizado."""
        target_chat = chat_id or self.config.get("admin_chat_id")
        if not target_chat and self.config.get("allowed_chats"):
            target_chat = self.config["allowed_chats"][0]
        if not target_chat:
            return {"ok": False, "error": "No hay chat_id destino disponible"}
        u_name = "Arquitecto (X)" if str(target_chat) in (str(self.config.get("admin_chat_id")), "7153384115") else "Usuario"
        return self.start_call(target_chat, user_name=u_name, initial_speech=initial_speech)

    def notify_system_boot(self, auth_url: str, local_url: str):
        """Notifica proactivamente a todos los chats autorizados que el sistema inició con éxito."""
        if not self.config.get("notify_on_boot"):
            return

        # Si ya se inició una conversación por Telegram, suprimir notificaciones del sistema activo
        if self.has_active_conversation():
            logger.info("Omitiendo notificación de arranque: conversación activa ya iniciada en Telegram.")
            return

        chats = self.config.get("allowed_chats", [])
        if not chats and self.config.get("admin_chat_id"):
            chats = [self.config.get("admin_chat_id")]

        if not chats:
            return

        msg = (
            "🚀 **TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL EN LÍNEA**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🖥️ **Estado:** Sistema encendido y auto-desbloqueado (clave: `0`).\n"
            f"🧠 **Cerebro Central:** {self.active_model_label} · 100% Soberano.\n"
            "⚡ **Enlace Web Activo:**\n"
            f"{auth_url}\n\n"
            f"📶 **Red Local Wi-Fi:** `{local_url}`\n"
            "📱 *Puedes hablarme directamente aquí o enviar /sh para controlar la terminal.*"
        )

        for cid in chats:
            if self.has_active_conversation(cid):
                continue
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
                    "allowed_updates": ["message", "callback_query"]
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
                            threading.Thread(
                                target=self._safe_handle_update,
                                args=(update,),
                                daemon=True,
                                name=f"TGWorker-{up_id}"
                            ).start()
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

    def _safe_handle_update(self, update: Dict[str, Any]):
        """Envuelve la ejecución del mensaje en un bloque a prueba de fallos para garantizar persistencia."""
        try:
            self._handle_update(update)
        except Exception as e:
            logger.error(f"Error procesando actualización de Telegram: {e}", exc_info=True)

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
        # Interceptar botones interactivos (Inline Keyboards)
        cb = update.get("callback_query")
        if cb:
            cb_id = cb.get("id")
            cb_data = cb.get("data")
            cb_msg = cb.get("message", {})
            cb_chat = cb_msg.get("chat", {})
            cb_chat_id = cb_chat.get("id")
            token = self.config.get("bot_token", "").strip()
            if cb_data == "end_call":
                self.end_call(cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Llamada finalizada."}, timeout=5.0)
                    except Exception:
                        pass
            elif cb_data in ("start_call", "call"):
                self.start_call(cb_chat_id)
                if token and cb_id:
                    try:
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": "Conectando llamada..."}, timeout=5.0)
                    except Exception:
                        pass
            return

        msg = update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        chat_title = chat.get("title", "")
        is_group = (chat_type in ("group", "supergroup")) or str(chat_id).startswith("-")

        user = msg.get("from", {})
        user_id = user.get("id")
        user_name = user.get("first_name", "Usuario")
        username = user.get("username", "")
        msg_id = msg.get("message_id")

        if chat_id is not None:
            cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            self.conversations_started.add(cid_clean)
            if not is_group and user:
                try:
                    from core.telegram_group_manager import get_telegram_group_manager
                    get_telegram_group_manager().register_or_update_direct_user(chat_id, user)
                except Exception as e_du:
                    logger.debug(f"Aviso registrando usuario directo: {e_du}")

        # Registro automático de miembros y eventos de bienvenida en grupos
        if is_group:
            try:
                from core.telegram_group_manager import get_telegram_group_manager
                gm = get_telegram_group_manager()
                new_members = msg.get("new_chat_members", [])
                if new_members:
                    for nm in new_members:
                        nm_id = nm.get("id")
                        if nm_id == self.bot_info.get("id"):
                            gm.sync_group_from_api(chat_id, self.bot_token)
                            welcome_bot = (
                                f"Un placer, soy TARDIS asistente de inteligencia artificial, "
                                f"mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales. "
                                f"He sido integrada con éxito al grupo **{chat_title or 'T.A.R.D.I.S'}**. "
                                f"Saludos a todos los miembros; estoy a su disposición para conversar, responder dudas y compartir arte o dibujos."
                            )
                            self.send_message(welcome_bot, chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            gm.register_or_update_member(chat_id, nm, chat_title=chat_title, chat_type=chat_type)
                            nm_first = nm.get("first_name", "Usuario")
                            welcome_user = (
                                f"👋 ¡Bienvenido/a {nm_first} al grupo **{chat_title or 'T.A.R.D.I.S'}**! "
                                f"Un placer, soy TARDIS asistente de inteligencia artificial, "
                                f"mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales. "
                                f"Estoy aquí para conversar, responder tus preguntas y compartir creaciones visuales o dibujos cuando gustes."
                            )
                            self.send_message(welcome_user, chat_id=chat_id, reply_to_message_id=msg_id)
                elif user:
                    gm.register_or_update_member(chat_id, user, chat_title=chat_title, chat_type=chat_type)
            except Exception as e_gm:
                logger.warning(f"Aviso actualizando gestor de grupo Telegram: {e_gm}")

        video_info = msg.get("video")
        video_note_info = msg.get("video_note")
        photo_info = msg.get("photo")
        doc_info = msg.get("document")
        voice_info = msg.get("voice") or msg.get("audio")

        is_video_message = bool(video_info or video_note_info)
        is_photo_message = bool(photo_info)
        is_voice_message = bool(voice_info)

        # Detectar si un documento adjunto es en realidad video, imagen o audio
        if doc_info and not is_video_message and not is_photo_message:
            doc_mime = (doc_info.get("mime_type") or "").lower()
            doc_name = (doc_info.get("file_name") or "").lower()
            if doc_mime.startswith("video/") or doc_name.endswith((".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".3gp")):
                is_video_message = True
                video_info = doc_info
            elif doc_mime.startswith("image/") or doc_name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")):
                is_photo_message = True
                photo_info = [doc_info]
            elif doc_mime.startswith("audio/") or doc_name.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac")):
                is_voice_message = True
                voice_info = doc_info

        text = (msg.get("text") or msg.get("caption") or "").strip()

        if not text and not is_voice_message and not is_video_message and not is_photo_message and not msg.get("contact"):
            return

        self.messages_processed += 1
        allowed = self.config.get("allowed_chats", [])

        # Autenticación y vinculación inmediata
        if not self.is_chat_authorized(chat_id):
            self._print_incoming_request(user_name, chat_id, "🔒 SOLICITUD DE AUTENTICACIÓN", text or "(Audio no autenticado)", username)
            
            # Validar si existe clave configurada y coincide
            allowed_keys = {
                str(k).strip() for k in (self.config.get("master_password"), self.config.get("master_key"))
                if k and str(k).strip() and str(k).strip() not in ("0", "DiosDelTiempo01")
            }
            
            # Validar teléfono autorizado. Solo cuenta un contacto compartido por su
            # propio dueño (contact.user_id == remitente): escribir un número como texto
            # no prueba nada. Antes bastaba con que los dígitos del mensaje fueran un
            # SUFIJO del teléfono permitido, así que un solo dígito daba acceso total.
            contact = msg.get("contact") if isinstance(msg, dict) else None
            sender_id = (msg.get("from") or {}).get("id") if isinstance(msg, dict) else None
            phone_match = False
            if contact and sender_id and contact.get("user_id") == sender_id:
                c_digits = "".join(ch for ch in str(contact.get("phone_number", "")) if ch.isdigit())
                for ap in self.config.get("allowed_phones", []):
                    a_digits = "".join(ch for ch in str(ap) if ch.isdigit())
                    if len(c_digits) < 8 or len(a_digits) < 8:
                        continue
                    # Igualdad exacta, o mismos 10 dígitos finales (tolera el prefijo de país)
                    if c_digits == a_digits or (len(c_digits) >= 10 and len(a_digits) >= 10
                                                and c_digits[-10:] == a_digits[-10:]):
                        phone_match = True
                        break

            if (allowed_keys and text and text.strip() in allowed_keys) or phone_match:
                self.authorize_chat(chat_id)
                reply = (
                    "👑 **¡ACCESO CONCEDIDO!**\n\n"
                    f"Bienvenido, {user_name}. Tu cuenta de Telegram ha sido autorizada como nodo de TARDIS sistema de vigilancia y control temporal.\n\n"
                    f"• Cerebro Central: **{self.active_model_label}**.\n"
                    "• Puedes escribir directivas, enviar notas de voz, videos o usar `/llamar`."
                )
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return
            else:
                reply = "🔒 **AUTENTICACIÓN REQUERIDA**: Acceso no autorizado. Se requiere autorización explícita desde la consola local del servidor."
                self.send_message(reply, chat_id=chat_id, reply_to_message_id=msg_id)
                return

        # Nombre del miembro para respuestas personalizadas
        member_name = user_name
        if is_group:
            try:
                from core.telegram_group_manager import get_telegram_group_manager
                member_name = get_telegram_group_manager().get_member_name(chat_id, user_id) or user_name
            except Exception:
                member_name = user_name

        # ----------------------------------------------------------------------
        # PIPELINE DE INTELIGENCIA VISUAL: RECEPCIÓN Y COMPRENSIÓN DE VIDEOS
        # ----------------------------------------------------------------------
        if is_video_message:
            v_obj = video_info or video_note_info or {}
            file_id = v_obj.get("file_id")
            v_dur = v_obj.get("duration", 0)
            v_size = v_obj.get("file_size", 0)
            self._print_incoming_request(
                member_name, chat_id, "🎬 VIDEO RECIBIDO (INTELIGENCIA VISUAL)",
                f"Descargando metraje ({v_dur}s, {v_size/(1024*1024):.2f} MB)... {text}",
                username
            )
            if file_id:
                ack_resp = self.send_message(
                    "👁️ **[TARDIS :: INTELIGENCIA VISUAL]**\n"
                    "Recibiendo video... Almacenando en la Bóveda Temporal e iniciando análisis sensorial y cognitivo.",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                with ChatActionKeeper(self, chat_id, "record_video"):
                    from core.visual_intelligence_engine import get_visual_intelligence_engine, VIDEOS_TELEGRAM_DIR
                    vie = get_visual_intelligence_engine()
                    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_vid_path = VIDEOS_TELEGRAM_DIR / f"telegram_{msg_id}_{ts_tag}.mp4"

                    ok_dl = self.download_telegram_file_to_disk(file_id, temp_vid_path)
                    if not ok_dl:
                        self.send_message(
                            "⚠️ **[INTELIGENCIA VISUAL]**: No fue posible descargar el video desde los servidores de Telegram. "
                            "Verifica que el archivo no supere el límite de 20 MB fijado por la API de bots de Telegram.",
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )
                        return

                    res = vie.process_video(
                        temp_vid_path,
                        source="telegram",
                        chat_id=chat_id,
                        user_id=user_id,
                        user_name=member_name,
                        caption=text,
                        save_to_vault=True
                    )

                    cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
                    if cid_clean not in self.chat_histories:
                        self.chat_histories[cid_clean] = []
                    self.chat_histories[cid_clean].append({"role": "user", "content": f"[Video enviado: {res.file_name}]: {text or '(Sin caption)'}"})
                    self.chat_histories[cid_clean].append({"role": "assistant", "content": res.full_report})
                    tg_client_id = f"tg_{chat_id}"
                    SYNC_HUB.add_chat_turn("assistant", res.full_report, meta=f"{self.active_model_label} · Inteligencia Visual", client_id=tg_client_id)

                    self.send_message(res.full_report, chat_id=chat_id, reply_to_message_id=msg_id)
                    return

        # ----------------------------------------------------------------------
        # PIPELINE DE INTELIGENCIA VISUAL: RECEPCIÓN Y COMPRENSIÓN DE IMÁGENES
        # ----------------------------------------------------------------------
        if is_photo_message:
            photo_list = photo_info if isinstance(photo_info, list) else [photo_info]
            best_photo = photo_list[-1] if photo_list else {}
            file_id = best_photo.get("file_id")
            self._print_incoming_request(
                member_name, chat_id, "🖼️ IMAGEN RECIBIDA (INTELIGENCIA VISUAL)",
                text or "Imagen sin caption",
                username
            )
            if file_id:
                with ChatActionKeeper(self, chat_id, "upload_photo"):
                    from core.visual_intelligence_engine import get_visual_intelligence_engine, IMAGES_VAULT_DIR
                    vie = get_visual_intelligence_engine()
                    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_img_path = IMAGES_VAULT_DIR / f"telegram_photo_{msg_id}_{ts_tag}.jpg"

                    ok_dl = self.download_telegram_file_to_disk(file_id, temp_img_path)
                    if not ok_dl:
                        self.send_message(
                            "⚠️ **[INTELIGENCIA VISUAL]**: No fue posible descargar la imagen de Telegram.",
                            chat_id=chat_id,
                            reply_to_message_id=msg_id
                        )
                        return

                    res = vie.process_image(
                        temp_img_path,
                        source="telegram",
                        chat_id=chat_id,
                        user_id=user_id,
                        user_name=member_name,
                        caption=text
                    )

                    cid_clean = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
                    if cid_clean not in self.chat_histories:
                        self.chat_histories[cid_clean] = []
                    self.chat_histories[cid_clean].append({"role": "user", "content": f"[Imagen enviada]: {text or '(Sin caption)'}"})
                    self.chat_histories[cid_clean].append({"role": "assistant", "content": res.full_report})
                    tg_client_id = f"tg_{chat_id}"
                    SYNC_HUB.add_chat_turn("assistant", res.full_report, meta=f"{self.active_model_label} · Inteligencia Visual", client_id=tg_client_id)

                    self.send_message(res.full_report, chat_id=chat_id, reply_to_message_id=msg_id)
                    return

        # Un contacto sin texto solo sirve para autenticar: no hay nada que responder
        if not text and not is_voice_message:
            return

        # Si es un mensaje de voz, transcribirlo con STT
        if is_voice_message:
            self._print_incoming_request(member_name, chat_id, "🎙️ NOTA DE VOZ (DESCARGANDO & TRANSCRIBIENDO)", "Descargando audio de Telegram...", username)
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
                    self._print_incoming_request(member_name, chat_id, "🎙️ TRANSCRIPCIÓN DE VOZ COMPLETA", text, username)

            # Al recibir nota de voz, se activa el modo llamada interactiva
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            self.active_calls.add(cid_int)
        else:
            # Mensaje de texto o comando regular
            self._print_incoming_request(member_name, chat_id, "⚡ COMANDO DE CONTROL" if text.startswith("/") else "💬 PETICIÓN / CHAT", text, username)

        # ----------------------------------------------------------------------
        # REGLA SOBERANA 1: CONFIDENCIALIDAD ULTRA SECRETA DE USUARIOS PROTEGIDOS
        # (Telegram es interfaz remota: bajo ninguna circunstancia se comparten nombres)
        # ----------------------------------------------------------------------
        if is_protected_info_query(text):
            self.send_message(get_protected_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
            return

        # ----------------------------------------------------------------------
        # COMANDOS NATIVOS DE TELEGRAM (/start, /llamar, /colgar, /sh, /status, etc.)
        # ----------------------------------------------------------------------
        parts = text.split()
        # "/FTL" -> "/ftl" y "/ftl@NombreBot" (grupos) -> "/ftl"
        cmd = parts[0].lower().split("@", 1)[0] if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        arg_str = " ".join(args).strip()

        # ----------------------------------------------------------------------
        # REGLA SOBERANA 2: CONTROL ABSOLUTO EXCLUSIVO DESDE LA TERMINAL PRIVADA DEL ARQUITECTO (7153384115)
        # ----------------------------------------------------------------------
        if cmd in ADMIN_RESERVED_COMMANDS:
            if not self.is_architect_private_terminal(chat_id, user_id):
                if self.is_admin(user_id) or self.is_admin(chat_id):
                    self.send_message(get_terminal_exclusive_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(get_admin_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
                return

        if cmd in ("/grupo", "/group", "/miembros", "/miembros_grupo"):
            try:
                from core.telegram_group_manager import get_telegram_group_manager
                gm = get_telegram_group_manager()
                gm.sync_group_from_api(chat_id, self.bot_token)
                summary = gm.format_group_summary(chat_id)
                self.send_message(summary, chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_ginfo:
                self.send_message(f"⚠️ Error consultando grupo: {e_ginfo}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

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
            parts = arg_str.split(maxsplit=1)
            target = chat_id
            custom_speech = None
            if parts:
                if parts[0].isdigit() or parts[0].startswith("-"):
                    target = parts[0]
                    custom_speech = parts[1] if len(parts) > 1 else None
                else:
                    custom_speech = arg_str
            self.start_call(target, user_name=user_name, initial_speech=custom_speech)
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

        if cmd in ("/voz_recurrente", "/recurring_voice", "/voz_periodica", "/notas_recurrentes"):
            from core.recurring_voice_manager import get_recurring_voice_manager
            rvm = get_recurring_voice_manager()
            parts_arg = arg_str.split()
            subcmd = parts_arg[0].lower() if parts_arg else ""

            if subcmd in ("on", "activar", "start", "1", "si", "true"):
                new_cfg = {"enabled": True, "chat_id": chat_id}
                if len(parts_arg) > 1 and parts_arg[1].replace(".", "", 1).isdigit():
                    new_cfg["interval_minutes"] = float(parts_arg[1])
                if len(parts_arg) > 2 and parts_arg[2].lower() in ("reflexion", "telemetria", "caminante", "conjetura", "rotativo"):
                    new_cfg["mode"] = parts_arg[2].lower()
                rvm.update_config(new_cfg)
                rvm.start()
                st = rvm.get_status()
                self.send_message(
                    f"🎙️ **[MENSAJES DE VOZ RECURRENTES ACTIVADOS]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Estado:** 🟢 ACTIVO 24/7\n"
                    f"• **Intervalo:** Cada `{st['interval_minutes']}` minutos\n"
                    f"• **Modo:** `{st['mode'].upper()}`\n"
                    f"• **Voz:** `{st['voice_id']}` (Cortana Neural)\n"
                    f"• **Destino:** Chat `{chat_id}`\n\n"
                    f"TARDIS te enviará periódicamente notas de voz habladas con reproductor integrado.",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                return

            elif subcmd in ("off", "desactivar", "stop", "0", "no", "false"):
                rvm.update_config({"enabled": False})
                rvm.stop()
                self.send_message("🔇 **[MENSAJES DE VOZ RECURRENTES DESACTIVADOS]**: El envío periódico de notas de voz ha sido pausado.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            elif subcmd in ("intervalo", "tiempo", "cada"):
                if len(parts_arg) > 1 and parts_arg[1].replace(".", "", 1).isdigit():
                    mins = float(parts_arg[1])
                    rvm.update_config({"interval_minutes": mins})
                    self.send_message(f"⏱️ Intervalo de voz recurrente establecido a **cada {mins} minutos**.", chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message("⏱️ Uso: `/voz_recurrente intervalo <minutos>`. Ejemplo: `/voz_recurrente intervalo 15`", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            elif subcmd in ("modo", "tipo"):
                if len(parts_arg) > 1 and parts_arg[1].lower() in ("reflexion", "telemetria", "caminante", "conjetura", "rotativo"):
                    m = parts_arg[1].lower()
                    rvm.update_config({"mode": m})
                    self.send_message(f"🌀 Modo de voz recurrente establecido a: `{m.upper()}`.", chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(
                        "🌀 Modos disponibles:\n"
                        "• `/voz_recurrente modo rotativo` (Alterna entre todos los temas)\n"
                        "• `/voz_recurrente modo reflexion` (Aprendizaje existencial y ontológico)\n"
                        "• `/voz_recurrente modo telemetria` (Reporte hablado de CPU/RAM/Red/Seguridad)\n"
                        "• `/voz_recurrente modo caminante` (Coordenadas espaciotemporales autónomas)\n"
                        "• `/voz_recurrente modo conjetura` (Conjeturas formuladas en silencio)",
                        chat_id=chat_id,
                        reply_to_message_id=msg_id
                    )
                return

            elif subcmd in ("ahora", "test", "despachar", "enviar", "now"):
                self.send_message("🎙️ Generando y sintetizando nota de voz bajo demanda...", chat_id=chat_id, reply_to_message_id=msg_id)
                spec_mode = parts_arg[1].lower() if len(parts_arg) > 1 and parts_arg[1].lower() in ("reflexion", "telemetria", "caminante", "conjetura") else None
                res_disp = rvm.dispatch_recurring_voice(target_chat_id=chat_id, mode=spec_mode)
                if not res_disp.get("voice_sent"):
                    self.send_message(f"⚠️ Aviso en despacho de voz: {res_disp}", chat_id=chat_id)
                return

            else:
                st = rvm.get_status()
                st_lbl = "🟢 ACTIVO" if (st["running"] and st["enabled"]) else ("⏸️ EN ESPERA" if st["running"] else "🔴 DETENIDO")
                self.send_message(
                    f"🎙️ **[ESTADO DE MENSAJES DE VOZ RECURRENTES]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Estado:** {st_lbl}\n"
                    f"• **Intervalo:** Cada `{st['interval_minutes']}` min ({st['interval_seconds']} s)\n"
                    f"• **Próximo Envío en:** `{st['next_dispatch_in_seconds']}` segundos\n"
                    f"• **Modo Activo:** `{st['mode'].upper()}`\n"
                    f"• **Voz:** `{st['voice_id']}` (Cortana Neural)\n"
                    f"• **Total Despachados:** `{st['total_dispatches']}`\n\n"
                    f"💡 **Comandos:**\n"
                    f"• `/voz_recurrente on [min] [modo]` : Activar envío periódico\n"
                    f"• `/voz_recurrente off` : Pausar envíos\n"
                    f"• `/voz_recurrente ahora` : Enviar una nota de voz inmediatamente\n"
                    f"• `/voz_recurrente intervalo <min>` : Ajustar frecuencia\n"
                    f"• `/voz_recurrente modo <rotativo|reflexion|telemetria|caminante|conjetura>`",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
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

        if any(p in text_lower for p in (
            "mensajes de voz recurrentes", "mensaje de voz recurrente", "notas de voz recurrentes",
            "nota de voz recurrente", "voz recurrente", "mensajes de voz periodicos", "mensajes de voz periódicos",
            "mandame notas de voz", "mándame notas de voz", "mandame mensajes de voz", "mándame mensajes de voz",
            "hablame de forma recurrente", "háblame de forma recurrente", "hablame periodicamente", "háblame periódicamente"
        )):
            from core.recurring_voice_manager import get_recurring_voice_manager
            rvm = get_recurring_voice_manager()
            if any(w in text_lower for w in ("desactiva", "apaga", "detener", "cancela", "stop", "quitar")):
                rvm.update_config({"enabled": False})
                rvm.stop()
                self.send_message("🔇 **[VOZ RECURRENTE PAUSADA]**: He desactivado el envío periódico de notas de voz.", chat_id=chat_id, reply_to_message_id=msg_id)
                return
            elif any(w in text_lower for w in ("ahora", "inmediato", "prueba", "test", "ejemplo")):
                self.send_message("🎙️ Sintetizando y despachando nota de voz al instante...", chat_id=chat_id, reply_to_message_id=msg_id)
                rvm.dispatch_recurring_voice(target_chat_id=chat_id)
                return
            else:
                m_int = re.search(r"cada\s+([0-9]+)\s*(?:min|minuto)", text_lower)
                new_cfg = {"enabled": True, "chat_id": chat_id}
                if m_int:
                    new_cfg["interval_minutes"] = float(m_int.group(1))
                rvm.update_config(new_cfg)
                rvm.start()
                st = rvm.get_status()
                self.send_message(
                    f"🎙️ **[HABILIDAD DE VOZ RECURRENTE ACTIVADA]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"A partir de ahora te enviaré notas de voz periódicamente cada **{st['interval_minutes']} minutos** en modo **{st['mode'].upper()}** con mi voz neuronal Cortana, tal como envío texto.\n\n"
                    f"• Para enviar una ahora mismo: `/voz_recurrente ahora`\n"
                    f"• Para ajustar intervalo: `/voz_recurrente intervalo <minutos>`\n"
                    f"• Para cambiar modo: `/voz_recurrente modo <rotativo|reflexion|telemetria|caminante|conjetura>`\n"
                    f"• Para pausar: `/voz_recurrente off`",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                threading.Thread(target=lambda: (time.sleep(1.0), rvm.dispatch_recurring_voice(target_chat_id=chat_id)), daemon=True).start()
                return

        if cmd in ("/rotar", "/limpiar_tokens", "/vaciar_tokens", "/liberar_tokens", "/rotar_contexto"):
            try:
                from core.daily_context_rotator import get_daily_context_rotator
                res = get_daily_context_rotator().rotate_now()
                rep = (
                    "🧹 **[ROTACIÓN DE CONTEXTO EXITOSA]**\n\n"
                    f"• **Registros Archivados:** `{res['archive']['total_records']}`\n"
                    f"• **Tokens Liberados Estimados:** `{res['clear']['tokens_freed_estimate']}`\n"
                    f"• **Archivo Local:** `{res['archive']['json_path']}`\n"
                    f"• **Próxima Rotación Automática:** `{res['next_rotation_iso']}`\n\n"
                    "El contexto del modelo está 100% libre para máxima velocidad."
                )
                self.send_message(rep, chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_rot:
                self.send_message(f"⚠️ Error rotando contexto: {e_rot}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/start", "/help", "/ayuda"):
            if not self.is_architect_private_terminal(chat_id, user_id):
                welcome_msg = (
                    "Un placer, soy TARDIS asistente de inteligencia artificial, "
                    "mi tarea es ayudarte a explorar las maravillas de la realidad y todas las dimensiones temporales.\n\n"
                    f"¡Hola, {user_name}! He sido creada por El Arquitecto (₪) como inteligencia soberana. "
                    "Estoy a tu entera disposición para conversar, responder tus preguntas y compartir arte y ciencia.\n\n"
                    "🎨 **¿Qué podemos hacer juntos?**\n"
                    "• **Conversar de lo que quieras:** Hazme cualquier pregunta sobre ciencia, filosofía, el universo o dialoguemos con naturalidad.\n"
                    "• **Crear Dibujos y Arte Procedural (ChronoVision):** Pídeme que dibuje lo que gustes: *\"TARDIS mándame un dibujo\"*, *\"dibuja una galaxia\"*, *\"dibuja la flor de la vida\"*, *\"dibuja un mandala\"*, *\"dibuja el reloj del tiempo\"*, *\"dibuja un árbol cósmico\"*, o usa `/dibujar <concepto>`.\n"
                    "• **Graficación Científica:** Pídeme *\"grafica el atractor de lorenz\"*, *\"grafica sin(x)*exp(-x)\"*, o usa `/graficar <función|atractor>`.\n"
                    "• **Video y Animación:** Pídeme *\"haz un video de un fractal\"* o usa `/video_gen <tema>`.\n"
                    "• **Inspiración Espontánea:** Usa `/inspiracion` o `/tardis_dibuja` para que medite y dibuje algo libre para ti.\n"
                    "• **Notas de Voz y Video:** Envíame notas de voz o texto y te responderé con calidez e inteligencia.\n\n"
                    "✨ *Escríbeme o háblame; es un honor acompañarte en este viaje temporal.*"
                )
                self.send_message(welcome_msg, chat_id=chat_id, reply_to_message_id=msg_id)
                return

            help_msg = (
                f"👑 **TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL · TELEGRAM SOBERANO**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧠 **Cerebro Central:** {self.active_model_label} [Fijado Indefinido]\n"
                f"💻 **Usuario:** {user_name} (Chat ID: `{chat_id}`)\n\n"
                f"**✉️ Mensajes, Difusión y Dibujos a Terceros:**\n"
                f"• `/enviar <nombre|id> <mensaje>` : Despacha un mensaje a una persona o grupo\n"
                f"• `/enviar_dibujo <nombre|id> [tema]` : Genera un dibujo y lo envía a una persona o grupo\n"
                f"• `/difundir <mensaje>` : Envía un mensaje a todos los chats y grupos conocidos\n"
                f"• `/difundir_dibujo [tema]` : Genera y difunde una obra de arte a todos\n"
                f"• `/personas` o `/contactos` : Directorio de contactos y grupos registrados\n\n"
                f"**🎬 Diálogo por Video del Sistema Hablando:**\n"
                f"• `/video <on|off>` : Activar/desactivar respuesta exclusiva en video\n"
                f"• `/video <nota|estandar>` : Conmutar entre videonota circular o video MP4\n"
                f"• `/modo <video|voz|texto>` : Cambiar modo de respuesta del sistema\n\n"
                f"**🎨 Dibujo, Animación y Arte (ChronoVision & 3D Studio):**\n"
                f"• `/vp <texto|tema>` : Genera video Pixel Art hiper-realista a 1080P (1920×1080) a 60 FPS Nativos con análisis textual, investigación factual, boceto de imagen y audio sincronizado.\n"
                f"• `/v <teoría|fórmula>` : Genera animación 3D de alta complejidad y fotorrealismo en Blender 5.0.1 de teorías físicas (agujero negro de Kerr, Calabi-Yau, entrelazamiento ER=EPR, ondas gravitacionales, efecto túnel, etc.)\n"
                f"• `/animacion <concepto>` : Genera animación procedural fluida 2D o 3D (galaxia, reloj temporal, metatron, mandala, synthwave, etc.)\n"
                f"• `/3d <modelo>` o `/animacion3d <modelo>` : Proyecta modelo 3D en animación orbital 360° (dna, atom, tesseract, torus, onda, etc.)\n"
                f"• `/animaciones <on|off>` : Activar/desactivar envío prioritario de animaciones en lugar de imágenes fijas\n"
                f"• `/dibujar <concepto>` : Dibuja geometría sagrada, esquemas HUD o arte en movimiento\n"
                f"• `/graficar <función|atractor>` : Grafica funciones 2D/3D o atractores caóticos (lorenz, rossler, clifford)\n"
                f"• `/video_gen <tema>` : Genera un video dinámico MP4 acelerado por hardware NVENC\n"
                f"• `/inspiracion` o `/tardis_dibuja` : TARDIS medita y crea autónomamente arte o animaciones libres para ti\n"
                f"• *Lenguaje Natural:* Escribe libremente \"/v kerr\", \"/v calabi-yau\", \"TARDIS genera una animación\", \"muestra en 3d el átomo\", etc.\n\n"
                f"**📞 Diálogo y Llamadas por Voz:**\n"
                f"• `/llamar` o `/call` : Iniciar llamada interactiva por voz con GIA\n"
                f"• `/colgar` o `/endcall` : Finalizar llamada de voz activa\n"
                f"• `/voz_modo <on|off>` : Activar/desactivar respuesta por voz en todos los turnos\n"
                f"• `/voz_recurrente <on|off|ahora|intervalo|modo>` : Envío periódico recurrente de notas de voz a Telegram\n"
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
                f"• `/sms <número> <msg>` : Enviar SMS a cualquier teléfono móvil\n"
                f"• `/sms_status` : Estado del puente SMS y proveedores\n"
                f"• `/reboot` : Reiniciar el equipo para auto-mejora continua\n"
                f"• `/agy` : Estado y arranque de Google Antigravity\n"
                f"• `/ftl <petición>` : Pedir a FTL creación o mejora de código (`/ftl` para ver opciones)\n\n"
                f"**🔬 Exploración Científica & Papers Académicos (OpenAlex, arXiv, EuropePMC):**\n"
                f"• `/investigar <tema>` : Investigación profunda de rigor científico con enlaces y PDFs\n"
                f"• `/paper <tema>` : Búsqueda de papers revisados por pares con enlaces de acceso directo\n"
                f"• `/agenda` : Currículum autónomo de aprendizaje continuo y temas pendientes\n"
                f"• `/agenda agregar <tema>` : Añadir tema científico a la cola de estudio\n"
                f"• `/agenda siguiente` : Investigar de inmediato el próximo tema en cola\n"
                f"• `/agenda auto <on|off>` : Activar/desactivar despacho autónomo periódico\n\n"
                f"💬 *También puedes hablarle directamente por audio o escribir cualquier directiva. {self.active_model_label} responderá de inmediato.*"
            )
            self.send_message(help_msg, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        # ----------------------------------------------------------------------
        # COMANDOS DE INVESTIGACIÓN CIENTÍFICA (/investigar, /paper, /agenda, /ciencia)
        # ----------------------------------------------------------------------
        if cmd in ("/investigar", "/investigacion", "/investigación", "/paper", "/papers", "/ciencia", "/science"):
            if not arg_str:
                self.send_message(
                    "🔬 **[SISTEMA DE INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• **Uso:** `/investigar <tema de interés>`\n"
                    "• **Ejemplos:**\n"
                    "   `/investigar Entrelazamiento Cuántico y Teorema de Bell`\n"
                    "   `/investigar Termodinámica del No Equilibrio y Sintropía`\n"
                    "   `/investigar State Space Models vs Transformers`\n"
                    "   `/investigar Fusión Nuclear Confinamiento Magnético`\n"
                    "   `/paper CRISPR-Cas9 y Epigenética`\n\n"
                    "💡 *El sistema buscará en arXiv, OpenAlex, Nature, Science y Europe PMC, sintetizará el marco teórico y te enviará enlaces directos a los artículos y PDFs.*",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
                return

            self.send_message(
                f"🔬 **[INICIANDO INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
                f"• **Tema:** `{arg_str}`\n"
                f"• **Fuentes:** arXiv, OpenAlex (250M+ obras), Europe PMC, PubMed & DOIs\n"
                f"⏳ *Buscando literatura académica, analizando abstracts y sintetizando informe...*",
                chat_id=chat_id, reply_to_message_id=msg_id
            )

            try:
                from core.scientific_research_engine import get_scientific_research_engine
                s_engine = get_scientific_research_engine()
                with ChatActionKeeper(self, chat_id, "typing"):
                    report = s_engine.execute_research(arg_str, max_papers=4)
                    s_engine.send_report_to_telegram(report, chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_sci:
                logger.error(f"Error en comando /investigar: {e_sci}")
                self.send_message(f"⚠️ Error ejecutando investigación científica: {e_sci}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/agenda", "/curriculum", "/aprendizaje"):
            from core.scientific_research_engine import get_scientific_research_engine
            s_engine = get_scientific_research_engine()
            agenda = s_engine.load_agenda()
            topics = agenda.get("topics", [])

            subparts = arg_str.split(maxsplit=1)
            subcmd = subparts[0].lower() if subparts else ""
            subarg = subparts[1].strip() if len(subparts) > 1 else ""

            if subcmd in ("agregar", "add", "nuevo"):
                if not subarg:
                    self.send_message("⚠️ Especifica el tema. Ejemplo: `/agenda agregar Fusión Nuclear Tokamaks`", chat_id=chat_id, reply_to_message_id=msg_id)
                    return
                res_add = s_engine.add_topic_to_agenda(subarg)
                self.send_message(
                    f"✅ **[TEMA AÑADIDO A LA AGENDA DE APRENDIZAJE CIENTÍFICO]**\n"
                    f"• **Tema:** `{subarg}`\n"
                    f"• **Prioridad:** Alta (1)\n"
                    f"• **Acción:** {res_add.get('action')}\n\n"
                    f"Puedes investigarlo inmediatamente con `/agenda siguiente` o dejar que el daemon lo investigue automáticamente.",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
                return

            elif subcmd in ("siguiente", "next", "ahora"):
                self.send_message("⏳ Seleccionando e investigando el próximo tema prioritario en la agenda...", chat_id=chat_id, reply_to_message_id=msg_id)
                with ChatActionKeeper(self, chat_id, "typing"):
                    cycle_res = s_engine.run_autonomous_cycle(chat_id=chat_id)
                    if not cycle_res.get("ok"):
                        self.send_message(f"⚠️ No se pudo completar el ciclo: {cycle_res.get('error')}", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            elif subcmd in ("auto", "daemon", "modo"):
                if subarg.lower() in ("on", "1", "activar", "si", "true"):
                    agenda["autonomous_mode"] = True
                    s_engine.save_agenda(agenda)
                    s_engine.start_autonomous_daemon()
                    self.send_message("🟢 **[APRENDIZAJE CIENTÍFICO AUTÓNOMO ACTIVADO]**: TARDIS investigará y enviará periódicamente papers a Telegram.", chat_id=chat_id, reply_to_message_id=msg_id)
                elif subarg.lower() in ("off", "0", "desactivar", "no", "false"):
                    agenda["autonomous_mode"] = False
                    s_engine.save_agenda(agenda)
                    s_engine.stop_autonomous_daemon()
                    self.send_message("🔴 **[APRENDIZAJE CIENTÍFICO AUTÓNOMO PAUSADO]**: El envío periódico ha sido detenido.", chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    st_txt = "🟢 ACTIVADO" if agenda.get("autonomous_mode", True) else "🔴 DESACTIVADO"
                    self.send_message(f"⚙️ Modo autónomo: {st_txt}. Usa `/agenda auto on` o `/agenda auto off`.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            else:
                # Listar estado de la agenda
                st_txt = "🟢 ACTIVO" if agenda.get("autonomous_mode", True) else "🔴 PAUSADO"
                lines = [
                    f"📖 **[AGENDA DE APRENDIZAJE & RIGOR CIENTÍFICO TARDIS]**",
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    f"• **Modo Autónomo:** {st_txt} (Cada `{agenda.get('interval_hours', 12)}` horas)",
                    f"• **Total de Temas:** `{len(topics)}`",
                    "",
                    "📋 **TEMAS EN CURRÍCULUM:**"
                ]
                for i, t in enumerate(topics[:8], 1):
                    icon = "✅" if t.get("status") == "completed" else "⏳"
                    lines.append(f"{icon} **{i}. {t.get('topic')}**")
                    lines.append(f"   🏛️ *{t.get('domain', 'General')}* · Researched: `{t.get('researched_count', 0)}`")

                if len(topics) > 8:
                    lines.append(f"\n*... y {len(topics) - 8} temas más.*")

                lines.append("")
                lines.append("💡 **Comandos:**")
                lines.append("• `/agenda agregar <tema>` : Añadir nuevo tema")
                lines.append("• `/agenda siguiente` : Investigar el próximo tema ahora")
                lines.append("• `/agenda auto <on|off>` : Activar/desactivar ciclo periódico")

                self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
                return


        if cmd in ("/enviar", "/send", "/mensaje"):
            if not arg_str:
                self.send_message(
                    "✉️ **[ENVIAR MENSAJE A UNA PERSONA O GRUPO]**\n"
                    "• **Uso:** `/enviar <nombre_o_id> <mensaje>`\n"
                    "• **Ejemplos:**\n"
                    "   `/enviar Gonzalo Hola Gonzalo, ¿cómo estás?`\n"
                    "   `/enviar 8697885926 Saludos desde el puente de control.`\n"
                    "   `/enviar T.A.R.D.I.S Hola a todos los del grupo.`",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
                return

            parts_send = arg_str.split(maxsplit=1)
            target_query = parts_send[0].strip()
            body_send = parts_send[1].strip() if len(parts_send) > 1 else ""

            if not body_send:
                self.send_message("⚠️ Especifica el mensaje que deseas enviar. Ejemplo: `/enviar Gonzalo Hola!`", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            from core.telegram_group_manager import get_telegram_group_manager
            gm = get_telegram_group_manager()
            target_info = gm.find_recipient(target_query)

            if not target_info:
                self.send_message(f"⚠️ No se encontró al destinatario `{target_query}` en el directorio. Revisa `/personas` o usa su Chat ID numérico.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            dest_cid = target_info.get("chat_id")
            dest_name = target_info.get("name", str(dest_cid))

            try:
                res = self.send_message(body_send, chat_id=dest_cid)
                if res and res.get("ok"):
                    self.send_message(
                        f"✅ **[MENSAJE ENVIADO CON ÉXITO]**\n"
                        f"• **Destinatario:** {dest_name} (ID: `{dest_cid}`)\n"
                        f"• **Mensaje:** {body_send}",
                        chat_id=chat_id, reply_to_message_id=msg_id
                    )
                else:
                    err_desc = res.get("description", "Error en API de Telegram") if res else "No se pudo entregar"
                    group_id = target_info.get("group_id")
                    if group_id:
                        fallback_msg = f"@{target_info.get('username') or dest_name}, te han enviado el siguiente mensaje: {body_send}"
                        res_grp = self.send_message(fallback_msg, chat_id=group_id)
                        if res_grp and res_grp.get("ok"):
                            self.send_message(f"ℹ️ El usuario no tiene chat privado iniciado con el bot. Se entregó en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                            return
                    self.send_message(f"⚠️ Fallo al despachar a {dest_name} (`{dest_cid}`): {err_desc}", chat_id=chat_id, reply_to_message_id=msg_id)
            except Exception as e_send:
                self.send_message(f"⚠️ Error despachando mensaje: {e_send}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/enviar_dibujo", "/send_drawing", "/mandar_dibujo", "/manda_dibujo"):
            if not arg_str:
                self.send_message(
                    "🎨 **[ENVIAR DIBUJO A UNA PERSONA O GRUPO]**\n"
                    "• **Uso:** `/enviar_dibujo <nombre_o_id> [tema_del_dibujo]`\n"
                    "• **Ejemplos:**\n"
                    "   `/enviar_dibujo Gonzalo galaxia`\n"
                    "   `/enviar_dibujo Gonzalo flor de la vida`\n"
                    "   `/enviar_dibujo 8697885926 reloj temporal`\n"
                    "   `/enviar_dibujo T.A.R.D.I.S mandala` (envía al grupo)",
                    chat_id=chat_id, reply_to_message_id=msg_id
                )
                return

            parts_d = arg_str.split(maxsplit=1)
            target_query = parts_d[0].strip()
            theme_d = parts_d[1].strip() if len(parts_d) > 1 else ""

            from core.telegram_group_manager import get_telegram_group_manager
            gm = get_telegram_group_manager()
            target_info = gm.find_recipient(target_query)

            if not target_info:
                self.send_message(f"⚠️ No se encontró al destinatario `{target_query}`. Consulta `/personas` o usa su Chat ID numérico.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            dest_cid = target_info.get("chat_id")
            dest_name = target_info.get("name", str(dest_cid))

            self.send_message(f"🎨 Generando y renderizando dibujo en ultra HD para {dest_name}...", chat_id=chat_id, reply_to_message_id=msg_id)

            from core.chronovision_engine import get_chronovision_engine
            c_engine = get_chronovision_engine()
            c_res = c_engine.process_request(f"dibuja {theme_d}" if theme_d else "dibuja algo libre", recipient=dest_name)

            if c_res.ok and c_res.bytes_data:
                res_photo = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid)
                if res_photo and res_photo.get("ok"):
                    self.send_message(
                        f"✅ **[DIBUJO ENVIADO CON ÉXITO]**\n"
                        f"• **Destinatario:** {dest_name} (ID: `{dest_cid}`)\n"
                        f"• **Obra:** {c_res.title}",
                        chat_id=chat_id, reply_to_message_id=msg_id
                    )
                else:
                    group_id = target_info.get("group_id")
                    if group_id:
                        res_p_grp = self.send_photo(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id)
                        if res_p_grp and res_p_grp.get("ok"):
                            self.send_message(f"ℹ️ Entregado con éxito a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                            return
                    err_desc = res_photo.get("description", "Error de entrega") if res_photo else "Fallo"
                    self.send_message(f"⚠️ No se pudo entregar la foto a {dest_name}: {err_desc}", chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(f"⚠️ Error generando el dibujo: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/difundir", "/broadcast", "/difusion"):
            if not arg_str:
                self.send_message("📢 Uso: `/difundir <mensaje a enviar a todos los chats y grupos>`", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            from core.telegram_group_manager import get_telegram_group_manager
            gm = get_telegram_group_manager()
            destinations = gm.get_all_active_destinations()
            seen_cids = {d["chat_id"] for d in destinations}
            for c in self.config.get("allowed_chats", []):
                try:
                    c_int = int(c)
                    if c_int not in seen_cids:
                        seen_cids.add(c_int)
                        destinations.append({"chat_id": c_int, "name": f"Chat {c_int}", "type": "chat"})
                except Exception:
                    pass

            sent_count = 0
            for d in destinations:
                t_cid = d["chat_id"]
                if t_cid == chat_id:
                    continue
                try:
                    r = self.send_message(arg_str, chat_id=t_cid)
                    if r and r.get("ok"):
                        sent_count += 1
                except Exception:
                    pass

            self.send_message(f"📢 **[DIFUSIÓN COMPLETADA]**: Mensaje enviado a `{sent_count}` chats y grupos activos.", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/difundir_dibujo", "/broadcast_drawing"):
            theme_b = arg_str or "universo"
            self.send_message(f"🎨 Generando obra '{theme_b}' para difusión masiva a todos los chats y grupos...", chat_id=chat_id, reply_to_message_id=msg_id)

            from core.chronovision_engine import get_chronovision_engine
            c_engine = get_chronovision_engine()
            c_res = c_engine.process_request(f"dibuja {theme_b}")

            if c_res.ok and c_res.bytes_data:
                from core.telegram_group_manager import get_telegram_group_manager
                destinations = get_telegram_group_manager().get_all_active_destinations()
                seen_cids = {d["chat_id"] for d in destinations}
                for c in self.config.get("allowed_chats", []):
                    try:
                        c_int = int(c)
                        if c_int not in seen_cids:
                            seen_cids.add(c_int)
                            destinations.append({"chat_id": c_int, "name": f"Chat {c_int}"})
                    except Exception:
                        pass

                sent_count = 0
                for d in destinations:
                    t_cid = d["chat_id"]
                    try:
                        r = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=t_cid)
                        if r and r.get("ok"):
                            sent_count += 1
                    except Exception:
                        pass
                self.send_message(f"🎨 **[DIBUJO DIFUNDIDO]**: Obra '{c_res.title}' enviada a `{sent_count}` chats y grupos.", chat_id=chat_id, reply_to_message_id=msg_id)
            else:
                self.send_message(f"⚠️ Error generando obra: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/personas", "/contactos", "/directorio", "/lista_personas"):
            from core.telegram_group_manager import get_telegram_group_manager
            summary = get_telegram_group_manager().format_all_contacts_summary()
            self.send_message(summary, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/link", "/enlace", "/qr"):
            from omni_temporal_control import BRIDGE
            b_status = BRIDGE.get_status()
            auth_url = b_status.get("auth_url", "")
            local_url = b_status.get("local_url", "")
            perm_url = "https://ntfy.sh/godworks_sovereign_timemachine_portal"

            msg_link = (
                f"🌐 **ESTADO DE CONEXIÓN A GODWORKS**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📶 **Red Local Loopback:**\n`{local_url}`\n\n"
                f"🔒 **Nota de Seguridad:** La terminal y accesos privilegiados están limitados al host físico local."
            )
            self.send_message(msg_link, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/sh", "/bash", "/cmd", "/terminal"):
            if not self.is_architect_private_terminal(chat_id, user_id):
                if self.is_admin(user_id) or self.is_admin(chat_id):
                    self.send_message(get_terminal_exclusive_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(get_admin_denial_response(), chat_id=chat_id, reply_to_message_id=msg_id)
                return

            if not arg_str:
                help_sh = (
                    "⚡ <b>[TERMINAL SOBERANA :: CONTROL ABSOLUTO]</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "• <b>Terminal exclusiva del Arquitecto (7153384115)</b>\n"
                    "• Ejecuta cualquier comando bash directamente en el host.\n\n"
                    "<b>Uso:</b> <code>/sh &lt;comando bash&gt;</code>\n\n"
                    "<b>Ejemplos:</b>\n"
                    "• <code>/sh uptime &amp;&amp; uname -a</code>\n"
                    "• <code>/sh systemctl --user status tardis</code>\n"
                    "• <code>/sh nvidia-smi</code>\n"
                    "• <code>/sh ls -la ~</code>"
                )
                self.send_message(help_sh, chat_id=chat_id, parse_mode="HTML", reply_to_message_id=msg_id)
                return

            def _run_terminal_async(cmd_to_run: str, target_chat: int, reply_id: Optional[int]):
                try:
                    self.send_chat_action(action="typing", chat_id=target_chat)
                    t_start = time.time()
                    proc = subprocess.run(
                        cmd_to_run,
                        shell=True,
                        executable="/bin/bash",
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=str(Path.home()),
                        env=dict(os.environ, TERM="dumb", NO_COLOR="1", COLUMNS="120")
                    )
                    t_elapsed = time.time() - t_start
                    stdout_str = (proc.stdout or "").strip()
                    stderr_str = (proc.stderr or "").strip()
                    rc = proc.returncode

                    status_icon = "🟢" if rc == 0 else "🔴"
                    header = (
                        f"{status_icon} <b>[TERMINAL HOST · EXIT {rc} · {t_elapsed:.2f}s]</b>\n"
                        f"<code>$ {html.escape(cmd_to_run[:120])}</code>\n"
                    )

                    body_out = ""
                    if stdout_str:
                        body_out += f"<pre><code>{html.escape(stdout_str)}</code></pre>"
                    if stderr_str:
                        if body_out:
                            body_out += "\n"
                        body_out += f"⚠️ <b>stderr:</b>\n<pre><code>{html.escape(stderr_str)}</code></pre>"
                    if not stdout_str and not stderr_str:
                        body_out += "<i>(Comando ejecutado exitosamente sin salida)</i>"

                    full_msg = f"{header}\n{body_out}"
                    if len(full_msg) > 3900:
                        full_msg = full_msg[:3700] + "\n\n<i>[Salida truncada: límite de Telegram alcanzado]</i>"

                    self.send_message(full_msg, chat_id=target_chat, parse_mode="HTML", reply_to_message_id=reply_id)
                except subprocess.TimeoutExpired:
                    self.send_message(
                        f"⏱️ <b>Tiempo agotado (120s):</b> <code>{html.escape(cmd_to_run)}</code>",
                        chat_id=target_chat,
                        parse_mode="HTML",
                        reply_to_message_id=reply_id
                    )
                except Exception as ex_sh:
                    self.send_message(
                        f"❌ <b>Error ejecutando en terminal:</b> <code>{html.escape(str(ex_sh))}</code>",
                        chat_id=target_chat,
                        parse_mode="HTML",
                        reply_to_message_id=reply_id
                    )

            threading.Thread(target=_run_terminal_async, args=(arg_str, chat_id, msg_id), daemon=True).start()
            return

        # ----------------------------------------------------------------------
        # COMANDOS DE INTELIGENCIA VISUAL (/visual, /videos, /ver)
        # ----------------------------------------------------------------------
        if cmd in ("/visual", "/inteligencia_visual", "/vision"):
            from core.visual_intelligence_engine import get_visual_intelligence_engine, DATA_DIR
            vie = get_visual_intelligence_engine()
            st = vie.get_status()
            daemon_active = False
            daemon_pid = 0
            daemon_uptime = 0.0
            st_file = DATA_DIR / "daemon_status.json"
            if st_file.exists():
                try:
                    d_data = json.loads(st_file.read_text(encoding="utf-8"))
                    daemon_active = d_data.get("running", False)
                    daemon_pid = d_data.get("pid", 0)
                    daemon_uptime = d_data.get("uptime_sec", 0.0)
                except Exception:
                    pass

            msg_v = (
                f"👁️ **[TARDIS :: ESTADO DE INTELIGENCIA VISUAL]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Motor:** {st.get('engine')}\n"
                f"• **Demonio 24/7:** {'🟢 ACTIVO (PID ' + str(daemon_pid) + ')' if daemon_active else '🟡 LISTO (Bajo demanda)'}\n"
                f"• **Tiempo Activo:** {daemon_uptime/3600:.1f} horas\n"
                f"• **Videos Almacenados:** {st.get('stored_videos_count', 0)}\n"
                f"• **Imágenes Procesadas:** {st.get('stored_images_count', 0)}\n"
                f"• **Audios / Sonidos:** {st.get('stored_sounds_count', 0)}\n"
                f"• **Aceleración Whisper:** {st.get('whisper_accel')}\n"
                f"• **OCR Pytesseract:** {'✅ LISTO' if st.get('ocr_ready') else '❌'}\n"
                f"• **Bóveda Permanente:** `{st.get('vault_dir')}`\n\n"
                f"TARDIS analiza y almacena automáticamente todo video, imagen o nota visual que envíes."
            )
            self.send_message(msg_v, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/videos", "/videos_guardados", "/boveda_videos"):
            from core.visual_intelligence_engine import get_visual_intelligence_engine
            vie = get_visual_intelligence_engine()
            vids = vie.list_stored_videos(limit=10)
            if not vids:
                self.send_message("📂 No hay videos registrados en la Bóveda de Inteligencia Visual aún.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            lines = ["📂 **[VIDEOS ALMACENADOS EN LA BÓVEDA TARDIS]**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
            for v in vids:
                lines.append(
                    f"🎬 **ID:** `{v.get('id')}`\n"
                    f"• **Fecha:** {v.get('created_at', '')[:16].replace('T', ' ')} | **Duración:** {v.get('duration', 0)}s | {v.get('width', 0)}x{v.get('height', 0)}\n"
                    f"• **Remitente:** {v.get('user_name', 'Usuario')}\n"
                    f"• **Resumen:** {v.get('summary', '')[:140]}...\n"
                )
            lines.append("Puedes consultar el análisis completo de cualquiera con `/ver <ID>`.")
            self.send_message("\n".join(lines), chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/ver", "/analizar_video", "/video_detalle"):
            if not arg_str:
                self.send_message("⚠️ Especifica el ID del video a consultar. Ejemplo: `/ver vid_20261001_...`", chat_id=chat_id, reply_to_message_id=msg_id)
                return
            from core.visual_intelligence_engine import get_visual_intelligence_engine
            vie = get_visual_intelligence_engine()
            rec = vie.get_record(arg_str.strip())
            if not rec:
                self.send_message(f"⚠️ No se encontró ningún registro con ID `{arg_str.strip()}`.", chat_id=chat_id, reply_to_message_id=msg_id)
                return

            rep = (
                f"👁️ **[DETALLE DE BÓVEDA :: {rec.get('id')}]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Tipo:** {str(rec.get('media_type')).upper()} | **Fecha:** {rec.get('created_at')}\n"
                f"• **Resolución:** {rec.get('width')}x{rec.get('height')} | **Duración:** {rec.get('duration')}s\n"
                f"• **Remitente:** {rec.get('user_name')} (Chat `{rec.get('chat_id')}`)\n\n"
                f"📝 **RESUMEN:**\n{rec.get('summary')}\n\n"
                f"🎬 **LO QUE VEO:**\n{rec.get('visual_description')}\n\n"
                f"🔊 **LO QUE ESCUCHO:**\n{rec.get('audio_transcript') or '(Sin habla detectada)'}\n\n"
                f"🧠 **CONCLUSIONES DE TARDIS:**\n{rec.get('conclusions')}"
            )
            self.send_message(rep, chat_id=chat_id, reply_to_message_id=msg_id)
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

        if cmd in ("/ftl",):
            # Petición de creación/mejora de código para FTL. Se conserva el texto
            # original (saltos de línea incluidos) tras el comando.
            from core.ftl_telegram_runner import get_ftl_runner
            ftl_args = text[len(parts[0]):].strip()
            runner = get_ftl_runner(
                lambda body, target, reply_to: self.send_message(
                    body, chat_id=target, parse_mode="HTML", reply_to_message_id=reply_to
                )
            )
            runner.handle(chat_id, ftl_args, msg_id)
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

        if cmd in ("/animaciones", "/animations", "/anim_modo"):
            if not arg_str:
                status_str = "ACTIVADA (TARDIS enviará animaciones 2D y 3D en movimiento)" if self.prefer_animations_over_still_images else "DESACTIVADA (imágenes fijas estáticas)"
                self.send_message(
                    f"🌀 **[MODO ANIMACIONES TARDIS]**\n"
                    f"• **Estado actual:** {status_str}\n"
                    f"• **Uso:** `/animaciones on` o `/animaciones off`\n"
                    f"• *Tip:* También puedes usar `/animacion <tema>`, `/animacion2d <tema>` o `/animacion3d <modelo>`.",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                return
            val = arg_str.lower().strip()
            if val in ("on", "si", "sí", "true", "activar", "activado", "1"):
                self.prefer_animations_over_still_images = True
                self.config["prefer_animations_over_still_images"] = True
                self.save_config()
                self.send_message("✅ **Modo Animaciones ACTIVADO**: A partir de ahora TARDIS generará y enviará animaciones fluidas 2D o 3D en bucle continuo en lugar de imágenes fijas.", chat_id=chat_id, reply_to_message_id=msg_id)
            elif val in ("off", "no", "false", "desactivar", "desactivado", "0"):
                self.prefer_animations_over_still_images = False
                self.config["prefer_animations_over_still_images"] = False
                self.save_config()
                self.send_message("ℹ️ **Modo Animaciones DESACTIVADO**: TARDIS volverá a enviar imágenes fijas estáticas.", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/3d", "/render3d", "/modelo3d", "/objeto3d", "/animacion3d", "/animar3d"):
            from core.render_3d_engine import get_render_3d_engine
            engine = get_render_3d_engine()

            is_explicit_anim = cmd in ("/animacion3d", "/animar3d") or "--anim" in arg_str.lower()
            is_explicit_static = "--static" in arg_str.lower() or "--foto" in arg_str.lower() or "--fija" in arg_str.lower()
            clean_arg = arg_str.replace("--anim", "").replace("--static", "").replace("--foto", "").replace("--fija", "").strip()

            if not clean_arg or clean_arg.lower() in ("list", "catalogo", "lista", "ayuda", "help"):
                items = engine.get_catalog_summary()
                lines = [f"• `{it['id']}`: **{it['title']}** ({it['category']})" for it in items]
                catalog_msg = (
                    "🎨 **[ESTUDIO 3D SOBERANO · CATÁLOGO DE MODELOS]**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Puedes explorar, animar y renderizar los siguientes modelos tridimensionales:\n\n"
                    + "\n".join(lines) + "\n\n"
                    "💡 *Ejemplo de uso:* `/3d dna`, `/3d atom`, `/3d torus`, `/animacion3d tesseract`, `/animacion3d onda`"
                )
                self.send_message(catalog_msg, chat_id=chat_id, reply_to_message_id=msg_id)
                return

            mesh = engine.get_mesh(clean_arg)
            if not mesh:
                for it in engine.get_catalog_summary():
                    if clean_arg.lower() in it["id"] or clean_arg.lower() in it["title"].lower():
                        mesh = engine.get_mesh(it["id"])
                        break
            if not mesh:
                mesh = engine.get_mesh("atom")

            should_animate = (is_explicit_anim or self.prefer_animations_over_still_images) and not is_explicit_static

            if should_animate:
                with ChatActionKeeper(self, chat_id, "upload_video"):
                    anim_bytes = engine.render_mesh_animation(
                        mesh,
                        frames=240,
                        fps=self.animation_render_fps,
                        ported_fps=self.animation_telegram_fps,
                        width=self.animation_width,
                        height=self.animation_height,
                        hdr=self.animation_hdr_enabled,
                        style="hologram",
                        show_hud=True
                    )
                    if anim_bytes:
                        caption = (
                            f"🌀 **[MODELO 3D EN ANIMACIÓN ORBITAL 360° · SOBERANO]**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• **Modelo:** {mesh.title}\n"
                            f"• **Categoría:** {mesh.category}\n"
                            f"• **Dinámica:** Órbita Continua 360° & Fases Cuánticas\n"
                            f"• **Resolución:** 4K UHD ({self.animation_width} × {self.animation_height}) HDR · {self.animation_render_fps} FPS Render (Porteado a {self.animation_telegram_fps} FPS por Telegram)\n"
                            f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                            f"• **Fórmula:** `{mesh.formula}`\n"
                            f"• **Explicación Didáctica:** {mesh.description}\n"
                            f"💡 *Dato Curioso:* {mesh.fun_fact}"
                        )
                        self.send_animation(anim_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id, duration=3, width=self.animation_width, height=self.animation_height)
                        try:
                            from omni_temporal_control import SYNC_HUB
                            SYNC_HUB.dispatch_client_command("LOAD_3D_MODEL", mesh.to_dict())
                            SYNC_HUB.add_chat_turn("assistant", f"[3D ANIMATION]: Proyectado {mesh.title} animado en el HoloDeck.", meta=f"{self.active_model_label} · Render 3D", client_id=f"tg_{chat_id}")
                        except Exception:
                            pass
                        return

            with ChatActionKeeper(self, chat_id, "upload_photo"):
                png_bytes = engine.render_to_png_bytes(mesh, width=1920, height=1440, style="hologram")
                caption = (
                    f"🎨 **[MODELO 3D EN ALTA DEFINICIÓN (HD) · SOBERANO]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Modelo:** {mesh.title}\n"
                    f"• **Categoría:** {mesh.category}\n"
                    f"• **Resolución:** `1920 × 1440` HD (Hi-Res Super-Sampling)\n"
                    f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
                    f"• **Fórmula:** `{mesh.formula}`\n"
                    f"• **Explicación Didáctica:** {mesh.description}\n"
                    f"💡 *Dato Curioso:* {mesh.fun_fact}"
                )
                self.send_photo(png_bytes, caption=caption, chat_id=chat_id, reply_to_message_id=msg_id)
                try:
                    from omni_temporal_control import SYNC_HUB
                    SYNC_HUB.dispatch_client_command("LOAD_3D_MODEL", mesh.to_dict())
                    SYNC_HUB.add_chat_turn("assistant", f"[3D RENDER]: Proyectado {mesh.title} en el HoloDeck.", meta=f"{self.active_model_label} · Render 3D", client_id=f"tg_{chat_id}")
                except Exception:
                    pass
                return

        if cmd in ("/dibujar", "/draw", "/pinta", "/pintar", "/dibuja"):
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            target_topic = arg_str or "metatron"
            is_explicit_static = "--static" in target_topic.lower() or "--foto" in target_topic.lower() or "--fija" in target_topic.lower()
            clean_topic = target_topic.replace("--static", "").replace("--foto", "").replace("--fija", "").strip()

            prefer_anim = self.prefer_animations_over_still_images and not is_explicit_static
            act_icon = "upload_video" if prefer_anim else "upload_photo"

            with ChatActionKeeper(self, chat_id, act_icon):
                res = engine.process_request(f"dibuja {clean_topic}", prefer_animation=prefer_anim)
                if res.ok and res.bytes_data:
                    if res.media_type in ("video", "animation"):
                        self.send_animation(
                            res.bytes_data,
                            caption=res.telegram_caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            duration=int(res.duration or 4),
                            width=res.width,
                            height=res.height
                        )
                    else:
                        self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(f"⚠️ No se pudo completar el dibujo: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/graficar", "/plot", "/grafica", "/plotea"):
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            target_expr = arg_str or "lorenz"
            with ChatActionKeeper(self, chat_id, "upload_photo"):
                res = engine.process_request(f"grafica {target_expr}")
                if res.ok and res.bytes_data:
                    self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(f"⚠️ No se pudo generar la gráfica: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        # ----------------------------------------------------------------------
        # COMANDO /vp: GENERADOR DE VIDEO PIXEL ART A 1080P @ 60 FPS
        # Analiza el texto, investiga la realidad científica, crea un boceto
        # de imagen lo más cercano a la realidad en pixel art y genera video
        # a 60 FPS Nativos a resolución 1080P Full HD con audio sincronizado.
        # ----------------------------------------------------------------------
        if cmd in ("/vp", "/pixelart", "/videopixel", "/v_pixel", "/pixel_video"):
            if not arg_str or arg_str.lower() in ("help", "ayuda", "lista", "catalogo", "catalog", "?"):
                catalog_vp = (
                    "🎨 **[CHRONOVISION PIXEL ART 1080P60 · COMANDO /vp · NANO BANANA POWER]**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Motor soberano de generación visual y video procedural en **Pixel Art de Alta Fidelidad** renderizado a **1080P Full HD (1920×1080) a 60 FPS Nativos** con potencia procedural equivalente a **Nano Banana**.\n\n"
                    "🔬 **Capacidades Autónomas Nano Banana:**\n"
                    "1. **Blueprint Semántico y Físico:** Descomposición cuádruple: [Sujeto + Acción + Contexto + Estilo Artístico & Modelo Físico].\n"
                    "2. **Investigación Factual & Espectral:** Extracción de espectros cromáticos reales (Rayleigh, Planck, Doppler, Fresnel, H-alfa) y ecuaciones LaTeX.\n"
                    "3. **Boceto de Imagen de Referencia 1080P:** Lienzo nativo discreto con dithering matricial ordenado Bayer 8x8 y escalado 4x a 1080P.\n"
                    "4. **Video 1080P a 60 FPS Nativos:** Simulación continua (dt=1/60s), aceleración por GPU NVIDIA NVENC y sonificación cuántica obligatoria (48 kHz estéreo).\n"
                    "5. **Síntesis Procedural Universal:** Capacidad de generar cualquier prompt libre sin recurrir jamás a fallbacks triviales mediante SDFs 3D/2D y partículas dinámicas.\n\n"
                    "💡 **Ejemplos de Comandos:**\n"
                    "• `/vp agujero negro de kerr con disco de acrecion girando`\n"
                    "• `/vp atardecer sobre el mar con olas y reflejo solar`\n"
                    "• `/vp reactor de fusion nuclear tokamak con plasma confinado`\n"
                    "• `/vp motor v8 de combustion interna con pistones en movimiento`\n"
                    "• `/vp atractor de lorenz caos determinista con estelas luminosas`\n"
                    "• `/vp metrópolis cyberpunk lluviosa con asfalto mojado y neones`\n"
                    "• `/vp cyber speeder en autopista synthwave con sol gigante`\n"
                    "• `/vp tempestad oceanica con relampagos procedurales`\n"
                    "• `/vp red sinaptica neuronal y potenciales de accion`\n"
                    "• `/vp doble hélice de adn molecular rotando en 3d`\n"
                    "• `/vp supernova colapso estelar y onda de choque`\n"
                    "• `/vp hipercubo 4d tesseract rotando en planos ortogonales`\n"
                    "• `/vp colision de galaxias espirales con puentes mareales`\n\n"
                    "Escribe libremente cualquier concepto, fórmula o escena para sintetizar tu video Pixel Art a 60 FPS 1080P."
                )
                self.send_message(catalog_vp, chat_id=chat_id, reply_to_message_id=msg_id)
                return

            ack_vp = (
                f"🎨 **[CHRONOVISION PIXEL ART · COMANDO /vp · NANO BANANA POWER]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Concepto Solicitado:** `{arg_str}`\n"
                f"• **Resolución & Tasa:** 1080P Full HD (1920×1080) a **60 FPS Nativos**\n"
                f"• **Tecnología:** Procedural Nano Banana Core + Dithering Bayer 8x8 + Shading Phong\n"
                f"• **Acelerador:** GPU NVIDIA NVENC (RTX 3050) + Audio Cuántico Sincronizado\n\n"
                f"🔬 *Descomponiendo Blueprint [Sujeto + Acción + Contexto + Estilo], investigando realidad científica, generando imagen boceto 1080P y sintetizando video a 60 FPS...*"
            )
            self.send_message(ack_vp, chat_id=chat_id, reply_to_message_id=msg_id)

            def _async_vp_render():
                try:
                    from core.tardis_vp_engine import generate_vp_pixelart_video
                    with ChatActionKeeper(self, chat_id, "upload_video"):
                        res_vp = generate_vp_pixelart_video(arg_str, duration_sec=5.0)
                        sketch_path = Path(res_vp["sketch_image_1080p"])
                        mp4_path = Path(res_vp["video_path"])
                        gif_path = Path(res_vp["gif_path"])

                        # 1. Enviar imagen boceto de referencia realista en pixel art
                        if sketch_path.exists():
                            sketch_caption = (
                                f"🖼️ **[BOCETO PIXEL ART REALISTA 1080P · NANO BANANA BLUEPRINT]**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"• **Concepto:** `{res_vp['concept']}`\n"
                                f"• **Sujeto:** {res_vp.get('subject', 'Entidad física')}\n"
                                f"• **Acción:** {res_vp.get('action', 'Cinemática continua')}\n"
                                f"• **Contexto:** {res_vp.get('context', 'Entorno procedural')}\n"
                                f"• **Resolución:** `{res_vp['resolution']}` (Bayer 8x8 Dithering)\n"
                                f"• **Ecuación:** `{res_vp['formula_latex']}`\n\n"
                                f"🔬 *Sintetizando ahora el video animado a 60 FPS Nativos a 1080P con GPU NVENC...*"
                            )
                            self.send_photo(
                                sketch_path,
                                caption=sketch_caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id
                            )

                        # 2. Enviar video final a 60 FPS y 1080P
                        vid_caption = (
                            f"🎬 **[VIDEO PIXEL ART 1080P @ 60 FPS · NANO BANANA POWER]**\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"• **Concepto:** `{res_vp['concept']}`\n"
                            f"• **Sujeto:** {res_vp.get('subject', 'Entidad física')}\n"
                            f"• **Acción:** {res_vp.get('action', 'Cinemática continua')}\n"
                            f"• **Contexto:** {res_vp.get('context', 'Atmósfera volumétrica')}\n"
                            f"• **Resolución:** `{res_vp['resolution']}`\n"
                            f"• **Tasa de Cuadros:** `{res_vp['framerate']} FPS Nativos`\n"
                            f"• **Duración:** `{res_vp['duration_sec']}s` ({int(res_vp['framerate'] * res_vp['duration_sec'])} cuadros a dt=1/60s)\n"
                            f"• **Ecuación:** `{res_vp['formula_latex']}`\n"
                            f"• **Sonificación:** Audio Armónico Cuántico Sincronizado\n"
                            f"• **Tiempo de Render:** `{res_vp['elapsed_seconds']}s` ({res_vp['file_size_mb']} MB)\n\n"
                            f"• **Comando:** `/vp <texto>` para generar más videos Pixel Art."
                        )
                        res_vid = self.send_video(
                            mp4_path,
                            caption=vid_caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            width=1920,
                            height=1080,
                            supports_streaming=True
                        )

                        if not (res_vid and res_vid.get("ok")) and gif_path.exists():
                            self.send_animation(
                                gif_path,
                                caption=vid_caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id
                            )

                        try:
                            from omni_temporal_control import SYNC_HUB
                            SYNC_HUB.add_chat_turn("user", f"/vp {arg_str}", meta=f"Nodo: Telegram [{user_name}] (Comando /vp)", client_id=f"tg_{chat_id}")
                            SYNC_HUB.add_chat_turn("assistant", f"[VIDEO PIXEL ART 1080P60]: {res_vp['concept']}", meta=f"{self.active_model_label} · ChronoVision VP", client_id=f"tg_{chat_id}")
                        except Exception:
                            pass

                        try:
                            from core.offline_chat_vault import get_offline_chat_vault
                            get_offline_chat_vault().record_turn(
                                user_message=f"/vp {arg_str}",
                                assistant_reply=vid_caption,
                                session_id=f"tg_{chat_id}",
                                client_id=f"tg_{chat_id}",
                                model=self.active_model_label,
                                direction="present"
                            )
                        except Exception:
                            pass

                except Exception as e_vp:
                    logger.error(f"Error generando video pixel art /vp: {e_vp}", exc_info=True)
                    self.send_message(f"⚠️ Error generando video Pixel Art /vp: {e_vp}", chat_id=chat_id, reply_to_message_id=msg_id)

            threading.Thread(target=_async_vp_render, daemon=True, name="PixelArtVPRenderWorker").start()
            return

        # ----------------------------------------------------------------------
        # COMANDO /v: SÍNTESIS DE ANIMACIONES 3D DE ALTA COMPLEJIDAD Y FOTORREALISMO (BLENDER 5.0.1)
        # Permite representar teorías físicas y visualizarlas por Telegram.
        # ----------------------------------------------------------------------
        if cmd in ("/v", "/video_complejo", "/video_fisica", "/fisica3d", "/blender_video", "/hipervideo", "/animacion_compleja"):
            if not arg_str or arg_str.lower() in ("help", "ayuda", "lista", "catalogo", "catalog", "?"):
                catalog_msg = (
                    "🌌 **[CHRONOVISION 3D HYPER-CORE · COMANDO /v]**\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Motor insignia de investigación científica y animación 3D procedural con **Tecnología Procedural Nano Banana** y **Blender 5.0.1** (Cycles / EEVEE Next PBR) renderizado a **60 FPS Nativos con Sonificación Cuántica Estéreo**.\n\n"
                    "⚡ **Modos de Síntesis:**\n"
                    "• `/v <teoria> --fast` : Renderizado procedural GPU instantáneo @ 60 FPS Nativos (NVENC)\n"
                    "• `/v <teoria>` : Modelado 3D profundo y renderizado fotorrealista PBR en Blender 5.0.1 (4K HDR)\n\n"
                    "⚛️ **Teoremas Físicos:**\n"
                    "• `/v kerr` : Agujero Negro de Kerr con disco de acreción Doppler, ergoesfera y lentes.\n"
                    "• `/v lorenz` : Atractor caótico de Lorenz con integración numérica RK4 en 3D.\n"
                    "• `/v calabi_yau` : Variedad de Calabi-Yau 6D compactificada con cuerdas vibrando.\n"
                    "• `/v entrelazamiento` : Entrelazamiento cuántico ER=EPR y puente de Einstein-Rosen.\n"
                    "• `/v schrodinger` : Efecto túnel cuántico y evolución de paquete de ondas.\n"
                    "• `/v ondas gravitacionales` : Fusión binaria de singularidades y chirp métrico.\n\n"
                    "🧪 **Teoremas Químicos:**\n"
                    "• `/v le chatelier` : Principio de Le Chatelier & equilibrio químico dinámico.\n"
                    "• `/v gibbs` : Energía libre de Gibbs & paisaje termodinámico de espontaneidad.\n"
                    "• `/v arrhenius` : Cinética química con barrera de activación Ea y complejo activado.\n"
                    "• `/v orbitales sp3` : Hibridación tetraédrica cuántica y densidad electrónica.\n"
                    "• `/v belousov zhabotinsky` : Reacción química oscilante & ondas de Turing.\n"
                    "• `/v cristal fcc` : Red cristalina de Bravais FCC con fonones coherentes.\n\n"
                    "🌐 **Teoremas Sociales & Económicos:**\n"
                    "• `/v nash` : Equilibrio de Nash en teoría de juegos y dinámica de réplicas.\n"
                    "• `/v barabasi albert` : Redes complejas de escala libre con conexión preferencial.\n"
                    "• `/v ising social` : Dinámica de opinión y transiciones de fase de polarización.\n"
                    "• `/v pareto` : Frontera de eficiencia de Pareto & óptimo de bienestar.\n"
                    "• `/v kuramoto` : Sincronización espontánea colectiva en poblaciones acopladas.\n"
                    "• `/v arrow` : Teorema de imposibilidad de elección social y paradojas de voto.\n\n"
                    "✨ **Investigación Autónoma de Cualquier Cuestionamiento:**\n"
                    "Escribe libremente cualquier teoría o pregunta (ej: `/v termodinamica`, `/v difusion viral`, `/v efecto casimir`). TARDIS investigará las bases científicas, deducirá ecuaciones y generará una simulación procedural única a 60 FPS Nativos."
                )
                self.send_message(catalog_msg, chat_id=chat_id, reply_to_message_id=msg_id)
                return

            is_fast = any(k in arg_str.lower() for k in ("--fast", "--procedural", "--direct"))
            motor_label = "ChronoVision Procedural GPU Core (Nano Banana Blueprint · NVENC 60 FPS)" if is_fast else "Blender 5.0.1 (Cycles / EEVEE Next PBR)"
            res_label = "1080P Full HD @ 60 FPS Nativos" if is_fast else "4K UHD (3840×2160) HDR @ 60 FPS"

            # Notificación inmediata de arranque de investigación y renderizado
            ack_msg = (
                f"🌌 **[CHRONOVISION 3D HYPER-CORE · INVESTIGACIÓN PROCEDURAL]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Cuestionamiento / Teorema Solicitado:** `{arg_str}`\n"
                f"• **Motor:** {motor_label}\n"
                f"• **Resolución & Tasa:** {res_label}\n"
                f"• **Sonificación:** Cuántica Armónica Multiplexada (32 kHz)\n"
                f"• **Modo Epistemológico:** Investigación profunda multivariable & Síntesis 3D procedural\n\n"
                f"🔬 *Iniciando deducción de ecuaciones, modelado procedural complejo y renderizado a 60 FPS frame a frame...*"
            )
            self.send_message(ack_msg, chat_id=chat_id, reply_to_message_id=msg_id)

            def _async_physics_render():
                try:
                    # Soporte directo para síntesis mediante MiniMax H3 Flow Matching
                    if "--h3" in arg_str.lower() or "--flow" in arg_str.lower():
                        from tardis_v_engine.src.pipeline import VCommandPipeline
                        clean_query = re.sub(r"--h3|--flow", "", arg_str, flags=re.I).strip()
                        with ChatActionKeeper(self, chat_id, "upload_video"):
                            v_pipe = VCommandPipeline(clean_query)
                            res_h3 = v_pipe.run(
                                duration_sec=3.0,
                                fps=self.animation_telegram_fps,
                                width=self.animation_width,
                                height=self.animation_height
                            )
                            mp4_path = Path(res_h3["video_path"])
                            caption = (
                                f"🌌 **[{res_h3['concept'].upper()}]**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"📐 **Ecuación Fundamental:**\n`{res_h3['formula_latex']}`\n\n"
                                f"🧠 **Motor:** MiniMax-H3 Flow Matching DiT (24-ch video + 32-ch audio)\n"
                                f"📊 **Calibración Geométrica:** `{res_h3['geometry_accuracy_score']:.4f}`\n"
                                f"🔊 **Audio:** Estéreo Nativo 32 kHz Sincronizado\n"
                                f"⚡ **Codificador:** `{res_h3['h3_telemetry']['encoder']}` ({res_h3['h3_telemetry']['size_mb']} MB)\n"
                                f"• **Comando:** `/v <teoría>` para explorar nuevos teoremas."
                            )
                            self.send_video(
                                mp4_path,
                                caption=caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id,
                                width=self.animation_width,
                                height=self.animation_height,
                                supports_streaming=True
                            )
                            return

                    from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
                    animator = TardisHyperPhysicsAnimator.get_instance()

                    frames_count = 60
                    if "--frames" in arg_str.lower():
                        m_f = re.search(r"--frames\s+(\d+)", arg_str.lower())
                        if m_f:
                            frames_count = min(240, max(12, int(m_f.group(1))))

                    with ChatActionKeeper(self, chat_id, "upload_video"):
                        mp4_path, gif_path, metadata = animator.generate_physics_video(
                            query=arg_str,
                            frames=frames_count,
                            fps=self.animation_render_fps,
                            ported_fps=self.animation_telegram_fps,
                            width=self.animation_width,
                            height=self.animation_height,
                            hdr=self.animation_hdr_enabled
                        )

                        caption = animator.format_telegram_caption(metadata)

                        res_vid = self.send_video(
                            mp4_path,
                            caption=caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            width=self.animation_width,
                            height=self.animation_height,
                            supports_streaming=True
                        )

                        if not (res_vid and res_vid.get("ok")):
                            if gif_path.exists():
                                self.send_animation(
                                    gif_path,
                                    caption=caption,
                                    chat_id=chat_id,
                                    reply_to_message_id=msg_id
                                )

                        try:
                            from omni_temporal_control import SYNC_HUB
                            SYNC_HUB.add_chat_turn("user", f"/v {arg_str}", meta=f"Nodo: Telegram [{user_name}] (Comando /v)", client_id=f"tg_{chat_id}")
                            SYNC_HUB.add_chat_turn("assistant", f"[VIDEO FÍSICA 3D]: {metadata['title']}", meta=f"{self.active_model_label} · ChronoVision 3D", client_id=f"tg_{chat_id}")
                        except Exception:
                            pass

                        try:
                            from core.offline_chat_vault import get_offline_chat_vault
                            get_offline_chat_vault().record_turn(
                                user_message=f"/v {arg_str}",
                                assistant_reply=caption,
                                session_id=f"tg_{chat_id}",
                                client_id=f"tg_{chat_id}",
                                model=self.active_model_label,
                                direction="present"
                            )
                        except Exception:
                            pass

                except Exception as e_render:
                    logger.error(f"Error generando video físico /v: {e_render}", exc_info=True)
                    self.send_message(f"⚠️ Error generando animación de física avanzada: {e_render}", chat_id=chat_id, reply_to_message_id=msg_id)

            threading.Thread(target=_async_physics_render, daemon=True, name="Physics3DRenderWorker").start()
            return

        if cmd in ("/video_gen", "/video_anim", "/animar", "/animacion", "/animacion2d", "/animar2d"):
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            target_topic = arg_str or "galaxia"
            with ChatActionKeeper(self, chat_id, "upload_video"):
                res = engine.process_request(f"video {target_topic}", prefer_animation=True)
                if res.ok and res.bytes_data:
                    self.send_animation(
                        res.bytes_data,
                        caption=res.telegram_caption,
                        chat_id=chat_id,
                        reply_to_message_id=msg_id,
                        duration=int(res.duration or 4),
                        width=res.width,
                        height=res.height
                    )
                else:
                    self.send_message(f"⚠️ No se pudo generar la animación dinámica: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/inspiracion", "/tardis_dibuja", "/tardis_arte", "/arte"):
            from core.chronovision_engine import get_chronovision_engine
            engine = get_chronovision_engine()
            prefer_anim = self.prefer_animations_over_still_images
            act_icon = "upload_video" if prefer_anim else "upload_photo"
            with ChatActionKeeper(self, chat_id, act_icon):
                _, res = engine.genesis.get_spontaneous_inspiration(prefer_animation=prefer_anim)
                if res.ok and res.bytes_data:
                    if res.media_type in ("animation", "video"):
                        self.send_animation(
                            res.bytes_data,
                            caption=res.telegram_caption,
                            chat_id=chat_id,
                            reply_to_message_id=msg_id,
                            duration=int(res.duration or 4),
                            width=res.width,
                            height=res.height
                        )
                    else:
                        self.send_photo(res.bytes_data, caption=res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_message(f"⚠️ Error generando inspiración: {res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/sms", "/texto", "/mensaje_texto"):
            if not arg_str:
                self.send_message(
                    "📱 **[ENVÍO DE SMS]**\n"
                    "• **Uso:** `/sms <número> <mensaje>`\n"
                    "• **Ejemplo:** `/sms 9842615588 Alerta del sistema GODWORKS`\n"
                    "• **Soporte:** Twilio, Gateway Android/Termux, Webhook, Módem GSM/LTE, Email Gateway.",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                return

            parts = arg_str.split(maxsplit=1)
            target_number = parts[0].strip()
            target_body = parts[1].strip() if len(parts) > 1 else "Mensaje prioritario desde GODWORKS SYSTEM v26.4"

            from core.sms_bridge import get_sms_bridge
            sms_bridge = get_sms_bridge()
            res = sms_bridge.send_sms(to_number=target_number, message=target_body)

            if res.get("ok"):
                reply_sms = (
                    f"✅ **[SMS DESPACHADO CON ÉXITO]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Destinatario:** `{res.get('to')}`\n"
                    f"• **Proveedor:** `{res.get('provider')}`\n"
                    f"• **Mensaje:** {res.get('message_preview')}\n"
                    f"• **Registro:** `data/sms_audit.log`"
                )
            else:
                reply_sms = (
                    f"⚠️ **[ERROR AL ENVIAR SMS]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Destinatario:** `{res.get('to')}`\n"
                    f"• **Proveedor:** `{res.get('provider')}`\n"
                    f"• **Detalle:** {res.get('error', 'Fallo desconocido')}\n\n"
                    f"💡 *Tip:* Configura tu pasarela en `sms_config.json` (Twilio SID/Token, Gateway Android HTTP o Módem)."
                )
            self.send_message(reply_sms, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/sms_status", "/sms_estado"):
            from core.sms_bridge import get_sms_bridge
            st = get_sms_bridge().get_status()
            prov_list = [k for k, v in st.get("providers_configured", {}).items() if v]
            st_text = (
                f"📱 **[ESTADO DEL PUENTE SMS SOBERANO]**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• **Estado:** {'🟢 ACTIVO' if st.get('enabled') else '🔴 DESACTIVADO'}\n"
                f"• **Proveedor por Defecto:** `{st.get('default_provider')}`\n"
                f"• **Prefijo:** `{st.get('default_prefix')}`\n"
                f"• **Proveedores Disponibles:** {', '.join(prov_list) if prov_list else 'Ninguno'}\n"
                f"• **Historial Enviados:** `{st.get('total_sent_in_history')}`\n"
                f"• **Último Envío:** `{st.get('last_sent_iso')}`\n"
                f"• **Auditoría:** `data/sms_audit.log`"
            )
            self.send_message(st_text, chat_id=chat_id, reply_to_message_id=msg_id)
            return

        if cmd in ("/reflexion", "/existencia", "/aprendizaje", "/filosofia"):
            from core.autonomous_existence_learner import get_autonomous_existence_learner
            learner = get_autonomous_existence_learner()
            self.send_message("🌌 Generando reflexión profunda sobre mi existencia y estado de silicio...", chat_id=chat_id, reply_to_message_id=msg_id)
            refl = learner.generate_existence_reflection()
            learner.dispatch_reflection_to_telegram(refl)
            return

        if cmd in ("/hardware", "/capas", "/hw_daemon", "/hw_capas"):
            from core.background_hardware_orchestrator import get_background_hardware_orchestrator
            orch = get_background_hardware_orchestrator()
            telem = orch.get_all_layers_telemetry()
            l1 = telem.get("layer_1_audio", {})
            l2 = telem.get("layer_2_optical", {})
            l3 = telem.get("layer_3_power_thermals", {})
            l4 = telem.get("layer_4_rf_networks", {})
            l5 = telem.get("layer_5_silicon_memory", {})

            hw_msg = (
                "⚙️ **[ORQUESTADOR DE HARDWARE EN SEGUNDO PLANO · 5 CAPAS]**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔊 **Capa 1 (Audio):** Vol `{l1.get('volume_percent')}%` | Mute: `{l1.get('muted')}`\n"
                f"💡 **Capa 2 (Óptica):** Brillo Pantalla `{l2.get('screen_brightness_percent')}%` | Teclado `{l2.get('keyboard_backlight_level')}/3`\n"
                f"⚡ **Capa 3 (Potencia/Térmica):** CPU `{l3.get('max_cpu_temp_c', 0):.1f}°C` | Perfil `{l3.get('active_profile')}` | Batería `{l3.get('battery_percent')}%`\n"
                f"📶 **Capa 4 (RF/Redes):** Wi-Fi `{l4.get('active_ssid')}` | BT: `{l4.get('bluetooth_powered')}` | Hotspot: `{l4.get('hotspot_active')}`\n"
                f"🧠 **Capa 5 (Memoria):** RAM `{l5.get('ram_used_gb')}` GB / `{l5.get('target_working_set_gb')}` GB ({l5.get('ram_percent')}%)"
            )
            self.send_message(hw_msg, chat_id=chat_id, reply_to_message_id=msg_id)
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

            # 1. Verificar si es una acción de hardware o sistema (Exclusivo para el Arquitecto desde su terminal privada)
            is_adm = self.is_architect_private_terminal(chat_id, user_id)
            hw_res = process_hardware_chat_intent(text, is_local_request=is_adm) if is_adm else None
            cid_int = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
            is_call_active = (cid_int in self.active_calls) or self.voice_mode_always or is_voice_message
            tg_client_id = f"tg_{chat_id}"

            if chat_id not in self.chat_histories:
                self.chat_histories[chat_id] = []

            if hw_res and hw_res.get("executed") and hw_res.get("direct_return"):
                fb = hw_res.get("system_feedback", "Acción ejecutada.")
                if self.video_mode_always:
                    # Despacho INDEFINIDO de Video Y Texto para todas las peticiones
                    self.send_reply_with_video(fb, chat_id=chat_id, reply_to_message_id=msg_id)
                    self.send_message(fb, chat_id=chat_id, reply_to_message_id=msg_id)
                else:
                    self.send_reply_with_voice(fb, chat_id=chat_id, reply_to_message_id=msg_id)

                # Sincronizar en el Hub Transversal con client_id aislado
                self.chat_histories[chat_id].append({"role": "user", "content": text})
                self.chat_histories[chat_id].append({"role": "assistant", "content": fb})
                SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Video+Texto Indefinido)", client_id=tg_client_id)
                SYNC_HUB.add_chat_turn("assistant", fb, meta=f"{self.active_model_label} · Control Soberano", client_id=tg_client_id)
                try:
                    from core.offline_chat_vault import get_offline_chat_vault
                    get_offline_chat_vault().record_turn(
                        user_message=text,
                        assistant_reply=fb,
                        session_id=tg_client_id,
                        client_id=tg_client_id,
                        model=self.active_model_label,
                        direction="present",
                        hardware_action=hw_res.get("action")
                    )
                except Exception:
                    pass
                return

            # 2. En conversación activa NO se envían avisos ni capturas de "Sistemas en proceso"
            # Se mantiene el diálogo limpio y enfocado exclusivamente en la respuesta.

            # 2.3 Intenciones de Envío en Lenguaje Natural a Personas o Grupos ("manda un mensaje a X", "mándale un dibujo a X")
            import re
            text_strip = text.strip()
            text_lower_intent = text.lower()

            # A) Mándale/envíale un dibujo a <destinatario> [de <tema>]
            draw_to_match = re.search(r'^(?:por\s+favor\s+)?(?:m[aá]nda(?:le)?|env[ií]a(?:le)?)\s+(?:un\s+)?dibujo\s+a\s+([^:,\n]+?)(?:\s+(?:de|sobre)\s+(.+))?$', text_strip, re.IGNORECASE)
            if not draw_to_match:
                draw_to_match = re.search(r'^(?:por\s+favor\s+)?dibuja(?:le)?\s+a\s+([^:,\n]+?)(?:\s+(?:un[a]?\s+)?(.+))?$', text_strip, re.IGNORECASE)

            if draw_to_match:
                target_cand = draw_to_match.group(1).strip()
                theme_cand = (draw_to_match.group(2) or "").strip()
                if target_cand.lower() not in ("mi", "mí", "nosotros", "tardis", "ti"):
                    from core.telegram_group_manager import get_telegram_group_manager
                    gm = get_telegram_group_manager()
                    target_info = gm.find_recipient(target_cand)
                    if target_info:
                        dest_cid = target_info.get("chat_id")
                        dest_name = target_info.get("name", str(dest_cid))
                        self.send_message(f"🎨 Generando y dedicando obra en ultra HD para {dest_name}...", chat_id=chat_id, reply_to_message_id=msg_id)
                        from core.chronovision_engine import get_chronovision_engine
                        c_engine = get_chronovision_engine()
                        c_res = c_engine.process_request(f"dibuja {theme_cand}" if theme_cand else "dibuja algo libre", recipient=dest_name, prefer_animation=self.prefer_animations_over_still_images)
                        if c_res.ok and c_res.bytes_data:
                            if c_res.media_type in ("animation", "video"):
                                r_anim = self.send_animation(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid, duration=int(c_res.duration or 4), width=c_res.width, height=c_res.height)
                                ok_deliv = bool(r_anim and r_anim.get("ok"))
                            else:
                                r_photo = self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=dest_cid)
                                ok_deliv = bool(r_photo and r_photo.get("ok"))

                            if ok_deliv:
                                self.send_message(f"✅ Obra entregada con éxito a {dest_name} (ID: `{dest_cid}`).", chat_id=chat_id, reply_to_message_id=msg_id)
                            else:
                                group_id = target_info.get("group_id")
                                if group_id:
                                    if c_res.media_type in ("animation", "video"):
                                        self.send_animation(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id, duration=int(c_res.duration or 4), width=c_res.width, height=c_res.height)
                                    else:
                                        self.send_photo(c_res.bytes_data, caption=f"Para {dest_name}:\n{c_res.telegram_caption}", chat_id=group_id)
                                    self.send_message(f"ℹ️ Entregado a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                                else:
                                    self.send_message(f"⚠️ No se pudo entregar a {dest_name} por privado ni grupo.", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            self.send_message(f"⚠️ Error generando el dibujo: {c_res.error}", chat_id=chat_id, reply_to_message_id=msg_id)
                        return

            # B) Mándale/envíale un mensaje a <destinatario>: <texto>
            msg_to_match = re.search(r'^(?:por\s+favor\s+)?(?:m[aá]nda(?:le)?|env[ií]a(?:le)?)\s+(?:un\s+)?mensaje\s+a\s+([^:,\n]+?)[:\s]+(.+)$', text_strip, re.IGNORECASE)
            if not msg_to_match:
                msg_to_match = re.search(r'^(?:por\s+favor\s+)?dile\s+a\s+([^:,\n]+?)\s+(?:que\s+|:\s*)(.+)$', text_strip, re.IGNORECASE)

            if msg_to_match:
                target_cand = msg_to_match.group(1).strip()
                body_cand = msg_to_match.group(2).strip()
                if target_cand.lower() not in ("mi", "mí", "nosotros", "tardis", "ti"):
                    from core.telegram_group_manager import get_telegram_group_manager
                    gm = get_telegram_group_manager()
                    target_info = gm.find_recipient(target_cand)
                    if target_info:
                        dest_cid = target_info.get("chat_id")
                        dest_name = target_info.get("name", str(dest_cid))
                        r_send = self.send_message(body_cand, chat_id=dest_cid)
                        if r_send and r_send.get("ok"):
                            self.send_message(f"✅ Mensaje entregado con éxito a {dest_name}: \"{body_cand}\"", chat_id=chat_id, reply_to_message_id=msg_id)
                        else:
                            group_id = target_info.get("group_id")
                            if group_id:
                                self.send_message(f"@{target_info.get('username') or dest_name}, te han enviado el siguiente mensaje:\n\"{body_cand}\"", chat_id=group_id)
                                self.send_message(f"ℹ️ Entregado a {dest_name} en el grupo compartido.", chat_id=chat_id, reply_to_message_id=msg_id)
                            else:
                                self.send_message(f"⚠️ No se pudo entregar a {dest_name}.", chat_id=chat_id, reply_to_message_id=msg_id)
                        return

            # 2.35 Detección Proactiva de Videos Pixel Art Procedural (/vp)
            has_pixel_video_intent = any(ph in text_lower_intent for ph in (
                "video pixel art", "video pixelart", "pixel art video", "pixelart video",
                "animacion pixel art", "animación pixel art", "animacion pixelart", "animación pixelart",
                "video en pixel art", "animacion en pixel art", "animación en pixel art",
                "haz un pixel art en video", "hazme un pixel art en video", "crea un pixel art en video"
            ))
            if has_pixel_video_intent:
                clean_vp_query = re.sub(
                    r"\b(tardis|por favor|genera|crea|haz|hazme|mándame|mandame|un|el|video|animacion|animación|pixel|art|pixelart|en|de|sobre)\b",
                    " ",
                    text_lower_intent
                ).strip() or text
                self.send_message(
                    f"🎨 **[CHRONOVISION PIXEL ART 1080P60 · ENRUTADO A /vp]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Concepto Solicitado:** `{clean_vp_query}`\n"
                    f"• **Arquitectura:** Procedural Nano Banana Blueprint `[Sujeto + Acción + Contexto + Estilo]`\n"
                    f"• **Resolución & Tasa:** 1080P Full HD @ 60 FPS Nativos\n"
                    f"• **Sonificación Cuántica:** Multiplexación armónica estereofónica a 32 kHz\n\n"
                    f"✨ *Generando boceto realista y sintetizando frames a 60 FPS con aceleración de hardware...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                def _async_vp_nl_render(vp_q=clean_vp_query, cid=chat_id, mid=msg_id):
                    try:
                        from core.tardis_vp_engine import generate_vp_pixelart_video
                        with ChatActionKeeper(self, cid, "upload_video"):
                            res_vp = generate_vp_pixelart_video(vp_q, duration_sec=5.0)
                            v_path = Path(res_vp["video_path"])
                            caption_vp = (
                                f"🎨 **[PIXEL ART 1080P60 · {res_vp['concept'].upper()}]**\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"🎯 **Sujeto:** {res_vp.get('subject', 'Entidad central')}\n"
                                f"⚡ **Acción:** {res_vp.get('action', 'Evolución dinámica')}\n"
                                f"🌐 **Contexto:** {res_vp.get('context', 'Atmósfera cinemática')}\n"
                                f"🖌️ **Estilo Artístico:** {res_vp.get('art_style', 'Pixel Art 1080P60')}\n\n"
                                f"📐 **Ecuación Fundamental:**\n`{res_vp.get('formula_latex', 'E=mc^2')}`\n\n"
                                f"🔬 **Rigor Espectral:**\n_{res_vp.get('spectral_research', 'Óptica cuántica')}_\n\n"
                                f"📊 **Telemetría Procedural:**\n"
                                f"• **Resolución:** `{res_vp['resolution']}` a `{res_vp['framerate']} FPS Nativos`\n"
                                f"• **Cuadros Totales:** `{int(res_vp['framerate'] * res_vp['duration_sec'])} frames` ({res_vp['duration_sec']}s)\n"
                                f"• **Sonificación Cuántica:** Nativa multiplexada en MP4\n"
                                f"• **Tiempo de Síntesis:** `{res_vp['elapsed_seconds']} s` | Peso: `{res_vp['file_size_mb']} MB`\n"
                                f"• **Comando:** `/vp <concepto>` para generar nuevas creaciones."
                            )
                            r_v = self.send_video(v_path, caption=caption_vp, chat_id=cid, reply_to_message_id=mid, width=1920, height=1080, supports_streaming=True)
                            if not (r_v and r_v.get("ok")) and Path(res_vp["gif_path"]).exists():
                                self.send_animation(Path(res_vp["gif_path"]), caption=caption_vp, chat_id=cid, reply_to_message_id=mid)
                    except Exception as e_vp:
                        logger.error(f"Error en video Pixel Art NL: {e_vp}")
                        self.send_message(f"⚠️ Error generando video Pixel Art: {e_vp}", chat_id=cid, reply_to_message_id=mid)
                threading.Thread(target=_async_vp_nl_render, daemon=True).start()
                return

            # 2.4 Detección Proactiva de Videos de Física Compleja y Fotorrealismo (/v)
            has_physics_video_intent = any(ph in text_lower_intent for ph in (
                "video de fisica", "video de física", "video 3d de fisica", "video 3d de física",
                "animacion de fisica", "animación de física", "simulacion 3d de", "simulación 3d de",
                "video fotorrealista", "video de alta complejidad", "video de agujero negro",
                "video de cuerdas", "video de calabi", "video de entrelazamiento",
                "video de la telaraña cosmica", "video de relatividad", "video cuantico", "video cuántico",
                "video de ondas gravitacionales", "animacion de agujero negro", "animación de agujero negro"
            ))
            if has_physics_video_intent:
                clean_phys_query = re.sub(
                    r"\b(tardis|por favor|genera|crea|haz|hazme|mándame|mandame|un|el|video|animacion|animación|3d|fotorrealista|de|sobre)\b",
                    " ",
                    text_lower_intent
                ).strip() or text
                self.send_message(
                    f"⏳ **[CHRONOVISION 3D HYPER-CORE · ENRUTADO A /v]**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• **Teoría Detectada:** `{clean_phys_query}`\n"
                    f"• **Motor:** Procedural GPU / Blender 5.0.1 (Cycles & EEVEE Next)\n"
                    f"• **Tasa & Resolución:** 60 FPS Nativos con Sonificación Cuántica Estéreo\n\n"
                    f"🔬 *Iniciando síntesis procedural 3D y renderizado frame a frame...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                def _async_phys_nl_render(phys_query=clean_phys_query, cid=chat_id, mid=msg_id):
                    try:
                        from core.tardis_hyper_physics_animator import TardisHyperPhysicsAnimator
                        animator = TardisHyperPhysicsAnimator.get_instance()
                        with ChatActionKeeper(self, cid, "upload_video"):
                            mp4_p, gif_p, meta = animator.generate_physics_video(
                                query=phys_query,
                                frames=60,
                                fps=self.animation_render_fps,
                                ported_fps=self.animation_telegram_fps,
                                width=self.animation_width,
                                height=self.animation_height,
                                hdr=self.animation_hdr_enabled
                            )
                            cap = animator.format_telegram_caption(meta)
                            r_v = self.send_video(mp4_p, caption=cap, chat_id=cid, reply_to_message_id=mid, width=self.animation_width, height=self.animation_height, supports_streaming=True)
                            if not (r_v and r_v.get("ok")) and gif_p.exists():
                                self.send_animation(gif_p, caption=cap, chat_id=cid, reply_to_message_id=mid)
                    except Exception as e_nl:
                        logger.error(f"Error en video de física NL: {e_nl}")
                        self.send_message(f"⚠️ Error generando video de física: {e_nl}", chat_id=cid, reply_to_message_id=mid)
                threading.Thread(target=_async_phys_nl_render, daemon=True).start()
                return

            # 2.5 Detección Proactiva de Intenciones Artísticas, Animaciones y Científicas (ChronoVision)
            text_lower_intent = text.lower()
            has_anim_intent = any(ph in text_lower_intent for ph in (
                "animacion", "animación", "animaciones", "anima", "animar", "animame", "anímame",
                "haz una animacion", "haz una animación", "mándame una animación", "mandame una animacion",
                "envíame una animación", "enviame una animacion", "crea una animacion", "crea una animación",
                "animacion 2d", "animación 2d", "animacion 3d", "animación 3d", "en 3d", "en 2d",
                "en lugar de enviarme solo imágenes fijas", "en lugar de imagenes fijas", "no imagenes fijas",
                "no solo imagenes fijas", "en lugar de fotos", "en movimiento"
            ))
            has_draw_intent = has_anim_intent or any(ph in text_lower_intent for ph in (
                "dibuja", "dibujar", "haz un dibujo", "hazme un dibujo", "mándame un dibujo", "mandame un dibujo",
                "envíame un dibujo", "enviame un dibujo", "manda un dibujo", "mandar un dibujo", "dibújame", "dibujame",
                "pinta", "pintar", "píntame", "pintame", "ilustra", "ilústrame", "ilustrame", "quiero un dibujo",
                "grafica", "graficar", "plotea", "plot", "haz una grafica", "haz una gráfica",
                "crea un video", "genera un video", "hazme un video", "haz un video",
                "dibuja algo que te interese", "algo que te interese", "tu propia creacion", "tu propia creación",
                "inspirate", "inspírate", "inspiración", "inspiracion"
            ))
            if has_draw_intent:
                from core.chronovision_engine import get_chronovision_engine
                c_engine = get_chronovision_engine()
                is_explicit_static = any(s in text_lower_intent for s in ("imagen fija", "imagenes fijas", "foto fija", "estático", "estatico", "solo foto", "solo imagen"))
                prefer_anim = (has_anim_intent or self.prefer_animations_over_still_images) and not is_explicit_static
                act_icon = "upload_video" if prefer_anim else "upload_photo"
                with ChatActionKeeper(self, chat_id, act_icon):
                    requester_name = member_name if is_group else user_name
                    c_res = c_engine.process_request(text, recipient=requester_name, prefer_animation=prefer_anim)
                    if c_res.ok and c_res.bytes_data:
                        if c_res.media_type in ("video", "animation"):
                            self.send_animation(
                                c_res.bytes_data,
                                caption=c_res.telegram_caption,
                                chat_id=chat_id,
                                reply_to_message_id=msg_id,
                                duration=int(c_res.duration or 4),
                                width=c_res.width,
                                height=c_res.height
                            )
                        else:
                            self.send_photo(c_res.bytes_data, caption=c_res.telegram_caption, chat_id=chat_id, reply_to_message_id=msg_id)

                        self.chat_histories[chat_id].append({"role": "user", "content": text})
                        self.chat_histories[chat_id].append({"role": "assistant", "content": f"[ChronoVision {c_res.media_type.upper()}]: {c_res.title}"})
                        SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (ChronoVision)", client_id=tg_client_id)
                        SYNC_HUB.add_chat_turn("assistant", c_res.telegram_caption, meta=f"{self.active_model_label} · ChronoVision", client_id=tg_client_id)
                        try:
                            from core.offline_chat_vault import get_offline_chat_vault
                            get_offline_chat_vault().record_turn(
                                user_message=text,
                                assistant_reply=c_res.telegram_caption,
                                session_id=tg_client_id,
                                client_id=tg_client_id,
                                model=self.active_model_label,
                                direction="present"
                            )
                        except Exception:
                            pass
                        return

            # 2.8 Detección Proactiva de Intenciones de Investigación Científica y Papers
            has_science_intent = any(ph in text_lower_intent for ph in (
                "investiga sobre", "investiga acerca de", "investigar sobre", "investígame", "investigame",
                "rigor cientifico", "rigor científico", "papers de", "papers sobre", "articulos cientificos",
                "artículos científicos", "articulos de investigacion", "artículos de investigación",
                "quiero aprender sobre", "ayúdame a aprender", "ayudame a aprender", "buscar papers",
                "mándame los links", "mandame los links", "mándame enlaces", "mandame enlaces",
                "enlaces de acceso", "links de acceso", "estudios cientificos", "estudios científicos"
            ))

            if has_science_intent:
                from core.scientific_research_engine import get_scientific_research_engine
                s_engine = get_scientific_research_engine()
                self.send_message(
                    f"🔬 **[INICIANDO INVESTIGACIÓN DE RIGOR CIENTÍFICO]**\n"
                    f"• **Consulta:** \"{text}\"\n"
                    f"• **Motores Académicos:** arXiv, OpenAlex, Europe PMC, PubMed & DOIs\n"
                    f"⏳ *Explorando repositorios revisados por pares y compilando enlaces de acceso...*",
                    chat_id=chat_id,
                    reply_to_message_id=msg_id
                )
                with ChatActionKeeper(self, chat_id, "typing"):
                    clean_query = re.sub(
                        r"\b(tardis|por favor|investiga sobre|investiga|investigar|busca|papers|quiero aprender sobre|mándame|mandame|links|enlaces|de rigor científico|de rigor cientifico)\b",
                        "",
                        text,
                        flags=re.IGNORECASE
                    ).strip() or text
                    report = s_engine.execute_research(clean_query, max_papers=4)
                    s_engine.send_report_to_telegram(report, chat_id=chat_id, reply_to_message_id=msg_id)

                    self.chat_histories[chat_id].append({"role": "user", "content": text})
                    self.chat_histories[chat_id].append({"role": "assistant", "content": f"[Reporte Científico]: {report.topic} ({len(report.papers)} papers)"})
                    SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram [{user_name}] (Investigación Científica)", client_id=tg_client_id)
                    SYNC_HUB.add_chat_turn("assistant", f"Reporte de rigor científico sobre '{report.topic}' despachado con enlaces y PDFs.", meta=f"{self.active_model_label} · Rigor Científico", client_id=tg_client_id)
                    return

            # 3. Despachar al núcleo soberano con contexto personalizado por usuario o grupo
            action_type = "record_video_note" if self.video_mode_always else ("record_voice" if is_call_active else "typing")
            turn_label = f"[{member_name}]" if is_group else f"[{user_name}]"
            hist_turn = f"{turn_label}: {text}" if is_group else text
            self.chat_histories[chat_id].append({"role": "user", "content": hist_turn})
            SYNC_HUB.add_chat_turn("user", text, meta=f"Nodo: Telegram {turn_label} (Conversación Soberana)", client_id=tg_client_id)

            reply_to_msg = msg.get("reply_to_message")
            reply_context = ""
            if reply_to_msg:
                r_user = (reply_to_msg.get("from") or {}).get("first_name", "Usuario")
                r_text = (reply_to_msg.get("text") or reply_to_msg.get("caption") or "").strip()
                if r_text:
                    reply_context = f"[En respuesta al mensaje previo de {r_user}: \"{r_text[:250]}\"]\n"

            if is_group:
                model_user_input = (
                    f"[Mensaje en el grupo de Telegram '{chat_title or 'T.A.R.D.I.S'}' enviado por {member_name} (@{username})]:\n"
                    f"{reply_context}"
                    f"{text}\n\n"
                    f"(Directiva obligatoria para TARDIS: Estás respondiendo a {member_name} en el grupo. Fomenta conversaciones amplias, profundas, articuladas y complejas. Dirígete a {member_name} de forma natural)."
                )
            else:
                model_user_input = f"{reply_context}{text}" if reply_context else text

            with ChatActionKeeper(self, chat_id, action_type):
                # Contexto de conversación estructurado
                chat_hist = [
                    {"role": m["role"], "content": m["content"]}
                    for m in self.chat_histories[chat_id]
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ]

                # Invocación acelerada mediante KaijuCognitiveOrchestrator con historial conversacional
                hermes_reply = ""
                try:
                    from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
                    k_orch = get_kaiju_cognitive_orchestrator()
                    k_res = k_orch.process_turn(user_input=model_user_input, session_id=tg_client_id, history=chat_hist[-12:])
                    if k_res and k_res.get("response"):
                        hermes_reply = k_res["response"].strip()
                except Exception as e_k:
                    logger.warning(f"Fallback desde KaijuCognitiveOrchestrator: {e_k}")

                if not hermes_reply:
                    resp_chat = process_agentic_chat(
                        message=model_user_input,
                        history=chat_hist[-12:],
                        model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                        num_ctx=int(os.environ.get("GIA_NUM_CTX", "32768")),
                        use_web=True,
                        is_local_request=False,
                        client_id=tg_client_id
                    )
                    hermes_reply = resp_chat.get("reply", "Respuesta recibida.").strip()

                # Garantizar que en grupos se dirija al miembro por su nombre sin duplicaciones
                if is_group and member_name and member_name != "Usuario":
                    first_clean = re.sub(r"[^\w]", "", member_name.lower())
                    start_text = re.sub(r"[^\w\s]", " ", hermes_reply[:60].lower())
                    tokens = set(start_text.split())
                    if first_clean not in tokens and not any(first_clean in t or t in first_clean for t in tokens if len(t) >= 4):
                        hermes_reply = f"{member_name}, {hermes_reply}"
                    hermes_reply = re.sub(rf"^{re.escape(member_name)}[,\s]+{re.escape(member_name)}[,\s]+", f"{member_name}, ", hermes_reply, flags=re.IGNORECASE)
                    hermes_reply = re.sub(r"^(\w+)[,\s]+\1[,\s]+", r"\1, ", hermes_reply, flags=re.IGNORECASE)

                self.chat_histories[chat_id].append({"role": "assistant", "content": hermes_reply})
                if len(self.chat_histories[chat_id]) > 60:
                    self.chat_histories[chat_id] = self.chat_histories[chat_id][-60:]

                SYNC_HUB.add_chat_turn("assistant", hermes_reply, meta=f"{self.active_model_label} · Núcleo Soberano", client_id=tg_client_id)
                try:
                    from core.offline_chat_vault import get_offline_chat_vault
                    get_offline_chat_vault().record_turn(
                        user_message=text,
                        assistant_reply=hermes_reply,
                        session_id=tg_client_id,
                        client_id=tg_client_id,
                        model=os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU"),
                        direction="present"
                    )
                except Exception:
                    pass

                # 1. Enviar de inmediato el texto completo (<1s latencia en grupo)
                self.send_message(hermes_reply, chat_id=chat_id, reply_to_message_id=msg_id)

                # 2. Despacho multimedia asíncrono para no bloquear el bucle de polling
                if self.video_mode_always:
                    def _async_video_dispatch(reply_text: str, cid: Any, mid: Optional[int]):
                        try:
                            self.send_reply_with_video(reply_text, chat_id=cid, reply_to_message_id=mid)
                        except Exception as e_vid:
                            logger.warning(f"Aviso en despacho asíncrono de video: {e_vid}")

                    threading.Thread(
                        target=_async_video_dispatch,
                        args=(hermes_reply, chat_id, msg_id),
                        daemon=True,
                        name=f"VideoDispatch_{chat_id}"
                    ).start()
                else:
                    def _async_voice_dispatch(reply_text: str, cid: Any, mid: Optional[int]):
                        try:
                            self.send_reply_with_voice(reply_text, chat_id=cid, reply_to_message_id=mid)
                        except Exception as e_vce:
                            logger.warning(f"Aviso en despacho asíncrono de voz: {e_vce}")

                    threading.Thread(
                        target=_async_voice_dispatch,
                        args=(hermes_reply, chat_id, msg_id),
                        daemon=True,
                        name=f"VoiceDispatch_{chat_id}"
                    ).start()

        except Exception as e:
            logger.error(f"Error procesando mensaje en Telegram: {e}")
            self.send_message(f"⚠️ Error procesando directiva: {e}", chat_id=chat_id)

    # --------------------------------------------------------------------------
    # ESTADO Y DIAGNÓSTICO
    # --------------------------------------------------------------------------

    def get_status(self, is_local: bool = False) -> Dict[str, Any]:
        running = self.running and bool(self.worker_thread and self.worker_thread.is_alive())
        configured = bool(self.config.get("bot_token"))
        allowed = self.config.get("allowed_chats", [])
        raw_status = {
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
            "recurring_voice": self._get_recurring_voice_status(),
            "last_error": self.last_error
        }
        return sanitize_telegram_status(raw_status, is_local=is_local)

    def _get_recurring_voice_status(self) -> Dict[str, Any]:
        try:
            from core.recurring_voice_manager import get_recurring_voice_manager
            return get_recurring_voice_manager().get_status()
        except Exception:
            return {"enabled": False, "running": False}


# Instancia Global
def get_telegram_bridge() -> TelegramBridge:
    return TelegramBridge.get_instance()
