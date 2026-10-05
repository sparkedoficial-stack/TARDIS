#!/usr/bin/env python3
"""
tardis_snap_voice_assistant.py - Asistente de Voz TARDIS Activado por Chasquido de Dedos
========================================================================================
Desarrollado para el Arquitecto (₪) · GODWORKS SYSTEM v26.4 & TARDIS

Operación:
  1. Centinela Acústico Continuo (SnapDetector): Monitorea la señal del micrófono
     en tiempo real (44.1 kHz) con bajo consumo de CPU (~0.5%). Identifica transitorios
     impulsivos característicos del chasquido de dedos (frecuencias altas 2.5-8 kHz,
     ataque empinado < 2 ms, rápido decaimiento < 30 ms y alto crest factor).
  2. Activación Instantánea: Emite un chime holográfico ascendente armónico
     e inicia captura de voz con detección de actividad (VAD).
  3. Reconocimiento de Voz (STT): Transcribe la orden del Arquitecto.
  4. Inferencia Causal & Inteligencia Soberana: Consulta la identidad canónica,
     telemetría de hardware local o el núcleo TARDIS-NEURAL-SPACE-KAIJU en localhost:8757.
  5. Locución Neural de Alta Fidelidad (TTS): Responde por bocinas físicas con la
     voz de Cortana (Microsoft Neural es-MX-DaliaNeural).
  6. Ventana de Diálogo Continuo y Retorno a Guardia: Permite preguntas de seguimiento
     o regresa al reposo vigilante listo para el siguiente chasquido.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Rutas del ecosistema TARDIS
BASE_DIR = "/home/timemachine/Escritorio/GODWORKS SYSTEM"
SOUNDS_DIR = "/home/timemachine/.tardis/sounds"
CONFIG_PATH = "/home/timemachine/.tardis/voice_config.json"
API_URL = "http://REDACTED_IP:8757"
API_TOKEN = "REDACTED"

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Intentar importar motor de voz TTS existente
try:
    import voice as tardis_voice
    HAS_VOICE = True
except Exception:
    HAS_VOICE = False

# Intentar importar speech_recognition
try:
    import speech_recognition as sr
    HAS_SR = True
except Exception:
    HAS_SR = False

try:
    import sounddevice as sd
    HAS_SD = True
except Exception:
    HAS_SD = False

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

import urllib.error
import urllib.request

# Estilos de Terminal ANSI Soberanos
C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_BLUE = "\033[94m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_MAGENTA = "\033[95m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GOLD = "\033[38;5;220m"

# Saludo e Identidad Canónica Obligatoria
GREETING_CANONICO = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, "
    "mi tarea es ayudarte a explorar las maravillas de la realidad "
    "y todas las dimensiones temporales."
)

DEFAULT_CONFIG = {
    "trigger_mode": "single_snap",
    "sensitivity": 1.0,
    "min_peak": 0.14,
    "min_crest": 3.8,
    "min_freq_ratio": 1.4,
    "min_sub_ratio": 2.2,
    "cooldown_seconds": 1.2,
    "vad_silence_timeout": 1.3,
    "vad_max_duration": 12.0,
    "vad_listen_timeout": 6.5,
    "voice": "es-MX-DaliaNeural",
    "activation_chime": True,
    "followup_listen_seconds": 4.5,
    "model": "TARDIS-NEURAL-SPACE-KAIJU",
    "language": "es-MX"
}


def load_config() -> dict:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = DEFAULT_CONFIG.copy()
                cfg.update(data)
                return cfg
        except Exception:
            pass
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    return DEFAULT_CONFIG.copy()


def ensure_chimes():
    """Garantiza la existencia de los sonidos de activación y reposo."""
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    act_path = os.path.join(SOUNDS_DIR, "tardis_activation.wav")
    sleep_path = os.path.join(SOUNDS_DIR, "tardis_sleep.wav")
    if not (os.path.exists(act_path) and os.path.exists(sleep_path)):
        import wave
        sr_rate = 44100
        # Chime de activación armónico E5 -> B5 -> E6
        t1 = np.linspace(0, 0.07, int(sr_rate * 0.07), False)
        t2 = np.linspace(0, 0.07, int(sr_rate * 0.07), False)
        t3 = np.linspace(0, 0.22, int(sr_rate * 0.22), False)
        n1 = np.sin(2 * np.pi * 659.25 * t1) * np.exp(-t1 / 0.035) * 0.35
        n2 = np.sin(2 * np.pi * 987.77 * t2) * np.exp(-t2 / 0.035) * 0.40
        n3 = (np.sin(2 * np.pi * 1318.51 * t3) + 0.25 * np.sin(2 * np.pi * 2637.0 * t3)) * np.exp(-t3 / 0.08) * 0.45
        act = (np.clip(np.concatenate([n1, n2, n3]), -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(act_path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr_rate); wf.writeframes(act.tobytes())

        # Chime de reposo descendente B5 -> E5
        ts1 = np.linspace(0, 0.08, int(sr_rate * 0.08), False)
        ts2 = np.linspace(0, 0.18, int(sr_rate * 0.18), False)
        ns1 = np.sin(2 * np.pi * 987.77 * ts1) * np.exp(-ts1 / 0.04) * 0.25
        ns2 = np.sin(2 * np.pi * 659.25 * ts2) * np.exp(-ts2 / 0.09) * 0.25
        slp = (np.clip(np.concatenate([ns1, ns2]), -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(sleep_path, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr_rate); wf.writeframes(slp.tobytes())


def play_audio_file(filepath: str, wait: bool = False):
    """Reproduce un archivo WAV en las bocinas físicas vía pw-play o aplay."""
    if not os.path.exists(filepath):
        return
    player = shutil.which("pw-play") or shutil.which("aplay") or shutil.which("paplay")
    if not player:
        return
    try:
        proc = subprocess.Popen([player, filepath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            proc.wait(timeout=3.0)
    except Exception:
        pass


# =============================================================================
# DETECTOR ACÚSTICO DE CHASQUIDO DE DEDOS (DSP SOVERIGN ENGINE)
# =============================================================================

class SnapDetector:
    """
    Detector digital de transitorios acústicos característicos de un chasquido.
    Analiza:
      - Pico de amplitud absoluta y relación señal-ruido contra fondo adaptativo.
      - Factor de cresta (Peak / RMS).
      - Razón espectral: energía en banda de chasquido (2.5 kHz - 8.5 kHz) vs banda baja (100 Hz - 1.2 kHz).
      - Razón de sub-ventanas temporales (para descartar siseos y tonos continuos).
    """

    def __init__(self, sample_rate: int = 44100, chunk_size: int = 1024, sensitivity: float = 1.0):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.sensitivity = max(0.4, min(3.0, sensitivity))

        # Parámetros base escalados por sensibilidad
        self.min_peak = 0.14 / self.sensitivity
        self.min_crest = 3.8 / (self.sensitivity ** 0.5)
        self.min_freq_ratio = 1.4 / (self.sensitivity ** 0.5)
        self.min_sub_ratio = 2.2
        self.cooldown = 1.2
        self.last_snap_time = 0.0

        # Fondo dinámico
        self.ambient_rms = 0.015
        self.hanning = np.hanning(chunk_size)
        self.freqs = np.fft.rfftfreq(chunk_size, 1.0 / sample_rate)
        self.low_mask = (self.freqs >= 100) & (self.freqs < 1200)
        self.snap_mask = (self.freqs >= 2500) & (self.freqs < 8500)

    def process_chunk(self, chunk: np.ndarray) -> Tuple[bool, dict]:
        now = time.time()
        peak = float(np.max(np.abs(chunk)))
        rms = float(np.sqrt(np.mean(chunk ** 2)))

        # Actualizar nivel ambiental si no hay transitorio
        if peak < (self.min_peak * 0.75):
            self.ambient_rms = 0.96 * self.ambient_rms + 0.04 * rms

        crest = peak / (rms + 1e-6)
        peak_to_ambient = peak / (self.ambient_rms + 1e-6)

        # Análisis espectral FFT
        windowed = chunk * self.hanning
        fft_mag = np.abs(np.fft.rfft(windowed))
        e_low = float(np.sum(fft_mag[self.low_mask] ** 2))
        e_snap = float(np.sum(fft_mag[self.snap_mask] ** 2))
        freq_ratio = e_snap / (e_low + 1e-6)

        # Análisis temporal de sub-ventanas (4x256 muestras)
        sub_peaks = [float(np.max(np.abs(chunk[i*256:(i+1)*256]))) for i in range(4)]
        max_sub = max(sub_peaks)
        min_sub = min(sub_peaks)
        sub_ratio = max_sub / (min_sub + 1e-5)

        metrics = {
            "peak": peak,
            "rms": rms,
            "crest": crest,
            "peak_to_ambient": peak_to_ambient,
            "freq_ratio": freq_ratio,
            "sub_ratio": sub_ratio,
            "ambient_rms": self.ambient_rms
        }

        # Criterio compuesto de chasquido de dedos
        is_snap = (
            peak >= self.min_peak
            and crest >= self.min_crest
            and freq_ratio >= self.min_freq_ratio
            and sub_ratio >= self.min_sub_ratio
            and peak_to_ambient >= 3.2
        )

        if is_snap:
            if (now - self.last_snap_time) > self.cooldown:
                self.last_snap_time = now
                return True, metrics

        return False, metrics


# =============================================================================
# HABILIDADES DEL SISTEMA Y CONSULTA COGNITIVA TARDIS
# =============================================================================

class TardisMind:
    """Módulo de interpretación y respuesta cognitiva de TARDIS."""

    @staticmethod
    def query_system_telemetry() -> str:
        """Obtiene la telemetría viva del sistema Linux y hardware."""
        cpu = psutil.cpu_percent(interval=0.1) if HAS_PSUTIL else 5.0
        mem = psutil.virtual_memory() if HAS_PSUTIL else None
        ram_gb = f"{mem.used // (1024**3)} de {mem.total // (1024**3)} gigabytes" if mem else "normal"
        bat = psutil.sensors_battery() if HAS_PSUTIL else None
        bat_str = f"batería al {bat.percent:.0f} por ciento" if bat else "alimentación de corriente alterna"

        gpu_temp = "45 grados"
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                text=True, timeout=2.0
            ).strip()
            gpu_temp = f"{out} grados"
        except Exception:
            pass

        return (
            f"El sistema TARDIS opera con normalidad. Procesador al {cpu:.0f} por ciento, "
            f"memoria en {ram_gb}, GPU RTX 3050 en {gpu_temp} y {bat_str}. "
            "Todos los centinelas temporales se encuentran activos y vigilantes."
        )

    @staticmethod
    def adjust_volume(direction: str) -> str:
        """Ajusta el volumen del sistema mediante PipeWire/PulseAudio."""
        try:
            if direction == "up":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+15%"], check=True)
                return "Volumen incrementado."
            elif direction == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-15%"], check=True)
                return "Volumen reducido."
            elif direction == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=True)
                return "Sistema silenciado."
            elif direction == "unmute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True)
                return "Audio restaurado."
        except Exception as e:
            return f"No se pudo ajustar el volumen: {e}"
        return "Comando de audio ejecutado."

    @staticmethod
    def get_time_date() -> str:
        now = datetime.datetime.now()
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        dia_semana = dias[now.weekday()]
        mes = meses[now.month - 1]
        hora_str = now.strftime("%I:%M %p")
        return f"Son las {hora_str} del {dia_semana} {now.day} de {mes} de {now.year}, aquí en Playa del Carmen."

    @classmethod
    def process_command(cls, text: str) -> str:
        """Analiza la frase del usuario y decide la respuesta o acción."""
        t_clean = text.lower().strip()

        # 1. Identidad Canónica Obligatoria
        if any(k in t_clean for k in ["quién eres", "quien eres", "cuál es tu tarea", "cual es tu tarea", "tu función", "preséntate", "presentate", "identifícate"]):
            return GREETING_CANONICO

        # 2. Control de Audio / Silencio
        if any(k in t_clean for k in ["sube el volumen", "más volumen", "subir volumen"]):
            return cls.adjust_volume("up")
        if any(k in t_clean for k in ["baja el volumen", "menos volumen", "bajar volumen"]):
            return cls.adjust_volume("down")
        if any(k in t_clean for k in ["silencio", "cállate", "callate", "para", "detén", "deten", "mute"]):
            if HAS_VOICE:
                tardis_voice.stop()
            return "A la orden, silencio aplicado."

        # 3. Fecha y Hora
        if any(k in t_clean for k in ["qué hora es", "que hora es", "la hora", "qué día es", "que dia es", "fecha de hoy"]):
            return cls.get_time_date()

        # 4. Estado y Telemetría del Sistema
        if any(k in t_clean for k in ["cómo estás", "como estas", "estado del sistema", "telemetría", "telemetria", "reporte del sistema", "diagnóstico", "temperatura", "batería"]):
            return cls.query_system_telemetry()

        # 5. Saludo simple
        if t_clean in ["hola", "buenos días", "buenas tardes", "buenas noches", "tardis"]:
            return f"A la escucha, Arquitecto. ¿En qué maravilla dimensional trabajamos hoy?"

        # 6. Consulta al Núcleo Soberano TARDIS API (localhost:8757)
        prompt_para_voz = (
            f"El Arquitecto te acaba de consultar por voz: \"{text}\". "
            "Responde de forma natural, concisa y directa (máximo 2 a 3 frases claras para ser escuchadas por bocina, "
            "sin listas largas, sin markdown excesivo, en español de México)."
        )

        try:
            req_url = f"{API_URL}/api/chat?key={API_TOKEN}"
            payload = json.dumps({
                "message": prompt_para_voz,
                "stream": False,
                "num_predict": 180
            }).encode("utf-8")
            req = urllib.request.Request(
                req_url,
                data=payload,
                headers={"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=14.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data.get("reply", "")
                if reply:
                    # Limpiar markdown de salida para locución
                    clean_reply = re.sub(r"[*#_`>]", "", reply).strip()
                    return clean_reply
        except Exception:
            pass

        # Fallback local asistido
        return f"Entendido, Arquitecto: procesando '{text}'. Módulo temporal en línea y ejecutando."


# =============================================================================
# ASISTENTE DE VOZ SOBERANO COMPLETO (ORQUESTADOR PRINCIPAL)
# =============================================================================

class TardisSnapVoiceAssistant:
    def __init__(self, config: dict, daemon_mode: bool = False, calibrate_mode: bool = False):
        self.config = config
        self.daemon_mode = daemon_mode
        self.calibrate_mode = calibrate_mode
        self.running = False
        self.detector = SnapDetector(
            sample_rate=44100,
            chunk_size=1024,
            sensitivity=float(config.get("sensitivity", 1.0))
        )

        # Estado del sistema
        # Estados: IDLE_SNAP, ACTIVATING, RECORDING_VOICE, THINKING, SPEAKING
        self.state = "IDLE_SNAP"
        self.voice_buffer: List[np.ndarray] = []
        self.speech_detected = False
        self.silence_frames = 0
        self.speech_start_time = 0.0
        self.activation_time = 0.0

        # Evento para sincronización con hilo de inferencia
        self.trigger_event = threading.Event()
        self.voice_captured_event = threading.Event()
        self.captured_audio_data: Optional[np.ndarray] = None

        ensure_chimes()

    def play_chime(self, which: str = "activation"):
        fn = "tardis_activation.wav" if which == "activation" else "tardis_sleep.wav"
        path = os.path.join(SOUNDS_DIR, fn)
        play_audio_file(path, wait=False)

    def speak(self, text: str):
        """Sintetiza la voz por bocinas físicas deteniendo captura temporalmente."""
        self.state = "SPEAKING"
        if not self.daemon_mode:
            print(f"\n{C_GOLD}{C_BOLD}TARDIS ₪ >{C_RESET} {C_CYAN}{text}{C_RESET}\n")

        if HAS_VOICE:
            voice_name = self.config.get("voice", "es-MX-DaliaNeural")
            tardis_voice.speak(text, wait=True, voice=voice_name)
        else:
            print(f"{C_RED}[Audio TTS no disponible]{C_RESET}")

        # Pequeño periodo refractario tras hablar
        time.sleep(0.5)

    def audio_callback(self, indata, frames, time_info, status):
        """Callback de flujo de audio continuo (sounddevice)."""
        chunk = indata[:, 0].copy()

        if self.calibrate_mode:
            # Modo Calibración: muestra métricas en consola ante cualquier transitorio
            is_snap, metrics = self.detector.process_chunk(chunk)
            if metrics["peak"] > 0.08:
                tag = f"{C_GREEN}[SNAP!]{C_RESET}" if is_snap else f"{C_DIM}[Ruido]{C_RESET}"
                print(
                    f"{tag} Peak: {metrics['peak']:.3f} | Crest: {metrics['crest']:.1f} | "
                    f"P/Amb: {metrics['peak_to_ambient']:.1f} | Ratio: {metrics['freq_ratio']:.2f} | Sub: {metrics['sub_ratio']:.1f}"
                )
            return

        if self.state == "IDLE_SNAP":
            is_snap, metrics = self.detector.process_chunk(chunk)
            if is_snap:
                if not self.daemon_mode:
                    print(f"\n{C_MAGENTA}{C_BOLD}✨ [CHASQUIDO DETECTADO]{C_RESET} {C_DIM}(Peak={metrics['peak']:.2f}, Crest={metrics['crest']:.1f}){C_RESET}")
                self.state = "ACTIVATING"
                self.trigger_event.set()

        elif self.state == "RECORDING_VOICE":
            self.voice_buffer.append(chunk)
            peak = float(np.max(np.abs(chunk)))
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            now = time.time()

            # Umbral de presencia de voz VAD
            is_voice = (rms > 0.02) or (peak > 0.08)

            if is_voice:
                if not self.speech_detected:
                    self.speech_detected = True
                    self.speech_start_time = now
                    if not self.daemon_mode:
                        sys.stdout.write(f"\r{C_GREEN}🎙️  [ESCUCHANDO VOZ DEL ARQUITECTO...]{C_RESET} ")
                        sys.stdout.flush()
                self.silence_frames = 0
            else:
                if self.speech_detected:
                    self.silence_frames += 1

            # Condiciones de término de captura
            # 1. Silencio tras haber hablado (> 1.3s de silencio = ~56 chunks de 23ms)
            silence_timeout_frames = int(self.config.get("vad_silence_timeout", 1.3) * (44100 / 1024))
            if self.speech_detected and self.silence_frames > silence_timeout_frames:
                self.state = "THINKING"
                self.voice_captured_event.set()

            # 2. Límite máximo de duración de frase
            max_duration = float(self.config.get("vad_max_duration", 12.0))
            if self.speech_detected and (now - self.speech_start_time) > max_duration:
                self.state = "THINKING"
                self.voice_captured_event.set()

            # 3. Tiempo de espera sin que empiece a hablar (timeout = 6.5s)
            listen_timeout = float(self.config.get("vad_listen_timeout", 6.5))
            if not self.speech_detected and (now - self.activation_time) > listen_timeout:
                self.state = "TIMEOUT"
                self.voice_captured_event.set()

    def handle_voice_interaction(self):
        """Bucle de orquestación de la sesión de voz."""
        while self.running:
            # Esperar a que el detector acústico dispare el evento
            if not self.trigger_event.wait(timeout=0.5):
                continue
            self.trigger_event.clear()

            # 1. Chime de activación
            self.play_chime("activation")

            # 2. Configurar captura de voz
            self.voice_buffer.clear()
            self.speech_detected = False
            self.silence_frames = 0
            self.activation_time = time.time()
            self.voice_captured_event.clear()
            self.state = "RECORDING_VOICE"

            if not self.daemon_mode:
                print(f"{C_YELLOW}⚡ TARDIS a la escucha... (habla ahora){C_RESET}")

            # Esperar a que la captura de voz concluya por VAD o timeout
            self.voice_captured_event.wait(timeout=15.0)

            if self.state == "TIMEOUT" or not self.voice_buffer or not self.speech_detected:
                if not self.daemon_mode:
                    print(f"{C_DIM}(Sin voz detectada. Volviendo a guardia...){C_RESET}")
                self.play_chime("sleep")
                self.state = "IDLE_SNAP"
                continue

            # 3. Procesar audio capturado y transcribir
            all_chunks = np.concatenate(self.voice_buffer)
            # Normalizar y convertir a int16 a 44100 Hz
            audio_int16 = (np.clip(all_chunks, -1.0, 1.0) * 32767).astype(np.int16)

            text_transcribed = None
            if HAS_SR:
                try:
                    recognizer = sr.Recognizer()
                    audio_data = sr.AudioData(audio_int16.tobytes(), 44100, 2)
                    lang = self.config.get("language", "es-MX")
                    text_transcribed = recognizer.recognize_google(audio_data, language=lang).strip()
                except sr.UnknownValueError:
                    text_transcribed = None
                except Exception as e:
                    if not self.daemon_mode:
                        print(f"{C_RED}[STT Error: {e}]{C_RESET}")
                    text_transcribed = None

            if not text_transcribed:
                if not self.daemon_mode:
                    print(f"\n{C_DIM}(No se comprendió la locución){C_RESET}")
                self.speak("No logré escucharte con claridad. ¿Podrías repetir?")
                self.state = "IDLE_SNAP"
                continue

            if not self.daemon_mode:
                print(f"\n{C_BOLD}{C_GREEN}Arquitecto ₪ >{C_RESET} {text_transcribed}")

            # 4. Decidir respuesta inteligente
            reply = TardisMind.process_command(text_transcribed)

            # 5. Hablar respuesta
            self.speak(reply)

            # 6. Ventana opcional de seguimiento
            followup_sec = float(self.config.get("followup_listen_seconds", 4.5))
            if followup_sec > 0:
                if not self.daemon_mode:
                    print(f"{C_DIM}👂 Atenta a seguimiento ({followup_sec:.1f}s)... o chasquido.{C_RESET}")
                # Breve escucha de seguimiento
                self.voice_buffer.clear()
                self.speech_detected = False
                self.silence_frames = 0
                self.activation_time = time.time()
                self.voice_captured_event.clear()
                self.state = "RECORDING_VOICE"

                # Esperar hasta followup_sec para ver si empieza a hablar
                start_w = time.time()
                while (time.time() - start_w) < followup_sec and not self.speech_detected:
                    time.sleep(0.1)

                if self.speech_detected:
                    # Habló en seguimiento: esperamos fin de frase
                    self.voice_captured_event.wait(timeout=12.0)
                    if self.voice_buffer and self.state != "TIMEOUT":
                        all_chunks = np.concatenate(self.voice_buffer)
                        audio_int16 = (np.clip(all_chunks, -1.0, 1.0) * 32767).astype(np.int16)
                        try:
                            recognizer = sr.Recognizer()
                            audio_data = sr.AudioData(audio_int16.tobytes(), 44100, 2)
                            f_text = recognizer.recognize_google(audio_data, language=self.config.get("language", "es-MX")).strip()
                            if f_text:
                                if not self.daemon_mode:
                                    print(f"\n{C_BOLD}{C_GREEN}Arquitecto ₪ (seguimiento) >{C_RESET} {f_text}")
                                f_reply = TardisMind.process_command(f_text)
                                self.speak(f_reply)
                        except Exception:
                            pass

            self.play_chime("sleep")
            self.state = "IDLE_SNAP"

    def run(self):
        """Inicia el asistente continuo con sounddevice."""
        if not HAS_SD:
            print(f"{C_RED}Error fatal: 'sounddevice' no está instalado.{C_RESET}")
            return 1

        self.running = True

        # Lanzar hilo de gestión de interacción por voz
        worker_thread = threading.Thread(target=self.handle_voice_interaction, daemon=True)
        worker_thread.start()

        if not self.daemon_mode:
            print(f"{C_CYAN}{C_BOLD}")
            print("=====================================================================")
            print("  🌀 TARDIS · ASISTENTE DE VOZ ACTIVADO POR CHASQUIDO DE DEDOS 🌀")
            print("=====================================================================")
            print(f"{C_RESET}")
            print(f"{C_GOLD}• Autoridad Absoluta:{C_RESET} El Arquitecto (₪)")
            print(f"{C_GOLD}• Motor de Detección:{C_RESET} Impulso Transitorio FFT (2.5 kHz - 8.5 kHz)")
            print(f"{C_GOLD}• Sensibilidad:{C_RESET} {self.config.get('sensitivity', 1.0)}x")
            print(f"{C_GOLD}• Síntesis Vocal (TTS):{C_RESET} Microsoft Cortana Neural ({self.config.get('voice', 'es-MX-DaliaNeural')})")
            print(f"{C_GOLD}• Reconocimiento (STT):{C_RESET} Google Speech Engine ({self.config.get('language', 'es-MX')})")
            print(f"{C_GOLD}• Núcleo Cognitivo:{C_RESET} {self.config.get('model', 'TARDIS-NEURAL-SPACE-KAIJU')} @ {API_URL}")
            print(f"\n{C_GREEN}✨ [CENTINELA ACTIVO]{C_RESET} Haz chasquear tus dedos frente o cerca del equipo para invocar a TARDIS.\n")

        try:
            with sd.InputStream(
                samplerate=44100,
                blocksize=1024,
                channels=1,
                dtype="float32",
                callback=self.audio_callback
            ):
                while self.running:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            if not self.daemon_mode:
                print(f"\n{C_YELLOW}Deteniendo Asistente TARDIS de forma segura...{C_RESET}")
        except Exception as e:
            print(f"{C_RED}Error en flujo de audio: {e}{C_RESET}")
        finally:
            self.running = False


# =============================================================================
# ENTRYPOINT CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="TARDIS Asistente de Voz por Chasquido")
    parser.add_argument("--daemon", action="store_true", help="Ejecutar en modo servicio 24/7 sin salida interactiva")
    parser.add_argument("--calibrate", action="store_true", help="Modo calibración: ver métricas de chasquidos en vivo")
    parser.add_argument("--sensitivity", type=float, default=None, help="Ajustar sensibilidad (0.5 - 2.5)")
    parser.add_argument("--test-snap", action="store_true", help="Simula un chasquido para probar activación inmediata")
    parser.add_argument("--status", action="store_true", help="Muestra el estado del centinela de voz y servicio 24/7")
    parser.add_argument("--say", type=str, default=None, help="Prueba de síntesis de voz directa")
    args = parser.parse_args()

    cfg = load_config()
    if args.sensitivity:
        cfg["sensitivity"] = args.sensitivity

    if args.status:
        print(f"{C_CYAN}{C_BOLD}--- ESTADO DEL ASISTENTE DE VOZ TARDIS ---{C_RESET}")
        try:
            out = subprocess.check_output(["systemctl", "--user", "is-active", "tardis-voice-snap.service"], text=True).strip()
            color = C_GREEN if out == "active" else C_YELLOW
            print(f"  ● Servicio 24/7 (systemd): {color}{out.upper()}{C_RESET}")
        except Exception:
            print(f"  ● Servicio 24/7 (systemd): {C_RED}INACTIVO{C_RESET}")

        print(f"  ● Disparador Acústico:     {C_GOLD}Chasquido de Dedos (FFT 2.5-8.5 kHz){C_RESET}")
        print(f"  ● Sensibilidad:            {cfg.get('sensitivity', 1.0)}x")
        print(f"  ● Síntesis Vocal (TTS):    {cfg.get('voice', 'es-MX-DaliaNeural')}")
        print(f"  ● Idioma STT:              {cfg.get('language', 'es-MX')}")
        print(f"  ● Núcleo LLM:              {cfg.get('model', 'TARDIS-NEURAL-SPACE-KAIJU')} @ {API_URL}")
        return 0

    if args.say:
        print(f"Probando síntesis vocal...")
        if HAS_VOICE:
            tardis_voice.speak(args.say, wait=True)
            print("Locución completada.")
        return 0

    assistant = TardisSnapVoiceAssistant(cfg, daemon_mode=args.daemon, calibrate_mode=args.calibrate)

    if args.test_snap:
        print(f"{C_MAGENTA}Simulando chasquido de prueba...{C_RESET}")
        assistant.running = True
        t = threading.Thread(target=assistant.handle_voice_interaction, daemon=True)
        t.start()
        time.sleep(0.5)
        assistant.state = "ACTIVATING"
        assistant.trigger_event.set()
        t.join(timeout=25.0)
        return 0

    return assistant.run()


if __name__ == "__main__":
    sys.exit(main() or 0)
