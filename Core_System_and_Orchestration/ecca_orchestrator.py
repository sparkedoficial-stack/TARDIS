"""
ecca_orchestrator.py - ECCA: orquestador multi-modelo (local + cloud).
======================================================================

ECCA enruta cada peticion al mejor modelo disponible:
  - LOCAL primero (Ollama) -> privacidad y costo cero por defecto.
  - CLOUD cuando aporta (Claude / GPT / Gemini), solo si hay API key.

Funciona HOY 100% local. En cuanto guardes una API key (via
ecca_credentials), ECCA empieza a enrutar a ese proveedor segun el tipo
de tarea, con fallback automatico a local si el proveedor falla.

Politica de enrutado (local-first + mejor-modelo-por-tarea):
    chat / simple / privado      -> local
    codigo                       -> Claude (anthropic) si hay key, si no local
    razonamiento complejo        -> Claude si hay key, si no local
    contexto muy largo           -> Gemini si hay key, si no Claude, si no local
    generalista                  -> GPT si hay key, si no Claude, si no local
`prefer=` fuerza un proveedor concreto.

Adaptadores: usan el SDK oficial de cada proveedor (import perezoso).
Si el SDK no esta instalado, ECCA lo reporta y cae a local.

API:
    route(messages, task_type="auto", prefer=None, system=None) -> dict
        {ok, reply, provider, model, error}
    providers_status() -> dict
    classify(text) -> str
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

try:
    import ecca_credentials as _creds
except Exception:
    _creds = None

OLLAMA = "http://REDACTED_IP:11434"

# Enruta al mejor nodo local del cluster si esta disponible
try:
    import distributed_compute as _cluster
except Exception:
    _cluster = None

# Modelos por defecto (editables por env var). Los cloud pueden cambiar de ID
# con el tiempo; se sobreescriben con ECCA_<PROVIDER>_MODEL.
DEFAULT_MODELS = {
    # General por defecto (persona + conversación). Optimizado con llama3.2:3b (GPU ultrarrápido).
    "local":     os.environ.get("ECCA_LOCAL_MODEL", "Llama-3.2-3B-Instruct-uncensored-GGUF:latest"),
    "anthropic": os.environ.get("ECCA_ANTHROPIC_MODEL", "claude-opus-4-8"),
    "openai":    os.environ.get("ECCA_OPENAI_MODEL", "gpt-4o"),
    "google":    os.environ.get("ECCA_GOOGLE_MODEL", "gemini-2.5-flash"),
}


# =====================================================================
#  CLASIFICADOR DE TAREA (heuristica ligera)
# =====================================================================

def classify(text: str) -> str:
    t = (text or "").lower()
    n = len(t)
    code_kw = ("codigo", "código", "python", "funcion", "función", "script",
               "vectorscript", "bug", "error", "compila", "def ", "class ",
               "regex", "sql", "api", "refactor")
    reason_kw = ("analiza", "razona", "demuestra", "plan", "estrategia",
                 "compara", "por que", "por qué", "explica a fondo",
                 "paso a paso", "optimiza")
    if n > 12000:
        return "long_context"
    if any(k in t for k in code_kw):
        return "code"
    if any(k in t for k in reason_kw):
        return "reasoning"
    if n < 200:
        return "simple"
    return "general"


# =====================================================================
#  SELECTOR DE PROVEEDOR
# =====================================================================

def _has(provider: str) -> bool:
    if provider in ("chinese", "deepseek", "siliconflow", "zhipu", "qwen", "groq"):
        try:
            from core.chinese_cloud_api import get_chinese_cloud_api
            st = get_chinese_cloud_api().get_status()
            return st.get("enabled", False) and (st.get("has_key", False) or st.get("active_provider") in ("openrouter", "zhipu"))
        except Exception:
            return False
    return bool(_creds and _creds.has_key(provider))


def _pick_provider(task_type: str, prefer: str | None) -> str:
    if prefer:
        prefer = prefer.lower()
        if prefer in ("chinese", "deepseek", "siliconflow", "zhipu", "qwen", "groq"):
            return "chinese"
        if prefer == "local" or _has(prefer):
            return prefer
    # Local-first para lo privado/simple
    if task_type in ("simple", "chat", "private"):
        return "local"
    if task_type in ("code", "reasoning"):
        if _has("chinese"):
            return "chinese"
        return "anthropic" if _has("anthropic") else "local"
    if task_type == "long_context":
        if _has("chinese"):
            return "chinese"
        return "anthropic" if _has("anthropic") else "local"
    # general
    for p in ("openai", "anthropic"):
        if _has(p):
            return p
    if _has("chinese"):
        return "chinese"
    return "local"


# =====================================================================
#  ADAPTADORES
# =====================================================================

def _local_endpoint(model: str) -> str:
    if _cluster:
        try:
            return _cluster.get_endpoint(model)
        except Exception:
            pass
    return OLLAMA


def _adapter_local(messages, system, model) -> dict:
    try:
        import gia_sovereign_engine as _gse
        res = _gse.get_engine().chat(messages, model=model, system=system)
        if res.get("ok"):
            return {
                "ok": True,
                "reply": res.get("reply", ""),
                "provider": "local",
                "model": res.get("model", model),
                "node": res.get("node", "local_sovereign")
            }
    except Exception:
        pass

    msgs = list(messages)
    if system:
        msgs = [{"role": "system", "content": system}] + msgs
    endpoint = _local_endpoint(model)
    try:
        r = httpx.post(f"{endpoint}/api/chat", json={
            "model": model, "messages": msgs, "stream": False,
            "options": {
                "temperature": 0.3,
                "num_ctx": 2048,
                "num_predict": 256,
                "num_thread": 8,
                "num_gpu": 99,
                "use_mmap": True,
                "num_batch": 512,
            },
            "keep_alive": "24h",
        }, timeout=None)
        r.raise_for_status()
        reply = (r.json().get("message", {}).get("content") or "").strip()
        return {"ok": True, "reply": reply, "provider": "local",
                "model": model, "node": endpoint}
    except Exception as ex:
        # Último recurso por tubería directa
        try:
            import gia_sovereign_engine as _gse
            chunks = list(_gse.get_engine()._pipe_chat_stream(msgs, model, system_prompt=system))
            reply = "".join(chunks).strip()
            if reply:
                return {"ok": True, "reply": reply, "provider": "local_pipe",
                        "model": model, "node": "direct_pipe"}
        except Exception:
            pass
        return {"ok": False, "provider": "local", "error": f"Fallo de conexión local: {ex}"}


def _adapter_anthropic(messages, system, model) -> dict:
    try:
        import anthropic
    except ImportError:
        return {"ok": False, "provider": "anthropic",
                "error": "SDK no instalado: pip install anthropic"}
    key = _creds.get_key("anthropic")
    client = anthropic.Anthropic(api_key=key)
    # Separar system; el resto se mapea 1:1 (roles user/assistant)
    conv = [m for m in messages if m.get("role") in ("user", "assistant")]
    if not conv or conv[0]["role"] != "user":
        conv = [{"role": "user", "content": " "}] + conv
    sys_block = ([{"type": "text", "text": system,
                   "cache_control": {"type": "ephemeral"}}] if system else None)
    complex_task = classify(conv[-1].get("content", "")) in ("code", "reasoning", "long_context")
    kwargs = dict(model=model, max_tokens=8000, messages=conv)
    if sys_block:
        kwargs["system"] = sys_block
    if complex_task:
        kwargs["thinking"] = {"type": "adaptive"}  # adaptive para tareas dificiles
    resp = client.messages.create(**kwargs)
    reply = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return {"ok": True, "reply": reply, "provider": "anthropic", "model": model}


def _adapter_openai(messages, system, model) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        return {"ok": False, "provider": "openai",
                "error": "SDK no instalado: pip install openai"}
    key = _creds.get_key("openai")
    client = OpenAI(api_key=key)
    msgs = list(messages)
    if system:
        msgs = [{"role": "system", "content": system}] + msgs
    resp = client.chat.completions.create(model=model, messages=msgs)
    reply = (resp.choices[0].message.content or "").strip()
    return {"ok": True, "reply": reply, "provider": "openai", "model": model}


def _adapter_chinese(messages, system, model) -> dict:
    try:
        from core.chinese_cloud_api import get_chinese_cloud_api
        api = get_chinese_cloud_api()
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        res = api.chat_completion(msgs, model=model)
        if res.get("ok"):
            return {
                "ok": True,
                "reply": res.get("reply", ""),
                "provider": res.get("provider", "chinese_cloud"),
                "model": res.get("model", model),
                "tokens_per_sec": res.get("tokens_per_sec", 0.0),
                "elapsed_s": res.get("elapsed_s", 0.0)
            }
        return {"ok": False, "provider": "chinese_cloud", "error": res.get("error")}
    except Exception as e:
        return {"ok": False, "provider": "chinese_cloud", "error": str(e)}


_ADAPTERS = {
    "local": _adapter_local,
    "anthropic": _adapter_anthropic,
    "openai": _adapter_openai,
    "chinese": _adapter_chinese,
}


# =====================================================================
#  ORQUESTADOR
# =====================================================================

def route(messages: list, task_type: str = "auto", prefer: str | None = None,
          system: str | None = None, model: str | None = None) -> dict:
    """Enruta la conversacion al mejor proveedor. messages: [{role,content}].

    model : fuerza un modelo concreto (p.ej. el que el usuario eligio en la
            interfaz). Sin esto, el selector de modelo de la UI no tendria
            efecto: route() impondria siempre su DEFAULT_MODELS.
    """
    if not messages:
        return {"ok": False, "error": "sin mensajes"}
    if task_type == "auto":
        last_user = next((m["content"] for m in reversed(messages)
                          if m.get("role") == "user"), "")
        task_type = classify(last_user)

    provider = _pick_provider(task_type, prefer)
    # Si el llamador pide un modelo explicito, manda sobre el default.
    # Un modelo local elegido a mano ancla el enrutado a local: no tendria
    # sentido pedir "llama3.1:8b" y que la peticion acabe en un proveedor
    # cloud que no lo tiene.
    chosen = (model or "").strip()
    if chosen:
        if chosen in ("local", DEFAULT_MODELS["local"]) or ":" in chosen:
            provider = "local" if not prefer else provider
        model_id = chosen
    else:
        model_id = DEFAULT_MODELS.get(provider, DEFAULT_MODELS["local"])

    adapter = _ADAPTERS.get(provider, _adapter_local)
    try:
        result = adapter(messages, system, model_id)
        if result.get("ok"):
            result["task_type"] = task_type
            return result
        # Adaptador cloud fallo (sin SDK, sin key) -> fallback local
        fb = _adapter_local(messages, system,
                            chosen if (chosen and ":" in chosen)
                            else DEFAULT_MODELS["local"])
        fb["task_type"] = task_type
        fb["fallback_from"] = provider
        fb["fallback_reason"] = result.get("error", "")
        return fb
    except Exception as e:  # noqa: BLE001
        # Cualquier error del proveedor -> fallback local
        try:
            fb = _adapter_local(messages, system,
                                chosen if (chosen and ":" in chosen)
                                else DEFAULT_MODELS["local"])
            fb["task_type"] = task_type
            fb["fallback_from"] = provider
            fb["fallback_reason"] = f"{type(e).__name__}: {e}"
            return fb
        except Exception as e2:  # noqa: BLE001
            return {"ok": False, "error": f"todos fallaron: {e} / {e2}"}


def providers_status() -> dict:
    """Estado de proveedores para la UI: cuales tienen key y modelo por defecto."""
    out = {"local": {"available": True, "model": DEFAULT_MODELS.get("local", ""),
                     "has_key": True}}
    cred_status = _creds.status() if _creds else {}
    for p in ("anthropic", "openai", "google"):
        cs = cred_status.get(p, {})
        out[p] = {
            "available": bool(cs.get("has_key")),
            "has_key": bool(cs.get("has_key")),
            "hint": cs.get("hint", ""),
            "model": DEFAULT_MODELS.get(p, ""),
        }
    return out


# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import json
    args = sys.argv[1:]
    if not args or args[0] == "status":
        print(json.dumps(providers_status(), indent=2, ensure_ascii=False))
    elif args[0] == "ask":
        msg = " ".join(args[1:]) or "Hola, preséntate en una frase."
        prefer = os.environ.get("ECCA_PREFER")
        r = route([{"role": "user", "content": msg}], prefer=prefer)
        print(json.dumps({k: v for k, v in r.items() if k != "reply"},
                         ensure_ascii=False))
        print("\n" + (r.get("reply") or "[sin respuesta]"))
    else:
        print("uso: ecca_orchestrator.py [status | ask <mensaje>]")
