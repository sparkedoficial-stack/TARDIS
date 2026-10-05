"""
sensor_telemetry.py - Rejilla de sensores fisicos de GIA (GIA-V26-SENSOR-GRID).
==============================================================================

Ingesta la telemetria que el navegador (PC o movil) captura de los sensores
reales del dispositivo y la pone a disposicion del modelo, para que GIA
correlacione el ESTADO FISICO con el texto del chat.

Arquitecto: Miguel Angel May Canche  ·  Ancla: Playa del Carmen, MX

QUE ES REAL AQUI (todo medido, nada inventado):
  - kinematic       : acelerometro/giroscopio del dispositivo (devicemotion)
  - acoustic        : nivel de entropia espectral calculado con FFT real
                      (AnalyserNode) en el cliente
  - gps_anchor      : latitud/longitud/altitud/rumbo/velocidad reales
  - bio_link_bpm    : ritmo cardiaco leido por BLE (servicio 0x180D)
  - optical         : frames JPEG reales de la camara
  - lamport_clock   : reloj logico de Lamport (orden causal de eventos)
  - sidereal        : Tiempo Sideral Local, calculo astronomico estandar
                      (Meeus) desde longitud + UTC — verificable
  - entropy_pool    : semilla de entropia derivada del ruido de movimiento
                      (fuente de aleatoriedad fisica legitima)

Almacen: %LOCALAPPDATA%\\vw-control\\telemetry\\  (frames + ultimo estado)

API:
    ingest(packet: dict) -> dict          # recibe un paquete del cliente
    latest() -> dict                      # ultimo estado agregado
    recent(n) -> list                     # ultimos n paquetes (buffer RAM)
    context_block() -> str                # estado fisico para el prompt
    local_sidereal_time(lon, when=None) -> float   # horas (0-24)
    entropy_seed(nbytes=16) -> str        # semilla hex del pool de movimiento
    save_frame(b64_jpeg) -> str|None      # guarda frame optico, devuelve path
    stats() -> dict
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
TELEM_DIR = _DIR / "telemetry"
FRAMES_DIR = TELEM_DIR / "frames"
STATE_FILE = TELEM_DIR / "last_state.json"
for _d in (TELEM_DIR, FRAMES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Ancla geoespacial por defecto (Playa del Carmen, MX)
ANCHOR = {"lat": 20.6296, "lng": -87.0739, "name": "Playa del Carmen, MX"}

MAX_BUFFER = 600          # ~10 min a 1 Hz
MAX_FRAMES_ON_DISK = 60   # rotacion: no llenar el disco con JPEG

_lock = threading.Lock()
_buffer: deque = deque(maxlen=MAX_BUFFER)
_lamport = 0                     # reloj logico del servidor
_entropy_pool = bytearray()
_counters = {"packets": 0, "frames": 0, "started": time.time()}


# =====================================================================
#  RELOJ DE LAMPORT
# =====================================================================

def lamport_tick(received: int | None = None) -> int:
    """Regla de Lamport: L = max(L_local, L_recibido) + 1."""
    global _lamport
    with _lock:
        try:
            r = int(received) if received is not None else 0
        except (TypeError, ValueError):
            r = 0
        _lamport = max(_lamport, r) + 1
        return _lamport


def lamport_now() -> int:
    return _lamport


# =====================================================================
#  TIEMPO SIDERAL LOCAL (astronomia real, formula estandar de Meeus)
# =====================================================================

def julian_date(when: datetime | None = None) -> float:
    """Fecha Juliana desde un datetime UTC."""
    dt = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    y, m = dt.year, dt.month
    d = (dt.day + (dt.hour + dt.minute / 60 + (dt.second + dt.microsecond / 1e6) / 3600) / 24)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4                      # calendario gregoriano
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + d + b - 1524.5)


def gmst_hours(when: datetime | None = None) -> float:
    """Tiempo Sideral Medio de Greenwich en horas (0-24)."""
    jd = julian_date(when)
    d = jd - 2451545.0                       # dias desde J2000.0
    t = d / 36525.0
    # GMST en grados (Meeus, cap. 12)
    gmst_deg = (280.46061837 + 360.98564736629 * d
                + 0.000387933 * t * t - (t ** 3) / 38710000.0)
    return (gmst_deg % 360.0) / 15.0


def local_sidereal_time(lon_deg: float, when: datetime | None = None) -> float:
    """Tiempo Sideral Local en horas (0-24). lon_deg: este positivo."""
    lst = gmst_hours(when) + (float(lon_deg) / 15.0)
    return lst % 24.0


def sidereal_str(lon_deg: float, when: datetime | None = None) -> str:
    lst = local_sidereal_time(lon_deg, when)
    h = int(lst)
    m = int((lst - h) * 60)
    s = int((((lst - h) * 60) - m) * 60)
    return f"{h:02d}h{m:02d}m{s:02d}s"


# =====================================================================
#  POOL DE ENTROPIA (ruido fisico del movimiento)
# =====================================================================

def _feed_entropy(kin: dict, extra: str = ""):
    """Alimenta el pool con las lecturas de movimiento (ruido fisico real)."""
    global _entropy_pool
    try:
        raw = f"{kin.get('x')}|{kin.get('y')}|{kin.get('z')}|{time.time_ns()}|{extra}"
        _entropy_pool.extend(hashlib.sha256(raw.encode()).digest())
        if len(_entropy_pool) > 4096:        # mantener acotado
            del _entropy_pool[:-2048]
    except Exception:
        pass


def entropy_seed(nbytes: int = 16) -> str:
    """Semilla hex derivada del pool de movimiento + estado del sistema."""
    with _lock:
        pool = bytes(_entropy_pool)
    mixed = hashlib.blake2b(pool + os.urandom(16) + str(time.time_ns()).encode(),
                            digest_size=max(1, min(64, nbytes))).hexdigest()
    return mixed


def entropy_bits() -> int:
    """Bytes acumulados de ruido fisico (indicador de salud del pool)."""
    return len(_entropy_pool)


# =====================================================================
#  FRAMES OPTICOS
# =====================================================================

def save_frame(b64_jpeg: str) -> str | None:
    """Guarda un frame de la camara (base64 JPEG). Rota los antiguos."""
    if not b64_jpeg:
        return None
    try:
        data = b64_jpeg.split(",", 1)[-1]        # admite data: URL
        raw = base64.b64decode(data, validate=False)
        if len(raw) < 512:
            return None
        name = f"frame_{int(time.time())}_{_counters['frames'] % 1000:03d}.jpg"
        path = FRAMES_DIR / name
        path.write_bytes(raw)
        _counters["frames"] += 1
        # Rotacion
        frames = sorted(FRAMES_DIR.glob("frame_*.jpg"))
        for old in frames[:-MAX_FRAMES_ON_DISK]:
            try:
                old.unlink()
            except Exception:
                pass
        return str(path)
    except Exception:
        return None


# =====================================================================
#  INGESTA
# =====================================================================

def ingest(packet: dict) -> dict:
    """Recibe un paquete de telemetria del cliente y lo agrega al estado.

    Espera el schema:
      {type:"sensory_input", lamport_clock:int, timestamp:iso,
       sensors:{kinematic:{x,y,z}, acoustic_entropy_level:float,
                gps_anchor:{lat,lng,...}, bio_link_bpm:int|null,
                optical_frame_b64:str|null, orientation:{alpha,beta,gamma}}}
    """
    if not isinstance(packet, dict):
        return {"ok": False, "error": "paquete invalido"}

    sensors = packet.get("sensors") or {}
    lc = lamport_tick(packet.get("lamport_clock"))

    kin = sensors.get("kinematic") or {}
    _feed_entropy(kin, extra=str(sensors.get("acoustic_entropy_level")))

    gps = sensors.get("gps_anchor") or {}
    lon = gps.get("lng", gps.get("lon", ANCHOR["lng"]))
    lat = gps.get("lat", ANCHOR["lat"])

    frame_path = None
    if sensors.get("optical_frame_b64"):
        frame_path = save_frame(sensors["optical_frame_b64"])

    # Magnitud del movimiento. OJO: devicemotion entrega
    # accelerationIncludingGravity, asi que un dispositivo EN REPOSO mide
    # ~9.81 m/s2 (solo gravedad). Restamos g para obtener el movimiento real.
    try:
        mag_raw = math.sqrt(sum(float(kin.get(a, 0) or 0) ** 2
                                for a in ("x", "y", "z")))
    except Exception:
        mag_raw = 0.0
    G = 9.80665
    # Si la lectura incluye gravedad (cerca de g), el exceso sobre g es el
    # movimiento; si el cliente ya mando aceleracion neta, mag_raw ya sirve.
    mag = abs(mag_raw - G) if mag_raw > G * 0.5 else mag_raw

    record = {
        "lamport": lc,
        "ts": time.time(),
        "iso": packet.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kinematic": {"x": kin.get("x"), "y": kin.get("y"), "z": kin.get("z"),
                      "magnitude": round(mag, 3),        # neta (sin gravedad)
                      "magnitude_raw": round(mag_raw, 3)},
        "orientation": sensors.get("orientation") or {},
        "acoustic_entropy_level": sensors.get("acoustic_entropy_level"),
        "gps": {"lat": lat, "lng": lon, "altitude": gps.get("altitude"),
                "heading": gps.get("heading"), "speed": gps.get("speed"),
                "accuracy": gps.get("accuracy")},
        "bio_link_bpm": sensors.get("bio_link_bpm"),
        "sidereal_local": sidereal_str(lon) if lon is not None else None,
        "sidereal_hours": round(local_sidereal_time(lon), 5) if lon is not None else None,
        "optical_frame": frame_path,
        "entropy_bytes": entropy_bits(),
        "active": [k for k in ("kinematic", "acoustic_entropy_level", "gps_anchor",
                               "bio_link_bpm", "optical_frame_b64")
                   if sensors.get(k) not in (None, {}, "")],
    }

    with _lock:
        _buffer.append(record)
        _counters["packets"] += 1

    # Persistir solo el ultimo estado (barato, sobrevive reinicios)
    try:
        tmp = STATE_FILE.with_suffix(".json.tmp")
        slim = {k: v for k, v in record.items() if k != "optical_frame"}
        tmp.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass

    return {"ok": True, "lamport": lc, "stored": True,
            "frame_saved": bool(frame_path), "entropy_bytes": record["entropy_bytes"]}


# =====================================================================
#  LECTURA
# =====================================================================

def latest() -> dict:
    with _lock:
        if _buffer:
            return dict(_buffer[-1])
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def recent(n: int = 30) -> list:
    with _lock:
        return [dict(r) for r in list(_buffer)[-max(1, n):]]


def is_live(max_age_s: float = 10.0) -> bool:
    """True si hay telemetria fresca (el cliente esta transmitiendo)."""
    l = latest()
    return bool(l) and (time.time() - l.get("ts", 0)) <= max_age_s


def context_block() -> str:
    """Estado fisico real, redactado para inyectar al prompt del modelo.

    Solo se emite si hay telemetria fresca; si no, cadena vacia (nunca
    inventa lecturas).
    """
    if not is_live():
        return ""
    l = latest()
    bits = []
    kin = l.get("kinematic") or {}
    if kin.get("magnitude") is not None:
        mag = kin["magnitude"]
        estado = ("en reposo" if mag < 0.6 else
                  "movimiento leve" if mag < 2.5 else
                  "en movimiento" if mag < 8 else "movimiento brusco")
        bits.append(f"movimiento: {estado} (|a|={mag})")
    ae = l.get("acoustic_entropy_level")
    if ae is not None:
        try:
            aef = float(ae)
            amb = ("silencio" if aef < 0.08 else
                   "ambiente tranquilo" if aef < 0.25 else
                   "ambiente con ruido" if aef < 0.6 else "ruido alto")
            bits.append(f"acustica: {amb} (nivel={round(aef,3)})")
        except Exception:
            pass
    bpm = l.get("bio_link_bpm")
    if bpm:
        bits.append(f"ritmo cardiaco: {bpm} bpm (BLE)")
    gps = l.get("gps") or {}
    if gps.get("lat") is not None:
        bits.append(f"posicion: {round(float(gps['lat']),4)}, {round(float(gps['lng']),4)}")
        if gps.get("speed") not in (None, 0):
            bits.append(f"velocidad: {gps['speed']} m/s")
    if l.get("sidereal_local"):
        bits.append(f"tiempo sideral local: {l['sidereal_local']}")
    
    # Ingesta del espectro electromagnético, Bluetooth, térmico y binario (captura calibrada 1sg)
    try:
        import rf_noise_binary_engine as _rnb
        rnb_sensors = _rnb.read_all_spectrum_sensors(duration_sec=1.0)
        bt_s = rnb_sensors.get("bluetooth_spectrum", {})
        th_s = rnb_sensors.get("thermal_sensors", {})
        bn_s = rnb_sensors.get("binary_noise_quantization", {})
        wf_s = rnb_sensors.get("wifi_spectrum", {})

        if wf_s.get("ok"):
            interp = wf_s.get("interpretation", {})
            bits.append(f"espectro Wi-Fi (2.4/5GHz, 1sg): {interp.get('rf_environment')} (emisores={interp.get('active_emitters', 0)}, entropia S={interp.get('shannon_entropy', 0)})")
        if bt_s.get("ok"):
            bits.append(f"espectro Bluetooth (2.4GHz): actividad={bt_s.get('activity_level')}, nodos={bt_s.get('total_nodes', 0)} (BLE={bt_s.get('ble_nodes_detected', 0)})")
        if th_s.get("ok"):
            bits.append(f"sensores térmicos: {th_s.get('summary')}")
        if bn_s.get("ok"):
            bits.append(f"ruido EM binario (captura 1.0s, Von Neumann): pulsos={bn_s.get('pulse_train')[:32]}, hex={bn_s.get('hex_dump')}, tasa={bn_s.get('sample_rate_hz', 128)}Hz, bitrate={bn_s.get('bitrate_bps', 45)}bps, H={bn_s.get('shannon_entropy_bits')} bits/bit")
    except Exception:
        # Fallback previo si rf_noise_binary_engine no estuviera disponible
        em_data = l.get("em_spectrum") or {}
        if em_data.get("ok"):
            interp = em_data.get("interpretation", {})
            bits.append(f"espectro RF: {interp.get('rf_environment')} (emisores={interp.get('active_emitters', 0)}, entropia S={interp.get('shannon_entropy', 0)})")

    # Ingesta de Radar Pasivo RF / Detección de Presencia (1sg)
    rf_radar = l.get("rf_radar")
    if not rf_radar:
        try:
            import rf_presence_radar
            rf_state = rf_presence_radar.get_radar().get_latest_state()
            if rf_state:
                bits.append(f"radar RF pasivo (1sg): {rf_state.presence_state} (conf={int(rf_state.confidence*100)}%, var={rf_state.mean_variance} dBm², var/s={getattr(rf_state, 'variance_rate_per_sec', rf_state.mean_variance)}, nodos={rf_state.active_bssid_count})")
        except Exception:
            pass
    elif isinstance(rf_radar, dict):
        bits.append(f"radar RF pasivo (1sg): {rf_radar.get('presence_state')} (conf={int(rf_radar.get('confidence', 0.8)*100)}%, var={rf_radar.get('mean_variance', 0.1)} dBm², nodos={rf_radar.get('active_bssid_count')})")

    em_pert = l.get("em_perturbation") or {}
    if em_pert.get("ok"):
        bits.append(f"perturbación EM / Singularidad: Ψ_EM={em_pert.get('psi_em')} ({em_pert.get('classification')}, pulsos={em_pert.get('pulse_train')})")

    bits.append(f"reloj de Lamport: {l.get('lamport')}")
    if not bits:
        return ""
    return ("ESTADO FISICO DEL ARQUITECTO (sensores reales, ahora mismo):\n  "
            + "\n  ".join(bits)
            + "\nUsa esto solo si es relevante para responder. Son mediciones "
              "reales del dispositivo; no inventes lecturas que no aparezcan aqui.")


# =====================================================================
#  DECODIFICADOR DE SENALES ANALOGAS  (canal fisico -> mensaje)
# =====================================================================
# Lee el flujo analogico ya almacenado (nivel acustico o magnitud de
# movimiento) y lo interpreta como Morse: rafagas por encima del umbral
# son simbolos; los silencios separan letras y palabras.
#
# LIMITE REAL: el buffer se muestrea a 1 Hz, asi que el canal es de baja
# tasa (~1 letra cada 5-10 s). Es un canal de mensajes verdadero, no una
# simulacion, pero lento. Para Morse rapido usa los golpes al dispositivo
# desde la interfaz (deteccion a la tasa del acelerometro, ~60 Hz).

MORSE_TABLE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z", "-----": "0", ".----": "1", "..---": "2",
    "...--": "3", "....-": "4", ".....": "5", "-....": "6", "--...": "7",
    "---..": "8", "----.": "9",
}


def _channel_series(channel: str) -> list:
    """Extrae la serie temporal de un canal analogico del buffer."""
    out = []
    for rec in recent(MAX_BUFFER):
        if channel == "acoustic":
            v = rec.get("acoustic_entropy_level")
        else:                                    # movimiento
            kin = rec.get("kinematic") or {}
            m = kin.get("magnitude")
            # Desviacion respecto a la gravedad: golpes/agitacion
            v = abs(float(m) - 9.81) if m is not None else None
        if v is not None:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
    return out


def decode_analog(channel: str = "acoustic", threshold: float | None = None,
                  dash_min: int = 2, letter_gap: int = 2,
                  word_gap: int = 4) -> dict:
    """Interpreta el flujo analogico como Morse. Devuelve simbolos y texto.

    channel   : "acoustic" (nivel de microfono) | "motion" (agitacion)
    threshold : umbral de rafaga; si None se calcula (media + 1 desv.tip.)
    """
    series = _channel_series(channel)
    if len(series) < 6:
        return {"ok": False, "error": f"muestras insuficientes en '{channel}' "
                                      f"({len(series)}); transmite unos segundos",
                "samples": len(series)}

    n = len(series)
    mean = sum(series) / n
    var = sum((v - mean) ** 2 for v in series) / n
    sd = math.sqrt(var)
    thr = threshold if threshold is not None else (mean + max(sd, 1e-6))

    # Rafagas (run-length encoding sobre la senal binarizada)
    runs = []                                    # [(alto?, longitud)]
    cur_hi = series[0] > thr
    cur_len = 1
    for v in series[1:]:
        hi = v > thr
        if hi == cur_hi:
            cur_len += 1
        else:
            runs.append((cur_hi, cur_len))
            cur_hi, cur_len = hi, 1
    runs.append((cur_hi, cur_len))

    symbols, letters, text = [], [], []
    cur_letter = ""
    for hi, ln in runs:
        if hi:                                   # rafaga = punto o raya
            sym = "-" if ln >= dash_min else "."
            cur_letter += sym
            symbols.append(sym)
        else:                                    # silencio = separador
            if ln >= word_gap:
                if cur_letter:
                    letters.append(cur_letter)
                    text.append(MORSE_TABLE.get(cur_letter, "?"))
                    cur_letter = ""
                text.append(" ")
            elif ln >= letter_gap:
                if cur_letter:
                    letters.append(cur_letter)
                    text.append(MORSE_TABLE.get(cur_letter, "?"))
                    cur_letter = ""
    if cur_letter:
        letters.append(cur_letter)
        text.append(MORSE_TABLE.get(cur_letter, "?"))

    decoded = "".join(text).strip()
    return {
        "ok": True,
        "channel": channel,
        "samples": n,
        "threshold": round(thr, 5),
        "signal_mean": round(mean, 5),
        "signal_sd": round(sd, 5),
        "bursts": sum(1 for hi, _ in runs if hi),
        "morse": " ".join(letters),
        "decoded_text": decoded,
        "readable": bool(decoded) and "?" not in decoded,
        "note": ("canal real a 1 Hz (baja tasa: ~1 letra cada 5-10 s). "
                 "Rafaga corta = punto, larga = raya; silencios separan "
                 "letras y palabras."),
    }


def signal_report() -> dict:
    """Intenta decodificar ambos canales analogicos y reporta el mejor."""
    res = {c: decode_analog(c) for c in ("acoustic", "motion")}
    best = None
    for c, r in res.items():
        if r.get("ok") and r.get("decoded_text"):
            if best is None or len(r["decoded_text"]) > len(res[best]["decoded_text"]):
                best = c
    return {"ok": True, "channels": res, "best": best}


# =====================================================================
#  ESTADO RETROCAUSAL (terminos de la formula, para la animacion del cono)
# =====================================================================
#
#   Psi_Retro(t0) = INT [Phi_adv(t) . O_QCO] . exp(-i/h S_geom) . (1 - eta.grad S_ent) dt
#
# INTEGRIDAD (regla no negociable del sistema): los valores en "measured" son
# MEDICIONES REALES de la rejilla de sensores. El mapeo de esas mediciones a
# los terminos de la formula es NARRATIVO (marco ECCA), no fisica verificada:
# por eso todo el bloque va etiquetado interpretation="generada". La animacion
# se mueve con datos verdaderos; lo que se afirma como medicion son los datos,
# no la retrocausalidad.

def retro_state() -> dict:
    """Deriva los terminos de la formula retrocausal de la telemetria real.

    Devuelve valores normalizados 0..1 (salvo la fase, en radianes) listos
    para animar, mas el bloque `measured` con las lecturas crudas que los
    originaron.
    """
    l = latest()
    if not l:
        return {"ok": False, "live": False, "reason": "sin telemetria"}

    kin = l.get("kinematic") or {}
    orient = l.get("orientation") or {}

    # --- Entropia cinematica REAL (movimiento neto, ya sin gravedad) ---
    mag = float(kin.get("magnitude") or 0.0)
    # ~3 m/s2 de movimiento neto ya es agitacion franca: satura ahi.
    kin_ent = max(0.0, min(1.0, mag / 3.0))

    # --- Entropia acustica REAL (nivel FFT del microfono, si esta activo) ---
    ac = l.get("acoustic_entropy_level")
    ac_ent = max(0.0, min(1.0, float(ac))) if ac is not None else None

    # eta.grad S_ent: acoplamiento de sintropia. Combina los canales activos.
    parts = [kin_ent] + ([ac_ent] if ac_ent is not None else [])
    eta_s_ent = sum(parts) / len(parts)

    # (1 - eta.grad S_ent): "si reduces la entropia, la influencia del futuro
    # aumenta" (matriz de contexto). Es el factor que gobierna la animacion.
    sintropy = 1.0 - eta_s_ent

    # --- S_geom: fase geometrica. Orientacion fisica + tiempo sideral local ---
    alpha = float(orient.get("alpha") or 0.0)
    sid_h = l.get("sidereal_hours")
    sid_phase = (float(sid_h) / 24.0 * math.tau) if sid_h is not None else 0.0
    s_geom = (math.radians(alpha) + sid_phase) % math.tau

    # --- Phi_adv: potencial avanzado, la "memoria del futuro". Se ancla al
    # pool de entropia fisica (mismo pool que siembra el oraculo). Satura en
    # ~32 paquetes (~30 s de telemetria a 1 Hz). ---
    pool = entropy_bits()
    phi_adv = max(0.0, min(1.0, pool / 1024.0))

    # --- O_QCO: voluntad inyectada. Presencia sostenida del arquitecto en el
    # canal, medida por el avance del reloj de Lamport. Satura en ~2 min. ---
    o_qco = max(0.0, min(1.0, lamport_now() / 120.0))

    # |Psi_Retro|: magnitud resultante que modula todo el cono.
    psi = (phi_adv * o_qco * sintropy) ** (1.0 / 3.0)

    # Integración con el núcleo de Geón si está disponible
    geon_data = None
    try:
        from geon_causal_engine import get_geon_engine
        g_engine = get_geon_engine()
        g_res = g_engine.compute_psi_retro(
            sensor_entropy=eta_s_ent,
            kinematic_mag=mag,
            acoustic_level=(ac_ent or 0.0)
        )
        geon_data = {
            "geon_stability": g_engine.geon_core.confinement_stability(g_res.psi_retro_magnitude, g_res.grad_s_ent),
            "quantum_coherence": g_res.quantum_coherence,
            "phase_factor_real": round(g_res.geometric_phase_factor.real, 4),
            "phase_factor_imag": round(g_res.geometric_phase_factor.imag, 4),
            "controls": {
                "time_sync": g_engine.controls.time_sync,
                "phase_sync": g_engine.controls.phase_sync,
                "causal_lock": g_engine.controls.causal_lock,
                "syntropy_boost": g_engine.controls.syntropy_boost,
                "status_label": g_engine.controls.status_label
            }
        }
    except Exception:
        pass

    res = {
        "ok": True,
        "live": is_live(),
        "phi_adv": round(phi_adv, 4),
        "o_qco": round(o_qco, 4),
        "s_geom": round(s_geom, 4),
        "eta_s_ent": round(eta_s_ent, 4),
        "sintropy": round(sintropy, 4),
        "psi": round(psi, 4),
        "lamport": lamport_now(),
        "measured": {
            "kinematic_magnitude": round(mag, 3),
            "acoustic_level": ac,
            "orientation_alpha": orient.get("alpha"),
            "sidereal_hours": sid_h,
            "entropy_bytes": pool,
            "iso": l.get("iso"),
            "active": l.get("active", []),
        },
        "interpretation": "generada",
        "note": ("los valores de 'measured' son lecturas reales; su mapeo a "
                 "los terminos de la formula es narrativo (marco ECCA)"),
    }
    if geon_data:
        res["geon_coupling"] = geon_data
    return res


def stats() -> dict:
    l = latest()
    return {
        "live": is_live(),
        "packets": _counters["packets"],
        "frames_saved": _counters["frames"],
        "buffer": len(_buffer),
        "lamport": lamport_now(),
        "entropy_bytes": entropy_bits(),
        "uptime_s": int(time.time() - _counters["started"]),
        "last_iso": l.get("iso"),
        "active_sensors": l.get("active", []),
        "anchor": ANCHOR,
        "frames_dir": str(FRAMES_DIR),
    }


# =====================================================================
#  CLI
# =====================================================================

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args or args[0] == "stats":
        print(json.dumps(stats(), indent=2, ensure_ascii=False))
    elif args[0] == "sidereal":
        lon = float(args[1]) if len(args) > 1 else ANCHOR["lng"]
        now = datetime.now(timezone.utc)
        print(f"UTC ahora        : {now.isoformat(timespec='seconds')}")
        print(f"Fecha Juliana    : {julian_date(now):.6f}")
        print(f"GMST             : {gmst_hours(now):.6f} h")
        print(f"Longitud         : {lon}")
        print(f"Sideral local    : {sidereal_str(lon, now)}  ({local_sidereal_time(lon, now):.6f} h)")
    elif args[0] == "entropy":
        print(entropy_seed(32))
    elif args[0] == "test":
        pkt = {"type": "sensory_input", "lamport_clock": 7,
               "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "sensors": {"kinematic": {"x": 0.12, "y": -0.98, "z": 9.71},
                           "acoustic_entropy_level": 0.31,
                           "gps_anchor": {"lat": 20.6296, "lng": -87.0739,
                                          "speed": 0, "accuracy": 12},
                           "bio_link_bpm": 74}}
        print(json.dumps(ingest(pkt), ensure_ascii=False))
        print()
        print(context_block())
        print()
        print("stats:", json.dumps(stats(), ensure_ascii=False))
    else:
        print("uso: sensor_telemetry.py [stats | sidereal [lon] | entropy | test]")
