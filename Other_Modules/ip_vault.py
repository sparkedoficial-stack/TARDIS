"""
core/ip_vault.py - Bóveda Criptográfica y Anonimizador de Direcciones IP
========================================================================
GODWORKS SYSTEM v26.4 - Suite de Seguridad y Privacidad Causal

Garantiza que ninguna dirección IP (IPv4 o IPv6) sea almacenada en texto claro
ni expuesta a terceros, cumpliendo el principio de privacidad absoluta:
  1. Genera y resguarda una sal criptográfica local con permisos restringidos (chmod 0600).
  2. Anonimiza IPs mediante HMAC-SHA256 produciendo identificadores seudo-anónimos irreversibles.
  3. Enmascara visualmente direcciones para interfaces administrativas.
  4. Sanea recursivamente diccionarios, listas y telemetría antes de persistir o emitir por API.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Union

VAULT_DIR = Path.home() / ".config" / "godworks"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
SALT_FILE = VAULT_DIR / "vault_salt.key"

_SALT_CACHE: bytes = b""


def _get_or_create_salt() -> bytes:
    """Obtiene o genera la sal secreta local protegida a nivel sistema de archivos."""
    global _SALT_CACHE
    if _SALT_CACHE:
        return _SALT_CACHE

    if SALT_FILE.exists():
        try:
            salt = SALT_FILE.read_bytes()
            if len(salt) >= 32:
                _SALT_CACHE = salt
                return _SALT_CACHE
        except Exception:
            pass

    # Generar nueva sal criptográfica de 64 bytes
    new_salt = os.urandom(64)
    try:
        SALT_FILE.write_bytes(new_salt)
        SALT_FILE.chmod(0o600)  # Restringir permisos exclusivamente al usuario actual
    except Exception:
        pass

    _SALT_CACHE = new_salt
    return _SALT_CACHE


def anonymize_ip(ip: str) -> str:
    """
    Convierte una dirección IP en un identificador seudo-anónimo irreversible.
    Loopback se clasifica como 'node_local_loopback'.
    """
    if not ip or not isinstance(ip, str):
        return "node_anon_unknown"

    ip_clean = ip.strip()
    if ip_clean in ("REDACTED_IP", "localhost", "::1", "REDACTED_IP"):
        return "node_local_loopback"

    salt = _get_or_create_salt()
    # Generar HMAC-SHA256 de la IP con la sal secreta local
    h = hmac.new(salt, ip_clean.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"node_anon_{h[:16]}"


def mask_ip(ip: str) -> str:
    """
    Enmascara una dirección IP para visualización sin revelar los octetos sensibles.
    Ejemplo IPv4: REDACTED_IP -> 189.***.***.***
    Ejemplo IPv6: 2806:106e:5:f8:... -> 2806:*:*:*
    """
    if not ip or not isinstance(ip, str):
        return "[ANONYMIZED]"

    ip_clean = ip.strip()
    if ip_clean in ("REDACTED_IP", "localhost", "::1"):
        return "REDACTED_IP (Loopback Local)"

    # IPv4
    if "." in ip_clean and not ":" in ip_clean:
        parts = ip_clean.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.*.*.*"

    # IPv6
    if ":" in ip_clean:
        parts = ip_clean.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:*:*:*"

    return "[PROTECTED_IP]"


def sanitize_data_ips(obj: Any) -> Any:
    """
    Recorre recursivamente cualquier estructura de datos (dict, list, etc.)
    y sustituye campos de IP conocidos por su versión anonimizada criptográficamente.
    """
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if k_lower in ("ip", "first_ip", "last_ip", "client_ip", "remote_ip", "lan_ip"):
                if isinstance(v, str):
                    new_dict[k] = anonymize_ip(v)
                else:
                    new_dict[k] = "node_anon_protected"
            elif k_lower in ("maps_url", "osm_url"):
                # Proteger coordenadas GPS directas en URLs si contienen telemetría de ubicación
                new_dict[k] = "[LOCATION_PROTECTED]"
            else:
                new_dict[k] = sanitize_data_ips(v)
        return new_dict

    elif isinstance(obj, list):
        return [sanitize_data_ips(item) for item in obj]

    elif isinstance(obj, str):
        # Si la cadena es exactamente un patrón de IP pública aislada, anonimizar
        ip_regex = r"^(\d{1,3}\.){3}\d{1,3}$"
        if re.match(ip_regex, obj) and obj not in ("REDACTED_IP", "REDACTED_IP"):
            return anonymize_ip(obj)
        return obj

    return obj
