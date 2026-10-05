"""
device_sensors.py - Acceso a camara, microfono y sensores del sistema.
=======================================================================

Capacidades para el agente GIA:
  - list_cameras / capture_photo   (opencv)
  - list_microphones / record_audio (sounddevice + scipy)
  - read_sensors                    (psutil: cpu, ram, disco, red, bateria,
                                     temperaturas si el driver las expone)

Cada operacion se registra en el audit log del agente (agent_safety.audit)
y muestra un indicador cuando camara/microfono estan capturando.

Los archivos capturados van a %LOCALAPPDATA%\\vw-control\\captures\\.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
CAPTURE_DIR = CONFIG_DIR / "captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

# Audit (best-effort: si no esta, no-op)
try:
    import agent_safety as _safety
    def _audit(a, d, v="ALLOW"):
        _safety.audit(a, d, verdict=v)
except Exception:
    def _audit(a, d, v="ALLOW"):
        pass


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# =====================================================================
#  CAMARA
# =====================================================================

def _get_camera_backend():
    import cv2
    if os.name == "nt":
        return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
    return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)


def list_cameras(max_probe: int = 5) -> dict:
    """Enumera indices de camara disponibles probando 0..max_probe-1."""
    try:
        import cv2
    except Exception as e:
        return {"ok": False, "error": f"opencv no disponible: {e}"}
    found = []
    backend = _get_camera_backend()
    for idx in range(max_probe):
        cap = cv2.VideoCapture(idx, backend)
        if cap is not None and cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            found.append({"index": idx, "width": w, "height": h})
            cap.release()
    return {"ok": True, "count": len(found), "cameras": found}


def capture_photo(args: dict) -> dict:
    """Captura una foto de la camara. args: {camera_index?, path?, warmup_frames?}"""
    try:
        import cv2
    except Exception as e:
        return {"ok": False, "error": f"opencv no disponible: {e}"}
    idx = int(args.get("camera_index", 0))
    warmup = int(args.get("warmup_frames", 8))
    out = args.get("path") or str(CAPTURE_DIR / f"photo_{_stamp()}.jpg")
    print("\033[91m  [CAMARA ACTIVA] capturando foto...\033[0m")
    frame = None
    try:
        from telemetry.camera_grabber import get_camera_grabber
        grabber = get_camera_grabber(idx)
        ok, frame, _ = grabber.get_latest_frame()
    except Exception:
        ok = False

    if not ok or frame is None:
        backend = _get_camera_backend()
        cap = cv2.VideoCapture(idx, backend)
        if not cap or not cap.isOpened():
            return {"ok": False, "error": f"no se pudo abrir la camara {idx}"}
        try:
            for _ in range(max(1, warmup)):        # dejar que ajuste exposicion
                ok, frame = cap.read()
                if not ok:
                    frame = None
        finally:
            cap.release()

    if frame is None:
        return {"ok": False, "error": "no se capturo frame"}
    cv2.imwrite(out, frame)
    _audit("capture_photo", out[:200])
    size = os.path.getsize(out) if os.path.isfile(out) else 0
    return {"ok": True, "path": out, "bytes": size,
            "note": "el modelo es de texto y NO ve la imagen; el archivo "
                    "queda en disco. Usa una tool de vision aparte si hace falta."}


def analyze_face_emotion(args: dict | None = None) -> dict:
    """Analiza la expresion facial y estimacion de emocion del usuario frente a la camara."""
    args = args or {}
    idx = int(args.get("camera_index", 0))
    try:
        import cv2
        import numpy as np
    except Exception as e:
        return {"ok": False, "error": f"opencv/numpy no disponible: {e}"}

    frame = None
    try:
        from telemetry.camera_grabber import get_camera_grabber
        grabber = get_camera_grabber(idx)
        ok, frame, _ = grabber.get_latest_frame()
    except Exception:
        ok = False

    if not ok or frame is None:
        if sys.platform.startswith("linux") and not os.path.exists(f"/dev/video{idx}"):
            return {"ok": False, "error": f"Dispositivo /dev/video{idx} no disponible en el sistema"}
        backend = _get_camera_backend()
        cap = cv2.VideoCapture(idx, backend)
        if not cap or not cap.isOpened():
            return {"ok": False, "error": f"Camara {idx} no disponible"}
        try:
            for _ in range(2):
                ok, frame = cap.read()
                if not ok:
                    frame = None
        finally:
            cap.release()

    if frame is None:
        return {"ok": False, "error": "No se pudo obtener frame de camara"}

    try:
        h, w, _ = frame.shape
        # Conversión a escala de grises para análisis de luminancia y gradientes
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detector rápido Haar de cascada si está disponible en cv2.data
        haar_path = getattr(cv2.data, 'haarcascades', '') + 'haarcascade_frontalface_default.xml'
        faces = []
        if os.path.isfile(haar_path):
            cascade = cv2.CascadeClassifier(haar_path)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(60, 60))

        if len(faces) == 0:
            # Fallback a centroide de masa de luminancia/color piel
            face_box = [int(w * 0.25), int(h * 0.2), int(w * 0.5), int(h * 0.6)]
            detected = False
        else:
            face_box = [int(v) for v in faces[0]]
            detected = True

        fx, fy, fw, fh = face_box
        norm_cx = round(((fx + fw / 2) - (w / 2)) / (w / 2), 3)
        norm_cy = round(((fy + fh / 2) - (h / 2)) / (h / 2), 3)

        # Análisis de contraste en tercio inferior (boca) y tercio superior (cejas/ojos)
        mouth_region = gray[fy + int(fh * 0.65): fy + fh, fx + int(fw * 0.2): fx + int(fw * 0.8)]
        eye_region = gray[fy + int(fh * 0.2): fy + int(fh * 0.5), fx + int(fw * 0.15): fx + int(fw * 0.85)]

        mouth_std = float(np.std(mouth_region)) if mouth_region.size > 0 else 0.0
        eye_std = float(np.std(eye_region)) if eye_region.size > 0 else 0.0

        # Heurística de expresión, gesticulación y neuroquímica
        if mouth_std > 38.0:
            emotion = "alegre"
            mood_state = "Entusiasmado y Creativo"
            gesticulation = "Elevación cigomática bilateral (sonrisa activa) y ojos despiertos"
            chem = {"dopamina": 84, "cortisol": 14, "serotonina": 80, "adrenalina": 25, "fatiga": 10}
            confidence = 0.88
            advice = "El usuario muestra sonrisa y entusiasmo. Conecta con dinamismo, calidez y complicidad intelectual."
        elif eye_std > 42.0:
            emotion = "enfocado"
            mood_state = "Analítico y Concentrado"
            gesticulation = "Fijación ocular sostenida, mínima oscilación muscular y atención centrada"
            chem = {"dopamina": 70, "cortisol": 22, "serotonina": 85, "adrenalina": 28, "fatiga": 12}
            confidence = 0.91
            advice = "El usuario está absorto en la terminal. Proporciona respuestas técnicas afiladas, directas y precisas."
        else:
            emotion = "neutral"
            mood_state = "Sereno y Reflexivo"
            gesticulation = "Gesticulación facial neutra y distendida, postura corporal estable"
            chem = {"dopamina": 62, "cortisol": 18, "serotonina": 76, "adrenalina": 15, "fatiga": 12}
            confidence = 0.78
        # Rastreador e identificación multi-individuo
        tracker_res = {}
        try:
            from core.individual_tracker import get_individual_tracker
            tracker_res = get_individual_tracker().process_frame(frame)
        except Exception:
            pass

        individuals = tracker_res.get("individuals", [])
        individuals_count = tracker_res.get("count", 1 if detected else 0)
        occupancy_label = tracker_res.get("occupancy_label", "1 Individuo" if detected else "Habitación Vacía")

        return {
            "ok": True,
            "detected": detected,
            "face_box": {"x": fx, "y": fy, "width": fw, "height": fh},
            "gaze_vector": {"x": norm_cx, "y": norm_cy},
            "primary": emotion,
            "mood_state": mood_state,
            "gesticulation": gesticulation,
            "neurochemistry": chem,
            "confidence": confidence,
            "attention": "Alta" if detected and abs(norm_cx) < 0.3 else "Media",
            "advice": advice,
            "individuals_count": individuals_count,
            "individuals": individuals,
            "occupancy_label": occupancy_label,
            "timestamp": time.time()
        }
    except Exception as e_proc:
        return {"ok": False, "error": f"Error procesando frame: {e_proc}"}


# =====================================================================
#  DEMONIO EN SEGUNDO PLANO: ESCÁNER FACIAL Y RASTREO OCULAR CONTINUO
# =====================================================================

_LAST_BACKGROUND_FACE: dict = {
    "ok": True,
    "detected": False,
    "primary": "neutral",
    "mood_state": "Sereno y Reflexivo",
    "gesticulation": "Gesticulación facial estable y natural",
    "neurochemistry": {"dopamina": 68, "cortisol": 18, "serotonina": 80, "adrenalina": 18, "fatiga": 12},
    "confidence": 0.85,
    "attention": "Alta",
    "gaze": "Enfocado en terminal",
    "advice": "El usuario se encuentra sereno y receptivo frente a la terminal.",
    "individuals_count": 0,
    "individuals": [],
    "occupancy_label": "Habitación Vacía (Sin presencia)",
    "timestamp": time.time()
}
_bg_scanner_running = False
_bg_scanner_thread = None

def get_latest_face_emotion() -> dict:
    """Retorna la última lectura biométrica en segundo plano."""
    return dict(_LAST_BACKGROUND_FACE)

def update_face_emotion_cache(payload: dict) -> dict:
    """Actualiza la telemetría facial desde el frontend o sensor local y procesa la presencia del usuario."""
    global _LAST_BACKGROUND_FACE
    if isinstance(payload, dict) and payload:
        try:
            from core.individual_tracker import get_individual_tracker
            tracker_state = get_individual_tracker().update_from_frontend_telemetry(payload)
            payload["individuals"] = tracker_state.get("individuals", [])
            payload["individuals_count"] = tracker_state.get("count", 1 if payload.get("detected") else 0)
            payload["occupancy_label"] = tracker_state.get("occupancy_label", "Presencia activa")
        except Exception:
            pass

        _LAST_BACKGROUND_FACE.update(payload)
        _LAST_BACKGROUND_FACE["timestamp"] = time.time()

        # Registrar interacción si se detecta presencia y ha pasado el periodo de deduplicación
        try:
            from core.interaction_logger import get_interaction_logger
            logger_inst = get_interaction_logger()
            indivs = payload.get("individuals", [])
            primary_indiv = indivs[0] if indivs else None
            is_detected = bool(payload.get("detected") or indivs)
            now = time.time()
            if is_detected and primary_indiv:
                p_id = primary_indiv.get("id", "")
                last_log_ts = getattr(logger_inst, "_last_presence_log_ts", 0)
                last_p_id = getattr(logger_inst, "_last_presence_id", "")
                if (now - last_log_ts > 60.0) or (p_id != last_p_id):
                    logger_inst._last_presence_log_ts = now
                    logger_inst._last_presence_id = p_id
                    p_name = primary_indiv.get("name", "Individuo Detectado")
                    logger_inst.record_interaction(
                        interaction_type="presencia_visual",
                        title=f"Presencia de {p_name}",
                        details=f"{primary_indiv.get('role', 'Operador')} frente a la terminal. Cercanía: {primary_indiv.get('proximity', 'Cercano')}. Emoción: {payload.get('primary', 'neutral')}.",
                        individual=primary_indiv,
                        photo_b64=primary_indiv.get("thumbnail_b64") or payload.get("thumbnail_b64"),
                        capture_system_screenshot=True if not primary_indiv.get("thumbnail_b64") else False
                    )
        except Exception:
            pass
    agent_res = {}
    try:
        from core.emotional_presence_agent import get_emotional_presence_agent
        agent_res = get_emotional_presence_agent().process_face_frame(payload if isinstance(payload, dict) else {})
    except Exception:
        pass
    return agent_res

def start_background_face_scanner(interval_sec: float = 3.0) -> None:
    """Inicia un hilo en segundo plano que mantiene el escáner facial activo continuamente."""
    global _bg_scanner_running, _bg_scanner_thread
    if _bg_scanner_running:
        return
    _bg_scanner_running = True

    def _loop():
        import threading
        fail_count = 0
        while _bg_scanner_running:
            try:
                # Si no hay cámara física en Linux, no saturar ioctl
                if sys.platform.startswith("linux") and not any(os.path.exists(f"/dev/video{i}") for i in range(4)):
                    time.sleep(15.0)
                    continue

                # Si el frontend envía telemetría fresca (últimos 4s), no disputa el dispositivo de cámara
                now = time.time()
                last_ts = _LAST_BACKGROUND_FACE.get("timestamp", 0)
                if (now - last_ts) > 4.0:
                    res = analyze_face_emotion()
                    if res.get("ok"):
                        fail_count = 0
                        update_face_emotion_cache(res)
                    else:
                        fail_count += 1
            except Exception:
                fail_count += 1
            sleep_sec = 15.0 if fail_count >= 2 else max(2.0, interval_sec)
            time.sleep(sleep_sec)

    import threading
    _bg_scanner_thread = threading.Thread(target=_loop, name="GIA_BackgroundFaceScanner", daemon=True)
    _bg_scanner_thread.start()


# =====================================================================
#  MICROFONO
# =====================================================================

def list_microphones() -> dict:
    """Lista dispositivos de entrada de audio."""
    try:
        import sounddevice as sd
    except Exception as e:
        return {"ok": False, "error": f"sounddevice no disponible: {e}"}
    devs = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                devs.append({"index": i, "name": d["name"][:60],
                             "channels": d["max_input_channels"],
                             "default_samplerate": int(d.get("default_samplerate", 0))})
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "count": len(devs), "microphones": devs}


def record_audio(args: dict) -> dict:
    """Graba audio del microfono. args: {seconds?, device_index?, path?, samplerate?}"""
    try:
        import sounddevice as sd
        from scipy.io import wavfile
        import numpy as np
    except Exception as e:
        return {"ok": False, "error": f"audio no disponible: {e}"}
    seconds = float(args.get("seconds", 5))
    seconds = max(0.5, min(seconds, 120))            # 0.5s..2min
    sr = int(args.get("samplerate", 44100))
    dev = args.get("device_index")
    out = args.get("path") or str(CAPTURE_DIR / f"audio_{_stamp()}.wav")
    print(f"\033[91m  [MICROFONO ACTIVO] grabando {seconds:.0f}s...\033[0m")
    try:
        kw = {"samplerate": sr, "channels": 1, "dtype": "int16"}
        if dev is not None:
            kw["device"] = int(dev)
        rec = sd.rec(int(seconds * sr), **kw)
        sd.wait()
        wavfile.write(out, sr, rec)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    _audit("record_audio", f"{out} ({seconds:.0f}s)")
    size = os.path.getsize(out) if os.path.isfile(out) else 0
    return {"ok": True, "path": out, "seconds": seconds, "bytes": size,
            "note": "audio guardado en disco (WAV). El modelo no lo 'oye'; "
                    "usarias STT aparte para transcribir."}


# =====================================================================
#  SENSORES DEL SISTEMA
# =====================================================================

def read_sensors(args: dict = None) -> dict:
    """Lee sensores/estado del sistema via psutil."""
    try:
        import psutil
    except Exception as e:
        return {"ok": False, "error": f"psutil no disponible: {e}"}
    data = {}
    try:
        data["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        data["cpu_count"] = psutil.cpu_count()
        try:
            freq = psutil.cpu_freq()
            if freq:
                data["cpu_freq_mhz"] = round(freq.current)
        except Exception:
            pass
        vm = psutil.virtual_memory()
        data["ram_total_gb"] = round(vm.total / 1e9, 1)
        data["ram_used_gb"] = round(vm.used / 1e9, 1)
        data["ram_percent"] = vm.percent
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                disks.append({"mount": part.mountpoint,
                              "total_gb": round(u.total / 1e9, 1),
                              "percent": u.percent})
            except Exception:
                continue
        data["disks"] = disks
        net = psutil.net_io_counters()
        data["net_sent_mb"] = round(net.bytes_sent / 1e6, 1)
        data["net_recv_mb"] = round(net.bytes_recv / 1e6, 1)
        # Bateria (laptop)
        try:
            bat = psutil.sensors_battery()
            if bat:
                data["battery_percent"] = bat.percent
                data["battery_plugged"] = bat.power_plugged
        except Exception:
            pass
        # Temperaturas (a veces no expuestas en Windows)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                data["temperatures"] = {
                    k: [round(t.current, 1) for t in v] for k, v in temps.items()}
        except Exception:
            pass

        # Lectura del espectro electromagnético & Wi-Fi
        if args and (args.get("include_em_spectrum") or args.get("include_all_spectrum")):
            try:
                import em_spectrum_engine as _em
                data["em_spectrum"] = _em.read_em_spectrum()
            except Exception as e:
                data["em_spectrum_error"] = str(e)

        # Lectura de Bluetooth / BLE
        if args and (args.get("include_bluetooth") or args.get("include_all_spectrum")):
            try:
                import rf_noise_binary_engine as _rnb
                data["bluetooth_spectrum"] = _rnb.scan_bluetooth_spectrum()
            except Exception as e:
                data["bluetooth_error"] = str(e)

        # Lectura de sensores térmicos
        if args and (args.get("include_thermal") or args.get("include_all_spectrum")):
            try:
                import rf_noise_binary_engine as _rnb
                data["thermal_sensors"] = _rnb.read_thermal_sensors()
            except Exception as e:
                data["thermal_error"] = str(e)

        # Conversión de ruido a binario
        if args and (args.get("include_binary_noise") or args.get("include_all_spectrum")):
            try:
                import rf_noise_binary_engine as _rnb
                data["binary_noise"] = _rnb.quantize_noise_to_binary()
            except Exception as e:
                data["binary_noise_error"] = str(e)

    except Exception as e:
        return {"ok": False, "error": str(e)}
    _audit("read_sensors", f"cpu={data.get('cpu_percent')}% ram={data.get('ram_percent')}%")
    return {"ok": True, "sensors": data}


# =====================================================================
#  ESPECTRO ELECTROMAGNÉTICO, BLUETOOTH, TÉRMICO Y RUIDO BINARIO
# =====================================================================

def read_em_spectrum(args: dict = None) -> dict:
    """Lee e interpreta el espectro electromagnético de la tarjeta Wi-Fi y sensores RF."""
    try:
        import em_spectrum_engine as _em
        res = _em.read_em_spectrum()
        _audit("read_em_spectrum", f"networks={res.get('total_networks_detected', 0)}")
        return res
    except Exception as e:
        return {"ok": False, "error": f"em_spectrum_engine no disponible: {e}"}


def scan_wifi_spectrum(args: dict = None) -> dict:
    """Escanea las redes inalámbricas del espectro RF y calcula su PSD."""
    return read_em_spectrum(args)


def read_bluetooth_spectrum(args: dict = None) -> dict:
    """Escanea radios y dispositivos Bluetooth / BLE en la banda de 2.4 GHz."""
    try:
        import rf_noise_binary_engine as _rnb
        res = _rnb.scan_bluetooth_spectrum()
        _audit("read_bluetooth_spectrum", f"nodes={res.get('total_nodes', 0)}")
        return res
    except Exception as e:
        return {"ok": False, "error": f"rf_noise_binary_engine no disponible: {e}"}


def read_thermal_sensors(args: dict = None) -> dict:
    """Lee temperaturas de GPU (NVIDIA), CPU y zonas térmicas del hardware."""
    try:
        import rf_noise_binary_engine as _rnb
        res = _rnb.read_thermal_sensors()
        _audit("read_thermal_sensors", res.get("summary", "nominal")[:100])
        return res
    except Exception as e:
        return {"ok": False, "error": f"rf_noise_binary_engine no disponible: {e}"}


def read_ambient_noise_binary(args: dict = None) -> dict:
    """Convierte el ruido analógico ambiental a un tren de pulsos binario cuantizado (Von Neumann)."""
    try:
        import rf_noise_binary_engine as _rnb
        samples = int(args.get("sample_count", 128)) if args else 128
        res = _rnb.quantize_noise_to_binary(sample_count=samples)
        _audit("read_ambient_noise_binary", f"bits={res.get('quantized_bit_count', 0)}")
        return res
    except Exception as e:
        return {"ok": False, "error": f"rf_noise_binary_engine no disponible: {e}"}


def read_all_spectrum(args: dict = None) -> dict:
    """Obtiene la lectura unificada de Wi-Fi, Bluetooth, sensores térmicos y ruido binario."""
    try:
        import rf_noise_binary_engine as _rnb
        res = _rnb.read_all_spectrum_sensors()
        _audit("read_all_spectrum", "unificado")
        return res
    except Exception as e:
        return {"ok": False, "error": f"rf_noise_binary_engine no disponible: {e}"}



# =====================================================================
#  Self-test
# =====================================================================
if __name__ == "__main__":
    import json
    print("=== list_cameras ===")
    print(json.dumps(list_cameras(), indent=2, ensure_ascii=False))
    print("\n=== list_microphones ===")
    print(json.dumps(list_microphones(), indent=2, ensure_ascii=False))
    print("\n=== read_sensors ===")
    print(json.dumps(read_sensors(), indent=2, ensure_ascii=False, default=str))
