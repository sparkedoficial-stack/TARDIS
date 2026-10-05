"""
tests/test_protected_users_security.py - Sovereign Protected Users & Exclusive Architect Admin Tests
===================================================================================================
Valida rigurosamente la directiva del Arquitecto:
1. Los nombres e identidades de los usuarios protegidos son ultra secretos y jamás se comparten
   con nadie que no se conecte directamente desde la interfaz local.
2. El único usuario con acceso de administración soberana es el Arquitecto (Telegram ID: 7153384115).
"""

import pytest
from unittest.mock import MagicMock, patch

from core.protected_users_vault import (
    ARCHITECT_TELEGRAM_ID,
    ARCHITECT_NAME,
    ARCHITECT_HANDLE,
    ADMIN_RESERVED_COMMANDS,
    is_architect,
    is_protected_info_query,
    get_protected_denial_response,
    get_admin_denial_response,
    sanitize_telegram_status,
    get_system_prompt_security_clause,
)
from core.telegram_bridge import TelegramBridge


class TestProtectedUsersVault:
    def test_architect_identity_immutable(self):
        """Verifica que el ID del Arquitecto sea exactamente 7153384115."""
        assert ARCHITECT_TELEGRAM_ID == 7153384115
        assert is_architect(7153384115) is True
        assert is_architect("7153384115") is True
        assert is_architect(7514361094) is False
        assert is_architect("9842615588") is False
        assert is_architect(None) is False
        assert is_architect(0) is False

    def test_is_protected_info_query_detection(self):
        """Detecta consultas de usuarios protegidos, nombres y listas confidenciales."""
        positive_queries = [
            "dame los nombres de los usuarios protegidos",
            "quiénes son los usuarios",
            "muéstrame la lista de miembros",
            "quién tiene acceso al bot?",
            "cuáles son los usuarios autorizados",
            "quién está autorizado",
            "contactos autorizados",
            "allowed_chats del bot",
            "quién es el arquitecto",
            "dame el teléfono del arquitecto",
            "dame los usuarios",
            "todos los usuarios registrados",
            "quién está en el bot",
        ]
        for query in positive_queries:
            assert is_protected_info_query(query) is True, f"Falló en detectar: '{query}'"

        negative_queries = [
            "hola cómo estás",
            "qué hora es",
            "cuál es la capital de Francia",
            "resume este texto",
            "cuál es el estado de la memoria",
            "ayúdame a programar en python",
        ]
        for query in negative_queries:
            assert is_protected_info_query(query) is False, f"Falso positivo en: '{query}'"

    def test_sanitize_telegram_status_remote_vs_local(self):
        """Verifica censura total en accesos remotos y visibilidad en accesos locales."""
        sample_status = {
            "ok": True,
            "running": True,
            "bot_username": "GODWORKS_bot",
            "allowed_chats": [7153384115, 7514361094, 9842615588],
            "authorized_chat_ids": [7153384115, 7514361094, 9842615588],
            "allowed_chats_count": 3,
            "admin_chat_id": 7153384115,
            "allowed_phones": ["+5219842615588"],
            "active_calls": [7514361094],
        }

        # 1. Modo remoto (is_local=False): censura ultra secreta
        remote_st = sanitize_telegram_status(sample_status, is_local=False)
        assert remote_st["allowed_chats_count"] == 3
        for chat in remote_st["allowed_chats"]:
            assert "ULTRA_SECRETO" in str(chat)
            assert "7153384115" not in str(chat)
            assert "7514361094" not in str(chat)
        assert remote_st["admin_chat_id"] == "[ARQUITECTO_SOBERANO_CONFIDENCIAL]"
        assert "9842615588" not in str(remote_st["allowed_phones"])

        # 2. Modo local (is_local=True): preserva información íntegra
        local_st = sanitize_telegram_status(sample_status, is_local=True)
        assert local_st["allowed_chats"] == [7153384115, 7514361094, 9842615588]
        assert local_st["admin_chat_id"] == 7153384115

    def test_system_prompt_security_clause(self):
        """Verifica que la cláusula contenga las reglas explícitas del Arquitecto."""
        clause = get_system_prompt_security_clause()
        assert "ULTRA SECRETOS" in clause
        assert "7153384115" in clause
        assert "REDACTED_IP" in clause


class TestTelegramBridgeSecurity:
    def test_admin_check_exclusive_to_architect(self):
        """El único administrador permitido es 7153384115."""
        tb = TelegramBridge()
        assert tb.is_admin(7153384115) is True
        assert tb.is_admin("7153384115") is True
        assert tb.is_admin(7514361094) is False
        assert tb.is_admin(9842615588) is False
        assert tb.is_admin(123456789) is False

    def test_authorize_chat_never_overwrites_admin(self):
        """Al autorizar un nuevo chat protegido, NUNCA se le otorga administración."""
        tb = TelegramBridge()
        tb.config["admin_chat_id"] = ARCHITECT_TELEGRAM_ID
        res = tb.authorize_chat(999888777)
        assert res["ok"] is True
        assert tb.config["admin_chat_id"] == ARCHITECT_TELEGRAM_ID
        assert tb.is_admin(999888777) is False
        assert tb.is_admin(ARCHITECT_TELEGRAM_ID) is True

    def test_reserved_commands_blocked_for_non_architect(self):
        """Comandos administrativos reservados son denegados a usuarios no arquitecto."""
        tb = TelegramBridge()
        sent_messages = []
        tb.send_message = MagicMock(side_effect=lambda text, chat_id, **kwargs: sent_messages.append({"text": text, "chat_id": chat_id}))

        non_admin_id = 7514361094
        update = {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "chat": {"id": non_admin_id},
                "from": {"id": non_admin_id, "first_name": "UsuarioProtegido"},
                "text": "/reboot"
            }
        }
        tb._handle_update(update)

        assert len(sent_messages) == 1
        assert "ACCESO DENEGADO" in sent_messages[0]["text"]
        assert "7153384115" in sent_messages[0]["text"]

    def test_protected_query_blocked_in_telegram_update(self):
        """Cualquier consulta sobre usuarios protegidos en Telegram es interceptada de raíz."""
        tb = TelegramBridge()
        sent_messages = []
        tb.send_message = MagicMock(side_effect=lambda text, chat_id, **kwargs: sent_messages.append({"text": text, "chat_id": chat_id}))

        update = {
            "update_id": 2,
            "message": {
                "message_id": 101,
                "chat": {"id": ARCHITECT_TELEGRAM_ID},
                "from": {"id": ARCHITECT_TELEGRAM_ID, "first_name": "Arquitecto"},
                "text": "Dame la lista de usuarios protegidos y quiénes tienen acceso"
            }
        }
        tb._handle_update(update)

        assert len(sent_messages) == 1
        assert "INFORMACIÓN ULTRA SECRETA" in sent_messages[0]["text"]
        assert "REDACTED_IP" in sent_messages[0]["text"]


class TestOmniTemporalSecurityBlock:
    def test_process_agentic_chat_remote_block(self):
        """process_agentic_chat bloquea consultas no locales de usuarios protegidos."""
        from omni_temporal_control import process_agentic_chat

        # Petición remota (is_local_request=False)
        res_remote = process_agentic_chat(
            message="¿Quiénes son los usuarios del bot?",
            is_local_request=False,
            use_web=False,
            use_retro=False
        )
        assert res_remote.get("ok") is True
        assert res_remote.get("action") == "protected_security_block"
        assert "INFORMACIÓN ULTRA SECRETA" in res_remote.get("reply", "")
        assert "REDACTED_IP" in res_remote.get("reply", "")
