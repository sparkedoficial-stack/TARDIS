"""
telemetry/camera_grabber.py - Captura Persistente de Cámara en Memoria (0ms V4L2 Overhead)
Mantiene un hilo dedicado con búfer en memoria RAM. Evita abrir/cerrar /dev/video0 continuamente.
"""
from __future__ import annotations
import os
import sys
import threading
import time
from typing import Optional, Tuple
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None


class PersistentCameraGrabber:
    _instance: Optional[PersistentCameraGrabber] = None
    _lock = threading.Lock()

    def __init__(self, camera_index: int = 0, target_fps: int = 5, idle_timeout: int = 30):
        self.camera_index = camera_index
        self.target_fps = max(1, min(target_fps, 30))
        self.idle_timeout = max(5, idle_timeout)

        self._cap = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._last_accessed: float = 0.0
        self._is_active = False

    @classmethod
    def get_instance(cls, camera_index: int = 0) -> PersistentCameraGrabber:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(camera_index=camera_index)
            return cls._instance

    def _get_backend(self):
        if not HAS_CV2:
            return 0
        if sys.platform == "win32":
            return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
        return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)

    def _open_device(self) -> bool:
        if not HAS_CV2:
            return False
        if sys.platform.startswith("linux") and not os.path.exists(f"/dev/video{self.camera_index}"):
            return False
        try:
            backend = self._get_backend()
            cap = cv2.VideoCapture(self.camera_index, backend)
            if cap and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self._cap = cap
                self._is_active = True
                return True
        except Exception:
            pass
        self._cap = None
        self._is_active = False
        return False

    def _close_device(self):
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._is_active = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._last_accessed = time.time()
        self._thread = threading.Thread(target=self._loop, name="GIA_CameraGrabberThread", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._close_device()

    def _loop(self):
        interval = 1.0 / self.target_fps
        while self._running:
            now = time.time()
            # Si nadie ha pedido un frame en idle_timeout segundos, cerrar el dispositivo para ahorrar energía
            if self._is_active and (now - self._last_accessed > self.idle_timeout):
                self._close_device()

            if not self._is_active:
                time.sleep(0.5)
                continue

            if self._cap is None:
                if not self._open_device():
                    time.sleep(2.0)
                    continue

            ok, frame = self._cap.read()
            if ok and frame is not None:
                with self._frame_lock:
                    self._latest_frame = frame
                    self._latest_ts = time.time()
            else:
                # Dispositivo desconectado o error temporal
                self._close_device()
                time.sleep(1.0)

            time.sleep(interval)

    def get_latest_frame(self) -> Tuple[bool, Optional[np.ndarray], float]:
        """
        Retorna (ok, frame_bgr, timestamp).
        Si la cámara estaba en reposo (idle), la reactiva de inmediato.
        """
        self._last_accessed = time.time()

        if not self._running:
            self.start()

        if not self._is_active:
            # Reactivar dispositivo bajo demanda
            if self._open_device():
                # Capturar 1 frame inicial para refrescar
                ok, frame = self._cap.read()
                if ok and frame is not None:
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._latest_ts = time.time()

        with self._frame_lock:
            if self._latest_frame is not None:
                return True, self._latest_frame.copy(), self._latest_ts

        return False, None, 0.0


def get_camera_grabber(camera_index: int = 0) -> PersistentCameraGrabber:
    grabber = PersistentCameraGrabber.get_instance(camera_index)
    if not grabber._running:
        grabber.start()
    return grabber
