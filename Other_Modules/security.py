"""
core/security.py - Control de Seguridad y Autenticación por Token Irrevocable
Garantiza acceso permanente e irrevocable mediante contraseñas maestras sin revocación.
"""
from __future__ import annotations
import os
from pathlib import Path
import secrets
from typing import Optional, Set
from core.config import get_settings

# Tokens irrevocables permanentes del sistema.
# Ningún cambio de código, reinicio o actualización puede revocar estos tokens.
HARDCODED_IRREVOCABLE_TOKENS: Set[str] = {
    "DiosDelTiempo01",
    "REDACTED_MISTRAL",
}


import json
import time

def get_invitation_tokens() -> Set[str]:
    """Retorna tokens de invitación activos expedidos por el motor de misiones."""
    inv_tokens = set()
    for vpath in [
        Path(os.path.expanduser("~/.config/godworks/missions_vault.json")),
        Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control" / "missions_vault.json"
    ]:
        if vpath.exists():
            try:
                data = json.loads(vpath.read_text(encoding="utf-8"))
                for inv in data.get("invitations", []):
                    tok = inv.get("token")
                    expires = inv.get("expires_ts")
                    if tok and (not expires or expires > time.time()):
                        inv_tokens.add(tok.strip())
            except Exception:
                pass
    return inv_tokens


def get_authorized_tokens() -> Set[str]:
    """Retorna el conjunto consolidado de tokens válidos e irrevocables del sistema."""
    tokens = set(HARDCODED_IRREVOCABLE_TOKENS)
    try:
        settings_tok = get_settings().token
        if settings_tok:
            tokens.add(settings_tok.strip())
    except Exception:
        pass

    env_tok = os.environ.get("GIA_AUTH_TOKEN") or os.environ.get("GIA_TOKEN")
    if env_tok:
        tokens.add(env_tok.strip())

    # Leer también gia_bridge_token.txt si existe
    try:
        base_dir = Path(__file__).resolve().parent.parent
        tok_file = base_dir / "gia_bridge_token.txt"
        if tok_file.exists():
            file_tok = tok_file.read_text(encoding="utf-8").strip()
            if file_tok:
                tokens.add(file_tok)
    except Exception:
        pass

    # Incluir tokens de invitación a misiones
    try:
        tokens.update(get_invitation_tokens())
    except Exception:
        pass

    return tokens


def verify_token(provided_token: Optional[str]) -> bool:
    """
    Verifica si el token proporcionado coincide con alguno de los tokens
    irrevocables autorizados en el sistema.
    Utiliza comparación en tiempo constante para mitigar ataques de temporización.
    """
    if not provided_token:
        return False
    cand = str(provided_token).strip()
    authorized = get_authorized_tokens()
    return any(secrets.compare_digest(cand, tok) for tok in authorized if tok)


def is_request_authorized(
    headers: dict,
    query_params: Optional[dict] = None,
    client_ip: str = ""
) -> bool:
    """
    Comprueba autorización examinando headers, parámetros query, cookies y registro de dispositivos.
    Garantiza que todo dispositivo que ingresó la contraseña una vez nunca pierda acceso.
    Soporta:
      - Header 'X-API-Key' / 'X-GIA-Key'
      - Header 'Authorization: Bearer <token>'
      - Query param 'key' o 'token'
      - Cookie 'gia_token=<token>' o 'key=<token>'
      - Header 'X-Device-ID', cookie 'gia_device_id', o query param 'device_id' (para dispositivos previamente autorizados)
    """
    from core.device_vault import get_device_vault
    device_vault = get_device_vault()

    # Extraer identificador de dispositivo y huella física de hardware
    device_id = (
        headers.get("x-device-id") or headers.get("X-Device-ID") or
        headers.get("x-client-id") or headers.get("X-Client-ID") or ""
    )
    device_fp = (
        headers.get("x-device-fingerprint") or headers.get("X-Device-Fingerprint") or ""
    )
    if not device_id and query_params:
        device_id = query_params.get("device_id") or query_params.get("client_id") or ""
    if not device_fp and query_params:
        device_fp = query_params.get("device_fp") or query_params.get("fp") or ""

    cookie_header = headers.get("cookie") or headers.get("Cookie") or ""
    token_in_cookie = ""
    device_in_cookie = ""
    fp_in_cookie = ""
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("gia_token="):
                token_in_cookie = part.replace("gia_token=", "").strip()
            elif part.startswith("key="):
                token_in_cookie = part.replace("key=", "").strip()
            elif part.startswith("gia_invite="):
                token_in_cookie = part.replace("gia_invite=", "").strip()
            elif part.startswith("gia_device_id="):
                device_in_cookie = part.replace("gia_device_id=", "").strip()
            elif part.startswith("device_id="):
                device_in_cookie = part.replace("device_id=", "").strip()
            elif part.startswith("gia_fp="):
                fp_in_cookie = part.replace("gia_fp=", "").strip()

    if not device_id and device_in_cookie:
        device_id = device_in_cookie
    if not device_fp and fp_in_cookie:
        device_fp = fp_in_cookie

    def _register_both():
        ua = headers.get("user-agent", "")
        if device_id:
            device_vault.register_device(device_id, ip=client_ip, user_agent=ua)
        if device_fp and device_fp != device_id:
            device_vault.register_device(device_fp, ip=client_ip, user_agent=ua, client_name="Huella Física de Hardware")

    # 1. Header X-API-Key / X-GIA-Key
    api_key = (
        headers.get("x-api-key") or headers.get("X-API-Key") or
        headers.get("x-gia-key") or headers.get("X-GIA-Key")
    )
    if api_key and verify_token(api_key):
        _register_both()
        return True

    # 2. Header Authorization
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth:
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            if verify_token(parts[1]):
                _register_both()
                return True

    # 3. Query parameters (key, token o invite)
    if query_params:
        q_token = query_params.get("key") or query_params.get("token") or query_params.get("invite")
        if q_token and verify_token(q_token):
            _register_both()
            return True

    # 4. Cookies
    if token_in_cookie and verify_token(token_in_cookie):
        _register_both()
        return True

    # 5. Reconocimiento Soberano de Dispositivo (Todo dispositivo que puso la contraseña nunca pierde acceso)
    if device_id and device_vault.is_device_authorized(device_id):
        device_vault.touch_device(device_id, ip=client_ip)
        return True

    # 6. Reconocimiento por Huella de Hardware (Inmune a borrado total de cookies/localStorage)
    if device_fp and device_vault.is_device_authorized(device_fp):
        device_vault.touch_device(device_fp, ip=client_ip)
        return True

    return False
