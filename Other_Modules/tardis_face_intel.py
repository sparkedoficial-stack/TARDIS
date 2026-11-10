#!/usr/bin/env python3
"""
core/tardis_face_intel.py - Motor de Inteligencia Biométrica Facial TARDIS (GOD-EYE)
====================================================================================
Analiza cada individuo detectado por el centinela perimetral Tapo C310 y produce:

  • Detección y alineación facial (OpenCV YuNet + SFace ONNX).
  • Identidad local: re-identificación contra el registro de personas conocidas
    (`data/tardis_face_intel/known_persons/`) y agrupación persistente de
    visitantes desconocidos (U-0001, U-0002, ...).
  • Edad física estimada (ONNX age_googlenet, 8 rangos etarios).
  • Estado emocional (ONNX emotion-ferplus, 8 emociones FER+).
  • Estatura y distancia estimadas por geometría de cámara (modelo pinhole +
    altura/inclinación/FOV configurables).
  • Permanencia frente a la cámara (inyectada por el rastreador del centinela).
  • Expediente biométrico JSON por alerta, con recortes faciales y embedding.

No realiza búsquedas automatizadas de identidad en redes sociales ni en bases
de datos externas: la identificación positiva proviene únicamente del registro
local consentido del Arquitecto. Los sujetos no registrados se documentan como
expediente biométrico para revisión humana o para entrega a autoridades.

CLI:
    python -m core.tardis_face_intel analyze --photo ruta.jpg
    python -m core.tardis_face_intel enroll --name "Annya May Carrillo" --age 34 --photo rostro.jpg
    python -m core.tardis_face_intel list
    python -m core.tardis_face_intel forget --person-id p_0001
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

logger = logging.getLogger("TARDIS.FaceIntel")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# Clases del modelo age_googlenet (ONNX Model Zoo)
AGE_BUCKETS: Tuple[Tuple[int, int], ...] = (
    (0, 2),
    (4, 6),
    (8, 12),
    (15, 20),
    (25, 32),
    (38, 43),
    (48, 53),
    (60, 100),
)
AGE_LABELS: Tuple[str, ...] = tuple(f"{lo}-{hi}" for lo, hi in AGE_BUCKETS)

# Orden oficial del modelo emotion-ferplus (FER+)
EMOTION_LABELS: Tuple[str, ...] = (
    "neutral",
    "felicidad",
    "sorpresa",
    "tristeza",
    "enojo",
    "disgusto",
    "miedo",
    "desprecio",
)

DEFAULT_DATA_DIR = BASE_DIR / "data" / "tardis_face_intel"


def _softmax(logits: np.ndarray) -> np.ndarray:
    x = np.asarray(logits, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return x
    x = x - float(np.max(x))
    e = np.exp(x)
    s = float(np.sum(e))
    return e / s if s > 1e-9 else np.ones_like(e) / float(e.size)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _fmt_dwell(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"


@dataclass
class PersonIntelInput:
    """Entrada por individuo: caja YOLO + metadatos de permanencia del tracker."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 0.0
    track_id: Optional[int] = None
    dwell_sec: float = 0.0


@dataclass
class FaceIntelRecord:
    """Resultado biométrico de un rostro, serializable a JSON y a HUD."""

    person_index: int
    person_bbox: List[int]
    person_confidence: float
    track_id: Optional[int]
    dwell_sec: float

    face_detected: bool = False
    face_bbox: Optional[List[int]] = None
    face_score: float = 0.0
    face_crop_path: str = ""

    identity_status: str = "NO_REGISTRADO"
    identity_name: str = ""
    person_id: str = ""
    identity_similarity: float = 0.0
    identity_source: str = "registro_local_tardis"

    age_estimate: Optional[float] = None
    age_range: str = ""
    age_confidence: float = 0.0
    age_source: str = ""

    emotion: str = ""
    emotion_confidence: float = 0.0
    emotion_scores: Dict[str, float] = field(default_factory=dict)

    height_m: Optional[float] = None
    distance_m: Optional[float] = None
    height_confidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "person_index": self.person_index,
            "person_bbox": self.person_bbox,
            "person_confidence": round(float(self.person_confidence), 4),
            "track_id": self.track_id,
            "dwell_sec": round(float(self.dwell_sec), 2),
            "dwell_human": _fmt_dwell(self.dwell_sec),
            "face_detected": self.face_detected,
            "face_bbox": self.face_bbox,
            "face_score": round(float(self.face_score), 4),
            "face_crop_path": self.face_crop_path,
            "identity_status": self.identity_status,
            "identity_name": self.identity_name,
            "person_id": self.person_id,
            "identity_similarity": round(float(self.identity_similarity), 4),
            "identity_source": self.identity_source,
            "age_estimate": None if self.age_estimate is None else round(float(self.age_estimate), 1),
            "age_range": self.age_range,
            "age_confidence": round(float(self.age_confidence), 4),
            "age_source": self.age_source,
            "emotion": self.emotion,
            "emotion_confidence": round(float(self.emotion_confidence), 4),
            "emotion_scores": {k: round(float(v), 4) for k, v in self.emotion_scores.items()},
            "height_m": None if self.height_m is None else round(float(self.height_m), 2),
            "distance_m": None if self.distance_m is None else round(float(self.distance_m), 2),
            "height_confidence": self.height_confidence,
        }

    def summary_line(self) -> str:
        parts: List[str] = []
        if self.identity_status == "CONOCIDO":
            parts.append(f"ID: {self.identity_name} ({self.identity_similarity:.2f})")
        elif self.person_id:
            parts.append(f"ID: {self.person_id} · NO REGISTRADO")
        else:
            parts.append("ID: NO REGISTRADO")
        if self.age_estimate is not None:
            parts.append(f"EDAD ~{self.age_estimate:.0f}a ({self.age_range})")
        if self.height_m is not None:
            parts.append(f"EST ~{self.height_m:.2f}m")
        if self.emotion:
            parts.append(f"EMOCIÓN {self.emotion.upper()} {self.emotion_confidence * 100:.0f}%")
        parts.append(f"PERMANENCIA {_fmt_dwell(self.dwell_sec)}")
        return " · ".join(parts)


class FaceIntelEngine:
    """Motor biométrico local con modelos ONNX/OpenCV y registro persistente."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = dict(config or {})

        def _resolve(rel: str, fallback: str) -> Path:
            raw = str(self.config.get(rel, fallback) or fallback)
            p = Path(raw)
            return p if p.is_absolute() else BASE_DIR / p

        self.enabled = bool(self.config.get("face_intel_enabled", True))
        self.yunet_path = _resolve(
            "face_intel_yunet_model", "models/face_detection_yunet_2023mar.onnx"
        )
        self.sface_path = _resolve(
            "face_intel_sface_model", "models/face_recognition_sface_2021dec.onnx"
        )
        self.age_model_path = _resolve(
            "face_intel_age_model", "models/age_googlenet.onnx"
        )
        self.emotion_model_path = _resolve(
            "face_intel_emotion_model", "models/emotion_ferplus.onnx"
        )

        data_dir_raw = str(self.config.get("face_intel_data_dir", "data/tardis_face_intel"))
        data_dir = Path(data_dir_raw)
        self.data_dir = data_dir if data_dir.is_absolute() else BASE_DIR / data_dir
        self.known_dir = self.data_dir / "known_persons"
        self.known_index_path = self.known_dir / "index.json"
        self.faces_dir = self.data_dir / "faces"
        self.dossier_dir = self.data_dir / "dossiers"
        self.unknown_index_path = self.data_dir / "unknown_visitors.json"
        self.investigation_ledger = self.data_dir / "investigation_ledger.jsonl"

        for d in (self.data_dir, self.known_dir, self.faces_dir, self.dossier_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.identity_threshold = float(self.config.get("face_intel_identity_threshold", 0.42))
        self.unknown_threshold = float(
            self.config.get("face_intel_unknown_cluster_threshold", 0.40)
        )
        self.max_faces = max(1, int(self.config.get("face_intel_max_faces", 8)))
        self.save_face_crops = bool(self.config.get("face_intel_save_crops", True))

        # Geometría de cámara para estatura/distancia
        self.camera_height_m = float(self.config.get("camera_height_m", 2.55))
        self.camera_pitch_deg = float(self.config.get("camera_pitch_deg", 14.0))
        self.camera_diag_fov_deg = float(self.config.get("camera_diag_fov_deg", 114.0))

        self._model_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._models_ready = False
        self._init_error = ""
        self._yunet: Any = None
        self._sface: Any = None
        self._age_session: Any = None
        self._emotion_session: Any = None
        self._age_input = ""
        self._emotion_input = ""

        self._known_cache_ts = 0.0
        self._known_persons: List[Dict[str, Any]] = []
        self._unknown_visitors: List[Dict[str, Any]] = []
        self._unknown_loaded = False
        self._next_unknown_id = 1

    # ------------------------------------------------------------------
    # Registro de personas conocidas / visitantes desconocidos
    # ------------------------------------------------------------------
    def _load_known_persons(self, force: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        if not force and (now - self._known_cache_ts) < 30.0 and self._known_persons:
            return self._known_persons
        index = _load_json(self.known_index_path, {"persons": []})
        persons: List[Dict[str, Any]] = []
        for entry in index.get("persons", []):
            p = dict(entry)
            emb_file = str(p.get("embedding_file", ""))
            if not emb_file:
                continue
            emb_path = self.known_dir / emb_file
            if not emb_path.is_file():
                continue
            try:
                emb = np.load(emb_path).astype(np.float32).reshape(-1)
                p["_embedding"] = _l2_normalize(emb)
                persons.append(p)
            except Exception as exc:
                logger.debug(f"Embedding ilegible para {p.get('name')}: {exc}")
        self._known_persons = persons
        self._known_cache_ts = now
        return persons

    def _load_unknown_visitors(self) -> None:
        if self._unknown_loaded:
            return
        payload = _load_json(self.unknown_index_path, {"next_id": 1, "visitors": []})
        self._unknown_visitors = list(payload.get("visitors", []))
        self._next_unknown_id = int(payload.get("next_id", 1) or 1)
        for v in self._unknown_visitors:
            try:
                v["_embedding"] = _l2_normalize(
                    np.frombuffer(base64.b64decode(v["embedding_b64"]), dtype=np.float32)
                )
            except Exception:
                v["_embedding"] = None
        self._unknown_loaded = True

    def _save_unknown_visitors(self) -> None:
        out: List[Dict[str, Any]] = []
        for v in self._unknown_visitors:
            emb = v.get("_embedding")
            if emb is None:
                continue
            out.append(
                {
                    "person_id": v.get("person_id"),
                    "first_seen_ts": v.get("first_seen_ts"),
                    "last_seen_ts": v.get("last_seen_ts"),
                    "seen_count": v.get("seen_count", 1),
                    "last_age_estimate": v.get("last_age_estimate"),
                    "last_emotion": v.get("last_emotion"),
                    "embedding_b64": base64.b64encode(
                        np.asarray(emb, dtype=np.float32).tobytes()
                    ).decode("ascii"),
                }
            )
        _atomic_write_json(
            self.unknown_index_path,
            {"next_id": self._next_unknown_id, "visitors": out},
        )

    def _resolve_unknown_identity(self, embedding: np.ndarray, now: float) -> Tuple[str, float]:
        """Agrupa rostros no registrados en identidades anónimas persistentes U-####."""
        self._load_unknown_visitors()
        best: Optional[Dict[str, Any]] = None
        best_sim = -1.0
        for v in self._unknown_visitors:
            emb = v.get("_embedding")
            if emb is None or emb.shape != embedding.shape:
                continue
            sim = float(np.dot(embedding, emb))
            if sim > best_sim:
                best_sim = sim
                best = v
        if best is not None and best_sim >= self.unknown_threshold:
            prev = best["_embedding"]
            merged = _l2_normalize(0.7 * prev + 0.3 * embedding)
            best["_embedding"] = merged
            best["last_seen_ts"] = now
            best["seen_count"] = int(best.get("seen_count", 1)) + 1
            return str(best.get("person_id", "")), best_sim

        person_id = f"U-{self._next_unknown_id:04d}"
        self._next_unknown_id += 1
        self._unknown_visitors.append(
            {
                "person_id": person_id,
                "first_seen_ts": now,
                "last_seen_ts": now,
                "seen_count": 1,
                "_embedding": _l2_normalize(embedding),
            }
        )
        return person_id, 0.0

    def _match_known_identity(
        self, embedding: np.ndarray
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        best: Optional[Dict[str, Any]] = None
        best_sim = -1.0
        for person in self._load_known_persons():
            emb = person.get("_embedding")
            if emb is None or emb.shape != embedding.shape:
                continue
            sim = float(np.dot(embedding, emb))
            if sim > best_sim:
                best_sim = sim
                best = person
        if best is not None and best_sim >= self.identity_threshold:
            return best, best_sim
        return None, max(0.0, best_sim)

    # ------------------------------------------------------------------
    # Carga perezosa de modelos
    # ------------------------------------------------------------------
    def _ensure_models(self) -> None:
        if self._models_ready or self._init_error:
            return
        with self._model_lock:
            if self._models_ready or self._init_error:
                return
            try:
                if not self.yunet_path.is_file():
                    raise FileNotFoundError(f"YuNet ausente: {self.yunet_path}")
                if not self.sface_path.is_file():
                    raise FileNotFoundError(f"SFace ausente: {self.sface_path}")
                self._yunet = cv2.FaceDetectorYN.create(
                    str(self.yunet_path), "", (640, 640), 0.55, 0.30, 5000
                )
                self._sface = cv2.FaceRecognizerSF.create(str(self.sface_path), "")

                try:
                    import onnxruntime as ort

                    providers = ["CPUExecutionProvider"]
                    available = ort.get_available_providers()
                    if "CUDAExecutionProvider" in available:
                        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

                    if self.age_model_path.is_file():
                        self._age_session = ort.InferenceSession(
                            str(self.age_model_path), providers=providers
                        )
                        self._age_input = self._age_session.get_inputs()[0].name
                    if self.emotion_model_path.is_file():
                        self._emotion_session = ort.InferenceSession(
                            str(self.emotion_model_path), providers=providers
                        )
                        self._emotion_input = self._emotion_session.get_inputs()[0].name
                except Exception as exc_models:
                    logger.warning(f"Modelos de edad/emoción no disponibles: {exc_models}")

                self._models_ready = True
                logger.info(
                    "Motor biométrico facial listo (YuNet + SFace"
                    + (", edad" if self._age_session is not None else "")
                    + (", emoción" if self._emotion_session is not None else "")
                    + ")."
                )
            except Exception as exc:
                self._init_error = str(exc)
                logger.error(f"No se pudo inicializar el motor facial: {exc}")

    # ------------------------------------------------------------------
    # Inferencia
    # ------------------------------------------------------------------
    def _estimate_age(self, aligned_bgr: np.ndarray) -> Tuple[Optional[float], str, float, np.ndarray]:
        if self._age_session is None:
            return None, "", 0.0, np.zeros(0, dtype=np.float32)
        try:
            inp = cv2.resize(aligned_bgr, (224, 224), interpolation=cv2.INTER_LINEAR).astype(
                np.float32
            )
            inp -= np.array([104.0, 117.0, 123.0], dtype=np.float32)
            blob = inp.transpose(2, 0, 1)[None, ...]
            logits = self._age_session.run(None, {self._age_input: blob})[0][0]
            probs = _softmax(logits)
            idx = int(np.argmax(probs))
            lo, hi = AGE_BUCKETS[idx]
            est = (lo + hi) / 2.0
            # Refinamiento continuo ponderado por todas las clases
            weighted = sum(
                probs[i] * ((AGE_BUCKETS[i][0] + AGE_BUCKETS[i][1]) / 2.0)
                for i in range(min(len(probs), len(AGE_BUCKETS)))
            )
            if 0.0 < weighted < 110.0:
                est = 0.65 * est + 0.35 * weighted
            return float(est), AGE_LABELS[idx], float(probs[idx]), probs
        except Exception as exc:
            logger.debug(f"Inferencia de edad falló: {exc}")
            return None, "", 0.0, np.zeros(0, dtype=np.float32)

    def _estimate_emotion(
        self, aligned_bgr: np.ndarray
    ) -> Tuple[str, float, Dict[str, float]]:
        if self._emotion_session is None:
            return "", 0.0, {}
        try:
            gray = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
            blob = gray.reshape(1, 1, 64, 64)
            logits = self._emotion_session.run(None, {self._emotion_input: blob})[0][0]
            probs = _softmax(logits)
            idx = int(np.argmax(probs))
            label = EMOTION_LABELS[idx] if idx < len(EMOTION_LABELS) else str(idx)
            scores = {
                EMOTION_LABELS[i]: float(probs[i])
                for i in range(min(len(probs), len(EMOTION_LABELS)))
            }
            return label, float(probs[idx]), scores
        except Exception as exc:
            logger.debug(f"Inferencia emocional falló: {exc}")
            return "", 0.0, {}

    def _estimate_height_distance(
        self, person: PersonIntelInput, frame_shape: Tuple[int, int]
    ) -> Tuple[Optional[float], Optional[float], str]:
        """
        Modelo pinhole con plano de suelo:
          d_suelo = h_cámara / tan(pitch + atan((y_pies - c_y) / f_y))
          estatura = h_cámara - d_suelo * tan(pitch + atan((y_cabeza - c_y) / f_y))
        """
        try:
            fh, fw = frame_shape
            if fh < 32 or fw < 32:
                return None, None, ""
            aspect = fw / float(fh)
            tan_diag = math.tan(math.radians(max(20.0, self.camera_diag_fov_deg) / 2.0))
            tan_v = tan_diag / math.sqrt(1.0 + aspect * aspect)
            fy = (fh / 2.0) / max(1e-6, tan_v)
            cy = fh / 2.0
            pitch = math.radians(self.camera_pitch_deg)

            y_feet = min(fh - 1.0, max(0.0, float(person.y2)))
            y_head = min(fh - 1.0, max(0.0, float(person.y1)))
            a_bottom = pitch + math.atan2(y_feet - cy, fy)
            a_top = pitch + math.atan2(y_head - cy, fy)

            # Si los pies están por encima de la línea del horizonte, no hay plano válido
            if a_bottom <= math.radians(2.0) or a_bottom >= math.radians(88.0):
                return None, None, ""
            d_ground = self.camera_height_m / math.tan(a_bottom)
            if not (0.35 <= d_ground <= 45.0):
                return None, None, ""

            head_height = self.camera_height_m - d_ground * math.tan(a_top)
            if not (1.05 <= head_height <= 2.35):
                return None, None, ""
            conf = "MEDIA"
            if person.y2 >= fh - 4:
                conf = "BAJA"
            elif person.y1 <= 4:
                conf = "BAJA"
            return float(head_height), float(d_ground), conf
        except Exception:
            return None, None, ""

    def analyze(
        self,
        bgr_frame: np.ndarray,
        persons: Sequence[PersonIntelInput],
        timestamp: Optional[float] = None,
        save_crops: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Analiza todos los individuos y devuelve registros serializables."""
        if not self.enabled or bgr_frame is None or not persons:
            return []
        self._ensure_models()
        if not self._models_ready:
            return []

        now = float(timestamp if timestamp is not None else time.time())
        save_crops = self.save_face_crops if save_crops is None else bool(save_crops)
        fh, fw = bgr_frame.shape[:2]
        records: List[Dict[str, Any]] = []

        with self._infer_lock:
            for idx, person in enumerate(persons[: self.max_faces], start=1):
                rec = FaceIntelRecord(
                    person_index=idx,
                    person_bbox=[int(person.x1), int(person.y1), int(person.x2), int(person.y2)],
                    person_confidence=float(person.confidence),
                    track_id=person.track_id,
                    dwell_sec=float(person.dwell_sec),
                )

                h_est, d_est, h_conf = self._estimate_height_distance(person, (fh, fw))
                rec.height_m, rec.distance_m, rec.height_confidence = h_est, d_est, h_conf

                # Recorte superior del individuo (la cara ocupa la franja cefálica)
                pad_x = int(max(0, person.x2 - person.x1) * 0.08)
                cx1 = max(0, person.x1 - pad_x)
                cy1 = max(0, person.y1 - int(max(0, person.y2 - person.y1) * 0.03))
                cx2 = min(fw, person.x2 + pad_x)
                cy2 = min(fh, person.y1 + int(max(1, person.y2 - person.y1) * 0.62))
                if cx2 - cx1 < 24 or cy2 - cy1 < 24:
                    records.append(rec.to_dict())
                    continue
                crop = bgr_frame[cy1:cy2, cx1:cx2]
                ch, cw = crop.shape[:2]

                # Escalar recorte para que YuNet vea rostros pequeños con detalle
                det_scale = max(1.0, min(2.5, 900.0 / float(max(cw, ch))))
                if det_scale > 1.01:
                    detect_img = cv2.resize(
                        crop,
                        (int(round(cw * det_scale)), int(round(ch * det_scale))),
                        interpolation=cv2.INTER_CUBIC,
                    )
                else:
                    detect_img = crop
                dh, dw = detect_img.shape[:2]
                self._yunet.setInputSize((dw, dh))
                _, faces = self._yunet.detect(detect_img)
                if faces is None or len(faces) == 0:
                    records.append(rec.to_dict())
                    continue

                # Elegir el rostro de mayor confianza dentro del recorte
                best_row = max(faces, key=lambda row: float(row[-1]))
                fx, fy, fw_box, fh_box = [float(v) for v in best_row[:4]]
                score = float(best_row[-1])
                rec.face_detected = True
                rec.face_score = score
                rec.face_bbox = [
                    int(round(cx1 + fx / det_scale)),
                    int(round(cy1 + fy / det_scale)),
                    int(round(cx1 + (fx + fw_box) / det_scale)),
                    int(round(cy1 + (fy + fh_box) / det_scale)),
                ]

                try:
                    aligned = self._sface.alignCrop(detect_img, best_row)
                    feature = self._sface.feature(aligned)
                    embedding = _l2_normalize(np.asarray(feature).reshape(-1))
                except Exception as exc:
                    logger.debug(f"Alineación/embedding facial falló: {exc}")
                    records.append(rec.to_dict())
                    continue

                known, sim = self._match_known_identity(embedding)
                if known is not None:
                    rec.identity_status = "CONOCIDO"
                    rec.identity_name = str(known.get("name", "SIN NOMBRE"))
                    rec.person_id = str(known.get("person_id", ""))
                    rec.identity_similarity = sim
                    rec.identity_source = "registro_local_tardis"
                    if known.get("age") is not None:
                        try:
                            reg_age = float(known["age"])
                            rec.age_estimate = reg_age
                            rec.age_range = "registro"
                            rec.age_confidence = 1.0
                            rec.age_source = "registro_local"
                        except Exception:
                            pass
                else:
                    uid, usize = self._resolve_unknown_identity(embedding, now)
                    rec.identity_status = "NO_REGISTRADO"
                    rec.person_id = uid
                    rec.identity_similarity = usize
                    rec.identity_name = f"VISITANTE DESCONOCIDO {uid}"

                # Edad y emoción desde el rostro alineado (112x112)
                if rec.age_estimate is None or rec.age_source != "registro_local":
                    age, rng, conf, _ = self._estimate_age(aligned)
                    if age is not None:
                        rec.age_estimate = age
                        rec.age_range = rng
                        rec.age_confidence = conf
                        rec.age_source = "vision_edad_onnx"
                emo, emo_conf, emo_scores = self._estimate_emotion(aligned)
                rec.emotion = emo
                rec.emotion_confidence = emo_conf
                rec.emotion_scores = emo_scores

                if save_crops:
                    try:
                        ts_tag = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
                        ms_tag = int((now % 1.0) * 1000)
                        pid = rec.person_id or f"idx{idx}"
                        crop_path = self.faces_dir / f"{ts_tag}_{ms_tag:03d}_{pid}.jpg"
                        cv2.imwrite(
                            str(crop_path),
                            aligned,
                            [int(cv2.IMWRITE_JPEG_QUALITY), 94],
                        )
                        rec.face_crop_path = str(crop_path)
                    except Exception as exc:
                        logger.debug(f"No se pudo guardar recorte facial: {exc}")

                records.append(rec.to_dict())

        try:
            self._save_unknown_visitors()
        except Exception as exc:
            logger.debug(f"No se pudo persistir visitantes desconocidos: {exc}")
        return records

    # ------------------------------------------------------------------
    # Expediente / dossier
    # ------------------------------------------------------------------
    def build_dossier(
        self,
        records: Sequence[Dict[str, Any]],
        *,
        camera_alias: str,
        camera_host: str,
        alert_kind: str,
        timestamp: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = float(timestamp if timestamp is not None else time.time())
        ts_human = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        dossier = {
            "schema": "tardis.face_intel.dossier.v1",
            "generated_at": now,
            "generated_iso": ts_human,
            "camera": {"alias": camera_alias, "host": camera_host},
            "alert_kind": alert_kind,
            "subjects_count": len(records),
            "subjects": list(records),
            "identity_resolution": {
                "scope": "registro_local_tardis",
                "external_face_search": bool(
                    self.config.get("face_intel_external_search_enabled", False)
                ),
                "note": (
                    "La identificación positiva se limita al registro local consentido. "
                    "Los sujetos no registrados quedan documentados para revisión humana."
                ),
            },
            "privacy": {
                "aegis": "Constante AEGIS activa",
                "retention_days": int(self.config.get("face_intel_retention_days", 30)),
            },
        }
        if extra:
            dossier.update(extra)

        try:
            ts_file = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
            ms = int((now % 1.0) * 1000)
            path = self.dossier_dir / f"dossier_{ts_file}_{ms:03d}.json"
            _atomic_write_json(path, dossier)
            dossier["dossier_path"] = str(path)
            with open(self.investigation_ledger, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(dossier, ensure_ascii=False) + "\n")
            self._prune_dossiers()
        except Exception as exc:
            logger.warning(f"No se pudo escribir expediente biométrico: {exc}")
        return dossier

    def _prune_dossiers(self) -> None:
        try:
            keep = max(20, int(self.config.get("face_intel_max_dossiers", 1000)))
            files = sorted(
                self.dossier_dir.glob("dossier_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[keep:]:
                old.unlink(missing_ok=True)
            keep_faces = max(50, int(self.config.get("face_intel_max_face_crops", 2000)))
            crops = sorted(
                self.faces_dir.glob("*.jpg"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in crops[keep_faces:]:
                old.unlink(missing_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Registro / CLI
    # ------------------------------------------------------------------
    def enroll_person(
        self,
        name: str,
        photo_path: Path,
        age: Optional[float] = None,
        relation: str = "",
        watch: bool = False,
        notes: str = "",
    ) -> Dict[str, Any]:
        self._ensure_models()
        if not self._models_ready:
            return {"ok": False, "error": self._init_error or "motor facial no disponible"}
        img = cv2.imread(str(photo_path), cv2.IMREAD_COLOR)
        if img is None:
            return {"ok": False, "error": f"No se pudo leer la fotografía: {photo_path}"}
        h, w = img.shape[:2]
        self._yunet.setInputSize((w, h))
        _, faces = self._yunet.detect(img)
        if faces is None or len(faces) == 0:
            return {"ok": False, "error": "No se detectó ningún rostro en la fotografía."}
        row = max(faces, key=lambda r: float(r[-1]))
        aligned = self._sface.alignCrop(img, row)
        feature = _l2_normalize(np.asarray(self._sface.feature(aligned)).reshape(-1))

        index = _load_json(self.known_index_path, {"persons": []})
        existing = index.get("persons", [])
        next_num = 1
        for p in existing:
            pid = str(p.get("person_id", ""))
            if pid.startswith("p_"):
                try:
                    next_num = max(next_num, int(pid.split("_", 1)[1]) + 1)
                except Exception:
                    pass
        person_id = f"p_{next_num:04d}"
        emb_file = f"{person_id}.npy"
        np.save(self.known_dir / emb_file, feature)

        entry = {
            "person_id": person_id,
            "name": name.strip(),
            "age": age,
            "relation": relation.strip(),
            "watch": bool(watch),
            "notes": notes.strip(),
            "embedding_file": emb_file,
            "created_at": time.time(),
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        existing.append(entry)
        _atomic_write_json(self.known_index_path, {"persons": existing})
        self._load_known_persons(force=True)
        return {"ok": True, "person": entry, "face_score": float(row[-1])}

    def forget_person(self, person_id: str) -> Dict[str, Any]:
        index = _load_json(self.known_index_path, {"persons": []})
        persons = index.get("persons", [])
        kept = [p for p in persons if str(p.get("person_id")) != person_id]
        if len(kept) == len(persons):
            return {"ok": False, "error": f"No existe {person_id}"}
        for p in persons:
            if str(p.get("person_id")) == person_id and p.get("embedding_file"):
                (self.known_dir / str(p["embedding_file"])).unlink(missing_ok=True)
        _atomic_write_json(self.known_index_path, {"persons": kept})
        self._load_known_persons(force=True)
        return {"ok": True, "removed": person_id}

    def list_known_persons(self) -> List[Dict[str, Any]]:
        return [
            {k: v for k, v in p.items() if not k.startswith("_")}
            for p in self._load_known_persons(force=True)
        ]


def _load_config() -> Dict[str, Any]:
    path = BASE_DIR / "tapo_c310_config.json"
    return _load_json(path, {})


def main() -> int:
    parser = argparse.ArgumentParser(description="TARDIS Face Intel · Analítica biométrica facial local")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_analyze = sub.add_parser("analyze", help="Analizar una fotografía")
    p_analyze.add_argument("--photo", type=Path, required=True)
    p_analyze.add_argument("--dwell", type=float, default=0.0)

    p_enroll = sub.add_parser("enroll", help="Registrar una persona conocida")
    p_enroll.add_argument("--name", required=True)
    p_enroll.add_argument("--photo", type=Path, required=True)
    p_enroll.add_argument("--age", type=float, default=None)
    p_enroll.add_argument("--relation", default="")
    p_enroll.add_argument("--notes", default="")
    p_enroll.add_argument("--watch", action="store_true")

    sub.add_parser("list", help="Listar personas registradas")

    p_forget = sub.add_parser("forget", help="Eliminar una persona registrada")
    p_forget.add_argument("--person-id", required=True)

    args = parser.parse_args()
    engine = FaceIntelEngine(_load_config())

    if args.cmd == "analyze":
        img = cv2.imread(str(args.photo), cv2.IMREAD_COLOR)
        if img is None:
            print(json.dumps({"ok": False, "error": "fotografía ilegible"}))
            return 1
        h, w = img.shape[:2]
        person = PersonIntelInput(x1=0, y1=0, x2=w, y2=h, confidence=1.0, dwell_sec=args.dwell)
        records = engine.analyze(img, [person], save_crops=False)
        print(json.dumps({"ok": True, "records": records}, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "enroll":
        res = engine.enroll_person(
            name=args.name,
            photo_path=args.photo,
            age=args.age,
            relation=args.relation,
            watch=args.watch,
            notes=args.notes,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    if args.cmd == "list":
        print(json.dumps({"ok": True, "persons": engine.list_known_persons()}, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "forget":
        res = engine.forget_person(args.person_id)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
