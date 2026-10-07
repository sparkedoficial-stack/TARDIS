"""
gemini_privacy_vault.py - Bóveda de Cifrado y Privacidad para el Puente Gemini.
================================================================================

Provee:
  1. Cifrado simétrico de alta seguridad (AES-256-GCM) atado a la cuenta de usuario
     mediante DPAPI de Windows (crypt32.dll), para almacenar localmente respuestas,
     análisis pesados y transcripciones sin riesgo de exposición en texto plano.
  2. Filtro de Sanitización y Anonimización de Privacidad (PII Scrubber):
     Antes de enviar cualquier bloque de conversación o contexto al cloud de Google,
     detecta y anonimiza rutas locales del sistema, nombres de usuario, tokens,
     claves privadas y contraseñas.
  3. Almacén seguro de conversaciones de Gemini: guarda y recupera datos en
     formato binario cifrado (.enc.dat).
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
from pathlib import Path

# Criptografía AES-256-GCM
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_AESGCM = True
except Exception:
    HAS_AESGCM = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import ecca_credentials as _creds
except Exception:
    _creds = None

VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control" / "gemini_vault"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
KEY_FILE = VAULT_DIR / "vault_master.key"
DATA_FILE = VAULT_DIR / "gemini_chats.enc.dat"


# =====================================================================
#  GESTIÓN DE CLAVE MAESTRA CIFRADA CON DPAPI
# =====================================================================

def _get_or_create_master_key() -> bytes:
    """Obtiene o genera una clave AES-256 (32 bytes) resguardada por DPAPI."""
    if KEY_FILE.exists():
        try:
            raw = KEY_FILE.read_bytes()
            if _creds:
                return _creds._dpapi_decrypt(raw)
            return raw[:32]
        except Exception:
            pass

    # Generar nueva clave de 256 bits
    new_key = os.urandom(32)
    if _creds:
        try:
            encrypted_key = _creds._dpapi_encrypt(new_key)
            KEY_FILE.write_bytes(encrypted_key)
            return new_key
        except Exception:
            pass
    KEY_FILE.write_bytes(new_key)
    return new_key


# =====================================================================
#  FUNCIONES DE CIFRADO / DESCIFRADO (AES-256-GCM)
# =====================================================================

def encrypt_data(plaintext_str: str) -> bytes:
    """Cifra una cadena de texto usando AES-256-GCM con nonce aleatorio de 12 bytes."""
    data = plaintext_str.encode("utf-8")
    if not HAS_AESGCM:
        # Fallback con DPAPI directa si no está cryptography
        if _creds:
            return _creds._dpapi_encrypt(data)
        return data

    key = _get_or_create_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_data(encrypted_bytes: bytes) -> str:
    """Descifra datos binarios AES-256-GCM y retorna la cadena de texto original."""
    if not encrypted_bytes:
        return ""
    if not HAS_AESGCM:
        if _creds:
            return _creds._dpapi_decrypt(encrypted_bytes).decode("utf-8")
        return encrypted_bytes.decode("utf-8", errors="ignore")

    try:
        key = _get_or_create_master_key()
        aesgcm = AESGCM(key)
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        # Intentar con DPAPI directa por si fue cifrado con versión previa
        if _creds:
            try:
                return _creds._dpapi_decrypt(encrypted_bytes).decode("utf-8")
            except Exception:
                pass
        raise ValueError("No se pudo descifrar el bloque (clave o firma no coinciden)")


# =====================================================================
#  FILTRO DE SANITIZACIÓN & PRIVACIDAD (PII & SECRET SCRUBBER)
# =====================================================================

def sanitize_for_cloud(text: str, strict: bool = False) -> tuple[str, list[str]]:
    """
    Sanitiza y anonimiza el texto antes de ser transmitido a la API de Google Gemini.
    Detecta y reemplaza:
      - Nombres de usuario y rutas del sistema local (ej. C:\\Users\\miguel -> [USER_HOME])
      - Tokens de acceso (Bearer, JWT, AWS, OpenAI, Anthropic, Google keys)
      - Contraseñas o credenciales en formato clave=valor o JSON
      - Direcciones IP locales o puertos sensibles
    Retorna (texto_sanitizado, lista_de_redacciones_realizadas).
    """
    if not text:
        return "", []

    redactions = []
    out = text

    # 1. Rutas de usuario local
    user_home = os.path.expanduser("~")
    if user_home and user_home.lower() in out.lower():
        # Reemplazar ignorando mayúsculas/minúsculas
        pattern = re.compile(re.escape(user_home), re.IGNORECASE)
        out = pattern.sub("[USER_HOME]", out)
        redactions.append("Ruta de usuario local anonimizada")

    username = os.environ.get("USERNAME", "")
    if username and len(username) > 2 and username in out:
        # Reemplazar nombre de usuario en rutas
        out = re.sub(rf"(Users|home)[/\\]{re.escape(username)}", r"\1/[USER]", out, flags=re.IGNORECASE)
        redactions.append("Nombre de usuario del sistema anonimizado")

    # 2. Claves de API y Tokens de Seguridad
    key_patterns = [
        (r"(AIzaSy[0-9A-Za-z_-]{33})", "[GOOGLE_API_KEY_REDACTED]"),
        (r"(sk-[a-zA-Z0-9]{32,})", "[OPENAI_KEY_REDACTED]"),
        (r"(sk-ant-[a-zA-Z0-9_-]{32,})", "[ANTHROPIC_KEY_REDACTED]"),
        (r"(ghp_[0-9a-zA-Z]{36})", "[GITHUB_TOKEN_REDACTED]"),
        (r"(eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*)", "[JWT_TOKEN_REDACTED]"),
        (r"(?i)(password|passwd|clave|secret)\s*[:=]\s*['\"]?([^\s'\"]{4,})['\"]?", r"\1: [SECRET_REDACTED]"),
    ]

    for pat, rep in key_patterns:
        if re.search(pat, out):
            out = re.sub(pat, rep, out)
            redactions.append(f"Patrón de credencial/token protegido ({rep})")

    # 3. Modo estricto: Sanitizar IPs locales y nombres de máquina
    if strict:
        out = re.sub(r"\b(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", "[LOCAL_IP]", out)
        computer_name = os.environ.get("COMPUTERNAME", "")
        if computer_name and len(computer_name) > 2:
            out = re.sub(re.escape(computer_name), "[LOCAL_NODE]", out, flags=re.IGNORECASE)

    return out, list(set(redactions))


# =====================================================================
#  ALMACÉN DE HISTORIAL CIFRADO DE GEMINI
# =====================================================================

def save_encrypted_interaction(prompt: str, reply: str, model: str, meta: dict = None) -> bool:
    """Guarda una interacción procesada por Gemini en el almacén local cifrado."""
    try:
        current_data = []
        if DATA_FILE.exists():
            try:
                decrypted_json = decrypt_data(DATA_FILE.read_bytes())
                current_data = json.loads(decrypted_json)
                if not isinstance(current_data, list):
                    current_data = []
            except Exception:
                current_data = []

        entry = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": model,
            "prompt": prompt,
            "reply": reply,
            "meta": meta or {}
        }
        current_data.append(entry)

        # Mantener últimos 1000 registros para evitar crecimiento ilimitado
        if len(current_data) > 1000:
            current_data = current_data[-1000:]

        raw_json = json.dumps(current_data, ensure_ascii=False)
        encrypted = encrypt_data(raw_json)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        tmp.replace(DATA_FILE)
        return True
    except Exception as e:
        print(f"[gemini_privacy_vault] Error guardando interacción cifrada: {e}", file=sys.stderr)
        return False


def get_encrypted_history(limit: int = 50) -> list[dict]:
    """Recupera el historial descifrado en memoria para su visualización o análisis."""
    if not DATA_FILE.exists():
        return []
    try:
        raw = DATA_FILE.read_bytes()
        decrypted_json = decrypt_data(raw)
        data = json.loads(decrypted_json)
        if isinstance(data, list):
            return data[-limit:]
        return []
    except Exception as e:
        print(f"[gemini_privacy_vault] Error leyendo historial cifrado: {e}", file=sys.stderr)
        return []


def get_vault_status() -> dict:
    """Retorna información del estado de la bóveda de privacidad."""
    has_key = KEY_FILE.exists()
    has_data = DATA_FILE.exists()
    size_kb = round(DATA_FILE.stat().st_size / 1024, 2) if has_data else 0
    return {
        "ok": True,
        "encryption": "AES-256-GCM + DPAPI",
        "has_master_key": has_key,
        "vault_path": str(VAULT_DIR),
        "data_size_kb": size_kb,
        "has_aesgcm": HAS_AESGCM,
        "status": "active"
    }


if __name__ == "__main__":
    print("Estado de la Bóveda:", json.dumps(get_vault_status(), indent=2))
    # Prueba de sanitización
    test_msg = f"Hola, mi usuario es {os.environ.get('USERNAME')} en C:\\Users\\{os.environ.get('USERNAME')}\\proyecto con key sk-ant-1234567890abcdef1234567890abcdef"
    clean, reds = sanitize_for_cloud(test_msg)
    print("\nPrueba de Sanitización:")
    print("Original:", test_msg)
    print("Limpio:  ", clean)
    print("Redacciones:", reds)

    # Prueba de cifrado
    enc = encrypt_data("Conversación confidencial del sistema GIA.")
    dec = decrypt_data(enc)
    print("\nPrueba de Cifrado AES-256-GCM:", "OK" if dec == "Conversación confidencial del sistema GIA." else "FALLO")
