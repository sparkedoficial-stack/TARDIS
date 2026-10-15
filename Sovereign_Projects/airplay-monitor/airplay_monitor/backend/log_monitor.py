"""
Módulo de Monitoreo de Registros y Telemetría en Tiempo Real
Captura el flujo de eventos de UxPlay mediante journalctl y rastrea el estado de las conexiones.
"""
from __future__ import annotations

import collections
import re
import subprocess
import threading
import time
from datetime import datetime


class AirPlayLogMonitor:
    """Escucha la salida de journalctl de uxplay-airplay.service y emite eventos."""

    REQ_RE = re.compile(r"connection request from (?P<name>.+) \((?P<model>.+)\) with deviceID = (?P<deviceid>[0-9A-Fa-f:]+)")
    REMOTE_RE = re.compile(r"Remote:\s+(?P<ip>\S+)")
    AGENT_RE = re.compile(r"User-Agent:\s+(?P<agent>\S+)")
    MIRROR_START_RE = re.compile(r"raop_rtp_mirror starting mirroring")
    MIRROR_STOP_RE = re.compile(r"(raop_rtp_mirror stopping mirroring|Stopping RAOP Server|connection to :0 broken|client silence|reset after)")
    AUDIO_START_RE = re.compile(r"raop_rtp_audio")
    STREAM_DIMS_RE = re.compile(r"begin video stream wxh = (?P<w>\d+)x(?P<h>\d+); source (?P<sw>\d+)x(?P<sh>\d+)")
    FPS_DATA_RE = re.compile(r"(?P<fps>\d+(?:\.\d+)?)\s*(?:fps|frames/s)", re.IGNORECASE)
    HLS_START_RE = re.compile(r"(Connection type HLS|play HLS streamed video|hls_playbin)", re.IGNORECASE)

    def __init__(self, max_lines: int = 1000):
        self.max_lines = max_lines
        self.logs: collections.deque[dict] = collections.deque(maxlen=max_lines)
        self.active_client: dict | None = None
        self.session_history: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None

        # Callbacks
        self.on_log_callbacks = []
        self.on_connection_callbacks = []

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    def add_log_callback(self, cb):
        self.on_log_callbacks.append(cb)

    def add_connection_callback(self, cb):
        self.on_connection_callbacks.append(cb)

    def get_logs(self) -> list[dict]:
        return list(self.logs)

    def get_active_client(self) -> dict | None:
        return self.active_client

    def _worker(self):
        # Primero leer las últimas 40 líneas existentes para capturar estado previo
        try:
            init_res = subprocess.run(
                ["journalctl", "--user", "-u", "uxplay-airplay.service", "-n", "40", "--no-pager"],
                capture_output=True, text=True
            )
            for line in init_res.stdout.splitlines():
                self._parse_line(line, emit=False)
        except Exception:
            pass

        # Luego streamear en vivo
        while self._running:
            try:
                self._process = subprocess.Popen(
                    ["journalctl", "--user", "-u", "uxplay-airplay.service", "-f", "-n", "0", "--output=short-iso"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1
                )

                for line in iter(self._process.stdout.readline, ""):
                    if not self._running:
                        break
                    line = line.strip()
                    if line:
                        self._parse_line(line, emit=True)

            except Exception:
                time.sleep(2)

    def _parse_line(self, line: str, emit: bool = True):
        now_str = datetime.now().strftime("%H:%M:%S")
        entry = {
            "timestamp": now_str,
            "raw": line,
            "level": "info"
        }

        # Detectar nivel
        lower = line.lower()
        if "error" in lower or "failed" in lower or "broken" in lower:
            entry["level"] = "error"
        elif "starting" in lower or "accepted" in lower or "connected" in lower:
            entry["level"] = "success"
        elif "stopping" in lower or "stopped" in lower:
            entry["level"] = "warning"

        self.logs.append(entry)

        # Parsear eventos de conexión
        m_dev = self.REQ_RE.search(line)
        if m_dev:
            name = m_dev.group("name")
            model = m_dev.group("model")
            deviceid = m_dev.group("deviceid")
            self.active_client = {
                "name": name,
                "model": model,
                "device_id": deviceid,
                "connected_at": now_str,
                "mode": "Conectando...",
                "ip": "Desconocida",
                "agent": "AirPlay"
            }
            if emit:
                self._notify_connection()

        m_rem = self.REMOTE_RE.search(line)
        if m_rem and self.active_client:
            self.active_client["ip"] = m_rem.group("ip")
            if emit:
                self._notify_connection()

        m_agent = self.AGENT_RE.search(line)
        if m_agent and self.active_client:
            self.active_client["agent"] = m_agent.group("agent")
            if emit:
                self._notify_connection()

        m_dims = self.STREAM_DIMS_RE.search(line)
        if m_dims:
            w = int(m_dims.group('w'))
            h = int(m_dims.group('h'))
            orientation = "Horizontal (Panorámica 16:9)" if w >= h else "Vertical (Retrato)"
            if not self.active_client:
                self.active_client = {
                    "name": "Dispositivo AirPlay",
                    "model": "Apple Device",
                    "device_id": "-",
                    "connected_at": now_str,
                    "mode": "Mirroring Activo",
                    "ip": "Local",
                    "agent": "AirPlay",
                }
            self.active_client["stream_res"] = f"{w}x{h}"
            self.active_client["source_res"] = f"{m_dims.group('sw')}x{m_dims.group('sh')}"
            self.active_client["orientation"] = orientation
            if emit:
                self._notify_connection()

        m_fps = self.FPS_DATA_RE.search(line)
        if m_fps and self.active_client:
            self.active_client["live_fps"] = f"{m_fps.group('fps')} FPS"
            if emit:
                self._notify_connection()

        if self.HLS_START_RE.search(line):
            if not self.active_client:
                self.active_client = {
                    "name": "Dispositivo AirPlay",
                    "model": "Apple Device",
                    "device_id": "-",
                    "connected_at": now_str,
                    "mode": "🎬 Video Directo a Pantalla Completa (Modo Monitor)",
                    "ip": "Local",
                    "agent": "AirPlay HLS"
                }
            else:
                self.active_client["mode"] = "🎬 Video Directo a Pantalla Completa (Modo Monitor)"
            if emit:
                self._notify_connection()

        if self.MIRROR_START_RE.search(line):
            if not self.active_client:
                self.active_client = {
                    "name": "Dispositivo AirPlay",
                    "model": "Apple Device",
                    "device_id": "-",
                    "connected_at": now_str,
                    "mode": "Duplicando Pantalla (Mirroring Activo)",
                    "ip": "Local",
                    "agent": "AirPlay"
                }
            else:
                self.active_client["mode"] = "Duplicando Pantalla (Mirroring Activo)"
            if emit:
                self._notify_connection()

        elif self.AUDIO_START_RE.search(line):
            if self.active_client:
                self.active_client["mode"] = "Transmitiendo Audio (AirTunes)"
            if emit:
                self._notify_connection()

        elif self.MIRROR_STOP_RE.search(line):
            if self.active_client:
                self.active_client["disconnected_at"] = now_str
                self.session_history.append(self.active_client.copy())
                self.active_client = None
                if emit:
                    self._notify_connection()

        if emit:
            for cb in self.on_log_callbacks:
                try:
                    cb(entry)
                except Exception:
                    pass

    def _notify_connection(self):
        for cb in self.on_connection_callbacks:
            try:
                cb(self.active_client)
            except Exception:
                pass
