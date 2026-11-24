#!/usr/bin/env python3
"""
core/videocall_vision_engine.py - Motor de Visión en Tiempo Real para Videollamadas TARDIS
==========================================================================================
Provee percepción visual bidireccional en vivo y de baja latencia para videollamadas
full-duplex de TARDIS (Telegram Mini App, Portal FTL, Cockpit y clientes web):

  1. Telemetría instantánea por fotograma (< 30 ms en CPU vía OpenCV / PIL):
     - Normalización segura JPEG, resolución, nivel de iluminación y cambio de escena (delta).
     - Detección de rostros (Haar Cascade) con cajas normalizadas [0..1] para el HUD en vivo.
     - Lectura instantánea de códigos QR visibles en cámara.
  2. Percepción semántica multimodal asíncrona (Qwen3-VL en carril GPU dedicado :11435):
     - Alinea estrictamente num_ctx=3072, num_gpu=22, keep_alive=-1, think=False para
       reutilizar el modelo residente en VRAM sin recargas ni thrashing en RTX 3050.
     - Mantiene memoria visual viva por sesión (SceneMemory) inyectada en el contexto LLM
       de cada turno hablado sin bloquear la latencia de voz (~1.2-1.6 s).
     - Soporta inspección bajo demanda cuando el usuario pregunta "¿qué ves?", "mira esto",
       o pulsa el botón de análisis visual instantáneo.
  3. Fuentes de video salientes de TARDIS hacia el usuario:
     - Cámara física GOD-EYE (Tapo C310 @ :8797).
     - Captura en vivo de pantalla del host (Wayland/Hyprland vía core/screen_capture.py,
       restringida exclusivamente al Arquitecto).
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np
from PIL import Image

logger = logging.getLogger("TARDIS.VideoCallVision")

BASE_DIR = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = BASE_DIR / "data" / "telephony" / "videocall_snapshots"

OLLAMA_VLM_GPU_URL = os.environ.get("TARDIS_VLM_GPU_URL", "http://127.0.0.1:11435").strip().rstrip("/")
OLLAMA_VLM_FALLBACK_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
if not OLLAMA_VLM_GPU_URL.startswith(("http://", "https://")):
    OLLAMA_VLM_GPU_URL = f"http://{OLLAMA_VLM_GPU_URL}"
if not OLLAMA_VLM_FALLBACK_URL.startswith(("http://", "https://")):
    OLLAMA_VLM_FALLBACK_URL = f"http://{OLLAMA_VLM_FALLBACK_URL}"

VLM_DEFAULT_MODEL = os.environ.get("TARDIS_VIDEOCALL_VLM_MODEL", "qwen3-vl:2b-instruct").strip()
VLM_GPU_NUM_CTX = int(os.environ.get("TARDIS_VLM_GPU_NUM_CTX", "3072"))
VLM_GPU_NUM_GPU = int(os.environ.get("TARDIS_VLM_GPU_NUM_GPU", "22"))
SENTINEL_HUB_URL = os.environ.get("TARDIS_C310_HUB_URL", "http://127.0.0.1:8797").rstrip("/")

OPENCV_DATA_DIR = Path("/usr/share/opencv4/haarcascades")
HAAR_FACE_PATH = OPENCV_DATA_DIR / "haarcascade_frontalface_default.xml"

_VISUAL_INTENT_PATTERNS = (
    r"\bqu[eé]\s+ves\b",
    r"\bqu[eé]\s+est[aá]s\s+viendo\b",
    r"\bqu[eé]\s+puedes\s+ver\b",
    r"\bme\s+ves\b",
    r"\bpuedes\s+verme\b",
    r"\bc[oó]mo\s+me\s+veo\b",
    r"\bmira\s+esto\b",
    r"\bmira\s+aqu[ií]\b",
    r"\bves\s+esto\b",
    r"\bobserva\b",
    r"\bqu[eé]\s+tengo\b",
    r"\bqu[eé]\s+sostengo\b",
    r"\ben\s+mi\s+mano\b",
    r"\bqu[eé]\s+es\s+esto\b",
    r"\bqu[eé]\s+objeto\b",
    r"\bqu[eé]\s+dice\b",
    r"\blee\s+esto\b",
    r"\blee\s+lo\s+que\b",
    r"\bdescribe\s+(?:lo\s+que|la\s+escena|mi|esto|el\s+entorno)\b",
    r"\bqu[eé]\s+hay\s+(?:detr[aá]s|atr[aá]s|en\s+la\s+c[aá]mara|en\s+mi\s+pantalla|aqu[ií]|ah[ií])\b",
    r"\banaliza\s+(?:la\s+imagen|el\s+video|la\s+c[aá]mara|esto|mi\s+pantalla)\b",
    r"\bde\s+qu[eé]\s+color\b",
    r"\bcu[aá]ntas\s+personas\b",
    r"\bqui[eé]n\s+est[aá]\b",
    r"\bwhat\s+do\s+you\s+see\b",
    r"\blook\s+at\s+this\b",
    r"\bcan\s+you\s+see\b",
)
_VISUAL_INTENT_RE = re.compile("|".join(_VISUAL_INTENT_PATTERNS), re.IGNORECASE)


def is_visual_question(text: str) -> bool:
    """Detecta si el usuario está haciendo una pregunta que requiere ver la cámara o pantalla."""
    if not text:
        return False
    return bool(_VISUAL_INTENT_RE.search(text))


def sanitize_vlm_caption(text: str, max_words: int = 85) -> str:
    """Limpia repeticiones y acota el texto VLM para voz en vivo y HUD."""
    if not text:
        return ""
    t = re.sub(r"<think>[\s\S]*?(?:</think>|\Z)", "", str(text), flags=re.IGNORECASE).strip()
    t = re.sub(r"((?:[^,;\n]{3,50})(?:,\s*|\s*;\s*))(?:\1){2,}", r"\1", t, flags=re.IGNORECASE)
    t = re.sub(r"((?:[^.;\n]{5,100})[.;]\s*)(?:\1){2,}", r"\1", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split()
    if len(words) > max_words:
        cut = " ".join(words[:max_words])
        idx = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        t = cut[: idx + 1] if idx > int(len(cut) * 0.55) else cut + "…"
    return t.strip()


@dataclass
class FrameTelemetry:
    width: int = 0
    height: int = 0
    brightness: float = 0.0
    lighting: str = "óptima"
    motion_score: float = 0.0
    faces_count: int = 0
    face_boxes: List[List[float]] = field(default_factory=list)  # [[x, y, w, h] normalized 0..1]
    qr_text: str = ""
    source: str = "camera"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "brightness": round(self.brightness, 1),
            "lighting": self.lighting,
            "motion_score": round(self.motion_score, 3),
            "faces_count": self.faces_count,
            "face_boxes": self.face_boxes,
            "qr_text": self.qr_text,
            "source": self.source,
            "timestamp": round(self.timestamp, 3),
        }


@dataclass
class SceneMemory:
    """Memoria visual viva de una sesión de videollamada."""
    latest_frame_bytes: Optional[bytes] = None
    latest_frame_ts: float = 0.0
    latest_source: str = "camera"
    latest_telemetry: Optional[FrameTelemetry] = None
    latest_description: str = ""
    latest_vlm_ts: float = 0.0
    latest_vlm_source: str = "camera"
    latest_vlm_ms: int = 0
    frames_received: int = 0
    vlm_analyses: int = 0
    significant_motion_since_vlm: bool = False
    observations: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=4))
    _prev_thumb: Optional[np.ndarray] = field(default=None, repr=False)

    def record_vlm_observation(self, description: str, source: str, elapsed_ms: int) -> None:
        now = time.time()
        self.latest_description = description
        self.latest_vlm_ts = now
        self.latest_vlm_source = source
        self.latest_vlm_ms = elapsed_ms
        self.vlm_analyses += 1
        self.significant_motion_since_vlm = False
        self.observations.append(
            {
                "ts": now,
                "time_str": time.strftime("%H:%M:%S"),
                "source": source,
                "description": description,
            }
        )

    def needs_fresh_vlm(self, max_age_sec: float = 10.0) -> bool:
        if not self.latest_frame_bytes:
            return False
        if not self.latest_description:
            return True
        age = time.time() - self.latest_vlm_ts
        if age > max_age_sec:
            return True
        if self.significant_motion_since_vlm and age > 2.5:
            return True
        if self.latest_source != self.latest_vlm_source:
            return True
        return False

    def build_prompt_context(self) -> str:
        """Construye un bloque conciso y fiel de percepción visual para inyectar al LLM."""
        parts: List[str] = []
        now = time.time()
        if self.latest_description:
            age_s = max(0, int(round(now - self.latest_vlm_ts)))
            src_lbl = {
                "camera": "cámara del usuario",
                "screen": "pantalla compartida del usuario",
                "c310": "cámara GOD-EYE C310",
                "host_screen": "pantalla del equipo host",
            }.get(self.latest_vlm_source, self.latest_vlm_source)
            parts.append(f"• Escena actual ({src_lbl}, hace {age_s}s): {self.latest_description}")
        if self.latest_telemetry:
            tel = self.latest_telemetry
            parts.append(
                f"• Telemetría óptica en vivo: {tel.width}x{tel.height}, "
                f"rostros detectados={tel.faces_count}, iluminación={tel.lighting}"
                + (f", QR visible='{tel.qr_text}'" if tel.qr_text else "")
            )
        if len(self.observations) > 1:
            prev = list(self.observations)[-2]
            if prev["description"] != self.latest_description:
                parts.append(f"• Observación previa ({prev['time_str']}): {prev['description']}")
        if not parts:
            return ""
        return (
            "[VISIÓN EN VIVO DE VIDEOLLAMADA — PERCEPCIÓN REAL]:\n"
            + "\n".join(parts)
            + "\nUsa esta percepción visual con naturalidad cuando sea relevante; no inventes detalles que no aparezcan aquí."
        )


class VideoCallVisionEngine:
    """Motor compartido de telemetría óptica instantánea + VLM asíncrono para videollamadas."""

    def __init__(self, vlm_model: str = VLM_DEFAULT_MODEL):
        self.vlm_model = vlm_model
        self._vlm_sem = asyncio.Semaphore(1)
        self._face_cascade = None
        if HAAR_FACE_PATH.exists():
            try:
                self._face_cascade = cv2.CascadeClassifier(str(HAAR_FACE_PATH))
            except Exception as exc:
                logger.debug(f"Haar face cascade no disponible: {exc}")
        self._qr_detector = cv2.QRCodeDetector() if hasattr(cv2, "QRCodeDetector") else None

    def normalize_jpeg(self, raw_bytes: bytes, max_side: int = 480, quality: int = 75) -> bytes:
        """Valida y reescala un fotograma JPEG/PNG/WebP a tamaño óptimo para análisis VLM."""
        if not raw_bytes:
            return b""
        try:
            im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue()
        except Exception:
            return raw_bytes

    def inspect_frame_fast(
        self,
        raw_bytes: bytes,
        scene: SceneMemory,
        source: str = "camera",
    ) -> FrameTelemetry:
        """
        Análisis óptico instantáneo en CPU (< 30 ms):
        resolución, iluminación, delta de movimiento, rostros (cajas normalizadas) y QR.
        """
        tel = FrameTelemetry(source=source, timestamp=time.time())
        if not raw_bytes or len(raw_bytes) < 64:
            return tel

        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            return tel

        h, w = bgr.shape[:2]
        tel.width = int(w)
        tel.height = int(h)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mean_luma = float(np.mean(gray))
        tel.brightness = mean_luma
        if mean_luma < 42:
            tel.lighting = "oscura"
        elif mean_luma < 82:
            tel.lighting = "tenue"
        elif mean_luma > 215:
            tel.lighting = "muy brillante"
        else:
            tel.lighting = "óptima"

        thumb = cv2.resize(gray, (64, 48), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        if scene._prev_thumb is not None:
            delta = float(np.mean(np.abs(thumb - scene._prev_thumb)))
            tel.motion_score = min(1.0, delta * 3.0)
            if tel.motion_score >= 0.14:
                scene.significant_motion_since_vlm = True
        else:
            tel.motion_score = 1.0
            scene.significant_motion_since_vlm = True
        scene._prev_thumb = thumb

        # Detección de rostros rápida sobre imagen reducida
        if self._face_cascade is not None and source in ("camera", "c310"):
            try:
                scale_w = min(w, 320)
                ratio = scale_w / float(w)
                small_h = max(1, int(h * ratio))
                small_gray = cv2.resize(gray, (scale_w, small_h), interpolation=cv2.INTER_AREA)
                faces = self._face_cascade.detectMultiScale(
                    small_gray,
                    scaleFactor=1.18,
                    minNeighbors=4,
                    minSize=(24, 24),
                )
                boxes: List[List[float]] = []
                for (fx, fy, fw, fh) in faces[:6]:
                    boxes.append(
                        [
                            round(float(fx) / scale_w, 4),
                            round(float(fy) / small_h, 4),
                            round(float(fw) / scale_w, 4),
                            round(float(fh) / small_h, 4),
                        ]
                    )
                tel.faces_count = len(boxes)
                tel.face_boxes = boxes
            except Exception:
                pass

        # Detección de QR (ligera)
        if self._qr_detector is not None and (scene.frames_received % 3 == 0):
            try:
                qr_txt, _pts, _ = self._qr_detector.detectAndDecode(gray)
                if qr_txt:
                    tel.qr_text = str(qr_txt)[:160]
            except Exception:
                pass

        scene.latest_frame_bytes = raw_bytes
        scene.latest_frame_ts = tel.timestamp
        scene.latest_source = source
        scene.latest_telemetry = tel
        scene.frames_received += 1
        return tel

    async def analyze_frame_vlm(
        self,
        raw_bytes: bytes,
        question: str = "",
        source: str = "camera",
        timeout_sec: float = 38.0,
    ) -> Dict[str, Any]:
        """
        Ejecuta inferencia multimodal real con Qwen3-VL en el carril GPU dedicado (:11435),
        manteniendo los parámetros exactos de VRAM para evitar recargas del modelo.
        """
        if not raw_bytes:
            return {"ok": False, "error": "Sin fotograma disponible"}

        loop = asyncio.get_running_loop()
        norm_bytes = await loop.run_in_executor(None, self.normalize_jpeg, raw_bytes, 480, 75)
        b64_img = base64.b64encode(norm_bytes).decode("ascii")

        src_desc = {
            "camera": "la cámara en vivo del usuario durante una videollamada",
            "screen": "la pantalla que el usuario está compartiendo durante una videollamada",
            "c310": "la cámara de seguridad GOD-EYE C310 en vivo",
            "host_screen": "la pantalla en vivo del escritorio host de TARDIS",
        }.get(source, "una cámara en vivo")

        if question.strip():
            prompt = (
                f"Observa literalmente esta imagen ({src_desc}) y responde en español en 1 a 3 frases claras y objetivas. "
                f"Describe solo lo que es realmente visible; si no hay personas u objetos mencionados, dilo sin inventar. "
                f"Pregunta: {question.strip()}"
            )
            max_predict = 95
        else:
            prompt = (
                "Describe literalmente en 1 o 2 frases breves en español solo lo que aparece en esta imagen "
                "(personas únicamente si realmente hay alguna visible, objetos, formas, colores, texto legible o entorno). "
                "No supongas ni inventes elementos que no se vean."
            )
            max_predict = 75

        t0 = time.perf_counter()
        async with self._vlm_sem:
            for endpoint, is_gpu_lane in (
                (OLLAMA_VLM_GPU_URL, True),
                (OLLAMA_VLM_FALLBACK_URL, False),
            ):
                if not endpoint:
                    continue
                options: Dict[str, Any] = {
                    "temperature": 0.15,
                    "num_ctx": VLM_GPU_NUM_CTX,
                    "num_predict": max_predict,
                    "top_k": 20,
                    "top_p": 0.9,
                    "repeat_penalty": 1.15,
                }
                if is_gpu_lane:
                    options["num_gpu"] = VLM_GPU_NUM_GPU

                payload = {
                    "model": self.vlm_model,
                    "prompt": prompt,
                    "images": [b64_img],
                    "stream": False,
                    "think": False,
                    "keep_alive": -1 if is_gpu_lane else 0,
                    "options": options,
                }
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(connect=3.0, read=timeout_sec, write=10.0, pool=5.0)
                    ) as client:
                        resp = await client.post(f"{endpoint}/api/generate", json=payload)
                    if resp.status_code == 200:
                        body = resp.json()
                        raw_txt = (body.get("response") or body.get("thinking") or "").strip()
                        clean = sanitize_vlm_caption(raw_txt, max_words=90)
                        if clean:
                            elapsed_ms = int((time.perf_counter() - t0) * 1000)
                            return {
                                "ok": True,
                                "description": clean,
                                "model": self.vlm_model,
                                "endpoint": endpoint,
                                "source": source,
                                "elapsed_ms": elapsed_ms,
                            }
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug(f"VLM endpoint {endpoint} falló: {exc}")
                    continue

        return {
            "ok": False,
            "error": "No se pudo consultar el motor visual Qwen3-VL en este instante.",
            "model": self.vlm_model,
            "source": source,
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }

    async def fetch_c310_frame_bytes(
        self,
        width: int = 960,
        quality: int = 74,
        hud: bool = True,
    ) -> Optional[bytes]:
        """Obtiene un fotograma JPEG en vivo de la cámara física GOD-EYE C310 (:8797)."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0)) as client:
                r = await client.get(
                    f"{SENTINEL_HUB_URL}/c310/snapshot.jpg",
                    params={"hud": "1" if hud else "0", "width": str(width), "quality": str(quality)},
                )
                if r.status_code == 200 and r.content:
                    return r.content
        except Exception as exc:
            logger.debug(f"Error leyendo frame C310: {exc}")
        return None

    async def capture_host_screen_bytes(
        self,
        max_width: int = 1280,
        quality: int = 72,
    ) -> Optional[bytes]:
        """Captura en vivo la pantalla del equipo host (Wayland/Hyprland) para compartir en videollamada."""
        def _grab() -> Optional[bytes]:
            try:
                from core import screen_capture
                if screen_capture.is_locked():
                    return None
                raw, _meta = screen_capture.capture(fmt="jpeg", max_width=max_width, quality=quality)
                return raw or None
            except Exception as exc:
                logger.debug(f"Error capturando pantalla del host: {exc}")
                return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _grab)

    def save_snapshot(self, raw_bytes: bytes, chat_id: str, source: str = "camera") -> Optional[Path]:
        """Guarda una captura solicitada durante la videollamada."""
        if not raw_bytes:
            return None
        try:
            SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            safe_cid = re.sub(r"[^0-9A-Za-z_-]", "", str(chat_id or "anon")) or "anon"
            safe_src = re.sub(r"[^0-9A-Za-z_-]", "", str(source or "camera")) or "camera"
            path = SNAPSHOTS_DIR / f"vc_{safe_cid}_{safe_src}_{int(time.time())}.jpg"
            path.write_bytes(raw_bytes)
            return path
        except Exception as exc:
            logger.warning(f"No se pudo guardar snapshot de videollamada: {exc}")
            return None


_VISION_ENGINE: Optional[VideoCallVisionEngine] = None


def get_videocall_vision_engine() -> VideoCallVisionEngine:
    global _VISION_ENGINE
    if _VISION_ENGINE is None:
        _VISION_ENGINE = VideoCallVisionEngine()
    return _VISION_ENGINE
