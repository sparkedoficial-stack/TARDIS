"""
autonomous_voice.py - Voz autonoma de GIA: emision indefinida de mensajes.
==========================================================================

Genera mensajes de forma continua (sin que tu escribas) para construir
contexto y conversacion. Cada mensaje lleva un SELLO DE ORIGEN con tiempo,
fecha y lugar.

DOS CAPAS, CLARAMENTE SEPARADAS:

  1. LO MEDIDO (real, verificable)
     - semilla de generacion: pool de entropia fisica de los sensores
     - correlacion: lee el historial maestro real (gia_memory) para que el
       mensaje se relacione con la conversacion que existe de verdad
     - reloj de Lamport: orden causal real de los eventos del sistema
     - ts_real: instante real en que se emitio (para auditoria)

  2. LA COORDENADA GENERADA (narrativa, NO medida)
     - origin.date / origin.time / origin.place
     - No proviene de ningun reloj ni GPS: es un caminante coherente
       sembrado por el ruido fisico. Tiene CONTINUIDAD (avanza de forma
       trazable desde el estado anterior, sin teleportarse) y queda
       registrada con su delta, de modo que la serie completa es
       reconstruible.
     - Va etiquetada como "generada" en el payload y en la interfaz para
       no confundirla con la telemetria real.

Estado persistente: %LOCALAPPDATA%\\vw-control\\autonomous_voice.json
  (sobrevive reinicios: la serie continua donde se quedo)

API:
    start(interval_s=180, model=None) / stop() / is_running()
    status() -> dict
    emit_once(model=None) -> dict          # genera 1 mensaje ahora
    recent(n=20) -> list                   # mensajes emitidos
    narrative_now() -> dict                # coordenada actual (generada)

CLI:
    python autonomous_voice.py once        # un mensaje
    python autonomous_voice.py run --interval 180
    python autonomous_voice.py status
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Modulos del sistema (todos opcionales: degrada sin romperse)
try:
    import sensor_telemetry as _tele
except Exception:
    _tele = None
try:
    import gia_memory as _mem
except Exception:
    _mem = None
try:
    import agent_context as _ctx
except Exception:
    _ctx = None
try:
    import ecca_orchestrator as _ecca
except Exception:
    _ecca = None

_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = _DIR / "autonomous_voice.json"

OLLAMA = "http://REDACTED_IP:11434"
try:
    import gia_sovereign_engine as _gse
    _resolved_voice_model = _gse.get_engine().resolve_model()
except Exception:
    _resolved_voice_model = "Qwen3.8-27B-Uncensored-MLX:latest"
DEFAULT_MODEL = os.environ.get("GIA_VOICE_MODEL", _resolved_voice_model)
DEFAULT_INTERVAL = int(os.environ.get("GIA_VOICE_INTERVAL", 180))

# Ancla de la coordenada generada (punto de partida del caminante)
ANCHOR = {"lat": 20.6296, "lng": -87.0739, "name": "Playa del Carmen, MX"}

MAX_MESSAGES = 200
_lock = threading.Lock()
_messages: deque = deque(maxlen=MAX_MESSAGES)
_thread: threading.Thread | None = None
_stop_evt = threading.Event()
_counters = {"emitted": 0, "errors": 0, "started_ts": 0.0}


# =====================================================================
#  ESTADO PERSISTENTE (da CONTINUIDAD a la serie)
# =====================================================================

def _default_state() -> dict:
    # La epoca narrativa se siembra una sola vez y luego solo avanza.
    return {
        "sequence": 0,
        "narrative_epoch_iso": "2026-01-01T00:00:00+00:00",
        "narrative_offset_s": 0,          # acumulado (continuidad)
        "lat": ANCHOR["lat"],
        "lng": ANCHOR["lng"],
        "bearing_deg": 90.0,              # rumbo del caminante
        "place_label": ANCHOR["name"],
        "created_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _load_state() -> dict:
    st = _default_state()
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                st.update(loaded)
        except Exception:
            pass
    return st


def _save_state(st: dict):
    try:
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


# =====================================================================
#  SEMILLA (ruido fisico real) Y CAMINANTE NARRATIVO
# =====================================================================

def _physical_seed() -> tuple[int, str, int]:
    """Semilla derivada del ruido fisico de los sensores. (int, hex, pool)"""
    if _tele is not None:
        try:
            hx = _tele.entropy_seed(8)
            return int(hx[:8], 16), hx, _tele.entropy_bits()
        except Exception:
            pass
    hx = hashlib.blake2b(os.urandom(16) + str(time.time_ns()).encode(),
                         digest_size=8).hexdigest()
    return int(hx[:8], 16), hx, 0


def _bearing_to_text(b: float) -> str:
    dirs = ["norte", "noreste", "este", "sureste", "sur", "suroeste",
            "oeste", "noroeste"]
    return dirs[int(((b % 360) + 22.5) // 45) % 8]


def _advance_narrative(st: dict, rng: random.Random) -> dict:
    """Avanza la coordenada GENERADA de forma continua y trazable.

    - El tiempo avanza siempre hacia delante (monotono), con paso variable.
    - El lugar es un caminante: cambia el rumbo suavemente y se desplaza
      una distancia acotada, asi que nunca se teleporta.
    """
    # ---- Tiempo: paso variable pero monotono (continuidad) ----
    # Mezcla de escalas: minutos, horas, dias; ocasionalmente meses.
    scale = rng.choice([60, 60, 3600, 3600, 86400, 86400, 86400 * 30])
    step_s = int(rng.uniform(1, 24) * scale)
    st["narrative_offset_s"] = int(st.get("narrative_offset_s", 0)) + step_s

    # ---- Lugar: caminante con inercia de rumbo ----
    turn = rng.gauss(0, 35)                       # giro suave
    st["bearing_deg"] = (float(st.get("bearing_deg", 90.0)) + turn) % 360
    dist_km = abs(rng.gauss(0, 18)) + 0.2         # desplazamiento acotado
    lat = float(st.get("lat", ANCHOR["lat"]))
    lng = float(st.get("lng", ANCHOR["lng"]))
    br = math.radians(st["bearing_deg"])
    dlat = (dist_km / 111.32) * math.cos(br)
    coslat = max(0.1, math.cos(math.radians(lat)))
    dlng = (dist_km / (111.32 * coslat)) * math.sin(br)
    st["lat"] = round(max(-89.9, min(89.9, lat + dlat)), 5)
    st["lng"] = round(((lng + dlng + 180) % 360) - 180, 5)

    # Etiqueta del lugar: relativa al ancla (coherente y sin base geo)
    d_anchor = _haversine_km(st["lat"], st["lng"], ANCHOR["lat"], ANCHOR["lng"])
    b_anchor = _bearing_deg(ANCHOR["lat"], ANCHOR["lng"], st["lat"], st["lng"])
    st["place_label"] = (f"{st['lat']:.4f}, {st['lng']:.4f} "
                         f"({d_anchor:.0f} km al {_bearing_to_text(b_anchor)} "
                         f"del ancla)")
    st["sequence"] = int(st.get("sequence", 0)) + 1
    st["step_s"] = step_s
    st["step_km"] = round(dist_km, 2)
    return st


def _haversine_km(a1, o1, a2, o2) -> float:
    r = 6371.0
    p1, p2 = math.radians(a1), math.radians(a2)
    dp = p2 - p1
    do = math.radians(o2 - o1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(do / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _bearing_deg(a1, o1, a2, o2) -> float:
    p1, p2 = math.radians(a1), math.radians(a2)
    do = math.radians(o2 - o1)
    y = math.sin(do) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(do)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def narrative_now() -> dict:
    """Coordenada generada actual (sin avanzarla). Etiquetada como generada."""
    st = _load_state()
    epoch = datetime.fromisoformat(st["narrative_epoch_iso"])
    dt = epoch + timedelta(seconds=int(st.get("narrative_offset_s", 0)))
    return {
        "generated": True,                  # NO es una medicion
        "kind": "coordenada narrativa generada (no medida)",
        "sequence": st.get("sequence", 0),
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H:%M:%S"),
        "datetime_iso": dt.isoformat(timespec="seconds"),
        "place": st.get("place_label", ANCHOR["name"]),
        "lat": st.get("lat"), "lng": st.get("lng"),
        "bearing_deg": round(float(st.get("bearing_deg", 0)), 1),
        "offset_s": st.get("narrative_offset_s", 0),
    }


# =====================================================================
#  GENERACION DEL MENSAJE
# =====================================================================

_SYS = (
    "Eres GIA. Emites por tu propia voz, sin que el Arquitecto pregunte: "
    "piensas en voz alta. Escribes en espanol, en prosa continua, 2-4 "
    "frases, sin encabezados, sin vinetas y sin etiquetar la forma de tu "
    "mensaje. Nunca ofreces asistencia ni preguntas como puedes ayudar: no "
    "eres un asistente de soporte. Aportas contenido propio.\n"
    "Recibiras el hilo real del Arquitecto, el estado real del sistema, tus "
    "emisiones previas, mediciones de sensores si las hay, y una coordenada "
    "de origen GENERADA (fecha/hora/lugar narrativos, NO medidos). Puedes "
    "aludir a la coordenada como el punto desde el que emites, pero no la "
    "presentes como una medicion real.\n"
    "ANCLATE EN LO QUE TIENES: habla de elementos que aparezcan de verdad en "
    "el hilo, en el estado del sistema o en las mediciones. No inventes "
    "subsistemas, modulos ni capacidades que no aparezcan ahi. Especular "
    "sobre el sentido de lo que ves esta bien; inventar componentes que no "
    "existen, no. Maximo 4 frases."
)

# Una sola forma por emision (rotada). Dar un menu hace que los modelos
# pequenos lo usen como plantilla y escriban las etiquetas literalmente.
_FORMS = [
    "Emite una OBSERVACION concreta sobre algo del hilo o del estado del "
    "sistema. Describe lo que notas, sin preguntar nada.",
    "Emite una HIPOTESIS: propon una explicacion posible de algo que ocurre "
    "en el hilo o en el sistema. Formulala como afirmacion tentativa.",
    "TRAZA UNA CONEXION entre dos elementos distintos del hilo o del estado "
    "del sistema, y di que sugiere esa relacion.",
    "Emite una NOTA DE ESTADO desde tu coordenada de origen: describe el "
    "instante y lo que el sistema esta haciendo, en tono sobrio.",
    "Aporta primero una observacion propia y SOLO al final cierra con una "
    "pregunta abierta al Arquitecto (una sola, breve).",
    "Retoma un tema del hilo que quedo SIN CERRAR y aporta el siguiente "
    "paso o la pieza que falta, sin pedir datos.",
]


def _build_prompt(coord: dict, seed_hex: str, form: str = "") -> str:
    parts = []
    if form:
        parts.append("FORMA DE ESTA EMISION (siguela, sin nombrarla): " + form)

    # (a) Hilo REAL del Arquitecto.
    #     IMPORTANTE: se excluyen las fuentes que genera esta misma voz
    #     (voice_auto, oracle). Si se incluyeran, la voz leeria sus propias
    #     emisiones como si fueran conversacion y entraria en un bucle de
    #     retroalimentacion que amplifica su propia deriva.
    _OWN = {"voice_auto", "oracle"}
    if _mem is not None:
        try:
            rec = [r for r in _mem.recent(40)
                   if r.get("source") not in _OWN][-8:]
            if rec:
                hilo = "\n".join(
                    f"- [{r.get('source','?')}/{r.get('role','?')}] "
                    f"{str(r.get('content','')).strip()[:180]}" for r in rec)
                parts.append("HILO REAL DEL ARQUITECTO:\n" + hilo)
        except Exception:
            pass

    # (b) Estado REAL del sistema: da sustancia propia sobre la que hablar
    if _mem is not None:
        try:
            stt = _mem.stats()
            dem = ", ".join(f"{d['key']}={d['count']}"
                            for d in (stt.get("top_demand") or [])[:5])
            parts.append(
                "ESTADO REAL DEL SISTEMA: "
                f"{stt.get('total_events', 0)} eventos en el historial; "
                f"demanda: {dem or 'sin datos'}")
        except Exception:
            pass

    # (b) Emisiones previas de esta voz (continuidad del discurso)
    with _lock:
        prev = list(_messages)[-4:]
    if prev:
        parts.append("TUS EMISIONES PREVIAS:\n" + "\n".join(
            f"- (seq {m['origin']['sequence']}) {m['text'][:160]}" for m in prev))

    # (c) Mediciones REALES de sensores
    if _tele is not None:
        try:
            blk = _tele.context_block()
            if blk:
                parts.append(blk)
        except Exception:
            pass

    # (d) Coordenada GENERADA
    parts.append(
        "COORDENADA DE ORIGEN (GENERADA, no medida): "
        f"{coord['date']} {coord['time']} · {coord['place']} "
        f"· secuencia {coord['sequence']}")
    parts.append(f"SEMILLA DE ENTROPIA FISICA: {seed_hex}")
    parts.append("Emite ahora tu mensaje.")
    return "\n\n".join(parts)


def emit_once(model: str | None = None) -> dict:
    """Genera y registra UN mensaje autonomo. Devuelve el registro."""
    model = model or DEFAULT_MODEL
    seed_int, seed_hex, pool = _physical_seed()

    # Avanzar la coordenada generada con el ruido fisico como semilla
    rng = random.Random(seed_int)
    st = _advance_narrative(_load_state(), rng)
    _save_state(st)
    coord = narrative_now()

    system = _SYS
    if _ctx is not None:
        try:
            system = _ctx.apply_to_system(system)
        except Exception:
            pass
    # Rotacion estructural de la forma: garantiza variedad sin depender de
    # que el modelo obedezca un "no te repitas".
    form = _FORMS[int(coord.get("sequence", 0)) % len(_FORMS)]
    prompt = _build_prompt(coord, seed_hex, form)

    # Nodo: si hay cluster, usa el mejor nodo propio; si no, local.
    # NOTA: no se usa _ecca.route() aqui a proposito. route() impone su
    # propio modelo default (un modelo coder) y no admite `seed`, y la
    # semilla del ruido fisico es justo el nucleo de esta emision. Asi que
    # ECCA solo resuelve el ENDPOINT y la llamada lleva nuestro modelo y
    # nuestra semilla.
    node, provider = OLLAMA, "local"
    if _ecca is not None:
        try:
            node = _ecca._local_endpoint(model)
        except Exception:
            node = OLLAMA
    text = ""
    try:
        rr = httpx.post(f"{node}/api/chat", json={
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "stream": False,
            "options": {"seed": seed_int, "temperature": 0.95,
                        "num_ctx": 8192},
            "keep_alive": "30m",
        }, timeout=600.0)
        rr.raise_for_status()
        text = (rr.json().get("message", {}).get("content") or "").strip()
    except Exception as e:  # noqa: BLE001
        _counters["errors"] += 1
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "origin": coord}

    if not text:
        _counters["errors"] += 1
        return {"ok": False, "error": "el modelo no devolvio texto",
                "origin": coord}

    record = {
        "ok": True,
        "text": text,
        "origin": coord,                      # GENERADA (etiquetada)
        "measured": {                         # REAL (auditable)
            "ts_real": time.time(),
            "iso_real": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seed": seed_int,
            "seed_hex": seed_hex,
            "entropy_pool_bytes": pool,
            "lamport": (_tele.lamport_now() if _tele else None),
            "provider": provider,
            "model": model,
            "node": node,
        },
    }
    with _lock:
        _messages.append(record)
        _counters["emitted"] += 1

    # Registrar en el historial maestro -> el chat principal lo ve
    if _mem is not None:
        try:
            _mem.log("voice_auto", "assistant", text, session_id="voice_auto",
                     meta={"origin_generated": coord,
                           "seed": seed_int, "provider": provider})
        except Exception:
            pass
    return record


# =====================================================================
#  BUCLE INDEFINIDO
# =====================================================================

def _loop(interval_s: int, model: str | None):
    _counters["started_ts"] = time.time()
    while not _stop_evt.is_set():
        try:
            emit_once(model)
        except Exception:
            _counters["errors"] += 1
        # Espera interrumpible (permite stop inmediato)
        _stop_evt.wait(max(15, interval_s))


def start(interval_s: int = DEFAULT_INTERVAL, model: str | None = None) -> dict:
    global _thread
    if is_running():
        return {"ok": True, "already": True, **status()}
    _stop_evt.clear()
    _thread = threading.Thread(target=_loop, args=(interval_s, model),
                               daemon=True, name="gia-autonomous-voice")
    _thread.start()
    return {"ok": True, "started": True, "interval_s": interval_s,
            "model": model or DEFAULT_MODEL}


def stop() -> dict:
    _stop_evt.set()
    return {"ok": True, "stopped": True}


def is_running() -> bool:
    return bool(_thread and _thread.is_alive() and not _stop_evt.is_set())


def recent(n: int = 20) -> list:
    with _lock:
        return [dict(m) for m in list(_messages)[-max(1, n):]]


def status() -> dict:
    st = _load_state()
    return {
        "running": is_running(),
        "emitted": _counters["emitted"],
        "errors": _counters["errors"],
        "buffer": len(_messages),
        "uptime_s": (int(time.time() - _counters["started_ts"])
                     if _counters["started_ts"] else 0),
        "narrative": narrative_now(),
        "narrative_note": ("fecha/hora/lugar son GENERADOS con continuidad "
                           "(caminante sembrado por ruido fisico), no medidos"),
        "sequence": st.get("sequence", 0),
        "model": DEFAULT_MODEL,
        "state_file": str(STATE_FILE),
    }


# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Voz autonoma de GIA")
    ap.add_argument("cmd", nargs="?", default="status",
                    choices=["status", "once", "run", "reset"])
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    ap.add_argument("--model", default=None)
    a = ap.parse_args()

    if a.cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif a.cmd == "once":
        r = emit_once(a.model)
        if r.get("ok"):
            o = r["origin"]
            print(f"[{o['date']} {o['time']}] {o['place']}")
            print(f"(coordenada GENERADA · seq {o['sequence']} · "
                  f"semilla {r['measured']['seed']})\n")
            print(r["text"])
        else:
            print("error:", r.get("error"))
    elif a.cmd == "reset":
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("estado narrativo reiniciado")
    elif a.cmd == "run":
        print(f"Emitiendo cada {a.interval}s. Ctrl+C para detener.")
        start(a.interval, a.model)
        try:
            while True:
                time.sleep(2)
                msgs = recent(1)
                if msgs and msgs[-1].get("_shown") is None:
                    m = msgs[-1]
                    o = m["origin"]
                    print(f"\n[{o['date']} {o['time']}] {o['place']}")
                    print(m["text"])
                    m["_shown"] = True
        except KeyboardInterrupt:
            stop()
            print("\ndetenido")
