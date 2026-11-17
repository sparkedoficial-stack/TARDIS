"""
core/aegis/classifier.py — Clasificación de información y detección de fugas.
=============================================================================
Dos capas complementarias:

1. Clasificación por ruta (C0–C4): determina la sensibilidad nominal de un
   archivo a partir de su nombre, extensión y ubicación.
2. Inspección de contenido: detecta credenciales, claves privadas, tokens de
   API, cadenas de alta entropía y PII, devolviendo SIEMPRE vistas redactadas
   (nunca el secreto completo, nunca en logs).

Niveles:
    C0  Público            (licencias, README, assets públicos)
    C1  Interno            (código fuente, documentación técnica)
    C2  Confidencial       (telemetría, informes, configuraciones)
    C3  Secreto            (credenciales, bases de datos, historiales)
    C4  Crítico/Absoluto   (claves maestras, tokens activos, bóveda AEGIS)
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class Level(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    SECRET = 3
    CRITICAL = 4


LEVELS: Dict[int, Dict[str, str]] = {
    0: {"code": "C0", "label": "PÚBLICO", "color": "#4ade80"},
    1: {"code": "C1", "label": "INTERNO", "color": "#38bdf8"},
    2: {"code": "C2", "label": "CONFIDENCIAL", "color": "#fbbf24"},
    3: {"code": "C3", "label": "SECRETO", "color": "#fb923c"},
    4: {"code": "C4", "label": "CRÍTICO", "color": "#f43f5e"},
}


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return {
            0: "info",
            1: "bajo",
            2: "medio",
            3: "alto",
            4: "crítico",
        }[int(self)]


@dataclass
class Classification:
    level: int
    code: str
    label: str
    tags: List[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {
            "level": int(self.level),
            "code": self.code,
            "label": self.label,
            "tags": list(self.tags),
            "reason": self.reason,
        }


@dataclass
class SecretFinding:
    path: str
    kind: str
    severity: Severity
    line: int
    preview: str
    rule: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "severity": self.severity.label,
            "severity_value": int(self.severity),
            "line": self.line,
            "preview": self.preview,
            "rule": self.rule,
        }


# ---------------------------------------------------------------------------
# Reglas de clasificación por ruta
# ---------------------------------------------------------------------------

_CRITICAL_NAMES = re.compile(
    r"""(?ix)^(
        master\.key | master\.pass\.enc | recovery\.enc |
        akashic_secret\.key | id_(rsa|ed25519|ecdsa|dsa)(\.pub)? |
        \.env(\..*)? | gia_bridge_token\.txt |
        (telegram|whatsapp|sms|social|tunnel|tapo_c310)_config\.json |
        client_gateway_secrets\.json
    )$"""
)

_SECRET_SUFFIXES = {
    ".key", ".pem", ".p12", ".pfx", ".kdbx", ".jks", ".keystore",
    ".asc", ".gpg", ".age", ".ovpn", ".mobileconfig", ".seed",
}

_SECRET_TOKENS = (
    "secret", "token", "credential", "password", "passwd", "apikey",
    "api_key", "private", "auth", "session", "cookie", "wallet",
)

_CONFIDENTIAL_TOKENS = (
    "telemetry", "telemetria", "log", "backup", "bak", "db", "sqlite",
    "vault", "vault", "report", "informe", "capture", "captura", "history",
    "historial", "memory", "memoria", "akashic",
)

_PUBLIC_NAMES = {
    "readme.md", "license", "licence", "copying", "notice", "changelog.md",
    ".gitignore", ".gitattributes", "requirements.txt", "pytest.ini",
}

_SKIP_DIRS = {
    ".git", ".venv-linux", ".venv-whatsapp", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}

_SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".rs", ".go", ".java",
    ".kt", ".c", ".h", ".cpp",
}

_DOC_SUFFIXES = {".md", ".rst", ".html", ".css", ".txt"}

_CONFIG_SUFFIXES = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".conf",
    ".properties", ".log", ".jsonl", ".csv", ".parquet", ".pdf", ".docx", ".xlsx",
}


def classify_path(path: os.PathLike | str) -> Classification:
    """Clasifica una ruta en la matriz C0–C4."""
    p = Path(path)
    name = p.name.lower()
    suffix = p.suffix.lower()
    parts = {part.lower() for part in p.parts}
    text = str(p).lower()

    if name in _PUBLIC_NAMES:
        return Classification(0, "C0", "PÚBLICO", ["readme"], "nombre público canónico")

    # Plantillas de entorno: no contienen secretos reales por definición.
    if name in {".env.example", ".env.sample", ".env.template"}:
        return Classification(1, "C1", "INTERNO", ["plantilla"], "plantilla de entorno sin secretos reales")

    # C4 — custodia absoluta
    if _CRITICAL_NAMES.match(name):
        return Classification(4, "C4", "CRÍTICO", ["credencial"], "nombre de credencial crítica")
    if ".aegis" in parts:
        return Classification(4, "C4", "CRÍTICO", ["bóveda-aegis"], "perímetro AEGIS")
    if ".ssh" in parts:
        return Classification(4, "C4", "CRÍTICO", ["ssh"], "directorio SSH")
    if suffix in {".kdbx", ".p12", ".pfx", ".jks", ".keystore"}:
        return Classification(4, "C4", "CRÍTICO", ["almacén-claves"], f"extensión {suffix}")

    # Respaldos operacionales: confidenciales, nunca secretos por nombre.
    if ".bak" in name:
        return Classification(2, "C2", "CONFIDENCIAL", ["respaldo"], "copia de respaldo")

    # C3 — secreto
    if suffix in _SECRET_SUFFIXES:
        return Classification(3, "C3", "SECRETO", ["clave"], f"extensión {suffix}")
    if name.startswith(".env"):
        return Classification(4, "C4", "CRÍTICO", ["entorno"], "archivo de entorno")
    if suffix in {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"}:
        return Classification(3, "C3", "SECRETO", ["base-datos"], "base de datos local")

    # Código y documentación: internos aunque su nombre mencione tokens.
    if suffix in _SOURCE_SUFFIXES:
        return Classification(1, "C1", "INTERNO", ["código"], "código o documentación interna")
    if any(token in name for token in _SECRET_TOKENS):
        return Classification(3, "C3", "SECRETO", ["credencial"], "nombre con indicador de secreto")

    # C2 — confidencial
    if ".git" in parts and "objects" in parts:
        return Classification(2, "C2", "CONFIDENCIAL", ["git-objects"], "objetos de repositorio")
    if any(token in text for token in _CONFIDENTIAL_TOKENS):
        return Classification(2, "C2", "CONFIDENCIAL", ["operacional"], "contenido operacional")
    if suffix in _CONFIG_SUFFIXES:
        return Classification(2, "C2", "CONFIDENCIAL", ["configuración"], f"extensión {suffix}")
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".wav", ".mp3"}:
        return Classification(2, "C2", "CONFIDENCIAL", ["media"], "contenido multimedia privado")

    # C1 — interno
    if suffix in _DOC_SUFFIXES:
        return Classification(1, "C1", "INTERNO", ["documentación"], "documentación interna")

    return Classification(1, "C1", "INTERNO", ["general"], "sin marca específica")


def should_skip(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


# ---------------------------------------------------------------------------
# Detección de secretos y PII
# ---------------------------------------------------------------------------

_SECRET_RULES: Sequence[Tuple[str, str, Severity, re.Pattern[str]]] = (
    (
        "private_key_block",
        "clave privada PEM/OpenPGP",
        Severity.CRITICAL,
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    ),
    (
        "aws_access_key",
        "AWS Access Key",
        Severity.CRITICAL,
        re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    ),
    (
        "google_api_key",
        "Google API Key",
        Severity.CRITICAL,
        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ),
    (
        "openai_key",
        "OpenAI/Anthropic Key",
        Severity.CRITICAL,
        re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{24,}\b"),
    ),
    (
        "github_token",
        "GitHub Token",
        Severity.CRITICAL,
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ),
    (
        "slack_token",
        "Slack Token",
        Severity.HIGH,
        re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    ),
    (
        "telegram_bot_token",
        "Telegram Bot Token",
        Severity.CRITICAL,
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
    ),
    (
        "jwt",
        "JSON Web Token",
        Severity.HIGH,
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    ),
    (
        "generic_secret",
        "Secreto genérico (clave=valor)",
        Severity.HIGH,
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
            r"client[_-]?secret|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s'\"#,;]{8,})"
        ),
    ),
    (
        "connection_string",
        "Cadena de conexión con credenciales",
        Severity.HIGH,
        re.compile(r"\b[a-z][a-z0-9+.\-]{2,}://[^\s:@/]{2,}:[^\s@/]{2,}@[^\s/]+", re.I),
    ),
    (
        "bearer_header",
        "Token Bearer en claro",
        Severity.HIGH,
        re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+([A-Za-z0-9\-._~+/]{16,}=*)"),
    ),
    (
        "credit_card",
        "Posible número de tarjeta",
        Severity.HIGH,
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    (
        "url_key_param",
        "Credencial en parámetro de URL",
        Severity.HIGH,
        re.compile(r"[?&](?:key|token|pass|password|auth|apikey)=([A-Za-z0-9_\-]{10,})"),
    ),
)

_PII_RULES: Sequence[Tuple[str, str, Severity, re.Pattern[str]]] = (
    ("email", "Correo electrónico", Severity.LOW, re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")),
    (
        "phone_mx",
        "Teléfono / WhatsApp",
        Severity.MEDIUM,
        re.compile(r"(?<!\d)(?:\+?52[\s\-]?)?(?:1[\s\-]?)?(?:\d{3}[\s\-]?){2}\d{4}(?!\d)"),
    ),
    (
        "curp",
        "CURP (México)",
        Severity.CRITICAL,
        re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"),
    ),
    (
        "rfc",
        "RFC (México)",
        Severity.HIGH,
        re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"),
    ),
    (
        "iban",
        "IBAN / cuenta bancaria",
        Severity.HIGH,
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
)

_HIGH_ENTROPY_CANDIDATE = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")
_HEX_ONLY = re.compile(r"^[0-9a-fA-F]+$")
_KNOWN_SAFE_PREFIXES = ("sha256:", "sha1:", "md5:", "blake2", "0x")
_PHONE_CONTEXT = re.compile(
    r"(?i)(tel[eé]fono|phone|whatsapp|celular|m[oó]vil|contacto|llamar|marcar|\+52)"
)


def _luhn(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _iban_valid(value: str) -> bool:
    compact = "".join(ch for ch in value.upper() if ch.isalnum())
    if len(compact) < 15 or len(compact) > 34:
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: Dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def redact(value: str, *, keep: int = 4) -> str:
    """Vista segura de un secreto: nunca revela el cuerpo completo."""
    value = value.strip()
    if len(value) <= keep + 2:
        return "…" * len(value)
    return f"{value[:keep]}…{value[-2:]} ({len(value)} ch)"


def _is_probably_text(blob: bytes) -> bool:
    if not blob:
        return True
    if b"\x00" in blob[:4096]:
        return False
    sample = blob[:4096]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(sample) > 0.85


def _entropy_candidates(line: str, path: str, line_no: int) -> List[SecretFinding]:
    findings: List[SecretFinding] = []
    for match in _HIGH_ENTROPY_CANDIDATE.finditer(line):
        token = match.group(0)
        if token.lower().startswith(_KNOWN_SAFE_PREFIXES):
            continue
        if _HEX_ONLY.match(token) and len(token) in (32, 40, 64, 96, 128):
            # Hashes de integridad declarados; se toleran (no son credenciales).
            continue
        if set(token) <= {"0", "1"}:
            continue
        entropy = shannon_entropy(token)
        if entropy >= 4.6 and len(set(token)) >= 12:
            findings.append(
                SecretFinding(
                    path=path,
                    kind="cadena de alta entropía",
                    severity=Severity.MEDIUM,
                    line=line_no,
                    preview=redact(token),
                    rule="high_entropy",
                )
            )
    return findings


_HIGH_CONFIDENCE_RULES = {
    "private_key_block",
    "aws_access_key",
    "google_api_key",
    "openai_key",
    "github_token",
    "slack_token",
    "telegram_bot_token",
    "jwt",
    "connection_string",
    "bearer_header",
}


def scan_text(
    text: str,
    path: str = "<memory>",
    *,
    include_pii: bool = True,
    high_confidence: bool = False,
) -> List[SecretFinding]:
    findings: List[SecretFinding] = []
    if high_confidence:
        rules = [r for r in _SECRET_RULES if r[0] in _HIGH_CONFIDENCE_RULES]
    else:
        rules = list(_SECRET_RULES) + (list(_PII_RULES) if include_pii else [])

    for line_no, line in enumerate(text.splitlines(), start=1):
        if len(line) > 8000:
            line = line[:8000]
        # Marcador de allowlist: sólo válido en pruebas, para fixtures sintéticos.
        if "aegis:allow-secret" in line and (
            Path(path).name.startswith("test_") or "/tests/" in f"/{path.replace(chr(92), '/')}"
        ):
            continue
        for rule_id, kind, severity, pattern in rules:
            match = pattern.search(line)
            if not match:
                continue
            raw = match.group(1) if match.groups() else match.group(0)
            # Descarta falsos positivos obvios de plantillas documentales.
            if rule_id == "generic_secret" and raw.lower() in {
                "cambiame", "changeme", "example", "ejemplo", "your_key_here",
                "xxxxxxxx", "********", "placeholder", "none", "null",
            }:
                continue
            if rule_id == "url_key_param" and (
                raw.lower() in {"changeme", "example", "placeholder", "test", "dummy"}
                or raw.startswith(("$", "{", "%", "YOUR", "your", "TU_", "tu_"))
            ):
                continue
            if rule_id == "generic_secret":
                if (
                    raw.endswith("(")
                    or any(ch in raw for ch in "()[]{}")
                    or raw.startswith(("$", "{", "<", "%", "/", ".", "~"))
                    or raw.startswith(("self.", "match.", "config.", "settings.", "os.", "process."))
                    or raw in {"os.environ", "process.env", "getenv"}
                    or (raw.isidentifier() and raw.islower())
                    or shannon_entropy(raw) < 3.0
                    or len(raw) < 12
                    or not (any(ch.isdigit() for ch in raw) and any(ch.isalpha() for ch in raw))
                    or ("/" in raw and "://" not in raw)
                ):
                    continue
            if rule_id in {"openai_key", "google_api_key"} and any(
                marker in raw.lower()
                for marker in ("1234567890abcdef", "abcdef123456", "example", "test", "dummy")
            ):
                continue
            if rule_id == "credit_card":
                digits = re.sub(r"\D", "", raw)
                if not (13 <= len(digits) <= 19 and _luhn(digits)):
                    continue
            if rule_id == "phone_mx" and not _PHONE_CONTEXT.search(line):
                continue
            if rule_id == "iban" and not _iban_valid(raw):
                continue
            findings.append(
                SecretFinding(
                    path=path,
                    kind=kind,
                    severity=severity,
                    line=line_no,
                    preview=redact(raw),
                    rule=rule_id,
                )
            )
        if not high_confidence:
            findings.extend(_entropy_candidates(line, path, line_no))
    # Deduplica por regla + línea (una credencial por línea).
    seen = set()
    unique: List[SecretFinding] = []
    for f in findings:
        key = (f.rule, f.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def scan_file(
    path: os.PathLike | str,
    *,
    max_bytes: int = 4 << 20,
    include_pii: bool = True,
    high_confidence: bool = False,
) -> List[SecretFinding]:
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return []
    if size == 0 or size > max_bytes:
        return []
    if classify_path(p).level >= 4 and p.suffix == ".enc":
        return []
    try:
        blob = p.read_bytes()
    except OSError:
        return []
    if not _is_probably_text(blob):
        return []
    text = blob.decode("utf-8", errors="ignore")
    return scan_text(text, str(p), include_pii=include_pii, high_confidence=high_confidence)
