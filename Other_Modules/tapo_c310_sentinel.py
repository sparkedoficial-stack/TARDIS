"""
core/tapo_c310_sentinel.py - Centinela Soberano de Detección Humana para TP-Link Tapo C310
==========================================================================================
GODWORKS SYSTEM v26.4 · Matriz de Vigilancia Perimetral TARDIS (GOD-EYE)

Conecta de forma nativa y cifrada (TLS JSON-RPC :443 + Tapo Encrypted MPEG-TS :8800) con la
cámara exterior TP-Link Tapo C310 (REDACTED_IP · alias GOD-EYE), decodifica el flujo 2K QHD
(2304x1296 H.264) en tiempo real sin retardo de búfer, ejecuta inferencia neuronal YOLOv8s
(ONNX Runtime) para detección precisa de individuos (día y visión nocturna IR), renderiza
telemetría HUD soberana sobre el fotograma 2K y despacha notificaciones instantáneas con
fotografía adjunta vía Telegram (@GODMODE69bot -> Arquitecto) y escritorio local (notify-send),
además de inyectar la señal en vivo hacia el Hub CCTV de TARDIS (:8757).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import WSMsgType, web
import cv2
import httpx
import numpy as np
import onnxruntime as ort
from pytapo import Tapo
from pytapo.media_stream.streamer import Streamer

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tapo_c310_speaker import DEFAULT_WARNING_MESSAGE, TapoC310Speaker

try:
    from core.tardis_face_intel import FaceIntelEngine, PersonIntelInput
except Exception as _face_intel_import_exc:  # pragma: no cover - degradación segura
    FaceIntelEngine = None  # type: ignore[assignment]
    PersonIntelInput = None  # type: ignore[assignment]
    _FACE_INTEL_IMPORT_ERROR = str(_face_intel_import_exc)
else:
    _FACE_INTEL_IMPORT_ERROR = ""

DEFAULT_CONFIG_PATH = BASE_DIR / "tapo_c310_config.json"
TELEGRAM_CONFIG_PATH = BASE_DIR / "telegram_config.json"
DETECTIONS_DIR = BASE_DIR / "data" / "tapo_c310_detections"
LIVE_CLIPS_DIR = DETECTIONS_DIR / "live_clips"
SENTINEL_HUB_HOST = os.environ.get("TARDIS_C310_HUB_HOST", "127.0.0.1")
SENTINEL_HUB_PORT = int(os.environ.get("TARDIS_C310_HUB_PORT", "8797"))
VOICE_CHANNEL_FLAG = BASE_DIR / "data" / "tapo_c310_voice_channel" / "session_active.json"
DEFAULT_DWELL_TRIGGER_SEC = 90.0
DEFAULT_VOICE_ALERT_MESSAGE = DEFAULT_WARNING_MESSAGE

logger = logging.getLogger("TARDIS.TapoC310Sentinel")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@dataclass
class PersonDetection:
    """Representa un individuo detectado en coordenadas nativas del fotograma (ej. 2304x1296)."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bbox": [self.x1, self.y1, self.x2, self.y2],
            "width": self.width,
            "height": self.height,
            "confidence": round(self.confidence, 4),
        }


class YoloV8PersonDetector:
    """Motor de inferencia ONNX Runtime sobre YOLOv8s para detección de individuos (COCO class 0)."""

    def __init__(
        self,
        model_path: Path,
        conf_threshold: float = 0.42,
        nms_iou_threshold: float = 0.45,
        min_box_w: int = 28,
        min_box_h: int = 36,
        intra_threads: int = 4,
    ) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Modelo ONNX no encontrado en: {model_path}")

        self.model_path = model_path
        self.conf_threshold = float(conf_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.min_box_w = int(min_box_w)
        self.min_box_h = int(min_box_h)

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = max(1, int(intra_threads))
        sess_opts.inter_op_num_threads = 1
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        available = ort.get_available_providers()
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in available
            else ["CPUExecutionProvider"]
        )
        self.session = ort.InferenceSession(
            str(model_path), sess_options=sess_opts, providers=providers
        )
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = 640

    def detect(self, bgr_image: np.ndarray) -> Tuple[List[PersonDetection], float]:
        """Ejecuta inferencia YOLOv8s y retorna (lista_de_individuos, latencia_ms)."""
        t0 = time.perf_counter()
        img_h, img_w = bgr_image.shape[:2]
        scale = min(self.input_size / img_w, self.input_size / img_h)
        new_w = int(round(img_w * scale))
        new_h = int(round(img_h * scale))

        resized = cv2.resize(bgr_image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        pad_w = (self.input_size - new_w) // 2
        pad_h = (self.input_size - new_h) // 2
        canvas[pad_h : pad_h + new_h, pad_w : pad_w + new_w] = resized

        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.transpose(rgb, (2, 0, 1))[None, ...]

        raw_out = self.session.run(None, {self.input_name: blob})[0]
        preds = np.squeeze(raw_out, axis=0).T  # [8400, 84]

        # Clase 0 en COCO = person (columna índice 4 tras cx, cy, w, h)
        person_scores = preds[:, 4]
        mask = person_scores >= self.conf_threshold
        if not np.any(mask):
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return [], dt_ms

        boxes_cxcywh = preds[mask, :4]
        scores = person_scores[mask]

        boxes_xywh: List[List[float]] = []
        valid_scores: List[float] = []
        for (cx, cy, bw, bh), sc in zip(boxes_cxcywh, scores):
            x1 = (cx - bw / 2.0 - pad_w) / scale
            y1 = (cy - bh / 2.0 - pad_h) / scale
            rw = bw / scale
            rh = bh / scale

            # Recortar a límites reales de la imagen
            cx1 = max(0.0, min(float(img_w - 1), x1))
            cy1 = max(0.0, min(float(img_h - 1), y1))
            cx2 = max(0.0, min(float(img_w), x1 + rw))
            cy2 = max(0.0, min(float(img_h), y1 + rh))
            cw = cx2 - cx1
            ch = cy2 - cy1

            if cw < self.min_box_w or ch < self.min_box_h:
                continue
            aspect = cw / max(1.0, ch)
            if aspect < 0.10 or aspect > 3.8:
                continue

            boxes_xywh.append([cx1, cy1, cw, ch])
            valid_scores.append(float(sc))

        if not boxes_xywh:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            return [], dt_ms

        indices = cv2.dnn.NMSBoxes(
            boxes_xywh, valid_scores, self.conf_threshold, self.nms_iou_threshold
        )
        detections: List[PersonDetection] = []
        if len(indices) > 0:
            for idx in np.array(indices).flatten():
                bx, by, bw, bh = boxes_xywh[int(idx)]
                detections.append(
                    PersonDetection(
                        x1=int(round(bx)),
                        y1=int(round(by)),
                        x2=int(round(bx + bw)),
                        y2=int(round(by + bh)),
                        confidence=float(valid_scores[int(idx)]),
                    )
                )
        detections.sort(key=lambda d: d.confidence, reverse=True)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return detections, dt_ms


def _fmt_dwell_seconds(seconds: Any) -> str:
    try:
        s = max(0, int(round(float(seconds))))
    except Exception:
        s = 0
    return f"{s // 60:02d}:{s % 60:02d}"


def render_tardis_hud(
    bgr_image: np.ndarray,
    detections: List[PersonDetection],
    camera_alias: str = "GOD-EYE",
    camera_ip: str = "REDACTED_IP",
    camera_model: str = "Tapo C310",
    timestamp_str: Optional[str] = None,
    orig_size: Optional[Tuple[int, int]] = None,
    live_badge: bool = False,
    person_intel: Optional[List[Dict[str, Any]]] = None,
    alert_kind: str = "",
) -> np.ndarray:
    """Dibuja retículas tácticas TARDIS y telemetría perimetral sobre una copia del fotograma."""
    annotated = bgr_image.copy()
    h, w = annotated.shape[:2]
    orig_w, orig_h = orig_size if orig_size else (w, h)
    sx = w / float(max(1, orig_w))
    sy = h / float(max(1, orig_h))
    ts_label = timestamp_str or time.strftime("%Y-%m-%d %H:%M:%S")

    # Panel táctico superior derecho (evita solapar el reloj OSD nativo de Tapo en la esquina superior izquierda)
    live_prefix = "LIVE | " if live_badge else ""
    kind_prefix = f"{alert_kind.upper()} | " if alert_kind else ""
    status_txt = (
        f"{live_prefix}{kind_prefix}TARDIS SENTINEL | {camera_alias} ({camera_model} @ {camera_ip}) "
        f"| INDIVIDUOS: {len(detections)} | {ts_label}"
    )
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.50, w / 2550.0)
    thickness = max(1, int(round(w / 1150.0)))
    (stw, sth), _ = cv2.getTextSize(status_txt, font, font_scale, thickness)

    bar_h = max(42, sth + 24)
    panel_x1 = max(0, w - stw - 48)
    overlay = annotated.copy()
    cv2.rectangle(overlay, (panel_x1, 0), (w, bar_h), (12, 16, 26), -1)
    cv2.addWeighted(overlay, 0.82, annotated, 0.18, 0, annotated)
    accent_color = (255, 225, 0) if not detections else (0, 180, 255)
    cv2.line(annotated, (panel_x1, bar_h), (w, bar_h), accent_color, 2)
    cv2.line(annotated, (panel_x1, 0), (panel_x1, bar_h), accent_color, 2)

    if live_badge:
        dot_r = max(5, int(round(bar_h * 0.16)))
        cv2.circle(
            annotated,
            (panel_x1 + 16, int(bar_h * 0.52)),
            dot_r,
            (40, 40, 255),
            -1,
            cv2.LINE_AA,
        )

    text_color = (0, 240, 255) if not detections else (80, 220, 255)
    cv2.putText(
        annotated,
        status_txt,
        (panel_x1 + (30 if live_badge else 24), int(bar_h * 0.68)),
        font,
        font_scale,
        text_color,
        thickness,
        cv2.LINE_AA,
    )

    # Retículas por individuo detectado
    for idx, det in enumerate(detections, start=1):
        dx1 = int(round(det.x1 * sx))
        dy1 = int(round(det.y1 * sy))
        dx2 = int(round(det.x2 * sx))
        dy2 = int(round(det.y2 * sy))
        dw = max(1, dx2 - dx1)
        dh = max(1, dy2 - dy1)

        box_color = (0, 210, 255)  # Ámbar-cian de alto contraste sobre IR y color
        corner_color = (0, 60, 255)  # Esquinas carmesí tácticas
        cv2.rectangle(annotated, (dx1, dy1), (dx2, dy2), box_color, max(2, thickness))

        # Esquinas reforzadas estilo HUD
        clen = max(12, min(dw, dh) // 5)
        for cx, cy, dir_x, dir_y in (
            (dx1, dy1, 1, 1),
            (dx2, dy1, -1, 1),
            (dx1, dy2, 1, -1),
            (dx2, dy2, -1, -1),
        ):
            cv2.line(annotated, (cx, cy), (cx + dir_x * clen, cy), corner_color, max(3, thickness + 2))
            cv2.line(annotated, (cx, cy), (cx, cy + dir_y * clen), corner_color, max(3, thickness + 2))

        intel: Dict[str, Any] = {}
        if person_intel and (idx - 1) < len(person_intel):
            intel = person_intel[idx - 1] or {}

        id_tag = ""
        if intel.get("identity_status") == "CONOCIDO" and intel.get("identity_name"):
            id_tag = str(intel["identity_name"])
        elif intel.get("person_id"):
            id_tag = str(intel["person_id"])

        label = f"INDIVIDUO #{idx}  {det.confidence * 100:.1f}%"
        if id_tag:
            label += f"  ·  {id_tag}"

        detail_lines: List[str] = []
        age_parts: List[str] = []
        if intel.get("age_estimate") is not None:
            age_txt = f"EDAD ~{float(intel['age_estimate']):.0f}a"
            if intel.get("age_range") and intel.get("age_range") != "registro":
                age_txt += f" ({intel['age_range']})"
            elif intel.get("age_range") == "registro":
                age_txt += " (REGISTRO)"
            age_parts.append(age_txt)
        if intel.get("height_m") is not None:
            age_parts.append(f"EST ~{float(intel['height_m']):.2f}m")
        if intel.get("distance_m") is not None:
            age_parts.append(f"DIST ~{float(intel['distance_m']):.1f}m")
        if age_parts:
            detail_lines.append(" · ".join(age_parts))

        state_parts: List[str] = []
        if intel.get("emotion"):
            state_parts.append(
                f"EMOCIÓN {str(intel['emotion']).upper()} "
                f"{float(intel.get('emotion_confidence', 0.0)) * 100:.0f}%"
            )
        state_parts.append(
            f"PERMANENCIA {_fmt_dwell_seconds(intel.get('dwell_sec', 0.0))}"
        )
        detail_lines.append(" · ".join(state_parts))

        if intel.get("identity_status") == "NO_REGISTRADO":
            detail_lines.append("IDENTIDAD NO REGISTRADA · EXPEDIENTE BIOMÉTRICO")
        elif intel.get("identity_status") == "CONOCIDO":
            detail_lines.append(
                f"COINCIDENCIA LOCAL {float(intel.get('identity_similarity', 0.0)):.2f} "
                f"· {intel.get('person_id', '')}"
            )

        detail_fs = font_scale * 0.72
        detail_th = max(1, thickness)
        all_lines = [label] + detail_lines
        text_sizes = [cv2.getTextSize(t, font, detail_fs, detail_th)[0] for t in all_lines]
        panel_w = max(tw for tw, _ in text_sizes) + 26
        line_h = max(18, int(round(cv2.getTextSize("Ag", font, detail_fs, detail_th)[0][1] * 1.55)))
        panel_h = line_h * len(all_lines) + 14
        panel_w = min(max(120, panel_w), max(140, w - 8))
        panel_x = max(2, min(dx1, w - panel_w - 2))
        panel_y = dy1 - panel_h - 6
        if panel_y < bar_h + 4:
            panel_y = min(h - panel_h - 4, dy1 + 6)
        panel_y = max(bar_h + 4, panel_y)

        overlay_panel = annotated.copy()
        cv2.rectangle(
            overlay_panel,
            (panel_x, panel_y),
            (panel_x + panel_w, panel_y + panel_h),
            (8, 14, 24),
            -1,
        )
        cv2.addWeighted(overlay_panel, 0.86, annotated, 0.14, 0, annotated)
        accent = (0, 230, 160) if intel.get("identity_status") == "CONOCIDO" else box_color
        cv2.rectangle(
            annotated,
            (panel_x, panel_y),
            (panel_x + panel_w, panel_y + panel_h),
            accent,
            max(1, detail_th),
        )
        cv2.line(
            annotated,
            (panel_x, panel_y),
            (panel_x, panel_y + panel_h),
            accent,
            max(3, detail_th + 2),
        )
        for line_idx, line_txt in enumerate(all_lines):
            color = (255, 255, 255) if line_idx == 0 else (215, 235, 245)
            if line_idx == len(all_lines) - 1 and intel.get("identity_status") == "NO_REGISTRADO":
                color = (80, 190, 255)
            cv2.putText(
                annotated,
                line_txt,
                (panel_x + 14, panel_y + 14 + line_h * line_idx + int(line_h * 0.62)),
                font,
                detail_fs,
                color,
                detail_th,
                cv2.LINE_AA,
            )

        # Caja del rostro detectado por el motor biométrico
        face_bbox = intel.get("face_bbox")
        if face_bbox and len(face_bbox) == 4:
            fx1 = int(round(int(face_bbox[0]) * sx))
            fy1 = int(round(int(face_bbox[1]) * sy))
            fx2 = int(round(int(face_bbox[2]) * sx))
            fy2 = int(round(int(face_bbox[3]) * sy))
            face_color = (0, 255, 140) if intel.get("identity_status") == "CONOCIDO" else (0, 200, 255)
            cv2.rectangle(
                annotated,
                (fx1, fy1),
                (fx2, fy2),
                face_color,
                max(1, detail_th),
                cv2.LINE_AA,
            )
            cv2.putText(
                annotated,
                "FACE",
                (fx1, max(bar_h + 12, fy1 - 6)),
                font,
                detail_fs * 0.78,
                face_color,
                max(1, detail_th - 1),
                cv2.LINE_AA,
            )

    return annotated


@dataclass
class _TrackedVisitor:
    track_id: int
    bbox: Tuple[int, int, int, int]
    embedding: np.ndarray
    first_seen_ts: float
    last_seen_ts: float
    announced: bool = False
    voice_warned: bool = False
    face_identity: str = ""
    face_person_id: str = ""


@dataclass
class _ArchivedVisitor:
    visitor_id: int
    embedding: np.ndarray
    last_announced_ts: float


class VisualPersonReIDTracker:
    """
    Rastreador ligero de identidad visual y trayectoria espacial para determinar cuándo ingresa
    un individuo NUEVO a la escena (día color o infrarrojo nocturno), evitando repetir el aviso
    vocal mientras la misma persona permanece frente a la cámara, pero disparando de inmediato
    cuando entra alguien distinto o una persona adicional.
    """

    def __init__(
        self,
        clear_timeout_sec: float = 8.0,
        same_person_cooldown_sec: float = 25.0,
        similarity_threshold: float = 0.80,
    ) -> None:
        self.clear_timeout_sec = float(clear_timeout_sec)
        self.same_person_cooldown_sec = float(same_person_cooldown_sec)
        self.similarity_threshold = float(similarity_threshold)
        self._next_id: int = 1
        self.active_tracks: List[_TrackedVisitor] = []
        self.recent_visitors: List[_ArchivedVisitor] = []
        self.total_new_visitors: int = 0

    @staticmethod
    def compute_embedding(bgr_frame: np.ndarray, det: PersonDetection) -> np.ndarray:
        h, w = bgr_frame.shape[:2]
        x1 = max(0, min(w - 2, det.x1))
        y1 = max(0, min(h - 2, det.y1))
        x2 = max(x1 + 2, min(w, det.x2))
        y2 = max(y1 + 2, min(h, det.y2))

        crop = bgr_frame[y1:y2, x1:x2]
        ch, cw = crop.shape[:2]
        if cw >= 12:
            pad_x = int(cw * 0.14)
            crop = crop[:, pad_x : max(pad_x + 4, cw - pad_x)]

        resized = cv2.resize(crop, (48, 96), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(resized, cv2.COLOR_BGR2LAB)

        parts: List[np.ndarray] = []
        for r0, r1 in ((10, 52), (52, 90)):
            h_band = hsv[r0:r1, :]
            l_band = lab[r0:r1, :]
            hist_h = cv2.calcHist([h_band], [0], None, [16], [0, 180]).flatten()
            hist_s = cv2.calcHist([h_band], [1], None, [8], [0, 256]).flatten()
            hist_v = cv2.calcHist([h_band], [2], None, [8], [0, 256]).flatten()
            hist_a = cv2.calcHist([l_band], [1], None, [4], [0, 256]).flatten()
            hist_b = cv2.calcHist([l_band], [2], None, [4], [0, 256]).flatten()
            for hist in (hist_h, hist_s, hist_v, hist_a, hist_b):
                s = float(hist.sum())
                if s > 0:
                    hist /= s
                parts.append(hist)

        vec = np.concatenate(parts).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 1e-6:
            vec /= norm
        return vec

    @staticmethod
    def _spatial_score(
        b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int], frame_diag: float
    ) -> float:
        ix1 = max(b1[0], b2[0])
        iy1 = max(b1[1], b2[1])
        ix2 = min(b1[2], b2[2])
        iy2 = min(b1[3], b2[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        a1 = max(1, (b1[2] - b1[0]) * (b1[3] - b1[1]))
        a2 = max(1, (b2[2] - b2[0]) * (b2[3] - b2[1]))
        iou = inter / float(a1 + a2 - inter)

        c1x, c1y = 0.5 * (b1[0] + b1[2]), 0.5 * (b1[1] + b1[3])
        c2x, c2y = 0.5 * (b2[0] + b2[2]), 0.5 * (b2[1] + b2[3])
        dist = float(np.hypot(c1x - c2x, c1y - c2y)) / max(1.0, frame_diag)
        prox = max(0.0, 1.0 - dist * 3.2)
        return max(iou, prox)

    def _expire_tracks(self, now: float) -> None:
        kept: List[_TrackedVisitor] = []
        for tr in self.active_tracks:
            if (now - tr.last_seen_ts) <= self.clear_timeout_sec:
                kept.append(tr)
            elif tr.announced:
                self.recent_visitors.append(
                    _ArchivedVisitor(
                        visitor_id=tr.track_id,
                        embedding=tr.embedding.copy(),
                        last_announced_ts=tr.last_seen_ts,
                    )
                )
        self.active_tracks = kept
        # Purgar memoria histórica expirada
        cutoff = now - max(self.same_person_cooldown_sec * 2.0, 120.0)
        self.recent_visitors = [
            rv for rv in self.recent_visitors if rv.last_announced_ts >= cutoff
        ]

    def describe_person(
        self,
        bbox: Tuple[int, int, int, int],
        now: float,
        frame_diag: float,
    ) -> Dict[str, Any]:
        """Devuelve track_id, permanencia continua y estado vocal para una caja YOLO."""
        best: Optional[_TrackedVisitor] = None
        best_score = -1.0
        for tr in self.active_tracks:
            score = self._spatial_score(bbox, tr.bbox, frame_diag)
            if score > best_score:
                best_score = score
                best = tr
        if best is None or best_score < 0.12:
            return {"track_id": None, "dwell_sec": 0.0, "voice_warned": False}
        return {
            "track_id": best.track_id,
            "dwell_sec": max(0.0, now - best.first_seen_ts),
            "voice_warned": bool(best.voice_warned),
            "first_seen_ts": best.first_seen_ts,
        }

    def claim_dwell_voice_targets(self, now: float, dwell_trigger_sec: float) -> List[int]:
        """
        Retorna los track_id que acaban de cumplir la permanencia mínima frente a la cámara
        y aún no han recibido el aviso vocal. Marca la reclamación para evitar duplicados.
        """
        due: List[int] = []
        threshold = max(1.0, float(dwell_trigger_sec))
        for tr in self.active_tracks:
            if tr.voice_warned:
                continue
            # Solo personas presentes en el último segundo (presencia continua efectiva)
            if (now - tr.last_seen_ts) > 1.25:
                continue
            if (now - tr.first_seen_ts) >= threshold:
                tr.voice_warned = True
                due.append(tr.track_id)
        return due

    def unmark_voice_warned(self, track_ids: List[int]) -> None:
        """Permite reintentar el aviso si la emisión por el altavoz falló."""
        wanted = set(int(t) for t in track_ids)
        for tr in self.active_tracks:
            if tr.track_id in wanted:
                tr.voice_warned = False

    def dwell_targets_active(self, now: float, dwell_trigger_sec: float) -> List[int]:
        """Personas que ya superaron el umbral y siguen presentes (para estado/HUD)."""
        ids: List[int] = []
        for tr in self.active_tracks:
            if (now - tr.last_seen_ts) <= 1.25 and (now - tr.first_seen_ts) >= dwell_trigger_sec:
                ids.append(tr.track_id)
        return ids

    def update_and_check_new(
        self,
        bgr_frame: np.ndarray,
        detections: List[PersonDetection],
        now: float,
        confirmed: bool,
    ) -> List[int]:
        """
        Actualiza tracks activos y, si `confirmed=True`, retorna la lista de IDs de individuos
        NUEVOS recién detectados que aún no han recibido el aviso vocal de TARDIS.
        """
        self._expire_tracks(now)
        if not detections:
            return []

        h, w = bgr_frame.shape[:2]
        diag = float(np.hypot(w, h))
        det_boxes = [(d.x1, d.y1, d.x2, d.y2) for d in detections]
        det_embs = [self.compute_embedding(bgr_frame, d) for d in detections]

        # Emparejamiento voraz entre detecciones actuales y tracks activos
        unmatched_dets = set(range(len(detections)))
        unmatched_tracks = set(range(len(self.active_tracks)))
        pairs: List[Tuple[float, int, int]] = []
        for di in unmatched_dets:
            for ti in unmatched_tracks:
                tr = self.active_tracks[ti]
                sp = self._spatial_score(det_boxes[di], tr.bbox, diag)
                sim = float(np.dot(det_embs[di], tr.embedding))
                if sp < 0.12 and sim < 0.72:
                    continue
                score = 0.58 * sp + 0.42 * max(0.0, sim)
                if score >= 0.36:
                    pairs.append((score, di, ti))

        pairs.sort(key=lambda x: x[0], reverse=True)
        for _, di, ti in pairs:
            if di in unmatched_dets and ti in unmatched_tracks:
                unmatched_dets.remove(di)
                unmatched_tracks.remove(ti)
                tr = self.active_tracks[ti]
                tr.bbox = det_boxes[di]
                merged = 0.75 * tr.embedding + 0.25 * det_embs[di]
                nrm = float(np.linalg.norm(merged))
                tr.embedding = merged / nrm if nrm > 1e-6 else det_embs[di]
                tr.last_seen_ts = now

        for di in sorted(unmatched_dets):
            tid = self._next_id
            self._next_id += 1
            self.active_tracks.append(
                _TrackedVisitor(
                    track_id=tid,
                    bbox=det_boxes[di],
                    embedding=det_embs[di],
                    first_seen_ts=now,
                    last_seen_ts=now,
                    announced=False,
                )
            )

        if not confirmed:
            return []

        new_visitor_ids: List[int] = []
        for tr in self.active_tracks:
            if tr.announced or (now - tr.last_seen_ts) > 1.0:
                continue

            # Verificar si corresponde exactamente a la misma persona que salió hace pocos segundos
            is_recent_same = False
            for idx_rv, rv in enumerate(self.recent_visitors):
                if (now - rv.last_announced_ts) < self.same_person_cooldown_sec:
                    sim = float(np.dot(tr.embedding, rv.embedding))
                    if sim >= self.similarity_threshold:
                        is_recent_same = True
                        # Consumir esa entrada para que una 2da persona con ropa parecida sí dispare
                        self.recent_visitors.pop(idx_rv)
                        break

            tr.announced = True
            if not is_recent_same:
                self.total_new_visitors += 1
                new_visitor_ids.append(tr.track_id)

        return new_visitor_ids


class TapoC310Sentinel:
    """Demonio autónomo de vigilancia y notificación instantánea para cámara Tapo C310."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = config_path
        self.config = self._load_json(config_path)
        self.tg_config = self._load_json(TELEGRAM_CONFIG_PATH)
        DETECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        LIVE_CLIPS_DIR.mkdir(parents=True, exist_ok=True)

        model_rel = self.config.get("yolo_model_path", "models/yolov8s.onnx")
        model_path = Path(model_rel) if Path(model_rel).is_absolute() else (BASE_DIR / model_rel)

        self.detector = YoloV8PersonDetector(
            model_path=model_path,
            conf_threshold=float(self.config.get("confidence_threshold", 0.42)),
            nms_iou_threshold=float(self.config.get("nms_iou_threshold", 0.45)),
            min_box_w=int(self.config.get("min_box_width_px", 28)),
            min_box_h=int(self.config.get("min_box_height_px", 36)),
        )

        self.host: str = str(self.config.get("host", "REDACTED_IP")).strip()
        self.device_alias: str = str(self.config.get("device_alias", "GOD-EYE"))
        self.device_model: str = str(self.config.get("device_model", "C310"))
        self.mac_address: str = str(self.config.get("mac_address", "48:22:54:3E:A0:CE"))
        self.tapo_user: str = str(self.config.get("tapo_user", "admin"))
        self.account_email: str = str(self.config.get("account_email", ""))
        self.password: str = str(self.config.get("password", ""))

        self.speaker = TapoC310Speaker(config_path=config_path)
        self.reid_tracker = VisualPersonReIDTracker(
            clear_timeout_sec=float(self.config.get("clear_reset_sec", 8.0)),
            same_person_cooldown_sec=float(
                self.config.get("reid_same_person_cooldown_sec", 25.0)
            ),
            similarity_threshold=float(self.config.get("reid_similarity_threshold", 0.80)),
        )
        # Directiva Arquitecto: el aviso vocal SOLO dispara cuando la persona permanece
        # más de DWELL_TRIGGER_SEC (1.5 min) frente a la cámara.
        self.dwell_trigger_sec: float = float(
            self.config.get("dwell_trigger_sec", DEFAULT_DWELL_TRIGGER_SEC)
        )
        self._face_intel_engine: Optional[Any] = None

        self._stop_event = asyncio.Event()
        self._latest_jpeg: Optional[bytes] = None
        self._latest_frame_ts: float = 0.0
        self._frame_seq: int = 0
        self._new_frame_event = asyncio.Event()
        self._frame_history: deque[Tuple[float, bytes]] = deque(maxlen=90)
        self._latest_bgr_shape: Tuple[int, int] = (1296, 2304)
        self._latest_detections: List[PersonDetection] = []
        self._latest_inference_ms: float = 0.0
        self._consecutive_zero_frame_connects: int = 0
        self._hub_runner: Optional[web.AppRunner] = None
        self._clip_lock = asyncio.Lock()

        # Métricas y estado persistente
        self.device_hw_info: Dict[str, Any] = {}
        self.total_frames_decoded: int = 0
        self.total_frames_analyzed: int = 0
        self.total_alerts_sent: int = 0
        self.total_voice_warnings_spoken: int = 0
        self.last_voice_warning_ts: float = 0.0
        self.last_spoken_message: str = ""
        self._voice_task: Optional[asyncio.Task] = None
        self.last_alert_ts: float = 0.0
        self.last_alert_person_count: int = 0
        self.last_person_seen_ts: float = 0.0
        self.presence_latched: bool = False
        self.consecutive_positive: int = 0
        self.stream_connected: bool = False
        self.started_at: float = time.time()

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"No se pudo leer JSON {path}: {e}")
            return {}

    def _connect_tapo_sync(self) -> Tapo:
        """Autentica contra la API local :443 de Tapo (debe ejecutarse en hilo fuera del loop asyncio)."""
        candidates = []
        if self.tapo_user:
            candidates.append(self.tapo_user)
        if self.account_email and self.account_email not in candidates:
            candidates.append(self.account_email)
        if "admin" not in candidates:
            candidates.append("admin")

        last_err: Optional[Exception] = None
        for user in candidates:
            try:
                tapo = Tapo(self.host, user, self.password, cloudPassword=self.password)
                info = tapo.getBasicInfo()
                basic = info.get("device_info", {}).get("basic_info", {})
                self.device_hw_info = basic
                if basic.get("device_alias"):
                    self.device_alias = str(basic["device_alias"])
                if basic.get("device_model"):
                    self.device_model = str(basic["device_model"])
                if basic.get("mac"):
                    self.mac_address = str(basic["mac"]).replace("-", ":")

                # Asegurar que la detección IA de personas en hardware esté habilitada
                try:
                    pdet = tapo.getPersonDetection()
                    if str(pdet.get("enabled", "")).lower() != "on":
                        tapo.setPersonDetection(True)
                        logger.info("Detección de personas nativa en hardware Tapo activada.")
                except Exception as pe:
                    logger.debug(f"Consulta/ajuste de PersonDetection en hardware omitida: {pe}")

                # Pre-inicializar método de cifrado para sesiones :8800
                tapo.getEncryptionMethod()
                return tapo
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"Fallo autenticando contra Tapo {self.host}: {last_err}")

    def _atomic_write_bytes(self, dest: Path, data: bytes) -> None:
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    def _atomic_write_json(self, dest: Path, payload: Dict[str, Any]) -> None:
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, dest)

    def _prune_old_snapshots(self) -> None:
        max_keep = max(20, int(self.config.get("max_saved_snapshots", 250)))
        try:
            files = sorted(
                [
                    p
                    for p in DETECTIONS_DIR.glob("*.jpg")
                    if p.name not in ("latest_frame.jpg", "latest_detection.jpg")
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[max_keep:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def _update_state_file(
        self,
        last_detections: Optional[List[PersonDetection]] = None,
        last_latency_ms: float = 0.0,
        last_error: Optional[str] = None,
    ) -> None:
        state = {
            "ok": self.stream_connected,
            "service": "tardis-tapo-c310-sentinel",
            "updated_at": time.time(),
            "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "uptime_sec": round(time.time() - self.started_at, 1),
            "camera": {
                "host": self.host,
                "alias": self.device_alias,
                "model": self.device_model,
                "mac": self.mac_address,
                "firmware": self.device_hw_info.get("sw_version", ""),
                "hw_version": self.device_hw_info.get("hw_version", ""),
                "dev_id": self.device_hw_info.get("dev_id", ""),
            },
            "metrics": {
                "stream_connected": self.stream_connected,
                "total_frames_decoded": self.total_frames_decoded,
                "total_frames_analyzed": self.total_frames_analyzed,
                "total_alerts_sent": self.total_alerts_sent,
                "total_voice_warnings_spoken": self.total_voice_warnings_spoken,
                "total_new_visitors_detected": self.reid_tracker.total_new_visitors,
                "last_voice_warning_ts": self.last_voice_warning_ts,
                "last_spoken_message": self.last_spoken_message,
                "last_inference_ms": round(last_latency_ms, 2),
                "last_alert_ts": self.last_alert_ts,
                "presence_latched": self.presence_latched,
                "current_persons": len(last_detections) if last_detections else 0,
            },
            "latest_frame_path": str(DETECTIONS_DIR / "latest_frame.jpg"),
            "latest_detection_path": str(DETECTIONS_DIR / "latest_detection.jpg"),
            "last_error": last_error,
        }
        try:
            self._atomic_write_json(DETECTIONS_DIR / "sentinel_state.json", state)
        except Exception as e:
            logger.debug(f"No se pudo escribir sentinel_state.json: {e}")

    def _send_desktop_notification(self, title: str, body: str, image_path: Path) -> None:
        if not self.config.get("desktop_notify_enabled", True):
            return
        try:
            env = os.environ.copy()
            uid = os.getuid()
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
            subprocess.Popen(
                [
                    "notify-send",
                    "-u",
                    "critical",
                    "-a",
                    "TARDIS GOD-EYE",
                    "-i",
                    str(image_path),
                    title,
                    body,
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            logger.debug(f"Notificación de escritorio omitida: {e}")

    async def _send_telegram_photo(
        self, client: httpx.AsyncClient, jpeg_bytes: bytes, caption: str
    ) -> Dict[str, Any]:
        if not self.config.get("telegram_notify_enabled", True):
            return {"ok": False, "skipped": True}

        # Recargar telegram_config.json por si cambió token/chat_id en caliente
        tg_cfg = self._load_json(TELEGRAM_CONFIG_PATH) or self.tg_config
        token = str(tg_cfg.get("bot_token", "")).strip()
        chat_id = tg_cfg.get("admin_chat_id")
        if not chat_id and tg_cfg.get("allowed_chats"):
            chat_id = tg_cfg["allowed_chats"][0]

        if not token or not chat_id:
            return {"ok": False, "error": "Credenciales de Telegram no configuradas"}

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        for attempt in range(1, 4):
            try:
                files = {"photo": (f"godeye_c310_{int(time.time())}.jpg", jpeg_bytes, "image/jpeg")}
                data = {
                    "chat_id": str(chat_id),
                    "caption": caption,
                    "parse_mode": "Markdown",
                }
                resp = await client.post(url, data=data, files=files, timeout=25.0)
                res_json = resp.json()
                if res_json.get("ok"):
                    return res_json
                # Fallback sin Markdown si falla el parseo
                data.pop("parse_mode", None)
                resp_fb = await client.post(url, data=data, files=files, timeout=25.0)
                return resp_fb.json()
            except Exception as exc:
                logger.warning(f"Intento {attempt}/3 fallido enviando foto a Telegram: {exc}")
                await asyncio.sleep(1.5 * attempt)
        return {"ok": False, "error": "Agotados reintentos hacia Telegram API"}

    async def _push_cctv_hub_frame(
        self,
        client: httpx.AsyncClient,
        bgr_frame: np.ndarray,
        detections: List[PersonDetection],
    ) -> None:
        if not self.config.get("cctv_hub_feed_enabled", True):
            return
        url = str(
            self.config.get("cctv_hub_url", "http://127.0.0.1:8757/api/terminal_cameras/feed")
        )
        term_id = str(self.config.get("cctv_hub_terminal_id", "tapo_c310_god_eye"))
        try:
            preview = cv2.resize(bgr_frame, (1280, 720), interpolation=cv2.INTER_AREA)
            ok, enc = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                return
            b64_str = "data:image/jpeg;base64," + base64.b64encode(enc.tobytes()).decode("ascii")
            payload = {
                "terminal_id": term_id,
                "terminal_name": f"{self.device_alias} · Tapo {self.device_model} ({self.host})",
                "device_type": "ip_camera_tapo_c310",
                "image_base64": b64_str,
                "client_ip": self.host,
                "country": "LAN",
                "user_agent": f"TP-Link Tapo {self.device_model} ({self.mac_address})",
                "resolution": "2304x1296 -> 1280x720",
                "bitrate_kbps": 2048.0,
                "biometrics": {
                    "persons_detected": len(detections),
                    "max_confidence": round(detections[0].confidence, 3) if detections else 0.0,
                    "mood_state": "ALERTA HUMANA" if detections else "Perímetro Despejado",
                },
            }
            await client.post(url, json=payload, timeout=3.0)
        except Exception:
            pass

    def _voice_channel_is_active(self) -> bool:
        """True si el canal de voz TARDIS está en conversación activa con el Arquitecto."""
        try:
            data = self._load_json(VOICE_CHANNEL_FLAG)
            active_until = float(data.get("active_until", 0) or 0)
            return active_until > time.time()
        except Exception:
            return False

    def _get_face_intel_engine(self) -> Optional[Any]:
        """Devuelve el motor biométrico facial GOD-EYE (si está habilitado y disponible)."""
        if not bool(self.config.get("face_intel_enabled", True)):
            return None
        if FaceIntelEngine is None:
            return None
        if self._face_intel_engine is None:
            self._face_intel_engine = FaceIntelEngine(self.config)
        return self._face_intel_engine

    def _build_vigilance_alert_text(self) -> str:
        """Retorna el texto canónico del aviso vocal de vigilancia TARDIS."""
        text = str(self.config.get("new_person_voice_message", "") or "").strip()
        return text or str(DEFAULT_VOICE_ALERT_MESSAGE)

    def _build_person_intel_records(
        self, bgr_frame: np.ndarray, detections: List[PersonDetection], now: float
    ) -> List[Dict[str, Any]]:
        """
        Investigación biométrica facial GOD-EYE sobre el fotograma del alerta perimetral:
        captura el rostro, lo alinea, lo identifica contra el registro consentido del Arquitecto,
        estima edad física, estatura/distancia y estado emocional.
        """
        if FaceIntelEngine is None or PersonIntelInput is None:
            logger.warning(f"Motor GOD-EYE (FaceIntel) no disponible: {_FACE_INTEL_IMPORT_ERROR}")
            return []
        engine = self._get_face_intel_engine()
        if engine is None or not bool(getattr(engine, "enabled", True)):
            return []
        frame_diag = float(np.hypot(bgr_frame.shape[1], bgr_frame.shape[0]))
        persons: List[Any] = []
        for det in detections:
            info = self.reid_tracker.describe_person(
                (det.x1, det.y1, det.x2, det.y2), now, frame_diag
            )
            persons.append(
                PersonIntelInput(
                    x1=det.x1,
                    y1=det.y1,
                    x2=det.x2,
                    y2=det.y2,
                    confidence=float(det.confidence),
                    track_id=info.get("track_id") if info.get("track_id") is not None else None,
                    dwell_sec=float(info.get("dwell_sec") or 0.0),
                )
            )
        try:
            return engine.analyze(
                bgr_frame,
                persons,
                timestamp=now,
                save_crops=bool(self.config.get("face_intel_save_crops", True)),
            )
        except Exception as exc:
            logger.warning(f"Fallo la investigación biométrica facial GOD-EYE: {exc}")
            return []

    async def _announce_new_person_voice(
        self, new_visitor_ids: List[int], custom_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """Emite el aviso vocal de vigilancia TARDIS por la bocina física de la cámara."""
        if not self.config.get("speaker_enabled", True):
            return {"ok": False, "skipped": True}
        if self._voice_channel_is_active():
            logger.info(
                "[VOZ] Aviso disuasorio omitido: el Arquitecto está conversando por el canal de voz TARDIS."
            )
            return {"ok": False, "skipped": True, "reason": "voice_channel_active"}
        try:
            res = await self.speaker.speak(text=custom_text)
            if res.get("ok"):
                self.total_voice_warnings_spoken += 1
                self.last_voice_warning_ts = time.time()
                self.last_spoken_message = str(res.get("text", ""))
                logger.info(
                    f"[VOZ DISUASORIA C310] Visitante(s) nuevo(s) {new_visitor_ids} advertido(s) "
                    f"por altavoz ({res.get('audio_duration_sec')}s)."
                )
            else:
                logger.warning(f"No se pudo emitir aviso vocal en {self.host}: {res}")
            return res
        except Exception as exc:
            logger.warning(f"Excepción emitiendo voz en {self.host}: {exc}")
            return {"ok": False, "error": str(exc)}

    async def _dispatch_person_alert(
        self,
        client: httpx.AsyncClient,
        raw_jpeg: bytes,
        bgr_frame: np.ndarray,
        detections: List[PersonDetection],
        inference_ms: float,
        is_test: bool = False,
        new_visitor_ids: Optional[List[int]] = None,
        voice_dispatched: bool = False,
    ) -> Dict[str, Any]:
        now = time.time()
        ts_file = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
        ts_human = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        loop = asyncio.get_running_loop()

        # Investigación biométrica facial GOD-EYE sobre el fotograma del alerta perimetral:
        # captura el rostro, lo alinea, lo identifica, estima edad física, estatura y emoción.
        person_intel: List[Dict[str, Any]] = []
        dossier: Optional[Dict[str, Any]] = None
        if detections:
            person_intel = await loop.run_in_executor(
                None, self._build_person_intel_records, bgr_frame, detections, now
            )
            if person_intel:
                face_engine = self._get_face_intel_engine()
                if face_engine is not None:
                    try:
                        dossier = face_engine.build_dossier(
                            person_intel,
                            camera_alias=self.device_alias,
                            camera_host=self.host,
                            alert_kind="PERIMETRAL",
                            timestamp=now,
                            extra={
                                "alert_kind": "PERIMETRAL",
                                "voice_alert_text": self._build_vigilance_alert_text(),
                                "dwell_trigger_sec": self.dwell_trigger_sec,
                            },
                        )
                    except Exception as exc_dossier:
                        logger.warning(f"No se pudo generar el expediente biométrico GOD-EYE: {exc_dossier}")

        annotated_bgr = render_tardis_hud(
            bgr_frame,
            detections,
            camera_alias=self.device_alias,
            camera_ip=self.host,
            camera_model=f"Tapo {self.device_model}",
            timestamp_str=ts_human,
            person_intel=person_intel,
            alert_kind="PERIMETRAL",
        )
        ok, enc_buf = cv2.imencode(".jpg", annotated_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        annotated_jpeg = enc_buf.tobytes() if ok else raw_jpeg

        raw_path = DETECTIONS_DIR / f"raw_{ts_file}_{int((now % 1) * 1000):03d}.jpg"
        alert_path = DETECTIONS_DIR / f"alert_{ts_file}_{int((now % 1) * 1000):03d}.jpg"
        self._atomic_write_bytes(raw_path, raw_jpeg)
        self._atomic_write_bytes(alert_path, annotated_jpeg)
        self._atomic_write_bytes(DETECTIONS_DIR / "latest_detection.jpg", annotated_jpeg)
        self._prune_old_snapshots()

        h, w = bgr_frame.shape[:2]
        max_conf = max((d.confidence for d in detections), default=0.0) * 100.0

        if is_test:
            header = "🛰️ *[CENTINELA TARDIS ACTIVO · ENLACE ÓPTICO VERIFICADO]*"
            desk_title = f"TARDIS {self.device_alias} ({self.host}) En Línea"
            desk_body = (
                f"Vigilancia 24/7 activa ({w}x{h}). Individuos en escena ahora: {len(detections)}."
            )
        else:
            header = "🚨 *[ALERTA PERIMETRAL TARDIS · INDIVIDUO DETECTADO]*"
            desk_title = f"🚨 INDIVIDUO DETECTADO · {self.device_alias}"
            desk_body = (
                f"Cámara Tapo {self.device_model} ({self.host}) detectó {len(detections)} "
                f"individuo(s) (Confianza: {max_conf:.1f}%) a las {ts_human}."
            )

        lines = [
            header,
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• *Cámara:* `{self.device_alias} (TP-Link Tapo {self.device_model})`",
            f"• *IP / MAC:* `{self.host}` (`{self.mac_address}`)",
            f"• *Individuos detectados:* `{len(detections)}`"
            + (f" (Confianza máx: `{max_conf:.1f}%`)" if detections else " (`Perímetro despejado`)"),
            f"• *Resolución / Motor:* `{w}×{h} (2K QHD)` · `YOLOv8s ({inference_ms:.1f} ms)`",
        ]
        if new_visitor_ids:
            ids_lbl = ", ".join(f"#{vid}" for vid in new_visitor_ids)
            lines.append(f"• *Identidad visual:* `Individuo nuevo ({ids_lbl})`")
        if voice_dispatched:
            lines.append(
                f"• *Bocina C310:* `🔊 Aviso vocal TARDIS emitido ({self.speaker.voice})`"
            )
        if person_intel:
            for intel in person_intel:
                emotion = str(intel.get("emotion") or "N/D")
                lines.append(
                    f"• *GOD-EYE · Biometría Facial:* `{intel.get('identity_status') or 'NO_REGISTRADO'}` · "
                    f"{intel.get('identity_name') or intel.get('person_id') or 'SIN NOMBRE'} · "
                    f"EDAD ~{float(intel.get('age_estimate') or 0):.0f} · "
                    f"EST ~{float(intel.get('height_m') or 0):.2f}m · "
                    f"EMOCIÓN {emotion.upper()} · PERMANENCIA {_fmt_dwell_seconds(intel.get('dwell_sec', 0.0))}"
                )
        lines.append(f"• *Hora local:* `{ts_human}`")
        caption = "\n".join(lines)

        self._send_desktop_notification(desk_title, desk_body, alert_path)
        tg_res = await self._send_telegram_photo(client, annotated_jpeg, caption)

        if not is_test:
            self.total_alerts_sent += 1
            self.last_alert_ts = now
            self.last_alert_person_count = len(detections)

        event_record = {
            "timestamp": now,
            "iso_time": ts_human,
            "is_test": is_test,
            "camera_host": self.host,
            "camera_alias": self.device_alias,
            "person_count": len(detections),
            "new_visitor_ids": new_visitor_ids or [],
            "voice_warning_dispatched": voice_dispatched,
            "max_confidence": round(max_conf / 100.0, 4),
            "detections": [d.to_dict() for d in detections],
            "inference_ms": round(inference_ms, 2),
            "annotated_photo": str(alert_path),
            "raw_photo": str(raw_path),
            "telegram_ok": bool(tg_res.get("ok")),
            "face_intel_subjects": len(person_intel),
            "dossier": dossier,
        }
        try:
            with open(DETECTIONS_DIR / "events_ledger.jsonl", "a", encoding="utf-8") as lf:
                lf.write(json.dumps(event_record, ensure_ascii=False) + "\n")
        except Exception:
            pass

        logger.info(
            f"{'[TEST]' if is_test else '[ALERTA]'} Individuos={len(detections)} "
            f"ConfMax={max_conf:.1f}% TelegramOK={tg_res.get('ok')} Archivo={alert_path.name}"
        )
        return event_record

    async def _mjpeg_stdout_reader(self, proc: asyncio.subprocess.Process) -> None:
        """Drena continuamente proc.stdout extrayendo siempre el último JPEG 2K completo (cero lag)."""
        buf = bytearray()
        assert proc.stdout is not None
        while not self._stop_event.is_set():
            chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=18.0)
            if not chunk:
                raise EOFError("El proceso ffmpeg cerró stdout.")
            buf.extend(chunk)
            if len(buf) > 8 * 1024 * 1024:
                # Salvaguarda de memoria ante corrupción de marcadores
                del buf[:-524288]

            while True:
                soi = buf.find(b"\xff\xd8")
                if soi == -1:
                    buf.clear()
                    break
                if soi > 0:
                    del buf[:soi]
                eoi = buf.find(b"\xff\xd9", 2)
                if eoi == -1:
                    break
                jpg = bytes(buf[: eoi + 2])
                del buf[: eoi + 2]
                now_ts = time.time()
                self._latest_jpeg = jpg
                self._latest_frame_ts = now_ts
                self._frame_history.append((now_ts, jpg))
                self._frame_seq += 1
                self.total_frames_decoded += 1
                self._new_frame_event.set()

    def render_current_frame_jpeg(
        self,
        width: int = 1280,
        hud: bool = True,
        quality: int = 84,
        raw_jpg: Optional[bytes] = None,
        frame_ts: Optional[float] = None,
    ) -> Optional[bytes]:
        """Renderiza un fotograma JPEG en vivo (con o sin HUD táctico TARDIS y escalado opcional)."""
        src_jpg = raw_jpg or self._latest_jpeg
        if not src_jpg:
            latest_file = DETECTIONS_DIR / "latest_frame.jpg"
            if latest_file.is_file():
                try:
                    src_jpg = latest_file.read_bytes()
                except Exception:
                    return None
        if not src_jpg:
            return None

        orig_h, orig_w = self._latest_bgr_shape
        if not hud and (width <= 0 or width >= orig_w):
            return src_jpg

        arr = np.frombuffer(src_jpg, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return src_jpg
        bh, bw = bgr.shape[:2]
        self._latest_bgr_shape = (bh, bw)

        if 0 < width < bw:
            target_w = int(width) - (int(width) % 2)
            target_h = int(round(bh * (target_w / float(bw))))
            target_h -= target_h % 2
            bgr = cv2.resize(bgr, (max(2, target_w), max(2, target_h)), interpolation=cv2.INTER_AREA)

        if hud:
            ts_val = frame_ts or self._latest_frame_ts or time.time()
            ms_part = int((ts_val % 1.0) * 10)
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_val)) + f".{ms_part}"
            bgr = render_tardis_hud(
                bgr,
                list(self._latest_detections),
                camera_alias=self.device_alias,
                camera_ip=self.host,
                camera_model=f"Tapo {self.device_model}",
                timestamp_str=ts_str,
                orig_size=(bw, bh),
                live_badge=True,
            )

        ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        return enc.tobytes() if ok else src_jpg

    async def record_live_mp4_clip(
        self,
        duration_sec: float = 6.0,
        fps: int = 12,
        width: int = 1280,
        hud: bool = True,
    ) -> Dict[str, Any]:
        """
        Graba en tiempo real un clip de video MP4 (H.264 yuv420p + pista de audio TARDIS)
        directamente desde el flujo en vivo de la cámara Tapo C310, combinando una ventana
        corta del buffer circular en memoria + fotogramas frescos en tiempo real.
        """
        duration_sec = max(2.0, min(25.0, float(duration_sec)))
        fps = max(6, min(24, int(fps)))
        width = max(480, min(2304, int(width)))
        width -= width % 2

        async with self._clip_lock:
            t0 = time.perf_counter()
            loop = asyncio.get_running_loop()

            # Esperar hasta 4s si el flujo acaba de arrancar y aún no hay fotogramas
            for _ in range(20):
                if self._latest_jpeg is not None:
                    break
                await asyncio.sleep(0.2)

            if self._latest_jpeg is None:
                latest_disk = DETECTIONS_DIR / "latest_frame.jpg"
                if latest_disk.is_file():
                    self._latest_jpeg = latest_disk.read_bytes()
                    self._latest_frame_ts = latest_disk.stat().st_mtime
                else:
                    return {"ok": False, "error": "Flujo en vivo no disponible aún"}

            orig_h, orig_w = self._latest_bgr_shape
            if orig_w <= 0 or orig_h <= 0:
                orig_w, orig_h = 2304, 1296
            height = int(round(orig_h * (width / float(orig_w))))
            height -= height % 2
            height = max(270, height)

            total_frames = max(12, int(round(duration_sec * fps)))
            step_sec = 1.0 / float(fps)

            # Tomar hasta 1.5s del buffer circular reciente para respuesta aún más ágil
            now_wall = time.time()
            pre_window_sec = min(1.5, duration_sec * 0.30)
            history_snap = [
                (ts, jpg)
                for (ts, jpg) in list(self._frame_history)
                if (now_wall - ts) <= pre_window_sec
            ]
            pre_frames_pairs: List[Tuple[float, bytes]] = []
            if len(history_snap) >= 2:
                max_pre = min(len(history_snap), int(round(pre_window_sec * fps)))
                idxs = np.linspace(0, len(history_snap) - 1, max_pre, dtype=int)
                pre_frames_pairs = [history_snap[int(i)] for i in idxs]

            live_needed = max(1, total_frames - len(pre_frames_pairs))
            ts_tag = time.strftime("%Y%m%d_%H%M%S")
            out_path = LIVE_CLIPS_DIR / f"godeye_live_{ts_tag}_{int((time.time() % 1)*1000):03d}.mp4"
            raw_video_tmp = LIVE_CLIPS_DIR / f".tmp_vid_{ts_tag}_{os.getpid()}.mp4"

            ff_cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "pipe:0",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "23",
                "-movflags",
                "+faststart",
                str(raw_video_tmp),
            ]

            ff_proc = await asyncio.create_subprocess_exec(
                *ff_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            def _prepare_bgr_bytes(
                jpg_bytes: bytes,
                ts_val: float,
                dets: List[PersonDetection],
            ) -> Optional[bytes]:
                arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    return None
                bh, bw = bgr.shape[:2]
                if bw != width or bh != height:
                    bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
                if hud:
                    ms_digit = int((ts_val % 1.0) * 10)
                    ts_lbl = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_val)) + f".{ms_digit}"
                    bgr = render_tardis_hud(
                        bgr,
                        dets,
                        camera_alias=self.device_alias,
                        camera_ip=self.host,
                        camera_model=f"Tapo {self.device_model}",
                        timestamp_str=ts_lbl,
                        orig_size=(bw, bh),
                        live_badge=True,
                    )
                return bgr.tobytes()

            written_frames = 0
            max_persons_seen = len(self._latest_detections)
            try:
                assert ff_proc.stdin is not None
                for f_ts, f_jpg in pre_frames_pairs:
                    raw_bgr = await loop.run_in_executor(
                        None,
                        _prepare_bgr_bytes,
                        f_jpg,
                        f_ts,
                        list(self._latest_detections),
                    )
                    if raw_bgr:
                        ff_proc.stdin.write(raw_bgr)
                        await ff_proc.stdin.drain()
                        written_frames += 1

                t_live_start = time.perf_counter()
                for idx in range(live_needed):
                    cur_jpg = self._latest_jpeg
                    cur_ts = self._latest_frame_ts or time.time()
                    cur_dets = list(self._latest_detections)
                    if len(cur_dets) > max_persons_seen:
                        max_persons_seen = len(cur_dets)
                    if cur_jpg:
                        raw_bgr = await loop.run_in_executor(
                            None,
                            _prepare_bgr_bytes,
                            cur_jpg,
                            cur_ts,
                            cur_dets,
                        )
                        if raw_bgr:
                            ff_proc.stdin.write(raw_bgr)
                            await ff_proc.stdin.drain()
                            written_frames += 1

                    target_elapsed = (idx + 1) * step_sec
                    sleep_s = target_elapsed - (time.perf_counter() - t_live_start)
                    if sleep_s > 0.004:
                        await asyncio.sleep(sleep_s)

                ff_proc.stdin.close()
                _, stderr_bytes = await asyncio.wait_for(ff_proc.communicate(), timeout=20.0)
                if ff_proc.returncode != 0 or not raw_video_tmp.is_file():
                    err_txt = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
                    return {"ok": False, "error": f"Fallo codificando MP4 en vivo: {err_txt}"}

                # Multiplexar pista acústica soberana de telemetría TARDIS para que el video tenga audio
                def _finalize_clip() -> Path:
                    os.replace(raw_video_tmp, out_path)
                    try:
                        from core.tardis_audio_synthesizer import ensure_video_has_audio
                        ensure_video_has_audio(
                            out_path,
                            title=f"GOD-EYE {self.device_alias} Transmisión en Vivo",
                        )
                    except Exception as e_aud:
                        logger.debug(f"Aviso aplicando audio a clip en vivo: {e_aud}")
                    # Limpiar clips antiguos (conservar últimos 20)
                    try:
                        clips = sorted(
                            LIVE_CLIPS_DIR.glob("godeye_live_*.mp4"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        for old_c in clips[20:]:
                            old_c.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return out_path

                final_path = await loop.run_in_executor(None, _finalize_clip)
                actual_dur = round(written_frames / float(fps), 2)
                elapsed_total = round(time.perf_counter() - t0, 2)
                return {
                    "ok": True,
                    "path": str(final_path),
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "frames": written_frames,
                    "duration_sec": actual_dur,
                    "elapsed_sec": elapsed_total,
                    "persons_detected": max_persons_seen,
                    "camera_alias": self.device_alias,
                    "camera_host": self.host,
                    "camera_model": self.device_model,
                    "size_bytes": final_path.stat().st_size if final_path.is_file() else 0,
                }
            finally:
                if ff_proc.returncode is None:
                    try:
                        ff_proc.kill()
                    except Exception:
                        pass
                raw_video_tmp.unlink(missing_ok=True)

    # --------------------------------------------------------------------------
    # SERVIDOR HTTP / WEBSOCKET LOCAL DE DISTRIBUCIÓN EN VIVO (:8797)
    # --------------------------------------------------------------------------

    def _build_live_state_dict(self) -> Dict[str, Any]:
        now = time.time()
        age = round(now - self._latest_frame_ts, 3) if self._latest_frame_ts > 0 else None
        h, w = self._latest_bgr_shape
        return {
            "ok": self.stream_connected and (age is not None and age < 15.0),
            "service": "tardis-tapo-c310-sentinel",
            "stream_connected": self.stream_connected,
            "frame_seq": self._frame_seq,
            "latest_frame_ts": self._latest_frame_ts,
            "latest_frame_age_sec": age,
            "resolution": f"{w}x{h}",
            "width": w,
            "height": h,
            "camera": {
                "host": self.host,
                "alias": self.device_alias,
                "model": self.device_model,
                "mac": self.mac_address,
                "firmware": self.device_hw_info.get("sw_version", ""),
            },
            "metrics": {
                "total_frames_decoded": self.total_frames_decoded,
                "total_frames_analyzed": self.total_frames_analyzed,
                "total_alerts_sent": self.total_alerts_sent,
                "total_voice_warnings_spoken": self.total_voice_warnings_spoken,
                "total_new_visitors_detected": self.reid_tracker.total_new_visitors,
                "last_inference_ms": round(self._latest_inference_ms, 2),
                "current_persons": len(self._latest_detections),
                "presence_latched": self.presence_latched,
            },
            "detections": [d.to_dict() for d in self._latest_detections],
        }

    async def _http_health(self, request: web.Request) -> web.Response:
        return web.json_response(self._build_live_state_dict())

    async def _http_snapshot(self, request: web.Request) -> web.Response:
        hud = request.query.get("hud", "1").lower() not in ("0", "false", "no")
        width = int(request.query.get("width", "1280") or 1280)
        quality = int(request.query.get("quality", "85") or 85)
        loop = asyncio.get_running_loop()
        jpg = await loop.run_in_executor(
            None,
            self.render_current_frame_jpeg,
            width,
            hud,
            quality,
            None,
            None,
        )
        if not jpg:
            return web.Response(status=503, text="Fotograma en vivo no disponible")
        return web.Response(
            body=jpg,
            content_type="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "X-Frame-Seq": str(self._frame_seq),
                "X-Persons-Detected": str(len(self._latest_detections)),
            },
        )

    async def _http_mjpeg_stream(self, request: web.Request) -> web.StreamResponse:
        hud = request.query.get("hud", "1").lower() not in ("0", "false", "no")
        width = int(request.query.get("width", "1280") or 1280)
        fps = max(1, min(20, int(request.query.get("fps", "10") or 10)))
        quality = int(request.query.get("quality", "78") or 78)
        min_interval = 1.0 / float(fps)

        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)
        loop = asyncio.get_running_loop()
        last_seq = -1
        try:
            while not self._stop_event.is_set():
                t0 = time.perf_counter()
                if self._frame_seq != last_seq and self._latest_jpeg:
                    last_seq = self._frame_seq
                    raw_jpg = self._latest_jpeg
                    f_ts = self._latest_frame_ts
                    jpg = await loop.run_in_executor(
                        None,
                        self.render_current_frame_jpeg,
                        width,
                        hud,
                        quality,
                        raw_jpg,
                        f_ts,
                    )
                    if jpg:
                        part_hdr = (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            + f"Content-Length: {len(jpg)}\r\n\r\n".encode("ascii")
                        )
                        await resp.write(part_hdr + jpg + b"\r\n")
                elapsed = time.perf_counter() - t0
                await asyncio.sleep(max(0.02, min_interval - elapsed))
        except (ConnectionResetError, asyncio.CancelledError, Exception):
            pass
        return resp

    async def _http_ws_stream(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)

        hud = request.query.get("hud", "1").lower() not in ("0", "false", "no")
        width = int(request.query.get("width", "1280") or 1280)
        fps = max(1, min(20, int(request.query.get("fps", "10") or 10)))
        quality = int(request.query.get("quality", "78") or 78)
        loop = asyncio.get_running_loop()

        async def _reader_ctrl() -> None:
            nonlocal hud, width, fps, quality
            try:
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except Exception:
                            continue
                        mtype = data.get("type")
                        if mtype == "set_options":
                            if "hud" in data:
                                hud = bool(data["hud"])
                            if "width" in data:
                                width = max(480, min(2304, int(data["width"])))
                            if "fps" in data:
                                fps = max(1, min(20, int(data["fps"])))
                            if "quality" in data:
                                quality = max(40, min(95, int(data["quality"])))
                        elif mtype == "speak":
                            txt = str(data.get("text") or "").strip() or None
                            res = await self._announce_new_person_voice([], custom_text=txt)
                            if not ws.closed:
                                await ws.send_str(
                                    json.dumps({"type": "speak_result", **res}, ensure_ascii=False)
                                )
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
            except Exception:
                pass

        ctrl_task = asyncio.create_task(_reader_ctrl())
        last_seq = -1
        try:
            while not ws.closed and not self._stop_event.is_set():
                t0 = time.perf_counter()
                if self._frame_seq != last_seq and self._latest_jpeg:
                    last_seq = self._frame_seq
                    raw_jpg = self._latest_jpeg
                    f_ts = self._latest_frame_ts
                    jpg = await loop.run_in_executor(
                        None,
                        self.render_current_frame_jpeg,
                        width,
                        hud,
                        quality,
                        raw_jpg,
                        f_ts,
                    )
                    if jpg and not ws.closed:
                        meta_msg = {
                            "type": "frame_meta",
                            "seq": last_seq,
                            "ts": round(f_ts, 3),
                            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f_ts)),
                            "persons": len(self._latest_detections),
                            "detections": [d.to_dict() for d in self._latest_detections],
                            "inference_ms": round(self._latest_inference_ms, 1),
                            "stream_connected": self.stream_connected,
                            "camera_alias": self.device_alias,
                            "camera_host": self.host,
                        }
                        await ws.send_str(json.dumps(meta_msg, ensure_ascii=False))
                        await ws.send_bytes(jpg)
                elapsed = time.perf_counter() - t0
                await asyncio.sleep(max(0.025, (1.0 / float(fps)) - elapsed))
        except (ConnectionResetError, asyncio.CancelledError, Exception):
            pass
        finally:
            ctrl_task.cancel()
            try:
                await ctrl_task
            except (asyncio.CancelledError, Exception):
                pass
        return ws

    async def _http_record_clip(self, request: web.Request) -> web.Response:
        params: Dict[str, Any] = dict(request.query)
        if request.method == "POST":
            try:
                body = await request.json()
                if isinstance(body, dict):
                    params.update(body)
            except Exception:
                pass
        duration = float(params.get("duration", 6.0) or 6.0)
        fps = int(params.get("fps", 12) or 12)
        width = int(params.get("width", 1280) or 1280)
        hud = str(params.get("hud", "1")).lower() not in ("0", "false", "no")
        res = await self.record_live_mp4_clip(
            duration_sec=duration,
            fps=fps,
            width=width,
            hud=hud,
        )
        if request.path.endswith(".mp4") and res.get("ok") and res.get("path"):
            p = Path(res["path"])
            if p.is_file():
                return web.Response(
                    body=p.read_bytes(),
                    content_type="video/mp4",
                    headers={"Cache-Control": "no-store"},
                )
        return web.json_response(res, status=200 if res.get("ok") else 500)

    async def _http_speak(self, request: web.Request) -> web.Response:
        text: Optional[str] = request.query.get("text")
        if request.method == "POST":
            try:
                body = await request.json()
                if isinstance(body, dict) and body.get("text"):
                    text = str(body["text"])
            except Exception:
                pass
        res = await self._announce_new_person_voice([], custom_text=text.strip() if text else None)
        return web.json_response(res, status=200 if res.get("ok") else 500)

    async def _start_hub_server(self) -> None:
        if self._hub_runner is not None:
            return
        app = web.Application()
        app.router.add_get("/health", self._http_health)
        app.router.add_get("/c310/health", self._http_health)
        app.router.add_get("/c310/state", self._http_health)
        app.router.add_get("/c310/snapshot.jpg", self._http_snapshot)
        app.router.add_get("/c310/stream.mjpg", self._http_mjpeg_stream)
        app.router.add_get("/c310/ws", self._http_ws_stream)
        app.router.add_get("/c310/clip.mp4", self._http_record_clip)
        app.router.add_get("/c310/record_clip", self._http_record_clip)
        app.router.add_post("/c310/record_clip", self._http_record_clip)
        app.router.add_post("/c310/speak", self._http_speak)

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, SENTINEL_HUB_HOST, SENTINEL_HUB_PORT, reuse_address=True)
        await site.start()
        self._hub_runner = runner
        logger.info(
            f"Hub de transmisión en vivo GOD-EYE activo en http://{SENTINEL_HUB_HOST}:{SENTINEL_HUB_PORT}/c310/"
        )

    async def _stop_hub_server(self) -> None:
        if self._hub_runner is not None:
            try:
                await self._hub_runner.cleanup()
            except Exception:
                pass
            self._hub_runner = None

    async def _analysis_worker(self, client: httpx.AsyncClient) -> None:
        """Muestrea el fotograma más reciente a ~2.5 FPS y ejecuta YOLOv8s + máquina de estados de alerta."""
        sample_interval = max(0.20, float(self.config.get("sample_interval_sec", 0.40)))
        confirm_needed = max(1, int(self.config.get("confirm_frames", 2)))
        extra_best_frames = max(0, int(self.config.get("best_shot_extra_frames", 1)))
        cooldown_sec = max(5.0, float(self.config.get("alert_cooldown_sec", 30.0)))
        clear_reset_sec = max(2.0, float(self.config.get("clear_reset_sec", 8.0)))
        save_latest_interval = max(1.0, float(self.config.get("latest_frame_save_interval_sec", 2.0)))
        cctv_interval = max(1.5, float(self.config.get("cctv_hub_interval_sec", 2.5)))

        last_analyzed_seq = -1
        last_disk_save_ts = 0.0
        last_cctv_push_ts = 0.0

        # Ventana corta para elegir la toma más nítida/confiable al confirmar un individuo
        candidate_shots: List[Tuple[float, bytes, np.ndarray, List[PersonDetection], float]] = []
        collecting_extra: int = 0
        pending_new_ids: List[int] = []
        pending_voice_dispatched: bool = False
        speaker_min_interval = max(
            4.0, float(self.config.get("speaker_min_interval_sec", 10.0))
        )

        loop = asyncio.get_running_loop()

        while not self._stop_event.is_set():
            await self._new_frame_event.wait()
            self._new_frame_event.clear()

            if self._frame_seq == last_analyzed_seq or not self._latest_jpeg:
                continue

            t_cycle_start = time.perf_counter()
            raw_jpg = self._latest_jpeg
            last_analyzed_seq = self._frame_seq

            # Decodificación + YOLOv8s en threadpool para no bloquear el lector asíncrono del socket :8800
            def _decode_and_detect(jpg_data: bytes):
                arr = np.frombuffer(jpg_data, dtype=np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    return None, [], 0.0
                dets, ms = self.detector.detect(bgr)
                return bgr, dets, ms

            bgr_frame, detections, latency_ms = await loop.run_in_executor(
                None, _decode_and_detect, raw_jpg
            )
            if bgr_frame is None:
                continue

            self.total_frames_analyzed += 1
            self._latest_bgr_shape = bgr_frame.shape[:2]
            self._latest_detections = detections
            self._latest_inference_ms = latency_ms
            now = time.time()

            # Persistir latest_frame.jpg y latest_hud_frame.jpg atómicamente cada ~2s para consultas instantáneas (/c310)
            if (now - last_disk_save_ts) >= save_latest_interval:
                last_disk_save_ts = now
                try:
                    self._atomic_write_bytes(DETECTIONS_DIR / "latest_frame.jpg", raw_jpg)
                    hud_jpg = await loop.run_in_executor(
                        None,
                        self.render_current_frame_jpeg,
                        1280,
                        True,
                        86,
                        raw_jpg,
                        now,
                    )
                    if hud_jpg:
                        self._atomic_write_bytes(DETECTIONS_DIR / "latest_hud_frame.jpg", hud_jpg)
                except Exception:
                    pass
                self._update_state_file(detections, latency_ms)

            # Alimentar Hub CCTV local de TARDIS (:8757)
            if (now - last_cctv_push_ts) >= cctv_interval:
                last_cctv_push_ts = now
                asyncio.create_task(self._push_cctv_hub_frame(client, bgr_frame, detections))

            # Máquina de estados de detección humana + Re-identificación de individuos nuevos
            if detections:
                self.last_person_seen_ts = now
                self.consecutive_positive += 1
                shot_score = sum(d.confidence * max(1, d.area) for d in detections)
                candidate_shots.append((shot_score, raw_jpg, bgr_frame, detections, latency_ms))
                if len(candidate_shots) > (confirm_needed + extra_best_frames + 2):
                    candidate_shots.pop(0)

                self.reid_tracker.update_and_check_new(
                    bgr_frame,
                    detections,
                    now,
                    confirmed=(self.consecutive_positive >= confirm_needed),
                )

                # Directiva Arquitecto (TARDIS-NEURAL-SPACE-KAIJU) · Aviso Vocal Dwell-Gated:
                # El aviso SOLO debe sonar cuando la persona permanezca más de 1.5 minutos
                # (dwell_trigger_sec = 90.0 s) cerca de la cámara. Se reclaman los tracks cuyo
                # tiempo de permanencia superó el umbral y que aún no han recibido el aviso.
                dwell_due_ids: List[int] = []
                dwell_ready = False
                if detections:
                    dwell_due_ids = self.reid_tracker.claim_dwell_voice_targets(
                        now, self.dwell_trigger_sec
                    )
                    dwell_ready = bool(
                        self.reid_tracker.dwell_targets_active(now, self.dwell_trigger_sec)
                    )
                if dwell_due_ids:
                    pending_new_ids.extend(dwell_due_ids)
                    voice_busy = self._voice_task is not None and not self._voice_task.done()
                    if (
                        self.config.get("speaker_enabled", True)
                        and not voice_busy
                        and (now - self.last_voice_warning_ts) >= speaker_min_interval
                    ):
                        self.last_voice_warning_ts = now
                        pending_voice_dispatched = True
                        self._voice_task = asyncio.create_task(
                            self._announce_new_person_voice(
                                list(dwell_due_ids),
                                custom_text=self._build_vigilance_alert_text(),
                            )
                        )

                should_evaluate_trigger = False
                if self.consecutive_positive == confirm_needed:
                    if extra_best_frames > 0:
                        collecting_extra = extra_best_frames
                    else:
                        should_evaluate_trigger = True
                elif collecting_extra > 0:
                    collecting_extra -= 1
                    if collecting_extra == 0:
                        should_evaluate_trigger = True
                elif self.consecutive_positive > confirm_needed:
                    elapsed_since_alert = now - self.last_alert_ts
                    more_people = len(detections) > self.last_alert_person_count
                    if (
                        bool(pending_new_ids)
                        or (not self.presence_latched and elapsed_since_alert >= 4.0 and dwell_ready)
                        or (elapsed_since_alert >= cooldown_sec)
                        or (more_people and elapsed_since_alert >= 6.0)
                    ):
                        should_evaluate_trigger = True

                if should_evaluate_trigger and candidate_shots:
                    elapsed_since_alert = now - self.last_alert_ts
                    more_people = len(detections) > self.last_alert_person_count
                    can_alert = (
                        bool(pending_new_ids)
                        or (not self.presence_latched and elapsed_since_alert >= 4.0 and dwell_ready)
                        or (elapsed_since_alert >= cooldown_sec)
                        or (more_people and elapsed_since_alert >= 6.0)
                    )
                    if can_alert:
                        best = max(candidate_shots, key=lambda item: item[0])
                        _, b_jpg, b_bgr, b_dets, b_ms = best
                        self.presence_latched = True
                        candidate_shots.clear()
                        dispatched_ids = list(pending_new_ids)
                        voice_flag = pending_voice_dispatched
                        pending_new_ids.clear()
                        pending_voice_dispatched = False
                        await self._dispatch_person_alert(
                            client,
                            b_jpg,
                            b_bgr,
                            b_dets,
                            b_ms,
                            is_test=False,
                            new_visitor_ids=dispatched_ids,
                            voice_dispatched=voice_flag,
                        )
                        self._update_state_file(b_dets, b_ms)
            else:
                self.reid_tracker.update_and_check_new(bgr_frame, [], now, confirmed=False)
                self.consecutive_positive = 0
                collecting_extra = 0
                pending_new_ids.clear()
                pending_voice_dispatched = False
                candidate_shots.clear()
                if self.presence_latched and (now - self.last_person_seen_ts) >= clear_reset_sec:
                    logger.info(
                        f"Perímetro despejado durante {clear_reset_sec:.0f}s. Rearmando gatillo instantáneo."
                    )
                    self.presence_latched = False
                    self.last_alert_person_count = 0
                    self._update_state_file([], latency_ms)

            elapsed = time.perf_counter() - t_cycle_start
            sleep_rem = sample_interval - elapsed
            if sleep_rem > 0.01:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_rem)
                except asyncio.TimeoutError:
                    pass

    async def run_forever(self, send_startup_photo: bool = False) -> None:
        """Bucle maestro 24/7 con auto-reconexión resiliente y hub local de transmisión en vivo (:8797)."""
        logger.info(
            f"Iniciando Centinela TARDIS para Tapo {self.device_model} en {self.host}..."
        )
        try:
            await self._start_hub_server()
        except Exception as hub_exc:
            logger.warning(f"No se pudo iniciar hub HTTP en :{SENTINEL_HUB_PORT}: {hub_exc}")

        if self.config.get("speaker_enabled", True):
            try:
                pw_res = await self.speaker.prewarm_default_phrase()
                logger.info(
                    f"Altavoz C310 listo (voz={pw_res.get('voice')}, "
                    f"duración={pw_res.get('duration_sec')}s, caché={pw_res.get('cached')})."
                )
            except Exception as pw_exc:
                logger.warning(f"Precalentamiento TTS de altavoz omitido: {pw_exc}")

        backoff = 2.0
        startup_sent = not send_startup_photo

        try:
            async with httpx.AsyncClient() as http_client:
                while not self._stop_event.is_set():
                    streamer: Optional[Streamer] = None
                    proc: Optional[asyncio.subprocess.Process] = None
                    stream_proc_task: Optional[asyncio.Task] = None
                    reader_task: Optional[asyncio.Task] = None
                    analyzer_task: Optional[asyncio.Task] = None
                    tapo: Optional[Tapo] = None
                    frames_before = self.total_frames_decoded

                    try:
                        loop = asyncio.get_running_loop()
                        tapo = await loop.run_in_executor(None, self._connect_tapo_sync)
                        logger.info(
                            f"Conectado a '{self.device_alias}' ({self.device_model} "
                            f"FW: {self.device_hw_info.get('sw_version', 'N/A')}) en {self.host}."
                        )

                        streamer = Streamer(
                            tapo,
                            audio=[],
                            quality=str(self.config.get("stream_quality", "HD")),
                            mode="pipe",
                            ff_args={
                                "-loglevel": "error",
                                "-probesize": "300000",
                                "-analyzeduration": "300000",
                                "-c:v": "mjpeg",
                                "-f": "image2pipe",
                            },
                        )
                        info = await asyncio.wait_for(streamer.start(), timeout=15.0)
                        proc = info["ffmpegProcess"]
                        stream_proc_task = info.get("streamProcess")
                        self.stream_connected = True
                        backoff = 2.0
                        self._update_state_file()

                        reader_task = asyncio.create_task(self._mjpeg_stdout_reader(proc))
                        analyzer_task = asyncio.create_task(self._analysis_worker(http_client))

                        if not startup_sent:
                            # Esperar el primer fotograma decodificado y enviar confirmación visual al Arquitecto
                            for _ in range(60):
                                if self._latest_jpeg is not None:
                                    break
                                await asyncio.sleep(0.25)
                            if self._latest_jpeg is not None:
                                jpg0 = self._latest_jpeg
                                bgr0 = cv2.imdecode(np.frombuffer(jpg0, np.uint8), cv2.IMREAD_COLOR)
                                if bgr0 is not None:
                                    dets0, ms0 = await loop.run_in_executor(
                                        None, self.detector.detect, bgr0
                                    )
                                    await self._dispatch_person_alert(
                                        http_client, jpg0, bgr0, dets0, ms0, is_test=True
                                    )
                                    startup_sent = True

                        wait_tasks = [reader_task, analyzer_task]
                        if stream_proc_task is not None:
                            wait_tasks.append(stream_proc_task)
                        done, _ = await asyncio.wait(
                            wait_tasks,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in done:
                            if task.exception():
                                raise task.exception()  # type: ignore[misc]
                        if stream_proc_task in done:
                            raise EOFError("La tarea de sesión :8800 (streamProcess) finalizó.")

                    except asyncio.CancelledError:
                        break
                    except Exception as exc:
                        self.stream_connected = False
                        self._update_state_file(last_error=str(exc))
                        decoded_in_session = self.total_frames_decoded - frames_before
                        if decoded_in_session == 0:
                            self._consecutive_zero_frame_connects += 1
                        else:
                            self._consecutive_zero_frame_connects = 0

                        if self._consecutive_zero_frame_connects >= 3 and tapo is not None:
                            logger.warning(
                                f"Detectados {self._consecutive_zero_frame_connects} intentos sin fotogramas en :8800. "
                                f"Ejecutando auto-sanación de hardware (reboot de {self.host} vía :443)..."
                            )
                            self._consecutive_zero_frame_connects = 0
                            try:
                                await asyncio.get_running_loop().run_in_executor(None, tapo.reboot)
                                backoff = 32.0
                            except Exception as reb_exc:
                                logger.warning(f"No se pudo reiniciar cámara automáticamente: {reb_exc}")
                        else:
                            logger.warning(
                                f"Flujo interrumpido en {self.host} ({exc}). Reconectando en {backoff:.1f}s..."
                            )
                    finally:
                        self.stream_connected = False
                        for t in (reader_task, analyzer_task):
                            if t and not t.done():
                                t.cancel()
                                try:
                                    await t
                                except (asyncio.CancelledError, Exception):
                                    pass
                        if proc and proc.returncode is None:
                            try:
                                proc.kill()
                                await asyncio.wait_for(proc.wait(), timeout=2.0)
                            except Exception:
                                pass
                        if streamer is not None:
                            try:
                                await asyncio.wait_for(streamer.stop(), timeout=2.5)
                            except Exception:
                                pass

                    if not self._stop_event.is_set():
                        try:
                            await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                        except asyncio.TimeoutError:
                            pass
                        backoff = min(20.0, backoff * 1.7)
        finally:
            await self._stop_hub_server()

    async def capture_single_snapshot(self, send_telegram: bool = False) -> Dict[str, Any]:
        """Captura un fotograma 2K instantáneo (usando hub local / caché reciente si el demonio está activo o conexión directa)."""
        latest_file = DETECTIONS_DIR / "latest_frame.jpg"
        raw_jpg: Optional[bytes] = None

        if latest_file.is_file() and (time.time() - latest_file.stat().st_mtime) <= 10.0:
            raw_jpg = latest_file.read_bytes()
        else:
            try:
                async with httpx.AsyncClient() as cl:
                    r_snap = await cl.get(
                        f"http://{SENTINEL_HUB_HOST}:{SENTINEL_HUB_PORT}/c310/snapshot.jpg?hud=0&width=2304",
                        timeout=3.5,
                    )
                    if r_snap.status_code == 200 and r_snap.content:
                        raw_jpg = r_snap.content
            except Exception:
                raw_jpg = None

        if not raw_jpg:
            loop = asyncio.get_running_loop()
            tapo = await loop.run_in_executor(None, self._connect_tapo_sync)
            streamer = Streamer(
                tapo,
                audio=[],
                quality="HD",
                mode="pipe",
                ff_args={
                    "-loglevel": "error",
                    "-probesize": "300000",
                    "-analyzeduration": "300000",
                    "-frames:v": "1",
                    "-c:v": "mjpeg",
                    "-f": "image2pipe",
                },
            )
            try:
                info = await asyncio.wait_for(streamer.start(), timeout=15.0)
                proc = info["ffmpegProcess"]
                raw_jpg = await asyncio.wait_for(proc.stdout.read(), timeout=15.0)
            finally:
                try:
                    await asyncio.wait_for(streamer.stop(), timeout=2.5)
                except Exception:
                    pass

        if not raw_jpg:
            return {"ok": False, "error": "No se pudo obtener fotograma de la cámara."}

        bgr = cv2.imdecode(np.frombuffer(raw_jpg, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return {"ok": False, "error": "Fotograma JPEG inválido."}

        detections, ms = self.detector.detect(bgr)
        if send_telegram:
            async with httpx.AsyncClient() as client:
                ev = await self._dispatch_person_alert(
                    client, raw_jpg, bgr, detections, ms, is_test=True
                )
                return {"ok": True, "event": ev}

        ts_human = time.strftime("%Y-%m-%d %H:%M:%S")
        annotated = render_tardis_hud(
            bgr,
            detections,
            camera_alias=self.device_alias,
            camera_ip=self.host,
            camera_model=f"Tapo {self.device_model}",
            timestamp_str=ts_human,
            live_badge=True,
        )
        out_path = DETECTIONS_DIR / "manual_snapshot.jpg"
        cv2.imwrite(str(out_path), annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        return {
            "ok": True,
            "path": str(out_path),
            "resolution": f"{bgr.shape[1]}x{bgr.shape[0]}",
            "persons_detected": len(detections),
            "detections": [d.to_dict() for d in detections],
            "inference_ms": round(ms, 2),
        }

    def request_stop(self) -> None:
        self._stop_event.set()
        self._new_frame_event.set()


def get_cached_c310_snapshot_bytes() -> Tuple[Optional[bytes], Dict[str, Any]]:
    """Helper rápido (<2ms) para que TelegramBridge obtenga el último fotograma 2K del demonio activo."""
    state_file = DETECTIONS_DIR / "sentinel_state.json"
    latest_file = DETECTIONS_DIR / "latest_frame.jpg"
    meta: Dict[str, Any] = {}
    if state_file.is_file():
        try:
            meta = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    if latest_file.is_file():
        try:
            return latest_file.read_bytes(), meta
        except Exception:
            pass
    return None, meta


def get_c310_live_hud_jpeg_sync(
    width: int = 1280,
    hud: bool = True,
    quality: int = 85,
) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """
    Obtiene un fotograma JPEG en vivo con HUD táctico TARDIS desde el hub del centinela (:8797),
    con fallback inmediato a `latest_hud_frame.jpg` / `latest_frame.jpg` en disco.
    """
    state_file = DETECTIONS_DIR / "sentinel_state.json"
    meta: Dict[str, Any] = {}
    if state_file.is_file():
        try:
            meta = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    try:
        with httpx.Client(timeout=2.5) as cl:
            r = cl.get(
                f"http://{SENTINEL_HUB_HOST}:{SENTINEL_HUB_PORT}/c310/snapshot.jpg",
                params={"hud": "1" if hud else "0", "width": str(width), "quality": str(quality)},
            )
            if r.status_code == 200 and r.content:
                return r.content, meta
    except Exception:
        pass

    candidate = DETECTIONS_DIR / ("latest_hud_frame.jpg" if hud else "latest_frame.jpg")
    if not candidate.is_file():
        candidate = DETECTIONS_DIR / "latest_frame.jpg"
    if candidate.is_file():
        try:
            return candidate.read_bytes(), meta
        except Exception:
            pass
    return None, meta


def record_c310_live_clip_sync(
    duration_sec: float = 6.0,
    fps: int = 12,
    width: int = 1280,
    hud: bool = True,
) -> Dict[str, Any]:
    """
    Solicita al hub local del centinela (:8797) grabar en tiempo real un clip MP4 H.264
    con HUD táctico y audio sincronizado de la cámara Tapo C310.
    """
    duration_sec = max(2.0, min(25.0, float(duration_sec)))
    try:
        with httpx.Client(timeout=duration_sec + 18.0) as cl:
            resp = cl.post(
                f"http://{SENTINEL_HUB_HOST}:{SENTINEL_HUB_PORT}/c310/record_clip",
                json={
                    "duration": duration_sec,
                    "fps": fps,
                    "width": width,
                    "hud": hud,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data
    except Exception as exc:
        logger.warning(f"Aviso grabando clip vía hub :{SENTINEL_HUB_PORT}: {exc}")

    # Fallback autónomo si el hub no respondió: generar clip desde latest_frame.jpg
    try:
        sentinel = TapoC310Sentinel()
        return asyncio.run(
            sentinel.record_live_mp4_clip(
                duration_sec=duration_sec,
                fps=fps,
                width=width,
                hud=hud,
            )
        )
    except Exception as exc_fb:
        return {"ok": False, "error": str(exc_fb)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TARDIS Sentinel · Detección Humana y Alertas para TP-Link Tapo C310"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--daemon", action="store_true", help="Ejecutar centinela continuo 24/7"
    )
    parser.add_argument(
        "--send-startup-photo",
        action="store_true",
        help="Enviar fotografía inicial de verificación al conectar el flujo",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Capturar y analizar un fotograma único",
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="Capturar fotograma en vivo y probar envío de alerta por Telegram/Escritorio",
    )
    parser.add_argument(
        "--record-clip",
        type=float,
        default=None,
        help="Grabar un clip MP4 en vivo de N segundos desde el flujo de la cámara",
    )
    parser.add_argument(
        "--speak",
        type=str,
        default=None,
        help="Pronunciar un mensaje personalizado desde la bocina de la cámara C310",
    )
    parser.add_argument(
        "--test-voice",
        action="store_true",
        help="Emitir inmediatamente el aviso vocal de vigilancia TARDIS por la bocina C310",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Mostrar estado actual del centinela",
    )
    args = parser.parse_args()

    if args.status:
        state_file = DETECTIONS_DIR / "sentinel_state.json"
        if state_file.is_file():
            print(state_file.read_text(encoding="utf-8"))
            return 0
        print(json.dumps({"ok": False, "error": "sentinel_state.json aún no generado"}))
        return 1

    if args.record_clip is not None:
        res_clip = record_c310_live_clip_sync(duration_sec=args.record_clip)
        print(json.dumps(res_clip, indent=2, ensure_ascii=False))
        return 0 if res_clip.get("ok") else 1

    sentinel = TapoC310Sentinel(config_path=args.config)

    if args.speak is not None or args.test_voice:
        res = asyncio.run(sentinel.speaker.speak(text=args.speak if args.speak else None))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    if args.snapshot or args.test_alert:
        res = asyncio.run(sentinel.capture_single_snapshot(send_telegram=args.test_alert))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    async def _runner() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, sentinel.request_stop)
            except NotImplementedError:
                pass
        await sentinel.run_forever(send_startup_photo=args.send_startup_photo)

    asyncio.run(_runner())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
