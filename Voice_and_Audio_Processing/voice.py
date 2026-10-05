"""
voice.py - Motor de voz (TTS) de alta fidelidad y generador de audio para GIA / GODWORKS.
========================================================================================

Proporciona soporte nativo para la VOZ DE CORTANA (Microsoft Neural AI) con
fallback a pyttsx3 / SAPI5 en Windows o sintetizadores locales.

Voz por defecto: Microsoft Cortana (es-MX-DaliaNeural / es-MX-Sabina).

Capacidades:
  1. Reproducción física por bocinas del PC anfitrión (speak / speak_async vía GStreamer/PipeWire).
  2. Generación y streaming de audio MP3 en memoria para clientes web y móviles (synthesize_to_bytes).
  3. Listado y conmutación dinámica de voces Cortana y regionales.
  4. Control de velocidad (rate) y volumen.
  5. Cancelación instantánea de locución en curso (stop / stop_speech).
"""
from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

# -----------------------------------------------------------------------------
# Verificación de Motores Disponibles
# -----------------------------------------------------------------------------
HAS_EDGE_TTS = False
try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    HAS_EDGE_TTS = False

HAS_PYTTSX3 = False
try:
    import pyttsx3
    HAS_PYTTSX3 = True
except Exception:
    HAS_PYTTSX3 = False

_OK = HAS_EDGE_TTS or HAS_PYTTSX3
_ERR = "" if _OK else "Ni edge_tts ni pyttsx3 están disponibles."

# Voces principales de Cortana
CORTANA_VOICES = [
    {
        "id": "es-MX-DaliaNeural",
        "name": "Cortana (Microsoft Neural - Español México)",
        "lang": "es-MX",
        "gender": "Female",
        "is_default": True
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Cortana (Microsoft Neural - English US)",
        "lang": "en-US",
        "gender": "Female",
        "is_default": False
    },
    {
        "id": "es-ES-ElviraNeural",
        "name": "Cortana (Microsoft Neural - España)",
        "lang": "es-ES",
        "gender": "Female",
        "is_default": False
    },
    {
        "id": "es-MX-JorgeNeural",
        "name": "Jorge (Microsoft Neural - Español)",
        "lang": "es-MX",
        "gender": "Male",
        "is_default": False
    }
]

# Preferencias activas
_PREF_VOICE = "es-MX-DaliaNeural"  # Voz oficial de Cortana en español
_RATE = 1.05                      # Cadencia ligeramente viva y clara característica de Cortana
_PITCH = "+2Hz"                   # Brillo tonal característico de Cortana
_VOLUME = 1.0

_lock = threading.Lock()
_current_proc: Optional[subprocess.Popen] = None
_current_thread: Optional[threading.Thread] = None


def _init_com():
    """Inicializa COM apartment en Windows para pyttsx3 si fuera necesario."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass


def _uninit_com():
    """Libera COM apartment en Windows."""
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass


def list_voices() -> List[Dict[str, Any]]:
    """Devuelve la lista de voces disponibles, priorizando los perfiles de Cortana."""
    voices = list(CORTANA_VOICES)
    if HAS_PYTTSX3:
        try:
            _init_com()
            eng = pyttsx3.init()
            for v in eng.getProperty("voices"):
                voices.append({
                    "id": "SAPI5:" + v.id,
                    "name": v.name,
                    "lang": getattr(v, "languages", ["es"])[0] if getattr(v, "languages", None) else "local",
                    "gender": getattr(v, "gender", "unknown"),
                    "is_default": False
                })
            eng.stop()
        except Exception:
            pass
        finally:
            _uninit_com()
    return voices


def set_voice(voice_id: str) -> str:
    """Configura la voz activa (acepta IDs o nombres como 'cortana', 'dalia', 'sabina')."""
    global _PREF_VOICE
    voice_clean = (voice_id or "").strip().lower()
    if not voice_clean:
        return _PREF_VOICE

    if "cortana" in voice_clean or "dalia" in voice_clean or "sabina" in voice_clean:
        _PREF_VOICE = "es-MX-DaliaNeural"
    elif "jenny" in voice_clean or "english" in voice_clean or "en-us" in voice_clean:
        _PREF_VOICE = "en-US-JennyNeural"
    elif "elvira" in voice_clean or "españa" in voice_clean or "es-es" in voice_clean:
        _PREF_VOICE = "es-ES-ElviraNeural"
    else:
        # Asignar directamente si coincide con alguna disponible
        for v in list_voices():
            if voice_clean in v["id"].lower() or voice_clean in v["name"].lower():
                _PREF_VOICE = v["id"]
                break
    return _PREF_VOICE


def set_rate(wpm_or_rate: float) -> float:
    """Configura la velocidad de locución."""
    global _RATE
    try:
        val = float(wpm_or_rate)
        if val > 10.0:  # Si viene en WPM (ej: 175)
            _RATE = round(val / 170.0, 2)
        else:
            _RATE = max(0.5, min(2.0, val))
    except Exception:
        pass
    return _RATE


def set_volume(vol: float) -> float:
    """Configura el volumen (0.0 a 1.0)."""
    global _VOLUME
    try:
        _VOLUME = max(0.0, min(1.0, float(vol)))
    except Exception:
        pass
    return _VOLUME


def get_config() -> Dict[str, Any]:
    """Retorna la configuración y estado actual del motor de voz."""
    return {
        "ok": _OK,
        "engine": "edge-tts (Cortana Neural)" if HAS_EDGE_TTS else ("pyttsx3" if HAS_PYTTSX3 else "none"),
        "pref_voice": _PREF_VOICE,
        "cortana_active": "dalia" in _PREF_VOICE.lower() or "cortana" in _PREF_VOICE.lower(),
        "rate": _RATE,
        "volume": _VOLUME,
        "voices": list_voices()
    }


async def synthesize_to_bytes_async(text: str, voice: Optional[str] = None) -> Optional[bytes]:
    """Sintetiza texto asíncronamente a bytes MP3 con la voz de Cortana."""
    text = (text or "").strip()
    if not text:
        return None

    target_voice = voice or _PREF_VOICE
    if target_voice.startswith("SERVER:"):
        target_voice = target_voice.replace("SERVER:", "")

    if HAS_EDGE_TTS and not target_voice.startswith("SAPI5:"):
        try:
            rate_pct = int((_RATE - 1.0) * 100)
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
            comm = edge_tts.Communicate(text, target_voice, rate=rate_str, pitch=_PITCH)
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()
        except Exception:
            pass
    return synthesize_to_bytes(text, voice=voice)


def synthesize_to_bytes(text: str, voice: Optional[str] = None) -> Optional[bytes]:
    """
    Sintetiza texto a bytes de audio MP3 usando la voz de Cortana.
    Compatible con streaming web directo para navegador y móvil.
    """
    text = (text or "").strip()
    if not text:
        return None

    target_voice = voice or _PREF_VOICE
    if target_voice.startswith("SERVER:"):
        target_voice = target_voice.replace("SERVER:", "")

    # Método Primario: Edge TTS (Voz de Cortana Neural)
    if HAS_EDGE_TTS and not target_voice.startswith("SAPI5:"):
        try:
            import concurrent.futures
            rate_pct = int((_RATE - 1.0) * 100)
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

            async def _synth_async() -> bytes:
                comm = edge_tts.Communicate(text, target_voice, rate=rate_str, pitch=_PITCH)
                buf = io.BytesIO()
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                return buf.getvalue()

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(lambda: asyncio.run(_synth_async())).result()
            else:
                return asyncio.run(_synth_async())
        except Exception:
            pass

    # Método Secundario: pyttsx3 (SAPI5 local)
    if HAS_PYTTSX3:
        with _lock:
            tmp_path = None
            try:
                _init_com()
                fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="gia_tts_")
                os.close(fd)
                eng = pyttsx3.init()
                eng.setProperty("rate", int(_RATE * 175))
                eng.setProperty("volume", _VOLUME)
                if target_voice.startswith("SAPI5:"):
                    eng.setProperty("voice", target_voice.replace("SAPI5:", ""))
                eng.save_to_file(text, tmp_path)
                eng.runAndWait()
                eng.stop()
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    with open(tmp_path, "rb") as f:
                        return f.read()
            except Exception:
                pass
            finally:
                _uninit_com()
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
    return None


def synthesize_to_file(text: str, filepath: str, voice: Optional[str] = None) -> bool:
    """Sintetiza texto directamente a un archivo de audio."""
    data = synthesize_to_bytes(text, voice=voice)
    if data:
        try:
            with open(filepath, "wb") as f:
                f.write(data)
            return True
        except Exception:
            return False
    return False


def stop() -> Dict[str, Any]:
    """Detiene cualquier reproducción física en curso en el anfitrión."""
    global _current_proc
    with _lock:
        if _current_proc:
            try:
                _current_proc.terminate()
                _current_proc.wait(timeout=1.0)
            except Exception:
                try:
                    _current_proc.kill()
                except Exception:
                    pass
            _current_proc = None

    if HAS_PYTTSX3:
        try:
            _init_com()
            eng = pyttsx3.init()
            eng.stop()
        except Exception:
            pass
        finally:
            _uninit_com()
    return {"ok": True, "stopped": True}


def stop_speech() -> Dict[str, Any]:
    """Alias para stop()."""
    return stop()


def speak(text: str, wait: bool = True, voice: Optional[str] = None) -> Dict[str, Any]:
    """
    Reproduce texto por las bocinas físicas del PC anfitrión con la voz de Cortana.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "Texto vacío"}

    def _run():
        global _current_proc
        # Detener locución previa si aún suena
        stop()

        target_voice = voice or _PREF_VOICE
        data = synthesize_to_bytes(text, voice=target_voice)
        if not data:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, prefix="cortana_") as tf:
            tf.write(data)
            tmp_file = tf.name

        try:
            # Reproducción con GStreamer (GstPulse / AutoAudioSink)
            if shutil.which("gst-launch-1.0"):
                proc = subprocess.Popen(
                    ["gst-launch-1.0", "playbin", f"uri=file://{tmp_file}", "audio-sink=autoaudiosink"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif shutil.which("pw-play"):
                proc = subprocess.Popen(
                    ["pw-play", tmp_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif shutil.which("aplay"):
                proc = subprocess.Popen(
                    ["aplay", tmp_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                proc = None

            with _lock:
                _current_proc = proc

            if proc:
                proc.wait()
        except Exception:
            pass
        finally:
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception:
                pass

    if wait:
        _run()
        return {"ok": True, "spoke": text[:120], "voice": voice or _PREF_VOICE}
    else:
        global _current_thread
        _current_thread = threading.Thread(target=_run, daemon=True, name="cortana-speaker")
        _current_thread.start()
        return {"ok": True, "spoke_async": text[:120], "voice": voice or _PREF_VOICE}


def speak_async(text: str, voice: Optional[str] = None) -> Dict[str, Any]:
    """Versión asíncrona no bloqueante de speak()."""
    return speak(text, wait=False, voice=voice)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        print("Voces disponibles en el sistema (Voz Cortana activa):")
        for v in list_voices():
            def_tag = " [PREDETERMINADA]" if v.get("is_default") else ""
            print(f"  - {v['name']} | ID: {v['id']}{def_tag}")
        sys.exit(0)

    if args[0] == "--wav" and len(args) >= 3:
        txt = args[1]
        out_file = args[2]
        ok = synthesize_to_file(txt, out_file)
        print(f"Sintetizado a {out_file}: {'OK' if ok else 'FALLO'}")
        sys.exit(0 if ok else 1)

    speak(" ".join(args))
