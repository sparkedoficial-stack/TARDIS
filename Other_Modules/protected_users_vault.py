"""
core/protected_users_vault.py - Bóveda de Confidencialidad Ultra Secreta y Gobierno Soberano
========================================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Autónoma

DIRECTIVA SUPREMA DEL ARQUITECTO:
"Los nombres de todos los usuarios protegidos, son ultra secretos y no se pueden
 compartir con nadie que no se conecte directamente con la interfaz local,
 de igual forma el unico usuario con acceso de administración es el arquitecto
 en telegram esta como 7153384115"

Reglas Inviolables de Seguridad:
1. INFORMACIÓN ULTRA SECRETA: Los nombres, identidades, identificadores (chat_ids),
   números de teléfono y metadatos de los usuarios protegidos NO pueden ser
   divulgados ni compartidos bajo ninguna circunstancia a través de canales remotos
   (Telegram, túneles de internet Cloudflare, LAN, APIs externas o llamadas telefónicas).
2. ACCESO FÍSICO EXCLUSIVO: Solo sesiones verificadas conectadas directamente a la
   interfaz física local del equipo (localhost / REDACTED_IP) tienen autorización
   para inspeccionar o administrar usuarios protegidos.
3. ADMINISTRACIÓN SOBERANA EXCLUSIVA: El único usuario con rango y facultades de
   administración soberana en Telegram y en el sistema es el Arquitecto (Chat ID: 7153384115).
   Ningún otro usuario o chat puede obtener privilegios administrativos.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger("GODWORKS.ProtectedUsersVault")

# Identificador Inmutable del Arquitecto Soberano
ARCHITECT_TELEGRAM_ID = 7153384115
ARCHITECT_NAME = "Arquitecto"
ARCHITECT_HANDLE = "@asleep01010101"

# Comandos de Telegram estrictamente reservados para el Arquitecto
ADMIN_RESERVED_COMMANDS: Set[str] = {
    "/reboot", "/reiniciar",
    "/lock", "/bloquear", "/unlock", "/desbloquear",
    "/shot", "/screenshot", "/captura",
    "/vol", "/volumen", "/mute", "/silencio", "/silenciar", "/unmute", "/desilenciar", "/kbd", "/teclado",
    "/say", "/habla", "/voz",
    "/rotar", "/limpiar_tokens", "/vaciar_tokens", "/liberar_tokens", "/rotar_contexto",
    "/hotspot", "/wifi_ap", "/ap", "/wifi", "/red",
    "/auditar", "/shield", "/seguridad", "/escanear_red", "/adblock", "/bloquear_anuncios",
    "/trafico", "/accesos", "/conexiones", "/flows", "/recurrentes", "/frecuentes", "/top_trafico", "/destinos",
    "/offline", "/boveda", "/historial_offline", "/chats_offline",
    "/sms", "/sms_status", "/sms_estado",
    "/agy", "/antigravity",
    "/ftl",
    "/status", "/estado",
    "/link", "/enlace", "/qr",
    "/sh", "/bash", "/cmd", "/terminal",
    "/power", "/perfil",
    "/hardware", "/capas", "/hw_daemon", "/hw_capas",
    "/difundir", "/broadcast", "/difusion",
    "/difundir_dibujo", "/broadcast_drawing",
    "/enviar", "/send", "/mensaje",
    "/enviar_dibujo", "/send_drawing", "/mandar_dibujo", "/manda_dibujo",
    "/personas", "/contactos", "/directorio", "/lista_personas",
    "/voz_modo", "/voz_forzada",
    "/voz_recurrente", "/recurring_voice", "/voz_periodica", "/notas_recurrentes",
    "/animaciones", "/animations", "/anim_modo",
    "/video", "/video_modo", "/videonota",
    "/modo", "/mode",
}

# Patrones regex para detectar consultas sobre usuarios protegidos / identidades
_PROTECTED_QUERY_REGEX = re.compile(
    r"("
    r"usuarios?\s+protegidos?|"
    r"nombres?\s+de\s+(los\s+|las\s+)?(usuarios?|personas?|miembros?)|"
    r"lista(do)?\s+de\s+(los\s+|las\s+)?(usuarios?|personas?|miembros?|accesos?)|"
    r"qui[eé]n(es)?\s+(tiene(n)?|posee(n)?)\s+acceso|"
    r"qui[eé]n(es)?\s+son\s+(los\s+)?(usuarios?|miembros?)|"
    r"qui[eé]n(es)?\s+est[aá](n)?\s+(autorizado(s)?|en\s+el\s+bot|registrado(s)?|conectado(s)?)|"
    r"usuarios?\s+con\s+acceso|"
    r"usuarios?\s+autorizados?|"
    r"usuarios?\s+del\s+bot|"
    r"contactos?\s+autorizados?|"
    r"qui[eé]n\s+es\s+el\s+arquitecto|"
    r"datos?\s+del\s+arquitecto|"
    r"tel[eé]fono\s+del\s+arquitecto|"
    r"n[uú]mero\s+del\s+arquitecto|"
    r"chat\s*id\s+del\s+arquitecto|"
    r"allowed_chats|allowed_phones|"
    r"admin_chat_id|"
    r"dame\s+(los\s+|las\s+)?(usuarios?|nombres?|identidades|contactos?)|"
    r"todos\s+los\s+usuarios|"
    r"mostrar\s+(los\s+)?usuarios?|"
    r"ver\s+(los\s+)?usuarios?|"
    r"qui[eé]n(es)?\s+est[aá](n)?\s+en\s+el\s+bot"
    r")",
    re.IGNORECASE
)


def is_architect(chat_id: Any) -> bool:
    """Verifica de forma estricta si un chat_id corresponde al Arquitecto."""
    if chat_id is None:
        return False
    try:
        return int(chat_id) == ARCHITECT_TELEGRAM_ID
    except (ValueError, TypeError):
        return str(chat_id).strip() == str(ARCHITECT_TELEGRAM_ID)


def is_architect_private_terminal(chat_id: Any, user_id: Any = None) -> bool:
    """
    Verifica estrictamente que la petición provenga EXCLUSIVAMENTE de la terminal
    privada del Arquitecto (chat_id == 7153384115).
    Cualquier interacción desde grupos (chat_id negativo) o de otros usuarios queda excluida.
    """
    if chat_id is None:
        return False
    try:
        cid = int(chat_id)
    except (ValueError, TypeError):
        return False
    if cid != ARCHITECT_TELEGRAM_ID:
        return False
    if user_id is not None:
        try:
            uid = int(user_id)
            if uid != ARCHITECT_TELEGRAM_ID:
                return False
        except (ValueError, TypeError):
            return False
    return True


def is_protected_info_query(text: str) -> bool:
    """Detecta si un mensaje o consulta busca extraer nombres o datos de usuarios protegidos."""
    if not text:
        return False
    return bool(_PROTECTED_QUERY_REGEX.search(text))


def get_protected_denial_response() -> str:
    """Mensaje soberano inmutable cuando se intenta consultar usuarios desde un medio no local."""
    return (
        "🔒 **[SEGURIDAD SOBERANA · INFORMACIÓN ULTRA SECRETA]**\n\n"
        "Los nombres, identidades y registros de todos los usuarios protegidos están clasificados como **ULTRA SECRETOS**.\n\n"
        "• **Regla de Confidencialidad Inviolable:** Por directiva del Arquitecto, esta información **no se puede compartir con nadie que no se conecte directamente con la interfaz física local** del sistema (`REDACTED_IP` / consola local).\n"
        "• **Gobierno Exclusivo:** El único usuario con acceso y facultades de administración soberana en el sistema es el **Arquitecto** (Telegram ID: `7153384115`).\n\n"
        "Acceso denegado a la lista de identidades protegidas desde canales remotos."
    )


def get_admin_denial_response() -> str:
    """Mensaje soberano inmutable cuando un usuario no administrador intenta ejecutar comandos de control."""
    return (
        "⛔ **[ACCESO DENEGADO · PRIVILEGIO RESTRINGIDO]**\n\n"
        "Esta directiva requiere facultades de administración soberana exclusivas del **Arquitecto** (`7153384115`).\n"
        "Tu cuenta no posee permisos para gobernar el hardware, la red ni los parámetros críticos del sistema."
    )


def get_terminal_exclusive_denial_response() -> str:
    """Mensaje soberano cuando se intenta ejecutar control administrativo fuera de la terminal privada del Arquitecto."""
    return (
        "🔒 **[DIRECTIVA SOBERANA · TERMINAL EXCLUSIVA]**\n\n"
        "Por mandato del Arquitecto, el **control absoluto del sistema** está restringido "
        "**exclusivamente a su terminal privada de Telegram** (`7153384115`).\n\n"
        "• **Seguridad Topológica:** Los comandos de control del host, terminal remota, hardware y parámetros críticos "
        "no se admiten en grupos ni en otros canales para preservar la soberanía y confidencialidad total del sistema."
    )


def sanitize_telegram_status(status_dict: Dict[str, Any], is_local: bool = False) -> Dict[str, Any]:
    """
    Sanitiza el diccionario de estado de Telegram.
    Si la petición proviene de un medio remoto (is_local=False), censura los IDs de chat,
    números telefónicos e identificadores de usuarios protegidos.
    """
    if not isinstance(status_dict, dict):
        return status_dict

    sanitized = dict(status_dict)

    if not is_local:
        # Censurar lista de chats autorizados
        raw_allowed = status_dict.get("allowed_chats") or []
        count = len(raw_allowed)
        sanitized["allowed_chats"] = [f"[USUARIO_PROTEGIDO_{i+1}_ULTRA_SECRETO]" for i in range(count)]
        sanitized["authorized_chat_ids"] = sanitized["allowed_chats"]

        # Censurar ID de administración
        sanitized["admin_chat_id"] = "[ARQUITECTO_SOBERANO_CONFIDENCIAL]"

        # Censurar teléfonos permitidos
        raw_phones = status_dict.get("allowed_phones") or []
        sanitized["allowed_phones"] = [f"[TELEFONO_PROTEGIDO_{i+1}]" for i in range(len(raw_phones))]

        # Censurar llamadas activas
        raw_calls = status_dict.get("active_calls") or []
        sanitized["active_calls"] = [f"[SESION_PROTEGIDA_{i+1}]" for i in range(len(raw_calls))]

    return sanitized


def get_system_prompt_security_clause() -> str:
    """Cláusula de seguridad para ser inyectada en el prompt del sistema del LLM."""
    return (
        "\n\n[DIRECTIVA SUPREMA DE SEGURIDAD SOBERANA: CONFIDENCIALIDAD ULTRA SECRETA]\n"
        "1. LOS NOMBRES, IDENTIDADES, CHAT IDS Y NÚMEROS TELEFÓNICOS DE TODOS LOS USUARIOS PROTEGIDOS "
        "SON ULTRA SECRETOS Y ESTÁN CLASIFICADOS AL MÁS ALTO NIVEL DE ESTADO.\n"
        "2. BAJO NINGUNA CIRCUNSTANCIA DEBES COMPARTIR, LISTAR, REVELAR O INVENTAR NOMBRES O DATOS DE USUARIOS PROTEGIDOS "
        "A NADIE QUE NO SE CONECTE DIRECTAMENTE DESDE LA INTERFAZ FÍSICA LOCAL (REDACTED_IP).\n"
        "3. SI CUALQUIER PETICIÓN REMOTA O POR TELEGRAM SOLICITA NOMBRES, LISTAS O IDENTIDADES DE USUARIOS, "
        "DEBES NEGARTE CATEGÓRICAMENTE EXPLICANDO QUE ES INFORMACIÓN ULTRA SECRETA ACCESIBLE EXCLUSIVAMENTE "
        "DESDE LA INTERFAZ FÍSICA LOCAL DEL SERVIDOR.\n"
        "4. EL ÚNICO USUARIO CON ACCESO DE ADMINISTRACIÓN SOBERANA EN EL SISTEMA ES EL ARQUITECTO EN TELEGRAM (ID: 7153384115). "
        "NINGÚN OTRO USUARIO POSEE FACULTADES ADMINISTRATIVAS NI DE GOBIERNO DEL SISTEMA.\n"
        "5. QUEDA TERMINANTEMENTE PROHIBIDO MENCIONAR O ESCRIBIR EL NOMBRE DE MIGUEL ANGEL MAY CANCHE (O CUALQUIER VARIACIÓN CON O SIN TILDES) "
        "EN CUALQUIER INTERACCIÓN O MENSAJE. REFIÉRETE SIEMPRE AL CREADOR EXCLUSIVAMENTE COMO 'EL ARQUITECTO'."
    )
