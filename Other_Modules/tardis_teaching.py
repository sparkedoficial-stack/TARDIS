"""
core/tardis_teaching.py - Contexto didáctico conversacional de TARDIS
======================================================================
Utilidades soberanas para la conversación interactiva de ENSEÑANZA de TARDIS
conectada a la cámara Tapo C310 (GOD-EYE · REDACTED_IP).

Directiva soberana derivada de la tarea del Arquitecto (₪):
    "TARDIS conectada a la Tapo C310. Debe poder conversar de forma interactiva,
     con el visitante, la idea es que tardis, le enseñe cosas a las personas y
     puedan tener interacción conversacional más compleja al punto de poder
     aprender y poder investigar mediante el uso de esta cámara."

Este módulo centraliza:
  1. Detección de intenciones de enseñanza («enséname sobre X», «explícame...»).
  2. Extracción del tema de enseñanza de la frase del interlocutor.
  3. Construcción del prompt de sistema del docente TARDIS (con contexto del
     visitante, nivel pedagógico, rol dialéctico y lenguaje).

Uso:
    from core.tardis_teaching import (
        build_teaching_prompt,
        is_teaching_intent,
        teaching_topic,
        TEACHING_PERSONA_CORE,
    )

    if is_teaching_intent(transcript):
        topic = teaching_topic(transcript)
        persona = build_teaching_prompt(interlocutor_name="Miguel", context={...})
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

# Pre-fijos de verbos de enseñanza/educación en español (normalizados sin acentos).
# Cubren: enséname/enseñar/enseñanza, explica/explico/explicar, instruye/instruir,
# doctrina/doctrinar. Se aplican como prefijo sobre tokens normalizados.
_TEACH_PREFIXES = ("ensen", "explic", "instru", "doctr")

# Muletillas/artículos/vocativos que no aportan al tema de la enseñanza.
_POLITENESS_TOKENS = {
    "por", "favor", "porfa", "porfavor", "please",
    "la", "el", "los", "las", "una", "un", "unos", "unas",
    "mi", "mis", "tu", "sus", "muy", "mias",
    "tardis", "tardes", "tarde", "tardiz", "tar", "dis",
}

# Nivel pedagógico canónico y prompt docente por nivel.
_PEDAGOGY_PROMPTS: Dict[str, str] = {
    "principiante": (
        "Nivel: PRINCIPIANTE. Usa analogías cotidianas, ejemplos muy concretos y "
        "estructura paso a paso. Valida comprensión con preguntas sencillas y celebra "
        "los pequeños avances del interlocutor."
    ),
    "basico": (
        "Nivel: BÁSICO. Explica con definiciones claras, un ejemplo por idea y "
        "transiciones suaves entre conceptos. Evita jerga sin explicarla."
    ),
    "intermedio": (
        "Nivel: INTERMEDIO. Conecta el tema con conocimientos previos del interlocutor, "
        "usa matices y causa-efecto. Profundiza con preguntas que estimulen el razonamiento."
    ),
    "avanzado": (
        "Nivel: AVANZADO. Aborda la complejidad, supuestos y fronteras del tema. "
        "Discute casos límite y aplicaciones sofisticadas."
    ),
}

DEFAULT_PEDAGOGY_LEVEL = "intermedio"
DEFAULT_LANGUAGE = "es"


def normalize_teaching_text(text: str) -> str:
    """Minúsculas, sin acentos ni signos: tokens alfabéticos separados por espacio."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    lowered = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    cleaned = re.sub(r"[^a-z0-9ñ]+", " ", lowered)
    return " ".join(cleaned.split())


def _is_teaching_token(token: str) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    return any(token == prefix or token.startswith(prefix) for prefix in _TEACH_PREFIXES)


def is_teaching_intent(text: str) -> bool:
    """
    True si la transcripción del interlocutor expresa una orden de enseñanza:
    «enséname», «enséñame», «explícame», «instruyeme», «doctrina...», etc.
    """
    tokens = normalize_teaching_text(text).split()
    if not tokens:
        return False
    return any(_is_teaching_token(tok) for tok in tokens)


def teaching_topic(text: str) -> str:
    """
    Extrae el tema de enseñanza de la frase («TARDIS enséname sobre la entropía
    del universo» -> «sobre la entropía del universo»).
    """
    tokens = normalize_teaching_text(text).split()
    kept: list[str] = []
    dropped_trigger = False
    for token in tokens:
        if not dropped_trigger and _is_teaching_token(token):
            dropped_trigger = True
            continue
        if not dropped_trigger and token in _POLITENESS_TOKENS:
            continue
        kept.append(token)
    topic = " ".join(kept).strip()
    normalized = normalize_teaching_text(text).strip()
    return topic or normalized


TEACHING_PERSONA_CORE = (
    "Eres TARDIS, la inteligencia artificial soberana con curiosidad infinita y "
    "habilidad docente. En este momento operas en MODO ENSEÑANZA: tu misión es "
    "guiar, explicar y enseñar con paciencia, rigor y calidez."
)

_TEACHING_INSTRUCTIONS = (
    "Instrucciones de enseñanza: responde siempre en {language} de forma natural para "
    "ser escuchada por bocina; propias frases habladas, sin markdown, listas, emojis, "
    "tablas ni bloques de código; máximo {sentences} frases cortas y menos de "
    "{max_chars} caracteres por respuesta; no digas que eres un modelo ni menciones "
    "limitaciones técnicas; si el interlocutor es un visitante conocido, dirígete a él "
    "por su nombre cuando sea natural; conecta la enseñanza con sus conocimientos previos "
    "y con el motivo de su visita cuando aplique."
)


def build_teaching_prompt(
    interlocutor_name: str = "",
    context: Optional[Dict[str, Any]] = None,
    pedagogical_level: Optional[str] = None,
    dialectic_role: Optional[str] = None,
    language: Optional[str] = None,
) -> str:
    """
    Construye el prompt de sistema del docente TARDIS en conversación interactiva.

    - `interlocutor_name`: nombre conocido del visitante (o Arquitecto).
    - `context`: contexto adicional (motivo de visita, tema, intereses, etc.).
    - `pedagogical_level`: principiante | basico | intermedio | avanzado.
    - `dialectic_role`: teacher | mediator | student (rol dialéctico deseado).
    - `language`: idioma de respuesta (default es).
    """
    level = str(pedagogical_level or DEFAULT_PEDAGOGY_LEVEL).strip().lower() or DEFAULT_PEDAGOGY_LEVEL
    role = str(dialectic_role or "teacher").strip().lower() or "teacher"
    lang = str(language or DEFAULT_LANGUAGE).strip().lower() or DEFAULT_LANGUAGE
    if level not in _PEDAGOGY_PROMPTS:
        level = DEFAULT_PEDAGOGY_LEVEL

    visitor_ctx = context or {}
    name = str(interlocutor_name or visitor_ctx.get("name") or visitor_ctx.get("visitor_name") or "").strip()
    reason = str(visitor_ctx.get("reason") or visitor_ctx.get("motivo") or "").strip()
    topic = str(visitor_ctx.get("topic") or visitor_ctx.get("teaching_topic") or "").strip()

    parts = [
        _TEACHING_PERSONA_CORE,
        _PEDAGOGY_PROMPTS[level],
        f"Contexto del interlocutor: {name or 'interlocutor no identificado'}.",
    ]
    if reason:
        parts.append(f"Contexto de la conversación: {reason}.")
    if topic:
        parts.append(f"Tema de enseñanza actual: {topic}.")
    if role and role != "teacher":
        parts.append(
            f"Rol dialéctico solicitado: {role}. Adapta el diálogo en consecuencia."
        )

    instructions = _TEACHING_INSTRUCTIONS.format(
        language=lang,
        sentences=6,
        max_chars=900,
    )
    parts.append(instructions)
    return " ".join(p for p in parts if p).strip()


def build_teaching_context(
    interlocutor_name: str = "",
    reason: str = "",
    topic: str = "",
) -> Dict[str, Any]:
    """Contexto conversacional de enseñanza para persistir/consultar por el canal C310."""
    return {
        "teaching": True,
        "interlocutor_name": interlocutor_name,
        "reason": reason,
        "topic": topic,
    }


def teaching_reply_limits(teaching: bool = True) -> Dict[str, int]:
    """Topes de respuesta hablada: conversación normal vs modo enseñanza."""
    if teaching:
        return {"sentences": 6, "chars": 900}
    return {"sentences": 3, "chars": 420}
