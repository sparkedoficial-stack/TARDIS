"""
core/speaking_video_generator.py - Generador de Video del Sistema Hablando (GIA/TARDIS)
=======================================================================================
Renderiza en tiempo real videos del sistema hablando para Telegram y clientes remotos:
  1. Síntesis de voz neural de alta fidelidad con Cortana Neural (voice.py / edge-tts).
  2. Generación de overlay ciberespacial con Pillow (avatar holográfico, HUD, subtítulos).
  3. Composición y visualización de espectro reactivo a la voz con FFmpeg (showwaves).
  4. Salida en formato MP4 H.264/AAC cuadrado (480x480) 100% compatible con:
     - Videonotas circulares nativas de Telegram (sendVideoNote).
     - Videos estándar de alta definición con reproducción fluida (sendVideo).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("SpeakingVideoGenerator")

BASE_DIR = Path(__file__).resolve().parent.parent
VIDEOS_DIR = BASE_DIR / "data" / "telegram_videos"
ICON_PATH = BASE_DIR / "godworks-icon.png"

FONT_BOLD_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


class SpeakingVideoGenerator:
    """Motor de generación de video del sistema hablando con avatar y espectro de voz."""

    _instance: Optional[SpeakingVideoGenerator] = None

    @classmethod
    def get_instance(cls) -> SpeakingVideoGenerator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or VIDEOS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.icon_path = ICON_PATH if ICON_PATH.exists() else None

    def clean_text_for_speech(self, text: str) -> str:
        """Limpia markdown, comandos y enlaces para una dicción natural."""
        if not text:
            return ""
        t = text
        t = re.sub(r"```[a-zA-Z0-9_-]*\n([\s\S]*?)```", r" Código: \1 ", t)
        t = re.sub(r"```", " ", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
        t = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", t)
        t = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", t)
        t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
        t = re.sub(r"[━─=_\-]{3,}", " ", t)
        t = re.sub(r"[ \t]+", " ", t)
        return t.strip()

    def _load_font(self, font_path: str, size: int) -> ImageFont.ImageFont:
        try:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            pass
        try:
            return ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    def create_overlay_image(
        self,
        text: str,
        width: int = 480,
        height: int = 480,
        title: str = "GIA · NODO SOBERANO"
    ) -> Image.Image:
        """Crea una capa transparente con HUD, título y subtítulos formateados."""
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font_title = self._load_font(FONT_BOLD_PATH, 15)
        font_text = self._load_font(FONT_REGULAR_PATH, 13)
        font_sub = self._load_font(FONT_REGULAR_PATH, 10)

        # 1. Badge superior de estatus soberano
        badge_w, badge_h = 240, 32
        badge_x0 = (width - badge_w) // 2
        badge_y0 = 14
        draw.rounded_rectangle(
            [badge_x0, badge_y0, badge_x0 + badge_w, badge_y0 + badge_h],
            radius=8,
            fill=(2, 22, 38, 220),
            outline=(0, 255, 212, 200),
            width=1
        )
        # Círculo verde de estatus en vivo
        draw.ellipse([badge_x0 + 10, badge_y0 + 10, badge_x0 + 22, badge_y0 + 22], fill=(0, 255, 180, 255))
        draw.text((badge_x0 + 30, badge_y0 + 8), title, font=font_title, fill=(0, 255, 212, 255))

        # 2. Caja inferior de subtítulos
        # Truncar o envolver texto
        clean_prompt = self.clean_text_for_speech(text)
        wrapped_lines = textwrap.wrap(clean_prompt, width=46)
        if len(wrapped_lines) > 3:
            wrapped_lines = wrapped_lines[:2] + [wrapped_lines[2][:40] + "..."]
        elif not wrapped_lines:
            wrapped_lines = ["..."]

        line_height = 17
        sub_box_h = 24 + len(wrapped_lines) * line_height + 14
        sub_box_y0 = height - sub_box_h - 12
        sub_box_w = width - 36
        sub_box_x0 = 18

        draw.rounded_rectangle(
            [sub_box_x0, sub_box_y0, sub_box_x0 + sub_box_w, sub_box_y0 + sub_box_h],
            radius=10,
            fill=(4, 14, 25, 225),
            outline=(0, 212, 200, 160),
            width=1
        )

        cur_y = sub_box_y0 + 8
        for line in wrapped_lines:
            draw.text((sub_box_x0 + 12, cur_y), line, font=font_text, fill=(255, 255, 255, 240))
            cur_y += line_height

        draw.text(
            (sub_box_x0 + 12, cur_y + 2),
            "TARDIS v26.4 · Inferencia y Síntesis Soberana",
            font=font_sub,
            fill=(160, 174, 192, 190)
        )

        return overlay

    def get_audio_duration(self, audio_path: str | Path) -> float:
        """Obtiene la duración exacta del audio usando ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
            return float(out)
        except Exception as e:
            logger.warning(f"Error midiendo duración con ffprobe: {e}")
            return 4.0

    def generate_speaking_video(
        self,
        text: str,
        audio_bytes: Optional[bytes] = None,
        voice_id: Optional[str] = None,
        title: str = "GIA · NODO SOBERANO",
        width: int = 480,
        height: int = 480
    ) -> Dict[str, Any]:
        """
        Genera un video completo del sistema hablando con locución y espectro reactivo.
        Retorna diccionario con la ruta del video, bytes, duración y metadatos.
        """
        t0 = time.time()
        text_clean = self.clean_text_for_speech(text)
        if not text_clean:
            return {"ok": False, "error": "Texto vacío para síntesis"}

        # 1. Sintetizar voz si no fue provista
        if not audio_bytes:
            try:
                import voice as _v
                v_target = voice_id or "es-MX-DaliaNeural"
                audio_bytes = _v.synthesize_to_bytes(text_clean, voice=v_target)
            except Exception as e:
                logger.error(f"Error sintetizando voz en speaking_video_generator: {e}")

        if not audio_bytes:
            return {"ok": False, "error": "Fallo en síntesis de audio"}

        ts_id = int(time.time() * 1000)
        temp_audio = self.output_dir / f"temp_audio_{ts_id}.mp3"
        temp_overlay = self.output_dir / f"temp_overlay_{ts_id}.png"
        output_mp4 = self.output_dir / f"gia_speaking_{ts_id}.mp4"

        try:
            temp_audio.write_bytes(audio_bytes)
            duration = self.get_audio_duration(temp_audio)

            # 2. Generar imagen overlay
            overlay_img = self.create_overlay_image(text=text, width=width, height=height, title=title)
            overlay_img.save(temp_overlay)

            # 3. Preparar imagen base de fondo (ícono o color sólido)
            bg_input = str(self.icon_path) if self.icon_path and self.icon_path.exists() else None

            # Construir comando FFmpeg
            if bg_input:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(temp_audio),
                    "-loop", "1", "-i", bg_input,
                    "-loop", "1", "-i", str(temp_overlay),
                    "-filter_complex",
                    f"[1:v]scale={width}:{height},format=yuv420p[bg];"
                    f"[0:a]showwaves=s=420x90:mode=cline:colors=0x00ffff|0x00ffd4:rate=24[wave];"
                    f"[bg][wave]overlay=x=(W-w)/2:y=310[bg_wave];"
                    f"[bg_wave][2:v]overlay=x=0:y=0:shortest=1[v]",
                    "-map", "[v]",
                    "-map", "0:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-t", f"{duration:.2f}",
                    str(output_mp4)
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(temp_audio),
                    "-f", "lavfi", "-i", f"color=c=0x021626:s={width}x{height}:d={duration}",
                    "-loop", "1", "-i", str(temp_overlay),
                    "-filter_complex",
                    f"[0:a]showwaves=s=420x110:mode=cline:colors=0x00ffff|0x00ffd4:rate=24[wave];"
                    f"[1:v][wave]overlay=x=(W-w)/2:y=280[bg_wave];"
                    f"[bg_wave][2:v]overlay=x=0:y=0:shortest=1[v]",
                    "-map", "[v]",
                    "-map", "0:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-t", f"{duration:.2f}",
                    str(output_mp4)
                ]

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=40.0)
            if res.returncode != 0:
                logger.error(f"FFmpeg falló al generar video: {res.stderr[-400:]}")
                return {"ok": False, "error": f"FFmpeg error: {res.stderr[-200:]}"}

            if not output_mp4.exists() or output_mp4.stat().st_size == 0:
                return {"ok": False, "error": "Video generado vacío"}

            video_bytes = output_mp4.read_bytes()
            elapsed = round(time.time() - t0, 2)

            # Limpiar videos antiguos (mantener solo los últimos 30)
            self._cleanup_old_videos()

            return {
                "ok": True,
                "video_path": str(output_mp4),
                "video_bytes": video_bytes,
                "duration": duration,
                "width": width,
                "height": height,
                "elapsed_s": elapsed,
                "file_size": len(video_bytes),
                "text": text
            }

        except Exception as e:
            logger.error(f"Excepción en generate_speaking_video: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            try:
                if temp_audio.exists():
                    temp_audio.unlink()
                if temp_overlay.exists():
                    temp_overlay.unlink()
            except Exception:
                pass

    def _cleanup_old_videos(self, keep_count: int = 30):
        """Mantiene el directorio de videos limpio sin saturar el almacenamiento."""
        try:
            v_files = sorted(self.output_dir.glob("gia_speaking_*.mp4"), key=lambda p: p.stat().st_mtime)
            if len(v_files) > keep_count:
                for f in v_files[:-keep_count]:
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception:
            pass


def get_speaking_video_generator() -> SpeakingVideoGenerator:
    return SpeakingVideoGenerator.get_instance()
