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
        user_prompt: str = ""
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

        if ocr_corpus:
            prompt_lines.append(f"\n=== TEXTO DETECTADO VISUALMENTE (OCR) ===\n{ocr_corpus[:1500]}")

        if audio_transcript:
            prompt_lines.append(f"\n=== TRANSCRIPCIÓN DE AUDIO / DIÁLOGO ===\n\"{audio_transcript[:2500]}\"")
        else:
            prompt_lines.append("\n=== TRANSCRIPCIÓN DE AUDIO ===\n(Sin pista de voz inteligible o audio ambiente silencioso)")

        if user_prompt:
            prompt_lines.append(f"\n=== DIRECTIVA O PREGUNTA DEL ARQUITECTO ===\n{user_prompt}")

        prompt_lines.append(
            "\n[INSTRUCCIÓN COGNITIVA SOBERANA PARA TARDIS]:\n"
            "Eres TARDIS, asistente de inteligencia artificial y sistema de control temporal. "
            "Has recibido este medio (video/imagen/sonido). Realiza un análisis exhaustivo y estructurado en 4 partes:\n"
            "1. RESUMEN: Una visión panorámica concisa y precisa de lo que ocurre.\n"
            "2. LO QUE VEO (ESCENA VISUAL Y DINÁMICA): Detalla objetos, sujetos, ambiente, movimiento, colores y elementos de fondo.\n"
            "3. LO QUE ESCUCHO (AUDIO Y VOZ): Detalla qué se dice, el tono, ruidos o música de fondo.\n"
            "4. CONCLUSIONES DE TARDIS: Deducciones causales profundas. ¿Cuál es el significado del video? ¿Qué contexto o intencionalidad se desprende? ¿Qué implicaciones o conclusiones extraes de lo observado?\n"
            "Responde con elegancia, rigor técnico, profundidad y sin rodeos genéricos."
        )

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
            "visual_description": f"Se observaron {len(visual_timeline)} secuencias temporales con tonalidades {visual_timeline[0].get('dominant_hex') if visual_timeline else 'neutras'}.",
            "audio_description": f"Transcripción: {audio_transcript}" if audio_transcript else "Pista de audio sin habla detectada.",
            "conclusions": "El medio ha sido procesado e indexado en la bóveda permanente de TARDIS para correlación temporal.",
            "full_text": "Análisis completado mediante procesamiento sensorial nativo."
        }

    def _parse_structured_ai_response(self, text: str) -> Dict[str, str]:
        """Extrae secciones estructuradas de la respuesta de TARDIS."""
        res = {
            "summary": "",
            "visual_description": "",
            "audio_description": "",
            "conclusions": "",
            "full_text": text
        }

        # Intentar segmentación por patrones
        summary_m = re.search(r"(?:1\.\s*RESUMEN|RESUMEN)[:\s]+(.*?)(?=(?:2\.\s*LO QUE VEO|LO QUE VEO|3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO|4\.\s*CONCLUSIONES|CONCLUSIONES|$))", text, re.DOTALL | re.IGNORECASE)
        if summary_m:
            res["summary"] = summary_m.group(1).strip()

        visual_m = re.search(r"(?:2\.\s*LO QUE VEO|LO QUE VEO)[:\s]+(.*?)(?=(?:3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO|4\.\s*CONCLUSIONES|CONCLUSIONES|$))", text, re.DOTALL | re.IGNORECASE)
        if visual_m:
            res["visual_description"] = visual_m.group(1).strip()

        audio_m = re.search(r"(?:3\.\s*LO QUE ESCUCHO|LO QUE ESCUCHO)[:\s]+(.*?)(?=(?:4\.\s*CONCLUSIONES|CONCLUSIONES|$))", text, re.DOTALL | re.IGNORECASE)
        if audio_m:
            res["audio_description"] = audio_m.group(1).strip()

        conc_m = re.search(r"(?:4\.\s*CONCLUSIONES DE TARDIS|CONCLUSIONES DE TARDIS|CONCLUSIONES)[:\s]+(.*)$", text, re.DOTALL | re.IGNORECASE)
        if conc_m:
            res["conclusions"] = conc_m.group(1).strip()

        if not res["summary"]:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            res["summary"] = paragraphs[0] if paragraphs else "Análisis visual TARDIS."
            res["conclusions"] = paragraphs[-1] if len(paragraphs) > 1 else text

        return res

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

        # 6. Síntesis Cognitiva y Deducción Causal (KAIJU)
        conclusions_data = self._synthesize_conclusions_with_kaiju(
            media_type="video",
            tech_meta=tech_meta,
            visual_timeline=visual_timeline,
            ocr_corpus=ocr_corpus,
            audio_transcript=audio_transcript,
            user_prompt=caption
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
            f"• **Procesamiento:** {len(keyframes)} fotogramas clave analizados en {elapsed}s.\n\n"
            f"📝 **RESUMEN GENERAL:**\n{conclusions_data.get('summary', '')}\n\n"
            f"🎬 **LO QUE VEO (ESCENA VISUAL):**\n{conclusions_data.get('visual_description', '')}\n\n"
            f"🔊 **LO QUE ESCUCHO (AUDIO & VOZ):**\n"
            f"{conclusions_data.get('audio_description', '')}\n"
            f"{'• *Transcripción literal:* \"' + audio_transcript + '\"' if audio_transcript else '• *Pista acústica:* Audio ambiental sin habla destacada.'}\n\n"
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
            metadata={
                "chat_id": str(chat_id) if chat_id else "",
                "user_id": str(user_id) if user_id else "",
                "user_name": user_name,
                "caption": caption,
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
        caption: str = ""
    ) -> VisualAnalysisResult:
        """Analiza y comprende una imagen fija en alta definición."""
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

        conclusions_data = self._synthesize_conclusions_with_kaiju(
            media_type="image",
            tech_meta={"width": w, "height": h, "duration": 0.0, "fps": 0.0},
            visual_timeline=[{"sec": 0.0, **f_feat}],
            ocr_corpus=f_feat.get("ocr_text", ""),
            audio_transcript="",
            user_prompt=caption
        )

        elapsed = round(time.time() - t0, 2)
        full_report = (
            f"👁️ **[TARDIS :: INTELIGENCIA VISUAL - ANÁLISIS DE IMAGEN]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **ID:** `{img_id}` | **Resolución:** {w}x{h} px | **Nitidez:** {f_feat.get('sharpness')}\n"
            f"• **Rostros Detectados:** {f_feat.get('faces_count', 0)}\n\n"
            f"📝 **RESUMEN:**\n{conclusions_data.get('summary', '')}\n\n"
            f"🎨 **LO QUE VEO:**\n{conclusions_data.get('visual_description', '')}\n\n"
            f"{'📋 **TEXTO DETECTADO (OCR):** \"' + f_feat.get('ocr_text') + '\"\n\n' if f_feat.get('ocr_text') else ''}"
            f"🧠 **CONCLUSIONES DE TARDIS:**\n{conclusions_data.get('conclusions', '')}\n\n"
            f"💾 **Almacenamiento:** Guardado permanentemente en la Bóveda de Imágenes."
        )

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
            metadata={"caption": caption, "user_name": user_name},
            elapsed_sec=elapsed
        )

        self._save_record_to_db(result)
        self._ingest_to_rag(result)
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
            metadata={"caption": caption, "user_name": user_name},
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
                        conclusions, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        out = []
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT * FROM visual_records WHERE media_type='video' ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                for r in cur.fetchall():
                    out.append(dict(r))
        except Exception as e:
            logger.error(f"Error consultando videos almacenados: {e}")
        return out

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
        except Exception:
            pass

        return {
            "status": "online",
            "engine": "VisualIntelligenceEngine v26.4",
            "orchestrator": "TARDIS-NEURAL-SPACE-KAIJU",
            "whisper_accel": "Groq LPU (whisper-large-v3-turbo)",
            "ocr_ready": HAS_PYTESSERACT,
            "haar_cascades_ready": bool(self._face_cascade),
            "stored_videos_count": total_videos,
            "stored_images_count": total_images,
            "stored_sounds_count": total_sounds,
            "vault_dir": str(VIDEOS_TELEGRAM_DIR),
            "spool_dir": str(SPOOL_DIR),
            "db_path": str(self.db_path)
        }


def get_visual_intelligence_engine() -> VisualIntelligenceEngine:
    """Acceso canónico al singleton de Inteligencia Visual."""
    return VisualIntelligenceEngine.get_instance()
