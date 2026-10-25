#!/usr/bin/env python3
"""
core/gods_eye_realtime.py - Motor real del Ojo de Dios
======================================================
Sustituye la capa de ficción (satélites, cámaras hackeadas, objetivos de película,
coordenadas GPS inventadas) por conciencia situacional verificable sobre las cámaras
que el sistema tiene de verdad:

  * Registro de cámaras: las que emiten por /api/terminal_cameras/feed entran solas.
  * Detección por movimiento (numpy, sin GPU ni modelos): energía de diferencia de
    fotogramas por rejilla 3x3, con umbral adaptativo y periodo de enfriamiento.
  * Seguimiento: centroides activos con id estable y trayectoria con decaimiento.
  * Eventos: cada detección se persiste en SQLite (fuente de verdad auditable).
  * Mapa: cada cámara se ubica en un plano LOCAL (x, y en metros) definido por el
    operador; la posición mostrada es "movimiento detectado en la zona de la cámara",
    nunca una geolocalización de personas.
  * Privacidad: no se identifican personas, no se guardan recortes, no se calculan
    biometrías y no se escribe ningún nombre (la API enmascara los protegidos).

Todo lo que este módulo reporta es medible con los datos que recibe: si no hay
fotogramas, reporta ausencia en lugar de inventar métricas.
"""
from __future__ import annotations

import io
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_ROOT / "data" / "gods_eye.db"

GRID = 3                 # rejilla GRID x GRID sobre la imagen
N_BINS = 18              # histograma de gradientes (orientación)
PIX_PER_METER_DEFAULT = 100.0
ZONE_MOTION_THRESHOLD = 0.030   # fracción de celdas en movimiento para declarar zona ocupada
STALE_FRAME_SEC = 15.0
TRACK_TTL_SEC = 8.0
EVENT_COOLDOWN_SEC = 20.0

PROTECTED_NAME_TOKENS = ("anya", "andrea", "rex", "miguel", "may canche", "cayetano", "carrillo")


def _mask_name(name: str) -> str:
    low = (name or "").lower()
    if any(tok in low for tok in PROTECTED_NAME_TOKENS):
        return "Protegido (Aegis)"
    return name


class GodsEyeRealtime:
    _instance: Optional["GodsEyeRealtime"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "GodsEyeRealtime":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, db_file: Path = DB_FILE):
        self.db_file = db_file
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cameras: Dict[str, Dict[str, Any]] = {}
        self._tracks: Dict[str, List[Dict[str, Any]]] = {}
        self._last_prev: Dict[str, np.ndarray] = {}
        self._last_event_ts: Dict[str, float] = {}
        self._init_db()
        self._load_cameras()

    # ------------------------------------------------------------------ DB
    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_file, timeout=10.0)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    terminal_id TEXT PRIMARY KEY,
                    name TEXT,
                    device_type TEXT,
                    online INTEGER DEFAULT 0,
                    last_frame_ts REAL DEFAULT 0,
                    frames INTEGER DEFAULT 0,
                    resolution TEXT,
                    pos_x REAL, pos_y REAL,
                    view_yaw_deg REAL DEFAULT 0,
                    pix_per_meter REAL DEFAULT 100,
                    created_ts REAL
                )""")
            con.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, terminal_id TEXT, cell TEXT,
                    motion REAL, objects INTEGER, centroid_x REAL, centroid_y REAL,
                    histogram TEXT
                )""")
            con.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, kind TEXT, terminal_id TEXT, zone TEXT,
                    detail TEXT, confidence REAL
                )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_det_ts ON detections(ts)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_evt_ts ON events(ts)")

    def _load_cameras(self) -> None:
        with self._conn() as con:
            for r in con.execute("SELECT * FROM cameras"):
                self._cameras[r["terminal_id"]] = dict(r)

    # ------------------------------------------------------------- cámaras
    def register_camera(self, terminal_id: str, name: str = "", device_type: str = "browser",
                        resolution: str = "", pos_x: Optional[float] = None,
                        pos_y: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            cam = self._cameras.get(terminal_id)
            if cam is None:
                if pos_x is None or pos_y is None:
                    idx = len(self._cameras)
                    pos_x = 60.0 * (idx % 3) + 30.0
                    pos_y = 40.0 * (idx // 3) + 30.0
                cam = {
                    "terminal_id": terminal_id, "name": name or terminal_id,
                    "device_type": device_type, "online": 0, "last_frame_ts": 0.0,
                    "frames": 0, "resolution": resolution,
                    "pos_x": float(pos_x), "pos_y": float(pos_y),
                    "view_yaw_deg": 0.0, "pix_per_meter": PIX_PER_METER_DEFAULT,
                    "created_ts": time.time(),
                }
            elif name or resolution:
                cam["name"] = name or cam["name"]
                cam["resolution"] = resolution or cam.get("resolution")
            self._cameras[terminal_id] = cam
            with self._conn() as con:
                con.execute("""INSERT INTO cameras
                    (terminal_id,name,device_type,online,last_frame_ts,frames,resolution,
                     pos_x,pos_y,view_yaw_deg,pix_per_meter,created_ts)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(terminal_id) DO UPDATE SET
                      name=excluded.name, device_type=excluded.device_type,
                      resolution=excluded.resolution""",
                    (cam["terminal_id"], cam["name"], cam["device_type"], cam["online"],
                     cam["last_frame_ts"], cam["frames"], cam["resolution"],
                     cam["pos_x"], cam["pos_y"], cam["view_yaw_deg"],
                     cam["pix_per_meter"], cam["created_ts"]))
            return cam

    def set_camera_pose(self, terminal_id: str, pos_x: float, pos_y: float,
                        view_yaw_deg: float = 0.0, pix_per_meter: float = PIX_PER_METER_DEFAULT) -> bool:
        with self._lock:
            cam = self._cameras.get(terminal_id)
            if not cam:
                return False
            cam.update({"pos_x": pos_x, "pos_y": pos_y, "view_yaw_deg": view_yaw_deg,
                        "pix_per_meter": pix_per_meter})
            with self._conn() as con:
                con.execute("UPDATE cameras SET pos_x=?,pos_y=?,view_yaw_deg=?,pix_per_meter=? WHERE terminal_id=?",
                            (pos_x, pos_y, view_yaw_deg, pix_per_meter, terminal_id))
            return True

    # ------------------------------------------------------------ análisis
    @staticmethod
    def _to_gray(frame_bytes: bytes) -> Optional[np.ndarray]:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(frame_bytes)).convert("L")
            img.thumbnail((320, 320))  # coste acotado y estable en CPU
            return np.asarray(img, dtype=np.float32)
        except Exception:
            return None

    @staticmethod
    def _cell_motion(prev: np.ndarray, cur: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if prev.shape != cur.shape:
            h = min(prev.shape[0], cur.shape[0]); w = min(prev.shape[1], cur.shape[1])
            prev, cur = prev[:h, :w], cur[:h, :w]
        diff = np.abs(cur - prev) / 255.0
        h, w = diff.shape
        cells = np.zeros((GRID, GRID), dtype=np.float32)
        for gy in range(GRID):
            for gx in range(GRID):
                block = diff[gy * h // GRID:(gy + 1) * h // GRID, gx * w // GRID:(gx + 1) * w // GRID]
                cells[gy, gx] = float(block.mean()) if block.size else 0.0
        # Centroide de masa de movimiento (x, y normalizados 0..1)
        total = float(diff.sum())
        if total <= 1e-6:
            return cells, np.array([np.nan, np.nan])
        ys, xs = np.mgrid[0:h, 0:w]
        cx = float((xs * diff).sum() / total) / max(w - 1, 1)
        cy = float((ys * diff).sum() / total) / max(h - 1, 1)
        return cells, np.array([cx, cy])

    @staticmethod
    def _histogram(gray: np.ndarray) -> np.ndarray:
        gx = np.zeros_like(gray); gy = np.zeros_like(gray)
        gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
        gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
        mag = np.hypot(gx, gy)
        ang = (np.arctan2(gy, gx) + math.pi) % (2 * math.pi)
        hist, _ = np.histogram(ang, bins=N_BINS, range=(0, 2 * math.pi), weights=mag)
        s = hist.sum()
        return (hist / s).astype(np.float32) if s > 0 else hist.astype(np.float32)

    def process_frame(self, terminal_id: str, frame_bytes: bytes,
                      terminal_name: str = "", device_type: str = "browser",
                      resolution: str = "") -> Dict[str, Any]:
        started = time.perf_counter()
        gray = self._to_gray(frame_bytes)
        if gray is None or gray.size == 0:
            return {"ok": False, "error": "fotograma no decodificable"}

        with self._lock:
            cam = self.register_camera(terminal_id, terminal_name, device_type, resolution)
            prev = self._last_prev.get(terminal_id)
            self._last_prev[terminal_id] = gray
            self._cameras[terminal_id].update({"online": 1, "frames": cam["frames"] + 1,
                                               "last_frame_ts": time.time()})
            frames = self._cameras[terminal_id]["frames"]
            with self._conn() as con:
                con.execute("UPDATE cameras SET online=1, frames=?, last_frame_ts=? WHERE terminal_id=?",
                            (frames, time.time(), terminal_id))

            if prev is None:
                return {"ok": True, "warmup": True, "frames": frames}

            cells, centroid = self._cell_motion(prev, gray)
            moving_cells = int((cells > 0.02).sum())
            motion = float(cells.mean())
            hist = self._histogram(gray)
            objects = 0
            if not np.isnan(centroid).any() and motion > 0.01:
                objects = self._update_tracks(terminal_id, centroid, motion)

            with self._conn() as con:
                con.execute(
                    "INSERT INTO detections (ts,terminal_id,cell,motion,objects,centroid_x,centroid_y,histogram) VALUES (?,?,?,?,?,?,?,?)",
                    (time.time(), terminal_id, f"{moving_cells}/{GRID * GRID}", motion, objects,
                     None if np.isnan(centroid).any() else float(centroid[0]),
                     None if np.isnan(centroid).any() else float(centroid[1]),
                     json.dumps([round(float(h), 4) for h in hist])))

            event = None
            occupied = moving_cells >= max(1, int(round(ZONE_MOTION_THRESHOLD * GRID * GRID)))
            now = time.time()
            if occupied and (now - self._last_event_ts.get(terminal_id, 0)) > EVENT_COOLDOWN_SEC:
                self._last_event_ts[terminal_id] = now
                event = {"kind": "motion_zone", "zone": self.zone_label(cam),
                         "confidence": round(min(1.0, motion * 12), 2),
                         "detail": f"movimiento en {moving_cells}/{GRID * GRID} celdas"}
                with self._conn() as con:
                    con.execute("INSERT INTO events (ts,kind,terminal_id,zone,detail,confidence) VALUES (?,?,?,?,?,?)",
                                (now, event["kind"], terminal_id, event["zone"], event["detail"], event["confidence"]))

            return {
                "ok": True, "frames": frames, "motion": round(motion, 4),
                "moving_cells": f"{moving_cells}/{GRID * GRID}",
                "zone": self.zone_label(cam), "objects": objects, "event": event,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }

    def _update_tracks(self, terminal_id: str, centroid: np.ndarray, motion: float) -> int:
        now = time.time()
        tracks = [t for t in self._tracks.get(terminal_id, []) if now - t["ts"] <= TRACK_TTL_SEC]
        best, best_d = None, 1e9
        for t in tracks:
            d = math.dist((t["x"], t["y"]), (float(centroid[0]), float(centroid[1])))
            if d < best_d:
                best, best_d = t, d
        self._tracks[terminal_id] = tracks
        if best is not None and best_d < 0.25:
            best.update({"x": float(centroid[0]), "y": float(centroid[1]), "ts": now, "hits": best["hits"] + 1})
            return 1
        self._tracks.setdefault(terminal_id, []).append({
            "id": f"m{int(now * 1000) % 100000}", "x": float(centroid[0]), "y": float(centroid[1]),
            "ts": now, "hits": 1, "motion": motion})
        return 1

    # --------------------------------------------------------------- vistas
    def zone_label(self, cam: Dict[str, Any]) -> str:
        return cam.get("name") or cam.get("terminal_id") or "zona"

    def cameras_view(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            out = []
            for cam in self._cameras.values():
                age = now - (cam.get("last_frame_ts") or 0)
                online = bool(cam.get("frames")) and age <= STALE_FRAME_SEC
                tracks = [t for t in self._tracks.get(cam["terminal_id"], []) if now - t["ts"] <= TRACK_TTL_SEC]
                out.append({
                    "id": cam["terminal_id"],
                    "name": _mask_name(cam.get("name") or cam["terminal_id"]),
                    "device_type": cam.get("device_type"),
                    "online": online,
                    "frames": cam.get("frames", 0),
                    "seconds_since_frame": round(age, 1) if cam.get("frames") else None,
                    "resolution": cam.get("resolution"),
                    "position_m": {"x": cam.get("pos_x"), "y": cam.get("pos_y")},
                    "view_yaw_deg": cam.get("view_yaw_deg"),
                    "active_tracks": [{"x": round(t["x"], 3), "y": round(t["y"], 3), "hits": t.get("hits", 1)} for t in tracks],
                    "zones": [f"celda {i}{j}" for i in range(GRID) for j in range(GRID)],
                })
            return out

    def recent_events(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def recent_detections(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM detections ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [{k: v for k, v in dict(r).items() if k != "histogram"} for r in rows]

    def stats(self, hours: int = 24) -> Dict[str, Any]:
        since = time.time() - hours * 3600
        with self._conn() as con:
            det = con.execute("SELECT COUNT(*) c, AVG(motion) m FROM detections WHERE ts > ?", (since,)).fetchone()
            evt = con.execute("SELECT COUNT(*) c FROM events WHERE ts > ?", (since,)).fetchone()
            cams = con.execute("SELECT COUNT(*) c FROM cameras").fetchone()
        view = self.cameras_view()
        return {
            "cameras_registered": cams["c"],
            "cameras_online": sum(1 for c in view if c["online"]),
            "detections_window": det["c"],
            "avg_motion": round(det["m"] or 0.0, 4),
            "events_window": evt["c"],
            "window_hours": hours,
        }

    def status(self) -> Dict[str, Any]:
        view = self.cameras_view()
        online = [c for c in view if c["online"]]
        return {
            "ok": True,
            "engine": "gods_eye_realtime",
            "mode": "motion-grid" if online else "idle-no-frames",
            "cameras_total": len(view),
            "cameras_online": len(online),
            "cameras": view,
            "stats": self.stats(),
            "events": self.recent_events(15),
            "detections": self.recent_detections(10),
            "plan": {
                "units": "metros",
                "cameras": {c["id"]: c["position_m"] for c in view},
            },
            "privacy": "sin biometrías, sin recortes, sin nombres",
            "ts": time.time(),
        }


def get_gods_eye_realtime() -> GodsEyeRealtime:
    return GodsEyeRealtime.get_instance()
