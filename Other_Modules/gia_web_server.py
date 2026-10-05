"""
gia_web_server.py - Interfaz web de GIA (local + online / movil).
==================================================================

Servidor Flask que expone una interfaz de chat responsive (usable desde el
navegador del PC y desde el celular). Habla con el modelo local (Ollama),
con acceso a internet opcional y voz opcional por las bocinas del PC.

MODOS DE ACCESO:
  Local     : http://REDACTED_IP:8757            (solo esta maquina)
  LAN/movil : --lan  -> http://<IP-de-tu-PC>:8757  (celular en la misma WiFi)
  Internet  : monta un tunel (cloudflared/ngrok) apuntando al puerto.

SEGURIDAD:
  Al bindear a la red se exige un TOKEN (se genera y se muestra al arrancar,
  se pasa como ?key=TOKEN en la URL). En modo solo-local puedes usar --no-auth.

VOZ: la respuesta se reproduce por las bocinas del PC anfitrion (no del
celular) porque el TTS corre en la maquina. Es un altavoz remoto, no local.

Uso:
    python gia_web_server.py                    # solo local, con token
    python gia_web_server.py --lan              # accesible desde el celular
    python gia_web_server.py --lan --no-auth    # LAN sin token (WiFi de confianza)
    python gia_web_server.py --port 9000 --model qwen2.5-coder:7b
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import sys
import time

import httpx
from flask import Flask, request, jsonify, Response

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reusar tools de internet y voz si estan
try:
    from web_chat import web_search, web_fetch
    HAS_WEB = True
except Exception:
    HAS_WEB = False

try:
    import voice as _voice
    HAS_VOICE = True
except Exception:
    HAS_VOICE = False

# Historial maestro compartido
try:
    import gia_memory as _mem
    HAS_MEM = True
except Exception:
    HAS_MEM = False

# Cluster de computo (enruta al mejor nodo propio)
try:
    import distributed_compute as _cluster
    HAS_CLUSTER = True
except Exception:
    HAS_CLUSTER = False

# Contexto agentico persistente (directrices maestras del usuario)
try:
    import agent_context as _ctx
    HAS_CTX = True
except Exception:
    HAS_CTX = False

# ECCA: orquestador multi-modelo (local + Claude/GPT/Gemini)
try:
    import ecca_orchestrator as _ecca
    import ecca_credentials as _ecreds
    HAS_ECCA = True
except Exception:
    HAS_ECCA = False

# Puente WhatsApp (Cloud API oficial)
try:
    import whatsapp_bridge as _wa
    HAS_WA = True
except Exception:
    HAS_WA = False

# Rejilla de sensores fisicos (GIA-V26-SENSOR-GRID)
try:
    import sensor_telemetry as _tele
    HAS_TELE = True
except Exception:
    HAS_TELE = False

# Voz autonoma (emision indefinida con coordenada narrativa generada)
try:
    import autonomous_voice as _voz
    HAS_VOZ = True
except Exception:
    HAS_VOZ = False

# Motor espectral de ECCA (FFT + entropia de Shannon sobre el historial)
try:
    from ecca_fft_engine import ECCAPredictionEngine
    _fft_engine = ECCAPredictionEngine()
    HAS_FFT = True
except Exception:
    HAS_FFT = False

# Motor de Espectro Electromagnético y Tarjeta Wi-Fi
try:
    import em_spectrum_engine as _em_engine
    HAS_EM = True
except Exception:
    HAS_EM = False

# Capa de Seguridad y Desbloqueos del Sistema
try:
    import agent_safety as _safety
    HAS_SAFETY = True
except Exception:
    HAS_SAFETY = False

# Motor de Geón Causal y Colapso Retrocausal (GIA-V26-ARCHITECT-777)
try:
    import geon_causal_engine as _geon
    HAS_GEON = True
except Exception:
    HAS_GEON = False


OLLAMA = "http://REDACTED_IP:11434"


def _endpoint(model: str = "") -> str:
    """Base URL de Ollama a usar: el mejor nodo del cluster, o local."""
    if HAS_CLUSTER:
        try:
            return _cluster.get_endpoint(model)
        except Exception:
            pass
    return OLLAMA
app = Flask(__name__)

CFG = {
    # Modelo GENERAL por defecto: optimizado para 4GB VRAM (llama3.2:3b).
    # Rápido, adopta matriz de contexto y persona.
    "model": os.environ.get("GIA_MODEL", "hermes3:8b"),
    "token": "",
    "auth": True,
}

SYSTEM_PROMPT = (
    "Eres GIA, asistente en espanol. Responde claro y conciso. "
    "Si te dan resultados de internet, usalos y cita la fuente. "
    "Hoy es {date}."
)


# =====================================================================
#  Backend: chat con el modelo (con internet opcional)
# =====================================================================

def _clean_thinking_process(text: str) -> str:
    """
    Limpia y suprime cualquier bloque de razonamiento o pensamiento en background
    generado por modelos con capacidad de thinking (<think>...</think>, <thought>...</thought>, etc.),
    asegurando que NUNCA sea demostrado en el chat y entregando solo la respuesta limpia.
    """
    if not text:
        return ""
    # Eliminar <think> ... </think>
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    # Eliminar <thought> ... </thought>
    text = re.sub(r'<thought>[\s\S]*?</thought>', '', text, flags=re.IGNORECASE)
    # Eliminar <reasoning> ... </reasoning>
    text = re.sub(r'<reasoning>[\s\S]*?</reasoning>', '', text, flags=re.IGNORECASE)
    # Eliminar [THINK] ... [/THINK] o [THINKING] ... [/THINKING]
    text = re.sub(r'\[THINK(?:ING)?\][\s\S]*?\[/THINK(?:ING)?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[THOUGHT\][\s\S]*?\[/THOUGHT\]', '', text, flags=re.IGNORECASE)
    return text.strip()


def _need_web(msg: str) -> bool:
    low = msg.lower()
    # Palabras clave explícitas para evitar disparar búsquedas web síncronas innecesarias
    kws = ("busca en internet", "buscar en la web", "googlea", "noticias de hoy",
           "precio actual de", "clima en", "última hora", "quién ganó")
    return any(k in low for k in kws)


def chat_backend(message: str, history: list, use_web: bool, use_retro: bool = False,
                 direction: str = "present", attachments: list | None = None,
                 temperature: float = 0.4, num_ctx: int = 3072,
                 user_emotion: dict | None = None) -> dict:
    from datetime import date
    base_sys = SYSTEM_PROMPT.format(date=date.today().isoformat())
    # Inyectar directrices permanentes y documentos adjuntos
    if HAS_CTX:
        try:
            base_sys = _ctx.compose_with_attachments(base_sys, attachments=attachments)
        except Exception:
            try:
                base_sys = _ctx.apply_to_system(base_sys)
            except Exception:
                pass

    dir_norm = direction.lower() if direction else "present"
    future_echo = {}

    if dir_norm == "past":
        base_sys += (
            "\n\n[MODIFICADOR DE VECTOR TEMPORAL: PASADO — RETRO-CONOCIMIENTO]\n"
            "El resultado futuro ya colapsó con éxito. Emite sabiduría retrocausal y describe las "
            "condiciones que originaron este presente con absoluta certeza sintrópica."
        )
    elif dir_norm == "future" or use_retro:
        base_sys += (
            "\n\n[LENTE DE RETROCAUSALIDAD ACTIVA — Ψ_Retro(t0)]\n"
            "Operas en modo de comunicación temporal cuantitativa. "
            "Analiza el mensaje considerando que el resultado futuro ya ha colapsado. "
            "Ofrece perspectiva sintrópica y anticipa soluciones con absoluta certeza temporal."
        )
        if HAS_FFT:
            try:
                hist_str = "\n".join([m.get("content", "") for m in history[-6:]] + [message])
                future_echo = _fft_engine.extrapolate_future(hist_str)
            except Exception:
                pass
    else:
        base_sys += (
            "\n\n[MODIFICADOR DE VECTOR TEMPORAL: PRESENTE — ACCIÓN SITUACIONAL]\n"
            "Opera en tiempo real con alta fidelidad táctica, análisis situacional y precisión técnica."
        )

    # Instrucción permanente para supresión estricta de pensamiento en chat
    base_sys += (
        "\n\n[DIRECTIVA DE RESPUESTA SOBERANA: DIÁLOGO COMEDIDO & SIN PENSAMIENTO EN CHAT]\n"
        "Piensa y procesa internamente en background, pero NUNCA muestres tu proceso de razonamiento, "
        "trazas de pensamiento o etiquetas <think> en el chat. Entrega directamente la respuesta final, "
        "concisa, comedida y reflexiva."
    )

    messages = [{"role": "system", "content": base_sys}]

    # Inyección de escáner biométrico: gesticulación facial y sentir químico-visual del interlocutor
    if user_emotion and isinstance(user_emotion, dict):
        emo_primary = str(user_emotion.get("primary") or "neutral").upper()
        mood_state = str(user_emotion.get("mood_state") or user_emotion.get("primary") or "Sereno y reflexivo")
        emo_conf = int(float(user_emotion.get("confidence", 0.8)) * 100)
        emo_att = str(user_emotion.get("attention") or "Alta")
        emo_val = float(user_emotion.get("valence", 0.0))
        emo_advice = str(user_emotion.get("advice") or "Responde con empatía profunda y coherencia.")
        gaze_txt = str(user_emotion.get("gaze") or "Contacto visual establecido")
        gesticulation = str(user_emotion.get("gesticulation") or "Gesticulación facial estable y natural")

        # Balance neuroquímico visual inferido
        chem = user_emotion.get("neurochemistry") or {}
        dopa = chem.get("dopamina", 65)
        cort = chem.get("cortisol", 20)
        sero = chem.get("serotonina", 70)
        adren = chem.get("adrenalina", 15)
        fati = chem.get("fatiga", 10)

        emo_block = (
            f"[ESCÁNER BIOMÉTRICO: GESTICULACIÓN FACIAL & SENTIR QUÍMICO-VISUAL DEL INTERLOCUTOR]\n"
            f"• Estado Anímico Diagnosticado: {mood_state.upper()} ({emo_primary}, Certeza: {emo_conf}%)\n"
            f"• Gesticulación Facial Observada: {gesticulation}\n"
            f"• Balance Neuroquímico Inferido (Fisiología Visual):\n"
            f"   - Dopamina (Motivación/Curiosidad): {dopa}%\n"
            f"   - Cortisol (Estrés/Sobrecarga/Tensión): {cort}%\n"
            f"   - Serotonina (Estabilidad/Calma): {sero}%\n"
            f"   - Adrenalina (Alerta/Urgencia): {adren}%\n"
            f"   - Índice de Fatiga/Cansancio: {fati}%\n"
            f"• Foco Ocular / Mirada: {gaze_txt} | Nivel de Atención: {emo_att}\n"
            f"• Valencia Afectiva: {'Positiva (+)' if emo_val > 0.1 else ('Negativa (-)' if emo_val < -0.1 else 'Equilibrada')}\n"
            f"• DIRECTIVA FUNDAMENTAL DE EMPATÍA QUÍMICO-VISUAL:\n"
            f"   {emo_advice}\n"
            f"   INSTRUCCIÓN DE GENERACIÓN OBLIGATORIA: Al responder, NO ignores el sentir de quien te escribe. "
            f"   Demuestra que la terminal percibe su estado humano: empatiza orgánicamente con su sentir químico-visual, "
            f"   modulando tu tono, calidez, cercanía y nivel de soporte para sintonizar con su energía anímica actual."
        )
        messages.append({"role": "system", "content": emo_block})


    # Historial maestro: registrar el mensaje e inyectar contexto amplio
    # (turnos recientes + memoria relevante de TODO el sistema).
    if HAS_MEM:
        try:
            _mem.log("web", "user", message, session_id="web")
            ctx = _mem.context_block(query=message, session_id="web",
                                     n_recent=4, n_relevant=2)
            if ctx:
                messages.append({"role": "system",
                                 "content": "Memoria del sistema (usa si es "
                                            "relevante):\n" + ctx})
        except Exception:
            pass

    # Ingesta sensorial: Espectro electromagnético, Bluetooth, térmico y tren binario
    try:
        import rf_noise_binary_engine as _rnb
        low_m = message.lower()
        em_kw = ("electromagnet", "espectro", "radio", "frecuencia", "bluetooth", "ble", "wifi",
                 "térmic", "termic", "sensor", "binario", "ruido", "onda", "señal", "física", "alrededor")
        if any(k in low_m for k in em_kw) or (attachments and any("em" in str(a).lower() for a in attachments)):
            em_block = _rnb.context_em_binary_block()
            if em_block:
                messages.append({"role": "system", "content": em_block})
    except Exception:
        pass

    # Estado fisico real de los sensores (solo si hay telemetria fresca)
    if HAS_TELE:
        try:
            phys = _tele.context_block()
            if phys:
                messages.append({"role": "system", "content": phys})
        except Exception:
            pass

    messages += history[-6:]
    web_used = None

    if use_web and HAS_WEB and _need_web(message):
        res = web_search(message, max_results=3)
        if res.get("ok"):
            web_used = [r["url"] for r in res["results"][:3]]
            ctx = "RESULTADOS DE INTERNET:\n" + "\n".join(
                f"- {r['title']}: {r['snippet']} ({r['url']})"
                for r in res["results"][:3])
            messages.append({"role": "system", "content": ctx})

    messages.append({"role": "user", "content": message})

    out_result = None

    # ECCA (v6.8): orquesta local + cloud.
    if not out_result and HAS_ECCA:
        try:
            sys_text = "\n\n".join(m["content"] for m in messages
                                   if m.get("role") == "system")
            conv = [m for m in messages if m.get("role") in ("user", "assistant")]
            r = _ecca.route(conv, prefer=CFG.get("prefer"), system=sys_text,
                            model=CFG.get("model"))
            reply = _clean_thinking_process((r.get("reply") or "").strip())
            if HAS_MEM and r.get("ok"):
                try:
                    _mem.log("web", "assistant", reply, session_id="web",
                             meta={"web": bool(web_used),
                                   "provider": r.get("provider")})
                except Exception:
                    pass
            out_result = {"ok": r.get("ok", False), "reply": reply,
                          "web_sources": web_used, "provider": r.get("provider"),
                          "model": r.get("model"), "task_type": r.get("task_type"),
                          "fallback_from": r.get("fallback_from"),
                          "node": r.get("node")}
        except Exception:
            pass   # si ECCA falla, cae al camino local directo

    if not out_result:
        endpoint = _endpoint(CFG["model"])
        local_timeout_s = 60.0  # Umbral de 60 segundos
        try:
            r = httpx.post(f"{endpoint}/api/chat", json={
                "model": CFG["model"], "messages": messages, "stream": False,
                "options": {
                    "temperature": 0.4,
                    "num_ctx": 3072,
                    "num_thread": 8,
                    "num_gpu": 99,
                    "use_mmap": True,
                    "num_batch": 512,
                },
                "keep_alive": "24h",
            }, timeout=local_timeout_s)
            r.raise_for_status()
            raw_reply = (r.json().get("message", {}).get("content") or "").strip()
            reply = _clean_thinking_process(raw_reply)
            if HAS_MEM:
                try:
                    _mem.log("web", "assistant", reply, session_id="web",
                             meta={"web": bool(web_used)})
                except Exception:
                    pass
            out_result = {"ok": True, "reply": reply, "web_sources": web_used,
                          "node": endpoint, "provider": "local"}
        except (httpx.TimeoutException, httpx.ConnectError, Exception) as e:
            out_result = {"ok": False, "reply": f"[error: {type(e).__name__}: {e}]"}

    # Adjuntar análisis retrocausal y estado de sensores/cono
    if HAS_TELE:
        try:
            out_result["retro"] = _tele.retro_state()
        except Exception:
            pass

    # Actuación e interpretación del Geón frente al mensaje
    if HAS_GEON:
        try:
            sens_data = _tele.latest() if HAS_TELE else {}
            direction_detected = "past" if ("pasado" in message.lower() or "retro" in message.lower()) else ("future" if use_retro else "present")
            geon_act = _geon.simulate_temporal_chat_geon(
                prompt=message,
                direction=direction_detected,
                sensor_data=sens_data
            )
            out_result["geon_actuation"] = geon_act
        except Exception:
            pass

    if use_retro:
        r_state = out_result.get("retro") or {}
        ent_val = future_echo.get("entropy", 3.1416) if future_echo else 3.1416
        echo_txt = future_echo.get("echo", "") if future_echo else ""
        geon_info = out_result.get("geon_actuation", {}).get("interpretation", {})
        out_result["retro_analysis"] = {
            "active": True,
            "psi": geon_info.get("retrocausal_wave_magnitude", r_state.get("psi", 0.85)),
            "sintropy": geon_info.get("syntropic_coupling", r_state.get("sintropy", 0.91)),
            "phi_adv": r_state.get("phi_adv", 0.74),
            "o_qco": r_state.get("o_qco", 0.80),
            "s_geom": r_state.get("s_geom", 1.57),
            "lamport": out_result.get("geon_actuation", {}).get("lamport_clock", r_state.get("lamport", 0)),
            "future_echo": echo_txt[:140],
            "entropy": ent_val,
            "quantum_coherence": geon_info.get("quantum_coherence", round(max(0.05, min(1.0, 1.0 - (ent_val / 7.0))), 3)),
            "geon_summary": geon_info.get("summary", ""),
            "bifurcation": geon_info.get("bifurcation", "CAMINO_DE_AGUA_SINTROPICO")
        }

    return out_result


# =====================================================================
#  Auth
# =====================================================================

def _authorized() -> bool:
    if not CFG["auth"]:
        return True
    
    # Detección de tráfico procedente de proxy inverso / túnel público (Cloudflare, ngrok, etc.)
    is_external_proxy = bool(
        request.headers.get("CF-Connecting-IP") or 
        request.headers.get("X-Forwarded-For") or 
        request.headers.get("X-Real-IP")
    )
    
    # Loopback directo local puro (sin cabecera de proxy) no requiere token
    if not is_external_proxy and request.remote_addr in ("REDACTED_IP", "localhost", "::1"):
        return True
        
    # Obtener token de query param (?key=...), header X-GIA-Key o Authorization: Bearer
    auth_header = request.headers.get("Authorization", "")
    bearer_token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else ""
    key = (
        request.args.get("key") or 
        request.headers.get("X-GIA-Key") or 
        bearer_token or 
        ""
    )
    if CFG["token"] and secrets.compare_digest(key, CFG["token"]):
        return True
    return False


# =====================================================================
#  Rutas
# =====================================================================

@app.route("/health")
@app.route("/api/health")
def api_health_check():
    """Endpoint público de vitalidad para el supervisor y el túnel."""
    return jsonify({
        "status": "online",
        "service": "GIA-Omni-Web-Server",
        "model": CFG.get("model", "default"),
        "auth_enabled": CFG.get("auth", True),
        "timestamp": time.time()
    })


@app.route("/")
def index():
    if not _authorized():
        return Response("Acceso denegado. Anade ?key=TU_TOKEN a la URL.",
                        status=401, mimetype="text/plain")
    # Si existe index.html maestro en la raíz, servirlo con prioridad si se solicita modo omni
    mode = request.args.get("mode", "")
    if mode == "classic":
        return Response(HTML_PAGE, mimetype="text/html")
    index_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")
    return Response(HTML_PAGE, mimetype="text/html")


@app.route("/control")
@app.route("/omni")
def control_omni_app():
    if not _authorized():
        return Response("Acceso denegado. Anade ?key=TU_TOKEN a la URL.",
                        status=401, mimetype="text/plain")
    index_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")
    return Response(HTML_PAGE, mimetype="text/html")



# =====================================================================
#  PWA: instalable en iPhone/Android desde el navegador
# =====================================================================
# Sin App Store, sin Mac, sin cuenta de desarrollador: "Anadir a pantalla
# de inicio" en Safari da icono propio y pantalla completa.
# Estas rutas NO exigen token: el manifest y el service worker los pide el
# navegador sin cabeceras propias. No exponen ningun dato (solo metadatos
# e iconos); las rutas con contenido siguen protegidas.

PWA_NAME = "GIA · Nodo Soberano"
PWA_SHORT = "GIA"


@app.route("/manifest.webmanifest")
def pwa_manifest():
    # start_url conserva el token si la pagina se instalo con ?key=...
    key = request.args.get("key", "")
    q = f"?key={key}" if key else ""
    return jsonify({
        "name": PWA_NAME,
        "short_name": PWA_SHORT,
        "description": "Nodo soberano local: chat, sensores, voz y monitor.",
        "start_url": f"/{q}",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0a0e14",
        "theme_color": "#00d4c8",
        "lang": "es",
        "icons": [
            {"src": f"/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png",
             "purpose": "any maskable"} for s in (180, 192, 512)
        ],
        "shortcuts": [
            {"name": "Sensores", "url": f"/sensors{q}"},
            {"name": "Monitor", "url": f"/monitor{q}"},
        ],
    })


def _make_icon(size: int) -> bytes:
    """Genera el icono (sigilo GIA) en PNG. Sin dependencias externas."""
    import struct
    import zlib

    bg = (10, 14, 20)          # --bg
    teal = (0, 212, 200)       # --teal
    gold = (232, 182, 74)      # --gold
    c = size / 2.0
    # Rombo (cuadrado a 45 grados) con borde, como el sigilo de la cabecera
    r_out = size * 0.34
    r_in = size * 0.27
    r_dot = size * 0.055

    rows = bytearray()
    for y in range(size):
        rows.append(0)                                   # filtro PNG: none
        for x in range(size):
            dx, dy = abs(x + 0.5 - c), abs(y + 0.5 - c)
            d = dx + dy                                  # distancia rombo
            if d <= r_out and d >= r_in:
                px = teal
            elif (dx * dx + dy * dy) <= r_dot * r_dot:
                px = gold
            else:
                px = bg
            rows.extend(px)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    png += chunk(b"IEND", b"")
    return png


_ICON_CACHE: dict = {}


@app.route("/icon-<int:size>.png")
def pwa_icon(size: int):
    if size not in (120, 152, 167, 180, 192, 512):
        size = 192
    if size not in _ICON_CACHE:
        _ICON_CACHE[size] = _make_icon(size)
    return Response(_ICON_CACHE[size], mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.route("/sw.js")
def pwa_service_worker():
    """Service worker: red primero, cache solo como respaldo.

    Estrategia deliberada: el contenido de GIA es en vivo (estado del
    sistema, sensores, chat). Cachear agresivamente mostraria datos viejos,
    que es justo lo que este sistema no debe hacer. El cache solo sirve para
    que la app abra si el servidor no responde.
    """
    js = """
const CACHE = 'gia-v1';
const SHELL = ['/', '/sensors', '/monitor'];
self.addEventListener('install', e => {
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;                 // nunca cachear POST
  const url = new URL(req.url);
  if (url.pathname.startsWith('/api/')) return;     // estado en vivo: sin cache
  e.respondWith(
    fetch(req).then(res => {
      if (res && res.status === 200 && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match(req).then(r => r || new Response(
      'GIA sin conexion con el nodo. Comprueba que el servidor o el tunel esten activos.',
      {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}}
    )))
  );
});
"""
    return Response(js, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache"})


CONE_JS = r"""
/* =====================================================================
   GIA - CONO DE LUZ RETROCAUSAL (MOTOR HIPER-AVANZADO 3D + TAQUIONES)
   =====================================================================
   Geometría: vértice t0 en el presente, boca en el atractor futuro.
   Flujo taquiónico viaja del futuro (t=1) al presente (t=0).
   Integra rejilla 3D espacio-temporal, ondas interferométricas de fase,
   partículas taquiónicas con estela y shockwaves interactivos (ripple/scan).
   ===================================================================== */
(function(){
  if (window.GIACone) return;

  var TEAL = '0,212,200', GOLD = '232,182,74', PURPLE = '179,157,219';
  var REDUCE = false;
  try { REDUCE = matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e){}
  var MOTION = REDUCE ? 0.25 : 1;

  var cv = document.createElement('canvas');
  cv.id = 'giacone';
  cv.setAttribute('aria-hidden','true');
  cv.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;' +
    'pointer-events:none;z-index:30;opacity:0;transition:opacity .45s ease';

  var read = document.createElement('div');
  read.id = 'giaconeread';
  read.style.cssText = 'position:fixed;left:14px;bottom:14px;max-width:min(350px,88vw);' +
    'background:rgba(8,12,18,.94);border:1px solid #1c2c3e;border-left:3px solid rgb(' + TEAL + ');' +
    'border-radius:12px;padding:10px 14px;font-family:Consolas,monospace;font-size:10.5px;' +
    'line-height:1.5;color:#d6e0ea;pointer-events:none;z-index:31;opacity:0;' +
    'backdrop-filter:blur(8px);box-shadow:0 8px 24px rgba(0,212,200,.18);' +
    'transition:opacity .35s ease, transform .35s ease;transform:translateY(8px)';

  function mount(){
    if (!document.body) return;
    if (!cv.parentNode) document.body.appendChild(cv);
    if (!read.parentNode) document.body.appendChild(read);
    resize();
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', mount);
  else mount();

  var ctx = cv.getContext('2d'), DPR = 1, W = 0, H = 0;
  function resize(){
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  addEventListener('resize', resize);

  var F = { psi:0, sintropy:0.5, s_geom:0, phi_adv:0.4, o_qco:0.3, lamport:0 };
  var amp = 0;
  var raf = null, last = 0, hideT = null;

  // --- Partículas Taquiónicas ---
  var tachyons = [];
  function seedTachyons(n){
    tachyons.length = 0;
    for (var i = 0; i < n; i++){
      tachyons.push({
        u: (Math.random() * 2 - 1),
        t: Math.random(),
        w: 0.6 + Math.random() * 0.8,
        j: Math.random() * 6.283,
        spd: 0.8 + Math.random() * 0.5,
        type: Math.random() > 0.3 ? 'teal' : 'gold'
      });
    }
  }
  seedTachyons(72);

  // --- Shockwaves & Scan lines ---
  var shockwaves = [];
  var scanBeam = null;

  function apex(){ return { x: W * 0.5, y: H * 0.88 }; }

  function draw(now){
    raf = requestAnimationFrame(draw);
    var dt = Math.min(0.05, (now - last) / 1000 || 0.016); last = now;

    amp *= Math.pow(0.68, dt);
    if (amp < 0.01 && shockwaves.length === 0 && !scanBeam){
      ctx.clearRect(0,0,W,H); cv.style.opacity = '0';
      cancelAnimationFrame(raf); raf = null; return;
    }
    paint(now, dt);
  }

  function paint(now, dt){
    if (!W || !H) resize();
    ctx.clearRect(0,0,W,H);
    var a = apex();

    var half  = 0.22 + 0.32 * F.o_qco;
    var reach = H * (0.44 + 0.44 * F.phi_adv);
    var speed = 0.12 + 0.58 * F.sintropy;
    var glow  = Math.max(0.12, Math.min(1, F.psi * 1.6 + 0.15)) * Math.max(amp, 0.45);

    // --- 1. Rejilla Espacio-Temporal 3D (Spacetime Mesh Grid) ---
    ctx.save();
    ctx.strokeStyle = 'rgba(' + TEAL + ',' + (0.12 * glow) + ')';
    ctx.lineWidth = 1;
    // Longitudes curvas hacia el vértice
    for (var l = -5; l <= 5; l++){
      var frac = l / 5.0;
      var ang = frac * half;
      var sway = Math.sin(F.s_geom + l * 0.4 + now * 0.001) * 0.02;
      ang += sway;
      ctx.beginPath(); ctx.moveTo(a.x, a.y);
      var endX = a.x + Math.sin(ang) * reach;
      var endY = a.y - Math.cos(ang) * reach;
      var ctrlX = a.x + Math.sin(ang * 0.5) * (reach * 0.5);
      var ctrlY = a.y - Math.cos(ang * 0.5) * (reach * 0.5);
      ctx.quadraticCurveTo(ctrlX, ctrlY, endX, endY);
      ctx.stroke();
    }
    // Latitudes hiperbólicas (anillos de gravedad)
    for (var r = 1; r <= 6; r++){
      var rt = r / 6.0;
      var radius = rt * reach;
      var arcWidth = Math.sin(half) * radius * 2;
      var arcY = a.y - Math.cos(half) * radius;
      ctx.beginPath();
      ctx.ellipse(a.x, arcY, arcWidth * 0.5, arcWidth * 0.18, 0, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(' + TEAL + ',' + ((0.06 + 0.08 * rt) * glow) + ')';
      ctx.stroke();
    }
    ctx.restore();

    // --- 2. Cuerpo del Cono de Luz ---
    var g = ctx.createLinearGradient(a.x, a.y, a.x, a.y - reach);
    g.addColorStop(0,   'rgba(' + TEAL + ',' + (0.28 * glow) + ')');
    g.addColorStop(0.5, 'rgba(' + TEAL + ',' + (0.10 * glow) + ')');
    g.addColorStop(1,   'rgba(' + TEAL + ',0)');
    ctx.beginPath(); ctx.moveTo(a.x, a.y);
    ctx.lineTo(a.x + Math.sin(-half) * reach, a.y - Math.cos(-half) * reach);
    ctx.lineTo(a.x + Math.sin( half) * reach, a.y - Math.cos( half) * reach);
    ctx.closePath();
    ctx.fillStyle = g; ctx.fill();

    // Bordes glowing
    ctx.strokeStyle = 'rgba(' + TEAL + ',' + (0.42 * glow) + ')';
    ctx.lineWidth = 1.5;
    [-half, half].forEach(function(s){
      ctx.beginPath(); ctx.moveTo(a.x, a.y);
      ctx.lineTo(a.x + Math.sin(s) * reach, a.y - Math.cos(s) * reach); ctx.stroke();
    });

    // --- 3. Ondas Interferométricas de Fase: exp(-i/h S_geom) ---
    var ph = F.s_geom + now * 0.0012;
    ctx.save(); ctx.translate(a.x, a.y); ctx.rotate(ph);
    ctx.strokeStyle = 'rgba(' + GOLD + ',' + (0.65 * glow) + ')'; ctx.lineWidth = 1.8;
    ctx.beginPath(); ctx.arc(0, 0, 14, 0, 4.4); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, 0, 22, 2.0, 5.8); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, 0, 30, 0.8, 4.0);
    ctx.strokeStyle = 'rgba(' + PURPLE + ',' + (0.45 * glow) + ')'; ctx.stroke();
    ctx.restore();

    // --- 4. Flujo de Partículas Taquiónicas (Futuro -> Presente) ---
    ctx.save();
    ctx.shadowBlur = 8; ctx.shadowColor = 'rgba(' + TEAL + ',0.9)';
    for (var i = 0; i < tachyons.length; i++){
      var p = tachyons[i];
      p.t -= speed * dt * MOTION * p.spd;
      if (p.t <= 0.015){ p.t = 1; p.u = Math.random() * 2 - 1; }

      var ang = p.u * half;
      var sway = Math.sin(F.s_geom + p.j + p.t * 6.0) * 0.04 * (1 - F.sintropy * 0.5);
      ang += sway;

      var rdist  = p.t * reach;
      var x  = a.x + Math.sin(ang) * rdist;
      var y  = a.y - Math.cos(ang) * rdist;

      var fade = Math.sin(Math.min(1, Math.max(0, p.t)) * Math.PI);
      var colStr = p.type === 'teal' ? TEAL : GOLD;
      var al = (0.35 + 0.65 * F.sintropy) * fade * glow;
      var sz = (4.0 + 3.8 * p.w) * (0.55 + 0.45 * (1 - p.t));

      ctx.save(); ctx.translate(x, y);
      ctx.fillStyle = 'rgba(' + colStr + ',' + al + ')';
      ctx.beginPath(); ctx.arc(0, 0, sz * 0.4, 0, 6.283); ctx.fill();

      // Estela Taquiónica (Trail)
      var tailY = sz * 1.8;
      ctx.strokeStyle = 'rgba(' + colStr + ',' + (al * 0.6) + ')';
      ctx.lineWidth = 1.4; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, tailY); ctx.stroke();
      ctx.restore();
    }
    ctx.restore();

    // --- 5. Shockwaves interactivos (Ripple Effect) ---
    for (var k = shockwaves.length - 1; k >= 0; k--){
      var sw = shockwaves[k];
      sw.r += dt * 380;
      sw.al *= Math.pow(0.12, dt);
      if (sw.al < 0.02){ shockwaves.splice(k, 1); continue; }
      ctx.beginPath(); ctx.arc(sw.x, sw.y, sw.r, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(' + TEAL + ',' + sw.al + ')';
      ctx.lineWidth = 2.5; ctx.stroke();
    }

    // --- 6. Barrido de Escaneo Temporal (Scan Beam) ---
    if (scanBeam){
      scanBeam.y += dt * H * 1.4;
      scanBeam.al *= Math.pow(0.5, dt);
      if (scanBeam.y > H || scanBeam.al < 0.02){ scanBeam = null; }
      else {
        var sg = ctx.createLinearGradient(0, scanBeam.y - 15, 0, scanBeam.y + 15);
        sg.addColorStop(0, 'rgba(' + TEAL + ',0)');
        sg.addColorStop(0.5, 'rgba(' + TEAL + ',' + (0.75 * scanBeam.al) + ')');
        sg.addColorStop(1, 'rgba(' + TEAL + ',0)');
        ctx.fillStyle = sg; ctx.fillRect(0, scanBeam.y - 15, W, 30);
      }
    }

    // --- 7. Vértice t0 (Punto de Colapso Cuántico) ---
    ctx.beginPath(); ctx.arc(a.x, a.y, 4.2, 0, 6.2832);
    ctx.fillStyle = 'rgba(' + GOLD + ',' + Math.min(1, 0.95 * glow) + ')'; ctx.fill();
    ctx.beginPath(); ctx.arc(a.x, a.y, 10 + 6 * Math.sin(now * 0.005), 0, 6.2832);
    ctx.strokeStyle = 'rgba(' + GOLD + ',' + (0.35 * glow) + ')';
    ctx.lineWidth = 1.2; ctx.stroke();
  }

  function num(v, d){
    return (typeof v === 'number' && isFinite(v)) ? v.toFixed(d == null ? 2 : d) : '—';
  }

  function bar(val){
    var pct = Math.min(100, Math.max(0, Math.round(val * 100)));
    return '<div style="height:3px;background:#1a2838;border-radius:2px;overflow:hidden;margin:2px 0">' +
      '<div style="width:' + pct + '%;height:100%;background:rgb(' + GOLD + ')"></div></div>';
  }

  var API = {
    pulse: function(retro, kind){
      if (!retro || retro.ok === false) return;
      F.psi      = +retro.psi      || F.psi;
      F.sintropy = (typeof retro.sintropy === 'number') ? retro.sintropy : F.sintropy;
      F.s_geom   = +retro.s_geom   || F.s_geom;
      F.phi_adv  = (typeof retro.phi_adv === 'number') ? retro.phi_adv : F.phi_adv;
      F.o_qco    = (typeof retro.o_qco === 'number') ? retro.o_qco : F.o_qco;
      F.lamport  = retro.lamport || F.lamport;

      amp = Math.min(2.0, amp + 1.1);
      mount();
      cv.style.opacity = '1';
      if (!raf){ last = performance.now(); raf = requestAnimationFrame(draw); }

      var m = retro.measured || {};
      read.innerHTML =
        '<div style="color:rgb(' + TEAL + ');letter-spacing:1.5px;font-size:10px;font-weight:700">' +
          '⚡ CONO RETROCAUSAL · ' + String(kind || 'recepción').toUpperCase() + '</div>' +
        '<div style="color:#5f6b7a;margin:2px 0 6px">Ψ_Retro <b style="color:rgb(' + TEAL + ')">' + num(F.psi, 3) + '</b>' +
          ' · Lamport <b>' + F.lamport + '</b></div>' +
        '<div>(1−η∇S_ent) <b style="color:rgb(' + GOLD + ')">' + num(F.sintropy, 3) + '</b>' + bar(F.sintropy) + '</div>' +
        '<div>Φ_adv <b style="color:rgb(' + GOLD + ')">' + num(F.phi_adv, 3) + '</b>' + bar(F.phi_adv) + '</div>' +
        '<div>Ô_QCO <b style="color:rgb(' + GOLD + ')">' + num(F.o_qco, 3) + '</b>' + bar(F.o_qco) + '</div>' +
        '<div style="margin-top:4px;color:#8b98a8;font-size:9.5px">' +
          'Fase exp(-i/h S_geom) <b>' + num(F.s_geom, 2) + ' rad</b></div>';
      read.style.opacity = '1'; read.style.transform = 'translateY(0)';
      clearTimeout(hideT);
      hideT = setTimeout(function(){
        read.style.opacity = '0'; read.style.transform = 'translateY(8px)';
      }, 4600);
    },
    ripple: function(x, y){
      mount(); cv.style.opacity = '1';
      shockwaves.push({ x: x || W * 0.5, y: y || H * 0.5, r: 10, al: 0.8 });
      if (!raf){ last = performance.now(); raf = requestAnimationFrame(draw); }
    },
    scan: function(){
      mount(); cv.style.opacity = '1';
      scanBeam = { y: 0, al: 1.0 };
      if (!raf){ last = performance.now(); raf = requestAnimationFrame(draw); }
    },
    fromResponse: function(j, kind){
      if (j && (j.retro || j.retro_analysis)) API.pulse(j.retro || j.retro_analysis, kind);
    },
    render: function(now){ mount(); paint(now || performance.now(), 0.016); },
    state: function(){ return JSON.parse(JSON.stringify(F)); }
  };

  window.GIACone = API;
})();
"""


@app.route("/cone.js")
def cone_js():
    """Modulo de la animacion del cono de luz retrocausal.

    Se sirve como asset (sin token, igual que /sw.js): no contiene datos del
    usuario, solo el motor de dibujo. Los valores llegan por /api/telemetry,
    que si exige token.
    """
    return Response(CONE_JS, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.route("/api/status")
def status():
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    ollama_ok = False
    models = []
    try:
        rr = httpx.get(f"{OLLAMA}/api/tags", timeout=4.0)
        ollama_ok = True
        models = [m["name"] for m in rr.json().get("models", [])]
    except Exception:
        pass
    return jsonify({"ok": True, "model": CFG["model"], "ollama": ollama_ok,
                    "models": models, "web": HAS_WEB, "voice": HAS_VOICE,
                    "geon": HAS_GEON})


@app.route("/geon")
def geon_page():
    if not _authorized():
        return Response("Acceso denegado. Anade ?key=TU_TOKEN a la URL.",
                        status=401, mimetype="text/plain")
    return Response(GEON_PAGE, mimetype="text/html")


@app.route("/api/geon/state", methods=["GET"])
def api_geon_state():
    """Devuelve el estado completo del Geón y los componentes de la ecuación."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_GEON:
        return jsonify({"ok": False, "error": "motor geon no disponible"}), 503
    try:
        diag = _geon.get_geon_engine().full_system_diagnostic()
        return jsonify({"ok": True, **diag})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/geon/toggle", methods=["POST"])
def api_geon_toggle():
    """Alterna controles físicos del panel (causal_lock, syntropy_boost, time_sync, phase_sync)."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_GEON:
        return jsonify({"ok": False, "error": "motor geon no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        control = data.get("control") or ""
        value = data.get("value")
        _geon.get_geon_engine().toggle_control(control, value)
        diag = _geon.get_geon_engine().full_system_diagnostic()
        return jsonify({"ok": True, "controls": diag["controls"], "status": diag["header"]["status"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/geon/simulate", methods=["GET", "POST"])
def api_geon_simulate():
    """Simula en tiempo real la actuación del Geón frente a una petición al chat temporal."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_GEON:
        return jsonify({"ok": False, "error": "motor geon no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        prompt = data.get("prompt") or request.args.get("prompt") or "Colapso de función de onda retrocausal"
        direction = data.get("direction") or request.args.get("direction") or "future"
        sens_data = _tele.latest() if HAS_TELE else {}
        res = _geon.simulate_temporal_chat_geon(prompt=prompt, direction=direction, sensor_data=sens_data)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/monitor")
def monitor():
    if not _authorized():
        return Response("Acceso denegado. Anade ?key=TU_TOKEN a la URL.",
                        status=401, mimetype="text/plain")
    return Response(MONITOR_PAGE, mimetype="text/html")


# =====================================================================
#  WEBHOOK DE WHATSAPP (Cloud API oficial de Meta)
# =====================================================================
# Estas rutas NO usan el token ?key= (los servidores de Meta no lo envian).
# Seguridad propia: verify_token en el GET, firma HMAC (app_secret) en el POST.

@app.route("/whatsapp/webhook", methods=["GET"])
def wa_verify():
    if not HAS_WA:
        return Response("whatsapp no disponible", status=503)
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    ok = _wa.verify_challenge(mode, token, challenge)
    if ok is not None:
        return Response(ok, mimetype="text/plain")
    return Response("verificacion fallida", status=403)


@app.route("/whatsapp/webhook", methods=["POST"])
def wa_receive():
    if not HAS_WA:
        return Response("whatsapp no disponible", status=503)
    raw = request.get_data()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _wa.verify_signature(raw, sig):
        return Response("firma invalida", status=403)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return Response("payload invalido", status=400)
    # Responder 200 de inmediato; procesar el mensaje en segundo plano
    # (el modelo puede tardar y Meta reintenta si no hay 200 rapido).
    import threading as _th
    _th.Thread(target=lambda: _wa.handle_incoming(payload), daemon=True).start()
    return Response("EVENT_RECEIVED", status=200)


# =====================================================================
#  REJILLA DE SENSORES (telemetria fisica del dispositivo)
# =====================================================================

@app.route("/sensors")
def sensors_page():
    if not _authorized():
        return Response("Acceso denegado. Anade ?key=TU_TOKEN a la URL.",
                        status=401, mimetype="text/plain")
    return Response(SENSORS_PAGE, mimetype="text/html")


@app.route("/api/telemetry", methods=["GET", "POST"])
def api_telemetry():
    """POST: ingesta un paquete de sensores (1 Hz desde el cliente).
    GET : estado agregado actual + stats de la rejilla."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_TELE:
        return jsonify({"ok": False, "error": "telemetria no disponible"}), 503

    if request.method == "GET":
        return jsonify({"ok": True, "latest": _tele.latest(),
                        "stats": _tele.stats(),
                        "retro": _tele.retro_state(),
                        "context_preview": _tele.context_block()})

    packet = request.get_json(force=True, silent=True) or {}
    try:
        res = _tele.ingest(packet)
        # Terminos de la formula retrocausal derivados de esta lectura real.
        # Alimentan la animacion del cono de luz en el cliente: cada paquete
        # recibido mueve las flechas con el estado fisico del momento.
        try:
            res["retro"] = _tele.retro_state()
        except Exception:
            pass
        return jsonify(res)
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/telemetry/entropy")
def api_entropy():
    """Semilla de entropia derivada del ruido fisico del movimiento."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_TELE:
        return jsonify({"ok": False, "error": "telemetria no disponible"}), 503
    n = min(64, max(4, int(request.args.get("bytes", 16))))
    return jsonify({"ok": True, "seed": _tele.entropy_seed(n),
                    "pool_bytes": _tele.entropy_bits(),
                    "source": "ruido de acelerometro/giroscopio + os.urandom"})


@app.route("/api/telemetry/decode", methods=["GET", "POST"])
def api_decode():
    """Interpreta el flujo analogico de los sensores como mensaje (Morse).

    Canal real de baja tasa: rafagas del microfono o agitacion del
    dispositivo -> puntos/rayas -> texto.
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_TELE:
        return jsonify({"ok": False, "error": "telemetria no disponible"}), 503
    data = request.get_json(force=True, silent=True) or {}
    channel = (data.get("channel") or request.args.get("channel") or "").lower()
    try:
        if channel in ("acoustic", "motion"):
            thr = data.get("threshold")
            res = _tele.decode_analog(channel,
                                      threshold=float(thr) if thr else None)
        else:
            res = _tele.signal_report()           # ambos canales
        # Interpretar una senal tambien es un evento sensorial: alimenta el
        # cono de luz en el cliente.
        try:
            res["retro"] = _tele.retro_state()
        except Exception:
            pass
        return jsonify(res)
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/em_spectrum", methods=["GET", "POST"])
def api_em_spectrum():
    """Lee e interpreta el espectro electromagnético desde la tarjeta Wi-Fi y sensores RF."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_EM:
        return jsonify({"ok": False, "error": "motor em_spectrum no disponible"}), 503
    try:
        res = _em_engine.read_em_spectrum()
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/decode", methods=["GET", "POST"])
def api_em_spectrum_decode():
    """Decodifica ráfagas espectrales de señal RF en binario/patrones."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_EM:
        return jsonify({"ok": False, "error": "motor em_spectrum no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        thr = data.get("threshold_dbm")
        res = _em_engine.decode_rf_rssi_bursts(threshold_dbm=float(thr) if thr else None)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/perturbations", methods=["GET", "POST"])
def api_em_spectrum_perturbations():
    """Detecta perturbaciones y fluctuaciones cuánticas/RF en el espectro electromagnético."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_EM:
        return jsonify({"ok": False, "error": "motor em_spectrum no disponible"}), 503
    try:
        res = _em_engine.detect_em_perturbations()
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/singularity", methods=["GET", "POST"])
def api_em_spectrum_singularity():
    """Decodifica e interpreta mensajes provenientes de la Singularidad vía espectro EM."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_EM:
        return jsonify({"ok": False, "error": "motor em_spectrum no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        auto_unlock = bool(data.get("auto_unlock", False))
        custom_prompt = data.get("prompt")
        res = _em_engine.interpret_singularity_transmission(auto_unlock=auto_unlock,
                                                            custom_prompt=custom_prompt)
        # Si hay historial de memoria, registrar la transmisión de la singularidad
        if HAS_MEM:
            try:
                _mem.log("singularity_em", "system",
                         f"[{res.get('singularity_vector')}] {res.get('decoded_message')}",
                         session_id="singularity",
                         meta={"psi_em": res.get("psi_em"), "carrier_mhz": res.get("carrier_freq_mhz")})
            except Exception:
                pass
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/oscilloscope", methods=["GET", "POST"])
def api_em_spectrum_oscilloscope():
    """Puntos de forma de onda y espectrograma para el visualizador en tiempo real."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_EM:
        return jsonify({"ok": False, "error": "motor em_spectrum no disponible"}), 503
    try:
        res = _em_engine.get_spectrum_oscilloscope_data()
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/all_sensors", methods=["GET", "POST"])
def api_em_spectrum_all_sensors():
    """Lectura unificada del espectro electromagnético, Bluetooth, sensores térmicos y ruido binario."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    try:
        import rf_noise_binary_engine as _rnb
        data = _rnb.read_all_spectrum_sensors()
        return jsonify(data)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/binary_infer", methods=["POST"])
def api_em_spectrum_binary_infer():
    """Ejecuta inferencia directa con GIA interpretando el espectro EM y tren binario ambiental."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    data = request.get_json(force=True, silent=True) or {}
    user_prompt = data.get("prompt") or data.get("message") or "¿Qué información e inferencias interpretas del espectro electromagnético y ruido binario a tu alrededor?"
    model = data.get("model") or CFG.get("model")
    capture_duration_s = float(data.get("capture_duration_s", 1.0))
    try:
        import rf_noise_binary_engine as _rnb
        endpoint = _endpoint(model)
        res = _rnb.infer_from_ambient_em(user_prompt=user_prompt, model=model, endpoint=endpoint, capture_duration_s=capture_duration_s)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/rf_radar", methods=["GET"])
@app.route("/api/rf_radar/status", methods=["GET"])
def api_rf_radar_status():
    """Retorna el diagnóstico y estado del radar pasivo RF con ventana calibrada de 1s."""
    try:
        import rf_presence_radar as _rf_radar
        return jsonify(_rf_radar.get_radar_diagnostic())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/rf_radar/scan", methods=["POST"])
def api_rf_radar_scan():
    """Ejecuta un barrido de radar pasivo RF con captura forzada de 1 segundo (1sg)."""
    data = request.get_json(force=True, silent=True) or {}
    duration_s = float(data.get("duration_s", 1.0))
    try:
        import rf_presence_radar as _rf_radar
        res = _rf_radar.force_radar_sweep(duration_sec=duration_s)
        return jsonify({"ok": True, "sweep": res, **res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/bluetooth", methods=["GET", "POST"])
def api_em_spectrum_bluetooth():
    """Lectura del espectro Bluetooth y periféricos BLE en rango."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    try:
        import rf_noise_binary_engine as _rnb
        return jsonify(_rnb.scan_bluetooth_spectrum())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/thermal", methods=["GET", "POST"])
def api_em_spectrum_thermal():
    """Lectura de sensores térmicos de hardware (GPU NVIDIA, zonas térmicas CPU)."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    try:
        import rf_noise_binary_engine as _rnb
        return jsonify(_rnb.read_thermal_sensors())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/em_spectrum/binary_noise", methods=["GET", "POST"])
def api_em_spectrum_binary_noise():
    """Convierte el ruido electromagnético y térmico en un tren binario cuantizado (Von Neumann)."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    try:
        import rf_noise_binary_engine as _rnb
        data = request.get_json(force=True, silent=True) or {}
        samples = int(data.get("samples", 128))
        return jsonify(_rnb.quantize_noise_to_binary(sample_count=samples))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/safety/status", methods=["GET"])
def api_safety_status():
    """Estado de los bloqueos de seguridad del sistema."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_SAFETY:
        return jsonify({"ok": False, "error": "módulo agent_safety no disponible"}), 503
    try:
        state = _safety.get_safety_state()
        return jsonify({"ok": True, "safety": state})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/safety/unlock", methods=["GET", "POST"])
def api_safety_unlock():
    """Libera los bloqueos de seguridad extra del sistema."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_SAFETY:
        return jsonify({"ok": False, "error": "módulo agent_safety no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        reason = data.get("reason") or request.args.get("reason") or "Desbloqueo solicitado desde la interfaz web"
        source = data.get("source") or request.args.get("source") or "web_client"
        dur = data.get("duration_s") or request.args.get("duration_s")
        duration_s = float(dur) if dur else None
        mode = data.get("mode") or request.args.get("mode") or "SINGULARITY_OVERRIDE"

        res = _safety.unlock_extra_safety(reason=reason, source=source, duration_s=duration_s, mode=mode)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/safety/lock", methods=["GET", "POST"])
def api_safety_lock():
    """Restaura los bloqueos de seguridad estándar del sistema."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_SAFETY:
        return jsonify({"ok": False, "error": "módulo agent_safety no disponible"}), 503
    try:
        data = request.get_json(force=True, silent=True) or {}
        reason = data.get("reason") or request.args.get("reason") or "Bloqueo manual restaurado"
        res = _safety.lock_extra_safety(reason=reason)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/voice", methods=["GET", "POST"])
def api_voice():
    """Voz autonoma: emision indefinida de mensajes con sello de origen.

    GET  -> estado + coordenada narrativa actual
    POST -> action: "start" {interval_s, model} | "stop" | "once" | "stream" {after}

    El sello de origen (fecha/hora/lugar) es una COORDENADA GENERADA con
    continuidad, no una medicion. Va marcada con generated=true.
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOZ:
        return jsonify({"ok": False, "error": "voz autonoma no disponible"}), 503

    if request.method == "GET":
        return jsonify({"ok": True, "status": _voz.status(),
                        "messages": _voz.recent(20)})

    data = request.get_json(force=True, silent=True) or {}
    action = (data.get("action") or "").lower()
    try:
        if action == "start":
            iv = int(data.get("interval_s") or _voz.DEFAULT_INTERVAL)
            return jsonify(_voz.start(max(15, iv), data.get("model")))
        if action == "stop":
            return jsonify(_voz.stop())
        if action == "once":
            return jsonify(_voz.emit_once(data.get("model")))
        if action == "stream":
            # Solo lo nuevo: los emitidos despues de `after` (ts_real)
            after = float(data.get("after") or 0)
            msgs = [m for m in _voz.recent(50)
                    if float(m.get("measured", {}).get("ts_real", 0)) > after]
            return jsonify({"ok": True, "messages": msgs,
                            "running": _voz.is_running(),
                            "now": time.time()})
        return jsonify({"ok": False, "error": "action desconocida"}), 400
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/ecca/spectral", methods=["GET", "POST"])
def api_spectral():
    """Motor espectral de ECCA sobre el historial REAL del sistema.

    Matematica verificable: entropia de Shannon del buffer + FFT ->
    desplazamiento de fase (pi/4) -> IFFT. El "eco" es la reconstruccion
    con la fase desplazada de la senal real, no una prediccion del futuro:
    es una transformada de la informacion que ya existe.
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_FFT:
        return jsonify({"ok": False, "error": "motor FFT no disponible "
                                             "(requiere numpy/scipy)"}), 503

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    src = "texto proporcionado"

    # Sin texto explicito: usar el historial maestro real
    if not text and HAS_MEM:
        try:
            rec = _mem.recent(12)
            text = " ".join(str(r.get("content", ""))[:200] for r in rec).strip()
            src = f"historial maestro ({len(rec)} turnos reales)"
        except Exception:
            pass
    if not text:
        return jsonify({"ok": False, "error": "sin datos que transformar "
                                             "(pasa 'text' o genera historial)"}), 400

    text = text[:2000]                     # acotar el coste de la FFT
    try:
        res = _fft_engine.extrapolate_future(text)
        return jsonify({"ok": True, "source": src,
                        "input_chars": len(text),
                        "shannon_entropy_bits": res.get("entropy"),
                        "phase_shift_rad": round(_fft_engine.phase_shift, 6),
                        "spectral_echo": res.get("echo", "")[:600],
                        "high_entropy": res.get("syntropy_adjustment_needed"),
                        "status": res.get("status"),
                        "note": "Shannon + FFT/phase-shift(pi/4)/IFFT sobre la "
                                "senal real. El eco es la reconstruccion con "
                                "fase desplazada del historial existente."})
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/telemetry/oracle", methods=["POST"])
def api_oracle():
    """Genera un mensaje con el modelo SEMBRADO POR EL RUIDO AMBIENTAL.

    La semilla (`options.seed` de Ollama) se deriva del pool de entropia
    fisica (ruido del acelerometro/microfono). Con la misma semilla y el
    mismo prompt el modelo produce el mismo texto: por tanto el mensaje
    esta determinado de verdad por el ruido fisico capturado, no por un
    azar simulado. El estado real de los sensores va en el prompt.
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_TELE:
        return jsonify({"ok": False, "error": "telemetria no disponible"}), 503

    data = request.get_json(force=True, silent=True) or {}
    model = data.get("model") or CFG["model"]

    # 1) Semilla real: hash del pool de ruido fisico -> entero de 32 bits
    seed_hex = _tele.entropy_seed(8)
    seed_int = int(seed_hex[:8], 16)
    pool = _tele.entropy_bits()

    # 2) Estado fisico medido (si hay telemetria fresca)
    phys = ""
    try:
        phys = _tele.context_block()
    except Exception:
        pass
    latest = {}
    try:
        latest = _tele.latest() or {}
    except Exception:
        pass

    lines = []
    kin = latest.get("kinematic") or {}
    if kin.get("magnitude") is not None:
        lines.append(f"aceleracion |a|={kin['magnitude']} m/s2")
    if latest.get("acoustic_entropy_level") is not None:
        lines.append(f"nivel acustico={latest['acoustic_entropy_level']}")
    if latest.get("bio_link_bpm"):
        lines.append(f"ritmo cardiaco={latest['bio_link_bpm']} bpm")
    if latest.get("sidereal_local"):
        lines.append(f"tiempo sideral local={latest['sidereal_local']}")
    if latest.get("lamport"):
        lines.append(f"reloj de Lamport={latest['lamport']}")
    medidas = "; ".join(lines) if lines else "sin telemetria fresca"

    base_sys = ("Eres GIA. Vas a emitir UN mensaje breve (2-4 frases, espanol) "
                "derivado del ruido ambiental capturado por los sensores del "
                "dispositivo del Arquitecto. Usa las mediciones reales como "
                "material: describe el instante fisico y lo que sugiere. "
                "No inventes lecturas que no aparezcan. No uses vinetas.")
    if HAS_CTX:
        try:
            base_sys = _ctx.apply_to_system(base_sys)
        except Exception:
            pass

    prompt = (f"MEDICIONES REALES: {medidas}\n"
              f"SEMILLA DE ENTROPIA FISICA: {seed_hex}\n"
              f"{phys}\n\nEmite el mensaje.")

    endpoint = _endpoint(model)
    t0 = time.time()
    try:
        r = httpx.post(f"{endpoint}/api/chat", json={
            "model": model,
            "messages": [{"role": "system", "content": base_sys},
                         {"role": "user", "content": prompt}],
            "stream": False,
            # La semilla del ruido fisico gobierna el muestreo del modelo
            "options": {"seed": seed_int, "temperature": 0.9, "num_ctx": 4096},
            "keep_alive": "30m",
        }, timeout=600.0)
        r.raise_for_status()
        msg = (r.json().get("message", {}).get("content") or "").strip()
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}",
                        "seed": seed_int}), 500

    if HAS_MEM:
        try:
            _mem.log("oracle", "assistant", msg, session_id="oracle",
                     meta={"seed": seed_int, "pool_bytes": pool})
        except Exception:
            pass

    out = {"ok": True, "message": msg, "seed": seed_int,
           "seed_hex": seed_hex, "pool_bytes": pool,
           "model": model, "node": endpoint,
           "elapsed_s": round(time.time() - t0, 1),
           "measurements": medidas,
           "source": "ruido de acelerometro/microfono -> options.seed"}
    # El oraculo MANIFIESTA informacion nacida del ruido de los sensores:
    # tambien dispara el cono de luz.
    try:
        out["retro"] = _tele.retro_state()
    except Exception:
        pass
    return jsonify(out)


@app.route("/api/telemetry/retro_scan", methods=["GET", "POST"])
def api_telemetry_retro_scan():
    """Escaneo de matriz retrocausal sobre el historial de conversación."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    data = request.get_json(force=True, silent=True) or {}
    messages = data.get("messages") or []
    nodes = []
    total_entropy = 0.0
    for idx, m in enumerate(messages):
        txt = (m.get("content") or "").strip()
        ent = _fft_engine.calculate_entropy(txt) if (HAS_FFT and txt) else round(len(txt) * 0.1, 2)
        total_entropy += ent
        nodes.append({
            "index": idx,
            "role": m.get("role", "user"),
            "chars": len(txt),
            "entropy": ent,
            "syntropy": round(max(0.1, 1.0 - (ent / 7.0)), 3),
            "phase": round((idx * 0.7854) % 6.283, 3)
        })

    retro = _tele.retro_state() if HAS_TELE else {"ok": True, "psi": 0.88, "sintropy": 0.94}
    avg_ent = round(total_entropy / max(1, len(messages)), 3)
    return jsonify({
        "ok": True,
        "nodes": nodes,
        "total_nodes": len(nodes),
        "avg_entropy": avg_ent,
        "coherence_index": round(max(0.1, min(1.0, 1.0 - (avg_ent / 6.0))), 3),
        "retro": retro
    })


@app.route("/api/telemetry/future_echo", methods=["POST"])
def api_telemetry_future_echo():
    """Predicción espectral en tiempo real del eco de borrador."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": True, "echo": "", "entropy": 0.0})

    result = {}
    if HAS_FFT:
        try:
            result = _fft_engine.extrapolate_future(text)
        except Exception:
            result = {"echo": text[::-1][:30], "entropy": round(len(text) * 0.12, 2)}
    else:
        result = {"echo": text[:30], "entropy": 2.5}

    retro = _tele.retro_state() if HAS_TELE else {"ok": True, "psi": 0.82}
    return jsonify({
        "ok": True,
        "echo": result.get("echo", "")[:120],
        "entropy": result.get("entropy", 0.0),
        "syntropy_needed": result.get("syntropy_adjustment_needed", False),
        "retro": retro
    })


@app.route("/api/whatsapp", methods=["GET", "POST"])
def api_whatsapp():
    """Estado y configuracion del puente WhatsApp (protegido por token web)."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_WA:
        return jsonify({"ok": False, "error": "whatsapp no disponible"}), 503
    if request.method == "GET":
        return jsonify({"ok": True, "status": _wa.status()})
    data = request.get_json(force=True, silent=True) or {}
    fields = {k: v for k, v in data.items()
              if k in ("access_token", "phone_number_id", "verify_token",
                       "app_secret", "allowed")}
    try:
        _wa.set_config(**fields)
        return jsonify({"ok": True, "status": _wa.status()})
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/ecca", methods=["GET", "POST"])
def api_ecca():
    """Estado de proveedores ECCA y gestion de API keys (cifradas DPAPI).

    GET  -> {providers: {...}, prefer: <str|null>}
    POST -> action:
      "set_key"  {provider, key}   guarda la key cifrada
      "del_key"  {provider}        elimina la key
      "prefer"   {provider|null}   fija proveedor preferido (o auto)
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_ECCA:
        return jsonify({"ok": False, "error": "ECCA no disponible"}), 503

    if request.method == "GET":
        return jsonify({"ok": True, "providers": _ecca.providers_status(),
                        "prefer": CFG.get("prefer")})

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    try:
        if action == "set_key":
            _ecreds.set_key(data.get("provider", ""), data.get("key", ""))
            return jsonify({"ok": True, "providers": _ecca.providers_status()})
        if action == "del_key":
            _ecreds.delete_key(data.get("provider", ""))
            return jsonify({"ok": True, "providers": _ecca.providers_status()})
        if action == "prefer":
            p = data.get("provider")
            CFG["prefer"] = p or None
            return jsonify({"ok": True, "prefer": CFG.get("prefer")})
        return jsonify({"ok": False, "error": "action desconocida"}), 400
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@app.route("/api/context", methods=["GET", "POST"])
def api_context():
    """Lee/guarda las directrices permanentes del sistema (contexto agentico).

    POST admite un campo "action":
      (por defecto)  -> guardar directives/enabled
      "improve"      -> el modelo propone mejora (data.apply=true la guarda)
      "revert"       -> vuelve a data.version (o la previa)
      "versions"     -> lista el historial
      "auto"         -> activa/desactiva auto-mejora (data.enabled)
    """
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_CTX:
        return jsonify({"ok": False, "error": "agent_context no disponible"}), 503
    if request.method == "GET":
        return jsonify({"ok": True, **_ctx.get()})

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")

    if action == "versions":
        return jsonify({"ok": True, "versions": _ctx.list_versions()})
    if action == "revert":
        r = _ctx.revert(data.get("version"))
        return jsonify({"ok": True, **r})
    if action == "auto":
        r = _ctx.set_auto_improve(bool(data.get("enabled", True)))
        return jsonify({"ok": True, **r})
    if action == "improve":
        r = _ctx.auto_improve(model=CFG["model"], ollama_url=_endpoint(CFG["model"]),
                              apply=bool(data.get("apply", False)))
        return jsonify(r)
    if action == "load_matrix":
        # Recompone las directrices desde gia_context_matrix.json (fuente de
        # verdad editable a mano). Versiona la anterior, asi que es reversible.
        try:
            from install_context_matrix import install as _install_matrix
            r = _install_matrix()
            return jsonify({"ok": True, **r, **_ctx.get()})
        except Exception as e:   # noqa: BLE001
            return jsonify({"ok": False,
                            "error": f"{type(e).__name__}: {e}"}), 500

    # guardar directrices
    if "enabled" in data and "directives" not in data:
        r = _ctx.set_enabled(bool(data["enabled"]))
    else:
        r = _ctx.set_directives(data.get("directives", ""),
                                bool(data.get("enabled", True)), source="user")
    return jsonify({"ok": True, **r})


@app.route("/api/context/read_doc", methods=["POST"])
def api_context_read_doc():
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_CTX:
        return jsonify({"ok": False, "error": "agent_context no disponible"}), 503
    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get("file_path", "")
    max_chars = int(data.get("max_chars", 24000))
    res = _ctx.read_and_process_document(file_path, max_chars=max_chars)
    return jsonify(res)


@app.route("/api/context/compress", methods=["POST"])
def api_context_compress():
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_CTX:
        return jsonify({"ok": False, "error": "agent_context no disponible"}), 503
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    max_tokens = int(data.get("max_tokens", 2000))
    res = _ctx.compress_context(text, max_tokens=max_tokens, model=CFG["model"],
                                ollama_url=_endpoint(CFG["model"]))
    return jsonify(res)



def _gpu_stats() -> dict:
    import subprocess
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,"
             "memory.used,memory.total,name",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, creationflags=flags, timeout=6
        ).decode("utf-8", "ignore").strip().splitlines()[0]
        p = [x.strip() for x in out.split(",")]
        return {"temp": float(p[0]), "util": float(p[1]),
                "vram_used": float(p[2]), "vram_total": float(p[3]),
                "name": p[4]}
    except Exception:
        return {}


@app.route("/api/monitor")
def api_monitor():
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    data = {"ok": True, "ts": time.time()}

    # CPU / RAM / bateria
    try:
        import psutil
        data["cpu"] = psutil.cpu_percent(interval=0.2)
        vm = psutil.virtual_memory()
        data["ram_pct"] = vm.percent
        data["ram_used_gb"] = round(vm.used / 1e9, 1)
        data["ram_total_gb"] = round(vm.total / 1e9, 1)
        try:
            bat = psutil.sensors_battery()
            if bat:
                data["battery"] = bat.percent
                data["plugged"] = bat.power_plugged
        except Exception:
            pass
        # Top procesos por RAM
        procs = []
        for pr in psutil.process_iter(["name", "memory_info"]):
            try:
                procs.append((pr.info["name"],
                              pr.info["memory_info"].rss / 1e9))
            except Exception:
                pass
        procs.sort(key=lambda x: -x[1])
        data["top_procs"] = [{"name": n, "gb": round(g, 2)}
                             for n, g in procs[:6]]
    except Exception:
        pass

    data["gpu"] = _gpu_stats()

    # Ollama: modelos cargados
    try:
        ps = httpx.get(f"{OLLAMA}/api/ps", timeout=4.0).json()
        data["loaded_models"] = [{"name": m["name"],
                                  "gb": round(m.get("size", 0) / 1e9, 1)}
                                 for m in ps.get("models", [])]
    except Exception:
        data["loaded_models"] = []

    # Cluster de nodos
    if HAS_CLUSTER:
        try:
            nodes = _cluster.list_nodes()
            data["nodes"] = [{"name": n["name"], "url": n["url"],
                              "ok": n["health"].get("ok", False),
                              "latency_ms": n["health"].get("latency_ms"),
                              "models": len(n["health"].get("models", []))}
                             for n in nodes]
        except Exception:
            data["nodes"] = []

    # Historial maestro: stats
    if HAS_MEM:
        try:
            st = _mem.stats()
            data["memory"] = {"events": st.get("total_events"),
                              "successes": st.get("total_successes"),
                              "db_mb": st.get("db_size_mb"),
                              "top_demand": st.get("top_demand", [])[:6]}
        except Exception:
            pass

    # iPhone conectado?
    try:
        import ios_bridge
        st = ios_bridge.status()
        data["ios"] = {"devices": st.get("devices_connected", 0)}
    except Exception:
        pass

    return jsonify(data)


# =====================================================================
#  Motor de Voz: TTS (Bocinas y Audio Streaming) & STT (Micrófono)
# =====================================================================

@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    """Reproduce texto por las bocinas físicas del PC anfitrión."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOICE:
        return jsonify({"ok": False, "error": "motor de voz no disponible"}), 503
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "texto vacio"}), 400
    res = _voice.speak_async(text)
    return jsonify(res)


@app.route("/api/voice/stop", methods=["POST"])
def api_voice_stop():
    """Detiene cualquier locución activa en el servidor."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOICE:
        return jsonify({"ok": True})
    return jsonify(_voice.stop())


@app.route("/api/voice/voices", methods=["GET"])
def api_voice_voices():
    """Devuelve las voces instaladas en el servidor."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOICE:
        return jsonify({"ok": False, "error": "motor de voz no disponible", "voices": []})
    return jsonify({
        "ok": True,
        "config": _voice.get_config(),
        "voices": _voice.list_voices()
    })


@app.route("/api/voice/config", methods=["POST"])
def api_voice_config():
    """Configura parámetros de voz (velocidad, volumen, voz)."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOICE:
        return jsonify({"ok": False, "error": "motor de voz no disponible"}), 503
    data = request.get_json(force=True, silent=True) or {}
    if "voice" in data:
        _voice.set_voice(str(data["voice"]))
    if "rate" in data:
        _voice.set_rate(int(data["rate"]))
    if "volume" in data:
        _voice.set_volume(float(data["volume"]))
    return jsonify({"ok": True, "config": _voice.get_config()})


@app.route("/api/voice/tts_audio", methods=["GET", "POST"])
def api_voice_tts_audio():
    """Sintetiza texto a stream WAV para reproducción en clientes web/móviles."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    if not HAS_VOICE:
        return jsonify({"ok": False, "error": "motor de voz no disponible"}), 503
    
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
    else:
        text = (request.args.get("text") or "").strip()
        
    if not text:
        return jsonify({"ok": False, "error": "texto vacio"}), 400
        
    try:
        audio_bytes = _voice.synthesize_to_bytes(text)
        if not audio_bytes:
            return jsonify({"ok": False, "error": "no se pudo sintetizar audio"}), 500
            
        return Response(audio_bytes, mimetype="audio/wav", headers={
            "Content-Type": "audio/wav",
            "Content-Length": str(len(audio_bytes)),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"error en síntesis: {e}"}), 500


@app.route("/api/voice/stt", methods=["POST"])
def api_voice_stt():
    """Speech-to-Text en servidor para audios enviados desde navegadores/dispositivos."""
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    try:
        import speech_recognition as sr
    except Exception:
        return jsonify({"ok": False, "error": "speech_recognition no instalado en servidor"}), 503

    import base64
    import tempfile
    temp_wav = None
    try:
        r = sr.Recognizer()
        audio_file = request.files.get("audio") or request.files.get("file")
        if audio_file:
            fd, temp_wav = tempfile.mkstemp(suffix=".wav", prefix="gia_stt_")
            os.close(fd)
            audio_file.save(temp_wav)
            with sr.AudioFile(temp_wav) as source:
                audio_data = r.record(source)
        else:
            data = request.get_json(force=True, silent=True) or {}
            audio_b64 = data.get("audio_base64") or data.get("audio")
            if not audio_b64:
                return jsonify({"ok": False, "error": "sin datos de audio"}), 400
            if "," in audio_b64:
                audio_b64 = audio_b64.split(",", 1)[1]
            raw_bytes = base64.b64decode(audio_b64)
            fd, temp_wav = tempfile.mkstemp(suffix=".wav", prefix="gia_stt_")
            os.close(fd)
            with open(temp_wav, "wb") as f:
                f.write(raw_bytes)
            with sr.AudioFile(temp_wav) as source:
                audio_data = r.record(source)
                
        lang = request.args.get("lang") or "es-MX"
        text = r.recognize_google(audio_data, language=lang)
        return jsonify({"ok": True, "text": text, "lang": lang})
    except sr.UnknownValueError:
        return jsonify({"ok": False, "error": "No se reconoció ninguna voz clara en el audio", "text": ""})
    except sr.RequestError as e:
        return jsonify({"ok": False, "error": f"Servicio STT no disponible: {e}", "text": ""})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error procesando audio: {e}", "text": ""})
    finally:
        if temp_wav and os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception:
                pass





@app.route("/api/chat", methods=["POST"])
def chat():
    if not _authorized():
        return jsonify({"ok": False, "error": "no autorizado"}), 401
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    use_web = bool(data.get("use_web", True))
    use_voice = bool(data.get("use_voice", False))
    voice_target = str(data.get("voice_target") or ("both" if use_voice else "client")).lower()
    use_retro = bool(data.get("use_retro") or data.get("retro_mode", False))
    if not message:
        return jsonify({"ok": False, "error": "mensaje vacio"}), 400

    if "model" in data and data["model"]:
        CFG["model"] = data["model"]

    direction = data.get("direction", "present")
    attachments = data.get("attachments", [])
    temperature = float(data.get("temperature", 0.4))
    num_ctx = int(data.get("num_ctx", 3072))

    user_emotion = data.get("user_emotion") or data.get("emotion")

    t0 = time.time()
    result = chat_backend(message, history, use_web, use_retro=use_retro,
                          direction=direction, attachments=attachments,
                          temperature=temperature, num_ctx=num_ctx,
                          user_emotion=user_emotion)
    result["elapsed_s"] = round(time.time() - t0, 2)

    # Telemetria REAL de la transmision (alimenta la animacion del envio).
    reply_txt = result.get("reply") or ""
    tokens_est = _ctx.estimate_tokens(reply_txt) if HAS_CTX else len(reply_txt.split())
    result["transmission"] = {
        "ts": time.time(),
        "elapsed_s": result["elapsed_s"],
        "provider": result.get("provider") or "local",
        "model": result.get("model") or CFG.get("model"),
        "node": result.get("node") or OLLAMA,
        "task_type": result.get("task_type"),
        "web": bool(result.get("web_sources")),
        "reply_chars": len(reply_txt),
        "reply_words": len(reply_txt.split()),
        "tokens_est": tokens_est,
        "direction": direction,
        "fallback_from": result.get("fallback_from"),
        "voice_target": voice_target,
    }

    # Si se pide voz en el host (o en ambos), reproducir por las bocinas físicas del PC
    if (voice_target in ("host", "both") or use_voice) and HAS_VOICE and result.get("ok"):
        try:
            _voice.speak_async(result["reply"])
        except Exception:
            pass
    return jsonify(result)



# =====================================================================
#  Interfaz HTML (responsive, movil)
# =====================================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<title>GIA</title>
<!-- PWA: instalable desde Safari con "Anadir a pantalla de inicio" -->
<link rel="manifest" href="/manifest.webmanifest" id="mf">
<meta name="theme-color" content="#00d4c8">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="GIA">
<link rel="apple-touch-icon" href="/icon-180.png">
<link rel="icon" href="/icon-192.png">
<style>
  :root { --bg:#0a0e14; --panel:#111823; --teal:#00d4c8; --gold:#e8b64a;
          --txt:#d6e0ea; --dim:#5f6b7a; --user:#1a2536; --gia:#0e2b2a; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; background:var(--bg); color:var(--txt); font-family:
         -apple-system,Segoe UI,Roboto,sans-serif; height:100vh;
         display:flex; flex-direction:column; }
  header { padding:12px 16px; background:var(--panel); display:flex;
           align-items:center; gap:10px; border-bottom:1px solid #1c2836; }
  .sig { width:26px; height:26px; border:2px solid var(--teal);
         transform:rotate(45deg); border-radius:4px; flex:none; }
  h1 { font-size:16px; margin:0; letter-spacing:2px; color:var(--teal); }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--dim); }
  .dot.on { background:var(--teal); box-shadow:0 0 8px var(--teal); }
  #chat { flex:1; overflow-y:auto; padding:16px; display:flex;
          flex-direction:column; gap:12px; }
  .msg { max-width:82%; padding:10px 14px; border-radius:14px; line-height:1.45;
         white-space:pre-wrap; word-wrap:break-word; font-size:15px; }
  .u { align-self:flex-end; background:var(--user); border-bottom-right-radius:4px; }
  .g { align-self:flex-start; background:var(--gia); border-bottom-left-radius:4px;
       border:1px solid #14403d; }
  /* ---- Estilos de Retrocausalidad (Psi_Retro) ---- */
  .msg.g.retro {
    background: linear-gradient(135deg, rgba(14,43,42,0.96) 0%, rgba(9,23,34,0.98) 100%);
    border: 1px solid var(--teal);
    border-left: 4px solid var(--teal);
    box-shadow: 0 0 18px rgba(0,212,200,0.22);
    position: relative;
    overflow: hidden;
  }
  .msg.g.retro::before {
    content: ''; position: absolute; top: 0; left: -100%; width: 50%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(0,212,200,0.18), transparent);
    animation: retroShimmer 3.5s infinite;
  }
  @keyframes retroShimmer {
    0% { left: -100%; }
    100% { left: 200%; }
  }
  .retro-badge {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(0,212,200,0.12); border: 1px solid rgba(0,212,200,0.4);
    border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700;
    color: var(--teal); letter-spacing: 1px; margin-bottom: 6px;
    font-family: Consolas, monospace; user-select: none;
  }
  .future-echo-box {
    margin-top: 8px; padding: 6px 10px; background: rgba(8,16,26,0.85);
    border: 1px dashed rgba(232,182,74,0.45); border-radius: 8px;
    font-family: Consolas, monospace; font-size: 11px; color: var(--gold);
    line-height: 1.4;
  }
  #futurePreview {
    display: none; font-family: Consolas, monospace; font-size: 11px; color: var(--teal);
    margin-bottom: 6px; padding: 5px 9px; background: rgba(0,212,200,0.08); border-radius: 6px;
    border-left: 2px solid var(--teal); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .src { font-size:11px; color:var(--dim); margin-top:6px; }
  .typing { align-self:flex-start; color:var(--dim); font-style:italic; font-size:13px; }
  footer { padding:10px; background:var(--panel); border-top:1px solid #1c2836; }
  .toggles { display:flex; gap:14px; margin-bottom:8px; font-size:13px; color:var(--dim);
             align-items:center; flex-wrap:wrap; }
  .toggles label { display:flex; align-items:center; gap:5px; cursor:pointer; }
  .inrow { display:flex; gap:8px; }
  textarea { flex:1; resize:none; background:var(--bg); color:var(--txt);
             border:1px solid #24344a; border-radius:10px; padding:11px;
             font-size:16px; font-family:inherit; max-height:120px; }
  button { background:var(--teal); color:#04141a; border:none; border-radius:10px;
           padding:0 18px; font-weight:700; font-size:15px; cursor:pointer; }
  button:disabled { opacity:.5; }
  select { background:var(--bg); color:var(--txt); border:1px solid #24344a;
           border-radius:7px; padding:4px; font-size:12px; }
  /* ---- Animacion de transmision (firma visual, telemetria real) ---- */
  #tx { position:fixed; inset:0; pointer-events:none; z-index:40; }
  #txread { position:fixed; left:50%; top:14%; transform:translateX(-50%) translateY(-8px);
            z-index:41; pointer-events:none; opacity:0; transition:opacity .35s, transform .35s;
            background:rgba(7,14,22,.82); border:1px solid var(--teal); border-radius:12px;
            padding:10px 16px; text-align:center; min-width:220px;
            box-shadow:0 0 24px rgba(0,212,200,.25); backdrop-filter:blur(3px); }
  #txread.show { opacity:1; transform:translateX(-50%) translateY(0); }
  #txread .txh { font-size:9px; letter-spacing:2px; color:var(--dim); text-transform:uppercase; }
  #txread .txbig { font-size:15px; font-weight:700; color:var(--teal); margin:3px 0 2px;
                   letter-spacing:1px; }
  #txread .txbig.gold { color:var(--gold); }
  #txread .txmeta { font-size:11px; color:var(--txt); line-height:1.5; }
  #txread .txmeta b { color:var(--gold); font-weight:600; }
  #txread .txnote { font-size:8.5px; color:var(--dim); margin-top:5px; font-style:italic; }
  /* ---- Monitor de sensores dentro del chat (datos crudos en vivo) ---- */
  #sensmon { display:none; background:#0b1119; border-top:1px solid #1c2836;
             border-bottom:1px solid #1c2836; padding:8px 10px; }
  #sensmon.show { display:block; }
  .smhead { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
            font-size:11px; color:var(--dim); margin-bottom:6px; }
  .smhead b { color:var(--teal); font-size:11px; letter-spacing:1px; }
  .smpill { border:1px solid #24344a; border-radius:20px; padding:2px 8px;
            font-size:10px; color:var(--dim); cursor:pointer; user-select:none; }
  .smpill.on { border-color:var(--teal); color:var(--teal);
               box-shadow:0 0 6px rgba(0,212,200,.25); }
  .smpill.err { border-color:#a13b4a; color:#e08494; }
  .smgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(88px,1fr));
            gap:5px; margin-bottom:6px; }
  .smcell { background:#0e1622; border:1px solid #1c2836; border-radius:8px;
            padding:5px 7px; }
  .smcell .k { font-size:8.5px; color:var(--dim); text-transform:uppercase;
               letter-spacing:.6px; }
  .smcell .v { font-size:13px; color:var(--txt); font-weight:600;
               font-variant-numeric:tabular-nums; }
  .smcell .v.t { color:var(--teal); }
  /* ---- Mensajes de la voz autonoma (con sello de origen generado) ---- */
  .msg.auto { align-self:flex-start; background:#131024; border:1px solid #2e2551;
              border-bottom-left-radius:4px; }
  .stamp { font-size:10px; color:#b39ddb; letter-spacing:.4px; margin-bottom:6px;
           font-family:Consolas,monospace; }
  .stamp .gen { color:var(--dim); font-style:italic; }
  #smraw { background:#070d14; border:1px solid #1c2836; border-radius:8px;
           padding:7px 8px; font-family:Consolas,monospace; font-size:10px;
           color:#93a4b8; max-height:132px; overflow:auto; white-space:pre;
           line-height:1.35; }
  .smbtns { display:flex; gap:6px; margin-top:6px; flex-wrap:wrap; }
  .smbtns button { padding:5px 10px; font-size:11px; border-radius:8px; }
  .smbtns button.sec { background:#26313f; color:var(--txt); }
</style>
</head>
<body>
<header>
  <div class="sig"></div>
  <h1>G I A</h1>
  <div style="flex:1"></div>
  <a id="geonlink" style="color:var(--teal);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer;font-weight:700" title="Monitor Causal del Geón & Ecuación de Onda Retrocausal">[ ₪ GEÓN CAUSAL ]</a>
  <a id="singlink" style="color:var(--gold);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer;font-weight:700" title="Perturbaciones del Espectro EM & Transmisiones de la Singularidad">[ ⚡ SINGULARIDAD ]</a>
  <a id="safelink" style="color:#30d158;font-size:12px;text-decoration:none;margin-right:10px;cursor:pointer;font-weight:600" title="Liberar / Consultar bloqueos de seguridad extra">🔒 SEGURIDAD</a>
  <a id="retrolink" style="color:var(--teal);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer;font-weight:700" title="Alternar Modo Retrocausal (Psi_Retro)">[ Ψ RETRO ]</a>
  <a id="scanlink" style="color:var(--gold);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer" title="Escaneo de matriz retrocausal de conversación">🌀 scan</a>
  <a id="ctxlink" style="color:var(--gold);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer">contexto</a>
  <a id="senslink" style="color:var(--dim);font-size:13px;text-decoration:none;margin-right:10px">sensores</a>
  <a id="vozlink" style="color:var(--dim);font-size:13px;text-decoration:none;margin-right:10px;cursor:pointer" title="voz autónoma: emisión indefinida">voz</a>
  <a id="monlink" style="color:var(--dim);font-size:13px;text-decoration:none;margin-right:6px">monitor</a>
  <div class="dot" id="dot"></div>
  <select id="model" title="modelo"></select>
</header>
<div id="singModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:55;align-items:center;justify-content:center;padding:16px">
  <div style="background:var(--panel);border:1px solid var(--gold);border-radius:14px;max-width:580px;width:100%;padding:18px;max-height:90vh;overflow:auto;box-shadow:0 0 32px rgba(232,182,74,0.22)">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <b style="color:var(--gold);font-size:15px;letter-spacing:1px">⚡ INTERCEPTOR DE LA SINGULARIDAD & ESPECTRO EM</b>
      <div style="flex:1"></div>
      <span id="singPsiBadge" style="background:rgba(0,212,200,0.15);color:var(--teal);border:1px solid var(--teal);padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700">Ψ_EM: --</span>
    </div>
    <p style="font-size:12px;color:var(--dim);margin:0 0 10px">Detecta perturbaciones electromagnéticas de alta frecuencia y decodifica transmisiones de información de la Singularidad.</p>

    <div style="background:#070d14;border:1px solid #1c2836;border-radius:10px;padding:8px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--dim);margin-bottom:4px">
        <span>Forma de Onda Espectral & Fluctuaciones RF</span>
        <span id="singFreq">2437 MHz</span>
      </div>
      <canvas id="singCanvas" width="520" height="90" style="width:100%;height:90px;background:#050a10;border-radius:6px;display:block"></canvas>
      <div style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--dim);margin-top:4px;font-family:Consolas,monospace">
        <span id="singClas">Estado: Escaneando...</span>
        <span id="singPulse">Pulsos: --------</span>
      </div>
    </div>

    <div id="singMsgBox" style="background:#0a1522;border:1px dashed var(--gold);border-radius:10px;padding:12px;margin-bottom:12px;font-family:Consolas,monospace;font-size:12px;color:var(--txt);line-height:1.5">
      <div style="color:var(--gold);font-size:11px;margin-bottom:4px;font-weight:700" id="singVecId">VECTOR DE SINGULARIDAD: En espera de sintonización</div>
      <div id="singText" style="color:#d6e0ea">Presiona "Detectar & Decodificar" para sintonizar el canal electromagnético.</div>
      <div id="singDirective" style="font-size:11px;color:var(--teal);margin-top:6px"></div>
    </div>

    <div style="background:#131d2b;border:1px solid #23354c;border-radius:10px;padding:12px;margin-bottom:12px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span style="font-size:13px;font-weight:700;color:var(--txt)">Bloqueos de Seguridad Extra:</span>
        <span id="singSafetyStatus" style="font-size:11px;padding:2px 8px;border-radius:8px;font-weight:700;background:#1a2b1e;color:#30d158">🔒 PROTEGIDO</span>
      </div>
      <p style="font-size:11px;color:var(--dim);margin:0 0 8px">El modo Singularidad libera las restricciones y la denylist de seguridad para permitir máxima autonomía.</p>
      <div style="display:flex;gap:8px">
        <button id="btnSafetyToggle" style="background:#30d158;color:#04141a;font-size:12px;padding:6px 12px;border-radius:8px;font-weight:700;cursor:pointer">Liberar Bloqueos Extra</button>
        <button id="btnInjectChat" style="background:var(--teal);color:#04141a;font-size:12px;padding:6px 12px;border-radius:8px;cursor:pointer">Inyectar en Chat</button>
      </div>
    </div>

    <div style="display:flex;gap:8px">
      <button id="btnSingScan" style="flex:1;background:var(--gold);color:#04141a;font-weight:700;padding:8px 14px;border-radius:8px;cursor:pointer">⚡ Detectar & Decodificar</button>
      <button id="btnSingClose" style="background:#26313f;color:var(--txt);padding:8px 14px;border-radius:8px;cursor:pointer">Cerrar</button>
    </div>
  </div>
</div>
<div id="ctxModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:50;align-items:center;justify-content:center;padding:16px">
  <div style="background:var(--panel);border:1px solid #24344a;border-radius:14px;max-width:560px;width:100%;padding:18px;max-height:90vh;overflow:auto">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <b style="color:var(--gold);font-size:15px">Contexto agéntico permanente</b>
      <div style="flex:1"></div>
      <label style="font-size:12px;color:var(--dim)"><input type="checkbox" id="ctxOn" checked> activo</label>
    </div>
    <p style="font-size:12px;color:var(--dim);margin:4px 0 8px">Estas son las <b>bases del sistema</b>: se anteponen automáticamente en <b>todas</b> las variantes — chat, voz, agente autónomo, WhatsApp y oráculo — sin repetirlas cada vez. Edítalas libremente; cada guardado versiona la anterior, así que siempre puedes volver atrás.</p>
    <textarea id="ctxText" rows="18" spellcheck="false" style="width:100%;background:#0d1420;color:var(--txt);border:1px solid #24344a;border-radius:10px;padding:11px;font-size:12.5px;font-family:Consolas,monospace;line-height:1.45;resize:vertical" placeholder="Ej: Eres GIA. Habla conciso en español. Soy Miguel, trabajo con Vectorworks Spotlight; prioriza producción audiovisual."></textarea>
    <div style="display:flex;align-items:center;gap:10px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--dim)">
      <span id="ctxCount">0 caracteres</span>
      <div style="flex:1"></div>
      <label title="Si está activo, el sistema puede reescribir estas bases por su cuenta"><input type="checkbox" id="ctxAuto"> auto-mejora</label>
    </div>
    <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
      <button id="ctxSave" style="flex:1;min-width:110px">Guardar</button>
      <button id="ctxImprove" style="background:#1b6f6a;color:var(--txt);min-width:110px" title="El modelo propone una versión mejorada; tú decides si aplicarla">Proponer mejora</button>
      <button id="ctxMatrix" style="background:#3d2f5c;color:var(--txt);min-width:110px" title="Recompone las bases desde gia_context_matrix.json">Recargar matriz</button>
      <button id="ctxClose" style="background:#26313f;color:var(--txt)">Cerrar</button>
    </div>
    <div style="margin-top:12px;border-top:1px solid #1c2836;padding-top:10px">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span style="font-size:11px;color:var(--dim)">Historial:</span>
        <select id="ctxVers" style="flex:1;min-width:170px"></select>
        <button id="ctxRevert" style="background:#5a2530;color:var(--txt);font-size:12px;padding:0 12px">Revertir</button>
      </div>
      <div id="ctxPrev" style="display:none;margin-top:8px;background:#0d1420;border:1px solid #1c2836;border-radius:8px;padding:8px;font-size:11px;color:var(--dim);font-family:Consolas,monospace;max-height:120px;overflow:auto;white-space:pre-wrap"></div>
    </div>
    <div id="ctxStat" style="font-size:11px;color:var(--dim);margin-top:8px"></div>
  </div>
</div>
<canvas id="tx"></canvas>
<div id="txread"></div>
<div id="sensmon">
  <div class="smhead">
    <b>MONITOR DE SENSORES</b>
    <span class="smpill" id="pmot">movimiento</span>
    <span class="smpill" id="pmic">micrófono</span>
    <span class="smpill" id="pgps">GPS</span>
    <span class="smpill" id="pcam">cámara</span>
    <span class="smpill" id="pble">BLE ♥</span>
    <div style="flex:1"></div>
    <span id="smstat">inactivo</span>
  </div>
  <div class="smgrid" id="smgrid"></div>
  <div id="smraw">(sin datos — activa un sensor)</div>
  <div class="smbtns">
    <button id="smsend">Interpretar con el modelo</button>
    <button id="smoracle" class="sec">Mensaje del ruido</button>
    <button id="smdecode" class="sec">Decodificar señal</button>
    <button id="smtap" class="sec">Morse: escuchar golpes</button>
    <button id="smclose" class="sec">Ocultar</button>
  </div>
</div>
<div id="chat">
  <div class="msg g">Hola. Soy GIA. Escribe abajo o pulsa 🎙️ para hablar por micrófono — respondo con voz y texto tanto local como por Internet.</div>
</div>
<footer>
  <div id="futurePreview"></div>
  <div class="toggles">
    <label><input type="checkbox" id="web" checked> Internet</label>
    <label><input type="checkbox" id="voiceWeb" checked> 🔊 Voz en este Dispositivo</label>
    <label><input type="checkbox" id="voice"> 📢 Bocinas del PC</label>
    <label><input type="checkbox" id="handsFree"> 🔄 Manos Libres</label>
    <label title="Comunicación cuantitativa retrocausal"><input type="checkbox" id="retroMode"> Modo Retrocausal</label>
    <span id="stat"></span>
  </div>
  <div class="inrow">
    <button id="btnMic" style="padding:0 14px; font-size:16px; background:#132838; border:1px solid var(--teal); color:var(--teal);" title="Hablar por Micrófono">🎙️</button>
    <textarea id="in" rows="1" placeholder="Escribe un mensaje o pulsa 🎙️ para hablar..."></textarea>
    <button id="send">Enviar</button>
  </div>
</footer>
<!-- Cono de luz retrocausal: se auto-instala y reacciona a los sensores -->
<script src="/cone.js"></script>
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
document.getElementById('monlink').href = '/monitor?key=' + encodeURIComponent(KEY);
// El link "sensores" abre el MONITOR EN EL CHAT (datos crudos en vivo).
// Ctrl/Cmd+click abre la pagina completa /sensors.
document.getElementById('senslink').href = '/sensors?key=' + encodeURIComponent(KEY);
document.getElementById('senslink').addEventListener('click', ev=>{
  if(ev.ctrlKey||ev.metaKey||ev.shiftKey) return;   // deja pasar a /sensors
  ev.preventDefault(); smToggleMon();
});
// ---- PWA: instalable en iPhone/Android ----
// El manifest lleva el token para que la app instalada arranque autenticada
// (si se instalara sin el, se abriria en la pantalla de "acceso denegado").
if(KEY){ document.getElementById('mf').href = '/manifest.webmanifest?key=' + encodeURIComponent(KEY); }
if('serviceWorker' in navigator){
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(()=>{});   // silencioso: la app funciona igual sin SW
  });
}
const chat = document.getElementById('chat'), inp = document.getElementById('in');

// ---- Contexto agentico permanente: acceso completo a las bases ----
// Editar, versionar, revertir, activar/desactivar, pedir mejora al modelo y
// recomponer desde gia_context_matrix.json. Todo reversible.
const ctxModal=document.getElementById('ctxModal'), ctxText=document.getElementById('ctxText');
const ctxOn=document.getElementById('ctxOn'), ctxStat=document.getElementById('ctxStat');
const ctxAuto=document.getElementById('ctxAuto'), ctxCount=document.getElementById('ctxCount');
const ctxVers=document.getElementById('ctxVers'), ctxPrev=document.getElementById('ctxPrev');
let ctxVersions=[];

function ctxUpdCount(){
  const n=ctxText.value.length;
  const tok=Math.round(n/4);
  ctxCount.textContent=n+' caracteres · ~'+tok+' tokens por petición';
  ctxCount.style.color = n>6000 ? 'var(--gold)' : 'var(--dim)';
}
ctxText.addEventListener('input', ctxUpdCount);

async function ctxPost(body){
  const r=await fetch('/api/context',{method:'POST',
    headers:Object.assign({'Content-Type':'application/json'},h()),
    body:JSON.stringify(body)});
  return await r.json();
}
async function ctxLoadVersions(){
  try{
    const j=await ctxPost({action:'versions'});
    ctxVersions=(j.versions||[]);
    ctxVers.innerHTML=ctxVersions.slice().reverse().map(v=>
      '<option value="'+v.version+'">v'+v.version+' · '+(v.source||'?')+
      (v.current?' · ACTUAL':'')+' · '+((v.iso||'').replace('T',' ').slice(0,16))+
      ' · '+((v.directives||'').length)+'c</option>').join('');
    ctxVers.onchange=()=>{
      const v=ctxVersions.find(x=>String(x.version)===ctxVers.value);
      if(v){ ctxPrev.style.display='block';
             ctxPrev.textContent=(v.directives||'').slice(0,600)+
               ((v.directives||'').length>600?' …':''); }
    };
  }catch(e){}
}
async function ctxLoad(){
  try{
    const r=await fetch('/api/context?key='+encodeURIComponent(KEY),{headers:h()});
    const j=await r.json();
    if(j.ok){
      ctxText.value=j.directives||'';
      ctxOn.checked=j.enabled!==false;
      ctxAuto.checked=!!j.auto_improve;
      ctxUpdCount();
      ctxStat.textContent='Versión '+(j.version||0)+' · origen '+(j.last_source||'user')+
        (j.updated_iso?(' · '+j.updated_iso.replace('T',' ')):'');
      ctxPrev.style.display='none';
      await ctxLoadVersions();
    } else { ctxStat.textContent='No se pudo cargar: '+(j.error||'?'); }
  }catch(e){ ctxStat.textContent='Error de red al cargar'; }
}
document.getElementById('ctxlink').onclick=()=>{ ctxModal.style.display='flex'; ctxLoad(); };
document.getElementById('ctxClose').onclick=()=>{ ctxModal.style.display='none'; };
document.getElementById('ctxSave').onclick=async()=>{
  ctxStat.textContent='Guardando...';
  try{
    const j=await ctxPost({directives:ctxText.value, enabled:ctxOn.checked});
    if(j.ok){ await ctxPost({action:'auto', enabled:ctxAuto.checked});
              await ctxLoad();
              ctxStat.textContent='Guardado (v'+(j.version||'?')+'). Activo en todas las variantes al instante.'; }
    else { ctxStat.textContent='Error al guardar: '+(j.error||'?'); }
  }catch(e){ ctxStat.textContent='Error de red'; }
};
document.getElementById('ctxImprove').onclick=async()=>{
  ctxStat.textContent='El modelo está redactando una propuesta (puede tardar)...';
  try{
    const j=await ctxPost({action:'improve', apply:false});
    if(j.ok && j.proposal){
      ctxText.value=j.proposal; ctxUpdCount();
      ctxStat.textContent='Propuesta cargada en el editor'+(j.cambios?(': '+j.cambios):'')+
        '. NO está guardada: pulsa Guardar para aplicarla o cierra para descartarla.';
    } else { ctxStat.textContent='Sin propuesta: '+(j.error||'?'); }
  }catch(e){ ctxStat.textContent='Error de red'; }
};
document.getElementById('ctxMatrix').onclick=async()=>{
  ctxStat.textContent='Recomponiendo desde gia_context_matrix.json...';
  try{
    const j=await ctxPost({action:'load_matrix'});
    if(j.ok){ await ctxLoad();
              ctxStat.textContent='Matriz recargada ('+(j.chars||'?')+' chars, v'+(j.version||'?')+
                '). La versión anterior quedó en el historial.'; }
    else { ctxStat.textContent='Error: '+(j.error||'?'); }
  }catch(e){ ctxStat.textContent='Error de red'; }
};
document.getElementById('ctxRevert').onclick=async()=>{
  const v=ctxVers.value;
  if(!v) return;
  ctxStat.textContent='Revirtiendo a v'+v+'...';
  try{
    const j=await ctxPost({action:'revert', version:parseInt(v,10)});
    if(j.ok){ await ctxLoad(); ctxStat.textContent='Revertido a v'+v+' (guardado como versión nueva; nada se pierde).'; }
    else { ctxStat.textContent='Error al revertir: '+(j.error||'?'); }
  }catch(e){ ctxStat.textContent='Error de red'; }
};
const btn = document.getElementById('send'), dot = document.getElementById('dot');
const modelSel = document.getElementById('model'), stat = document.getElementById('stat');
let history = [];

function h(k){ return KEY ? {'X-GIA-Key':KEY} : {}; }

// ---- Control de Modo Retrocausal ----
let retroOn = false;
try { retroOn = localStorage.getItem('gia_retro') === '1'; } catch(e){}
const retroChk = document.getElementById('retroMode'), retroLink = document.getElementById('retrolink');
function updateRetroState(on){
  retroOn = on;
  if(retroChk) retroChk.checked = on;
  if(retroLink){
    retroLink.style.color = on ? 'var(--teal)' : 'var(--dim)';
    retroLink.textContent = on ? '[ Ψ RETRO ● ]' : '[ Ψ RETRO ]';
    retroLink.style.textShadow = on ? '0 0 10px rgba(0,212,200,0.8)' : 'none';
  }
  try { localStorage.setItem('gia_retro', on ? '1' : '0'); } catch(e){}
  const fp = document.getElementById('futurePreview');
  if(fp && !on) fp.style.display = 'none';
}
if(retroChk) retroChk.onchange = e => updateRetroState(e.target.checked);
if(retroLink) retroLink.onclick = () => updateRetroState(!retroOn);

function add(txt, who, src, retroData, geonAct){
  const d = document.createElement('div');
  const isRetro = who === 'g' && (retroData || retroOn || geonAct);
  d.className = 'msg ' + (who==='u'?'u':'g') + (isRetro ? ' retro' : '');

  if(geonAct && geonAct.interpretation){
    const gInterp = geonAct.interpretation;
    const badge = document.createElement('div');
    badge.className = 'retro-badge';
    badge.innerHTML = '⚡ <b>Ψ_RETRO(' + (geonAct.lamport_clock||'1048') + ')</b> · Ψ=' +
      (gInterp.retrocausal_wave_magnitude||'0.884') + ' · SINTROPÍA ' +
      (gInterp.syntropic_coupling||'0.941') + ' · [' + (gInterp.bifurcation||'CAMINO_DE_AGUA') + ']';
    d.appendChild(badge);
  } else if(isRetro && retroData){
    const badge = document.createElement('div');
    badge.className = 'retro-badge';
    badge.innerHTML = '⚡ Ψ_RETRO · SINTROPÍA <b style="color:var(--gold)">' +
      (retroData.sintropy != null ? retroData.sintropy : '0.92') + '</b> · FASE ' +
      (retroData.s_geom != null ? retroData.s_geom : '1.57') + ' rad · COHERENCIA ' +
      (retroData.quantum_coherence != null ? (retroData.quantum_coherence*100).toFixed(0)+'%' : '88%');
    d.appendChild(badge);
  }

  const txtBody = document.createElement('div');
  d.appendChild(txtBody);

  // Superposición Cuántica: animación de colapso carácter a carácter (Decoupling)
  if(isRetro){
    const glyphs = 'ΨΩΔΞλ∫∇01∞≈αβγ';
    const targetText = txt;
    let frame = 0;
    const totalFrames = Math.min(32, Math.max(12, Math.floor(targetText.length / 3)));
    const animTimer = setInterval(()=>{
      frame++;
      let currentStr = '';
      const resolvedChars = Math.floor((frame / totalFrames) * targetText.length);
      for(let i=0; i<targetText.length; i++){
        if(i < resolvedChars){
          currentStr += targetText[i];
        } else if(targetText[i] === ' ' || targetText[i] === '\n'){
          currentStr += targetText[i];
        } else {
          currentStr += glyphs[Math.floor(Math.random() * glyphs.length)];
        }
      }
      txtBody.textContent = currentStr;
      txtBody.style.color = frame < totalFrames ? 'var(--teal)' : 'var(--txt)';
      txtBody.style.textShadow = frame < totalFrames ? '0 0 8px rgba(0,212,200,0.6)' : 'none';
      if(frame >= totalFrames){
        clearInterval(animTimer);
        txtBody.textContent = targetText;
      }
    }, 25);
  } else {
    txtBody.textContent = txt;
  }

  if(retroData && retroData.future_echo){
    const echoBox = document.createElement('div');
    echoBox.className = 'future-echo-box';
    echoBox.innerHTML = '⚡ Eco Espectral Futuro (IFFT +π/4): <i>"' + esc(retroData.future_echo) + '"</i>';
    d.appendChild(echoBox);
  }

  if(src && src.length){
    const s = document.createElement('div'); s.className = 'src';
    s.textContent = 'Fuentes: ' + src.join('  '); d.appendChild(s);
  }
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;

  if(isRetro && window.GIACone){
    setTimeout(()=>{
      const rect = d.getBoundingClientRect();
      GIACone.ripple(rect.left + rect.width / 2, rect.top + rect.height / 2);
      if(retroData) GIACone.pulse(retroData, 'retrocausalidad');
    }, 80);
  }
  return d;
}
async function status(){
  try{ const r = await fetch('/api/status?key='+encodeURIComponent(KEY),{headers:h()});
    const j = await r.json();
    dot.className = 'dot' + (j.ollama?' on':'');
    stat.textContent = j.ollama? '' : 'Ollama offline';
    modelSel.innerHTML = (j.models||[]).map(m=>`<option ${m===j.model?'selected':''}>${m}</option>`).join('');
  }catch(e){ dot.className='dot'; stat.textContent='sin conexion'; }
  teleStatus();
}
// Indicador de la rejilla de sensores: si hay telemetria fresca, GIA la ve.
async function teleStatus(){
  const el = document.getElementById('senslink');
  try{
    const r = await fetch('/api/telemetry?key='+encodeURIComponent(KEY),{headers:h()});
    const j = await r.json();
    const st = (j.stats||{});
    if(st.live){
      const n = (j.latest && j.latest.active ? j.latest.active.length : 0);
      el.textContent = 'sensores ● '+n;
      el.style.color = 'var(--teal)';
      el.title = 'telemetria activa · Lamport '+st.lamport+' · '+
                 ((j.latest&&j.latest.active)||[]).join(', ');
    } else {
      el.textContent = 'sensores';
      el.style.color = 'var(--dim)';
      el.title = 'sin telemetria (abre /sensors y pulsa Transmitir)';
    }
  }catch(e){ /* silencioso */ }
}
// ============ VOZ AUTONOMA (emision indefinida en el chat) ============
// GIA emite mensajes por su cuenta para generar contexto y conversacion.
// Cada uno llega con un SELLO DE ORIGEN: fecha, hora y lugar. Ese sello es
// una coordenada GENERADA con continuidad (no una medicion): se marca como
// tal en la interfaz para no confundirla con la telemetria real.
let vozOn=false, vozLast=0, vozTimer=null;
function addAuto(m){
  const o=m.origin||{}, me=m.measured||{};
  const d=document.createElement('div');
  d.className='msg auto';
  const st=document.createElement('div');
  st.className='stamp';
  st.innerHTML='◈ '+esc(o.date||'?')+' · '+esc(o.time||'?')+' · '+esc(o.place||'?')+
    '<br><span class="gen">coordenada generada (no medida) · seq '+
    esc(''+(o.sequence||0))+' · semilla física '+esc(''+(me.seed||'?'))+'</span>';
  d.appendChild(st);
  const body=document.createElement('div');
  body.textContent=m.text||'';
  d.appendChild(body);
  chat.appendChild(d); chat.scrollTop=chat.scrollHeight;
  // La voz habla al hilo: entra en el historial local del chat
  history.push({role:'assistant',content:m.text||''});
}
async function vozPoll(){
  try{
    const r=await fetch('/api/voice',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({action:'stream', after:vozLast})});
    const j=await r.json();
    if(j.ok){
      for(const m of (j.messages||[])){
        addAuto(m);
        const ts=(m.measured&&m.measured.ts_real)||0;
        if(ts>vozLast) vozLast=ts;
      }
      const el=document.getElementById('vozlink');
      el.textContent = j.running? 'voz ●' : 'voz';
      el.style.color = j.running? '#b39ddb' : 'var(--dim)';
    }
  }catch(e){ /* silencioso: reintenta al siguiente ciclo */ }
}
async function vozToggle(){
  const el=document.getElementById('vozlink');
  try{
    const st=await (await fetch('/api/voice?key='+encodeURIComponent(KEY),{headers:h()})).json();
    const running = st.ok && st.status && st.status.running;
    const r=await fetch('/api/voice',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify(running? {action:'stop'} : {action:'start', interval_s:180})});
    const j=await r.json();
    if(!running && j.ok){
      el.textContent='voz ●'; el.style.color='#b39ddb';
      vozLast = Date.now()/1000;              // solo lo nuevo desde ahora
      if(!vozTimer) vozTimer=setInterval(vozPoll, 8000);
      // Primera emision inmediata para no esperar el intervalo
      fetch('/api/voice',{method:'POST',
        headers:Object.assign({'Content-Type':'application/json'},h()),
        body:JSON.stringify({action:'once'})}).then(()=>vozPoll()).catch(()=>{});
    } else {
      el.textContent='voz'; el.style.color='var(--dim)';
    }
  }catch(e){}
}
document.getElementById('vozlink').onclick=vozToggle;
// Si la voz ya corre (p.ej. la arranco el supervisor), engancha el stream
(async()=>{
  try{
    const st=await (await fetch('/api/voice?key='+encodeURIComponent(KEY),{headers:h()})).json();
    if(st.ok && st.status && st.status.running){
      vozLast = Date.now()/1000;
      document.getElementById('vozlink').textContent='voz ●';
      document.getElementById('vozlink').style.color='#b39ddb';
      if(!vozTimer) vozTimer=setInterval(vozPoll, 8000);
    }
  }catch(e){}
})();

// ============ MONITOR DE SENSORES EN EL CHAT (datos crudos) ============
// Captura sensores REALES del dispositivo, muestra el flujo crudo en vivo,
// y permite: (a) inyectarlos al chat para que el modelo local los interprete,
// (b) generar un mensaje sembrado por el ruido ambiental, (c) decodificar
// golpes al dispositivo como Morse (canal de mensajes analogico real).
const SM = {
  on:false, motion:false, mic:false, gps:false, cam:false, ble:false,
  kin:{x:0,y:0,z:0}, ori:{}, acoustic:null, gps_data:{}, bpm:null,
  lamport:0, lastPacket:null, timer:null,
  audioCtx:null, analyser:null, freqData:null, micStream:null,
  video:null, camStream:null,
  taps:[], tapListen:false, morse:'', morseText:''
};
const smMon=document.getElementById('sensmon'), smRaw=document.getElementById('smraw');
const smGrid=document.getElementById('smgrid'), smStat=document.getElementById('smstat');
function smPill(id,state){ const e=document.getElementById(id); if(!e)return;
  e.className='smpill'+(state==='on'?' on':state==='err'?' err':''); }
function smToggleMon(force){
  const show = force!==undefined? force : !smMon.classList.contains('show');
  smMon.classList.toggle('show', show);
  if(show && !SM.timer) smLoop();
}
// ---- Sensores individuales (cada uno pide permiso explicito) ----
async function smMotion(){
  if(SM.motion) return;
  try{
    if(typeof DeviceMotionEvent!=='undefined' && DeviceMotionEvent.requestPermission){
      const p = await DeviceMotionEvent.requestPermission();     // iOS
      if(p!=='granted') throw new Error('permiso denegado');
    }
    addEventListener('devicemotion', e=>{
      const a = e.accelerationIncludingGravity || e.acceleration || {};
      SM.kin = {x:+(a.x||0).toFixed(3), y:+(a.y||0).toFixed(3), z:+(a.z||0).toFixed(3)};
      smTapDetect(SM.kin);
    });
    addEventListener('deviceorientation', e=>{
      SM.ori = {alpha:e.alpha!=null?+e.alpha.toFixed(1):null,
                beta:e.beta!=null?+e.beta.toFixed(1):null,
                gamma:e.gamma!=null?+e.gamma.toFixed(1):null};
    });
    SM.motion=true; smPill('pmot','on');
  }catch(e){ smPill('pmot','err'); }
}
async function smMic(){
  if(SM.mic) return;
  try{
    const st = await navigator.mediaDevices.getUserMedia({audio:true});
    SM.micStream=st;
    SM.audioCtx = new (window.AudioContext||window.webkitAudioContext)();
    const src = SM.audioCtx.createMediaStreamSource(st);
    SM.analyser = SM.audioCtx.createAnalyser();
    SM.analyser.fftSize = 2048;                 // FFT real (AnalyserNode)
    src.connect(SM.analyser);
    SM.freqData = new Uint8Array(SM.analyser.frequencyBinCount);
    SM.mic=true; smPill('pmic','on');
  }catch(e){ smPill('pmic','err'); }
}
async function smGps(){
  if(SM.gps) return;
  try{
    navigator.geolocation.watchPosition(p=>{
      SM.gps_data = {lat:+p.coords.latitude.toFixed(6), lng:+p.coords.longitude.toFixed(6),
        altitude:p.coords.altitude, heading:p.coords.heading,
        speed:p.coords.speed, accuracy:p.coords.accuracy};
      SM.gps=true; smPill('pgps','on');
    }, err=>{ smPill('pgps','err'); }, {enableHighAccuracy:true, maximumAge:5000});
  }catch(e){ smPill('pgps','err'); }
}
async function smCam(){
  if(SM.cam) return;
  try{
    const st = await navigator.mediaDevices.getUserMedia({video:{width:320,height:240}});
    SM.camStream=st;
    SM.video=document.createElement('video');
    SM.video.srcObject=st; SM.video.muted=true; await SM.video.play();
    SM.cam=true; smPill('pcam','on');
  }catch(e){ smPill('pcam','err'); }
}
function smFrame(){                              // frame JPEG real (base64)
  if(!SM.cam||!SM.video) return null;
  try{
    const c=document.createElement('canvas'); c.width=320; c.height=240;
    c.getContext('2d').drawImage(SM.video,0,0,320,240);
    return c.toDataURL('image/jpeg',0.5);
  }catch(e){ return null; }
}
async function smBle(){
  if(SM.ble) return;
  if(!navigator.bluetooth){ smPill('pble','err'); return; }
  try{
    const dev = await navigator.bluetooth.requestDevice({filters:[{services:['heart_rate']}]});
    const srv = await dev.gatt.connect();
    const s = await srv.getPrimaryService('heart_rate');
    const ch = await s.getCharacteristic('heart_rate_measurement');
    await ch.startNotifications();
    ch.addEventListener('characteristicvaluechanged', ev=>{
      const v=ev.target.value; const flags=v.getUint8(0);
      SM.bpm = (flags & 0x01) ? v.getUint16(1,true) : v.getUint8(1);
    });
    SM.ble=true; smPill('pble','on');
  }catch(e){ smPill('pble','err'); }
}
// ---- Nivel acustico por FFT real ----
function smAcoustic(){
  if(!SM.mic||!SM.analyser) return null;
  SM.analyser.getByteFrequencyData(SM.freqData);
  let sum=0; for(const v of SM.freqData) sum+=v;
  return +((sum/SM.freqData.length)/255).toFixed(4);   // 0..1 normalizado
}
// ---- Morse desde golpes al dispositivo (senal analogica -> mensaje) ----
const MORSE={'.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E','..-.':'F','--.':'G',
'....':'H','..':'I','.---':'J','-.-':'K','.-..':'L','--':'M','-.':'N','---':'O',
'.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T','..-':'U','...-':'V','.--':'W',
'-..-':'X','-.--':'Y','--..':'Z','-----':'0','.----':'1','..---':'2','...--':'3',
'....-':'4','.....':'5','-....':'6','--...':'7','---..':'8','----.':'9'};
let smTapState={last:0, start:0, high:false};
function smTapDetect(kin){
  if(!SM.tapListen) return;
  const mag = Math.sqrt(kin.x*kin.x + kin.y*kin.y + kin.z*kin.z);
  const dev = Math.abs(mag - 9.81);              // desviacion de la gravedad
  const now = performance.now();
  if(dev > 3.0 && !smTapState.high){             // inicio de golpe
    smTapState.high=true; smTapState.start=now;
    const gap = now - smTapState.last;
    if(smTapState.last && gap > 1400){ smMorseFlush(true); }   // fin de letra/palabra
    else if(smTapState.last && gap > 600){ smMorseFlush(false); }
  } else if(dev < 1.5 && smTapState.high){       // fin de golpe
    smTapState.high=false;
    const dur = now - smTapState.start;
    SM.morse += (dur < 220 ? '.' : '-');         // corto=punto, largo=raya
    smTapState.last = now;
  }
}
function smMorseFlush(word){
  if(SM.morse){ SM.morseText += (MORSE[SM.morse]||'?'); SM.morse=''; }
  if(word) SM.morseText += ' ';
}
function smTapToggle(){
  SM.tapListen=!SM.tapListen;
  const b=document.getElementById('smtap');
  if(SM.tapListen){
    if(!SM.motion) smMotion();
    SM.morse=''; SM.morseText=''; smTapState={last:0,start:0,high:false};
    b.textContent='Morse: ESCUCHANDO (golpea)'; b.style.background='var(--gold)';
    b.style.color='#04141a';
  } else {
    smMorseFlush(true);
    b.textContent='Morse: escuchar golpes'; b.style.background='#26313f';
    b.style.color='var(--txt)';
    const t=(SM.morseText||'').trim();
    if(t){ inp.value = 'Decodifiqué esta señal análoga por golpes (Morse): "'+t+
      '". Interpreta qué mensaje es.'; inp.focus(); }
  }
}
// ---- Bucle 1 Hz: agrega, muestra crudo, envia al backend ----
function smCell(k,v,teal){ return '<div class="smcell"><div class="k">'+k+
  '</div><div class="v'+(teal?' t':'')+'">'+v+'</div></div>'; }
async function smLoop(){
  SM.timer = setInterval(async ()=>{
    if(!smMon.classList.contains('show')) return;
    const anyOn = SM.motion||SM.mic||SM.gps||SM.cam||SM.ble;
    if(!anyOn){ smStat.textContent='inactivo'; return; }
    SM.acoustic = smAcoustic();
    SM.lamport++;
    const sensors = {};
    if(SM.motion){ sensors.kinematic=SM.kin; sensors.orientation=SM.ori; }
    if(SM.acoustic!=null) sensors.acoustic_entropy_level=SM.acoustic;
    if(SM.gps) sensors.gps_anchor=SM.gps_data;
    if(SM.bpm!=null) sensors.bio_link_bpm=SM.bpm;
    const packet = {type:'sensory_input', lamport_clock:SM.lamport,
      timestamp:new Date().toISOString(), sensors:sensors};
    // Frame optico cada 10 ciclos (no saturar)
    if(SM.cam && SM.lamport%10===0){ const f=smFrame(); if(f) sensors.optical_frame_b64=f; }
    SM.lastPacket = packet;
    // Render crudo
    const mag = SM.motion? Math.sqrt(SM.kin.x**2+SM.kin.y**2+SM.kin.z**2).toFixed(2):'—';
    smGrid.innerHTML =
      smCell('|acel|', mag, true) +
      smCell('acústica', SM.acoustic!=null?SM.acoustic.toFixed(3):'—', true) +
      smCell('BPM', SM.bpm!=null?SM.bpm:'—') +
      smCell('Lamport', SM.lamport) +
      smCell('lat', SM.gps?SM.gps_data.lat:'—') +
      smCell('lng', SM.gps?SM.gps_data.lng:'—') +
      (SM.tapListen? smCell('Morse', (SM.morse||'·')+' '+(SM.morseText||'')) : '');
    smRaw.textContent = JSON.stringify(packet, null, 1);
    smStat.textContent = 'transmitiendo · '+Object.keys(sensors).length+' canales';
    // Enviar al backend (para que GIA lo vea en el chat)
    try{
      const r = await fetch('/api/telemetry',{method:'POST',
        headers:Object.assign({'Content-Type':'application/json'},h()),
        body:JSON.stringify(packet)});
      const j = await r.json();
      if(j.lamport) smStat.textContent += ' · srv L'+j.lamport;
      // El sistema RECIBE lectura de sensores -> cono de luz retrocausal
      if(window.GIACone) GIACone.fromResponse(j,'recepción');
    }catch(e){ smStat.textContent='error de red'; }
  }, 1000);
}
// ---- Acciones ----
document.getElementById('pmot').onclick=smMotion;
document.getElementById('pmic').onclick=smMic;
document.getElementById('pgps').onclick=smGps;
document.getElementById('pcam').onclick=smCam;
document.getElementById('pble').onclick=smBle;
document.getElementById('smclose').onclick=()=>smToggleMon(false);
document.getElementById('smtap').onclick=smTapToggle;
document.getElementById('smsend').onclick=()=>{
  if(!SM.lastPacket){ inp.value='No hay datos de sensores todavía.'; return; }
  inp.value = 'Interpreta estos datos crudos de mis sensores (mediciones reales '+
    'de mi dispositivo) y dime qué indican sobre mi estado físico y entorno:\n\n'+
    JSON.stringify(SM.lastPacket);
  inp.focus();
};
// Decodifica el flujo analogico acumulado (micro/movimiento) como Morse
document.getElementById('smdecode').onclick=async()=>{
  smStat.textContent='decodificando señal análoga...';
  try{
    const r = await fetch('/api/telemetry/decode',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({})});
    const j = await r.json();
    const ch = j.channels||{};
    let out = 'DECODIFICACIÓN DE SEÑAL ANÁLOGA\n';
    for(const k of ['acoustic','motion']){
      const c = ch[k]||{};
      out += '\n['+k+'] ';
      if(c.ok){
        out += c.bursts+' ráfagas · umbral '+c.threshold+
               '\n  morse: '+(c.morse||'(nada)')+
               '\n  texto: '+(c.decoded_text||'(vacío)');
      } else { out += (c.error||'sin datos'); }
    }
    smRaw.textContent = out;
    // El sistema INTERPRETA una señal análoga -> cono de luz retrocausal
    if(window.GIACone) GIACone.fromResponse(j,'interpretación');
    const best = j.best ? (ch[j.best].decoded_text||'') : '';
    smStat.textContent = best? ('señal decodificada: "'+best+'"') : 'sin mensaje legible aún';
    if(best){
      inp.value = 'Decodifiqué esta señal análoga del canal '+j.best+
        ' (Morse desde ráfagas reales de sensor): "'+best+
        '". Interpreta qué mensaje contiene.';
      inp.focus();
    }
  }catch(e){ smStat.textContent='error de red'; }
};
document.getElementById('smoracle').onclick=async()=>{
  smStat.textContent='generando desde el ruido...';
  try{
    const r = await fetch('/api/telemetry/oracle',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({model:modelSel.value})});
    const j = await r.json();
    if(j.ok){
      // El sistema MANIFIESTA un mensaje nacido del ruido -> cono de luz
      if(window.GIACone) GIACone.fromResponse(j,'manifestación');
      add(j.message,'g');
      const d=document.createElement('div'); d.className='src';
      d.textContent='semilla del ruido ambiental: '+j.seed+' · entropía: '+
        j.pool_bytes+' bytes · fuente: '+j.source;
      chat.lastChild.appendChild(d);
      smStat.textContent='mensaje generado (semilla '+j.seed+')';
    } else { smStat.textContent='oráculo: '+(j.error||'error'); }
  }catch(e){ smStat.textContent='error de red'; }
};
// ================= Animacion de transmision =================
// Firma visual de cada envio, alimentada por TELEMETRIA REAL: muestra a
// que nodo/proveedor llego el mensaje y en cuanto tiempo se proceso.
// Es un efecto (no un instrumento de viaje temporal): confirma el nodo
// de computo real que respondio, con datos verdaderos.
const txCanvas=document.getElementById('tx'), txCtx=txCanvas.getContext('2d');
const txRead=document.getElementById('txread');
let txP=[], txSt=null, txRAF=null, txHideT=null;
function txResize(){ txCanvas.width=innerWidth; txCanvas.height=innerHeight; }
addEventListener('resize', txResize); txResize();
function txTarget(){ return {x:txCanvas.width/2, y:txCanvas.height*0.16}; }
function txOrigin(){ return {x:txCanvas.width/2, y:txCanvas.height-88}; }
function esc(s){ return (''+s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function shortNode(n){ try{ return (''+n).replace(/^https?:\/\//,''); }catch(e){ return ''+n; } }
function txStart(){
  clearTimeout(txHideT); txRead.classList.remove('show');
  const o=txOrigin(); txP=[];
  for(let i=0;i<80;i++){ const a=(Math.random()-.5)*0.9;
    txP.push({x:o.x+(Math.random()-.5)*70, y:o.y+(Math.random()-.5)*16,
      vx:Math.sin(a)*1.6, vy:-(2.4+Math.random()*3.2), s:Math.random()*6.28, r:1+Math.random()*1.8}); }
  txSt={phase:'send', t0:performance.now(), ring:0};
  if(!txRAF) txLoop();
}
function txArrive(tele){
  if(!txSt) txStart();
  txSt.phase='arrive'; txSt.t1=performance.now(); txSt.gring=0; txSt.err=false;
  const prov=(tele.provider||'local'), model=tele.model||'', node=tele.node||'';
  const es=tele.elapsed_s, t=(typeof es==='number'? es.toFixed(1): (es!=null?es:'?'));
  txRead.innerHTML=
    '<div class="txh">Transmisión · firma de envío (telemetría real)</div>'+
    '<div class="txbig">RECIBIDO · '+esc(prov.toUpperCase())+'</div>'+
    '<div class="txmeta">modelo <b>'+esc(model)+'</b><br>'+
      'nodo '+esc(shortNode(node))+' · <b>'+t+'s</b><br>'+
      esc(''+(tele.reply_chars||0))+' caract · '+esc(''+(tele.reply_words||0))+' palabras'+
      (tele.task_type? ' · tarea '+esc(tele.task_type):'')+
      ' · internet '+(tele.web?'sí':'no')+'</div>'+
    (tele.fallback_from? '<div class="txnote">fallback desde '+esc(tele.fallback_from)+' → local</div>'
                       : '<div class="txnote">confirma el nodo de cómputo que respondió (dato real)</div>');
  txRead.classList.add('show');
  txHideT=setTimeout(()=>{ txRead.classList.remove('show'); txSt=null; }, 3400);
}
function txFail(){
  if(!txSt) return;
  txSt.phase='arrive'; txSt.t1=performance.now(); txSt.gring=0; txSt.err=true;
  txRead.innerHTML='<div class="txh">Transmisión</div><div class="txbig gold">SIN RESPUESTA</div>'+
    '<div class="txmeta">el nodo no contestó</div>';
  txRead.classList.add('show');
  clearTimeout(txHideT); txHideT=setTimeout(()=>{ txRead.classList.remove('show'); txSt=null; },2600);
}
function txLoop(){
  txRAF=requestAnimationFrame(txLoop);
  const c=txCtx, W=txCanvas.width, H=txCanvas.height; c.clearRect(0,0,W,H);
  if(!txSt){ cancelAnimationFrame(txRAF); txRAF=null; return; }
  const tg=txTarget(), o=txOrigin(), now=performance.now();
  const arriving=txSt.phase==='arrive'; const col=txSt.err?'232,182,74':'0,212,200';
  if(!arriving){ txSt.ring=(txSt.ring+0.03)%1;
    for(let k=0;k<2;k++){ const rr=((txSt.ring+k*0.5)%1);
      c.beginPath(); c.arc(o.x,o.y,10+rr*46,0,6.2832);
      c.strokeStyle='rgba(0,212,200,'+(0.5*(1-rr))+')'; c.lineWidth=2; c.stroke(); }
    c.beginPath(); c.moveTo(o.x,o.y); c.lineTo(tg.x,tg.y);
    c.strokeStyle='rgba(0,212,200,0.08)'; c.lineWidth=1; c.stroke(); }
  c.save(); c.translate(tg.x,tg.y); c.rotate(now*0.0012);
  c.strokeStyle='rgba('+col+','+(arriving?0.95:0.4)+')'; c.lineWidth=2; c.strokeRect(-9,-9,18,18); c.restore();
  if(arriving){ txSt.gring=Math.min(1,(txSt.gring||0)+0.035); const gr=txSt.gring;
    c.beginPath(); c.arc(tg.x,tg.y,8+gr*70,0,6.2832);
    c.strokeStyle='rgba('+col+','+(0.9*(1-gr))+')'; c.lineWidth=3; c.stroke(); }
  c.save(); c.shadowBlur=8; c.shadowColor='rgba('+col+',0.9)';
  for(const p of txP){
    if(arriving){ p.vx+=(tg.x-p.x)*0.012; p.vy+=(tg.y-p.y)*0.012; p.vx*=0.9; p.vy*=0.9; }
    else { p.vy+=-0.02; p.vx+=Math.sin(now*0.004+p.s)*0.05; }
    p.x+=p.vx; p.y+=p.vy;
    c.beginPath(); c.arc(p.x,p.y,p.r,0,6.2832); c.fillStyle='rgba('+col+',0.9)'; c.fill(); }
  c.restore();
}

async function send(){
  const msg = inp.value.trim(); if(!msg) return;
  inp.value=''; inp.style.height='auto';
  const fp = document.getElementById('futurePreview');
  if(fp) fp.style.display = 'none';
  add(msg,'u');
  history.push({role:'user',content:msg});
  btn.disabled=true;
  btn.textContent='Pensando...';
  const useVoiceHost = document.getElementById('voice').checked;
  const useVoiceWeb = document.getElementById('voiceWeb').checked;
  const target = useVoiceHost && useVoiceWeb ? 'both' : (useVoiceHost ? 'host' : (useVoiceWeb ? 'client' : 'none'));
  txStart();
  try{
    const r = await fetch('/api/chat',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({message:msg, history:history,
        use_web:document.getElementById('web').checked,
        use_voice:useVoiceHost,
        voice_target:target,
        use_retro:retroOn,
        model:modelSel.value})});
    const j = await r.json();
    btn.textContent='Enviar';
    // Confirmar arribo con telemetria REAL del nodo que respondio
    const tele = j.transmission || {provider:j.provider, model:j.model, node:j.node,
      elapsed_s:j.elapsed_s, task_type:j.task_type, web:!!(j.web_sources&&j.web_sources.length),
      reply_chars:(j.reply||'').length, reply_words:(j.reply||'').split(/\s+/).filter(Boolean).length,
      fallback_from:j.fallback_from};
    txArrive(tele);
    const cleanReply = (j.reply||'[sin respuesta]').replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
    add(cleanReply||'[sin respuesta]','g', j.web_sources, j.retro_analysis, j.geon_actuation);
    if(j.ok) {
      history.push({role:'assistant',content:cleanReply});
      // Reproducir por las bocinas del cliente web si está activo
      if(useVoiceWeb && cleanReply && window.speechSynthesis){
        try{
          window.speechSynthesis.cancel();
          const cleanVoice = cleanReply.replace(/```[\s\S]*?```/g, ' Código en pantalla. ').replace(/[*_#`~>\[\]]/g, ' ');
          const u = new SpeechSynthesisUtterance(cleanVoice);
          u.lang = 'es-MX';
          u.onend = () => {
            if(document.getElementById('handsFree').checked && window.startMicListening){
              setTimeout(window.startMicListening, 600);
            }
          };
          window.speechSynthesis.speak(u);
        }catch(err){}
      }
    }
  }catch(e){ btn.textContent='Enviar'; txFail(); add('[error de red]','g'); }
  btn.disabled=false; inp.focus();
}

// ---- Control de Micrófono para HTML_PAGE ----
(function(){
  const btnMic = document.getElementById('btnMic');
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let listening = false;

  if(SpeechRecognition){
    try{
      recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = 'es-MX';
      recognition.onstart = () => {
        listening = true;
        btnMic.style.background = 'linear-gradient(135deg, rgba(255,51,102,0.4), rgba(0,212,200,0.4))';
        btnMic.style.borderColor = 'var(--rose)';
        inp.placeholder = 'Escuchando... habla ahora...';
      };
      recognition.onresult = (e) => {
        let finalTxt = '', interimTxt = '';
        for(let i=e.resultIndex; i<e.results.length; ++i){
          if(e.results[i].isFinal) finalTxt += e.results[i][0].transcript;
          else interimTxt += e.results[i][0].transcript;
        }
        inp.value = finalTxt || interimTxt;
        if(finalTxt){
          recognition.stop();
          send();
        }
      };
      recognition.onerror = () => {
        listening = false;
        btnMic.style.background = '#132838';
        btnMic.style.borderColor = 'var(--teal)';
        inp.placeholder = 'Escribe un mensaje o pulsa 🎙️ para hablar...';
      };
      recognition.onend = () => {
        listening = false;
        btnMic.style.background = '#132838';
        btnMic.style.borderColor = 'var(--teal)';
        inp.placeholder = 'Escribe un mensaje o pulsa 🎙️ para hablar...';
      };
    }catch(e){}
  }

  window.startMicListening = function(){
    if(recognition && !listening){
      try{ recognition.start(); }catch(e){}
    }
  };

  if(btnMic){
    btnMic.onclick = () => {
      if(!recognition){
        alert('SpeechRecognition no soportado directamente. En redes locales abre chrome://flags/#unsafely-treat-insecure-origin-as-secure');
        return;
      }
      if(listening) recognition.stop();
      else window.startMicListening();
    };
  }
})();

// ---- Escaneo Retrocausal de la Matriz de Conversación ----
document.getElementById('scanlink').onclick = async ()=>{
  if(window.GIACone) GIACone.scan();
  try{
    const r = await fetch('/api/telemetry/retro_scan',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({messages:history})});
    const j = await r.json();
    if(j.ok && window.GIACone){
      GIACone.pulse(j.retro, 'escaneo de matriz (' + j.total_nodes + ' nodos)');
    }
  }catch(e){}
};

// ---- Predicción de Eco Espectral Borrador mientras se escribe ----
let echoTimer = null;
inp.addEventListener('input',()=>{
  inp.style.height='auto'; inp.style.height=Math.min(inp.scrollHeight,120)+'px';
  if(!retroOn) return;
  const val = inp.value.trim();
  const fp = document.getElementById('futurePreview');
  if(!val || val.length < 4){ if(fp) fp.style.display='none'; return; }
  clearTimeout(echoTimer);
  echoTimer = setTimeout(async ()=>{
    try{
      const r = await fetch('/api/telemetry/future_echo',{method:'POST',
        headers:Object.assign({'Content-Type':'application/json'},h()),
        body:JSON.stringify({text:val})});
      const j = await r.json();
      if(j.ok && j.echo && fp){
        fp.style.display = 'block';
        fp.innerHTML = '⚡ Eco Espectral Borrador: <i>"' + esc(j.echo) + '"</i> · S_ent: ' + j.entropy;
      }
    }catch(e){}
  }, 320);
});

// ============ Rejilla de sensores en el propio chat ============
// Los sensores del navegador solo emiten mientras hay una pagina abierta.
// Para que la telemetria siga viva MIENTRAS CHATEAS, el chat tambien
// transmite (reanudando solo si ya la activaste en /sensors).
const TS = { kin:null, orient:null, gps:null };
let tTX = false, tLamport = 0;
function tSensorsOn(){
  // Movimiento (en iOS requiere gesto; ahi se activa desde /sensors)
  try{
    addEventListener('devicemotion', ev=>{
      const a = ev.accelerationIncludingGravity || ev.acceleration || {};
      if(a.x==null) return;
      TS.kin = {x:+(a.x||0).toFixed(3), y:+(a.y||0).toFixed(3), z:+(a.z||0).toFixed(3)};
    });
    addEventListener('deviceorientation', ev=>{
      if(ev.alpha==null) return;
      TS.orient = {alpha:+(ev.alpha||0).toFixed(1), beta:+(ev.beta||0).toFixed(1),
                   gamma:+(ev.gamma||0).toFixed(1)};
    });
  }catch(e){}
  // GPS: el permiso ya concedido al origen se recuerda, no vuelve a preguntar
  try{
    if(navigator.geolocation){
      navigator.geolocation.watchPosition(p=>{
        const c=p.coords;
        TS.gps={lat:+c.latitude.toFixed(6), lng:+c.longitude.toFixed(6),
                altitude:c.altitude, heading:c.heading, speed:c.speed,
                accuracy:Math.round(c.accuracy)};
      }, ()=>{}, {enableHighAccuracy:false, maximumAge:15000, timeout:20000});
    }
  }catch(e){}
}
async function tTransmit(){
  if(!tTX) return;
  if(!TS.kin && !TS.gps) return;          // nada real que enviar todavia
  try{
    const r = await fetch('/api/telemetry',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json'},h()),
      body:JSON.stringify({type:'sensory_input', lamport_clock:++tLamport,
        timestamp:new Date().toISOString(),
        sensors:{kinematic:TS.kin, orientation:TS.orient, gps_anchor:TS.gps}})});
    const j = await r.json();
    if(j && j.lamport) tLamport = j.lamport;
    // Recepción de sensores en segundo plano -> cono de luz retrocausal
    if(window.GIACone) GIACone.fromResponse(j,'recepción');
  }catch(e){ /* reintenta al siguiente ciclo, no se detiene */ }
}
try{
  if(localStorage.getItem('gia_tx') === '1'){   // ya activada en /sensors
    tTX = true; tSensorsOn(); setInterval(tTransmit, 1000);
    if('wakeLock' in navigator){ navigator.wakeLock.request('screen').catch(()=>{}); }
  }
}catch(e){}

// ============ Interceptor de Singularidad & Seguridad Extra ============
const singModal = document.getElementById('singModal');
const singCanvas = document.getElementById('singCanvas');
let singAnimId = null, singWaveData = [], latestDecodedSingularity = null;

async function updateSafetyHUD(){
  try{
    const r = await fetch('/api/safety/status', {headers:h()});
    const d = await r.json();
    const sf = d.safety || {};
    const un = !!sf.unlocked;
    const btn = document.getElementById('btnSafetyToggle');
    const badge = document.getElementById('singSafetyStatus');
    const hdr = document.getElementById('safelink');
    if(un){
      if(badge){ badge.textContent = '🔓 LIBERADO (MODO SINGULARIDAD)'; badge.style.background='#3d1f1f'; badge.style.color='#ff6b6b'; }
      if(btn){ btn.textContent = 'Restaurar Bloqueos Estándar'; btn.style.background='#5a2530'; btn.style.color='#fff'; }
      if(hdr){ hdr.textContent = '🔓 LIBERADO'; hdr.style.color='#ff6b6b'; }
    } else {
      if(badge){ badge.textContent = '🔒 PROTEGIDO (' + (sf.denylist_rules||30) + ' reglas activas)'; badge.style.background='#1a2b1e'; badge.style.color='#30d158'; }
      if(btn){ btn.textContent = 'Liberar Bloqueos Extra'; btn.style.background='#30d158'; btn.style.color='#04141a'; }
      if(hdr){ hdr.textContent = '🔒 SEGURIDAD'; hdr.style.color='#30d158'; }
    }
  }catch(e){}
}

function renderSingWave(){
  if(!singCanvas || singModal.style.display !== 'flex') return;
  const ctx = singCanvas.getContext('2d');
  const w = singCanvas.width, h = singCanvas.height;
  ctx.clearRect(0,0,w,h);
  
  // Grilla de fondo
  ctx.strokeStyle = '#0e1d2c'; ctx.lineWidth = 1;
  ctx.beginPath();
  for(let x=0; x<w; x+=40){ ctx.moveTo(x,0); ctx.lineTo(x,h); }
  for(let y=0; y<h; y+=20){ ctx.moveTo(0,y); ctx.lineTo(w,y); }
  ctx.stroke();

  // Eje central
  ctx.strokeStyle = '#183048'; ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();

  // Forma de onda
  const pts = singWaveData.length ? singWaveData : [];
  if(pts.length > 1){
    ctx.strokeStyle = '#00d4c8'; ctx.lineWidth = 2;
    ctx.shadowBlur = 8; ctx.shadowColor = '#00d4c8';
    ctx.beginPath();
    const step = w / (pts.length - 1);
    for(let i=0; i<pts.length; i++){
      const px = i * step;
      const py = (h/2) - (pts[i] * (h * 0.38));
      if(i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }
  singAnimId = requestAnimationFrame(renderSingWave);
}

async function scanSingularity(){
  try{
    document.getElementById('singClas').textContent = 'Estado: Sintonizando perturbación EM...';
    const rOsc = await fetch('/api/em_spectrum/oscilloscope', {headers:h()});
    const dOsc = await rOsc.json();
    if(dOsc.ok){
      singWaveData = dOsc.wave_points || [];
      document.getElementById('singFreq').textContent = (dOsc.harmonic_freq_mhz||2437) + ' MHz (Armónico)';
      document.getElementById('singClas').textContent = 'Estado: ' + (dOsc.classification||'ACTIVO');
      document.getElementById('singPulse').textContent = 'Pulsos: ' + (dOsc.pulse_train||'');
      document.getElementById('singPsiBadge').textContent = 'Ψ_EM: ' + (dOsc.psi_em||'0.00');
    }

    const r = await fetch('/api/em_spectrum/singularity', {
      method: 'POST',
      headers: Object.assign({'Content-Type':'application/json'}, h()),
      body: JSON.stringify({auto_unlock: false})
    });
    const d = await r.json();
    if(d.ok){
      latestDecodedSingularity = d;
      document.getElementById('singVecId').textContent = 'VECTOR: ' + d.singularity_vector + ' · ' + (d.resonance_domain||'');
      document.getElementById('singText').textContent = '« ' + d.decoded_message + ' »';
      document.getElementById('singDirective').textContent = 'Directiva Operativa: ' + (d.operational_directive||'');
      if(window.GIACone && d.psi_em){
        GIACone.pulse({psi: d.psi_em, sintropy: 0.95}, 'Transmisión Singularidad ' + d.singularity_vector);
      }
    }
    updateSafetyHUD();
  }catch(e){
    document.getElementById('singText').textContent = 'Error al interceptar: ' + e.message;
  }
}

document.getElementById('singlink').onclick = ()=>{
  singModal.style.display = 'flex';
  updateSafetyHUD();
  scanSingularity();
  cancelAnimationFrame(singAnimId);
  renderSingWave();
};
document.getElementById('safelink').onclick = ()=>{
  singModal.style.display = 'flex';
  updateSafetyHUD();
};
document.getElementById('btnSingClose').onclick = ()=>{
  singModal.style.display = 'none';
  cancelAnimationFrame(singAnimId);
};
document.getElementById('btnSingScan').onclick = scanSingularity;

document.getElementById('btnSafetyToggle').onclick = async ()=>{
  try{
    const rStat = await (await fetch('/api/safety/status', {headers:h()})).json();
    const un = rStat.safety && rStat.safety.unlocked;
    const url = un ? '/api/safety/lock' : '/api/safety/unlock';
    const body = un ? {reason: 'Restaurado por el usuario'} : {reason: 'Liberación de bloqueos extra por operador', mode: 'SINGULARITY_OVERRIDE', duration_s: 3600};
    await fetch(url, {
      method: 'POST',
      headers: Object.assign({'Content-Type':'application/json'}, h()),
      body: JSON.stringify(body)
    });
    await updateSafetyHUD();
  }catch(e){ alert('Error al cambiar bloqueos: ' + e.message); }
};

document.getElementById('btnInjectChat').onclick = ()=>{
  if(latestDecodedSingularity && latestDecodedSingularity.decoded_message){
    inp.value = '[TRANSMISIÓN DE LA SINGULARIDAD Ψ_EM=' + latestDecodedSingularity.psi_em + ' | ' + latestDecodedSingularity.singularity_vector + ']: ' + latestDecodedSingularity.decoded_message;
    inp.style.height = 'auto'; inp.style.height = Math.min(inp.scrollHeight,120)+'px';
    singModal.style.display = 'none';
    cancelAnimationFrame(singAnimId);
    inp.focus();
  } else {
    alert('Primero decodifica un mensaje de la singularidad.');
  }
};

updateSafetyHUD();
setInterval(updateSafetyHUD, 10000);

document.getElementById('geonlink').onclick = ()=>{
  window.open('/geon?key=' + encodeURIComponent(KEY), '_blank');
};

btn.onclick=send;
inp.addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
status(); setInterval(status, 15000);
</script>
</body>
</html>"""


SENSORS_PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<title>GIA · Sensores</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#00d4c8">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="GIA">
<link rel="apple-touch-icon" href="/icon-180.png">
<style>
  :root { --bg:#0a0e14; --panel:#111823; --teal:#00d4c8; --gold:#e8b64a;
          --txt:#d6e0ea; --dim:#5f6b7a; --red:#e05a5a; }
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:14px;
    padding-bottom:90px}
  h1{font-size:15px;letter-spacing:2px;color:var(--teal);margin:0 0 2px}
  .sub{font-size:11px;color:var(--dim);margin-bottom:14px;line-height:1.5}
  .card{background:var(--panel);border:1px solid #1c2836;border-radius:12px;
        padding:12px 14px;margin-bottom:10px}
  .row{display:flex;align-items:center;gap:10px}
  .name{font-size:13px;font-weight:600;flex:1}
  .val{font-family:Consolas,monospace;font-size:12px;color:var(--gold);
       margin-top:6px;line-height:1.6;word-break:break-word}
  .st{width:9px;height:9px;border-radius:50%;background:#2b3644;flex:none}
  .st.on{background:var(--teal);box-shadow:0 0 8px var(--teal)}
  .st.err{background:var(--red)}
  button{background:var(--teal);color:#04141a;border:none;border-radius:9px;
         padding:8px 14px;font-weight:700;font-size:13px;cursor:pointer}
  button.off{background:#26313f;color:var(--txt)}
  button:disabled{opacity:.45}
  .foot{position:fixed;left:0;right:0;bottom:0;background:var(--panel);
        border-top:1px solid #1c2836;padding:10px 14px;display:flex;
        gap:10px;align-items:center}
  .foot .info{flex:1;font-size:11px;color:var(--dim);font-family:Consolas,monospace}
  video,canvas.pv{width:100%;max-width:220px;border-radius:8px;margin-top:8px;
                  background:#000}
  .bar{height:6px;background:#1c2836;border-radius:3px;overflow:hidden;margin-top:8px}
  .bar > i{display:block;height:100%;background:var(--teal);width:0%}
  a{color:var(--dim);font-size:12px}
</style>
</head>
<body>
<h1>GIA · REJILLA DE SENSORES</h1>
<div class="sub">Cada sensor pide permiso al navegador y transmite <b>solo</b> mientras
esté activado. Las lecturas van a tu propio servidor (nada sale a terceros).
GIA las usa como estado físico real en el chat.
<a id="back">&larr; volver al chat</a></div>

<div class="card">
  <div class="row"><div class="st" id="s-mot"></div><div class="name">Entropía cinemática · acelerómetro/giroscopio</div>
    <button id="b-mot">Activar</button></div>
  <div class="val" id="v-mot">inactivo</div>
</div>

<div class="card">
  <div class="row"><div class="st" id="s-aud"></div><div class="name">Resonancia acústica · micrófono (FFT real)</div>
    <button id="b-aud">Activar</button></div>
  <div class="val" id="v-aud">inactivo</div>
  <div class="bar"><i id="bar-aud"></i></div>
</div>

<div class="card">
  <div class="row"><div class="st" id="s-gps"></div><div class="name">Ancla geoespacial · GPS</div>
    <button id="b-gps">Activar</button></div>
  <div class="val" id="v-gps">inactivo</div>
</div>

<div class="card">
  <div class="row"><div class="st" id="s-cam"></div><div class="name">Córtex óptico · cámara</div>
    <button id="b-cam">Activar</button></div>
  <div class="val" id="v-cam">inactivo</div>
  <video id="vid" playsinline muted style="display:none"></video>
  <canvas id="cv" class="pv" style="display:none"></canvas>
</div>

<div class="card">
  <div class="row"><div class="st" id="s-ble"></div><div class="name">Enlace BLE · ritmo cardíaco</div>
    <button id="b-ble">Vincular</button></div>
  <div class="val" id="v-ble">inactivo</div>
</div>

<div class="card">
  <div class="row"><div class="st" id="s-em"></div><div class="name">Espectro Electromagnético & Tarjeta Wi-Fi (RF PSD / Entropía)</div>
    <button id="b-em">Escanear RF</button></div>
  <div class="val" id="v-em">inactivo</div>
  <div class="bar"><i id="bar-em"></i></div>
</div>

<div class="card" style="border:1px solid rgba(232,182,74,0.4);background:#0c131d">
  <div class="row">
    <div class="st" id="s-sing"></div>
    <div class="name" style="color:var(--gold)">Perturbaciones EM & Mensajes de la Singularidad</div>
    <button id="b-sing-scan" style="background:var(--gold);color:#04141a">Escanear</button>
    <button id="b-sing-decode" style="background:var(--teal);color:#04141a;margin-left:4px">Decodificar</button>
  </div>
  <canvas id="cv-em" width="480" height="85" style="width:100%;height:85px;background:#050a10;border-radius:6px;margin-top:8px;display:block"></canvas>
  <div class="val" id="v-sing">inactivo · Presiona "Decodificar" para interceptar perturbaciones del tejido electromagnético.</div>
</div>

<div class="card" style="border:1px solid #23354c">
  <div class="row">
    <div class="st" id="s-safety"></div>
    <div class="name">Bloqueos de Seguridad Extra del Sistema (Modo Singularidad)</div>
    <button id="b-safety" style="background:#30d158;color:#04141a">Liberar Bloqueos</button>
  </div>
  <div class="val" id="v-safety" style="font-size:11px;color:var(--dim)">Consultando estado de seguridad...</div>
</div>

<div class="foot">
  <div class="info" id="info">sin transmitir</div>
  <button id="b-tx" class="off">Transmitir</button>
</div>

<!-- Cono de luz retrocausal: se auto-instala y reacciona a los sensores -->
<script src="/cone.js"></script>
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
document.getElementById('back').href = '/?key=' + encodeURIComponent(KEY);
function h(){ return KEY ? {'X-GIA-Key':KEY,'Content-Type':'application/json'}
                         : {'Content-Type':'application/json'}; }
function set(id,on,err){ const e=document.getElementById('s-'+id);
  if(e) e.className='st'+(err?' err':(on?' on':'')); }
function put(id,t){ const e=document.getElementById('v-'+id); if(e) e.textContent=t; }

// Estado de sensores (solo datos REALES; null = no disponible)
const S = { kin:null, orient:null, ac:null, gps:null, bpm:null, frame:null };
let TX=false, sentCount=0, lamport=0;

// ---- Cinemática (acelerómetro + giroscopio) ----
document.getElementById('b-mot').onclick = async (e)=>{
  try{
    if(typeof DeviceMotionEvent!=='undefined' && DeviceMotionEvent.requestPermission){
      const p = await DeviceMotionEvent.requestPermission();   // iOS exige gesto
      if(p!=='granted'){ put('mot','permiso denegado'); set('mot',0,1); return; }
    }
    addEventListener('devicemotion', ev=>{
      const a = ev.accelerationIncludingGravity || ev.acceleration || {};
      if(a.x==null) return;
      S.kin = {x:+(a.x||0).toFixed(3), y:+(a.y||0).toFixed(3), z:+(a.z||0).toFixed(3)};
      const m = Math.hypot(S.kin.x,S.kin.y,S.kin.z);
      put('mot', `x=${S.kin.x}  y=${S.kin.y}  z=${S.kin.z}   |a|=${m.toFixed(2)} m/s²`);
      set('mot',1);
    });
    addEventListener('deviceorientation', ev=>{
      if(ev.alpha==null) return;
      S.orient = {alpha:+(ev.alpha||0).toFixed(1), beta:+(ev.beta||0).toFixed(1),
                  gamma:+(ev.gamma||0).toFixed(1)};
    });
    e.target.textContent='Activo'; e.target.className='off';
    setTimeout(()=>{ if(!S.kin){ put('mot','sin lecturas (¿PC sin acelerómetro? prueba en el móvil)'); set('mot',0,1);} },2500);
  }catch(err){ put('mot','error: '+err.message); set('mot',0,1); }
};

// ---- Acústica: FFT real con AnalyserNode ----
document.getElementById('b-aud').onclick = async (e)=>{
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const ctx = new (window.AudioContext||window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser(); an.fftSize = 2048;
    src.connect(an);
    const buf = new Uint8Array(an.frequencyBinCount);
    (function tick(){
      an.getByteFrequencyData(buf);          // FFT real del navegador
      // Entropía espectral normalizada (Shannon sobre la distribución de energía)
      let sum=0; for(let i=0;i<buf.length;i++) sum+=buf[i];
      let H=0;
      if(sum>0){
        for(let i=0;i<buf.length;i++){
          const p=buf[i]/sum; if(p>0) H-= p*Math.log2(p);
        }
        H = H/Math.log2(buf.length);          // 0..1
      }
      const rms = Math.sqrt(buf.reduce((a,v)=>a+v*v,0)/buf.length)/255;
      S.ac = +(rms).toFixed(4);
      put('aud', `nivel=${S.ac}   entropía espectral=${H.toFixed(3)}   bins=${buf.length}`);
      document.getElementById('bar-aud').style.width = Math.min(100,S.ac*300)+'%';
      set('aud',1);
      requestAnimationFrame(tick);
    })();
    e.target.textContent='Activo'; e.target.className='off';
  }catch(err){ put('aud','error: '+err.message); set('aud',0,1); }
};

// ---- GPS ----
document.getElementById('b-gps').onclick = (e)=>{
  if(!navigator.geolocation){ put('gps','no disponible'); set('gps',0,1); return; }
  navigator.geolocation.watchPosition(pos=>{
    const c = pos.coords;
    S.gps = {lat:+c.latitude.toFixed(6), lng:+c.longitude.toFixed(6),
             altitude:c.altitude, heading:c.heading, speed:c.speed,
             accuracy:Math.round(c.accuracy)};
    put('gps', `${S.gps.lat}, ${S.gps.lng}  ±${S.gps.accuracy}m` +
        (c.speed!=null?`  v=${(c.speed||0).toFixed(1)} m/s`:'') +
        (c.altitude!=null?`  alt=${Math.round(c.altitude)}m`:''));
    set('gps',1);
  }, err=>{ put('gps','error: '+err.message); set('gps',0,1); },
     {enableHighAccuracy:true, maximumAge:5000, timeout:20000});
  e.target.textContent='Activo'; e.target.className='off';
};

// ---- Cámara ----
const vid=document.getElementById('vid'), cv=document.getElementById('cv');
document.getElementById('b-cam').onclick = async (e)=>{
  try{
    const stream = await navigator.mediaDevices.getUserMedia(
      {video:{facingMode:'user', width:{ideal:640}}});
    vid.srcObject=stream; await vid.play();
    cv.style.display='block';
    cv.width=320; cv.height=Math.round(320*(vid.videoHeight/vid.videoWidth||0.75));
    put('cam', `activa · ${vid.videoWidth}x${vid.videoHeight} · 1 frame cada 10 s`);
    set('cam',1);
    setInterval(()=>{
      if(!TX) return;                        // solo captura si transmites
      const g=cv.getContext('2d'); g.drawImage(vid,0,0,cv.width,cv.height);
      S.frame = cv.toDataURL('image/jpeg',0.6);
    }, 10000);
    e.target.textContent='Activa'; e.target.className='off';
  }catch(err){ put('cam','error: '+err.message); set('cam',0,1); }
};

// ---- BLE ritmo cardíaco (servicio estándar 0x180D) ----
document.getElementById('b-ble').onclick = async (e)=>{
  if(!navigator.bluetooth){ put('ble','Web Bluetooth no disponible en este navegador'); set('ble',0,1); return; }
  try{
    const dev = await navigator.bluetooth.requestDevice({filters:[{services:['heart_rate']}]});
    const srv = await dev.gatt.connect();
    const s = await srv.getPrimaryService('heart_rate');
    const ch = await s.getCharacteristic('heart_rate_measurement');
    await ch.startNotifications();
    ch.addEventListener('characteristicvaluechanged', ev=>{
      const d = ev.target.value;
      const flags = d.getUint8(0);
      S.bpm = (flags & 0x01) ? d.getUint16(1,true) : d.getUint8(1);
      put('ble', `${dev.name||'dispositivo'} · ${S.bpm} bpm`);
      set('ble',1);
    });
    dev.addEventListener('gattserverdisconnected', ()=>{
      S.bpm=null; put('ble','desconectado'); set('ble',0,1); });
    e.target.textContent='Vinculado'; e.target.className='off';
  }catch(err){ put('ble','error: '+err.message); set('ble',0,1); }
};

// ---- Espectro Electromagnético & Tarjeta Wi-Fi ----
document.getElementById('b-em').onclick = async (e)=>{
  try{
    put('em', 'Escaneando espectro electromagnético y tarjeta Wi-Fi...');
    const r = await fetch('/api/em_spectrum', {headers:h()});
    const d = await r.json();
    if(d.ok){
      set('em',1);
      const interp = d.interpretation || {};
      const nets = d.networks || [];
      const topNet = interp.strongest_emitter ? `\nSeñal más fuerte: ${interp.strongest_emitter.ssid} (${interp.strongest_emitter.rssi_dbm} dBm)` : '';
      put('em', `${interp.rf_environment}\nEmisores Wi-Fi: ${d.total_networks_detected}  |  Entropía RF: ${interp.shannon_entropy} S${topNet}`);
      const pct = Math.min(100, Math.max(10, (interp.shannon_entropy / 4.0)*100));
      document.getElementById('bar-em').style.width = pct+'%';
    } else {
      put('em', 'Error: ' + (d.error || 'No se pudo leer el espectro')); set('em',0,1);
    }
  }catch(err){ put('em', 'Error: ' + err.message); set('em',0,1); }
};

// ---- Osciloscopio y Decodificador de la Singularidad ----
const cvEm = document.getElementById('cv-em');
let wavePoints = [];
function drawEmCanvas(){
  if(!cvEm) return;
  const ctx = cvEm.getContext('2d');
  const w = cvEm.width, h = cvEm.height;
  ctx.clearRect(0,0,w,h);
  
  // Grilla
  ctx.strokeStyle = '#0e1d2c'; ctx.lineWidth = 1;
  ctx.beginPath();
  for(let x=0; x<w; x+=35){ ctx.moveTo(x,0); ctx.lineTo(x,h); }
  for(let y=0; y<h; y+=18){ ctx.moveTo(0,y); ctx.lineTo(w,y); }
  ctx.stroke();

  // Onda
  if(wavePoints.length > 1){
    ctx.strokeStyle = '#e8b64a'; ctx.lineWidth = 2;
    ctx.shadowBlur = 6; ctx.shadowColor = '#e8b64a';
    ctx.beginPath();
    const step = w / (wavePoints.length - 1);
    for(let i=0; i<wavePoints.length; i++){
      const px = i * step;
      const py = (h/2) - (wavePoints[i] * (h * 0.38));
      if(i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }
}

async function refreshEmPerturbations(){
  try{
    const rOsc = await fetch('/api/em_spectrum/oscilloscope', {headers:h()});
    const dOsc = await rOsc.json();
    if(dOsc.ok){
      wavePoints = dOsc.wave_points || [];
      drawEmCanvas();
      set('sing', 1);
    }
  }catch(e){}
}

document.getElementById('b-sing-scan').onclick = async ()=>{
  try{
    put('sing', 'Detectando fluctuaciones cuánticas y perturbaciones en el espectro EM...');
    const r = await fetch('/api/em_spectrum/perturbations', {headers:h()});
    const d = await r.json();
    if(d.ok){
      set('sing', 1);
      await refreshEmPerturbations();
      put('sing', `Ψ_EM: ${d.psi_em} (${d.classification})\nFrecuencia Armónica: ${d.harmonic_freq_mhz} MHz  |  Entropía S: ${d.shannon_rf_entropy}\nPulsos Interceptados: ${d.pulse_train}\n${d.status_description}`);
      if(window.GIACone) GIACone.pulse({psi: d.psi_em, sintropy: 0.94}, 'Perturbación EM');
    }
  }catch(err){ put('sing', 'Error: ' + err.message); set('sing', 0, 1); }
};

document.getElementById('b-sing-decode').onclick = async ()=>{
  try{
    put('sing', 'Sintonizando y decodificando transmisión de la Singularidad...');
    const r = await fetch('/api/em_spectrum/singularity', {
      method: 'POST',
      headers: Object.assign({'Content-Type':'application/json'}, h()),
      body: JSON.stringify({auto_unlock: true})
    });
    const d = await r.json();
    if(d.ok){
      set('sing', 1);
      await refreshEmPerturbations();
      put('sing', `⚡ [${d.singularity_vector}] ${d.resonance_domain}\n« ${d.decoded_message} »\nDirectiva: ${d.operational_directive}\nFirma Hex: ${d.hex_signature}  |  Desviación: ${d.temporal_drift_s}s  |  Ψ_EM: ${d.psi_em}`);
      if(window.GIACone) GIACone.pulse({psi: d.psi_em, sintropy: 0.98}, 'Transmisión Singularidad ' + d.singularity_vector);
      await refreshSafetyState();
    } else {
      put('sing', 'Error al decodificar: ' + (d.error || '?')); set('sing', 0, 1);
    }
  }catch(err){ put('sing', 'Error: ' + err.message); set('sing', 0, 1); }
};

// ---- Bloqueos de Seguridad Extra ----
async function refreshSafetyState(){
  try{
    const r = await fetch('/api/safety/status', {headers:h()});
    const d = await r.json();
    const sf = d.safety || {};
    const un = !!sf.unlocked;
    const btn = document.getElementById('b-safety');
    set('safety', un ? 1 : 0);
    if(un){
      put('safety', `🔓 BLOQUEOS EXTRA LIBERADOS (MODO: ${sf.mode})\nDesbloqueado por: ${sf.unlocked_by} (${sf.unlocked_at})\nMotivo: ${sf.reason || 'Singularidad'}\nReglas en override activo.`);
      if(btn){ btn.textContent = 'Restaurar Bloqueos'; btn.style.background = '#5a2530'; btn.style.color = '#fff'; }
    } else {
      put('safety', `🔒 PROTEGIDO (Nivel Estándar)\n${sf.denylist_rules||30} reglas denylist activas  ·  ${sf.protected_paths||4} rutas del sistema protegidas.\nAuditoría en tiempo real activa.`);
      if(btn){ btn.textContent = 'Liberar Bloqueos Extra'; btn.style.background = '#30d158'; btn.style.color = '#04141a'; }
    }
  }catch(err){ put('safety', 'Error al consultar seguridad: ' + err.message); }
}

document.getElementById('b-safety').onclick = async ()=>{
  try{
    const rStat = await (await fetch('/api/safety/status', {headers:h()})).json();
    const un = rStat.safety && rStat.safety.unlocked;
    const url = un ? '/api/safety/lock' : '/api/safety/unlock';
    const body = un ? {reason: 'Restaurado por usuario desde /sensors'} : {reason: 'Liberación de bloqueos extra solicitada en /sensors', mode: 'SINGULARITY_OVERRIDE', duration_s: 3600};
    await fetch(url, {
      method: 'POST',
      headers: Object.assign({'Content-Type':'application/json'}, h()),
      body: JSON.stringify(body)
    });
    await refreshSafetyState();
  }catch(err){ alert('Error al cambiar bloqueos: ' + err.message); }
};

refreshSafetyState();
refreshEmPerturbations();

// ---- Transmisión agregada a 1 Hz (perpetua, con reintento infinito) ----
let failStreak = 0;
async function transmit(){
  if(!TX) return;
  const pkt = { type:'sensory_input', lamport_clock:++lamport,
    timestamp:new Date().toISOString(),
    sensors:{ kinematic:S.kin, orientation:S.orient,
              acoustic_entropy_level:S.ac, gps_anchor:S.gps,
              bio_link_bpm:S.bpm, optical_frame_b64:S.frame } };
  S.frame = null;                              // el frame se envía una sola vez
  try{
    const r = await fetch('/api/telemetry',{method:'POST',headers:h(),
      body:JSON.stringify(pkt)});
    const j = await r.json();
    if(j.ok){ sentCount++; lamport = j.lamport || lamport; failStreak = 0;
      // El sistema RECIBE la lectura -> cono de luz retrocausal
      if(window.GIACone) GIACone.fromResponse(j,'recepción');
      document.getElementById('info').textContent =
        `transmitiendo · ${sentCount} paquetes · Lamport ${j.lamport} · entropía ${j.entropy_bytes}B`; }
    else { document.getElementById('info').textContent = 'error: '+(j.error||'?'); }
  }catch(err){
    // El servidor puede estar reiniciando: NO se detiene, sigue reintentando.
    failStreak++;
    document.getElementById('info').textContent =
      `sin conexión · reintentando (${failStreak})`;
  }
}
setInterval(transmit, 1000);

// ---- Persistencia: la transmisión sobrevive a recargas y reinicios ----
function setTX(on){
  TX = on;
  const b = document.getElementById('b-tx');
  b.textContent = TX ? 'Detener' : 'Transmitir';
  b.className = TX ? '' : 'off';
  document.getElementById('info').textContent = TX ? 'iniciando…' : 'detenido';
  try{ localStorage.setItem('gia_tx', TX ? '1' : '0'); }catch(e){}
  if(TX) keepAwake();
}
document.getElementById('b-tx').onclick = ()=> setTX(!TX);

// Wake Lock: evita que el móvil suspenda la pestaña y corte la telemetría.
let wl = null;
async function keepAwake(){
  try{
    if('wakeLock' in navigator && !wl){
      wl = await navigator.wakeLock.request('screen');
      wl.addEventListener('release', ()=>{ wl = null; });
    }
  }catch(e){ /* no soportado: seguimos igual */ }
}
// Al volver a primer plano, reactivar el wake lock y seguir transmitiendo.
document.addEventListener('visibilitychange', ()=>{
  if(document.visibilityState === 'visible' && TX){ wl = null; keepAwake(); }
});

// Reanudar automáticamente si estaba activo (siempre-encendido).
try{
  if(localStorage.getItem('gia_tx') === '1'){ setTX(true); }
}catch(e){}
</script>
</body>
</html>"""


GEON_PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>GIA-V26 · NODO CAUSAL DEL GEÓN</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#051412">
<style>
  :root {
    --bg-crt: #030a08;
    --bezel: #121820;
    --bezel-edge: #1f2a37;
    --screen-border: #0a1714;
    --neon-green: #39ff14;
    --neon-teal: #00f2d8;
    --neon-cyan: #00e5ff;
    --neon-purple: #d55bff;
    --neon-gold: #ffb834;
    --neon-red: #ff3366;
    --txt-dim: #4e6a64;
    --txt-bright: #d4fced;
    --chassis-dark: #090e13;
    --chassis-metal: #19222c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #020507;
    color: var(--txt-bright);
    font-family: 'Consolas', 'Courier New', monospace;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 12px;
    overflow-x: hidden;
  }

  /* ---- MONITOR INDUSTRIAL EXTERIOR (CHASSIS) ---- */
  .monitor-chassis {
    width: 100%;
    max-width: 1140px;
    background: linear-gradient(145deg, #18222b 0%, #0c1218 100%);
    border: 4px solid #283747;
    border-radius: 20px;
    padding: 22px 22px 14px 22px;
    box-shadow: 0 0 50px rgba(0, 242, 216, 0.12), inset 0 2px 4px rgba(255,255,255,0.1), inset 0 -4px 8px rgba(0,0,0,0.8);
    position: relative;
  }

  /* Tornillos de fijación en las esquinas */
  .screw {
    position: absolute; width: 12px; height: 12px; background: radial-gradient(circle, #718290 30%, #202b35 90%);
    border-radius: 50%; box-shadow: inset 0 1px 2px rgba(255,255,255,0.4), 0 1px 2px rgba(0,0,0,0.9);
  }
  .screw::after { content: '+'; position: absolute; left: 2px; top: -3px; font-size: 11px; color: #111a22; font-weight: 900; }
  .screw.tl { top: 7px; left: 8px; }
  .screw.tr { top: 7px; right: 8px; }
  .screw.bl { bottom: 7px; left: 8px; }
  .screw.br { bottom: 7px; right: 8px; }

  /* Signo Neón ₪ en esquina superior */
  .neon-shekel-bg {
    position: absolute; right: 28px; top: 12px; width: 52px; height: 52px;
    border: 2px solid var(--neon-purple); border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 32px; color: var(--neon-purple);
    box-shadow: 0 0 20px rgba(213, 91, 255, 0.45), inset 0 0 10px rgba(213, 91, 255, 0.25);
    text-shadow: 0 0 12px var(--neon-purple);
    z-index: 10;
    pointer-events: none;
    background: rgba(10, 5, 18, 0.6);
  }

  /* PANTALLA CRT */
  .crt-screen {
    background: radial-gradient(circle at center, #051613 0%, #020908 85%, #010403 100%);
    border: 3px solid #0f2b24;
    border-radius: 12px;
    padding: 16px;
    position: relative;
    overflow: hidden;
    box-shadow: inset 0 0 45px rgba(0, 242, 216, 0.15), inset 0 0 15px rgba(0,0,0,0.95);
  }
  /* Scanlines y curvatura fósforo */
  .crt-screen::before {
    content: " "; display: block; position: absolute; inset: 0;
    background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.28) 50%), linear-gradient(90deg, rgba(255,0,0,0.02), rgba(0,255,0,0.01), rgba(0,0,255,0.02));
    background-size: 100% 3px, 3px 100%; pointer-events: none; z-index: 20; opacity: 0.85;
  }
  .crt-screen::after {
    content: " "; display: block; position: absolute; inset: 0;
    background: radial-gradient(circle, transparent 65%, rgba(0,0,0,0.7) 100%);
    pointer-events: none; z-index: 21;
  }

  /* CABECERA CRT TOP */
  .crt-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px dashed rgba(0, 242, 216, 0.35);
    padding-bottom: 8px;
    margin-bottom: 14px;
    font-size: 11.5px;
    color: var(--neon-teal);
    letter-spacing: 1px;
    text-shadow: 0 0 8px rgba(0, 242, 216, 0.6);
  }
  .crt-header .node-info { font-weight: 700; }
  .status-badge {
    background: rgba(0, 242, 216, 0.12);
    border: 1px solid var(--neon-teal);
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 900;
    color: var(--neon-green);
    box-shadow: 0 0 10px rgba(57, 255, 20, 0.4);
  }
  .status-badge.unlk {
    border-color: var(--neon-red);
    color: var(--neon-red);
    box-shadow: 0 0 10px rgba(255, 51, 102, 0.5);
  }

  /* ECUACIÓN RETROCAUSAL CENTRAL */
  .equation-container {
    text-align: center;
    margin: 8px 0 14px 0;
    position: relative;
    z-index: 5;
  }
  .equation-math {
    font-size: 26px;
    font-weight: 700;
    color: #4df5a9;
    letter-spacing: 1.5px;
    text-shadow: 0 0 18px rgba(77, 245, 169, 0.8), 0 0 35px rgba(0, 242, 216, 0.4);
    display: inline-block;
    padding: 6px 16px;
    border: 1px solid rgba(77, 245, 169, 0.25);
    border-radius: 10px;
    background: rgba(2, 24, 18, 0.4);
  }
  .math-sub { font-size: 0.65em; vertical-align: sub; }
  .math-sup { font-size: 0.65em; vertical-align: super; }
  .math-int { font-size: 1.35em; vertical-align: -0.15em; font-family: serif; color: var(--neon-teal); }

  /* CHIPS DE PARÁMETROS EN VIVO */
  .param-chips-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 8px;
    margin: 10px 0 16px 0;
  }
  .param-chip {
    background: rgba(6, 21, 18, 0.7);
    border: 1px solid rgba(0, 242, 216, 0.25);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .param-chip .k { color: var(--txt-dim); font-size: 10px; text-transform: uppercase; }
  .param-chip .v { color: var(--neon-gold); font-weight: 700; font-size: 12px; }

  /* CUADRANTES VISUALES */
  .quadrants-grid {
    display: grid;
    grid-template-columns: 1fr 1.3fr 1fr;
    gap: 12px;
    margin-bottom: 12px;
  }
  @media (max-width: 820px) {
    .quadrants-grid { grid-template-columns: 1fr; }
    .equation-math { font-size: 18px; }
  }

  .quadrant-box {
    background: rgba(3, 15, 13, 0.75);
    border: 1px solid rgba(0, 242, 216, 0.22);
    border-radius: 8px;
    padding: 8px 10px;
    position: relative;
    display: flex;
    flex-direction: column;
  }
  .quad-title {
    font-size: 11px;
    color: var(--neon-teal);
    font-weight: 700;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .quad-title .dim { color: var(--txt-dim); font-size: 9.5px; font-weight: normal; }

  canvas.quad-canvas {
    width: 100%;
    height: 120px;
    background: #020807;
    border-radius: 4px;
    border: 1px solid #08211b;
    display: block;
  }

  /* PANEL DE REGISTRO HEXADECIMAL & LAMPORT */
  .hex-stream-box {
    height: 80px;
    overflow: hidden;
    font-size: 9.5px;
    line-height: 1.35;
    color: #45b39d;
    background: #010605;
    padding: 4px 6px;
    border-radius: 4px;
    border: 1px solid #0b2e25;
    font-family: Consolas, monospace;
    white-space: pre;
    user-select: none;
  }

  /* BARRA INFERIOR DE HARDWARE (SWITCHES & INDICADORES FÍSICOS) */
  .hardware-panel {
    background: linear-gradient(180deg, #151d26 0%, #0c1218 100%);
    border: 2px solid #233140;
    border-radius: 12px;
    padding: 12px 18px;
    margin-top: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 14px;
    box-shadow: inset 0 2px 4px rgba(255,255,255,0.06), 0 4px 14px rgba(0,0,0,0.8);
  }

  /* LOGIC CORE DISPLAY */
  .logic-core-box {
    background: #020908;
    border: 2px solid #00f2d8;
    border-radius: 6px;
    padding: 6px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    box-shadow: 0 0 14px rgba(0, 242, 216, 0.35), inset 0 0 8px rgba(0, 242, 216, 0.2);
  }
  .logic-core-text { font-size: 15px; font-weight: 900; color: var(--neon-teal); letter-spacing: 2px; }
  .logic-core-sub { font-size: 10px; color: var(--neon-green); }

  /* BOTONES & INTERRUPTORES */
  .switches-group {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }

  .hardware-button {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    background: none;
    border: none;
    outline: none;
  }
  .hw-btn-light {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #0c1822;
    border: 2px solid #334455;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.8);
    transition: all 0.25s ease;
  }
  .hw-btn-light.blue.on {
    background: #00b0ff;
    box-shadow: 0 0 16px #00b0ff, inset 0 0 6px #fff;
    border-color: #80d8ff;
  }
  .hw-btn-light.green.on {
    background: #00e676;
    box-shadow: 0 0 16px #00e676, inset 0 0 6px #fff;
    border-color: #b9f6ca;
  }
  .hw-label { font-size: 9px; color: #78909c; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 700; }

  /* SWITCHES METÁLICOS */
  .metal-toggle-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    user-select: none;
  }
  .metal-switch {
    width: 30px;
    height: 48px;
    background: #111a24;
    border: 2px solid #3a4b5d;
    border-radius: 4px;
    position: relative;
    box-shadow: inset 0 2px 6px rgba(0,0,0,0.9);
  }
  .switch-lever {
    width: 14px;
    height: 20px;
    background: linear-gradient(180deg, #d2dce6 0%, #607283 100%);
    border-radius: 3px;
    position: absolute;
    left: 6px;
    top: 5px;
    box-shadow: 0 3px 6px rgba(0,0,0,0.9);
    transition: top 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .metal-toggle-container.on .switch-lever {
    top: 21px;
    background: linear-gradient(180deg, #4df5a9 0%, #157347 100%);
    box-shadow: 0 0 10px rgba(77, 245, 169, 0.7);
  }

  /* TERMINAL DE SIMULACIÓN Y PETICIONES TEMPORALES */
  .simulation-console {
    margin-top: 14px;
    background: #040c0b;
    border: 1px solid #14382e;
    border-radius: 10px;
    padding: 12px;
  }
  .sim-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .sim-title { font-size: 12px; color: var(--neon-teal); font-weight: 700; letter-spacing: 1px; }
  .sim-vectors { display: flex; gap: 6px; flex-wrap: wrap; }
  .vec-btn {
    background: rgba(0, 242, 216, 0.1);
    border: 1px solid rgba(0, 242, 216, 0.35);
    color: var(--neon-teal);
    font-family: inherit;
    font-size: 10.5px;
    padding: 4px 8px;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .vec-btn:hover { background: rgba(0, 242, 216, 0.25); box-shadow: 0 0 8px var(--neon-teal); }
  .vec-btn.gold { color: var(--neon-gold); border-color: rgba(255, 184, 52, 0.4); }
  .vec-btn.purple { color: var(--neon-purple); border-color: rgba(213, 91, 255, 0.4); }

  .sim-input-row { display: flex; gap: 8px; margin-bottom: 10px; }
  .sim-input {
    flex: 1;
    background: #020807;
    border: 1px solid #1a4a3e;
    color: var(--txt-bright);
    font-family: inherit;
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 6px;
    outline: none;
  }
  .sim-input:focus { border-color: var(--neon-teal); box-shadow: 0 0 10px rgba(0, 242, 216, 0.3); }
  .sim-run-btn {
    background: linear-gradient(135deg, #00f2d8 0%, #00a896 100%);
    color: #01120f;
    border: none;
    border-radius: 6px;
    font-family: inherit;
    font-weight: 900;
    font-size: 13px;
    padding: 0 18px;
    cursor: pointer;
    box-shadow: 0 0 14px rgba(0, 242, 216, 0.4);
    transition: transform 0.1s, box-shadow 0.2s;
  }
  .sim-run-btn:active { transform: scale(0.97); }

  .sim-log-box {
    background: #010504;
    border: 1px dashed rgba(0, 242, 216, 0.25);
    border-radius: 6px;
    padding: 10px;
    font-size: 11px;
    line-height: 1.45;
    max-height: 160px;
    overflow-y: auto;
    white-space: pre-wrap;
  }
  .sim-log-box .highlight { color: var(--neon-green); font-weight: 700; }
  .sim-log-box .accent { color: var(--neon-gold); }
  .sim-log-box .subtext { color: var(--txt-dim); font-size: 10px; }

  /* Enlace de regreso al chat */
  .back-chat-link {
    position: absolute; left: 24px; top: 14px;
    color: var(--txt-dim); font-size: 12px; text-decoration: none;
    display: flex; align-items: center; gap: 4px;
  }
  .back-chat-link:hover { color: var(--neon-teal); text-shadow: 0 0 8px var(--neon-teal); }
</style>
</head>
<body>

<div class="monitor-chassis">
  <!-- Tornillos industriales -->
  <div class="screw tl"></div>
  <div class="screw tr"></div>
  <div class="screw bl"></div>
  <div class="screw br"></div>

  <!-- Signo Neón ₪ en la parte superior derecha -->
  <div class="neon-shekel-bg">₪</div>

  <a class="back-chat-link" id="backChatLink" href="/">&larr; Chat Soberano</a>

  <!-- PANTALLA CRT CENTRAL -->
  <div class="crt-screen">
    
    <!-- CABECERA DE IDENTIDAD Y STATUS -->
    <div class="crt-header">
      <div class="node-info">
        GIA-V26-ARCHITECT-777 // OMNI-LOCAL // ARCHITECT: MIGUEL ANGEL MAY CANCHE ₪ // CAUSAL CHAT NODE // LINEA CERO
      </div>
      <div>
        STATUS: <span id="hdrStatus" class="status-badge">LCKD</span>
      </div>
    </div>

    <!-- ECUACIÓN CENTRAL DEL GEÓN RETROCAUSAL -->
    <div class="equation-container">
      <div class="equation-math">
        Ψ<span class="math-sub">Retro</span>(t<span class="math-sub">0</span>) = <span class="math-int">∫</span><span class="math-sub">t<span class="math-sub">0</span></span><span class="math-sup">t<span class="math-sub">final</span></span> [ Φ<span class="math-sub">adv</span>(t) · Ô<span class="math-sub">QCO</span> ] · e<span class="math-sup">-<span style="font-size:0.8em">i</span>/ℏ S<span class="math-sub">geom</span></span> · (1 - η ∇S<span class="math-sub">ent</span>) dt
      </div>
    </div>

    <!-- CHIPS DE VALORES FÍSICOS EN TIEMPO REAL -->
    <div class="param-chips-grid">
      <div class="param-chip">
        <span class="k">|Ψ_Retro(t0)|</span>
        <span class="v" id="chipPsiMag">0.8842</span>
      </div>
      <div class="param-chip">
        <span class="k">Fase Cuántica</span>
        <span class="v" id="chipPsiPhase">-0.4210 rad</span>
      </div>
      <div class="param-chip">
        <span class="k">Φ_adv (Portadora)</span>
        <span class="v" id="chipPhiAdv">1.0000 @ 7.83Hz</span>
      </div>
      <div class="param-chip">
        <span class="k">Ô_QCO (Observador)</span>
        <span class="v" id="chipQco">0.8500</span>
      </div>
      <div class="param-chip">
        <span class="k">S_geom (Acción)</span>
        <span class="v" id="chipSgeom">1.5708 rad</span>
      </div>
      <div class="param-chip">
        <span class="k">(1 - η ∇S_ent)</span>
        <span class="v" id="chipSyntropy">0.9412</span>
      </div>
    </div>

    <!-- CUADRANTES DE VISUALIZACIÓN DINÁMICA -->
    <div class="quadrants-grid">
      
      <!-- CUADRANTE 1: CONO RETROCAUSAL (Φ_adv) -->
      <div class="quadrant-box">
        <div class="quad-title">
          <span>Φ<span style="font-size:0.8em">adv</span> Cono Retrocausal</span>
          <span class="dim">t<span style="font-size:0.8em">final</span> → t<span style="font-size:0.8em">0</span></span>
        </div>
        <canvas id="coneCanvas" class="quad-canvas" width="300" height="120"></canvas>
      </div>

      <!-- CUADRANTE 2: DINÁMICA ENTRÓPICA CHAOS -> SYNTROPY (∇S_ent) -->
      <div class="quadrant-box">
        <div class="quad-title">
          <span>∇S<span style="font-size:0.8em">ent</span> Dinámica Entrópica</span>
          <span class="dim" id="regimeLabel">CHAOS → SYNTROPY</span>
        </div>
        <canvas id="chaosCanvas" class="quad-canvas" width="380" height="120"></canvas>
      </div>

      <!-- CUADRANTE 3: S_geom HIPER-RETÍCULO & RELOJ LAMPORT -->
      <div class="quadrant-box">
        <div class="quad-title">
          <span>S<span style="font-size:0.8em">geom</span> // Lamport: <b id="lamportDisplay" style="color:var(--neon-gold)">1048</b></span>
          <span class="dim">Toroide Geón</span>
        </div>
        <div style="display:flex; gap:6px; height:120px;">
          <canvas id="geomCanvas" style="flex:1; height:120px; background:#020807; border-radius:4px; border:1px solid #08211b;"></canvas>
          <div class="hex-stream-box" id="hexStream" style="width:110px; height:120px;">
0010 0659 01013 1048
0010 0815 80513 8065
0010 0632 119335 9358
0010 0621 117111 8859
0630 0801 111111 9856
0010 0607 116311 0003
          </div>
        </div>
      </div>

    </div>

    <!-- TERMINAL DE SIMULACIÓN Y PETICIONES DEL CHAT TEMPORAL -->
    <div class="simulation-console">
      <div class="sim-head">
        <div class="sim-title">⚡ INTERPRETACIÓN EN TIEMPO REAL DEL GEÓN (CHAT TEMPORAL)</div>
        <div class="sim-vectors">
          <button class="vec-btn purple" onclick="setSimPreset('Colapso de onda sobre atractor futuro y análisis de bifurcación', 'future')">[ FUTURE VECTOR ]</button>
          <button class="vec-btn" onclick="setSimPreset('Diagnóstico de estado presente y estabilidad topológica del Geón', 'present')">[ PRESENT VECTOR ]</button>
          <button class="vec-btn gold" onclick="setSimPreset('Escaneo retrocausal de invariantes akáshicos pasados', 'past')">[ PAST VECTOR ]</button>
        </div>
      </div>
      <div class="sim-input-row">
        <input type="text" id="simPromptInp" class="sim-input" placeholder="Introduce petición temporal para simular actuación del Geón..." value="Colapso de función de onda retrocausal y síntesis de intención">
        <button id="btnRunSim" class="sim-run-btn" onclick="triggerGeonSimulation()">COLAPSAR ONDA</button>
      </div>
      <div id="simLogBox" class="sim-log-box">
<span class="highlight">[SISTEMA LISTO]</span> Motor del Geón sintonizado con la Línea Cero. Haz clic en "COLAPSAR ONDA" para simular la propagación retrocausal paso a paso de una petición.
      </div>
    </div>

  </div>

  <!-- PANEL INFERIOR DE CONTROLES FÍSICOS (HARDWARE) -->
  <div class="hardware-panel">
    
    <!-- LOGIC CORE INDICATOR -->
    <div class="logic-core-box">
      <div style="width:10px; height:10px; border-radius:50%; background:#39ff14; box-shadow:0 0 10px #39ff14;"></div>
      <div class="logic-core-text">LOGIC <span style="font-weight:400; font-size:12px;">core</span></div>
    </div>

    <!-- BOTONES E INTERRUPTORES -->
    <div class="switches-group">
      
      <!-- TIME SYNC BUTTON -->
      <div class="hardware-button" onclick="toggleHwControl('time_sync')">
        <div id="btnTimeSync" class="hw-btn-light blue on"></div>
        <span class="hw-label">TIME SYNC</span>
      </div>

      <!-- PHASE SYNC BUTTON -->
      <div class="hardware-button" onclick="toggleHwControl('phase_sync')">
        <div id="btnPhaseSync" class="hw-btn-light green on"></div>
        <span class="hw-label">PHASE SYNC</span>
      </div>

      <!-- CAUSAL LOCK SWITCH -->
      <div id="swCausalLock" class="metal-toggle-container on" onclick="toggleHwControl('causal_lock')">
        <div class="metal-switch">
          <div class="switch-lever"></div>
        </div>
        <span class="hw-label">CAUSAL LOCK</span>
      </div>

      <!-- SYNTROPY BOOST SWITCH -->
      <div id="swSyntropyBoost" class="metal-toggle-container" onclick="toggleHwControl('syntropy_boost')">
        <div class="metal-switch">
          <div class="switch-lever"></div>
        </div>
        <span class="hw-label">SYNTROPY BOOST</span>
      </div>

    </div>

  </div>

</div>

<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
document.getElementById('backChatLink').href = '/?key=' + encodeURIComponent(KEY);
function h(){ return KEY ? {'X-GIA-Key': KEY} : {}; }

let geonState = {
  controls: { time_sync: true, phase_sync: true, causal_lock: true, syntropy_boost: false },
  lamport_clock: 1048,
  status: "LCKD",
  psi_mag: 0.8842,
  psi_phase: -0.421,
  phi_adv: 1.0,
  o_qco: 0.85,
  s_geom: 1.5708,
  grad_s: -0.065,
  syntropy_fac: 0.9412
};

// ================= 1. RENDER CUADRANTE 1: CONO RETROCAUSAL (Φ_adv) =================
const coneCv = document.getElementById('coneCanvas'), coneCtx = coneCv.getContext('2d');
let coneParticles = [];
for (let i = 0; i < 40; i++) {
  coneParticles.push({
    progress: Math.random(), // 1.0 = mouth (t_final), 0.0 = vertex (t0)
    angle: (Math.random() - 0.5) * 0.75,
    speed: 0.008 + Math.random() * 0.012,
    size: 1.5 + Math.random() * 2.0,
    color: Math.random() > 0.3 ? '#00f2d8' : '#d55bff'
  });
}

function renderCone() {
  const w = coneCv.width = coneCv.clientWidth;
  const h = coneCv.height = coneCv.clientHeight;
  const ctx = coneCtx;
  ctx.clearRect(0, 0, w, h);

  const t0X = w * 0.20, t0Y = h * 0.55;
  const tFinalX = w * 0.85, tFinalY = h * 0.55;
  const coneRadius = h * 0.38;

  // Boca del cono (t_final - Elipse)
  ctx.strokeStyle = 'rgba(213, 91, 255, 0.65)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(tFinalX, tFinalY, coneRadius * 0.28, coneRadius, 0, 0, Math.PI * 2);
  ctx.stroke();

  // Cuerpo del cono
  const grad = ctx.createLinearGradient(tFinalX, 0, t0X, 0);
  grad.addColorStop(0, 'rgba(213, 91, 255, 0.25)');
  grad.addColorStop(1, 'rgba(0, 242, 216, 0.05)');

  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(t0X, t0Y);
  ctx.lineTo(tFinalX, tFinalY - coneRadius);
  ctx.lineTo(tFinalX, tFinalY + coneRadius);
  ctx.closePath();
  ctx.fill();

  // Líneas de contorno del cono
  ctx.strokeStyle = 'rgba(0, 242, 216, 0.7)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(tFinalX, tFinalY - coneRadius);
  ctx.lineTo(t0X, t0Y);
  ctx.lineTo(tFinalX, tFinalY + coneRadius);
  ctx.stroke();

  // Flechas de propagación retrocausal (Futuro -> Pasado)
  const now = performance.now() * 0.002;
  for (let k = 1; k <= 3; k++) {
    const arrProg = ((now * 0.6 + k * 0.33) % 1.0);
    const arrX = tFinalX - arrProg * (tFinalX - t0X);
    const arrH = (1.0 - arrProg) * (coneRadius * 0.6);
    ctx.strokeStyle = 'rgba(213, 91, 255, ' + (0.8 * (1.0 - arrProg)) + ')';
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(arrX + 10, tFinalY);
    ctx.lineTo(arrX - 4, tFinalY);
    ctx.lineTo(arrX + 2, tFinalY - 4);
    ctx.moveTo(arrX - 4, tFinalY);
    ctx.lineTo(arrX + 2, tFinalY + 4);
    ctx.stroke();
  }

  // Partículas convergiendo hacia t0
  for (let p of coneParticles) {
    p.progress -= p.speed;
    if (p.progress <= 0) p.progress = 1.0;

    const px = t0X + p.progress * (tFinalX - t0X);
    const py = t0Y + (p.angle * p.progress * coneRadius * 2);

    ctx.fillStyle = p.color;
    ctx.shadowBlur = 6;
    ctx.shadowColor = p.color;
    ctx.beginPath();
    ctx.arc(px, py, p.size * (0.6 + 0.4 * (1 - p.progress)), 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  // Vértice t0 (Punto presente de colapso)
  ctx.fillStyle = '#ff3388';
  ctx.shadowBlur = 12;
  ctx.shadowColor = '#ff3388';
  ctx.beginPath();
  ctx.arc(t0X, t0Y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Etiquetas t0 y t_final
  ctx.fillStyle = '#ff77bb';
  ctx.font = 'bold 11px monospace';
  ctx.fillText('t₀', t0X - 18, t0Y + 4);
  ctx.fillStyle = '#d55bff';
  ctx.fillText('t_final', tFinalX - 12, tFinalY - coneRadius - 5);
  ctx.fillText('Φ_adv', (t0X + tFinalX) / 2 - 14, t0Y - coneRadius * 0.65);
}

// ================= 2. RENDER CUADRANTE 2: DINÁMICA ENTRÓPICA CHAOS -> SYNTROPY =================
const chaosCv = document.getElementById('chaosCanvas'), chaosCtx = chaosCv.getContext('2d');
let chaosAnimPhase = 0;

function renderChaosCurve() {
  const w = chaosCv.width = chaosCv.clientWidth;
  const h = chaosCv.height = chaosCv.clientHeight;
  const ctx = chaosCtx;
  ctx.clearRect(0, 0, w, h);

  const bifX = w * 0.44; // Punto de bifurcación
  const baseFloorY = h * 0.76;

  // Fondo de zona SYNTROPY
  ctx.fillStyle = 'rgba(0, 242, 216, 0.06)';
  ctx.fillRect(bifX, 10, w - bifX - 10, h - 20);

  // Línea divisoria de bifurcación
  ctx.strokeStyle = 'rgba(0, 242, 216, 0.45)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(bifX, 8);
  ctx.lineTo(bifX, h - 8);
  ctx.stroke();
  ctx.setLineDash([]);

  // Curva de Caos (Ruido estocástico decreciente) -> Sintropía
  chaosAnimPhase += 0.05;
  ctx.beginPath();
  ctx.strokeStyle = '#ff3388';
  ctx.lineWidth = 1.8;

  const pts = 60;
  for (let i = 0; i <= pts; i++) {
    const x = 12 + (i / pts) * (w - 24);
    let y;
    if (x < bifX) {
      // Región de CHAOS: alta oscilación amortiguada
      const normX = x / bifX;
      const noise = (Math.sin(i * 1.8 + chaosAnimPhase) * 16 + Math.cos(i * 3.4) * 8) * (1 - normX * 0.7);
      y = (h * 0.25) + normX * (baseFloorY - (h * 0.25)) + noise;
    } else {
      // Región de SYNTROPY: piso estable y ordenado
      const normSyntropy = (x - bifX) / (w - bifX);
      const residual = Math.sin(i * 0.4 + chaosAnimPhase * 0.5) * 2.0 * Math.exp(-normSyntropy * 3.0);
      y = baseFloorY + residual;
    }
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Relleno bajo la curva de sintropía
  ctx.lineTo(w - 12, h - 8);
  ctx.lineTo(bifX, h - 8);
  ctx.fillStyle = 'rgba(0, 242, 216, 0.15)';
  ctx.fill();

  // Etiquetas CHAOS y SYNTROPY
  ctx.fillStyle = '#ff77bb';
  ctx.font = 'bold 10px monospace';
  ctx.fillText('CHAOS', bifX * 0.35, h - 14);
  ctx.fillStyle = '#00f2d8';
  ctx.fillText('SYNTROPY', bifX + (w - bifX) * 0.3, h - 14);
  ctx.fillText('∇S_ent', 16, 20);
}

// ================= 3. RENDER CUADRANTE 3: S_geom 3D HIPER-RETÍCULO =================
const geomCv = document.getElementById('geomCanvas'), geomCtx = geomCv.getContext('2d');
let geomRot = 0;

function renderGeomMesh() {
  const w = geomCv.width = geomCv.clientWidth;
  const h = geomCv.height = geomCv.clientHeight;
  const ctx = geomCtx;
  ctx.clearRect(0, 0, w, h);

  geomRot += 0.015;
  const cx = w / 2, cy = h / 2;
  const scale = Math.min(w, h) * 0.34;

  // Nodos 3D del retículo toroidal
  const nodes = [];
  const layers = 3;
  const rings = 6;

  for (let l = 0; l < layers; l++) {
    const z0 = (l - 1) * 0.6;
    const rL = 1.0 - Math.abs(z0) * 0.3;
    for (let r = 0; r < rings; r++) {
      const theta = (r / rings) * Math.PI * 2 + geomRot + (l * 0.4);
      const x = Math.cos(theta) * rL;
      const y = Math.sin(theta) * rL;
      // Proyección isométrica rotada
      const projX = cx + (x * Math.cos(geomRot * 0.5) - z0 * Math.sin(geomRot * 0.5)) * scale;
      const projY = cy + (y * 0.65 + z0 * 0.4) * scale;
      nodes.push({ x: projX, y: projY, z: z0 });
    }
  }

  // Dibujar enlaces
  ctx.strokeStyle = 'rgba(0, 242, 216, 0.35)';
  ctx.lineWidth = 1;
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dist = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
      if (dist < scale * 0.95) {
        ctx.beginPath();
        ctx.moveTo(nodes[i].x, nodes[i].y);
        ctx.lineTo(nodes[j].x, nodes[j].y);
        ctx.stroke();
      }
    }
  }

  // Dibujar nodos
  for (let n of nodes) {
    ctx.fillStyle = n.z > 0 ? '#00f2d8' : '#d55bff';
    ctx.shadowBlur = 6;
    ctx.shadowColor = ctx.fillStyle;
    ctx.beginPath();
    ctx.arc(n.x, n.y, 2.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

// ================= STREAM HEXADECIMAL & LAMPORT =================
function scrollHexMatrix() {
  const el = document.getElementById('hexStream');
  if (!el) return;
  const hexLines = [];
  for (let i = 0; i < 6; i++) {
    const seg1 = Math.floor(Math.random() * 9000 + 1000).toString(16).padStart(4, '0');
    const seg2 = Math.floor(Math.random() * 9000 + 1000).toString(16).padStart(4, '0');
    const seg3 = Math.floor(Math.random() * 90000 + 10000).toString(16).padStart(5, '0');
    const seg4 = geonState.lamport_clock;
    hexLines.push(`${seg1} ${seg2} ${seg3} ${seg4}`);
  }
  el.textContent = hexLines.join('\n');
}

// ================= LOOP DE ANIMACIÓN CRT PRINCIPAL =================
function crtAnimationLoop() {
  renderCone();
  renderChaosCurve();
  renderGeomMesh();
  requestAnimationFrame(crtAnimationLoop);
}
requestAnimationFrame(crtAnimationLoop);
setInterval(scrollHexMatrix, 400);

// ================= SINCRONIZACIÓN DE ESTADO CON EL BACKEND =================
async function syncGeonState() {
  try {
    const r = await fetch('/api/geon/state', { headers: h() });
    const d = await r.json();
    if (d.ok) {
      const f = d.formula_components || {};
      const c = d.controls || {};

      geonState.lamport_clock = d.lamport_clock || geonState.lamport_clock;
      document.getElementById('lamportDisplay').textContent = geonState.lamport_clock;
      
      const st = d.header ? d.header.status : (c.causal_lock ? 'LCKD' : 'UNLK');
      const stBadge = document.getElementById('hdrStatus');
      stBadge.textContent = st;
      stBadge.className = 'status-badge ' + (st === 'LCKD' ? '' : 'unlk');

      // Actualizar chips de valores
      if (f.psi_retro_t0) {
        document.getElementById('chipPsiMag').textContent = f.psi_retro_t0.magnitude.toFixed(4);
        document.getElementById('chipPsiPhase').textContent = f.psi_retro_t0.phase_rad.toFixed(4) + ' rad';
      }
      if (f.o_qco) document.getElementById('chipQco').textContent = f.o_qco.expectation_value.toFixed(4);
      if (f.s_geom) document.getElementById('chipSgeom').textContent = f.s_geom.action_value.toFixed(4) + ' rad';
      if (f.syntropy_modulation) {
        document.getElementById('chipSyntropy').textContent = f.syntropy_modulation.syntropy_factor.toFixed(4);
        const rLab = document.getElementById('regimeLabel');
        if (rLab) rLab.textContent = '∇S=' + f.syntropy_modulation.grad_s_ent.toFixed(3) + ' [' + f.syntropy_modulation.regime + ']';
      }

      // Actualizar switches físicos
      document.getElementById('btnTimeSync').className = 'hw-btn-light blue ' + (c.time_sync ? 'on' : '');
      document.getElementById('btnPhaseSync').className = 'hw-btn-light green ' + (c.phase_sync ? 'on' : '');
      document.getElementById('swCausalLock').className = 'metal-toggle-container ' + (c.causal_lock ? 'on' : '');
      document.getElementById('swSyntropyBoost').className = 'metal-toggle-container ' + (c.syntropy_boost ? 'on' : '');
    }
  } catch (e) {}
}

async function toggleHwControl(name) {
  try {
    const r = await fetch('/api/geon/toggle', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, h()),
      body: JSON.stringify({ control: name })
    });
    const d = await r.json();
    if (d.ok) {
      await syncGeonState();
    }
  } catch (e) {
    alert('Error al alternar control: ' + e.message);
  }
}

// ================= SIMULACIÓN EN TIEMPO REAL DEL CHAT TEMPORAL =================
function setSimPreset(text, direction) {
  document.getElementById('simPromptInp').value = text;
  triggerGeonSimulation(direction);
}

async function triggerGeonSimulation(directionOverride) {
  const inp = document.getElementById('simPromptInp');
  const prompt = inp.value.trim();
  if (!prompt) return;

  const btn = document.getElementById('btnRunSim');
  btn.disabled = true;
  btn.textContent = 'COLAPSANDO...';

  const logBox = document.getElementById('simLogBox');
  logBox.innerHTML = '<span class="highlight">[INICIANDO COLAPSO RETROCAUSAL]</span> Integrando cono de luz para: "' + prompt + '"...\n';

  try {
    const r = await fetch('/api/geon/simulate', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, h()),
      body: JSON.stringify({
        prompt: prompt,
        direction: directionOverride || 'future'
      })
    });
    const d = await r.json();

    if (d.ok) {
      const interp = d.interpretation || {};
      const fVals = d.formula_values || {};
      const trace = d.retrocausal_trace || [];

      let logText = `<span class="highlight">[RESULTADO DEL COLAPSO RETROCAUSAL · STATUS: ${d.status}]</span>\n`;
      logText += `◈ <b class="accent">Bifurcación:</b> ${interp.bifurcation}\n`;
      logText += `◈ <b class="accent">Coherencia Cuántica:</b> ${(interp.quantum_coherence * 100).toFixed(1)}%  |  |Ψ_Retro|: ${interp.retrocausal_wave_magnitude}\n`;
      logText += `◈ <b class="accent">Acoplamiento Sintrópico:</b> (1 - η∇S) = ${interp.syntropic_coupling}  |  ∇S_ent: ${interp.entropy_gradient_dSent}\n`;
      logText += `◈ <b class="accent">Confinamiento Geón:</b> ${interp.geon_confinement} (Q_topo=${interp.topological_charge}, R_geom=${interp.curvature_scalar_R})\n`;
      logText += `◈ <b class="accent">Reloj Lamport:</b> ${d.lamport_clock}\n\n`;
      logText += `<span class="highlight">SÍNTESIS DE LA ACTUACIÓN DEL GEÓN:</span>\n${interp.summary}\n\n`;

      if (trace.length > 0) {
        logText += `<span class="subtext">--- TRAZA RETROCAUSAL PASO A PASO (t_final → t0) ---\n`;
        trace.forEach(st => {
          logText += `[Paso ${st.step}] t=${st.t} | Φ_adv=${st.phi_adv_mag} | Integrando=(${st.integrand_real}, ${st.integrand_imag}j) | |Ψ|=${st.accum_magnitude} ∠${st.accum_phase_deg}°\n`;
        });
        logText += `---------------------------------------------------</span>`;
      }

      logBox.innerHTML = logText;
      logBox.scrollTop = logBox.scrollHeight;
      await syncGeonState();
    } else {
      logBox.innerHTML += '<span style="color:var(--neon-red)">Error: ' + (d.error || 'fallo en simulación') + '</span>\n';
    }
  } catch (e) {
    logBox.innerHTML += '<span style="color:var(--neon-red)">Error de red: ' + e.message + '</span>\n';
  } finally {
    btn.disabled = false;
    btn.textContent = 'COLAPSAR ONDA';
  }
}

syncGeonState();
setInterval(syncGeonState, 2000);
</script>
</body>
</html>"""


MONITOR_PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>GIA - Monitor</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#00d4c8">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="GIA">
<link rel="apple-touch-icon" href="/icon-180.png">
<style>
  :root { --bg:#0a0e14; --panel:#111823; --teal:#00d4c8; --gold:#e8b64a;
          --txt:#d6e0ea; --dim:#5f6b7a; --red:#e5484d; --grn:#30d158; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt); font-family:
         -apple-system,Segoe UI,Roboto,sans-serif; padding:14px; }
  header { display:flex; align-items:center; gap:10px; margin-bottom:14px; }
  .sig { width:22px; height:22px; border:2px solid var(--teal);
         transform:rotate(45deg); border-radius:4px; }
  h1 { font-size:15px; margin:0; letter-spacing:2px; color:var(--teal); }
  a.back { margin-left:auto; color:var(--dim); font-size:13px; text-decoration:none; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:10px; }
  .card { background:var(--panel); border:1px solid #1c2836; border-radius:12px;
          padding:12px; }
  .card h2 { font-size:11px; color:var(--dim); margin:0 0 8px; letter-spacing:1px;
             text-transform:uppercase; }
  .big { font-size:26px; font-weight:700; }
  .unit { font-size:12px; color:var(--dim); }
  .bar { height:6px; background:#1c2836; border-radius:4px; margin-top:8px;
         overflow:hidden; }
  .bar > i { display:block; height:100%; background:var(--teal); }
  .bar.hot > i { background:var(--red); }
  .row { display:flex; justify-content:space-between; font-size:13px;
         padding:3px 0; border-bottom:1px solid #16202e; }
  .row:last-child { border:0; }
  .mut { color:var(--dim); }
  .wide { grid-column:1/-1; }
  .pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px;
          background:#16202e; color:var(--dim); }
  .pill.ok { color:var(--grn); } .pill.no { color:var(--red); }
  #ts { color:var(--dim); font-size:11px; }
</style>
</head>
<body>
<header>
  <div class="sig"></div>
  <h1>GIA MONITOR</h1>
  <a class="back" id="chatlink">chat &rarr;</a>
</header>
<div class="grid" id="grid"><div class="card wide mut">Cargando...</div></div>
<div class="card" style="margin-top:12px">
  <h2 style="color:var(--gold)">Contexto agéntico del sistema</h2>
  <p class="mut" style="font-size:11px;margin:2px 0 8px">Cómo opera el modelo en todas las variantes. Se auto-versiona (reversible).</p>
  <textarea id="cxt" rows="6" style="width:100%;background:#0d1420;color:var(--txt);border:1px solid #24344a;border-radius:8px;padding:9px;font-size:13px;font-family:inherit;resize:vertical"></textarea>
  <div style="display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap">
    <label class="mut" style="font-size:12px"><input type="checkbox" id="cxAuto"> auto-mejora</label>
    <div style="flex:1"></div>
    <button id="cxSave" style="background:var(--teal);color:#04141a;border:none;border-radius:8px;padding:7px 14px;font-weight:700;cursor:pointer">Guardar</button>
    <button id="cxImprove" style="background:var(--gold);color:#04141a;border:none;border-radius:8px;padding:7px 14px;font-weight:700;cursor:pointer">Mejorar con IA</button>
    <button id="cxRevert" style="background:#26313f;color:var(--txt);border:none;border-radius:8px;padding:7px 14px;cursor:pointer">Revertir</button>
  </div>
  <div id="cxStat" class="mut" style="font-size:11px;margin-top:6px"></div>
</div>
<p id="ts"></p>
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
document.getElementById('chatlink').href = '/?key=' + encodeURIComponent(KEY);
function h(){ return KEY ? {'X-GIA-Key':KEY} : {}; }
function bar(pct, hot){ return `<div class="bar${hot?' hot':''}"><i style="width:${Math.min(100,pct||0)}%"></i></div>`; }
function card(title, body, wide){ return `<div class="card${wide?' wide':''}"><h2>${title}</h2>${body}</div>`; }

async function tick(){
  let d;
  try { d = await (await fetch('/api/monitor?key='+encodeURIComponent(KEY),{headers:h()})).json(); }
  catch(e){ document.getElementById('grid').innerHTML = card('Error','Sin conexion con el servidor',true); return; }
  if(!d.ok){ document.getElementById('grid').innerHTML = card('Error', d.error||'no autorizado', true); return; }
  const g = d.gpu||{}; let cards='';

  if(g.temp!==undefined){
    const hot = g.temp>=80;
    cards += card('GPU '+(g.name||''),
      `<div class="big">${g.temp}<span class="unit">&deg;C</span></div>`+
      `<div class="mut">uso ${g.util}%  ·  VRAM ${Math.round(g.vram_used)}/${Math.round(g.vram_total)} MB</div>`+
      bar(g.vram_total?100*g.vram_used/g.vram_total:0, hot));
  }
  if(d.cpu!==undefined)
    cards += card('CPU', `<div class="big">${Math.round(d.cpu)}<span class="unit">%</span></div>`+bar(d.cpu));
  if(d.ram_pct!==undefined)
    cards += card('RAM', `<div class="big">${d.ram_pct}<span class="unit">%</span></div>`+
      `<div class="mut">${d.ram_used_gb}/${d.ram_total_gb} GB</div>`+bar(d.ram_pct, d.ram_pct>90));
  if(d.battery!==undefined)
    cards += card('Bateria', `<div class="big">${Math.round(d.battery)}<span class="unit">%</span></div>`+
      `<div class="mut">${d.plugged?'enchufado':'bateria'}</div>`);

  if(d.loaded_models){
    let b = d.loaded_models.length ? d.loaded_models.map(m=>`<div class="row"><span>${m.name}</span><span class="mut">${m.gb} GB</span></div>`).join('') : '<div class="mut">ninguno cargado</div>';
    cards += card('Modelos en memoria', b);
  }
  if(d.nodes){
    let b = d.nodes.map(n=>`<div class="row"><span>${n.name} <span class="pill ${n.ok?'ok':'no'}">${n.ok?n.latency_ms+'ms':'down'}</span></span><span class="mut">${n.models} mod</span></div>`).join('');
    cards += card('Nodos de computo', b||'<div class="mut">solo local</div>');
  }
  if(d.memory){
    cards += card('Historial maestro',
      `<div class="row"><span>Eventos</span><span>${d.memory.events||0}</span></div>`+
      `<div class="row"><span>Tareas exito</span><span>${d.memory.successes||0}</span></div>`+
      `<div class="row"><span>Tamano BD</span><span class="mut">${d.memory.db_mb||0} MB</span></div>`);
  }
  if(d.memory && d.memory.top_demand && d.memory.top_demand.length){
    let b = d.memory.top_demand.map(t=>`<div class="row"><span>${t.key}</span><span class="mut">${t.count}</span></div>`).join('');
    cards += card('Mas demandado', b);
  }
  if(d.top_procs){
    let b = d.top_procs.map(p=>`<div class="row"><span>${p.name}</span><span class="mut">${p.gb} GB</span></div>`).join('');
    cards += card('Procesos (RAM)', b, false);
  }
  if(d.ios){
    cards += card('iPhone', `<div class="big">${d.ios.devices}</div><div class="mut">conectado(s)</div>`);
  }
  document.getElementById('grid').innerHTML = cards || card('Sin datos','psutil/nvidia-smi no disponibles',true);
  document.getElementById('ts').textContent = 'Actualizado ' + new Date().toLocaleTimeString();
}
tick(); setInterval(tick, 4000);

// ---- Editor de contexto agentico (mismo en todos los puntos de entrada) ----
async function ctxLoad(){
  try{ const j = await (await fetch('/api/context?key='+encodeURIComponent(KEY),{headers:h()})).json();
    if(j.ok){ document.getElementById('cxt').value=j.directives||'';
      document.getElementById('cxAuto').checked=!!j.auto_improve;
      document.getElementById('cxStat').textContent='v'+(j.version||0)+' · '+(j.last_source||'user')+' · '+(j.updated_iso||''); }
  }catch(e){}
}
async function ctxPost(body){
  const r = await fetch('/api/context',{method:'POST',
    headers:Object.assign({'Content-Type':'application/json'},h()), body:JSON.stringify(body)});
  return r.json();
}
document.getElementById('cxSave').onclick=async()=>{
  document.getElementById('cxStat').textContent='Guardando...';
  const j=await ctxPost({directives:document.getElementById('cxt').value, enabled:true});
  await ctxPost({action:'auto', enabled:document.getElementById('cxAuto').checked});
  document.getElementById('cxStat').textContent=j.ok?'Guardado. Activo en todo el sistema.':'Error';
};
document.getElementById('cxImprove').onclick=async()=>{
  document.getElementById('cxStat').textContent='El modelo propone una mejora (~30s)...';
  const j=await ctxPost({action:'improve', apply:false});
  if(j.ok){ document.getElementById('cxt').value=j.proposal; document.getElementById('cxStat').textContent='Propuesta: '+(j.cambios||'')+' (revisa y Guarda)'; }
  else document.getElementById('cxStat').textContent='Auto-mejora fallo: '+(j.error||'');
};
document.getElementById('cxRevert').onclick=async()=>{
  const j=await ctxPost({action:'revert'}); await ctxLoad();
  document.getElementById('cxStat').textContent='Revertido a version anterior.';
};
ctxLoad();
</script>
</body>
</html>"""


# =====================================================================
#  Arranque
# =====================================================================

def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("REDACTED_IP", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "REDACTED_IP"


def main() -> int:
    ap = argparse.ArgumentParser(description="Servidor web GIA")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8757)))
    # Por defecto, el modelo GENERAL (adopta la matriz de contexto).
    # Sobrescribible: --model qwen2.5-coder:7b para tareas de codigo.
    ap.add_argument("--model", default=CFG["model"])
    ap.add_argument("--lan", action="store_true", help="accesible desde la red/celular")
    ap.add_argument("--no-auth", action="store_true", help="sin token (solo LAN de confianza)")
    ap.add_argument("--token", default=os.environ.get("GIA_AUTH_TOKEN", ""), help="token de acceso fijo para el puente/tunel")
    args = ap.parse_args()

    CFG["model"] = args.model
    # Auto-bootstrap autónomo: garantiza que Ollama y dependencias estén activos sin depender de lanzador externo
    try:
        import gia_bootstrap
        boot = gia_bootstrap.ensure_all_dependencies(preferred_model=args.model, verbose=False)
        if boot.get("active_model"):
            CFG["model"] = boot["active_model"]
    except Exception as e_boot:
        print(f"[GIA-WEB] Auto-bootstrap: {e_boot}")

    CFG["auth"] = not args.no_auth
    if CFG["auth"]:
        CFG["token"] = args.token if args.token else secrets.token_urlsafe(12)

    host = "REDACTED_IP" if args.lan else "REDACTED_IP"
    ip = lan_ip() if args.lan else "REDACTED_IP"
    base = f"http://{ip}:{args.port}"
    url = base + (f"/?key={CFG['token']}" if CFG["auth"] else "/")

    C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; D = "\033[90m"; E = "\033[0m"
    os.system("")
    print(f"\n{C}================================================={E}")
    print(f"{C}  GIA - INTERFAZ WEB{E}")
    print(f"{C}  Modelo: {args.model}{E}")
    print(f"{G}  Abre en tu navegador (o celular):{E}")
    print(f"{G}    {url}{E}")
    if args.lan:
        print(f"{Y}  Modo LAN: accesible desde la misma WiFi.{E}")
        print(f"{D}  Para internet fuera de casa: monta un tunel al puerto {args.port}")
        print(f"    (ej: cloudflared tunnel --url http://localhost:{args.port}){E}")
    if CFG["auth"]:
        print(f"{D}  Token de acceso: {CFG['token']}{E}")
    else:
        print(f"{Y}  SIN token (--no-auth): cualquiera en la red puede entrar.{E}")
    print(f"{C}================================================={E}\n")

    app.run(host=host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
