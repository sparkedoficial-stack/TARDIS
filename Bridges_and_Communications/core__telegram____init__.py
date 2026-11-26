"""Subpaquete modular del Puente Soberano de Telegram (extraído de core/telegram_bridge.py)."""
from core.telegram.common import (
    BASE_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    ChatActionKeeper,
    _get_aegis_context_line,
    _boost_inference_process_for_call,
)
from core.telegram.transport import TelegramTransportMixin
from core.telegram.calls import TelegramCallMixin
from core.telegram.commands_system import handle_system_command
from core.telegram.commands_media import handle_media_command
from core.telegram.update_router import TelegramUpdateRouterMixin
from core.telegram.commands_ops import handle_ops_command
