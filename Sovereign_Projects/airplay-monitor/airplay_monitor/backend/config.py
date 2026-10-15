"""
Módulo de Configuración de AirPlay Monitor
Maneja las preferencias del usuario, archivos ~/.config/uxplayrc y el servicio systemd.
Configurado para Pantalla Completa, Rotación Dinámica, Modo Receptor de Video (HLS), 144 FPS y Calidad Cruda.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "airplay-monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"
UXPLAY_RC_FILE = Path.home() / ".config" / "uxplayrc"

DEFAULT_CONFIG = {
    "server_name": "TimeMachine-AirPlay",
    "video_sink": "waylandsink",
    "video_decoder": "nvh264dec",       # Hardware acceleration vía NVIDIA RTX 3050 NVDEC
    "resolution": "2560x1440@144",      # Resolución nativa de monitor 144Hz
    "fps": "144",                       # Techo dinámico hasta 144 FPS
    "dynamic_fps": True,                # FPS Dinámico adaptativo (ProMotion / Variable Refresh)
    "fps_data": True,                   # Telemetría de FPS en tiempo real enviada por el cliente
    "fullscreen": True,                 # Modo Pantalla Completa por defecto
    "auto_orientation": True,           # Adaptación visual automática horizontal / vertical
    "hls": True,                        # Modo Monitor Receptor de Video Directo (AirPlay Video Cast / HLS)
    "h265": True,                       # HEVC para fidelidad Retina sin pérdidas
    "srgb": True,                       # Rango de color dinámico completo [0-255] sin recorte
    "low_latency": True,                # vsync no: Desactiva búfer de retardo de sincronización
    "audio_latency": 0.05,              # 50ms de latencia reportada a iOS (elimina buffer cliente)
    "pin_code": "",
    "audio_delay": 0,
    "autostart": True,
    "reset_timeout": 15,
    "nofreeze": True,
}


class ConfigManager:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self.load()

    def load(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg = DEFAULT_CONFIG.copy()
                    cfg.update(data)
                    return cfg
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def save(self, new_cfg: dict | None = None) -> bool:
        if new_cfg:
            self.config.update(new_cfg)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.write_uxplayrc()
            return True
        except Exception as e:
            print(f"Error al guardar config: {e}")
            return False

    def write_uxplayrc(self):
        """Escribe las directivas optimizadas de inicio en ~/.config/uxplayrc."""
        lines = [
            "# ==============================================================================",
            "# UxPlay RC - Pantalla Completa, Rotación Dinámica y Modo Monitor Receptor HLS",
            "# ==============================================================================",
            f"n {self.config.get('server_name', 'TimeMachine-AirPlay')}",
            "nh",
        ]

        # Pantalla Completa y Motor de Video (Wayland Sink)
        is_fs = self.config.get("fullscreen", True)
        sink = self.config.get("video_sink", "waylandsink")
        
        if is_fs:
            lines.append("fs")
        if sink and sink != "default":
            lines.append(f"vs {sink}")

        # Modo Monitor Receptor de Video Directo (HLS / Media Playback Fullscreen)
        if self.config.get("hls", True):
            hls_v = str(self.config.get("hls_version", "3"))
            if hls_v == "2":
                lines.append("hls 2")
            else:
                lines.append("hls")

        # Decodificador de Hardware
        decoder = self.config.get("video_decoder", "nvh264dec")
        if decoder and decoder != "default":
            lines.append(f"vd {decoder}")

        # Tasa de Cuadros Dinámica hasta 144 FPS
        fps = self.config.get("fps", "144")
        if fps:
            lines.append(f"fps {fps}")

        # Reporte de telemetría de rendimiento y FPS del cliente
        if self.config.get("fps_data", True):
            lines.append("FPSdata")

        # Resolución y Frecuencia Solicitada
        res = self.config.get("resolution", "2560x1440@144")
        if res and res != "default":
            lines.append(f"s {res}")

        # Códec H.265 / HEVC de alta fidelidad
        if self.config.get("h265", True):
            lines.append("h265")

        # Rango de Color Completo sRGB [0-255]
        if self.config.get("srgb", True):
            lines.append("srgb")

        # Ultra-Baja Latencia: Desactivar sincronización diferida por timestamp (vsync no)
        if self.config.get("low_latency", True):
            lines.append("vsync no")
        else:
            delay = self.config.get("audio_delay", 0)
            if delay != 0:
                lines.append(f"vsync {delay}")

        # Latencia reportada al cliente iOS (reduce búfer previo en el iPhone/iPad)
        al = self.config.get("audio_latency", 0.05)
        if al is not None:
            lines.append(f"al {al}")

        # Comportamiento de desconexión y reset
        if self.config.get("nofreeze", True):
            lines.append("nofreeze")

        timeout = self.config.get("reset_timeout", 15)
        lines.append(f"reset {timeout}")

        # Seguridad PIN
        pin = self.config.get("pin_code", "").strip()
        if pin and len(pin) == 4:
            lines.append(f"pin {pin}")

        try:
            UXPLAY_RC_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(UXPLAY_RC_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            print(f"Error escribiendo uxplayrc: {e}")
