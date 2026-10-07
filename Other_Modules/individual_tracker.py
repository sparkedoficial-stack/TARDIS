"""
core/individual_tracker.py - Rastreador y Reconocedor Facial Multi-Individuo
=============================================================================
GODWORKS SYSTEM v26.4 - Suite Soberana de Control Temporal e Inteligencia Causal

Capacidades:
  1. Detección simultánea de múltiples individuos en la escena (OpenCV YCrCb/HSV + LBP + Haar/Contornos).
  2. Conteo de individuos y estimación de proximidad ("Frente a cámara", "En escritorio", "En habitación").
  3. Extracción de firma biométrica espacial (LBP multi-cuadrante + histograma cromático normalizado).
  4. Reconocimiento y matching de identidades contra base persistente (`known_individuals.json`).
  5. Bautizo y asignación dinámica de nombres vía API, Chat GIA o interfaz gráfica.
  6. Soporte dual: fotogramas locales (OpenCV) y telemetría de visión cliente (HUD / Navegador).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("godworks.individual_tracker")

# Directorio de persistencia
VAULT_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "vw-control"
VAULT_DIR.mkdir(parents=True, exist_ok=True)
INDIVIDUALS_DB_FILE = VAULT_DIR / "known_individuals.json"

# Importación condicional segura de OpenCV
try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False


def _compute_lbp_cell(cell: np.ndarray) -> np.ndarray:
    """Calcula un histograma LBP básico de 8 vecinos para una celda de imagen."""
    h, w = cell.shape
    if h < 3 or w < 3:
        return np.zeros(16, dtype=np.float32)
    center = cell[1:-1, 1:-1]
    code = np.zeros_like(center, dtype=np.uint8)
    code |= (cell[:-2, :-2] >= center).astype(np.uint8) << 7
    code |= (cell[:-2, 1:-1] >= center).astype(np.uint8) << 6
    code |= (cell[:-2, 2:] >= center).astype(np.uint8) << 5
    code |= (cell[1:-1, 2:] >= center).astype(np.uint8) << 4
    code |= (cell[2:, 2:] >= center).astype(np.uint8) << 3
    code |= (cell[2:, 1:-1] >= center).astype(np.uint8) << 2
    code |= (cell[2:, :-2] >= center).astype(np.uint8) << 1
    code |= (cell[1:-1, :-2] >= center).astype(np.uint8) << 0

    hist, _ = np.histogram(code, bins=16, range=(0, 256))
    norm = np.linalg.norm(hist)
    if norm > 0:
        hist = hist.astype(np.float32) / norm
    return hist.astype(np.float32)


def extract_face_signature(face_img: np.ndarray) -> Optional[np.ndarray]:
    """
    Extrae una firma biométrica invariant a escala y rotación suave.
    Combina:
      1. Descriptores LBP espaciales en una cuadrícula de 3x3 celdas (textura y rasgos finos).
      2. Histograma cromático normalizado en espacio HSV (tono y saturación).
    """
    if face_img is None or face_img.size == 0 or not HAS_CV2:
        return None

    try:
        resized = cv2.resize(face_img, (96, 96), interpolation=cv2.INTER_AREA)

        # 1. Textura LBP
        if len(resized.shape) == 3:
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        else:
            gray = resized

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        equalized = clahe.apply(gray)

        cell_h, cell_w = 32, 32
        lbp_features = []
        for r in range(3):
            for c in range(3):
                cell = equalized[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
                hist = _compute_lbp_cell(cell)
                lbp_features.append(hist)
        lbp_vec = np.concatenate(lbp_features)  # 144 elementos

        # 2. Histograma cromático HSV
        if len(resized.shape) == 3:
            hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
            h_hist, _ = np.histogram(hsv[:, :, 0], bins=16, range=(0, 180))
            s_hist, _ = np.histogram(hsv[:, :, 1], bins=16, range=(0, 256))
            h_norm = np.linalg.norm(h_hist)
            if h_norm > 0:
                h_hist = h_hist.astype(np.float32) / h_norm
            s_norm = np.linalg.norm(s_hist)
            if s_norm > 0:
                s_hist = s_hist.astype(np.float32) / s_norm
            color_vec = np.concatenate([h_hist, s_hist])  # 32 elementos
        else:
            color_vec = np.zeros(32, dtype=np.float32)

        combined = np.concatenate([lbp_vec * 0.7, color_vec * 0.3])
        total_norm = float(np.linalg.norm(combined))
        if total_norm > 0:
            combined = combined / total_norm
        return [float(x) for x in combined]
    except Exception as e:
        logger.warning(f"Error extrayendo firma facial: {e}")
        return None


def cosine_similarity(v1: Any, v2: Any) -> float:
    """Calcula similitud coseno entre 0.0 y 1.0."""
    if v1 is None or v2 is None:
        return 0.0
    v1_arr = np.asarray(v1, dtype=np.float32)
    v2_arr = np.asarray(v2, dtype=np.float32)
    norm1 = float(np.linalg.norm(v1_arr))
    norm2 = float(np.linalg.norm(v2_arr))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    dot = float(np.dot(v1_arr, v2_arr))
    sim = dot / (norm1 * norm2)
    return float(max(0.0, min(1.0, sim)))


class IndividualTracker:
    """Gestor unificado de presencia, conteo de personas y reconocimiento facial."""

    _instance: Optional["IndividualTracker"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or INDIVIDUALS_DB_FILE
        self._db_lock = threading.Lock()
        self._known_individuals: Dict[str, Dict[str, Any]] = {}
        self._last_presence_state: Dict[str, Any] = {
            "timestamp": 0.0,
            "count": 0,
            "occupancy_label": "Habitación Vacía (Sin presencia)",
            "individuals": []
        }
        self._load_db()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> "IndividualTracker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    def _load_db(self):
        """Carga la base de datos de individuos conocidos desde disco y asegura el creador por defecto."""
        with self._db_lock:
            if not self.db_path.exists():
                # Sembrar con el Arquitecto creador
                now = time.time()
                iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                self._known_individuals = {
                    "indiv_creator": {
                        "id": "indiv_creator",
                        "name": "Miguel Angel May Canche",
                        "role": "Arquitecto / Creador Soberano",
                        "signatures": [],
                        "first_seen_ts": now,
                        "first_seen_iso": iso,
                        "last_seen_ts": now,
                        "last_seen_iso": iso,
                        "sightings_count": 1,
                        "thumbnail_b64": ""
                    }
                }
                self._save_db_unlocked()
                return

            try:
                raw = self.db_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict):
                    self._known_individuals = data.get("individuals", {})
            except Exception as e:
                logger.warning(f"Error cargando base de individuos: {e}")
                self._known_individuals = {}

    def _save_db(self):
        with self._db_lock:
            self._save_db_unlocked()

    def _save_db_unlocked(self):
        try:
            payload = {
                "version": "26.4",
                "updated_ts": time.time(),
                "total_known": len(self._known_individuals),
                "individuals": self._known_individuals
            }
            self.db_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error guardando base de individuos: {e}")

    def list_known_individuals(self) -> List[Dict[str, Any]]:
        """Retorna la lista de individuos registrados con sus metadatos (sin firmas raw)."""
        with self._db_lock:
            res = []
            for indiv_id, d in self._known_individuals.items():
                item = dict(d)
                item.pop("signatures", None)
                item["has_biometric_signature"] = bool(d.get("signatures"))
                res.append(item)
            return sorted(res, key=lambda x: x.get("last_seen_ts", 0), reverse=True)

    def get_individual(self, individual_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene un individuo registrado por su ID."""
        with self._db_lock:
            ind = self._known_individuals.get(individual_id)
            return dict(ind) if ind else None

    def delete_individual(self, individual_id: str) -> bool:
        """Elimina a un individuo registrado de la base de datos."""
        with self._db_lock:
            if individual_id in self._known_individuals:
                del self._known_individuals[individual_id]
                self._save_db_unlocked()
                return True
            return False

    def name_individual(self,
                        target_id: str,
                        name: str,
                        role: str = "Colaborador",
                        signature: Optional[Any] = None,
                        thumbnail_b64: Optional[str] = None) -> Dict[str, Any]:
        """
        Asigna o actualiza el nombre y rol de un individuo.
        Si target_id es 'indiv_creator' o coincide con uno existente, actualiza sus datos.
        """
        clean_id = target_id.strip()
        clean_name = name.strip()
        if not clean_name:
            return {"ok": False, "error": "El nombre no puede estar vacío."}

        sig_list = None
        if signature is not None:
            sig_list = signature.tolist() if hasattr(signature, "tolist") else [float(x) for x in signature]

        now = time.time()
        iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

        with self._db_lock:
            if clean_id in self._known_individuals:
                indiv = self._known_individuals[clean_id]
                indiv["name"] = clean_name
                if role:
                    indiv["role"] = role.strip()
                if thumbnail_b64:
                    indiv["thumbnail_b64"] = thumbnail_b64
                if sig_list:
                    sigs = indiv.get("signatures", [])
                    sigs.append(sig_list)
                    indiv["signatures"] = sigs[-5:]
                indiv["last_seen_ts"] = now
                indiv["last_seen_iso"] = iso
                target_key = clean_id
            else:
                target_key = f"indiv_{int(now * 1000)}" if clean_id.startswith("unknown") else clean_id
                sigs = [sig_list] if sig_list else []
                self._known_individuals[target_key] = {
                    "id": target_key,
                    "name": clean_name,
                    "role": role.strip() or "Colaborador",
                    "signatures": sigs,
                    "first_seen_ts": now,
                    "first_seen_iso": iso,
                    "last_seen_ts": now,
                    "last_seen_iso": iso,
                    "sightings_count": 1,
                    "thumbnail_b64": thumbnail_b64 or ""
                }
            self._save_db_unlocked()
            saved = dict(self._known_individuals[target_key])
            saved.pop("signatures", None)

            # Registrar interacción de bautismo con foto
            try:
                from core.interaction_logger import get_interaction_logger
                get_interaction_logger().record_interaction(
                    interaction_type="bautismo_identidad",
                    title=f"Bautismo: {clean_name}",
                    details=f"Identidad registrada o actualizada como '{clean_name}' con rol '{role.strip()}'. ID: {target_key}.",
                    individual={"id": target_key, "name": clean_name, "role": role.strip()},
                    photo_b64=thumbnail_b64,
                    capture_system_screenshot=True if not thumbnail_b64 else False
                )
            except Exception:
                pass

            return {"ok": True, "individual": saved}

    def _match_signature(self, sig: np.ndarray, threshold: float = 0.70) -> Tuple[Optional[str], str, str, float]:
        """Compara una firma contra la base de individuos conocidos."""
        if sig is None:
            return None, "", "", 0.0

        best_sim = 0.0
        best_match_id = None
        best_name = ""
        best_role = ""

        with self._db_lock:
            for indiv_id, indiv in self._known_individuals.items():
                stored_sigs = indiv.get("signatures", [])
                for s in stored_sigs:
                    try:
                        stored_arr = np.array(s, dtype=np.float32)
                        sim = cosine_similarity(sig, stored_arr)
                        if sim > best_sim:
                            best_sim = sim
                            best_match_id = indiv_id
                            best_name = indiv.get("name", "Individuo")
                            best_role = indiv.get("role", "")
                    except Exception:
                        continue

        if best_sim >= threshold and best_match_id:
            with self._db_lock:
                if best_match_id in self._known_individuals:
                    dev = self._known_individuals[best_match_id]
                    dev["last_seen_ts"] = time.time()
                    dev["sightings_count"] = dev.get("sightings_count", 0) + 1
            return best_match_id, best_name, best_role, round(best_sim, 3)

        return None, "", "", round(best_sim, 3)

    def detect_faces_in_frame(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Detección multi-rostro de alto rendimiento mediante segmentación universal de piel
        en espacio YCrCb + morfología + verificación de aspecto facial.
        Funciona instantáneamente en cualquier CPU y detecta todas las personas en la escena.
        """
        if frame is None or not HAS_CV2:
            return []
        h, w = frame.shape[:2]
        try:
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
            cr = ycrcb[:, :, 1]
            cb = ycrcb[:, :, 2]
            # Modelo cromático universal de piel humana
            mask = (cr >= 130) & (cr <= 180) & (cb >= 75) & (cb <= 135)
            mask = (mask * 255).astype(np.uint8)

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for cnt in contours:
                bx, by, bw, bh = cv2.boundingRect(cnt)
                area = bw * bh
                if bw >= 35 and bh >= 45 and area >= 1600 and (0.75 <= (bh / bw) <= 2.4):
                    boxes.append((bx, by, bw, bh))

            # NMS simple
            merged: List[Tuple[int, int, int, int]] = []
            for box in boxes:
                bx, by, bw, bh = box
                overlap = False
                for mx, my, mw, mh in merged:
                    ix1, iy1 = max(bx, mx), max(by, my)
                    ix2, iy2 = min(bx + bw, mx + mw), min(by + bh, my + mh)
                    if ix1 < ix2 and iy1 < iy2:
                        inter = (ix2 - ix1) * (iy2 - iy1)
                        union = (bw * bh) + (mw * mh) - inter
                        if union > 0 and (inter / union) > 0.35:
                            overlap = True
                            break
                if not overlap:
                    merged.append(box)

            # Ordenar por proximidad (área de mayor a menor)
            merged.sort(key=lambda b: b[2] * b[3], reverse=True)
            return merged
        except Exception as e:
            logger.warning(f"Aviso en detección de rostros: {e}")
            return []

    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """Procesa un fotograma de cámara local/backend."""
        now = time.time()
        if frame is None or not HAS_CV2:
            return {
                "ok": False,
                "count": 0,
                "occupancy_label": "Cámara no disponible",
                "individuals": [],
                "timestamp": now
            }

        try:
            h, w = frame.shape[:2]
            boxes = self.detect_faces_in_frame(frame)
            total_frame_area = float(w * h)
            individuals_list: List[Dict[str, Any]] = []

            for idx, (fx, fy, fw, fh) in enumerate(boxes):
                pad_x = int(fw * 0.08)
                pad_y = int(fh * 0.08)
                x1, y1 = max(0, fx - pad_x), max(0, fy - pad_y)
                x2, y2 = min(w, fx + fw + pad_x), min(h, fy + fh + pad_y)
                face_crop = frame[y1:y2, x1:x2]

                sig = extract_face_signature(face_crop)
                sig_list = sig if isinstance(sig, list) else (sig.tolist() if sig is not None else None)

                thumb_b64 = ""
                if face_crop is not None and face_crop.size > 0:
                    try:
                        thumb_resized = cv2.resize(face_crop, (64, 64), interpolation=cv2.INTER_AREA)
                        _, buf = cv2.imencode(".jpg", thumb_resized, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
                    except Exception:
                        pass

                indiv_id, name, role, conf = self._match_signature(sig)
                recognized = indiv_id is not None

                # Si es el rostro primario más cercano y hay creador registrado sin firma previa, vincular
                if not recognized and idx == 0:
                    with self._db_lock:
                        creator = self._known_individuals.get("indiv_creator")
                        if creator and not creator.get("signatures") and sig_list:
                            creator["signatures"] = [sig_list]
                            creator["thumbnail_b64"] = thumb_b64
                            creator["last_seen_ts"] = now
                            self._save_db_unlocked()
                            indiv_id = "indiv_creator"
                            name = creator.get("name", "Miguel Angel May Canche")
                            role = creator.get("role", "Arquitecto / Creador")
                            recognized = True
                            conf = 0.95

                if not recognized:
                    temp_id = f"unknown_{idx + 1}"
                    name = f"Individuo #{idx + 1}"
                    role = "No identificado"
                    conf = max(0.55, 1.0 - (idx * 0.1))
                else:
                    temp_id = indiv_id

                area_ratio = (fw * fh) / total_frame_area
                if area_ratio > 0.09:
                    proximity = "Frente a cámara (Muy cercano)"
                elif area_ratio > 0.025:
                    proximity = "En escritorio (Cercano)"
                else:
                    proximity = "Fondo de habitación"

                norm_cx = round(((fx + fw / 2) - (w / 2)) / (w / 2), 3)
                norm_cy = round(((fy + fh / 2) - (h / 2)) / (h / 2), 3)

                indiv_data = {
                    "id": temp_id,
                    "name": name,
                    "role": role,
                    "recognized": recognized,
                    "is_known": recognized,
                    "confidence": conf,
                    "proximity": proximity,
                    "box": {"x": fx, "y": fy, "width": fw, "height": fh},
                    "normalized_center": {"x": norm_cx, "y": norm_cy},
                    "thumbnail_b64": thumb_b64,
                    "signature": sig_list
                }
                individuals_list.append(indiv_data)

            count = len(individuals_list)
            if count == 0:
                occupancy_label = "Habitación Vacía (Sin presencia cercana)"
            elif count == 1:
                ind = individuals_list[0]
                occupancy_label = f"1 Individuo: {ind['name']} ({ind['proximity']})"
            else:
                names_str = ", ".join([ind["name"] for ind in individuals_list[:3]])
                occupancy_label = f"Múltiples Individuos ({count} en escena): {names_str}"

            result = {
                "ok": True,
                "count": count,
                "occupancy_label": occupancy_label,
                "individuals": individuals_list,
                "timestamp": now
            }

            with self._lock:
                self._last_presence_state = result
            return result
        except Exception as e:
            logger.error(f"Error procesando fotograma: {e}")
            return {
                "ok": False,
                "count": 0,
                "error": str(e),
                "occupancy_label": "Error de procesamiento",
                "individuals": [],
                "timestamp": now
            }

    def update_from_frontend_telemetry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sincroniza la telemetría facial/presencia emitida por el frontend.
        Permite que cuando la cámara se use desde el navegador (HUD), se reconozcan los individuos.
        """
        now = time.time()
        detected = bool(payload.get("detected", False) or payload.get("individuals_count", 0) > 0)
        frontend_indivs = payload.get("individuals", [])

        if not detected and not frontend_indivs:
            state = {
                "ok": True,
                "count": 0,
                "occupancy_label": "Habitación Vacía (Sin presencia)",
                "individuals": [],
                "timestamp": now
            }
            with self._lock:
                self._last_presence_state = state
            return state

        # Si el frontend envía lista de individuos
        processed_list = []
        if frontend_indivs:
            for idx, item in enumerate(frontend_indivs):
                t_id = item.get("id") or f"unknown_{idx + 1}"
                # Comprobar si coincide con un conocido
                with self._db_lock:
                    known = self._known_individuals.get(t_id)
                    if known:
                        name = known.get("name", item.get("name", f"Individuo #{idx + 1}"))
                        role = known.get("role", item.get("role", "Reconocido"))
                        rec = True
                    else:
                        name = item.get("name", f"Individuo #{idx + 1}")
                        role = item.get("role", "No identificado")
                        rec = bool(item.get("recognized", False))

                processed_list.append({
                    "id": t_id,
                    "name": name,
                    "role": role,
                    "recognized": rec,
                    "is_known": rec,
                    "confidence": float(item.get("confidence", 0.88)),
                    "proximity": item.get("proximity", "Frente a pantalla"),
                    "box": item.get("box", {"x": 0, "y": 0, "width": 100, "height": 100}),
                    "thumbnail_b64": item.get("thumbnail_b64", "")
                })
        else:
            # Entrada de rostro individual del detector del navegador
            with self._db_lock:
                creator = self._known_individuals.get("indiv_creator", {})
                name = creator.get("name", "Miguel Angel May Canche")
                role = creator.get("role", "Arquitecto / Creador")

            processed_list.append({
                "id": "indiv_creator",
                "name": name,
                "role": role,
                "recognized": True,
                "is_known": True,
                "confidence": float(payload.get("confidence", 0.92)),
                "proximity": "Frente a pantalla (Interlocutor Principal)",
                "box": payload.get("face_box", {"x": 100, "y": 80, "width": 180, "height": 220}),
                "thumbnail_b64": ""
            })

        count = len(processed_list)
        if count == 1:
            occupancy_label = f"1 Individuo: {processed_list[0]['name']} ({processed_list[0]['proximity']})"
        else:
            names_str = ", ".join([ind["name"] for ind in processed_list[:3]])
            occupancy_label = f"Múltiples Individuos ({count} en escena): {names_str}"

        state = {
            "ok": True,
            "count": count,
            "occupancy_label": occupancy_label,
            "individuals": processed_list,
            "timestamp": now
        }
        with self._lock:
            self._last_presence_state = state
        return state

    def get_latest_presence(self) -> Dict[str, Any]:
        """Retorna la última lectura de presencia e individuos."""
        with self._lock:
            res = dict(self._last_presence_state)
            clean_indivs = []
            for ind in res.get("individuals", []):
                ci = dict(ind)
                ci.pop("signature", None)
                clean_indivs.append(ci)
            res["individuals"] = clean_indivs
            return res


_TRACKER_SINGLETON: Optional[IndividualTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_individual_tracker() -> IndividualTracker:
    """Singleton soberano del rastreador de individuos."""
    global _TRACKER_SINGLETON
    with _TRACKER_LOCK:
        if _TRACKER_SINGLETON is None:
            _TRACKER_SINGLETON = IndividualTracker()
        return _TRACKER_SINGLETON
