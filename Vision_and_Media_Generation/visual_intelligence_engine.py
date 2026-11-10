"""
core/visual_intelligence_engine.py - Motor Soberano de Inteligencia Visual de TARDIS
=====================================================================================
GODWORKS SYSTEM v26.4 · Suite Soberana TARDIS (TARDIS-NEURAL-SPACE-KAIJU Core)
Adaptado para: ASUS TUF A15 (AMD Ryzen 7 4800H, 32 GB RAM, NVIDIA RTX 3050 4GB VRAM)

Capacidades Centrales:
  1. Percepción Multimodal Total:
     - Visión de Video: Desglose temporal de escenas, keyframes adaptativos, flujo óptico,
       dinámica de movimiento, rostros/cuerpos y OCR en tiempo real sobre cada fotograma.
     - Visión de Imagen: Cromatismo, contraste, nitidez (Laplaciano), OCR multilingüe y detección.
     - Percepción Acústica: Extracción de pista de audio con ffmpeg, transcripción ultra-rápida
       de habla con Whisper LPU (Groq) / Google STT, y métricas psicoacústicas (RMS, energía, tono).
  2. Síntesis Cognitiva y Deducción Causal (Conclusiones de TARDIS):
     - Fusión de señales ópticas + transcripción de audio + telemetría temporal.
     - Deducción analítica profunda mediante TARDIS-NEURAL-SPACE-KAIJU / Kaiju Cognitive Orchestrator.
  3. Bóveda y Almacenamiento Permanente:
     - Almacenamiento seguro e indexación en base de datos SQLite y Bóveda RAG / Akasha.
     - Archivo automático de todo video recibido por Telegram, Spool o API.
  4. Ejecución 24/7 y Multicapa:
     - Motor en segundo plano desacoplado para invocación síncrona o asíncrona.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

try:
    import pytesseract
    HAS_PYTESSERACT = True
except Exception:
    HAS_PYTESSERACT = False

import requests

# Configuración de rutas
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

VAULT_DIR = BASE_DIR / "vault"
VIDEOS_TELEGRAM_DIR = VAULT_DIR / "videos" / "telegram"
IMAGES_VAULT_DIR = VAULT_DIR / "images"
SPOOL_DIR = VAULT_DIR / "visual_intelligence" / "spool"
DATA_DIR = BASE_DIR / "data" / "visual_intelligence"
FRAMES_CACHE_DIR = DATA_DIR / "frames"
DB_PATH = DATA_DIR / "visual_memory.db"

# Asegurar directorios
for d in (VIDEOS_TELEGRAM_DIR, IMAGES_VAULT_DIR, SPOOL_DIR, DATA_DIR, FRAMES_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Crear enlace en ~/Vídeos si existe
USER_VIDEOS_DIR = Path(os.path.expanduser("~")) / "Vídeos" / "tardis_telegram_videos"
try:
    USER_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    symlink_path = USER_VIDEOS_DIR / "boveda_telegram"
    if not symlink_path.exists():
        symlink_path.symlink_to(VIDEOS_TELEGRAM_DIR)
except Exception:
    pass

logger = logging.getLogger("TARDIS.VisualIntelligence")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] [VisualIntelligence] [%(levelname)s] %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

OPENCV_DATA_DIR = Path("/usr/share/opencv4/haarcascades")
HAAR_FACE = OPENCV_DATA_DIR / "haarcascade_frontalface_default.xml"
HAAR_PROFILE = OPENCV_DATA_DIR / "haarcascade_profileface.xml"
HAAR_BODY = OPENCV_DATA_DIR / "haarcascade_upperbody.xml"

# ------------------------------------------------------------------------------
# PERCEPCIÓN VISUAL MULTIMODAL (VLM) + VEREDICTOS SOBERANOS
# ------------------------------------------------------------------------------

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
if not OLLAMA_URL.startswith(("http://", "https://")):
    OLLAMA_URL = f"http://{OLLAMA_URL}"

# Modelos multimodales locales ordenados por preferencia (Qwen3-VL > Qwen2.5-VL > MiniCPM > Llama Vision > LLaVA)
VLM_MODEL_PREFERENCES = (
    "qwen3-vl:2b-instruct",
    "qwen3-vl:2b-instruct-q4_K_M",
    "qwen3-vl:4b-instruct",
    "qwen3-vl:2b",
    "qwen3-vl:4b",
    "qwen3-vl:latest",
    "qwen2.5vl:3b",
    "qwen2.5vl:7b",
    "qwen2.5-vl:3b",
    "qwen2.5-vl:7b",
    "qwen2.5-vl:latest",
    "minicpm-v:latest",
    "llama3.2-vision:11b",
    "llama3.2-vision:latest",
    "llava:7b",
    "llava:latest",
    "moondream:latest",
    "bakllava:latest",
)

VLM_PERCEPTION_PROMPT = (
    "Eres el módulo de percepción visual de TARDIS. Analiza esta imagen como un observador "
    "forense y descriptivo. Enumera con precisión: 1) PERSONAS: cuántas hay, apariencia, ropa, "
    "postura y qué hacen (si no hay, dilo). 2) OBJETOS: todos los objetos visibles y su posición "
    "relativa (mesa, silla, pantalla, herramientas, vehículos, animales). 3) ENTORNO: interior o "
    "exterior, habitación, muebles, puertas, ventanas, iluminación, clima. 4) TEXTO: cualquier "
    "texto, letrero, etiqueta o número legible. 5) SEGURIDAD: posibles riesgos visibles (cables, "
    "fuego, humo, agua, armas, herramientas peligrosas, obstáculos, desconocidos). 6) ANOMALÍAS: "
    "cualquier cosa fuera de lugar. Sé literal y objetivo: describe solo lo que ves, sin inventar. "
    "Responde en español, en texto plano y con detalle."
)

VERDICT_PROMPT = (
    "Un placer, soy TARDIS asistente de inteligencia artificial, mi tarea es ayudarte a explorar "
    "las maravillas de la realidad y todas las dimensiones temporales. Emite un VEREDICTO claro, "
    "directo y útil sobre lo que rodea al Arquitecto. Distingue entre hechos observados, "
    "inferencias y dudas. Incluye siempre: estado general del entorno, nivel de riesgo objetivo "
    "de 0 a 10, y una recomendación concreta si procede. No inventes identidades ni datos que no "
    "puedas ver."
)


@dataclass
class VisualAnalysisResult:
    """Resultado estructurado de percepción y conclusiones de Inteligencia Visual."""
    id: str
    media_type: str  # "video" | "image" | "sound"
    source: str      # "telegram" | "api" | "spool" | "local"
    file_path: str
    file_name: str
    file_size_bytes: int
    duration_sec: float
    width: int
    height: int
    fps: float
    keyframe_count: int
    keyframe_paths: List[str]
    detected_faces: int
    detected_text_ocr: str
    dominant_colors: List[str]
    motion_intensity: float
    audio_present: bool
    audio_transcript: str
    acoustic_profile: Dict[str, Any]
    summary: str
    visual_description: str
    audio_description: str
    conclusions: str
    full_report: str
    verdict: str = ""
    verdict_data: Dict[str, Any] = field(default_factory=dict)
    vision_engine: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    elapsed_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VisualIntelligenceEngine:
    """
    Motor Soberano TARDIS de Inteligencia Visual.
    Analiza y comprende videos, imágenes y sonidos, extrayendo conclusiones causales.
    """

    _instance: Optional["VisualIntelligenceEngine"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "VisualIntelligenceEngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()
        # Inicialización segura de clasificadores de rostros (compatible con OpenCV 4 y 5)
        cascade_cls = getattr(cv2, "CascadeClassifier", None)
        if cascade_cls and HAAR_FACE.exists():
            try:
                self._face_cascade = cascade_cls(str(HAAR_FACE))
            except Exception:
                self._face_cascade = None
        else:
            self._face_cascade = None

        if cascade_cls and HAAR_BODY.exists():
            try:
                self._body_cascade = cascade_cls(str(HAAR_BODY))
            except Exception:
                self._body_cascade = None
        else:
            self._body_cascade = None

        # Detector de códigos QR / códigos visuales nativo de OpenCV
        self._qr_detector = cv2.QRCodeDetector() if hasattr(cv2, "QRCodeDetector") else None

        # Caché de descubrimiento del modelo VLM local
        self._vlm_model_cache: Optional[str] = None
        self._vlm_checked_at: float = 0.0
        self._vlm_last_error: str = ""

    def _init_db(self):
        """Inicializa la base de datos de memoria visual estructurada."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS visual_records (
                    id TEXT PRIMARY KEY,
                    media_type TEXT,
                    source TEXT,
                    file_path TEXT,
                    file_size INTEGER,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    fps REAL,
                    chat_id TEXT,
                    user_id TEXT,
                    user_name TEXT,
                    caption TEXT,
                    ocr_text TEXT,
                    audio_transcript TEXT,
                    summary TEXT,
                    visual_description TEXT,
                    conclusions TEXT,
                    metadata_json TEXT,
                    created_at TEXT
                )
            """)
            # Migración incremental: columnas de veredicto y motor de visión
            try:
                existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(visual_records)").fetchall()}
                for col_name, col_type in (("verdict", "TEXT"), ("vision_engine", "TEXT")):
                    if col_name not in existing_cols:
                        conn.execute(f"ALTER TABLE visual_records ADD COLUMN {col_name} {col_type}")
            except Exception as e_mig:
                logger.debug(f"Aviso migrando esquema de memoria visual: {e_mig}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vr_created ON visual_records(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vr_chat ON visual_records(chat_id)")
            conn.commit()

    # --------------------------------------------------------------------------
    # GESTIÓN DE CREDENCIALES Y APIS ACELERADAS
    # --------------------------------------------------------------------------

    def _get_groq_key(self) -> str:
        """Obtiene la clave de Groq desde la bóveda de configuración."""
        env_k = os.environ.get("GROQ_API_KEY", "").strip()
        if env_k:
            return env_k
        cfg_file = Path(os.path.expanduser("~")) / "vw-control" / "chinese_api_config.json"
        if cfg_file.exists():
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                k = data.get("api_keys", {}).get("groq_deepseek", "").strip()
                if k:
                    return k
            except Exception:
                pass
        return "REDACTED_GROQ"

    # --------------------------------------------------------------------------
    # PERCEPCIÓN VISUAL MULTIMODAL REAL (VLM LOCAL / NUBE SOBERANA)
    # --------------------------------------------------------------------------

    def _discover_vlm_model(self, force: bool = False) -> Optional[str]:
        """Descubre el mejor modelo de visión multimodal disponible en Ollama."""
        now = time.time()
        if not force and self._vlm_model_cache and (now - self._vlm_checked_at) < 120.0:
            return self._vlm_model_cache
        model: Optional[str] = None
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4.0)
            if r.status_code == 200:
                names = [str(m.get("name", "")) for m in r.json().get("models", [])]
                for pref in VLM_MODEL_PREFERENCES:
                    if pref in names:
                        model = pref
                        break
                if not model:
                    vision_tokens = ("qwen3-vl", "qwen2.5vl", "qwen2.5-vl", "minicpm-v",
                                     "llama3.2-vision", "llava", "moondream", "bakllava", "vision")
                    for name in names:
                        low = name.lower()
                        if any(tok in low for tok in vision_tokens):
                            model = name
                            break
        except Exception as e:
            self._vlm_last_error = f"Ollama no disponible: {e}"
        self._vlm_model_cache = model
        self._vlm_checked_at = now
        return model

    @staticmethod
    def _prepare_image_b64(image_source: Union[Path, str, bytes], max_side: int = 1600) -> str:
        """Normaliza y codifica una imagen en base64 lista para inferencia multimodal."""
        if isinstance(image_source, (str, Path)):
            raw = Path(image_source).read_bytes()
        else:
            raw = image_source
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=88, optimize=True)
            raw = buf.getvalue()
        except Exception:
            pass
        return base64.b64encode(raw).decode("utf-8")

    def _ollama_vision_call(self, b64_img: str, prompt: str, model: str) -> Dict[str, Any]:
        """Inferencia multimodal local en Ollama (privacidad soberana total)."""
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "images": [b64_img],
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0.15,
                    "num_ctx": 8192,
                    "num_predict": 900,
                },
            }
            r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=240)
            if r.status_code == 200:
                body = r.json()
                text = (body.get("response") or "").strip()
                if not text:
                    # Algunos modelos de razonamiento vuelcan todo en 'thinking'
                    text = (body.get("thinking") or "").strip()
                if text:
                    return {"ok": True, "engine": f"Ollama VLM ({model})", "model": model, "analysis": text}
            return {"ok": False, "engine": f"Ollama VLM ({model})", "model": model,
                    "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"ok": False, "engine": f"Ollama VLM ({model})", "model": model, "error": str(e)}

    def _gemini_vision_call(self, b64_img: str, prompt: str) -> Dict[str, Any]:
        """Inferencia multimodal en Gemini (fallback en nube si se configura API key)."""
        key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        if not key:
            try:
                import gemini_bridge as _gb
                key = (_gb.get_api_key() or "").strip()
            except Exception:
                key = ""
        if not key:
            return {"ok": False, "engine": "Gemini VLM", "error": "Sin API key de Google/Gemini"}
        model = os.environ.get("VLM_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                    ]
                }],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200},
            }
            r = requests.post(url, json=payload, headers={"x-goog-api-key": key}, timeout=90)
            if r.status_code == 200:
                parts = (r.json().get("candidates", [{}])[0].get("content", {}).get("parts", []) or [])
                text = "\n".join(str(p.get("text", "")) for p in parts).strip()
                if text:
                    return {"ok": True, "engine": f"Gemini VLM ({model})", "model": model, "analysis": text}
            return {"ok": False, "engine": f"Gemini VLM ({model})", "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"ok": False, "engine": f"Gemini VLM ({model})", "error": str(e)}

    def _openai_compatible_vision_call(self, b64_img: str, prompt: str) -> Dict[str, Any]:
        """Inferencia multimodal en cualquier endpoint compatible con OpenAI (OpenRouter, etc.)."""
        base_url = (os.environ.get("VLM_BASE_URL") or "").strip().rstrip("/")
        api_key = (os.environ.get("VLM_API_KEY") or "").strip()
        model = (os.environ.get("VLM_MODEL") or "").strip()
        if not (base_url and api_key and model):
            return {"ok": False, "engine": "OpenAI-compatible VLM", "error": "VLM_BASE_URL/VLM_API_KEY/VLM_MODEL no configurados"}
        try:
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}},
                    ],
                }],
                "temperature": 0.2,
                "max_tokens": 1200,
            }
            r = requests.post(f"{base_url}/chat/completions", json=payload,
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
            if r.status_code == 200:
                text = (r.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if text:
                    return {"ok": True, "engine": f"OpenAI-compatible VLM ({model})", "model": model, "analysis": text}
            return {"ok": False, "engine": f"OpenAI-compatible VLM ({model})", "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"ok": False, "engine": f"OpenAI-compatible VLM ({model})", "error": str(e)}

    def describe_image_with_vlm(
        self,
        image_source: Union[Path, str, bytes],
        context: str = "",
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Describe una imagen con un modelo de visión multimodal real.
        Orden: VLM local (Ollama) -> Gemini -> endpoint OpenAI-compatible -> sin VLM.
        """
        b64_img = self._prepare_image_b64(image_source)
        full_prompt = (prompt or VLM_PERCEPTION_PROMPT).strip()
        if context:
            full_prompt += f"\n\nPREGUNTA O DIRECTIVA DEL ARQUITECTO: {context.strip()}"

        provider = (os.environ.get("VLM_PROVIDER") or "auto").strip().lower()
        attempts: List[Dict[str, Any]] = []

        if provider in ("auto", "ollama", "local"):
            model = self._discover_vlm_model()
            if model:
                res = self._ollama_vision_call(b64_img, full_prompt, model)
                attempts.append(res)
                if res.get("ok"):
                    return res

        if provider in ("auto", "gemini", "google"):
            res = self._gemini_vision_call(b64_img, full_prompt)
            attempts.append(res)
            if res.get("ok") and len(res.get("analysis", "")) > 40:
                return res

        if provider in ("auto", "openai", "openrouter"):
            res = self._openai_compatible_vision_call(b64_img, full_prompt)
            attempts.append(res)
            if res.get("ok") and len(res.get("analysis", "")) > 40:
                return res

        # Si el VLM local respondió algo corto, rescatarlo antes que nada
        for res in attempts:
            if res.get("ok") and res.get("analysis"):
                return res

        return {
            "ok": False,
            "engine": "sin_vlm",
            "error": "; ".join(str(a.get("error", "")) for a in attempts if a.get("error")) or "Ningún VLM disponible",
            "analysis": "",
            "attempts": attempts,
        }

    # --------------------------------------------------------------------------
    # PROCESAMIENTO ACÚSTICO Y TRANSCRIPCIÓN DE AUDIO
    # --------------------------------------------------------------------------

    def extract_audio_from_video(self, video_path: Path, output_wav_path: Path) -> bool:
        """Extrae la pista de audio del video a formato WAV 16kHz mono."""
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(output_wav_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            return output_wav_path.exists() and output_wav_path.stat().st_size > 44
        except Exception as e:
            logger.warning(f"Aviso extrayendo audio con ffmpeg: {e}")
            return False

    def transcribe_audio_whisper(self, wav_bytes_or_path: Union[bytes, Path, str]) -> Tuple[str, Dict[str, Any]]:
        """
        Transcribe audio usando Groq Whisper LPU (sub-segundo) con fallback a Google STT.
        Retorna (texto_transcrito, perfil_acustico).
        """
        if isinstance(wav_bytes_or_path, (str, Path)):
            wav_bytes = Path(wav_bytes_or_path).read_bytes()
        else:
            wav_bytes = wav_bytes_or_path

        profile = {
            "duration_sec": 0.0,
            "rms_energy": 0.0,
            "speech_detected": False,
            "engine": "whisper-large-v3-turbo"
        }

        # Calcular métricas básicas del WAV
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                profile["duration_sec"] = round(frames / float(rate), 2)
                raw_data = wf.readframes(frames)
                samples = np.frombuffer(raw_data, dtype=np.int16)
                if len(samples) > 0:
                    profile["rms_energy"] = round(float(np.sqrt(np.mean(samples.astype(np.float64)**2))), 2)
        except Exception:
            pass

        if not wav_bytes or len(wav_bytes) < 500:
            return "", profile

        # 1. Intento primario: Groq Whisper LPU
        groq_key = self._get_groq_key()
        if groq_key:
            try:
                headers = {"Authorization": f"Bearer {groq_key}"}
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                data = {"model": "whisper-large-v3-turbo", "language": "es", "temperature": "0.0"}
                r = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=25.0
                )
                if r.status_code == 200:
                    txt = r.json().get("text", "").strip()
                    if txt:
                        profile["speech_detected"] = True
                        return txt, profile
            except Exception as e_groq:
                logger.debug(f"Aviso en Whisper LPU: {e_groq}")

        # 2. Fallback secundario: Google STT
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = recognizer.record(source)
            txt = recognizer.recognize_google(audio_data, language="es-MX").strip()
            if txt:
                profile["engine"] = "google_stt"
                profile["speech_detected"] = True
                return txt, profile
        except Exception:
            pass

        return "", profile

    # --------------------------------------------------------------------------
    # EXTRACCIÓN Y PERCEPCIÓN DE FOTOGRAMAS (KEYFRAMES)
    # --------------------------------------------------------------------------

    def get_video_telemetry(self, video_path: Path) -> Dict[str, Any]:
        """Obtiene especificaciones técnicas exactas del video vía OpenCV y ffprobe."""
        info = {
            "duration": 0.0,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "frame_count": 0,
            "codec": "unknown",
            "file_size": video_path.stat().st_size if video_path.exists() else 0
        }
        cap = cv2.VideoCapture(str(video_path))
        if cap.isOpened():
            info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            info["fps"] = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            info["frame_count"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if info["fps"] > 0:
                info["duration"] = round(info["frame_count"] / info["fps"], 2)
            cap.release()
        return info

    def extract_keyframes(
        self,
        video_path: Path,
        output_dir: Path,
        max_keyframes: int = 8
    ) -> List[Tuple[float, Path, np.ndarray]]:
        """
        Extrae fotogramas clave adaptativos a lo largo de la línea temporal.
        Retorna lista de (timestamp_sec, path_fotograma, imagen_cv2_rgb).
        """
        keyframes = []
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return keyframes

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        duration = total_frames / fps if fps > 0 else 0.0

        if total_frames <= 0:
            cap.release()
            return keyframes

        output_dir.mkdir(parents=True, exist_ok=True)

        # Distribuir muestras a lo largo del metraje
        if total_frames <= max_keyframes:
            sample_indices = list(range(total_frames))
        else:
            step = total_frames / float(max_keyframes)
            sample_indices = [int(i * step) for i in range(max_keyframes)]

        prev_gray = None
        for idx in sample_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame_bgr = cap.read()
            if not ret or frame_bgr is None:
                continue

            sec = round(idx / fps, 2) if fps > 0 else 0.0
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            k_path = output_dir / f"frame_{idx:05d}_{int(sec*100)}cs.jpg"

            # Guardar fotograma comprimido de alta definición
            cv2.imwrite(str(k_path), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            keyframes.append((sec, k_path, frame_rgb))

        cap.release()
        return keyframes

    def analyze_frame_features(self, frame_rgb: np.ndarray) -> Dict[str, Any]:
        """Extrae características ópticas, cromáticas y de rostros de un fotograma."""
        h, w, c = frame_rgb.shape
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

        # 1. Nitidez vía varianza Laplaciana
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 2. Brillo y contraste
        mean_brightness = float(np.mean(gray))
        contrast = float(np.std(gray))

        # 3. Paleta cromática dominante
        small = cv2.resize(frame_rgb, (64, 64))
        avg_r = int(np.mean(small[:, :, 0]))
        avg_g = int(np.mean(small[:, :, 1]))
        avg_b = int(np.mean(small[:, :, 2]))
        dominant_hex = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"

        # 4. Detección de rostros y personas
        faces_detected = 0
        if self._face_cascade:
            faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
            faces_detected = len(faces)

        # 5. Detección de texto OCR con pytesseract
        ocr_text = ""
        if HAS_PYTESSERACT:
            try:
                ocr_text = pytesseract.image_to_string(gray, lang="spa+eng").strip()
                ocr_text = re.sub(r"\s+", " ", ocr_text).strip()
            except Exception:
                pass

        # 6. Detección y decodificación de códigos QR en pantalla
        qr_data = ""
        if getattr(self, "_qr_detector", None):
            try:
                data, _, _ = self._qr_detector.detectAndDecode(gray)
                if data:
                    qr_data = data.strip()
            except Exception:
                pass

        return {
            "sharpness": round(laplacian_var, 1),
            "brightness": round(mean_brightness, 1),
            "contrast": round(contrast, 1),
            "dominant_hex": dominant_hex,
            "faces_count": faces_detected,
            "ocr_text": ocr_text,
            "qr_data": qr_data
        }

    # --------------------------------------------------------------------------
    # SÍNTESIS COGNITIVA Y GENERACIÓN DE CONCLUSIONES (TARDIS KAIJU)
    # --------------------------------------------------------------------------

    def _synthesize_conclusions_with_kaiju(
        self,
        media_type: str,
        tech_meta: Dict[str, Any],
        visual_timeline: List[Dict[str, Any]],
        ocr_corpus: str,
        audio_transcript: str,
        user_prompt: str = "",
        vlm_description: str = "",
        verdict_mode: bool = False,
    ) -> Dict[str, str]:
        """
        Sintetiza la información sensorial a través del córtex TARDIS-NEURAL-SPACE-KAIJU
        y emite conclusiones y deducciones analíticas profundas.
        """
        # Preparar especificación densa
        prompt_lines = [
            f"[SISTEMA DE INTELIGENCIA VISUAL · TARDIS-NEURAL-SPACE-KAIJU]",
            f"Tipo de Medio: {media_type.upper()}",
            f"Resolución: {tech_meta.get('width', 0)}x{tech_meta.get('height', 0)} | Duración: {tech_meta.get('duration', 0)}s | FPS: {tech_meta.get('fps', 0)}",
            "",
            "=== DESGLOSE TEMPORAL Y OBSERVACIONES VISUALES ==="
        ]

        for vt in visual_timeline:
            sec = vt.get("sec", 0.0)
            faces = vt.get("faces_count", 0)
            ocr = vt.get("ocr_text", "")
            sharp = vt.get("sharpness", 0)
            color = vt.get("dominant_hex", "")
            desc = f"• [{sec:.1f}s]: Color={color}, Nitidez={sharp}"
            if faces > 0:
                desc += f", Rostros/Personas={faces}"
            if ocr:
                desc += f', Texto en pantalla="{ocr[:100]}"'
            prompt_lines.append(desc)

        if vlm_description:
            prompt_lines.append(
                "\n=== PERCEPCIÓN VISUAL MULTIMODAL (VLM · OBSERVACIÓN DIRECTA DE LA IMAGEN) ===\n"
                f"{vlm_description[:5000]}"
            )

        if ocr_corpus:
            prompt_lines.append(f"\n=== TEXTO DETECTADO VISUALMENTE (OCR) ===\n{ocr_corpus[:1500]}")

        if audio_transcript:
            prompt_lines.append(f"\n=== TRANSCRIPCIÓN DE AUDIO / DIÁLOGO ===\n\"{audio_transcript[:2500]}\"")
        else:
            prompt_lines.append("\n=== TRANSCRIPCIÓN DE AUDIO ===\n(Sin pista de voz inteligible o audio ambiente silencioso)")

        if user_prompt:
            prompt_lines.append(f"\n=== DIRECTIVA O PREGUNTA DEL ARQUITECTO ===\n{user_prompt}")

        instruction = (
            "\n[INSTRUCCIÓN COGNITIVA SOBERANA PARA TARDIS]:\n"
            "Eres TARDIS, asistente de inteligencia artificial y sistema de control temporal. "
            "Has recibido este medio (video/imagen/sonido). Realiza un análisis exhaustivo y estructurado en 4 partes:\n"
            "1. RESUMEN: Una visión panorámica concisa y precisa de lo que ocurre.\n"
            "2. LO QUE VEO (ESCENA VISUAL Y DINÁMICA): Detalla objetos, sujetos, ambiente, movimiento, colores y elementos de fondo.\n"
            "3. LO QUE ESCUCHO (AUDIO Y VOZ): Detalla qué se dice, el tono, ruidos o música de fondo.\n"
            "4. CONCLUSIONES DE TARDIS: Deducciones causales profundas. ¿Cuál es el significado del video? ¿Qué contexto o intencionalidad se desprende? ¿Qué implicaciones o conclusiones extraes de lo observado?\n"
        )
        if verdict_mode:
            instruction += (
                "5. VEREDICTO DE TARDIS: Emite un dictamen claro, directo y útil sobre lo que rodea al Arquitecto. "
                "Distingue entre hechos observados, inferencias y dudas. Incluye el estado general del entorno, "
                "el nivel de riesgo (0 a 10, donde 0 es totalmente seguro y 10 es peligro inminente) y una "
                "recomendación concreta si procede. No inventes identidades ni datos que no puedas ver.\n"
            )
        instruction += "Responde con elegancia, rigor técnico, profundidad y sin rodeos genéricos."
        prompt_lines.append(instruction)

        full_prompt = "\n".join(prompt_lines)

        # 1. Intentar con KaijuCognitiveOrchestrator (Groq LPU ultra-rápido)
        try:
            from core.kaiju_cognitive_orchestrator import get_kaiju_cognitive_orchestrator
            orch = get_kaiju_cognitive_orchestrator()
            res = orch.orchestrate_chat_turn(
                message=full_prompt,
                session_id="visual_intelligence_synthesis",
                force_offload=True
            )
            raw_text = res.get("response", "").strip()
            if raw_text:
                return self._parse_structured_ai_response(raw_text)
        except Exception as e_orch:
            logger.warning(f"Aviso orquestador cognitivo en síntesis visual: {e_orch}")

        # 2. Fallback a inferencia local soberana
        try:
            import gia_sovereign_engine as _gse
            eng = _gse.get_engine()
            res = eng.chat([{"role": "user", "content": full_prompt}])
            raw_text = res.get("reply", "").strip()
            if raw_text:
                return self._parse_structured_ai_response(raw_text)
        except Exception as e_local:
            logger.warning(f"Aviso inferencia local en síntesis visual: {e_local}")

        # 3. Fallback determinista
        return {
            "summary": f"Video de {tech_meta.get('duration', 0)}s ({tech_meta.get('width',0)}x{tech_meta.get('height',0)}).",
            "visual_description": vlm_description[:1200] if vlm_description else f"Se observaron {len(visual_timeline)} secuencias temporales con tonalidades {visual_timeline[0].get('dominant_hex') if visual_timeline else 'neutras'}.",
            "audio_description": f"Transcripción: {audio_transcript}" if audio_transcript else "Pista de audio sin habla detectada.",
            "conclusions": "El medio ha sido procesado e indexado en la bóveda permanente de TARDIS para correlación temporal.",
            "verdict": self._deterministic_verdict(vlm_description),
            "full_text": "Análisis completado mediante procesamiento sensorial nativo."
        }

    def _parse_structured_ai_response(self, text: str) -> Dict[str, str]:
        """Extrae secciones estructuradas de la respuesta de TARDIS."""
        # Normalización soberana: tolerar formato markdown del modelo (negritas **, dos-puntos, ordinales)
        text = re.sub(r"\*\*", "", (text or "")).strip()
        res = {
            "summary": "",
            "visual_description": "",
            "audio_description": "",
            "conclusions": "",
            "verdict": "",
            "full_text": text
        }

        # Intentar segmentación por patrones
        summary_m = re.search(r"(?:1\.\s*RESUMEN|RESUMEN)\s*[:\-]?\s*(.*?)(?=(?:2\.\s*LO QUE VEO|LO QUE VEO|3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO|4\.\s*CONCLUSIONES|CONCLUSIONES|5\.\s*VEREDICTO|VEREDICTO|$))", text, re.DOTALL | re.IGNORECASE)
        if summary_m:
            res["summary"] = summary_m.group(1).strip()

        visual_m = re.search(r"(?:2\.\s*LO QUE VEO|LO QUE VEO)(?: \([^)]*\))?\s*[:\-]?\s*(.*?)(?=(?:3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO|4\.\s*CONCLUSIONES|CONCLUSIONES|5\.\s*VEREDICTO|VEREDICTO|$))", text, re.DOTALL | re.IGNORECASE)
        if visual_m:
            res["visual_description"] = visual_m.group(1).strip()

        audio_m = re.search(r"(?:3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO)(?: \([^)]*\))?\s*[:\-]?\s*(.*?)(?=(?:4\.\s*CONCLUSIONES|CONCLUSIONES|5\.\s*VEREDICTO|VEREDICTO|$))", text, re.DOTALL | re.IGNORECASE)
        if audio_m:
            res["audio_description"] = audio_m.group(1).strip()

        conc_m = re.search(r"(?:4\.\s*CONCLUSIONES DE TARDIS|CONCLUSIONES DE TARDIS|CONCLUSIONES)\s*[:\-]?\s*(.*?)(?=(?:5\.\s*VEREDICTO|VEREDICTO DE TARDIS|VEREDICTO|$))", text, re.DOTALL | re.IGNORECASE)
        if conc_m:
            res["conclusions"] = conc_m.group(1).strip()

        verdict_m = re.search(r"(?:5\.\s*VEREDICTO DE TARDIS|VEREDICTO DE TARDIS|VEREDICTO|DICTAMEN)\s*[:\-]?\s*(.*)$", text, re.DOTALL | re.IGNORECASE)
        if verdict_m:
            res["verdict"] = verdict_m.group(1).strip()

        if not res["summary"]:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            res["summary"] = paragraphs[0] if paragraphs else "Análisis visual TARDIS."
            res["conclusions"] = paragraphs[-1] if len(paragraphs) > 1 else text

        if not res["verdict"]:
            res["verdict"] = self._deterministic_verdict(res.get("visual_description", ""), res.get("conclusions", ""))

        return res

    @staticmethod
    def _parse_risk_level(text: str) -> Optional[int]:
        """Extrae el nivel de riesgo 0-10 declarado por el modelo o el veredicto."""
        if not text:
            return None
        patterns = (
            r"nivel\s+de\s+riesgo[^\d]{0,24}(\d{1,2})\s*(?:/\s*10)?",
            r"riesgo\s*(?:general|actual|observado)?[^\d]{0,20}(\d{1,2})\s*/\s*10",
            r"riesgo[^\d]{0,16}(\d{1,2})\s*(?:/|de)\s*10",
        )
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    val = int(m.group(1))
                    return max(0, min(10, val))
                except Exception:
                    continue
        return None

    @staticmethod
    def _deterministic_verdict(visual_description: str = "", conclusions: str = "") -> str:
        """Veredicto determinista de respaldo cuando el LLM no está disponible."""
        base = (visual_description or conclusions or "").strip()
        if base:
            return (
                f"{base[:900]}\n\n"
                "Nivel de riesgo: no cuantificado (síntesis lingüística no disponible). "
                "Recomendación: verificar visualmente el entorno antes de actuar."
            )
        return (
            "No fue posible obtener una descripción semántica de la imagen. "
            "Nivel de riesgo: no cuantificado. Recomendación: repetir la captura con mejor iluminación "
            "o revisar la disponibilidad del motor de visión."
        )

    def _build_verdict_data(self, verdict_text: str, vlm_res: Dict[str, Any], f_feat: Dict[str, Any],
                            camera_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Estructura el veredicto para telemetría, API y memoria a largo plazo."""
        risk = self._parse_risk_level(verdict_text)
        if risk is None:
            risk = self._parse_risk_level(str(vlm_res.get("analysis", "")))
        return {
            "risk_level": risk,
            "risk_label": (
                "sin_cuantificar" if risk is None else
                "seguro" if risk <= 2 else
                "vigilancia" if risk <= 5 else
                "alto" if risk <= 7 else
                "crítico"
            ),
            "vision_engine": vlm_res.get("engine", "sin_vlm"),
            "vision_ok": bool(vlm_res.get("ok")),
            "faces_detected": int(f_feat.get("faces_count", 0) or 0),
            "sharpness": f_feat.get("sharpness"),
            "brightness": f_feat.get("brightness"),
            "dominant_hex": f_feat.get("dominant_hex"),
            "ocr_text": (f_feat.get("ocr_text") or "")[:1000],
            "camera": camera_meta or {},
            "generated_at": datetime.now().isoformat(),
        }

    # --------------------------------------------------------------------------
    # CAPTURA DE ENTORNO Y VEREDICTO SOBERANO
    # --------------------------------------------------------------------------

    def capture_surroundings_image(self, camera: str = "auto") -> Tuple[Optional[Path], str, Dict[str, Any]]:
        """
        Captura una imagen del entorno desde la fuente solicitada.
        Fuentes: c310 (GOD-EYE), local (cámara del portátil), webcam, auto.
        Retorna (ruta, etiqueta_fuente, metadatos).
        """
        cam = (camera or "auto").strip().lower()
        aliases = {
            "godeye": "c310", "god-eye": "c310", "seguridad": "c310", "exterior": "c310",
            "camara": "c310", "cámara": "c310", "tapo": "c310", "c310": "c310",
            "local": "local", "laptop": "local", "portatil": "local", "portátil": "local",
            "webcam": "webcam", "usb": "webcam", "auto": "auto",
        }
        cam = aliases.get(cam, cam)

        candidates: List[str]
        if cam == "auto":
            candidates = ["c310", "local", "webcam"]
        else:
            candidates = [cam]

        last_error = ""
        for candidate in candidates:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = IMAGES_VAULT_DIR / f"surroundings_{candidate}_{ts}.jpg"

            if candidate == "c310":
                meta = {"camera": "GOD-EYE Tapo C310", "source": "c310"}
                # 1. Hub del centinela (fotograma en vivo)
                try:
                    r = requests.get(
                        "http://127.0.0.1:8797/c310/snapshot.jpg",
                        params={"hud": "0", "width": "1920", "quality": "92"},
                        timeout=6.0,
                    )
                    if r.status_code == 200 and len(r.content) > 5000:
                        out_path.write_bytes(r.content)
                        meta["capture"] = "live_hub"
                        return out_path, "c310", meta
                except Exception as e:
                    last_error = f"hub C310: {e}"

                # 2. Último fotograma persistido por el centinela
                try:
                    from core.tapo_c310_sentinel import DETECTIONS_DIR
                    latest = DETECTIONS_DIR / "latest_frame.jpg"
                    if latest.is_file() and (time.time() - latest.stat().st_mtime) < 120:
                        shutil.copy2(latest, out_path)
                        meta["capture"] = "latest_frame"
                        meta["frame_age_sec"] = round(time.time() - latest.stat().st_mtime, 1)
                        return out_path, "c310", meta
                    last_error = "C310 sin fotograma reciente"
                except Exception as e:
                    last_error = f"latest_frame C310: {e}"

            elif candidate in ("local", "webcam"):
                meta = {"camera": "Cámara local del portátil", "source": candidate}
                # 1. Hub de cámaras terminales
                if candidate == "local":
                    try:
                        from core.terminal_camera_hub import get_terminal_camera_hub
                        raw = get_terminal_camera_hub().get_terminal_snapshot("host_local_tardis")
                        if raw and len(raw) > 5000 and b"SIN TRANSMISI" not in raw[:2000]:
                            out_path.write_bytes(raw)
                            meta["capture"] = "terminal_camera_hub"
                            return out_path, "local", meta
                    except Exception as e:
                        last_error = f"hub local: {e}"
                # 2. OpenCV directo
                try:
                    cap = cv2.VideoCapture(0)
                    if cap and cap.isOpened():
                        frame = None
                        for _ in range(5):
                            ok, frame = cap.read()
                        cap.release()
                        if ok and frame is not None:
                            cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                            meta["capture"] = "opencv"
                            return out_path, candidate, meta
                    else:
                        if cap:
                            cap.release()
                        last_error = "cámara local no disponible"
                except Exception as e:
                    last_error = f"OpenCV cámara local: {e}"

        logger.warning(f"No fue posible capturar el entorno ({camera}): {last_error}")
        return None, "sin_camara", {"error": last_error, "camera_requested": camera}

    def analyze_surroundings(
        self,
        camera: str = "auto",
        question: str = "",
        source: str = "api",
        user_name: str = "Arquitecto",
    ) -> VisualAnalysisResult:
        """
        Captura el entorno en vivo y emite un veredicto soberano sobre lo observado.
        Punto de entrada único para Telegram, API, CLI y herramientas del agente.
        """
        img_path, cam_label, cam_meta = self.capture_surroundings_image(camera=camera)
        if not img_path or not img_path.exists():
            raise RuntimeError(
                f"No se pudo obtener una imagen del entorno ({camera}). "
                f"Detalle: {cam_meta.get('error', 'sin detalle')}"
            )

        prompt = (question or "").strip()
        base_directive = (
            "Analiza mi entorno actual y dime con franqueza qué hay a mi alrededor, "
            "si existe algún riesgo o anomalía, y cuál es tu veredicto."
        )
        caption = f"{base_directive} {VERDICT_PROMPT}"
        if prompt:
            caption = f"{prompt}\n\n{VERDICT_PROMPT}"

        result = self.process_image(
            img_path,
            source=source,
            user_name=user_name,
            caption=caption,
            extra_metadata={"camera": cam_label, "camera_meta": cam_meta, "surroundings": True},
        )
        result.metadata["surroundings"] = True
        result.metadata["camera"] = cam_label
        result.metadata["camera_meta"] = cam_meta
        self._save_record_to_db(result)
        return result

    # --------------------------------------------------------------------------
    # PIPELINE MAESTRO DE ANÁLISIS DE VIDEO
    # --------------------------------------------------------------------------

    def process_video(
        self,
        video_input: Union[Path, str, bytes],
        source: str = "telegram",
        chat_id: Optional[str | int] = None,
        user_id: Optional[str | int] = None,
        user_name: str = "Usuario",
        caption: str = "",
        save_to_vault: bool = True
    ) -> VisualAnalysisResult:
        """
        Procesa exhaustivamente un video completo:
        1. Almacena en la Bóveda de Videos TARDIS.
        2. Extrae telemetría técnica (ffprobe/OpenCV).
        3. Extrae y transcribe la pista de audio con Whisper LPU.
        4. Muestrea keyframes y analiza óptica, rostros y OCR en cada uno.
        5. Sintetiza conclusiones con TARDIS-NEURAL-SPACE-KAIJU.
        6. Persiste en SQLite y Bóveda RAG / Akasha.
        """
        t0 = time.time()
        ts_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        rand_hash = hashlib.sha256(f"{ts_id}_{caption}_{time.time()}".encode()).hexdigest()[:6]
        vid_id = f"vid_{ts_id}_{rand_hash}"

        # Determinar ruta permanente de almacenamiento
        if source == "telegram":
            target_dir = VIDEOS_TELEGRAM_DIR
        else:
            target_dir = VAULT_DIR / "videos" / source
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = ".mp4"
        if isinstance(video_input, (str, Path)):
            src_path = Path(video_input)
            ext = src_path.suffix or ".mp4"
            final_video_path = target_dir / f"{vid_id}{ext}"
            if save_to_vault and src_path.resolve() != final_video_path.resolve():
                shutil.copy2(src_path, final_video_path)
            elif not save_to_vault:
                final_video_path = src_path
        else:
            final_video_path = target_dir / f"{vid_id}.mp4"
            final_video_path.write_bytes(video_input)

        logger.info(f"🎬 [VisualIntelligence] Procesando video {vid_id} ({final_video_path.stat().st_size / (1024*1024):.2f} MB)...")

        # 1. Telemetría del Video
        tech_meta = self.get_video_telemetry(final_video_path)

        # 2. Extracción y Transcripción de Audio
        audio_wav_path = final_video_path.with_suffix(".wav")
        has_audio = self.extract_audio_from_video(final_video_path, audio_wav_path)
        audio_transcript = ""
        acoustic_profile = {}
        if has_audio:
            audio_transcript, acoustic_profile = self.transcribe_audio_whisper(audio_wav_path)

        # 3. Extracción de Keyframes
        frames_dir = FRAMES_CACHE_DIR / vid_id
        keyframes = self.extract_keyframes(final_video_path, frames_dir, max_keyframes=8)

        # 4. Análisis Óptico y OCR por Fotograma
        visual_timeline = []
        all_ocr_tokens = []
        dominant_colors = []
        total_faces = 0
        keyframe_paths_str = []

        for sec, k_path, k_rgb in keyframes:
            keyframe_paths_str.append(str(k_path))
            f_feat = self.analyze_frame_features(k_rgb)
            f_feat["sec"] = sec
            f_feat["path"] = str(k_path)
            visual_timeline.append(f_feat)
            if f_feat.get("dominant_hex"):
                dominant_colors.append(f_feat["dominant_hex"])
            if f_feat.get("faces_count", 0) > total_faces:
                total_faces = f_feat["faces_count"]
            if f_feat.get("ocr_text"):
                all_ocr_tokens.append(f_feat["ocr_text"])

        ocr_corpus = "\n".join(all_ocr_tokens).strip()

        # 5. Estimación de Dinámica y Movimiento
        motion_score = 0.0
        if len(keyframes) >= 2:
            diffs = []
            for i in range(len(keyframes) - 1):
                f1 = cv2.cvtColor(keyframes[i][2], cv2.COLOR_RGB2GRAY)
                f2 = cv2.cvtColor(keyframes[i+1][2], cv2.COLOR_RGB2GRAY)
                diff = np.mean(cv2.absdiff(f1, f2))
                diffs.append(diff)
            motion_score = round(float(np.mean(diffs)), 2)

        # 6. Percepción visual multimodal de keyframes representativos (VLM real)
        vlm_fragments: List[str] = []
        if keyframes and os.environ.get("TARDIS_VLM_VIDEO", "1") not in ("0", "false", "False"):
            sample_idx = [0]
            if len(keyframes) > 2:
                sample_idx.append(len(keyframes) // 2)
            if len(keyframes) > 4:
                sample_idx.append(len(keyframes) - 2)
            for idx in list(dict.fromkeys(sample_idx))[:3]:
                sec_k, path_k, _rgb = keyframes[idx]
                try:
                    vlm_k = self.describe_image_with_vlm(
                        path_k,
                        context=f"Fotograma del video en el segundo {sec_k:.1f}. {caption}".strip(),
                    )
                    if vlm_k.get("ok") and vlm_k.get("analysis"):
                        vlm_fragments.append(
                            f"[{sec_k:.1f}s · {vlm_k.get('engine')}]: {vlm_k.get('analysis', '')[:2500]}"
                        )
                except Exception as e_vlm_k:
                    logger.warning(f"VLM keyframe {sec_k:.1f}s falló: {e_vlm_k}")
        vlm_video_description = "\n\n".join(vlm_fragments)

        # 7. Síntesis Cognitiva y Deducción Causal (KAIJU)
        conclusions_data = self._synthesize_conclusions_with_kaiju(
            media_type="video",
            tech_meta=tech_meta,
            visual_timeline=visual_timeline,
            ocr_corpus=ocr_corpus,
            audio_transcript=audio_transcript,
            user_prompt=caption,
            vlm_description=vlm_video_description,
            verdict_mode=True,
        )
        verdict_text = (conclusions_data.get("verdict") or "").strip()
        if not verdict_text:
            verdict_text = self._deterministic_verdict(vlm_video_description, conclusions_data.get("conclusions", ""))
        verdict_data = self._build_verdict_data(
            verdict_text,
            {"engine": "VLM por keyframes" if vlm_fragments else "sin_vlm", "ok": bool(vlm_fragments)},
            visual_timeline[0] if visual_timeline else {},
        )

        elapsed = round(time.time() - t0, 2)

        # Construir reporte completo para Telegram o UI
        full_report = (
            f"👁️ **[TARDIS :: INTELIGENCIA VISUAL - ANÁLISIS DE VIDEO]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **ID del Archivo:** `{vid_id}`\n"
            f"• **Metadatos Técnicos:** {tech_meta.get('width', 0)}x{tech_meta.get('height', 0)} px | "
            f"{tech_meta.get('duration', 0)}s | {tech_meta.get('fps', 0):.1f} FPS | "
            f"{tech_meta.get('file_size', 0) / (1024*1024):.2f} MB\n"
            f"• **Procesamiento:** {len(keyframes)} fotogramas clave analizados en {elapsed}s.\n"
            f"• **Visión Multimodal:** {'✅ ' + str(len(vlm_fragments)) + ' keyframes descritos por VLM' if vlm_fragments else '⚠️ sin VLM (solo rasgos ópticos)'}\n\n"
            f"📝 **RESUMEN GENERAL:**\n{conclusions_data.get('summary', '')}\n\n"
            f"🎬 **LO QUE VEO (ESCENA VISUAL):**\n{conclusions_data.get('visual_description', '')}\n\n"
            f"🔊 **LO QUE ESCUCHO (AUDIO & VOZ):**\n"
            f"{conclusions_data.get('audio_description', '')}\n"
            f"{'• *Transcripción literal:* \"' + audio_transcript + '\"' if audio_transcript else '• *Pista acústica:* Audio ambiental sin habla destacada.'}\n\n"
            f"⚖️ **VEREDICTO DE TARDIS:**\n{verdict_text}\n\n"
            f"🚦 **Nivel de Riesgo:** {verdict_data.get('risk_level') if verdict_data.get('risk_level') is not None else 'no cuantificado'}/10 "
            f"({verdict_data.get('risk_label')})\n\n"
            f"🧠 **CONCLUSIONES & DEDUCCIONES DE TARDIS:**\n{conclusions_data.get('conclusions', '')}\n\n"
            f"💾 **Almacenamiento Permanente:** Guardado de forma segura en la Bóveda TARDIS."
        )

        result = VisualAnalysisResult(
            id=vid_id,
            media_type="video",
            source=source,
            file_path=str(final_video_path),
            file_name=final_video_path.name,
            file_size_bytes=tech_meta.get("file_size", 0),
            duration_sec=tech_meta.get("duration", 0.0),
            width=tech_meta.get("width", 0),
            height=tech_meta.get("height", 0),
            fps=tech_meta.get("fps", 0.0),
            keyframe_count=len(keyframes),
            keyframe_paths=keyframe_paths_str,
            detected_faces=total_faces,
            detected_text_ocr=ocr_corpus,
            dominant_colors=list(dict.fromkeys(dominant_colors)),
            motion_intensity=motion_score,
            audio_present=has_audio,
            audio_transcript=audio_transcript,
            acoustic_profile=acoustic_profile,
            summary=conclusions_data.get("summary", ""),
            visual_description=conclusions_data.get("visual_description", ""),
            audio_description=conclusions_data.get("audio_description", ""),
            conclusions=conclusions_data.get("conclusions", ""),
            full_report=full_report,
            verdict=verdict_text,
            verdict_data=verdict_data,
            vision_engine="VLM por keyframes" if vlm_fragments else "sin_vlm",
            metadata={
                "chat_id": str(chat_id) if chat_id else "",
                "user_id": str(user_id) if user_id else "",
                "user_name": user_name,
                "caption": caption,
                "vlm_keyframes": vlm_video_description[:8000],
                "keyframes_meta": visual_timeline
            },
            elapsed_sec=elapsed
        )

        # 7. Persistir metadatos JSON junto al video
        json_meta_path = final_video_path.with_suffix(".json")
        try:
            json_meta_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        # 8. Persistir en Base de Datos SQLite
        self._save_record_to_db(result)

        # 9. Ingestar en la Bóveda RAG / Akasha
        self._ingest_to_rag(result)

        logger.info(f"✅ [VisualIntelligence] Video {vid_id} procesado y comprendido en {elapsed}s.")
        return result

    # --------------------------------------------------------------------------
    # PIPELINE DE ANÁLISIS DE IMÁGENES
    # --------------------------------------------------------------------------

    def process_image(
        self,
        image_input: Union[Path, str, bytes],
        source: str = "telegram",
        chat_id: Optional[str | int] = None,
        user_id: Optional[str | int] = None,
        user_name: str = "Usuario",
        caption: str = "",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> VisualAnalysisResult:
        """Analiza, comprende y dictamina una imagen fija en alta definición."""
        t0 = time.time()
        ts_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_id = f"img_{ts_id}_{hashlib.sha256(f'{time.time()}'.encode()).hexdigest()[:6]}"
        target_path = IMAGES_VAULT_DIR / f"{img_id}.jpg"

        if isinstance(image_input, (str, Path)):
            shutil.copy2(Path(image_input), target_path)
        else:
            target_path.write_bytes(image_input)

        frame_bgr = cv2.imread(str(target_path))
        if frame_bgr is None:
            raise ValueError("No fue posible leer la imagen.")

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = frame_rgb.shape
        f_feat = self.analyze_frame_features(frame_rgb)

        # 1. Percepción visual multimodal real (VLM): la imagen se observa directamente
        vlm_res = self.describe_image_with_vlm(target_path, context=caption)
        vlm_description = str(vlm_res.get("analysis", "") or "").strip()
        if not vlm_res.get("ok"):
            logger.warning(f"VLM no disponible para {img_id}: {vlm_res.get('error', '')[:200]}")

        # 2. Síntesis cognitiva + veredicto soberano
        conclusions_data = self._synthesize_conclusions_with_kaiju(
            media_type="image",
            tech_meta={"width": w, "height": h, "duration": 0.0, "fps": 0.0},
            visual_timeline=[{"sec": 0.0, **f_feat}],
            ocr_corpus=f_feat.get("ocr_text", ""),
            audio_transcript="",
            user_prompt=caption,
            vlm_description=vlm_description,
            verdict_mode=True,
        )

        verdict_text = (conclusions_data.get("verdict") or "").strip()
        if not verdict_text:
            verdict_text = self._deterministic_verdict(vlm_description, conclusions_data.get("conclusions", ""))
        verdict_data = self._build_verdict_data(verdict_text, vlm_res, f_feat,
                                                camera_meta=(extra_metadata or {}).get("camera_meta"))
        verdict_block = (
            f"⚖️ **VEREDICTO DE TARDIS:**\n{verdict_text}\n\n"
            f"🚦 **Nivel de Riesgo:** {verdict_data.get('risk_level') if verdict_data.get('risk_level') is not None else 'no cuantificado'}/10 "
            f"({verdict_data.get('risk_label')})\n\n"
        )

        elapsed = round(time.time() - t0, 2)
        full_report = (
            f"👁️ **[TARDIS :: INTELIGENCIA VISUAL - ANÁLISIS DE IMAGEN]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **ID:** `{img_id}` | **Resolución:** {w}x{h} px | **Nitidez:** {f_feat.get('sharpness')}\n"
            f"• **Rostros Detectados:** {f_feat.get('faces_count', 0)}\n"
            f"• **Motor de Visión:** {vlm_res.get('engine', 'sin VLM')}\n\n"
            f"📝 **RESUMEN:**\n{conclusions_data.get('summary', '')}\n\n"
            f"🎨 **LO QUE VEO:**\n{conclusions_data.get('visual_description', '')}\n\n"
            f"{'📋 **TEXTO DETECTADO (OCR):** \"' + f_feat.get('ocr_text') + '\"\n\n' if f_feat.get('ocr_text') else ''}"
            f"{verdict_block}"
            f"🧠 **CONCLUSIONES DE TARDIS:**\n{conclusions_data.get('conclusions', '')}\n\n"
            f"💾 **Almacenamiento:** Guardado permanentemente en la Bóveda de Imágenes."
        )

        metadata = {
            "caption": caption,
            "user_name": user_name,
            "chat_id": str(chat_id or ""),
            "user_id": str(user_id or ""),
            "vision_engine": vlm_res.get("engine", ""),
            "vision_ok": bool(vlm_res.get("ok")),
            "vlm_analysis": vlm_description[:6000],
            "verdict_data": verdict_data,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        result = VisualAnalysisResult(
            id=img_id,
            media_type="image",
            source=source,
            file_path=str(target_path),
            file_name=target_path.name,
            file_size_bytes=target_path.stat().st_size,
            duration_sec=0.0,
            width=w,
            height=h,
            fps=0.0,
            keyframe_count=1,
            keyframe_paths=[str(target_path)],
            detected_faces=f_feat.get("faces_count", 0),
            detected_text_ocr=f_feat.get("ocr_text", ""),
            dominant_colors=[f_feat.get("dominant_hex", "#000000")],
            motion_intensity=0.0,
            audio_present=False,
            audio_transcript="",
            acoustic_profile={},
            summary=conclusions_data.get("summary", ""),
            visual_description=conclusions_data.get("visual_description", ""),
            audio_description="",
            conclusions=conclusions_data.get("conclusions", ""),
            full_report=full_report,
            verdict=verdict_text,
            verdict_data=verdict_data,
            vision_engine=str(vlm_res.get("engine", "")),
            metadata=metadata,
            elapsed_sec=elapsed
        )

        self._save_record_to_db(result)
        self._ingest_to_rag(result)
        logger.info(
            f"⚖️ [VisualIntelligence] Imagen {img_id} dictaminada: "
            f"riesgo={verdict_data.get('risk_level')} vía {vlm_res.get('engine', 'sin_vlm')} "
            f"({elapsed}s)"
        )
        return result

    # --------------------------------------------------------------------------
    # PIPELINE DE ANÁLISIS DE SONIDO / AUDIO
    # --------------------------------------------------------------------------

    def process_sound(
        self,
        audio_input: Union[Path, str, bytes],
        source: str = "telegram",
        chat_id: Optional[str | int] = None,
        user_name: str = "Usuario",
        caption: str = ""
    ) -> VisualAnalysisResult:
        """Analiza y comprende un archivo de audio o sonido ambiental."""
        t0 = time.time()
        ts_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        snd_id = f"snd_{ts_id}_{hashlib.sha256(f'{time.time()}'.encode()).hexdigest()[:6]}"
        target_wav = DATA_DIR / f"{snd_id}.wav"

        if isinstance(audio_input, (str, Path)):
            cmd = ["ffmpeg", "-y", "-i", str(audio_input), "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(target_wav)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        else:
            with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tf:
                tf.write(audio_input)
                tf_path = Path(tf.name)
            cmd = ["ffmpeg", "-y", "-i", str(tf_path), "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(target_wav)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            tf_path.unlink(missing_ok=True)

        transcript, profile = self.transcribe_audio_whisper(target_wav)

        conclusions_data = self._synthesize_conclusions_with_kaiju(
            media_type="sound",
            tech_meta={"duration": profile.get("duration_sec", 0.0), "fps": 0, "width": 0, "height": 0},
            visual_timeline=[],
            ocr_corpus="",
            audio_transcript=transcript,
            user_prompt=caption
        )

        elapsed = round(time.time() - t0, 2)
        full_report = (
            f"🎙️ **[TARDIS :: INTELIGENCIA SENSORIAL - ANÁLISIS ACÚSTICO]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **ID:** `{snd_id}` | **Duración:** {profile.get('duration_sec', 0)}s | **Energía RMS:** {profile.get('rms_energy', 0)}\n\n"
            f"🔊 **LO QUE ESCUCHO:**\n{conclusions_data.get('audio_description', '')}\n"
            f"{'• *Transcripción:* \"' + transcript + '\"\n\n' if transcript else '• *Paisaje Sonoro:* Audio sin habla evidente.\n\n'}"
            f"🧠 **CONCLUSIONES DE TARDIS:**\n{conclusions_data.get('conclusions', '')}"
        )

        result = VisualAnalysisResult(
            id=snd_id,
            media_type="sound",
            source=source,
            file_path=str(target_wav),
            file_name=target_wav.name,
            file_size_bytes=target_wav.stat().st_size if target_wav.exists() else 0,
            duration_sec=profile.get("duration_sec", 0.0),
            width=0,
            height=0,
            fps=0.0,
            keyframe_count=0,
            keyframe_paths=[],
            detected_faces=0,
            detected_text_ocr="",
            dominant_colors=[],
            motion_intensity=0.0,
            audio_present=True,
            audio_transcript=transcript,
            acoustic_profile=profile,
            summary=conclusions_data.get("summary", ""),
            visual_description="",
            audio_description=conclusions_data.get("audio_description", ""),
            conclusions=conclusions_data.get("conclusions", ""),
            full_report=full_report,
            metadata={"caption": caption, "user_name": user_name, "chat_id": str(chat_id or ""), "user_id": ""},
            elapsed_sec=elapsed
        )

        self._save_record_to_db(result)
        self._ingest_to_rag(result)
        return result

    # --------------------------------------------------------------------------
    # PERSISTENCIA EN DB Y BÓVEDA RAG
    # --------------------------------------------------------------------------

    def _save_record_to_db(self, res: VisualAnalysisResult):
        """Guarda el registro analítico en SQLite."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO visual_records (
                        id, media_type, source, file_path, file_size, duration,
                        width, height, fps, chat_id, user_id, user_name, caption,
                        ocr_text, audio_transcript, summary, visual_description,
                        conclusions, verdict, vision_engine, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    res.id, res.media_type, res.source, res.file_path, res.file_size_bytes,
                    res.duration_sec, res.width, res.height, res.fps,
                    str(res.metadata.get("chat_id", "")),
                    str(res.metadata.get("user_id", "")),
                    res.metadata.get("user_name", "Usuario"),
                    res.metadata.get("caption", ""),
                    res.detected_text_ocr,
                    res.audio_transcript,
                    res.summary,
                    res.visual_description,
                    res.conclusions,
                    res.verdict,
                    res.vision_engine,
                    json.dumps(res.metadata, ensure_ascii=False),
                    res.created_at
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error guardando registro visual en DB: {e}")

    def _ingest_to_rag(self, res: VisualAnalysisResult):
        """Ingesta el análisis en la memoria RAG / Akasha permanente de TARDIS."""
        try:
            from core.rag_vault import get_rag_vault
            vault = get_rag_vault()
            content = (
                f"[MEMORIA VISUAL SOBERANA TARDIS - {res.media_type.upper()}]\n"
                f"Identificador: {res.id}\n"
                f"Fecha: {res.created_at}\n"
                f"Fuente: {res.source} (Remitente: {res.metadata.get('user_name', 'Usuario')})\n"
                f"Resumen: {res.summary}\n"
                f"Descripción Visual: {res.visual_description}\n"
                f"Transcripción de Audio: {res.audio_transcript}\n"
                f"Texto en Pantalla: {res.detected_text_ocr}\n"
                f"Conclusiones de TARDIS: {res.conclusions}\n"
                f"Veredicto de TARDIS: {res.verdict}\n"
                f"Motor de Visión: {res.vision_engine}\n"
            )
            vault.ingest(
                text=content,
                source=f"visual_intelligence:{res.media_type}",
                url=res.file_path,
                title=f"Percepción Visual {res.id}"
            )
            logger.info(f"🧠 [VisualIntelligence] Registro {res.id} asimilado en la Bóveda RAG / Akasha.")
        except Exception as e_rag:
            logger.debug(f"Aviso ingestando memoria visual en RAG: {e_rag}")

    # --------------------------------------------------------------------------
    # CONSULTAS Y GESTIÓN DE LA BÓVEDA
    # --------------------------------------------------------------------------

    def list_stored_videos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve la lista de videos almacenados y comprendidos."""
        return self.list_recent_records(media_type="video", limit=limit)

    def list_recent_records(self, media_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Devuelve los registros visuales más recientes, opcionalmente filtrados por tipo."""
        out = []
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                if media_type:
                    cur = conn.execute(
                        "SELECT * FROM visual_records WHERE media_type=? ORDER BY created_at DESC LIMIT ?",
                        (media_type, limit)
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM visual_records ORDER BY created_at DESC LIMIT ?",
                        (limit,)
                    )
                for r in cur.fetchall():
                    out.append(dict(r))
        except Exception as e:
            logger.error(f"Error consultando registros visuales: {e}")
        return out

    def get_last_verdict(self) -> Optional[Dict[str, Any]]:
        """Retorna el último veredicto visual emitido por TARDIS."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT * FROM visual_records WHERE verdict IS NOT NULL AND verdict != '' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    data = dict(row)
                    try:
                        data["metadata"] = json.loads(data.get("metadata_json") or "{}")
                    except Exception:
                        data["metadata"] = {}
                    return data
        except Exception as e:
            logger.error(f"Error consultando último veredicto: {e}")
        return None

    def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene un registro por su ID único."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute("SELECT * FROM visual_records WHERE id=?", (record_id,))
                row = cur.fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.error(f"Error consultando registro {record_id}: {e}")
        return None

    def get_status(self) -> Dict[str, Any]:
        """Estado general de salud del motor de Inteligencia Visual."""
        total_videos = 0
        total_images = 0
        total_sounds = 0
        total_verdicts = 0
        last_verdict = None
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur = conn.execute("SELECT media_type, COUNT(*) FROM visual_records GROUP BY media_type")
                for mt, cnt in cur.fetchall():
                    if mt == "video":
                        total_videos = cnt
                    elif mt == "image":
                        total_images = cnt
                    elif mt == "sound":
                        total_sounds = cnt
                try:
                    total_verdicts = int(conn.execute(
                        "SELECT COUNT(*) FROM visual_records WHERE verdict IS NOT NULL AND verdict != ''"
                    ).fetchone()[0])
                except Exception:
                    total_verdicts = 0
        except Exception:
            pass

        vlm_model = self._discover_vlm_model()
        try:
            last_verdict = self.get_last_verdict()
        except Exception:
            last_verdict = None

        return {
            "status": "online",
            "engine": "VisualIntelligenceEngine v26.5 (VLM + Veredictos)",
            "orchestrator": "TARDIS-NEURAL-SPACE-KAIJU",
            "whisper_accel": "Groq LPU (whisper-large-v3-turbo)",
            "ocr_ready": HAS_PYTESSERACT,
            "haar_cascades_ready": bool(self._face_cascade),
            "vlm_ready": bool(vlm_model),
            "vlm_model": vlm_model or "no instalado",
            "vlm_provider": (os.environ.get("VLM_PROVIDER") or "auto"),
            "vlm_error": self._vlm_last_error[:300] if not vlm_model else "",
            "verdict_engine": "VLM + Kaiju + veredicto estructurado",
            "stored_videos_count": total_videos,
            "stored_images_count": total_images,
            "stored_sounds_count": total_sounds,
            "stored_verdicts_count": total_verdicts,
            "last_verdict": {
                "id": (last_verdict or {}).get("id"),
                "created_at": (last_verdict or {}).get("created_at"),
                "source": (last_verdict or {}).get("source"),
                "verdict": ((last_verdict or {}).get("verdict") or "")[:600],
                "risk_level": (((last_verdict or {}).get("metadata") or {}).get("verdict_data") or {}).get("risk_level"),
            } if last_verdict else None,
            "surroundings_interval_sec": int(float(os.environ.get("TARDIS_SURROUNDINGS_INTERVAL", "900") or 900)),
            "vault_dir": str(VIDEOS_TELEGRAM_DIR),
            "spool_dir": str(SPOOL_DIR),
            "db_path": str(self.db_path)
        }


def get_visual_intelligence_engine() -> VisualIntelligenceEngine:
    """Acceso canónico al singleton de Inteligencia Visual."""
    return VisualIntelligenceEngine.get_instance()
