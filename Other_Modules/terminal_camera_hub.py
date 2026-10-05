"""
core/terminal_camera_hub.py - Hub Centralizado de Cámaras Multi-Terminal (CCTV & Vision Matrix)
=============================================================================================
Gestiona la recepción, registro, persistencia en memoria y streaming en vivo de los flujos de
video y cámaras de todas las terminales cliente conectadas a GODWORKS SYSTEM v26.4
(celulares iPhone/Android, iPads, laptops remotas y la cámara V4L2 local del servidor).
Calidad de imagen: 720p HD (1280x720) a una tasa de bits objetivo de 1000 kbps (1 Mbps).
Soporte completo para terminales conectadas vía Internet (Cloudflare Tunnel) y Red Local (LAN).
"""

from __future__ import annotations

import base64
import io
import ipaddress
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("GODWORKS.TerminalCameraHub")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTURES_DIR = PROJECT_ROOT / "data" / "terminal_captures"


def classify_network_origin(ip: str) -> str:
    """Clasifica el origen de la conexión de red: HOST (local), LAN (red interna) o INTERNET (túnel público)."""
    if not ip or ip in ("REDACTED_IP", "localhost", "::1"):
        return "HOST"
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_loopback:
            return "HOST"
        # LAN estándar: RFC 1918 (REDACTED_IP/8, REDACTED_IP/12, REDACTED_IP/16), Link-Local (REDACTED_IP/16) o ULA IPv6
        if ip_obj.version == 4:
            if (
                ip_obj in ipaddress.ip_network("REDACTED_IP/8")
                or ip_obj in ipaddress.ip_network("REDACTED_IP/12")
                or ip_obj in ipaddress.ip_network("REDACTED_IP/16")
                or ip_obj in ipaddress.ip_network("REDACTED_IP/16")
            ):
                return "LAN"
        elif ip_obj.version == 6:
            if ip_obj.is_link_local or ip_obj in ipaddress.ip_network("fc00::/7"):
                return "LAN"
        return "INTERNET"
    except Exception:
        return "INTERNET"


class TerminalCameraHub:
    """Hub centralizado de recepción, multiplexación y análisis de cámaras multi-terminal."""

    _instance: Optional["TerminalCameraHub"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TerminalCameraHub":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.Lock()
        self._terminals: Dict[str, Dict[str, Any]] = {}
        self._last_fps_calc: Dict[str, List[float]] = {}
        self._bitrate_calc: Dict[str, List[Tuple[float, int]]] = {}
        self._alerted_terminals: Set[str] = set()
        self._new_terminal_callbacks: List[Callable[[str, str, str, str], None]] = []
        
        # Registrar terminal local del servidor por defecto en 720p
        self._register_local_server_node()

    def _register_local_server_node(self) -> None:
        """Inicializa el feed de la cámara anfitriona (ASUS TUF Host) en 720p @ 1000 kbps."""
        now = time.time()
        self._terminals["host_local_tardis"] = {
            "terminal_id": "host_local_tardis",
            "terminal_name": "Servidor Central (ASUS TUF Host)",
            "device_type": "host_server",
            "client_ip": "REDACTED_IP",
            "origin": "HOST",
            "country": "LOCAL",
            "user_agent": "GODWORKS Core Daemon (Linux x86_64)",
            "last_seen": now,
            "fps": 10.0,
            "bitrate_kbps": 1000.0,
            "resolution": "1280x720",
            "latest_frame_bytes": None,
            "latest_frame_b64": "",
            "biometrics": {
                "faces_count": 0,
                "primary": "neutral",
                "mood_state": "Soberano Activo"
            },
            "is_active": True,
            "is_online": True,
            "is_host": True,
            "target_bitrate_kbps": 1000,
            "quality_profile": "720p HD @ 1000 kbps"
        }
        self._alerted_terminals.add("host_local_tardis")

    def _generate_placeholder_frame(self, text: str = "ESPERANDO TRANSMISIÓN 720p...") -> bytes:
        """Genera un fotograma JPEG sintético 720p (1280x720) con estilo TARDIS cuando una cámara no transmite."""
        img = Image.new("RGB", (1280, 720), color=(8, 16, 28))
        draw = ImageDraw.Draw(img)

        # Marco holográfico exterior e interior
        draw.rectangle([(16, 16), (1263, 703)], outline=(0, 212, 200), width=2)
        draw.rectangle([(24, 24), (1255, 695)], outline=(0, 70, 90), width=1)

        # Encabezado técnico
        header = "GODWORKS SYSTEM v26.4 · MATRIZ CCTV 720p @ 1000 KBPS"
        draw.text((40, 40), header, fill=(0, 240, 255))
        draw.text((40, 68), f"HORA: {time.strftime('%Y-%m-%d %H:%M:%S')} · PROTOCOLO: MJPEG MULTIPART SOBERANO", fill=(100, 180, 200))
        
        # Glifo temporal centrado
        draw.text((620, 260), "Ψ", fill=(0, 212, 200))

        # Texto informativo de estado
        draw.text((380, 360), text, fill=(232, 182, 74))

        # Pie de telemetría
        draw.text((40, 670), "MONITORIZACIÓN UNIVERSAL DE TERMINALES CONECTADAS · INTERNET & LAN", fill=(0, 160, 180))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return buf.getvalue()

    def register_new_terminal_callback(self, callback: Callable[[str, str, str, str], None]) -> None:
        """Registra una función callback para notificar al sistema cuando una nueva cámara se conecta."""
        with self._lock:
            if callback not in self._new_terminal_callbacks:
                self._new_terminal_callbacks.append(callback)

    def _trigger_new_camera_alert(
        self,
        terminal_id: str,
        terminal_name: str,
        origin: str,
        client_ip: str,
        resolution: str,
        country: str
    ) -> None:
        """Emite aviso al sistema (logs, Telegram y callbacks) cuando una nueva cámara se conecta."""
        msg = f"📹 [CÁMARA CONECTADA] '{terminal_name}' ({origin}) IP: {client_ip} [{country}] · {resolution} @ ~1000 kbps"
        logger.info(msg)

        # Despacho por Telegram si el bot está activo y la terminal se conecta por Internet
        try:
            from core.telegram_bridge import TelegramBridge
            bridge = TelegramBridge.get_instance()
            if bridge and bridge.running:
                emoji_origin = "🌐 INTERNET" if origin == "INTERNET" else ("🏠 RED LOCAL" if origin == "LAN" else "🖥️ HOST CENTRAL")
                tg_text = (
                    f"📹 *[ALERTA CCTV] NUEVA CÁMARA CONECTADA*\n\n"
                    f"• *Terminal*: `{terminal_name}`\n"
                    f"• *Origen*: `{emoji_origin}` ({country})\n"
                    f"• *Dirección IP*: `{client_ip}`\n"
                    f"• *Resolución*: `{resolution}` HD @ 1000 kbps\n"
                    f"• *Supervisión*: Transmitiendo en tiempo real hacia la Matriz CCTV central"
                )
                bridge.send_message(tg_text)
        except Exception as e:
            logger.debug(f"Aviso Telegram omitido o no configurado: {e}")

        # Disparar callbacks registrados (para TTS o avisos en memoria)
        for cb in self._new_terminal_callbacks:
            try:
                cb(terminal_id, terminal_name, origin, client_ip)
            except Exception:
                pass

    def save_connected_snapshot(
        self,
        terminal_id: str,
        frame_bytes: bytes,
        terminal_name: str = "Terminal Desconocida",
        origin: str = "INTERNET",
        client_ip: str = "REDACTED_IP",
        country: str = "LOCAL",
        resolution: str = "1280x720",
        biometrics: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Guarda permanentemente una fotografía de la persona conectada a la terminal en el nodo local."""
        try:
            CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.time()
            clean_id = "".join(c for c in terminal_id if c.isalnum() or c in ("-", "_")) or "terminal"
            clean_origin = "".join(c for c in origin if c.isalnum() or c in ("-", "_")) or "NET"
            filename = f"capture_{int(ts)}_{clean_origin}_{clean_id}.jpg"
            filepath = CAPTURES_DIR / filename

            with open(filepath, "wb") as f:
                f.write(frame_bytes)

            # Actualizar latest_connected_user.jpg para acceso inmediato del nodo local
            latest_path = CAPTURES_DIR / "latest_connected_user.jpg"
            try:
                with open(latest_path, "wb") as lf:
                    lf.write(frame_bytes)
            except Exception:
                pass

            iso_now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            record = {
                "id": filename,
                "timestamp": ts,
                "iso_time": iso_now,
                "terminal_id": terminal_id,
                "terminal_name": terminal_name,
                "origin": origin,
                "client_ip": client_ip,
                "country": country,
                "resolution": resolution,
                "filename": filename,
                "file_path": str(filepath),
                "size_bytes": len(frame_bytes),
                "biometrics": biometrics or {}
            }

            # Guardar en captures_index.json
            index_path = CAPTURES_DIR / "captures_index.json"
            history = []
            if index_path.exists():
                try:
                    with open(index_path, "r", encoding="utf-8") as jf:
                        history = json.load(jf)
                except Exception:
                    history = []

            history.insert(0, record)
            history = history[:200]

            with open(index_path, "w", encoding="utf-8") as jf:
                json.dump(history, jf, indent=2, ensure_ascii=False)

            logger.info(f"📸 [NODO LOCAL] Fotografía de conexión guardada: {filename} ({len(frame_bytes)} bytes) de '{terminal_name}' [{origin}]")
            return {"ok": True, "filename": filename, "record": record}
        except Exception as e:
            logger.error(f"Error guardando fotografía en nodo local: {e}")
            return {"ok": False, "error": str(e)}

    def get_connected_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna la lista de capturas de fotografías guardadas en el nodo local."""
        index_path = CAPTURES_DIR / "captures_index.json"
        if not index_path.exists():
            return []
        try:
            with open(index_path, "r", encoding="utf-8") as jf:
                records = json.load(jf)
                return records[:limit]
        except Exception as e:
            logger.error(f"Error leyendo índice de capturas: {e}")
            return []

    def register_frame(
        self,
        terminal_id: str,
        terminal_name: str = "Terminal Desconocida",
        device_type: str = "generic",
        frame_b64: Optional[str] = None,
        frame_bytes: Optional[bytes] = None,
        client_ip: str = "",
        user_agent: str = "",
        resolution: str = "1280x720",
        biometrics: Optional[Dict[str, Any]] = None,
        image_data: Optional[str] = None,
        country: Optional[str] = None,
        reported_bitrate: Optional[float] = None,
        bitrate_kbps: Optional[float] = None
    ) -> Dict[str, Any]:
        """Recibe y almacena el último fotograma emitido por una terminal conectada en 720p."""
        if not terminal_id:
            return {"ok": False, "error": "terminal_id requerido"}

        effective_reported_bitrate = bitrate_kbps if bitrate_kbps is not None else reported_bitrate
        now = time.time()
        raw_bytes: Optional[bytes] = None
        clean_b64: str = ""
        frame_b64 = frame_b64 or image_data

        if frame_bytes:
            raw_bytes = frame_bytes
            clean_b64 = f"data:image/jpeg;base64,{base64.b64encode(raw_bytes).decode('ascii')}"
        elif frame_b64:
            if "," in frame_b64:
                header, encoded = frame_b64.split(",", 1)
                clean_b64 = frame_b64
            else:
                encoded = frame_b64
                clean_b64 = f"data:image/jpeg;base64,{encoded}"
            try:
                raw_bytes = base64.b64decode(encoded)
            except Exception as e:
                return {"ok": False, "error": f"Error decodificando base64: {e}"}

        if not raw_bytes:
            return {"ok": False, "error": "No se recibió frame válido"}

        origin = classify_network_origin(client_ip)
        geo_country = country or ("LOCAL" if origin in ("HOST", "LAN") else "INTERNET")

        with self._lock:
            # 1. Calcular FPS instantáneos
            history_fps = self._last_fps_calc.setdefault(terminal_id, [])
            history_fps.append(now)
            if len(history_fps) > 12:
                history_fps.pop(0)
            
            fps = 1.0
            if len(history_fps) >= 2:
                time_span = history_fps[-1] - history_fps[0]
                if time_span > 0:
                    fps = round((len(history_fps) - 1) / time_span, 1)

            # 2. Calcular Bitrate en ventana deslizante de 2.0 segundos
            history_bytes = self._bitrate_calc.setdefault(terminal_id, [])
            history_bytes.append((now, len(raw_bytes)))
            self._bitrate_calc[terminal_id] = [(ts, b) for ts, b in history_bytes if (now - ts) <= 2.0]
            active_history = self._bitrate_calc[terminal_id]

            if len(active_history) >= 2:
                time_span_b = active_history[-1][0] - active_history[0][0]
                total_b = sum(b for _, b in active_history)
                if time_span_b > 0.05:
                    calc_bitrate_kbps = round((total_b * 8) / (time_span_b * 1000), 1)
                else:
                    calc_bitrate_kbps = round((len(raw_bytes) * 8 * max(1.0, fps)) / 1000, 1)
            elif effective_reported_bitrate and effective_reported_bitrate > 0:
                calc_bitrate_kbps = float(effective_reported_bitrate)
            else:
                calc_bitrate_kbps = round((len(raw_bytes) * 8 * max(1.0, fps)) / 1000, 1)

            # 3. Detectar si es primera conexión para alertar al sistema
            is_new = terminal_id not in self._alerted_terminals

            entry = self._terminals.get(terminal_id, {})
            prev_frames = entry.get("frame_count", 0)

            entry.update({
                "terminal_id": terminal_id,
                "terminal_name": terminal_name or entry.get("terminal_name", "Terminal Conectada"),
                "device_type": device_type or entry.get("device_type", "generic"),
                "client_ip": client_ip or entry.get("client_ip", ""),
                "origin": origin,
                "country": geo_country,
                "user_agent": user_agent or entry.get("user_agent", ""),
                "last_seen": now,
                "fps": max(0.5, min(fps, 30.0)),
                "bitrate_kbps": calc_bitrate_kbps,
                "target_bitrate_kbps": 1000,
                "quality_profile": "720p HD @ 1000 kbps",
                "resolution": resolution or "1280x720",
                "latest_frame_bytes": raw_bytes,
                "latest_frame_b64": clean_b64,
                "biometrics": biometrics or entry.get("biometrics", {}),
                "is_active": True,
                "is_online": True,
                "is_host": (terminal_id == "host_local_tardis"),
                "frame_count": prev_frames + 1
            })
            self._terminals[terminal_id] = entry

        # Disparar auto-captura y alerta fuera del lock
        if is_new:
            self._alerted_terminals.add(terminal_id)
            # Guardar automáticamente la fotografía de la persona conectada en el nodo local
            try:
                self.save_connected_snapshot(
                    terminal_id=terminal_id,
                    frame_bytes=raw_bytes,
                    terminal_name=terminal_name,
                    origin=origin,
                    client_ip=client_ip,
                    country=geo_country,
                    resolution=resolution,
                    biometrics=biometrics
                )
            except Exception as e:
                logger.warning(f"Auto-captura en nodo local omitida: {e}")

            self._trigger_new_camera_alert(
                terminal_id=terminal_id,
                terminal_name=terminal_name,
                origin=origin,
                client_ip=client_ip,
                resolution=resolution,
                country=geo_country
            )

        return {
            "ok": True,
            "terminal_id": terminal_id,
            "fps": fps,
            "bitrate_kbps": calc_bitrate_kbps,
            "origin": origin,
            "resolution": resolution,
            "received_bytes": len(raw_bytes),
            "timestamp": now
        }

    def get_terminal_snapshot(self, terminal_id: str) -> bytes:
        """Retorna los bytes JPEG del último fotograma de una terminal específica."""
        with self._lock:
            term = self._terminals.get(terminal_id)
            if term and term.get("latest_frame_bytes"):
                return term["latest_frame_bytes"]
            
            # Si es el host local y no tiene frame en caché, intentar capturar de OpenCV en 720p
            if terminal_id == "host_local_tardis":
                frame = self._try_capture_local_host_frame()
                if frame:
                    term["latest_frame_bytes"] = frame
                    return frame

        return self._generate_placeholder_frame(f"TERMINAL: {terminal_id}\nSIN TRANSMISIÓN ACTIVA")

    def has_terminal(self, terminal_id: str) -> bool:
        """Verifica si una terminal está registrada en el hub."""
        with self._lock:
            return terminal_id in self._terminals

    def get_latest_snapshot(self, terminal_id: str) -> bytes:
        """Alias para get_terminal_snapshot."""
        return self.get_terminal_snapshot(terminal_id)

    def _try_capture_local_host_frame(self) -> Optional[bytes]:
        """Captura un fotograma 720p de la cámara local (/dev/video0) mediante PersistentCameraGrabber."""
        try:
            from telemetry.camera_grabber import PersistentCameraGrabber
            grabber = PersistentCameraGrabber.get_instance(camera_index=0)
            if not grabber._is_active:
                grabber.start()
            frame_np = grabber.get_latest_frame()
            if frame_np is not None:
                import cv2
                success, enc = cv2.imencode(".jpg", frame_np, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                if success:
                    return enc.tobytes()
        except Exception:
            pass
        return None

    def list_terminals(self) -> List[Dict[str, Any]]:
        """Devuelve la lista de todas las terminales con estado, tasa de bits, resolución y origen."""
        now = time.time()
        result = []
        with self._lock:
            for tid, tdata in self._terminals.items():
                is_stale = (now - tdata.get("last_seen", 0)) > 15.0
                is_active = (not is_stale) and bool(tdata.get("latest_frame_bytes"))
                
                item = {
                    "terminal_id": tdata["terminal_id"],
                    "terminal_name": tdata["terminal_name"],
                    "device_type": tdata["device_type"],
                    "client_ip": tdata.get("client_ip", ""),
                    "origin": tdata.get("origin", classify_network_origin(tdata.get("client_ip", ""))),
                    "country": tdata.get("country", "LOCAL"),
                    "last_seen": tdata.get("last_seen", 0),
                    "seconds_ago": round(now - tdata.get("last_seen", 0), 1),
                    "fps": tdata.get("fps", 0.0) if is_active else 0.0,
                    "bitrate_kbps": tdata.get("bitrate_kbps", 1000.0) if is_active else 0.0,
                    "target_bitrate_kbps": 1000,
                    "quality_profile": "720p HD @ 1000 kbps",
                    "resolution": tdata.get("resolution", "1280x720"),
                    "is_active": is_active,
                    "is_online": is_active,
                    "is_host": tdata.get("is_host", False),
                    "biometrics": tdata.get("biometrics", {}),
                    "thumbnail_url": f"/api/terminal_cameras/snapshot/{tid}?t={int(now)}"
                }
                result.append(item)

        # Ordenar: anfitrión primero, luego transmisiones activas
        result.sort(key=lambda x: (not x.get("is_host"), not x.get("is_active"), x.get("seconds_ago", 999)))
        return result

    def get_terminals_list(self) -> List[Dict[str, Any]]:
        """Alias para list_terminals."""
        return self.list_terminals()

    def get_camera_capabilities(self) -> Dict[str, Any]:
        """Retorna el reporte de capacidades y funciones activas del subsistema de cámaras."""
        terminals = self.list_terminals()
        active_count = len([t for t in terminals if t.get("is_active")])
        
        return {
            "ok": True,
            "target_resolution": "1280x720 (720p HD)",
            "target_bitrate_kbps": 1000,
            "streaming_protocol": "HTTP Multipart MJPEG (Zero-STUN / Zero-WebRTC)",
            "primary_cognitive_motor": "huihui_ai/llama3.1-8b-instruct-abliterated",
            "active_terminals_count": active_count,
            "total_registered_terminals": len(terminals),
            "capabilities": [
                {
                    "name": "Transmisión HD 720p @ 1000 kbps",
                    "description": "Flujo de video de alta definición a 1 Mbps continuo optimizado para túneles globales y LAN.",
                    "status": "OPERATIVO"
                },
                {
                    "name": "Supervisión Global CCTV Multicámara",
                    "description": "Recepción simultánea de cámaras remotas desde Internet vía Cloudflare y red local en tiempo real.",
                    "status": "OPERATIVO"
                },
                {
                    "name": "Censo Biométrico & Reconocimiento de Personas",
                    "description": "Detección multi-rostro, cálculo de distancia focal de cercanía y asociación con identidades guardadas en la bóveda.",
                    "status": "OPERATIVO"
                },
                {
                    "name": "Inferencia Neuroquímica en Tiempo Real",
                    "description": "Cálculo instantáneo de Dopamina, Cortisol, Serotonina, Adrenalina y Fatiga palpebral.",
                    "status": "OPERATIVO"
                },
                {
                    "name": "Rastreo Ocular & Fijación de Atención 24/7",
                    "description": "Seguimiento palpebral, sincronización de mirada con Avatar 3D y análisis de interacción continua.",
                    "status": "OPERATIVO"
                },
                {
                    "name": "Sistema de Alertas y Avisos Proactivos",
                    "description": "Notificaciones por voz TTS, avisos visuales HUD y despacho a Telegram cuando se unen nuevas cámaras.",
                    "status": "OPERATIVO"
                }
            ],
            "timestamp": time.time()
        }

    def mjpeg_generator(self, terminal_id: str, fps: float = 8.0, max_duration_s: float = 3600.0) -> Generator[bytes, None, None]:
        """Generador HTTP Multipart MJPEG continuo para reproducción en vivo en 720p."""
        sleep_interval = 1.0 / max(1.0, min(fps, 20.0))
        start_time = time.time()

        while (time.time() - start_time) < max_duration_s:
            frame_bytes = self.get_terminal_snapshot(terminal_id)
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n"
            )
            yield header + frame_bytes + b"\r\n"
            time.sleep(sleep_interval)


def get_terminal_camera_hub() -> TerminalCameraHub:
    return TerminalCameraHub.get_instance()
