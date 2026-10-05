"""
core/speaking_video_generator.py - Generador de Video del Sistema Hablando (GIA/TARDIS)
=======================================================================================
Renderiza en tiempo real videos del sistema hablando para Telegram y clientes remotos:
  1. Síntesis de voz neural de alta fidelidad con Cortana Neural (voice.py / edge-tts).
  2. Render 3D del personaje (core/character_3d_renderer) sincronizado con los visemas.
  3. Composición de HUD, subtítulos y espectro en resolución nativa.
  4. Salida MP4 H.264/AAC en dos formatos:
     - 3840x2160 (4K) a 60 FPS con HUD, para sendVideo.
     - 1024x1024 sin HUD, para las videonotas circulares (sendVideoNote).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
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
    _render_lock = threading.Lock()

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

    def render_vocalizing_frame(
        self,
        t_sec: float,
        duration: float,
        word_timings: List[Dict[str, Any]],
        text: str,
        width: int = 1080,
        height: int = 1080,
        title: str = "TARDIS · MENSAJE SOBERANO"
    ) -> Image.Image:
        """
        Renderiza un cuadro ultra-HD (1080P) del personaje de TARDIS con los gráficos exactos
        de la plataforma local soberana vocalizando sincrónicamente palabra a palabra.
        """
        import math
        img = Image.new("RGB", (width, height), (3, 8, 16))
        draw = ImageDraw.Draw(img)

        scale = min(width, height) / 480.0
        cx = width // 2
        cy = int(height * 0.43)
        base_size = 175.0 * scale

        # Dinámica del personaje (levitación, oscilación y respiración natural)
        float_y = math.sin(t_sec * 1.6) * (base_size * 0.024)
        breath = 1.0 + math.sin(t_sec * 2.4) * 0.012
        char_cy = cy + float_y
        size = base_size * breath

        # Colores idénticos a la plataforma local soberana
        col_primary = (0, 212, 200)       # Teal
        col_secondary = (232, 182, 74)    # Gold
        col_hull_fill = (4, 16, 28)       # Dark cyan glass
        col_iris_ring = (245, 158, 11)    # Speaking amber

        # Detección de palabra activa y fonética en t_sec
        active_w = None
        for w in word_timings:
            if w.get("start", 0) <= t_sec <= w.get("end", 0):
                active_w = w
                break

        blink_phase = (t_sec % 3.4)
        is_blinking = blink_phase < 0.16
        blink_val = math.sin(blink_phase / 0.16 * math.pi) if is_blinking else 0.0

        if active_w:
            dur = max(0.01, active_w.get("duration", 0.3))
            rel_t = (t_sec - active_w.get("start", 0)) / dur
            syl = math.sin(rel_t * math.pi * max(1, active_w.get("syllables", 1)))
            mouth_open = max(0.12, active_w.get("target_open", 0.7) * (0.35 + 0.65 * max(0.0, syl)))
            mouth_width = active_w.get("target_width", 1.0)
            vocal_pulse = 1.0 if active_w.get("emphasis") else 0.8
        else:
            mouth_open = 0.04
            mouth_width = 1.0
            vocal_pulse = 0.0

        # 1. Fondo con Viñeta Cibernética Radial
        max_r = int(min(width, height) * 0.5)
        step_r = max(10, int(18 * scale))
        for r in range(max_r, 0, -step_r):
            intensity = int(24 * (1.0 - r / float(max_r)))
            draw.ellipse(
                [(cx - r, char_cy - r), (cx + r, char_cy + r)],
                fill=(3 + intensity, 8 + intensity * 2, 16 + intensity * 3)
            )

        # 2. Ondas de Choque Acústicas al Vocalizar
        wave_count = 3
        speed = 2.8
        for w in range(wave_count):
            wave_phase = (t_sec * speed + w / float(wave_count)) % 1.0
            r_min = size * 0.45
            r_max = size * 0.95
            wr = r_min + wave_phase * (r_max - r_min)
            w_alpha = int((1.0 - wave_phase) * 180)
            if w_alpha > 12:
                w_thick = max(1, int(4 * scale * (1.0 - wave_phase)))
                draw.ellipse(
                    [(cx - wr, char_cy - wr), (cx + wr, char_cy + wr)],
                    outline=col_primary,
                    width=w_thick
                )

        # 3. Astrolabio Rúnico Rotatorio
        r_reticle = size * 0.74
        reticle_angle = t_sec * 0.28
        notches = 12
        for n in range(notches):
            ang = (n / float(notches)) * math.pi * 2 + reticle_angle
            tick_len = size * 0.025
            nx1 = cx + math.cos(ang) * (r_reticle - tick_len)
            ny1 = char_cy + math.sin(ang) * (r_reticle - tick_len)
            nx2 = cx + math.cos(ang) * (r_reticle + tick_len)
            ny2 = char_cy + math.sin(ang) * (r_reticle + tick_len)
            col_tick = col_secondary if n % 3 == 0 else col_primary
            draw.line([(nx1, ny1), (nx2, ny2)], fill=col_tick, width=max(1, int(3 * scale)))

        draw.ellipse(
            [(cx - r_reticle, char_cy - r_reticle), (cx + r_reticle, char_cy + r_reticle)],
            outline=col_secondary,
            width=max(1, int(2 * scale))
        )

        # 4. Geometría Equilátera (Casco Triangular)
        tri_h = size * (math.sqrt(3) / 2)
        p_apex = (cx, char_cy - tri_h * (2 / 3))
        p_left = (cx - size * 0.5, char_cy + tri_h * (1 / 3))
        p_right = (cx + size * 0.5, char_cy + tri_h * (1 / 3))
        p_mid_left = ((p_apex[0] + p_left[0]) * 0.5, (p_apex[1] + p_left[1]) * 0.5)
        p_mid_right = ((p_apex[0] + p_right[0]) * 0.5, (p_apex[1] + p_right[1]) * 0.5)
        p_mid_bottom = (cx, char_cy + tri_h * (1 / 3))

        # Relleno del casco con borde neón
        draw.polygon([p_apex, p_right, p_left], fill=col_hull_fill, outline=col_primary, width=max(2, int(5 * scale)))

        # 5. Enrejado Interno
        draw.line([(cx, char_cy), p_apex], fill=col_primary, width=max(1, int(2 * scale)))
        draw.line([(cx, char_cy), p_left], fill=col_primary, width=max(1, int(2 * scale)))
        draw.line([(cx, char_cy), p_right], fill=col_primary, width=max(1, int(2 * scale)))
        draw.polygon([p_mid_bottom, p_mid_left, p_mid_right], outline=col_secondary, width=max(1, int(2 * scale)))

        # 6. Nodos en los Vértices
        node_r = int(size * 0.026)
        for pt in [p_apex, p_left, p_right]:
            draw.ellipse(
                [(pt[0] - node_r, pt[1] - node_r), (pt[0] + node_r, pt[1] + node_r)],
                fill=col_secondary,
                outline=col_primary,
                width=max(1, int(2 * scale))
            )
            inner_dot = max(1, int(node_r * 0.4))
            draw.ellipse(
                [(pt[0] - inner_dot, pt[1] - inner_dot), (pt[0] + inner_dot, pt[1] + inner_dot)],
                fill=(255, 255, 255)
            )

        # 7. Ojo Cibernético con Micro-Dilatación Pupilar
        eye_w = size * 0.34
        eye_h = max(2.0, size * 0.20 * (1.0 - blink_val * 0.96))
        eye_cx, eye_cy = cx, char_cy - size * 0.012

        draw.ellipse(
            [(eye_cx - eye_w * 0.5, eye_cy - eye_h * 0.5), (eye_cx + eye_w * 0.5, eye_cy + eye_h * 0.5)],
            fill=(2, 6, 12),
            outline=col_primary,
            width=max(1, int(3 * scale))
        )

        if not is_blinking and eye_h > 4:
            iris_r = eye_w * 0.26
            draw.ellipse(
                [(eye_cx - iris_r, eye_cy - iris_r), (eye_cx + iris_r, eye_cy + iris_r)],
                fill=col_iris_ring,
                outline=col_primary,
                width=max(1, int(2 * scale))
            )

            # Radios / Rayos de retícula cuántica del iris
            for a in range(8):
                ang = (a / 8.0) * math.pi * 2 + t_sec * 0.5
                r1 = iris_r * 0.35
                r2 = iris_r * 0.90
                draw.line(
                    [(eye_cx + math.cos(ang) * r1, eye_cy + math.sin(ang) * r1),
                     (eye_cx + math.cos(ang) * r2, eye_cy + math.sin(ang) * r2)],
                    fill=col_primary,
                    width=max(1, int(2 * scale))
                )

            # Pupila viva con micro-dilatación vocal
            pupil_r = iris_r * (0.38 + 0.12 * vocal_pulse)
            draw.ellipse(
                [(eye_cx - pupil_r, eye_cy - pupil_r), (eye_cx + pupil_r, eye_cy + pupil_r)],
                fill=(0, 0, 0)
            )

            # Brillo especular
            sp1_r = max(1, int(iris_r * 0.22))
            draw.ellipse(
                [(eye_cx - iris_r * 0.32 - sp1_r, eye_cy - iris_r * 0.32 - sp1_r),
                 (eye_cx - iris_r * 0.32 + sp1_r, eye_cy - iris_r * 0.32 + sp1_r)],
                fill=(255, 255, 255)
            )
            sp2_r = max(1, int(iris_r * 0.10))
            draw.ellipse(
                [(eye_cx + iris_r * 0.26 - sp2_r, eye_cy + iris_r * 0.22 - sp2_r),
                 (eye_cx + iris_r * 0.26 + sp2_r, eye_cy + iris_r * 0.22 + sp2_r)],
                fill=(255, 255, 255)
            )

        # 8. Boca Biomecánica Articulada Palabra a Palabra
        mouth_y = char_cy + tri_h * 0.18
        cur_mouth_w = size * 0.28 * mouth_width
        left_x = cx - cur_mouth_w * 0.5
        right_x = cx + cur_mouth_w * 0.5
        open_h = max(2.0, size * 0.20 * mouth_open)

        if mouth_open > 0.08:
            # Cavidad bucal abierta con profundidad
            draw.chord(
                [(left_x, mouth_y - open_h * 0.40), (right_x, mouth_y + open_h * 0.85)],
                0, 180,
                fill=(2, 8, 16),
                outline=col_secondary,
                width=max(1, int(3 * scale))
            )
            if open_h > 6 * scale:
                draw.line(
                    [(cx - cur_mouth_w * 0.25, mouth_y - 2 * scale), (cx + cur_mouth_w * 0.25, mouth_y - 2 * scale)],
                    fill=(240, 240, 240),
                    width=max(1, int(2 * scale))
                )
            comm_r = max(2, int(4 * scale))
            draw.ellipse([(left_x - comm_r, mouth_y - comm_r), (left_x + comm_r, mouth_y + comm_r)], fill=col_primary)
            draw.ellipse([(right_x - comm_r, mouth_y - comm_r), (right_x + comm_r, mouth_y + comm_r)], fill=col_primary)
        else:
            # Sonrisa en reposo durante pausas entre palabras
            draw.line([(left_x, mouth_y), (right_x, mouth_y)], fill=col_secondary, width=max(1, int(3 * scale)))
            comm_r = max(1, int(3 * scale))
            draw.ellipse([(left_x - comm_r, mouth_y - comm_r), (left_x + comm_r, mouth_y + comm_r)], fill=col_primary)
            draw.ellipse([(right_x - comm_r, mouth_y - comm_r), (right_x + comm_r, mouth_y + comm_r)], fill=col_primary)

        # 9. Enjambre Orbital de Partículas (8 partículas)
        for p in range(8):
            p_ang = (p / 8.0) * math.pi * 2 + t_sec * 0.85 * (1 if p % 2 == 0 else -0.7)
            px = cx + math.cos(p_ang) * (size * 0.62 + (p % 3) * (size * 0.04))
            py = char_cy + math.sin(p_ang) * (size * 0.38)
            pr = max(2, int(size * 0.016))
            draw.ellipse(
                [(px - pr, py - pr), (px + pr, py + pr)],
                fill=col_primary if p % 2 == 0 else col_secondary
            )

        # 10. HUD Inferior y Subtítulos (1080P)
        font_title = self._load_font(FONT_BOLD_PATH, max(12, int(22 * scale)))
        font_text = self._load_font(FONT_REGULAR_PATH, max(11, int(20 * scale)))
        font_sub = self._load_font(FONT_REGULAR_PATH, max(9, int(15 * scale)))

        # Badge superior
        badge_w, badge_h = int(380 * scale), int(42 * scale)
        badge_x0 = (width - badge_w) // 2
        badge_y0 = int(24 * scale)
        draw.rounded_rectangle(
            [badge_x0, badge_y0, badge_x0 + badge_w, badge_y0 + badge_h],
            radius=int(10 * scale),
            fill=(2, 22, 38),
            outline=(0, 255, 212),
            width=max(1, int(2 * scale))
        )
        dot_r = int(6 * scale)
        draw.ellipse(
            [(badge_x0 + int(16 * scale) - dot_r, badge_y0 + badge_h // 2 - dot_r),
             (badge_x0 + int(16 * scale) + dot_r, badge_y0 + badge_h // 2 + dot_r)],
            fill=(0, 255, 180)
        )
        draw.text(
            (badge_x0 + int(32 * scale), badge_y0 + int(8 * scale)),
            title,
            font=font_title,
            fill=(0, 255, 212)
        )

        # Subtítulos con texto de la explicación
        clean_prompt = self.clean_text_for_speech(text)
        wrap_width = max(30, int(42 * (width / 480.0)))
        wrapped_lines = textwrap.wrap(clean_prompt, width=wrap_width)
        if len(wrapped_lines) > 3:
            wrapped_lines = wrapped_lines[:2] + [wrapped_lines[2][:wrap_width - 4] + "..."]
        elif not wrapped_lines:
            wrapped_lines = ["..."]

        line_height = int(26 * scale)
        sub_box_h = int(30 * scale) + len(wrapped_lines) * line_height + int(20 * scale)
        sub_box_y0 = height - sub_box_h - int(24 * scale)
        sub_box_w = width - int(48 * scale)
        sub_box_x0 = int(24 * scale)

        draw.rounded_rectangle(
            [sub_box_x0, sub_box_y0, sub_box_x0 + sub_box_w, sub_box_y0 + sub_box_h],
            radius=int(14 * scale),
            fill=(4, 14, 25),
            outline=(0, 212, 200),
            width=max(1, int(2 * scale))
        )

        cur_y = sub_box_y0 + int(12 * scale)
        for line in wrapped_lines:
            draw.text((sub_box_x0 + int(18 * scale), cur_y), line, font=font_text, fill=(255, 255, 255))
            cur_y += line_height

        draw.text(
            (sub_box_x0 + int(18 * scale), cur_y + int(4 * scale)),
            "TARDIS · Plataforma Soberana (1080P · 60FPS)",
            font=font_sub,
            fill=(160, 174, 192)
        )

        return img

    def generate_speaking_video(
        self,
        text: str,
        audio_bytes: Optional[bytes] = None,
        voice_id: Optional[str] = None,
        title: str = "TARDIS · MENSAJE SOBERANO",
        width: int = 3840,
        height: int = 2160,
        fps: int = 60,
        mode: str = "uhd"
    ) -> Dict[str, Any]:
        """
        Genera el videomensaje del personaje 3D de TARDIS vocalizando el texto.

        mode="uhd"  -> 3840x2160 (4K) a 60 FPS con HUD, para sendVideo.
        mode="note" -> 1024x1024 sin HUD, para las videonotas circulares de Telegram,
                       que la API recorta a un circulo y limita a ~640 px de lado.
        """
        t0 = time.time()
        text_clean = self.clean_text_for_speech(text)
        if not text_clean:
            return {"ok": False, "error": "Texto vacío para síntesis"}

        word_timings = []
        duration = 3.0

        # 1. Sintetizar voz y extraer marcas fonéticas si no fue provista
        if not audio_bytes:
            try:
                import voice as _v
                v_target = voice_id or "es-MX-DaliaNeural"
                synth_res = _v.synthesize_with_timing(text_clean, voice=v_target)
                if synth_res.get("ok"):
                    audio_bytes = synth_res.get("audio_bytes")
                    word_timings = synth_res.get("word_timings", [])
                    duration = synth_res.get("duration", 3.0)
                else:
                    audio_bytes = _v.synthesize_to_bytes(text_clean, voice=v_target)
            except Exception as e:
                logger.error(f"Error sintetizando voz en speaking_video_generator: {e}")
        else:
            # Si audio_bytes fue provisto externamente, estimar los límites de palabra a escala
            try:
                import voice as _v
                ts_dummy = int(time.time() * 1000)
                temp_dummy = self.output_dir / f"temp_dummy_{ts_dummy}.mp3"
                temp_dummy.write_bytes(audio_bytes)
                duration = self.get_audio_duration(temp_dummy)
                if temp_dummy.exists():
                    temp_dummy.unlink()

                words = text_clean.split()
                if words and duration > 0:
                    dur_per_word = duration / len(words)
                    for i, w in enumerate(words):
                        vis = _v.extract_word_visemes(w) if hasattr(_v, "extract_word_visemes") else {}
                        start = i * dur_per_word
                        end = (i + 1) * dur_per_word
                        word_timings.append({
                            "word": w,
                            "start": round(start, 3),
                            "end": round(end, 3),
                            "duration": round(dur_per_word, 3),
                            "viseme": vis.get("viseme", "A"),
                            "target_open": vis.get("target_open", 0.7),
                            "target_width": vis.get("target_width", 1.0),
                            "emphasis": vis.get("emphasis", False),
                            "syllables": vis.get("syllables", 1)
                        })
            except Exception as e:
                logger.warning(f"Error calculando timing para audio externo: {e}")

        if not audio_bytes:
            # MANDATO SOBERANO: En todos los videos debe existir audio.
            # Si no hay locución o falla el TTS, generar audio armónico sintrópico procedural
            try:
                from core.tardis_audio_synthesizer import get_audio_synthesizer
                synth = get_audio_synthesizer()
                est_dur = max(3.5, len(text_clean.split()) * 0.45)
                audio_arr, _ = synth.synthesize_soundscape(
                    duration=est_dur,
                    title=title,
                    domain="Resonancia Armónica TARDIS"
                )
                ts_synth = int(time.time() * 1000)
                temp_wav_synth = self.output_dir / f"temp_synth_{ts_synth}.wav"
                synth.export_to_wav(audio_arr, temp_wav_synth)
                audio_bytes = temp_wav_synth.read_bytes()
                duration = est_dur
                if temp_wav_synth.exists():
                    temp_wav_synth.unlink()
            except Exception as e_synth:
                logger.error(f"Error generando audio alternativo sintrópico: {e_synth}")

        if not audio_bytes:
            return {"ok": False, "error": "Fallo en síntesis de audio"}

        ts_id = int(time.time() * 1000)
        temp_audio = self.output_dir / f"temp_audio_{ts_id}.mp3"
        output_mp4 = self.output_dir / f"gia_speaking_{ts_id}.mp4"

        try:
            temp_audio.write_bytes(audio_bytes)
            actual_duration = self.get_audio_duration(temp_audio)
            duration = actual_duration if actual_duration > 0.5 else duration

            # 2. Render 3D del personaje y codificacion en paralelo
            from core.video_pipeline_4k import render_video_4k

            if mode == "note":
                # Las videonotas se recortan en circulo: sin HUD y encuadre cerrado
                width, height = 1024, 1024
                hud, char_scale, center, bloom = False, 1.10, (0.5, 0.46), 0.50
            else:
                hud, char_scale, center, bloom = True, 0.86, (0.5, 0.40), 0.55

            with self._render_lock:
                r = render_video_4k(
                    audio_path=temp_audio,
                    word_timings=word_timings,
                    duration=duration,
                    output_path=output_mp4,
                    width=width,
                    height=height,
                    fps=fps,
                    title=title,
                    hud=hud,
                    char_scale=char_scale,
                    center=center,
                    bloom=bloom,
                )

            if not r.get("ok"):
                logger.error(f"Render 3D fallido: {r.get('error')}")
                return {"ok": False, "error": r.get("error")}

            video_bytes = output_mp4.read_bytes()
            elapsed = round(time.time() - t0, 2)
            self._cleanup_old_videos()

            if r.get("over_limit"):
                logger.warning(
                    f"Video de {len(video_bytes)/1048576:.1f} MB supera el limite de subida de Telegram"
                )

            return {
                "ok": True,
                "video_path": str(output_mp4),
                "video_bytes": video_bytes,
                "duration": duration,
                "width": r["width"],
                "height": r["height"],
                "fps": fps,
                "elapsed_s": elapsed,
                "file_size": len(video_bytes),
                "text": text,
                "word_count": len(word_timings),
                "encoder": r.get("encoder"),
                "bitrate_kbps": r.get("bitrate_kbps"),
                "workers": r.get("workers"),
                "over_limit": r.get("over_limit", False),
                "mode": mode,
            }

        except Exception as e:
            logger.error(f"Excepción en generate_speaking_video: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            try:
                if temp_audio.exists():
                    temp_audio.unlink()
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
