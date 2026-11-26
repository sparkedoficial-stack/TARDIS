"""core/telegram/common.py - Constantes compartidas, configuración por defecto y ChatActionKeeper."""
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

BASE_DIR = Path(__file__).resolve().parent.parent.parent
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


_AEGIS_CONTEXT_LINE_CACHE: Optional[str] = None


def _get_aegis_context_line() -> str:
    """Línea canónica de la Constante AEGIS (carga diferida del motor SSM v27)."""
    global _AEGIS_CONTEXT_LINE_CACHE
    if _AEGIS_CONTEXT_LINE_CACHE is None:
        try:
            from core.tardis_ssm_v27 import AEGIS_CONTEXT_LINE

            _AEGIS_CONTEXT_LINE_CACHE = str(AEGIS_CONTEXT_LINE)
        except Exception:
            _AEGIS_CONTEXT_LINE_CACHE = (
                "🛡️ CONSTANTE AEGIS · Matriz de Anclaje Soberana Blindada"
            )
    return _AEGIS_CONTEXT_LINE_CACHE


def _boost_inference_process_for_call(proc: Any) -> Dict[str, Any]:
    """Callback `on_process_spawned`: refuerza la prioridad del proceso de inferencia."""
    try:
        from core.telegram_call_priority import boost_process_for_call

        return boost_process_for_call(proc)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Aviso reforzando proceso de inferencia en llamada: {exc}")
        return {"ok": False, "error": str(exc)}


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

