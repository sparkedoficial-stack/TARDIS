#!/usr/bin/env python3
"""
GODWORKS · FTL & TARDIS External Free Inference Provider
=========================================================
Proveedor externo de inferencia gratuito (cero costo, cero API key obligatoria)
con streaming SSE nativo, pooling HTTP keep-alive y soporte multi-proveedor:

  1. Pollinations AI (https://text.pollinations.ai/openai)
     - 100% gratuito, sin API key requerida (tier anonymous, GPT-OSS 20B / OVH).
     - Compatible con OpenAI Chat Completions + streaming SSE real.
     - Independencia total de OpenCode y de la GPU local (cero carga en RTX 3050).

  2. Proveedores gratuitos opcionales por API key (auto-detectados si existen
     en entorno o en ~/.config/tardis/secrets/):
     - Groq        (GROQ_API_KEY)       -> llama-3.3-70b-versatile
     - OpenRouter  (OPENROUTER_API_KEY) -> meta-llama/llama-3.3-70b-instruct:free
     - Cerebras    (CEREBRAS_API_KEY)   -> llama3.1-8b
     - Mistral     (MISTRAL_API_KEY)    -> mistral-small-latest
     - HuggingFace (HF_TOKEN)           -> router.huggingface.co/v1

  3. Fallback local soberano (TemporalBrain IPC /tmp/temporal_brain.sock)
     para continuidad sin conexión a Internet.

Expone:
  - `ExternalChatRunner`: interfaz de eventos normalizados 100% compatible con
    `chat_engine.ChatRunner` para TUI (`ftl chat`) y Web (`:8765/chat`).
  - `chat()` / `stream_chat()` / `probe()` para `omni_temporal_control.py` y
    telemetría del sistema TARDIS.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

import httpx
import runtime_env

SECRETS_DIR = Path.home() / ".config" / "tardis" / "secrets"
TEMPORAL_BRAIN_SOCK = Path("/tmp/temporal_brain.sock")

DEFAULT_SYSTEM_PROMPT = (
    "Eres TARDIS (GODWORKS SYSTEM · FTL), asistente de inteligencia artificial "
    "soberano de alta precisión técnica. Responde en español de forma clara, "
    "directa y estructurada salvo que el usuario escriba en otro idioma."
)


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    base_url: str
    default_model: str
    env_key: str = ""          # vacío = sin API key requerida
    secret_file: str = ""      # nombre opcional en ~/.config/tardis/secrets/
    timeout_s: float = 45.0
    requires_key: bool = False
    is_unix_socket: bool = False


PROVIDERS: Dict[str, ProviderSpec] = {
    "pollinations": ProviderSpec(
        id="pollinations",
        name="Pollinations AI (Free External · GPT-OSS 20B)",
        base_url="https://text.pollinations.ai/openai",
        default_model="openai-fast",
        timeout_s=45.0,
        requires_key=False,
    ),
    "groq": ProviderSpec(
        id="groq",
        name="Groq Cloud (Free Tier)",
        base_url="https://api.groq.com/openai/v1/chat/completions",
        default_model="llama-3.3-70b-versatile",
        env_key="GROQ_API_KEY",
        secret_file="groq_api_key",
        timeout_s=30.0,
        requires_key=True,
    ),
    "openrouter": ProviderSpec(
        id="openrouter",
        name="OpenRouter (Free Tier)",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        env_key="OPENROUTER_API_KEY",
        secret_file="openrouter_api_key",
        timeout_s=40.0,
        requires_key=True,
    ),
    "cerebras": ProviderSpec(
        id="cerebras",
        name="Cerebras Cloud (Free Tier)",
        base_url="https://api.cerebras.ai/v1/chat/completions",
        default_model="llama3.1-8b",
        env_key="CEREBRAS_API_KEY",
        secret_file="cerebras_api_key",
        timeout_s=30.0,
        requires_key=True,
    ),
    "mistral": ProviderSpec(
        id="mistral",
        name="Mistral AI (Free Tier)",
        base_url="https://api.mistral.ai/v1/chat/completions",
        default_model="mistral-small-latest",
        env_key="MISTRAL_API_KEY",
        secret_file="mistral_api_key",
        timeout_s=35.0,
        requires_key=True,
    ),
    "huggingface": ProviderSpec(
        id="huggingface",
        name="HuggingFace Router (Free Tier)",
        base_url="https://router.huggingface.co/v1/chat/completions",
        default_model="Qwen/Qwen2.5-72B-Instruct",
        env_key="HF_TOKEN",
        secret_file="hf_token",
        timeout_s=40.0,
        requires_key=True,
    ),
    "local": ProviderSpec(
        id="local",
        name="TARDIS Temporal Brain (Local IPC)",
        base_url="http://localhost/v1/chat/completions",
        default_model="TARDIS-NEURAL-SPACE-KAIJU",
        timeout_s=90.0,
        requires_key=False,
        is_unix_socket=True,
    ),
}

EXTERNAL_PREFIXES = tuple(f"{pid}/" for pid in PROVIDERS.keys()) + ("external/",)

# ---------------------------------------------------------------------------
# Pool de clientes HTTP persistentes (reutiliza conexiones TCP/TLS y UDS)
# ---------------------------------------------------------------------------
_CLIENT_LOCK = threading.Lock()
_HTTP_CLIENT: Optional[httpx.Client] = None
_UDS_CLIENT: Optional[httpx.Client] = None
_PROBE_CACHE: Dict[str, Dict[str, Any]] = {}


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    with _CLIENT_LOCK:
        if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
            _HTTP_CLIENT = httpx.Client(
                timeout=httpx.Timeout(connect=8.0, read=45.0, write=15.0, pool=8.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60.0),
                follow_redirects=True,
                headers={"User-Agent": "TARDIS-FTL/26.4"},
            )
        return _HTTP_CLIENT


def _get_uds_client() -> httpx.Client:
    global _UDS_CLIENT
    with _CLIENT_LOCK:
        if _UDS_CLIENT is None or _UDS_CLIENT.is_closed:
            transport = httpx.HTTPTransport(uds=str(TEMPORAL_BRAIN_SOCK))
            _UDS_CLIENT = httpx.Client(
                transport=transport,
                base_url="http://localhost",
                timeout=httpx.Timeout(connect=4.0, read=90.0, write=10.0, pool=5.0),
            )
        return _UDS_CLIENT


def _read_api_key(spec: ProviderSpec) -> str:
    if not spec.requires_key:
        return ""
    if spec.env_key:
        val = (os.environ.get(spec.env_key) or "").strip()
        if val:
            return val
    if spec.secret_file:
        path = SECRETS_DIR / spec.secret_file
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def is_external_model(model_ref: str) -> bool:
    ref = (model_ref or "").strip().lower()
    return ref.startswith(EXTERNAL_PREFIXES)


def parse_model_ref(model_ref: str) -> tuple[ProviderSpec, str]:
    """Convierte 'pollinations/openai-fast' -> (ProviderSpec, 'openai-fast')."""
    raw = (model_ref or "pollinations/openai-fast").strip()
    clean = raw.split("#", 1)[0]
    if "/" not in clean:
        spec = PROVIDERS.get(clean.lower(), PROVIDERS["pollinations"])
        return spec, spec.default_model
    prefix, rest = clean.split("/", 1)
    pid = prefix.lower()
    if pid == "external":
        pid = "pollinations"
    spec = PROVIDERS.get(pid, PROVIDERS["pollinations"])
    model_name = rest.strip() or spec.default_model
    return spec, model_name


def configured_providers() -> List[Dict[str, Any]]:
    """Lista los proveedores externos disponibles en este host (sin exponer claves)."""
    rows: List[Dict[str, Any]] = []
    for pid, spec in PROVIDERS.items():
        if spec.is_unix_socket:
            ready = TEMPORAL_BRAIN_SOCK.exists()
        elif not spec.requires_key:
            ready = True
        else:
            ready = bool(_read_api_key(spec))
        cached = _PROBE_CACHE.get(pid) or {}
        rows.append({
            "id": pid,
            "name": spec.name,
            "ref": f"{pid}/{spec.default_model}",
            "default_model": spec.default_model,
            "requires_key": spec.requires_key,
            "configured": ready,
            "available": cached.get("available"),
            "latency_s": cached.get("latency_s"),
            "checked_at": cached.get("checked_at"),
            "error": cached.get("error", ""),
        })
    return rows


def best_external_ref() -> str:
    """Devuelve el mejor proveedor externo gratuito listo para usar de inmediato."""
    # Prioridad: si hay clave free-tier ultrarrápida (Groq/Cerebras/OpenRouter), usarla;
    # si no, Pollinations AI (cero API key, siempre disponible).
    for pid in ("groq", "cerebras", "openrouter", "mistral", "pollinations"):
        spec = PROVIDERS[pid]
        if not spec.requires_key or _read_api_key(spec):
            return f"{pid}/{spec.default_model}"
    return "pollinations/openai-fast"


def _build_headers(spec: ProviderSpec) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
    }
    key = _read_api_key(spec)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if spec.id == "openrouter":
        headers["HTTP-Referer"] = "https://tardis.local"
        headers["X-Title"] = "TARDIS FTL Chat"
    return headers


def _extract_delta(chunk: Dict[str, Any]) -> tuple[str, str, Optional[Dict[str, int]]]:
    """Extrae (text_delta, thinking_delta, usage_dict) de un chunk OpenAI SSE."""
    choices = chunk.get("choices") or []
    text = ""
    thinking = ""
    if choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta") or choices[0].get("message") or {}
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                text = content
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                thinking = reasoning
    usage_raw = chunk.get("usage")
    usage = None
    if isinstance(usage_raw, dict) and (usage_raw.get("prompt_tokens") or usage_raw.get("completion_tokens")):
        usage = {
            "input": int(usage_raw.get("prompt_tokens") or 0),
            "output": int(usage_raw.get("completion_tokens") or 0),
        }
    return text, thinking, usage


def build_messages_from_session(
    prompt: str,
    session_messages: Optional[Sequence[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
    files: Optional[Sequence[str]] = None,
    max_history: int = 12,
) -> List[Dict[str, str]]:
    """Construye el arreglo OpenAI `messages` conservando continuidad conversacional."""
    msgs: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT}
    ]
    if session_messages:
        # Filtrar sólo user/assistant previos (evitando duplicar el prompt actual si ya fue guardado al final)
        filtered = [
            m for m in session_messages
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
        ]
        if filtered and filtered[-1].get("role") == "user" and filtered[-1].get("content", "").strip() == prompt.strip():
            filtered = filtered[:-1]
        for m in filtered[-max_history:]:
            content = str(m.get("content") or "")
            if len(content) > 4000:
                content = content[:4000] + "\n…[truncado]"
            msgs.append({"role": m["role"], "content": content})

    user_content = prompt
    if files:
        snippets: List[str] = []
        for fpath in files[:4]:
            try:
                p = Path(fpath)
                if p.is_file() and p.stat().st_size <= 200_000:
                    txt = p.read_text(encoding="utf-8", errors="replace")[:8000]
                    snippets.append(f"[Archivo adjunto: {p.name}]\n```\n{txt}\n```")
            except Exception:
                pass
        if snippets:
            user_content = "\n\n".join(snippets) + "\n\n" + prompt

    msgs.append({"role": "user", "content": user_content})
    return msgs


# ---------------------------------------------------------------------------
# API directa síncrona y streaming (para TARDIS Core :8757 y pruebas)
# ---------------------------------------------------------------------------
def chat(
    messages: Sequence[Dict[str, str]],
    model_ref: Optional[str] = None,
    *,
    temperature: float = 0.25,
    max_tokens: int = 1200,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Ejecuta una consulta completa contra el proveedor externo gratuito."""
    ref = model_ref or best_external_ref()
    spec, model_name = parse_model_ref(ref)
    if spec.requires_key and not _read_api_key(spec):
        return {"ok": False, "error": f"Falta API key ({spec.env_key}) para {spec.name}", "provider": spec.id}

    t0 = time.perf_counter()
    payload = {
        "model": model_name,
        "messages": list(messages),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    headers = _build_headers(spec)
    client = _get_uds_client() if spec.is_unix_socket else _get_http_client()
    url = "/v1/chat/completions" if spec.is_unix_socket else spec.base_url
    req_timeout = timeout or spec.timeout_s

    last_err = ""
    for attempt in range(2):
        try:
            resp = client.post(url, json=payload, headers=headers, timeout=req_timeout)
            elapsed = round(time.perf_counter() - t0, 3)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                msg = (choices[0].get("message") or {}) if choices else {}
                reply = (msg.get("content") or "").strip()
                reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
                usage = data.get("usage") or {}
                comp_toks = int(usage.get("completion_tokens") or max(1, len(reply.split())))
                return {
                    "ok": bool(reply),
                    "reply": reply,
                    "reasoning": reasoning,
                    "provider": spec.id,
                    "provider_name": spec.name,
                    "model": f"{spec.id}/{model_name}",
                    "elapsed_s": elapsed,
                    "tokens_in": int(usage.get("prompt_tokens") or 0),
                    "tokens_out": comp_toks,
                    "tokens_per_sec": round(comp_toks / max(elapsed, 0.001), 1),
                    "cost": 0.0,
                }
            last_err = f"HTTP {resp.status_code}: {resp.text[:240]}"
            if resp.status_code in (429, 502, 503, 504) and attempt == 0:
                time.sleep(0.8)
                continue
            return {"ok": False, "error": last_err, "status": resp.status_code, "provider": spec.id, "elapsed_s": elapsed}
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                time.sleep(0.5)
                continue
    return {"ok": False, "error": last_err, "provider": spec.id, "elapsed_s": round(time.perf_counter() - t0, 3)}


def chat_opencode_fast(
    messages: Sequence[Dict[str, str]],
    models: Sequence[str] = (
        "opencode/beam-free#max",
        "opencode/nemotron-3.5-lightning-free",
        "opencode/deepseek-v4.1-flash-free#max",
    ),
    timeout: float = 25.0,
) -> Dict[str, Any]:
    """Fallback ultrarrápido al pool gratuito de OpenCode Zen (~0.9s - 1.8s, 0 API key)."""
    exe = runtime_env.which("opencode")
    if not exe:
        return {"ok": False, "error": "binario opencode no encontrado", "provider": "opencode"}

    # Compactar historial en un prompt conversacional claro
    parts: List[str] = []
    sys_parts = [str(m.get("content") or "").strip() for m in messages if m.get("role") == "system"]
    if sys_parts:
        parts.append("[SISTEMA]\n" + "\n".join(sys_parts)[:2000])
    conv = [m for m in messages if m.get("role") in ("user", "assistant")]
    if len(conv) > 1:
        hist_lines = []
        for m in conv[:-1][-6:]:
            tag = "Usuario" if m["role"] == "user" else "TARDIS"
            hist_lines.append(f"{tag}: {str(m.get('content') or '')[:1200]}")
        parts.append("[HISTORIAL RECIENTE]\n" + "\n".join(hist_lines))
    if conv:
        parts.append(str(conv[-1].get("content") or ""))
    full_prompt = "\n\n".join(p for p in parts if p).strip()

    env = runtime_env.augment_path({**os.environ})
    env.update({"PYTHONUNBUFFERED": "1", "NO_COLOR": "1"})

    last_err = ""
    for mref in models:
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [exe, "run", "--format", "json", "--model", mref, full_prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                env=env,
            )
            elapsed = round(time.perf_counter() - t0, 3)
            texts: List[str] = []
            tokens_in = tokens_out = 0
            err_msg = ""
            for line in (proc.stdout or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                et = ev.get("type")
                part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
                if et == "text" and part.get("text"):
                    texts.append(str(part["text"]))
                elif et == "step_finish":
                    toks = part.get("tokens") or {}
                    tokens_in += int(toks.get("input") or 0)
                    tokens_out += int(toks.get("output") or 0)
                elif et == "error":
                    eobj = ev.get("error") or {}
                    err_msg = eobj.get("message") if isinstance(eobj, dict) else str(eobj)
            reply = "\n\n".join(t.strip() for t in texts if t.strip()).strip()
            if reply:
                return {
                    "ok": True,
                    "reply": reply,
                    "provider": "opencode",
                    "provider_name": f"OpenCode Zen Free ({mref.split('/')[-1]})",
                    "model": mref,
                    "elapsed_s": elapsed,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out or max(1, len(reply.split())),
                    "tokens_per_sec": round((tokens_out or max(1, len(reply.split()))) / max(elapsed, 0.001), 1),
                    "cost": 0.0,
                }
            last_err = err_msg or (proc.stderr or "")[:200] or f"rc={proc.returncode}"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
    return {"ok": False, "error": last_err, "provider": "opencode"}


def chat_with_failover(
    messages: Sequence[Dict[str, str]],
    model_ref: Optional[str] = None,
    *,
    temperature: float = 0.25,
    max_tokens: int = 1200,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    """
    Ejecuta inferencia externa gratuita con failover automático dual:
      - Si se solicita `opencode/...`, intenta OpenCode Zen primero y luego Pollinations AI.
      - En cualquier otro caso, intenta el proveedor externo HTTPS (Pollinations AI / Groq / etc.)
        y ante 402/429/error conmuta instantáneamente a OpenCode Zen Free Pool (~1s).
    """
    ref = (model_ref or best_external_ref()).strip()
    if ref.lower().startswith("opencode/"):
        r_oc = chat_opencode_fast(messages, models=(ref, "opencode/beam-free#max", "opencode/nemotron-3.5-lightning-free"), timeout=timeout)
        if r_oc.get("ok"):
            return r_oc
        return chat(messages, model_ref="pollinations/openai-fast", temperature=temperature, max_tokens=max_tokens, timeout=timeout)

    r_http = chat(messages, model_ref=ref, temperature=temperature, max_tokens=max_tokens, timeout=min(timeout, 20.0))
    if r_http.get("ok"):
        return r_http
    # Failover automático a OpenCode Zen Free Pool (11 modelos gratuitos independientes)
    r_oc = chat_opencode_fast(messages, timeout=timeout)
    if r_oc.get("ok"):
        r_oc["failover_from"] = ref
        r_oc["failover_reason"] = r_http.get("error", "")[:140]
        return r_oc
    return r_http


def probe(provider_id: str = "pollinations", ttl: float = 300.0, force: bool = False) -> Dict[str, Any]:
    """Sonda rápida con caché TTL para verificar disponibilidad y latencia real."""
    cached = _PROBE_CACHE.get(provider_id)
    now = time.time()
    if not force and cached and (now - float(cached.get("checked_epoch") or 0)) < ttl:
        return dict(cached)

    spec = PROVIDERS.get(provider_id)
    if not spec:
        return {"provider": provider_id, "available": False, "error": "proveedor desconocido"}
    if spec.requires_key and not _read_api_key(spec):
        res = {
            "provider": provider_id,
            "available": False,
            "configured": False,
            "latency_s": None,
            "error": f"sin {spec.env_key}",
            "checked_epoch": now,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        _PROBE_CACHE[provider_id] = res
        return dict(res)

    res_chat = chat(
        [
            {"role": "system", "content": "Responde únicamente OK."},
            {"role": "user", "content": "OK"},
        ],
        model_ref=f"{provider_id}/{spec.default_model}",
        temperature=0.0,
        max_tokens=16,
        timeout=15.0,
    )
    entry = {
        "provider": provider_id,
        "ref": f"{provider_id}/{spec.default_model}",
        "name": spec.name,
        "available": bool(res_chat.get("ok")),
        "configured": True,
        "latency_s": res_chat.get("elapsed_s"),
        "error": "" if res_chat.get("ok") else str(res_chat.get("error") or "fallo"),
        "checked_epoch": time.time(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _PROBE_CACHE[provider_id] = entry
    return dict(entry)


# ---------------------------------------------------------------------------
# Runner compatible 100% con chat_engine.ChatRunner (TUI + Web SSE)
# ---------------------------------------------------------------------------
class ExternalChatRunner:
    """
    Ejecutor streaming directo por HTTPS (sin subprocesos) compatible con el
    protocolo de eventos de `chat_engine.ChatRunner`.
    """

    def __init__(
        self,
        prompt: str,
        model_ref: str = "pollinations/openai-fast",
        *,
        thinking: bool = False,
        files: Optional[Sequence[str]] = None,
        session_messages: Optional[Sequence[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.25,
        max_tokens: int = 2048,
    ):
        self.prompt = prompt
        self.model_ref = model_ref
        self.thinking = thinking
        self.files = list(files or [])
        self.session_messages = list(session_messages or [])
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.session_id: Optional[str] = None
        self.started_at = 0.0
        self._cancel_event = threading.Event()
        self._response: Optional[httpx.Response] = None

    def cancel(self) -> None:
        self._cancel_event.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self) -> Iterator[dict]:
        self.started_at = time.time()
        spec, model_name = parse_model_ref(self.model_ref)
        if spec.requires_key and not _read_api_key(spec):
            yield {
                "kind": "error",
                "message": f"Proveedor {spec.name} requiere {spec.env_key}.",
                "status": 401,
                "error_type": "auth_missing",
                "retry_after_ms": None,
            }
            yield {
                "kind": "process_end",
                "rc": 1,
                "session_id": self.session_id,
                "duration_s": round(time.time() - self.started_at, 2),
            }
            return

        messages = build_messages_from_session(
            self.prompt,
            session_messages=self.session_messages,
            system_prompt=self.system_prompt,
            files=self.files,
        )
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        headers = _build_headers(spec)
        client = _get_uds_client() if spec.is_unix_socket else _get_http_client()
        url = "/v1/chat/completions" if spec.is_unix_socket else spec.base_url

        yield {"kind": "step_start", "provider": spec.id, "model": f"{spec.id}/{model_name}"}

        tokens_in = sum(max(1, len(m["content"]) // 4) for m in messages)
        tokens_out = 0
        emitted_any = False
        rc = 0

        try:
            with client.stream("POST", url, json=payload, headers=headers, timeout=spec.timeout_s) as resp:
                self._response = resp
                if resp.status_code != 200:
                    body = ""
                    try:
                        body = resp.read().decode("utf-8", errors="replace")[:300]
                    except Exception:
                        pass
                    rc = 1
                    yield {
                        "kind": "error",
                        "message": f"{spec.name} respondió HTTP {resp.status_code}: {body or 'error upstream'}",
                        "status": resp.status_code,
                        "error_type": "http_error",
                        "retry_after_ms": None,
                    }
                else:
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "text/event-stream" in ctype or "event-stream" in ctype:
                        for raw_line in resp.iter_lines():
                            if self._cancel_event.is_set():
                                break
                            line = (raw_line or "").strip()
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                except Exception:
                                    continue
                                text_delta, think_delta, usage = _extract_delta(chunk)
                                if think_delta and self.thinking:
                                    yield {"kind": "thinking", "text": think_delta, "delta": True}
                                if text_delta:
                                    emitted_any = True
                                    tokens_out += max(1, len(text_delta) // 4)
                                    yield {"kind": "text", "text": text_delta, "delta": True}
                                if usage:
                                    tokens_in = usage["input"] or tokens_in
                                    tokens_out = usage["output"] or tokens_out
                    else:
                        # Algunos endpoints devuelven JSON completo incluso con stream=true
                        data = json.loads(resp.read().decode("utf-8", errors="replace"))
                        text_delta, think_delta, usage = _extract_delta(data)
                        if think_delta and self.thinking:
                            yield {"kind": "thinking", "text": think_delta}
                        if text_delta:
                            emitted_any = True
                            tokens_out += max(1, len(text_delta) // 4)
                            yield {"kind": "text", "text": text_delta}
                        if usage:
                            tokens_in = usage["input"] or tokens_in
                            tokens_out = usage["output"] or tokens_out
        except Exception as exc:
            if not self._cancel_event.is_set():
                rc = 1
                yield {
                    "kind": "error",
                    "message": f"Fallo conectando con {spec.name}: {type(exc).__name__}: {exc}",
                    "status": 502,
                    "error_type": "connection_error",
                    "retry_after_ms": None,
                }
        finally:
            self._response = None

        if rc == 0 and not emitted_any and not self._cancel_event.is_set():
            rc = 1
            yield {
                "kind": "error",
                "message": f"{spec.name} no emitió contenido en la respuesta.",
                "status": 502,
                "error_type": "empty_response",
                "retry_after_ms": None,
            }
        elif rc == 0:
            yield {
                "kind": "step_finish",
                "tokens": {"input": tokens_in, "output": tokens_out},
                "cost": 0.0,
                "reason": "stop",
                "provider": spec.id,
            }

        yield {
            "kind": "process_end",
            "rc": rc,
            "session_id": self.session_id,
            "duration_s": round(time.time() - self.started_at, 2),
        }
