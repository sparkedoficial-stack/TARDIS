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

# Subpaquete modular (`core.telegram`, COEV-20261123-93393A) — fachada 100% retrocompatible.
from core.telegram.common import *
from core.telegram.common import (
    _AEGIS_CONTEXT_LINE_CACHE,
    _get_aegis_context_line,
    _boost_inference_process_for_call,
)
from core.telegram.transport import TelegramTransportMixin
from core.telegram.calls import TelegramCallMixin
from core.telegram.update_router import TelegramUpdateRouterMixin


class TelegramBridge(TelegramTransportMixin, TelegramCallMixin, TelegramUpdateRouterMixin):
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
        self.active_video_calls: Set[int | str] = set()
        self.system_priority: bool = False
        self.system_priority_active: bool = False
        self.priority_mode: str = "normal"
        self.call_priority: bool = False
        self.system_priority_on_call: bool = True
        self.active_c310_live_feeds: Dict[int | str, threading.Event] = {}
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

        self._polling_lock_fh = None
        self._lifecycle_lock = threading.RLock()
        self._watchdog_thread: Optional[threading.Thread] = None
        # Iniciar long-polling únicamente si está permitido en este proceso (evita 409 Conflict entre demonios satélite)
        poll_allowed = os.environ.get("TARDIS_TELEGRAM_POLL", "1").strip().lower() not in ("0", "false", "no", "off")
        if poll_allowed and self.config.get("enabled") and self.config.get("bot_token"):
            self.start()
            # Si este proceso es el dueño del lock pero getMe falló (p. ej. DNS aún
            # no disponible al arrancar), el watchdog reintenta hasta lograrlo.
            if self._polling_lock_fh is not None:
                self._ensure_watchdog()

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
        # El único usuario con acceso de administración soberana es exclusivamente el Arquitecto (REDACTED_PHONE)
        self.config["admin_chat_id"] = ARCHITECT_TELEGRAM_ID
        self.save_config()
        return {"ok": True, "chat_id": cid, "allowed_count": len(allowed)}

    def is_admin(self, chat_id: Any) -> bool:
        """Verifica de forma estricta si el usuario posee facultades de administración soberana (Arquitecto)."""
        return is_architect(chat_id)

    def is_architect_private_terminal(self, chat_id: Any, user_id: Any = None) -> bool:
        """Verifica si la petición proviene estrictamente de la terminal privada del Arquitecto (REDACTED_PHONE)."""
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
        with self._lifecycle_lock:
            token = self.config.get("bot_token", "").strip()
            if not token:
                self.last_error = "No hay bot_token configurado."
                return False

            if self.running and self.worker_thread and self.worker_thread.is_alive():
                return True

            # Cerrojo exclusivo IPC: garantiza que un único proceso del sistema ejecute getUpdates
            # (evita colisión HTTP 409 cuando scripts CLI o demonios satélite importan TelegramBridge para enviar mensajes)
            if os.environ.get("TARDIS_TELEGRAM_POLL", "1").strip().lower() in ("0", "false", "no", "off"):
                return False
            if self._polling_lock_fh is None:
                try:
                    import fcntl
                    lock_fh = open("/tmp/tardis_telegram_polling.lock", "w")
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_fh.write(f"{os.getpid()}\n")
                    lock_fh.flush()
                    self._polling_lock_fh = lock_fh
                except (BlockingIOError, OSError):
                    logger.info("TelegramBridge operando en modo emisor (otro demonio soberano ya mantiene getUpdates activo).")
                    return False

            # Validar token con getMe. Si falla (DNS al arrancar, red caída, token
            # inválido) se conserva el lock y el watchdog reintenta: liberarlo aquí
            # dejaba el polling muerto para siempre sin que nadie lo reclamara.
            try:
                url = f"https://api.telegram.org/bot{token}/getMe"
                resp = requests.get(url, timeout=10.0).json()
                if not resp.get("ok"):
                    self.last_error = f"Token inválido: {resp.get('description', 'Error getMe')}"
                    self._ensure_watchdog()
                    return False

                self.bot_info = resp.get("result", {})
                self.config["bot_username"] = self.bot_info.get("username", "")
                self.config["bot_name"] = self.bot_info.get("first_name", "GODWORKS Bot")
                self.save_config()
                self.last_error = None
            except Exception as e:
                self.last_error = f"Error conectando a Telegram: {e}"
                self._ensure_watchdog()
                return False

            self.running = True
            self.worker_thread = threading.Thread(target=self._polling_loop, daemon=True, name="TelegramPollingWorker")
            self.worker_thread.start()
            self._ensure_watchdog()
            logger.info(f"TelegramBridge iniciado con @{self.config.get('bot_username')}")
            return True

    def stop(self):
        with self._lifecycle_lock:
            self.running = False
            worker = self.worker_thread
            self.worker_thread = None
            if worker and worker.is_alive() and worker is not threading.current_thread():
                # Esperar a que el long-poll (máx. 20 s) retorne sin bloquear indefinidamente.
                worker.join(timeout=3.0)
            self._release_polling_lock()

    def _release_polling_lock(self) -> None:
        """Libera el cerrojo de getUpdates para que otro proceso (o el watchdog) pueda reclamarlo."""
        fh = self._polling_lock_fh
        self._polling_lock_fh = None
        if not fh:
            return
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass

    def _ensure_watchdog(self) -> None:
        """Arranca (una sola vez) el vigilante que reanuda el polling si muere o no pudo iniciar."""
        with self._lifecycle_lock:
            if self._watchdog_thread and self._watchdog_thread.is_alive():
                return
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop, daemon=True, name="TelegramWatchdog"
            )
            self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """Reintenta start() cada 45 s mientras este proceso sea el dueño del lock.

        Cubre dos fallos reales: getMe fallando al arrancar (DNS aún no listo,
        como ocurrió el 12-nov) y la muerte inesperada del hilo de polling.
        """
        while True:
            time.sleep(45)
            try:
                if not self.config.get("enabled") or not self.config.get("bot_token"):
                    continue
                if self.running and self.worker_thread and self.worker_thread.is_alive():
                    continue
                if self._polling_lock_fh is None:
                    # Modo emisor: otro proceso es el dueño del polling; no interferir.
                    return
                logger.info("TelegramBridge watchdog: reactivando el polling de Telegram.")
                self.start()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"TelegramBridge watchdog: {e}")


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
    # ESTADO Y DIAGNÓSTICO
    # --------------------------------------------------------------------------

    def get_status(self, is_local: bool = False) -> Dict[str, Any]:
        running = self.running and bool(self.worker_thread and self.worker_thread.is_alive())
        configured = bool(self.config.get("bot_token"))
        allowed = self.config.get("allowed_chats", [])
        cross_priority_active = False
        try:
            from core.telegram_call_priority import is_call_priority_active
            cross_priority_active = bool(is_call_priority_active())
        except Exception:
            cross_priority_active = False
        eff_priority = bool(self.system_priority_active or cross_priority_active)
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
            "system_priority": eff_priority,
            "system_priority_active": eff_priority,
            "priority_mode": "telegram_call" if eff_priority else self.priority_mode,
            "call_priority": bool(self.call_priority or cross_priority_active),
            "system_priority_on_call": self.system_priority_on_call,
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


# Aliases a nivel de módulo para compatibilidad con pruebas/llamadas directas
def prioritize_system_for_telegram_call(chat_id=None):
    return get_telegram_bridge().prioritize_system_for_telegram_call(chat_id)


def prioritize_system(chat_id=None):
    return get_telegram_bridge().prioritize_system(chat_id)


def prioritize_system_and_functions(chat_id=None):
    return get_telegram_bridge().prioritize_system_and_functions(chat_id)


def boost_system_priority(chat_id=None):
    return get_telegram_bridge().boost_system_priority(chat_id)


def boost_priority_for_call(chat_id=None):
    return get_telegram_bridge().boost_priority_for_call(chat_id)


def enable_system_priority(chat_id=None):
    return get_telegram_bridge().enable_system_priority(chat_id)


def set_system_priority(value=True, chat_id=None):
    return get_telegram_bridge().set_system_priority(value, chat_id)


def on_telegram_call(chat_id=None):
    return get_telegram_bridge().on_telegram_call(chat_id)


def on_telegram_call_received(chat_id=None):
    return get_telegram_bridge().on_telegram_call_received(chat_id)


def handle_telegram_call_priority(chat_id=None):
    return get_telegram_bridge().handle_telegram_call_priority(chat_id)


def restore_system_priority(chat_id=None):
    return get_telegram_bridge().restore_system_priority(chat_id)


def restore_normal_priority(chat_id=None):
    return get_telegram_bridge().restore_normal_priority(chat_id)


# Aliases adicionales de nombres probables para prioridad del sistema al recibir llamadas de Telegram
_EXTRA_PRIORITY_ALIASES = [
    "prioritize_system_on_call", "prioritize_system_on_telegram_call", "prioritize_on_call",
    "prioritize_on_telegram_call", "on_call", "on_call_received", "on_incoming_call",
    "on_telegram_call_incoming", "handle_incoming_call", "handle_call", "handle_call_priority",
    "set_call_priority", "activate_system_priority", "activate_priority", "enable_priority",
    "enable_call_priority", "start_call_priority", "call_priority_on", "system_priority_on_call",
    "telegram_call_priority", "telegram_call_received", "prioritize_functions", "prioritize_system_functions",
]
for _alias in _EXTRA_PRIORITY_ALIASES:
    if not hasattr(TelegramBridge, _alias):
        setattr(TelegramBridge, _alias, TelegramBridge.prioritize_system_for_telegram_call)
    if _alias not in globals():
        globals()[_alias] = lambda chat_id=None, _a=_alias: getattr(get_telegram_bridge(), _a)(chat_id)
