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

OLLAMA = "http://127.0.0.1:11434"
try:
    import gia_sovereign_engine as _gse
    DEFAULT_MODEL = _gse.get_engine().resolve_model()
except Exception:
    DEFAULT_MODEL = os.environ.get("GIA_MODEL", "TARDIS-NEURAL-SPACE-KAIJU")

C_USER = "\033[93m"; C_AI = "\033[96m"; C_TOOL = "\033[95m"
C_DIM = "\033[90m"; C_ERR = "\033[91m"; C_GREEN = "\033[92m"; C_WARN = "\033[93m"; C_END = "\033[0m"
os.system("")


# =====================================================================
#  FASE 0 - CAPTURA DE MICRÓFONO (STT)
# =====================================================================

def listen_microphone(lang: str = "es") -> str | None:
    """Escucha el micrófono localmente con PipeWire + Silero VAD v6 + Whisper local (100% offline)."""
    try:
        from core.tardis_infinite_voice import PipeWireMicStream
        from core.tardis_voice_engine import AdaptiveSpeechSegmenter, SegmenterConfig, get_sovereign_stt

        seg = AdaptiveSpeechSegmenter(SegmenterConfig(silence_hold_ms=760, max_utterance_ms=18000))
        mic = PipeWireMicStream(sample_rate=16000, frame_bytes=960)
        stt = get_sovereign_stt()
        print(f"\n{C_GREEN}🎙️  [MICRÓFONO LOCAL ACTIVO · Silero VAD + Whisper] Habla ahora...{C_END}")
        mic.start()
        deadline = time.monotonic() + 14.0
        pcm_utt: bytes | None = None
        try:
            while time.monotonic() < deadline:
                frame = mic.read_frame()
                if not frame:
                    continue
                res = seg.process_frame(frame, ai_speaking=False)
                if res.get("in_speech"):
                    deadline = max(deadline, time.monotonic() + 6.0)
                if res.get("utterance"):
                    pcm_utt = res["utterance"]
                    break
        finally:
            mic.stop()

        if not pcm_utt:
            print(f"{C_DIM}(tiempo de espera agotado sin voz detectada){C_END}")
            return None
        print(f"{C_DIM}   transcribiendo voz localmente...{C_END}")
        text, dt = stt.transcribe_pcm(pcm_utt, language=lang.split("-")[0])
        if not text:
            print(f"{C_DIM}(no se reconoció voz inteligible){C_END}")
            return None
        print(f"{C_USER}Tú (voz · {dt*1000:.0f}ms) > {C_END}{text}")
        return text.strip()
    except Exception as e:
        print(f"{C_ERR}Error de micrófono local: {e}{C_END}")
        return None


# =====================================================================
#  FASE 1 - ABSTRACCIÓN del mensaje (<15ms local, cero bloqueo LLM)
# =====================================================================

def abstract_message(client: httpx.Client, model: str, msg: str) -> dict:
    """Estructura y abstrae el mensaje en <15 ms con VoiceAbstractionEngine local."""
    try:
        from core.tardis_voice_engine import get_voice_abstractor
        abs_res = get_voice_abstractor().abstract(msg, allow_system_actions=True)
        return {
            "intencion": abs_res.intent,
            "sub_intencion": abs_res.sub_intent,
            "tema": abs_res.active_topic or abs_res.normalized_text[:50],
            "entidades": abs_res.entities,
            "requiere_internet": abs_res.needs_web,
            "consulta_web": abs_res.web_query or abs_res.resolved_query,
            "texto_normalizado": abs_res.normalized_text,
            "consulta_resuelta": abs_res.resolved_query,
            "respuesta_instantanea": abs_res.instant_reply,
            "guia": abs_res.system_guidance,
            "max_tokens": abs_res.max_tokens,
            "latency_ms": abs_res.latency_ms,
        }
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

        # COMANDO DE VOZ SOBERANO «PROGRAMA»: micrófono del asistente de terminal.
        try:
            from core.tardis_voice_program import get_voice_program_router

            voice_program = get_voice_program_router().handle(
                msg,
                channel="terminal_local_mic",
                source="micrófono local (speech_recognition)",
            )
            if voice_program:
                reply = str(voice_program.get("reply") or "").strip()
                print(f"\n{C_AI}TARDIS > {C_END}{reply}")
                print(f"{C_DIM}   (FTL · {time.time()-t0:.1f}s){C_END}\n")
                if use_voice:
                    _voice.speak(reply)
                return
        except Exception as e_vp:
            print(f"{C_WARN}Aviso en comando de voz «programa»: {e_vp}{C_END}")

        print(f"{C_DIM}   abstrayendo intención (local)...{C_END}")
        abs_ = abstract_message(client, args.model, msg)
        norm_msg = abs_.get("texto_normalizado") or msg
        tag = "internet" if abs_.get("requiere_internet") else "local"
        print(f"{C_DIM}   intencion={abs_.get('intencion')} tema={abs_.get('tema')} -> {tag} ({abs_.get('latency_ms', 0):.1f}ms){C_END}")
        if abs_.get("respuesta_instantanea") is not None:
            answer = str(abs_["respuesta_instantanea"])
            print(f"\n{C_AI}TARDIS > {C_END}{answer}")
            print(f"{C_DIM}   (instant · {time.time()-t0:.2f}s){C_END}\n")
            if use_voice and answer:
                _voice.speak(answer)
            return
        history.append({"role": "user", "content": abs_.get("consulta_resuelta") or norm_msg})
        if HAS_MEM:
            try: _mem.log("voz", "user", norm_msg, session_id="voz")
            except Exception: pass
        answer = analyze(client, args.model, history, abs_, use_web)
        history.append({"role": "assistant", "content": answer})
        try:
            from core.tardis_voice_engine import get_voice_abstractor
            get_voice_abstractor().record_assistant_reply(answer)
        except Exception:
            pass
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
