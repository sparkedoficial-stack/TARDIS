"""
gemini_bridge.py - Puente de Alto Rendimiento con Google Gemini Heavy (Gemini 2.5 Pro).
=======================================================================================

Capacidades principales:
  1. Acceso al modelo más actual y pesado de Google: `gemini-2.5-pro` (o alternativas
     configurables: `gemini-2.0-pro-exp-02-05`, `gemini-1.5-pro`, `gemini-2.5-flash`).
  2. Integración nativa con la memoria e historial de conversaciones (`gia_memory.py`):
     recupera turnos recientes y turnos semánticamente relevantes vía SQLite FTS5.
  3. Bóveda Cifrada de Privacidad (`gemini_privacy_vault.py`):
     - Sanitización de PII, rutas y claves antes del envío.
     - Almacenamiento local de respuestas en bóveda binaria AES-256-GCM + DPAPI.
  4. Escalado Automático para tareas pesadas (> 2 minutos de procesamiento o contexto masivo).
  5. Búsqueda y Grounding en tiempo real con Google Search.
"""
from __future__ import annotations

import os
import sys
import time
import json
from typing import Generator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from google import genai
    from google.genai import types as gtypes
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

try:
    import ecca_credentials as _creds
except Exception:
    _creds = None

try:
    import gia_memory as _mem
    HAS_MEM = True
except Exception:
    HAS_MEM = False

try:
    import gemini_privacy_vault as _vault
    HAS_VAULT = True
except Exception:
    HAS_VAULT = False

try:
    import agent_context as _ctx
    HAS_CTX = True
except Exception:
    HAS_CTX = False


# Modelos soportados (ordenados por peso / capacidad de razonamiento)
GEMINI_MODELS = {
    "gemini-2.5-pro": {
        "name": "Gemini 2.5 Pro (Flagship Heavy / Deep Reasoning)",
        "context_window": 2000000,
        "is_heavy": True,
        "supports_thinking": True,
        "supports_grounding": True
    },
    "gemini-2.0-pro-exp-02-05": {
        "name": "Gemini 2.0 Pro Experimental (Heavy)",
        "context_window": 2000000,
        "is_heavy": True,
        "supports_thinking": True,
        "supports_grounding": True
    },
    "gemini-2.0-flash-thinking-exp-01-21": {
        "name": "Gemini 2.0 Flash Thinking Exp",
        "context_window": 1000000,
        "is_heavy": True,
        "supports_thinking": True,
        "supports_grounding": True
    },
    "gemini-2.5-flash": {
        "name": "Gemini 2.5 Flash (Ultra Rápido)",
        "context_window": 1000000,
        "is_heavy": False,
        "supports_thinking": True,
        "supports_grounding": True
    },
    "gemini-1.5-pro": {
        "name": "Gemini 1.5 Pro",
        "context_window": 2000000,
        "is_heavy": True,
        "supports_thinking": False,
        "supports_grounding": True
    }
}

DEFAULT_HEAVY_MODEL = "gemini-2.5-pro"
TIMEOUT_HEAVY_SECONDS = 120.0  # Umbral de escalado a 2 minutos


# =====================================================================
#  GESTIÓN DE CLIENTE Y CREDENCIALES
# =====================================================================

def get_api_key() -> str | None:
    """Obtiene la clave de Google resguardada en la bóveda DPAPI o variables de entorno."""
    # 1. Variable de entorno
    if os.environ.get("GOOGLE_API_KEY"):
        return os.environ["GOOGLE_API_KEY"].strip()
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    # 2. Bóveda DPAPI segura
    if _creds:
        k = _creds.get_key("google")
        if k:
            return k.strip()
    return None


def set_api_key(api_key: str) -> bool:
    """Guarda la clave de Google en la bóveda DPAPI del usuario (cifrada)."""
    if not _creds:
        return False
    return _creds.set_key("google", api_key)


def get_client() -> genai.Client:
    """Crea una instancia autenticada de genai.Client."""
    if not HAS_GENAI:
        raise RuntimeError("El SDK 'google-genai' no está instalado. Ejecuta: pip install google-genai")
    key = get_api_key()
    if not key:
        raise ValueError("No se ha configurado la API Key de Google. Usa set_api_key() o la interfaz web.")
    return genai.Client(api_key=key)


# =====================================================================
#  CONSTRUCCIÓN DE CONTEXTO E HISTORIAL
# =====================================================================

def build_system_context(custom_system: str | None = None, include_history_memory: bool = True,
                         query_for_search: str = "", sanitize: bool = True) -> tuple[str, list[str]]:
    """Construye el prompt de sistema inyectando memoria histórica permanente y directrices."""
    redactions_all = []
    base = custom_system or (
        "Eres GIA (Godworks Interactive Assistant), operando a través del puente de alto rendimiento "
        "con Google Gemini. Posees acceso al conocimiento profundo del sistema, memoria contextual "
        "y capacidades avanzadas de síntesis, matemática, código y razonamiento estratégico."
    )

    if HAS_CTX:
        try:
            base = _ctx.apply_to_system(base)
        except Exception:
            pass

    if include_history_memory and HAS_MEM:
        try:
            # Extraer turnos recientes y búsqueda semántica de eventos pasados
            mem_block = _mem.context_block(query=query_for_search, session_id="", n_recent=8, n_relevant=6, max_chars=4500)
            if mem_block:
                base += f"\n\n[HISTORIAL Y MEMORIA DEL SISTEMA GIA]\n{mem_block}"
        except Exception as e:
            print(f"[gemini_bridge] Aviso memoria: {e}", file=sys.stderr)

    if sanitize and HAS_VAULT:
        base, reds = _vault.sanitize_for_cloud(base)
        redactions_all.extend(reds)

    return base, redactions_all


# =====================================================================
#  CONSULTA PRINCIPAL A GEMINI HEAVY
# =====================================================================

def ask_gemini_heavy(
    prompt: str,
    history: list[dict] | None = None,
    model: str = DEFAULT_HEAVY_MODEL,
    system_instruction: str | None = None,
    use_grounding: bool = True,
    thinking_budget: int = -1,
    temperature: float = 0.4,
    sanitize: bool = True,
    privacy_strict: bool = False
) -> dict:
    """
    Ejecuta una inferencia con el modelo más pesado de Gemini (Gemini 2.5 Pro por defecto).
    Retorna un diccionario completo con:
      {
        "ok": bool,
        "reply": str,
        "model": str,
        "provider": "google",
        "elapsed_s": float,
        "tokens_est": int,
        "redactions": list,
        "grounding_chunks": list,
        "error": str | None
      }
    """
    t0 = time.time()
    redactions_all = []

    if not HAS_GENAI:
        return {
            "ok": False,
            "reply": "Error: SDK 'google-genai' no disponible.",
            "error": "SDK_NOT_INSTALLED",
            "provider": "google"
        }

    key = get_api_key()
    if not key:
        return {
            "ok": False,
            "reply": "No hay API Key de Google configurada. Configúrala en la pestaña de Ajustes o con /api/gemini/config.",
            "error": "NO_API_KEY",
            "provider": "google"
        }

    # 1. Sanitización de prompt
    clean_prompt = prompt
    if sanitize and HAS_VAULT:
        clean_prompt, reds = _vault.sanitize_for_cloud(prompt, strict=privacy_strict)
        redactions_all.extend(reds)

    # 2. Construir sistema con memoria histórica
    sys_text, reds_sys = build_system_context(
        custom_system=system_instruction,
        include_history_memory=True,
        query_for_search=prompt,
        sanitize=sanitize
    )
    redactions_all.extend(reds_sys)

    # 3. Formatear historial a formato contents de Gemini
    contents = []
    if history:
        for m in history:
            role = "user" if m.get("role") == "user" else "model"
            c_text = str(m.get("content", ""))
            if sanitize and HAS_VAULT:
                c_text, _ = _vault.sanitize_for_cloud(c_text, strict=privacy_strict)
            contents.append(gtypes.Content(role=role, parts=[gtypes.Part(text=c_text)]))

    # Añadir el prompt actual del usuario
    contents.append(gtypes.Content(role="user", parts=[gtypes.Part(text=clean_prompt)]))

    # 4. Configurar herramientas y parámetros avanzados
    tools = []
    if use_grounding:
        try:
            tools.append(gtypes.Tool(google_search=gtypes.GoogleSearch()))
        except Exception:
            pass

    # Configuración de llamada
    cfg_kwargs = {
        "system_instruction": sys_text,
        "temperature": temperature,
    }
    if tools:
        cfg_kwargs["tools"] = tools

    # Configurar Thinking para modelos compatibles
    model_meta = GEMINI_MODELS.get(model, {})
    if model_meta.get("supports_thinking", True) and thinking_budget is not None:
        try:
            # thinking_budget: -1 para dinámico/automático, o número entero de tokens
            cfg_kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass

    config = gtypes.GenerateContentConfig(**cfg_kwargs)

    # 5. Ejecutar la llamada con cliente Google GenAI
    try:
        client = get_client()
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        reply_text = (response.text or "").strip()
        elapsed_s = round(time.time() - t0, 2)

        # Extraer fuentes de grounding si las hay
        grounding_sources = []
        try:
            if hasattr(response, "candidates") and response.candidates:
                cand = response.candidates[0]
                if hasattr(cand, "grounding_metadata") and cand.grounding_metadata:
                    gm = cand.grounding_metadata
                    if hasattr(gm, "grounding_chunks") and gm.grounding_chunks:
                        for chunk in gm.grounding_chunks:
                            if hasattr(chunk, "web") and chunk.web:
                                grounding_sources.append({
                                    "title": getattr(chunk.web, "title", "Web Source"),
                                    "url": getattr(chunk.web, "uri", "")
                                })
        except Exception:
            pass

        # 6. Almacenar en bóveda cifrada local (AES-256-GCM)
        if HAS_VAULT:
            _vault.save_encrypted_interaction(
                prompt=clean_prompt,
                reply=reply_text,
                model=model,
                meta={"elapsed_s": elapsed_s, "grounding_count": len(grounding_sources)}
            )

        # 7. Registrar en el historial maestro de GIA
        if HAS_MEM:
            try:
                _mem.log("gemini_bridge", "assistant", reply_text, session_id="gemini",
                         meta={"model": model, "elapsed_s": elapsed_s})
            except Exception:
                pass

        tokens_est = max(1, len(reply_text) // 4)

        return {
            "ok": True,
            "reply": reply_text,
            "model": model,
            "provider": "google",
            "elapsed_s": elapsed_s,
            "tokens_est": tokens_est,
            "redactions": list(set(redactions_all)),
            "grounding_sources": grounding_sources,
            "is_heavy": True,
            "error": None
        }

    except Exception as e:
        elapsed_s = round(time.time() - t0, 2)
        err_msg = str(e)
        print(f"[gemini_bridge] Error en llamada a Gemini ({model}): {err_msg}", file=sys.stderr)

        # Si el modelo pesado falla por disponibilidad o cuota, intentar fallback suave
        if model != "gemini-2.5-flash" and ("404" in err_msg or "not found" in err_msg.lower() or "quota" in err_msg.lower()):
            print("[gemini_bridge] Reintentando con fallback gemini-2.5-flash...", file=sys.stderr)
            try:
                return ask_gemini_heavy(
                    prompt=prompt,
                    history=history,
                    model="gemini-2.5-flash",
                    system_instruction=system_instruction,
                    use_grounding=False,
                    sanitize=sanitize
                )
            except Exception as fb_err:
                err_msg = f"{err_msg} | Fallback error: {fb_err}"

        return {
            "ok": False,
            "reply": f"No se pudo completar la consulta con Gemini ({model}): {err_msg}",
            "model": model,
            "provider": "google",
            "elapsed_s": elapsed_s,
            "error": err_msg
        }


# =====================================================================
#  ESTADO Y PRUEBA DE CONECTIVIDAD
# =====================================================================

def test_connection() -> dict:
    """Verifica la conectividad y mide la latencia de Gemini 2.5 Pro."""
    t0 = time.time()
    key = get_api_key()
    if not key:
        return {"ok": False, "error": "No hay API Key configurada"}

    try:
        client = get_client()
        # Prueba ligera con un ping semántico
        resp = client.models.generate_content(
            model=DEFAULT_HEAVY_MODEL,
            contents="Responde únicamente con la palabra: ACTIVO",
            config=gtypes.GenerateContentConfig(temperature=0.1)
        )
        latency_ms = round((time.time() - t0) * 1000, 1)
        text = (resp.text or "").strip()
        return {
            "ok": True,
            "status": "ONLINE",
            "model": DEFAULT_HEAVY_MODEL,
            "latency_ms": latency_ms,
            "reply": text,
            "key_hint": _creds._hint(key) if _creds else "****"
        }
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 1)
        return {
            "ok": False,
            "status": "ERROR",
            "error": str(e),
            "latency_ms": latency_ms
        }


def get_bridge_status() -> dict:
    """Retorna el estado global del puente Gemini, bóveda y modelos disponibles."""
    key = get_api_key()
    vault_st = _vault.get_vault_status() if HAS_VAULT else {}
    return {
        "ok": True,
        "has_key": bool(key),
        "key_hint": _creds._hint(key) if (_creds and key) else "",
        "default_model": DEFAULT_HEAVY_MODEL,
        "available_models": [
            {"id": k, "name": v["name"], "context_window": v["context_window"], "is_heavy": v["is_heavy"]}
            for k, v in GEMINI_MODELS.items()
        ],
        "timeout_heavy_threshold_s": TIMEOUT_HEAVY_SECONDS,
        "sdk_installed": HAS_GENAI,
        "vault": vault_st
    }


if __name__ == "__main__":
    print(json.dumps(get_bridge_status(), indent=2, ensure_ascii=False))
