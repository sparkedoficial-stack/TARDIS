"""
voice_assistant.py - Asistente interactivo por VOZ (Micrófono STT + Bocinas TTS).
==================================================================================

Flujo completo bidireccional:
  1. ESCUCHA: captura tu voz por el micrófono con SpeechRecognition o por teclado.
  2. ABSTRAE: el modelo local extrae intención, entidades y necesidad de internet.
  3. ANALIZA: responde combinando su conocimiento interno + web_search fresca.
  4. HABLA: la respuesta sale por las bocinas físicas (voice.py) y por pantalla.

Uso:
    python voice_assistant.py                      # texto -> voz
    python voice_assistant.py --mic                # micrófono directo -> voz (manos libres)
    python voice_assistant.py --model qwen2.5-coder:7b
    python voice_assistant.py --no-web             # solo conocimiento del modelo
    python voice_assistant.py --once "tu pregunta" # una sola interacción

Comandos en sesión: /mic  /mic on|off  /voz off|on  /web off|on  /clear  /salir
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import voice as _voice

try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    from web_chat import web_search, web_fetch, TOOLS_SCHEMA as WEB_TOOLS, TOOL_IMPL as WEB_IMPL
    HAS_WEB = True
except Exception:
    HAS_WEB = False
    WEB_TOOLS, WEB_IMPL = [], {}

try:
    import gia_memory as _mem
    HAS_MEM = True
except Exception:
    HAS_MEM = False

try:
    import agent_context as _ctx
    HAS_CTX = True
except Exception:
    HAS_CTX = False

OLLAMA = "http://REDACTED_IP:11434"
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "Qwen3.8-27B-Uncensored-MLX:latest")

C_USER = "\033[93m"; C_AI = "\033[96m"; C_TOOL = "\033[95m"
C_DIM = "\033[90m"; C_ERR = "\033[91m"; C_GREEN = "\033[92m"; C_END = "\033[0m"
os.system("")


# =====================================================================
#  FASE 0 - CAPTURA DE MICRÓFONO (STT)
# =====================================================================

def listen_microphone(lang: str = "es-MX") -> str | None:
    """Escucha el micrófono del sistema y retorna el texto transcrito."""
    if not HAS_SR:
        print(f"{C_ERR}speech_recognition no disponible.{C_END}")
        return None

    r = sr.Recognizer()
    r.energy_threshold = 300
    r.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            print(f"\n{C_GREEN}🎙️  [MICRÓFONO ACTIVO] Habla ahora... (silencio para enviar){C_END}")
            r.adjust_for_ambient_noise(source, duration=0.6)
            audio = r.listen(source, timeout=10.0, phrase_time_limit=15.0)
            print(f"{C_DIM}   transcribiendo voz...{C_END}")
            text = r.recognize_google(audio, language=lang)
            print(f"{C_USER}Tú (voz) > {C_END}{text}")
            return text.strip()
    except sr.WaitTimeoutError:
        print(f"{C_DIM}(tiempo de espera agotado sin voz detectada){C_END}")
        return None
    except sr.UnknownValueError:
        print(f"{C_DIM}(no se reconoció voz inteligible){C_END}")
        return None
    except sr.RequestError as e:
        print(f"{C_ERR}Error conectando servicio STT: {e}{C_END}")
        return None
    except Exception as e:
        print(f"{C_ERR}Error de micrófono: {e}{C_END}")
        return None


# =====================================================================
#  FASE 1 - ABSTRACCIÓN del mensaje
# =====================================================================

ABSTRACT_PROMPT = (
    "Analiza el mensaje del usuario y responde SOLO con un objeto JSON "
    "(sin texto extra) con estas claves:\n"
    '  "intencion": breve (pregunta|orden|charla|busqueda_dato),\n'
    '  "tema": frase corta,\n'
    '  "entidades": [palabras clave],\n'
    '  "requiere_internet": true/false  (true si pide datos actuales, '
    "precios, noticias, versiones, clima, eventos recientes),\n"
    '  "consulta_web": string con la query ideal si requiere_internet.\n'
    "Mensaje: {msg}"
)


def abstract_message(client: httpx.Client, model: str, msg: str) -> dict:
    """Pide al modelo que estructure el mensaje. Devuelve dict abstraccion."""
    try:
        r = client.post(f"{OLLAMA}/api/chat", json={
            "model": model,
            "messages": [{"role": "user", "content": ABSTRACT_PROMPT.format(msg=msg)}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 4096},
            "keep_alive": "30m",
        }, timeout=300.0)
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "{}")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("no dict")
        return data
    except Exception as e:   # noqa: BLE001
        low = msg.lower()
        net_kw = ("hoy", "actual", "ultima", "última", "precio", "noticia",
                  "version", "versión", "clima", "2025", "2026", "ahora")
        return {
            "intencion": "pregunta",
            "tema": msg[:40],
            "entidades": [],
            "requiere_internet": any(k in low for k in net_kw),
            "consulta_web": msg,
            "_fallback": str(e),
        }


# =====================================================================
#  FASE 2 - ANÁLISIS (modelo + internet)
# =====================================================================

ANALYZE_SYSTEM = (
    "Eres GIA, asistente por voz en español. Hoy es {date}. "
    "Responde de forma clara, natural y CONCISA (2-4 frases, ideal para escuchar "
    "por las bocinas, sin listas excesivas ni markdown complejo). "
    "Si usas resultados de internet, responde de forma asertiva citando la fuente."
)


def analyze(client: httpx.Client, model: str, history: list,
            abstraction: dict, use_web: bool) -> str:
    """Genera la respuesta final con conocimiento y búsqueda web si se precisa."""
    web_context = ""
    if use_web and HAS_WEB and abstraction.get("requiere_internet"):
        query = abstraction.get("consulta_web") or abstraction.get("tema", "")
        print(f"{C_TOOL}   [internet] buscando: {query}{C_END}")
        res = web_search(query, max_results=4)
        if res.get("ok"):
            top = res["results"][:4]
            web_context = "RESULTADOS WEB:\n" + "\n".join(
                f"- {r['title']}: {r['snippet']} ({r['url']})" for r in top)
            if top and len(top[0].get("snippet", "")) < 40:
                f = web_fetch(top[0]["url"], max_chars=2500)
                if f.get("ok"):
                    web_context += f"\n\nCONTENIDO {top[0]['url']}:\n{f['text'][:2000]}"
        else:
            web_context = f"(busqueda web fallo: {res.get('error','')})"

    _sys = ANALYZE_SYSTEM.format(date=date.today().isoformat())
    if HAS_CTX:
        try:
            _sys = _ctx.apply_to_system(_sys)
        except Exception:
            pass
    messages = [{"role": "system", "content": _sys}]
    if HAS_MEM:
        try:
            last_user = next((m["content"] for m in reversed(history)
                              if m.get("role") == "user"), "")
            ctx = _mem.context_block(query=last_user, session_id="voz",
                                     n_recent=5, n_relevant=3)
            if ctx:
                messages.append({"role": "system",
                                 "content": "Memoria del sistema:\n" + ctx})
        except Exception:
            pass
    messages += history[-6:]
    if web_context:
        messages.append({"role": "user",
                         "content": f"[contexto de internet]\n{web_context}\n\n"
                                    "Responde a mi último mensaje usando esto."})

    try:
        r = client.post(f"{OLLAMA}/api/chat", json={
            "model": model, "messages": messages, "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 2048, "num_predict": 200, "num_thread": 8, "use_mmap": True, "num_batch": 512},
            "keep_alive": "24h",
        }, timeout=None)
        r.raise_for_status()
        return (r.json().get("message", {}).get("content") or "").strip()
    except Exception as e:   # noqa: BLE001
        return f"No pude completar el análisis: {e}"


# =====================================================================
#  BUCLE PRINCIPAL
# =====================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Asistente de voz GIA bidireccional")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-web", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--mic", action="store_true", help="activar micrófono continuo")
    ap.add_argument("--once", default=None)
    args = ap.parse_args()

    use_web = HAS_WEB and not args.no_web
    use_voice = not args.no_voice
    use_mic = args.mic and HAS_SR

    print(f"\n{C_AI}================================================={C_END}")
    print(f"{C_AI}  GIA · ASISTENTE DE VOZ BIDIRECCIONAL{C_END}")
    print(f"{C_AI}  Modelo: {args.model}   Bocinas (TTS): {'ON' if use_voice else 'OFF'}{C_END}")
    print(f"{C_AI}  Micrófono (STT): {'ON' if use_mic else 'OFF (usa /mic o --mic)'}   Internet: {'ON' if use_web else 'OFF'}{C_END}")
    print(f"{C_DIM}  Comandos: /mic [on|off]  /voz [on|off]  /web [on|off]  /clear  /salir{C_END}")
    print(f"{C_AI}================================================={C_END}\n")

    # Auto-bootstrap autónomo del motor LLM y dependencias
    try:
        import gia_bootstrap
        boot = gia_bootstrap.ensure_all_dependencies(preferred_model=args.model, verbose=False)
        if boot.get("active_model"):
            args.model = boot["active_model"]
    except Exception as e_boot:
        print(f"{C_WARN}Aviso en auto-bootstrap: {e_boot}{C_END}")

    client = httpx.Client()
    try:
        client.get(f"{OLLAMA}/api/tags", timeout=5.0)
    except Exception:
        print(f"{C_WARN}Aviso: Ollama no parece estar corriendo en {OLLAMA}.{C_END}")
        print(f"{C_DIM}Iniciando con: ollama serve{C_END}\n")
        return 1

    history: list = []

    def handle(msg: str):
        nonlocal use_web
        t0 = time.time()
        print(f"{C_DIM}   abstrayendo intención...{C_END}")
        abs_ = abstract_message(client, args.model, msg)
        tag = "internet" if abs_.get("requiere_internet") else "local"
        print(f"{C_DIM}   intencion={abs_.get('intencion')} tema={abs_.get('tema')} -> {tag}{C_END}")
        history.append({"role": "user", "content": msg})
        if HAS_MEM:
            try: _mem.log("voz", "user", msg, session_id="voz")
            except Exception: pass
        answer = analyze(client, args.model, history, abs_, use_web)
        history.append({"role": "assistant", "content": answer})
        if HAS_MEM:
            try: _mem.log("voz", "assistant", answer, session_id="voz")
            except Exception: pass
        print(f"\n{C_AI}GIA > {C_END}{answer}")
        print(f"{C_DIM}   ({time.time()-t0:.1f}s){C_END}\n")
        if use_voice:
            _voice.speak(answer)

    if args.once:
        handle(args.once)
        return 0

    while True:
        try:
            msg = ""
            if use_mic:
                msg = listen_microphone() or ""
                if not msg:
                    # Permitir entrada por teclado si no hubo audio
                    msg = input(f"{C_USER}Tu (o Enter para mic) > {C_END}").strip()
                    if not msg and use_mic:
                        continue
            else:
                msg = input(f"{C_USER}Tu > {C_END}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAdios.")
            return 0

        if not msg:
            continue

        low = msg.lower()
        if low in ("/salir", "/bye", "/exit"):
            print("Adios."); return 0
        if low == "/clear":
            history.clear(); print(f"{C_DIM}(historial limpio){C_END}"); continue
        if low == "/voz off":
            use_voice = False; print(f"{C_DIM}(bocinas OFF){C_END}"); continue
        if low == "/voz on":
            use_voice = True; print(f"{C_DIM}(bocinas ON){C_END}"); continue
        if low == "/mic on":
            use_mic = HAS_SR; print(f"{C_DIM}(micrófono {'ON' if HAS_SR else 'no disponible'}){C_END}"); continue
        if low == "/mic off":
            use_mic = False; print(f"{C_DIM}(micrófono OFF){C_END}"); continue
        if low == "/mic":
            res = listen_microphone()
            if res: handle(res)
            continue
        if low == "/web off":
            use_web = False; print(f"{C_DIM}(internet OFF){C_END}"); continue
        if low == "/web on":
            use_web = HAS_WEB; print(f"{C_DIM}(internet {'ON' if HAS_WEB else 'no disponible'}){C_END}"); continue

        handle(msg)


if __name__ == "__main__":
    raise SystemExit(main())
