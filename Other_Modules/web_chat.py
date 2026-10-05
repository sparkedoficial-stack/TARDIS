"""
web_chat.py - Chat de terminal con modelo local pesado + acceso a INTERNET.
============================================================================

Loop agentico sobre Ollama con dos tools:
  - web_search(query)  : busca en DuckDuckGo (sin API key)
  - web_fetch(url)     : descarga una pagina y extrae el texto

El modelo decide cuando buscar; los resultados vuelven como tool results
y el modelo redacta la respuesta final citando fuentes.

Uso:
    python web_chat.py                    # modelo default qwen3-coder:30b
    python web_chat.py --model qwen2.5-coder:7b
    python web_chat.py --ctx 8192
    python web_chat.py --private          # arranca SIN acceso a internet

Comandos dentro del chat:
    /salir  /bye   - terminar
    /clear         - limpiar historial
    /model <name>  - cambiar modelo al vuelo
    /web off       - MODO PRIVADO: desactiva todo acceso a internet
    /web on        - reactiva las tools de internet
    /egress        - muestra el log de TODO lo que ha salido a internet

PRIVACIDAD (v1.1):
    - La conversacion vive SOLO en RAM de este proceso; no se persiste.
    - La inferencia es 100% local (Ollama en REDACTED_IP).
    - Lo UNICO que sale de la maquina son las queries de web_search y las
      URLs de web_fetch que el modelo decide invocar (solo si /web on).
    - CADA egreso se muestra en pantalla y se registra en
      %LOCALAPPDATA%\\vw-control\\web_egress.log para auditoria local.
    - En modo /web off NADA sale de la maquina, garantizado: las tools no
      se anuncian al modelo y las implementaciones quedan bloqueadas.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import time
import urllib.parse

import httpx

OLLAMA = "http://REDACTED_IP:11434"
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")
DEFAULT_CTX = 4096          # óptimo para Ryzen 7 + RTX 3050 (24 GB RAM)
REQUEST_TIMEOUT = 300.0
MAX_TOOL_ROUNDS = 6

# ---------------------------------------------------------------------
# Colores ANSI (Windows 10+ los soporta en consolas modernas)
# ---------------------------------------------------------------------
import os
os.system("")  # habilita VT100 en conhost
C_USER = "\033[93m"    # amarillo
C_AI = "\033[96m"      # cyan
C_TOOL = "\033[95m"    # magenta
C_DIM = "\033[90m"     # gris
C_ERR = "\033[91m"     # rojo
C_END = "\033[0m"


# =====================================================================
#  TOOLS DE INTERNET
# =====================================================================

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---------------------------------------------------------------------
# v1.1 PRIVACIDAD: estado global de web + log de egreso auditable
# ---------------------------------------------------------------------
WEB_ENABLED = True  # se togglea con /web on|off o --private

_EGRESS_LOG = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "vw-control", "web_egress.log")


def _log_egress(kind: str, payload: str):
    """Registra localmente CADA dato que sale de la maquina (auditable)."""
    try:
        os.makedirs(os.path.dirname(_EGRESS_LOG), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_EGRESS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {kind} | {payload}\n")
    except Exception:
        pass


def _egress_blocked() -> dict:
    return {"ok": False,
            "error": "MODO PRIVADO ACTIVO: acceso a internet desactivado "
                     "(/web on para reactivar)",
            "results": [], "text": ""}


def web_search(query: str, max_results: int = 6) -> dict:
    """Busca en DuckDuckGo HTML y devuelve [{title, url, snippet}]."""
    if not WEB_ENABLED:
        return _egress_blocked()
    if not query.strip():
        return {"ok": False, "error": "query vacio", "results": []}
    _log_egress("SEARCH->duckduckgo.com", query)
    print(f"{C_ERR}   [EGRESO] query enviada a DuckDuckGo: \"{query}\"{C_END}")
    try:
        r = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": _UA},
            timeout=20.0,
            follow_redirects=True,
        )
        r.raise_for_status()
        page = r.text
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"search fallo: {type(e).__name__}: {e}",
                "results": []}

    results = []
    # Bloques de resultado: <a class="result__a" href="...">titulo</a>
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page, re.DOTALL,
    ):
        raw_href, raw_title = m.group(1), m.group(2)
        # DDG envuelve la URL real en /l/?uddg=<url-encoded>
        url = raw_href
        uddg = re.search(r"[?&]uddg=([^&]+)", raw_href)
        if uddg:
            url = urllib.parse.unquote(uddg.group(1))
        title = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        if url.startswith("//"):
            url = "https:" + url
        results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= max_results:
            break

    # Snippets (mismo orden que los resultados)
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page, re.DOTALL)
    for i, sn in enumerate(snippets[: len(results)]):
        results[i]["snippet"] = html_mod.unescape(
            re.sub(r"<[^>]+>", "", sn)).strip()[:300]

    if not results:
        return {"ok": False, "error": "sin resultados (DDG pudo bloquear)",
                "results": []}
    return {"ok": True, "query": query, "results": results}


def web_fetch(url: str, max_chars: int = 7000) -> dict:
    """Descarga una URL y devuelve el texto visible (sin tags)."""
    if not WEB_ENABLED:
        return _egress_blocked()
    if not url.strip():
        return {"ok": False, "error": "url vacia", "text": ""}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _log_egress("FETCH", url)
    print(f"{C_ERR}   [EGRESO] descargando URL: {url}{C_END}")
    try:
        r = httpx.get(url, headers={"User-Agent": _UA},
                      timeout=25.0, follow_redirects=True)
        r.raise_for_status()
        page = r.text
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"fetch fallo: {type(e).__name__}: {e}",
                "text": ""}

    # Quitar bloques no-texto
    page = re.sub(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>",
                  " ", page, flags=re.DOTALL | re.IGNORECASE)
    # Tags -> espacio; entidades -> chars
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", page))
    # Colapsar whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + " ...[truncado]"
    return {"ok": True, "url": str(r.url), "status": r.status_code,
            "chars": len(text), "text": text}


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Busca en internet (DuckDuckGo). Devuelve titulos, URLs y "
                "snippets. USAR cuando el usuario pregunte por informacion "
                "actual, noticias, precios, datos que no conoces o que pueden "
                "haber cambiado despues de tu entrenamiento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Terminos de busqueda"},
                    "max_results": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Descarga una pagina web y devuelve su texto. USAR despues "
                "de web_search para leer el contenido completo de un "
                "resultado prometedor, o cuando el usuario pegue una URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL completa"},
                    "max_chars": {"type": "integer", "default": 7000},
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_IMPL = {
    "web_search": lambda a: web_search(a.get("query", ""),
                                       int(a.get("max_results", 6))),
    "web_fetch": lambda a: web_fetch(a.get("url", ""),
                                     int(a.get("max_chars", 7000))),
}

SYSTEM_PROMPT = (
    "Eres un asistente en espanol con ACCESO A INTERNET via las tools "
    "web_search y web_fetch. Hoy es {date}.\n"
    "PROTOCOLO DE PRIORIDAD Y DIÁLOGO COMEDIDO: Responde de forma directa, comedida, conversacional y concisa (1 a 3 párrafos). "
    "Evita divagaciones extensas o redundancias para máxima velocidad de respuesta.\n"
    "REGLAS:\n"
    "1. Si la pregunta involucra informacion actual (noticias, precios, "
    "versiones de software, eventos, clima, datos post-entrenamiento), "
    "USA web_search PRIMERO. No inventes.\n"
    "2. Tras un search, si un resultado parece clave, usa web_fetch para "
    "leerlo antes de responder.\n"
    "3. Cita las fuentes con su URL al final de tu respuesta.\n"
    "4. Si las tools fallan, dilo claramente y responde con tu conocimiento "
    "marcandolo como posiblemente desactualizado.\n"
    "5. Responde conciso y en espanol."
)

SYSTEM_PROMPT_PRIVATE = (
    "Eres un asistente en espanol operando en MODO PRIVADO: sin acceso a "
    "internet, 100% local. Hoy es {date}.\n"
    "PROTOCOLO DE PRIORIDAD Y DIÁLOGO COMEDIDO: Responde de forma directa, comedida, conversacional y concisa (1 a 3 párrafos). "
    "Evita divagaciones extensas.\n"
    "Responde solo con tu conocimiento de entrenamiento. Si te preguntan "
    "por informacion muy reciente, aclara que puede estar desactualizada "
    "y que el usuario puede activar internet con /web on si lo desea.\n"
    "Responde conciso y en espanol."
)


# =====================================================================
#  LOOP AGENTICO
# =====================================================================

def chat_once(client: httpx.Client, model: str, history: list,
              num_ctx: int) -> str:
    """Una ronda user->respuesta, resolviendo tool calls intermedios y procesando por Colibri."""
    # Redirección primaria universal por Colibri / Motor Soberano
    active_tools = TOOLS_SCHEMA if WEB_ENABLED else []
    if not active_tools:
        t0 = time.time()
        try:
            import gia_sovereign_engine as _gse
            res = _gse.get_engine().chat(history, model=model, temperature=0.3, num_ctx=min(num_ctx, 4096))
            if res.get("ok"):
                content = res.get("reply", "")
                elapsed = res.get("elapsed_s", round(time.time() - t0, 2))
                history.append({"role": "assistant", "content": content})
                print(f"\n{C_AI}{content}{C_END}")
                print(f"{C_DIM}   [{res.get('provider', 'colibri')} | 20GB RAM | {elapsed}s]{C_END}")
                return content
        except Exception:
            pass

    for round_i in range(MAX_TOOL_ROUNDS):
        t0 = time.time()
        # v1.1: en modo privado las tools NI SE ANUNCIAN al modelo
        try:
            resp = client.post(
                f"{OLLAMA}/api/chat",
                json={
                    "model": model,
                    "messages": history,
                    "tools": active_tools,
                    "stream": False,
                    "options": {
                        "num_ctx": min(num_ctx, 4096),
                        "num_predict": 256,
                        "temperature": 0.3,
                        "num_thread": 8,
                        "num_gpu": 99,
                        "use_mmap": True,
                        "use_mlock": True,
                        "num_batch": 512,
                    },
                    "keep_alive": "24h",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("error", "")
            except Exception:
                detail = e.response.text[:200]
            return f"{C_ERR}[Ollama HTTP {e.response.status_code}] {detail}{C_END}"
        except Exception as e:  # noqa: BLE001
            return f"{C_ERR}[error de conexion] {type(e).__name__}: {e}{C_END}"

        msg = data.get("message", {})
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        elapsed = time.time() - t0
        eval_n = data.get("eval_count", 0)
        tps = eval_n / elapsed if elapsed > 0 else 0

        history.append({"role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls or None})

        if not tool_calls:
            print(f"{C_DIM}   ({elapsed:.0f}s, {eval_n} tok, {tps:.1f} tok/s)"
                  f"{C_END}")
            return content

        # Ejecutar cada tool y devolver resultados
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            arg_str = json.dumps(args, ensure_ascii=False)[:120]
            print(f"{C_TOOL}   [tool] {name}({arg_str}){C_END}")
            impl = TOOL_IMPL.get(name)
            if impl:
                result = impl(args)
            else:
                result = {"ok": False, "error": f"tool desconocida: {name}"}
            ok_str = "ok" if result.get("ok") else f"ERROR: {result.get('error','')[:80]}"
            print(f"{C_DIM}   [tool] -> {ok_str}{C_END}")
            history.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False)[:9000],
            })
    return f"{C_ERR}[abortado: demasiadas rondas de tools]{C_END}"


def main() -> int:
    global WEB_ENABLED
    ap = argparse.ArgumentParser(description="Chat local con internet")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ctx", type=int, default=DEFAULT_CTX)
    ap.add_argument("--private", action="store_true",
                    help="arranca en modo privado (sin acceso a internet)")
    args = ap.parse_args()

    model = args.model
    num_ctx = args.ctx
    if args.private:
        WEB_ENABLED = False

    web_status = (f"{C_TOOL}ON (queries salen a DuckDuckGo){C_END}"
                  if WEB_ENABLED else f"{C_AI}OFF - MODO PRIVADO{C_END}")
    print(f"\n{C_AI}================================================={C_END}")
    print(f"{C_AI}  CHAT LOCAL - 100% en tu maquina{C_END}")
    print(f"{C_AI}  Modelo: {model}  (ctx={num_ctx}){C_END}")
    print(f"{C_AI}  Internet: {web_status}")
    print(f"{C_DIM}  /web off = privado total | /web on = con internet{C_END}")
    print(f"{C_DIM}  /egress = auditar que salio | /salir | /clear{C_END}")
    print(f"{C_AI}================================================={C_END}\n")

    from datetime import date
    system = SYSTEM_PROMPT.format(date=date.today().isoformat())
    history: list = [{"role": "system", "content": system}]

    with httpx.Client() as client:
        # Verificar Ollama
        try:
            client.get(f"{OLLAMA}/api/tags", timeout=5.0)
        except Exception:
            print(f"{C_ERR}Ollama no responde en {OLLAMA}. "
                  f"Arranca con: ollama serve{C_END}")
            return 1

        while True:
            try:
                user = input(f"{C_USER}Tu > {C_END}").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nAdios.")
                return 0
            if not user:
                continue
            if user.lower() in ("/salir", "/bye", "/exit", "/quit"):
                print("Adios.")
                return 0
            if user.lower() == "/clear":
                history = [{"role": "system", "content": system}]
                print(f"{C_DIM}(historial limpio){C_END}")
                continue
            if user.lower().startswith("/model "):
                model = user.split(None, 1)[1].strip()
                print(f"{C_DIM}(modelo -> {model}){C_END}")
                continue
            if user.lower() == "/web off":
                WEB_ENABLED = False
                print(f"{C_AI}(MODO PRIVADO: internet desactivado - nada "
                      f"sale de esta maquina){C_END}")
                continue
            if user.lower() == "/web on":
                WEB_ENABLED = True
                print(f"{C_TOOL}(internet ON - las queries del modelo "
                      f"saldran a DuckDuckGo y se registraran){C_END}")
                continue
            if user.lower() == "/egress":
                if os.path.isfile(_EGRESS_LOG):
                    print(f"{C_DIM}--- {_EGRESS_LOG} ---{C_END}")
                    with open(_EGRESS_LOG, encoding="utf-8") as f:
                        lines = f.readlines()
                    for ln in lines[-30:]:
                        print(f"{C_DIM}  {ln.rstrip()}{C_END}")
                    print(f"{C_DIM}  ({len(lines)} egresos registrados en "
                          f"total){C_END}")
                else:
                    print(f"{C_AI}(nada ha salido a internet todavia){C_END}")
                continue

            # v1.1: system prompt coherente con el modo actual
            from datetime import date as _date
            active_system = (
                SYSTEM_PROMPT.format(date=_date.today().isoformat())
                if WEB_ENABLED else
                SYSTEM_PROMPT_PRIVATE.format(date=_date.today().isoformat())
            )
            history[0] = {"role": "system", "content": active_system}

            history.append({"role": "user", "content": user})
            print(f"{C_DIM}   pensando...{C_END}")
            answer = chat_once(client, model, history, num_ctx)
            label = "GIA-Web" if WEB_ENABLED else "GIA-Privado"
            print(f"\n{C_AI}{label} > {C_END}{answer}\n")


if __name__ == "__main__":
    sys.exit(main())
