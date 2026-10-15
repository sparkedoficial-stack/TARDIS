#!/usr/bin/env python3
"""
tardis_pixelart_math_engine.py - Motor Soberano de Generación de Video Pixel Art & Graficador Matemático TARDIS
=============================================================================================================
GODWORKS SYSTEM v26.4 · Directiva Soberana del Arquitecto (₪) · ChronoVision Core

Modelo de generación de video procedural en Pixel Art de alta fidelidad estética retro:
  1. Renderizado nativo en rejilla de baja resolución discreta (320x180 / 256x256).
  2. Paletas de color indexadas auténticas (Cyberpunk Neon, PICO-8, Chrono TARDIS, Game Boy, Synthwave, Solar Plasma).
  3. Difuminado de matrices ordenadas Bayer 4x4 para simulación de gradientes y campos escalares 8-bit / 16-bit.
  4. Rasterizador de primitivas de píxeles: algoritmos de Bresenham, círculos, estelas de persistencia de fósforo CRT.
  5. Shaders de post-procesado: líneas de escaneo (Scanlines CRT), curvatura y viñeteado.
  6. Tipografía bitmap de píxeles 5x7 integrada para visualización de ecuaciones, simbología griega y HUD de telemetría.
  7. Escalado entero por vecino más cercano (Nearest-Neighbor) a 720p / 1080p sin distorsión ni suavizado borroso.
  8. Graficación de Sistemas Físico-Matemáticos Complejos:
     - Fluido Micropolar Cósmico Reysek-Ocampo (Navier-Stokes + Cosserat + f_RO)
     - Ondas Cuánticas Retrocausales Wheeler-Feynman & Sintropía ECCA V2.0
     - Atractor Caótico No Lineal de Lorenz (RK4 3D con efecto mariposa)
     - Epiciclos de Fourier y Síntesis Armónica de Ondas
     - Geometría Sagrada & Curvas Paramétricas Lissajous / Rosa Polar
     - Fractales Dinámicos del Conjunto de Julia en el Plano Complejo
     - Evaluador de Ecuaciones y Fórmulas Arbitrarias del Usuario
  9. Exportación dual a MP4 (acelerado por GPU NVENC / libx264) y GIF animado en bucle.
  10. Integración con el Sintetizador Acústico Cuántico TARDIS (ensure_video_has_audio) para sonificación obligatoria.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

# Importar sintetizador de audio TARDIS si está disponible
TARDIS_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(TARDIS_ROOT) not in sys.path:
    sys.path.insert(0, str(TARDIS_ROOT))

try:
    from core.tardis_audio_synthesizer import ensure_video_has_audio
    AUDIO_SYNTH_AVAILABLE = True
except Exception:
    AUDIO_SYNTH_AVAILABLE = False

OUTPUT_VIDEOS_DIR = Path("/home/timemachine/Vídeos")
OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

GODWORKS_VIDEOS_DIR = TARDIS_ROOT / "videos"
GODWORKS_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_DIR = Path("/home/timemachine/.gemini/antigravity-cli/brain/c25983f5-e102-4aa5-a88b-f6faf31a7dcf")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 1. MATRICES DE DITHERING Y PALETAS DE COLOR RETRO PIXEL ART
# =============================================================================

# Matriz estándar Bayer 4x4 normalizada en [-0.5, 0.5]
BAYER_4X4 = np.array([
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5]
], dtype=np.float32) / 16.0 - 0.5

PALETTES = {
    "cyber_neon": np.array([
        [3, 7, 18],        # 0: Deep Void
        [10, 17, 40],      # 1: Dark Abyss
        [28, 27, 77],      # 2: Deep Indigo
        [58, 12, 163],     # 3: Midnight Purple
        [114, 9, 183],     # 4: Electric Violet
        [247, 37, 133],    # 5: Hot Magenta
        [255, 0, 85],      # 6: Neon Crimson
        [0, 180, 216],     # 7: Cyber Teal
        [0, 245, 212],     # 8: Laser Cyan
        [144, 224, 239],   # 9: Bright Aqua
        [57, 255, 20],     # 10: Electric Lime
        [255, 183, 3],     # 11: Amber Gold
        [255, 255, 255]    # 12: Pure Neon White
    ], dtype=np.uint8),

    "pico_8": np.array([
        [0, 0, 0],         # 0: Black
        [29, 43, 83],      # 1: Dark Blue
        [126, 37, 83],     # 2: Dark Purple
        [0, 135, 81],      # 3: Dark Green
        [171, 82, 54],     # 4: Brown
        [95, 87, 79],      # 5: Dark Gray
        [194, 195, 199],   # 6: Light Gray
        [255, 241, 232],   # 7: White
        [255, 0, 77],      # 8: Red
        [255, 163, 0],     # 9: Orange
        [255, 236, 39],    # 10: Yellow
        [0, 228, 54],      # 11: Green
        [41, 173, 255],    # 12: Blue
        [131, 118, 156],   # 13: Indigo
        [255, 119, 168],   # 14: Pink
        [255, 204, 170]    # 15: Peach
    ], dtype=np.uint8),

    "chrono_tardis": np.array([
        [2, 8, 20],        # 0: TARDIS Deep Blue
        [5, 25, 55],       # 1: Cosmic Indigo
        [0, 60, 110],      # 2: Oceanic Blue
        [0, 135, 147],     # 3: Time Vortex Cyan
        [0, 191, 114],     # 4: Syntropy Mint
        [249, 168, 38],    # 5: Temporal Gold
        [255, 209, 102],   # 6: Starlight Gold
        [240, 248, 255]    # 7: Aegis White
    ], dtype=np.uint8),

    "gameboy": np.array([
        [15, 56, 15],      # 0: Darkest Green
        [48, 98, 48],      # 1: Dark Green
        [139, 172, 15],    # 2: Light Green
        [155, 188, 15]     # 3: Brightest Phosphor Green
    ], dtype=np.uint8),

    "solar_plasma": np.array([
        [4, 2, 8],         # 0: Void
        [45, 0, 15],       # 1: Burgundy
        [100, 5, 10],      # 2: Dark Crimson
        [180, 20, 10],     # 3: Flame Red
        [230, 80, 10],     # 4: Bright Orange
        [255, 160, 20],    # 5: Solar Amber
        [255, 220, 80],    # 6: Golden Flare
        [255, 255, 220]    # 7: Plasma White
    ], dtype=np.uint8)
}


# =============================================================================
# 2. TIPOGRAFÍA BITMAP PIXEL ART 5x7 EMBEBIDA
# =============================================================================

# Definición matricial de caracteres 5x7 en mapas binarios
FONT_5X7: Dict[str, List[str]] = {
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'B': ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    'C': ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    'F': ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    'G': ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    'H': ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    'I': ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    'J': ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'N': ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    'X': ["10001", "01010", "00100", "00100", "00100", "01010", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    'Z': ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    '0': ["01110", "10011", "10101", "10101", "11001", "10001", "01110"],
    '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    '3': ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["01110", "10000", "11110", "10001", "10001", "10001", "01110"],
    '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    '9': ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    ' ': ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    '.': ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ':': ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '+': ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    '=': ["00000", "11111", "00000", "11111", "00000", "00000", "00000"],
    '/': ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    '[': ["01110", "01000", "01000", "01000", "01000", "01000", "01110"],
    ']': ["01110", "00010", "00010", "00010", "00010", "00010", "01110"],
    '(': ["00110", "01000", "10000", "10000", "10000", "01000", "00110"],
    ')': ["01100", "00010", "00001", "00001", "00001", "00010", "01100"],
    '*': ["00000", "10101", "01110", "11111", "01110", "10101", "00000"],
    '^': ["00100", "01010", "10001", "00000", "00000", "00000", "00000"],
    '<': ["00011", "00110", "01100", "11000", "01100", "00110", "00011"],
    '>': ["11000", "01100", "00110", "00011", "00110", "01100", "11000"],
    '_': ["00000", "00000", "00000", "00000", "00000", "00000", "11111"],
    '|': ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    '~': ["01101", "10010", "00000", "00000", "00000", "00000", "00000"],
    # Glifos matemáticos y físicos especiales
    '\\psi': ["10101", "10101", "10101", "01110", "00100", "00100", "00100"],  # Psi
    '\\omega': ["00000", "10001", "10101", "10101", "01010", "10001", "00000"],  # Omega
    '\\pi':   ["11111", "01010", "01010", "01010", "01010", "01010", "11011"],  # Pi
    '\\sum':  ["11111", "10000", "01000", "00100", "01000", "10000", "11111"],  # Sumatoria
    '\\int':  ["00111", "01000", "01000", "01000", "01000", "00010", "11100"],  # Integral
    '\\nabla':["11111", "10001", "01010", "01010", "00100", "00100", "00000"],  # Nabla
    '\\Delta':["00100", "01010", "01010", "10001", "10001", "11111", "00000"],  # Delta
    '\\partial': ["01110", "10001", "00001", "01111", "10001", "10001", "01110"]  # Derivada parcial
}


# =============================================================================
# 3. LIENZO Y RASTERIZADOR PROCEDURAL PIXEL ART (PixelCanvas)
# =============================================================================

class PixelCanvas:
    """Lienzo de dibujo discreto pixel-art de baja resolución con buffers y shaders."""

    def __init__(self, width: int = 320, height: int = 180, palette_name: str = "cyber_neon"):
        self.width = width
        self.height = height
        self.palette_name = palette_name
        self.palette = PALETTES.get(palette_name, PALETTES["cyber_neon"])
        self.buffer = np.zeros((height, width, 3), dtype=np.uint8)
        self.persistence_buffer = np.zeros((height, width, 3), dtype=np.float32)

    def clear(self, bg_color: Tuple[int, int, int] = (5, 8, 18)):
        """Limpia el buffer con el color base de fondo."""
        self.buffer[:] = bg_color

    def decay_persistence(self, decay_rate: float = 0.82):
        """Decaimiento suave de estelas de fósforo CRT para partículas y dinámicas."""
        self.persistence_buffer *= decay_rate
        self.buffer = np.clip(self.buffer.astype(np.float32) + self.persistence_buffer, 0, 255).astype(np.uint8)

    def set_pixel(self, x: int, y: int, color: Union[Tuple[int, int, int], int], persistent: bool = False):
        """Pinta un píxel discreto asegurando límites espaciales."""
        if 0 <= x < self.width and 0 <= y < self.height:
            if isinstance(color, int):
                c = self.palette[color % len(self.palette)]
            else:
                c = color
            self.buffer[y, x] = c
            if persistent:
                self.persistence_buffer[y, x] = c

    def draw_line(self, x0: int, y0: int, x1: int, y1: int, color: Union[Tuple[int, int, int], int]):
        """Dibuja una línea de píxeles discreta utilizando el algoritmo de Bresenham."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            self.set_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_rect(self, x: int, y: int, w: int, h: int, color: Union[Tuple[int, int, int], int], fill: bool = False):
        """Dibuja o rellena un rectángulo alineado con la rejilla de píxeles."""
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return

        if fill:
            if isinstance(color, int):
                c = self.palette[color % len(self.palette)]
            else:
                c = color
            self.buffer[y0:y1, x0:x1] = c
        else:
            self.draw_line(x, y, x + w - 1, y, color)
            self.draw_line(x, y + h - 1, x + w - 1, y + h - 1, color)
            self.draw_line(x, y, x, y + h - 1, color)
            self.draw_line(x + w - 1, y, x + w - 1, y + h - 1, color)

    def draw_circle(self, cx: int, cy: int, radius: int, color: Union[Tuple[int, int, int], int], fill: bool = False):
        """Dibuja un círculo de píxeles utilizando el algoritmo del punto medio."""
        x = radius
        y = 0
        err = 0

        while x >= y:
            pts = [
                (cx + x, cy + y), (cx + y, cy + x),
                (cx - y, cy + x), (cx - x, cy + y),
                (cx - x, cy - y), (cx - y, cy - x),
                (cx + y, cy - x), (cx + x, cy - y)
            ]
            if fill:
                self.draw_line(cx - x, cy + y, cx + x, cy + y, color)
                self.draw_line(cx - x, cy - y, cx + x, cy - y, color)
                self.draw_line(cx - y, cy + x, cx + y, cy + x, color)
                self.draw_line(cx - y, cy - x, cx + y, cy - x, color)
            else:
                for px, py in pts:
                    self.set_pixel(px, py, color)

            y += 1
            err += 1 + 2 * y
            if 2 * (err - x) + 1 > 0:
                x -= 1
                err += 1 - 2 * x

    def blit_scalar_field(self, field: np.ndarray, region: Optional[Tuple[int, int, int, int]] = None,
                          dither: bool = True, dither_strength: float = 0.45):
        """
        Renderiza un campo escalar continuo 2D mapeado a la paleta indexada con dithering Bayer 4x4.
        field: array 2D normalizado en [0.0, 1.0].
        """
        fh, fw = field.shape
        if region is None:
            rx, ry, rw, rh = 0, 0, self.width, self.height
        else:
            rx, ry, rw, rh = region

        # Redimensionar el campo escalar a la región solicitada
        if (fw, fh) != (rw, rh):
            f_resized = cv2.resize(field, (rw, rh), interpolation=cv2.INTER_LINEAR)
        else:
            f_resized = field

        num_colors = len(self.palette)

        if dither:
            # Crear máscara de Bayer repetida sobre toda la dimensión
            tile_y = (rh + 3) // 4
            tile_x = (rw + 3) // 4
            bayer_grid = np.tile(BAYER_4X4, (tile_y, tile_x))[:rh, :rw]
            dithered = f_resized + (dither_strength * bayer_grid)
            indices = np.clip(np.round(dithered * (num_colors - 1)).astype(int), 0, num_colors - 1)
        else:
            indices = np.clip(np.round(f_resized * (num_colors - 1)).astype(int), 0, num_colors - 1)

        # Mapeo a colores RGB de la paleta
        color_mapped = self.palette[indices]
        self.buffer[ry:ry + rh, rx:rx + rw] = color_mapped

    def draw_text(self, x: int, y: int, text: str, color: Union[Tuple[int, int, int], int], scale: int = 1):
        """Renderiza texto pixel-art usando la fuente matricial 5x7."""
        if isinstance(color, int):
            c = self.palette[color % len(self.palette)]
        else:
            c = color

        cursor_x = x
        i = 0
        while i < len(text):
            # Detectar comandos de símbolos matemáticos (\psi, \omega, \pi, etc.)
            char = text[i]
            matched_glyph = None
            if char == '\\':
                for g in ['\\psi', '\\omega', '\\pi', '\\sum', '\\int', '\\nabla', '\\Delta', '\\partial']:
                    if text[i:].startswith(g):
                        matched_glyph = g
                        i += len(g) - 1
                        break

            if matched_glyph is None:
                matched_glyph = char.upper()

            matrix = FONT_5X7.get(matched_glyph, FONT_5X7.get(' '))

            for row_idx, row in enumerate(matrix):
                for col_idx, bit in enumerate(row):
                    if bit == '1':
                        for sx in range(scale):
                            for sy in range(scale):
                                px = cursor_x + col_idx * scale + sx
                                py = y + row_idx * scale + sy
                                if 0 <= px < self.width and 0 <= py < self.height:
                                    self.buffer[py, px] = c

            cursor_x += (5 + 1) * scale
            i += 1

    def draw_hud_box(self, x: int, y: int, w: int, h: int, title: str = "",
                     border_color: Union[Tuple[int, int, int], int] = (0, 245, 212),
                     bg_color: Tuple[int, int, int] = (6, 12, 28)):
        """Dibuja una caja HUD retro con borde de píxeles y título."""
        self.draw_rect(x, y, w, h, bg_color, fill=True)
        self.draw_rect(x, y, w, h, border_color, fill=False)
        # Esquinas decorativas arcade
        self.set_pixel(x, y, (255, 255, 255))
        self.set_pixel(x + w - 1, y, (255, 255, 255))
        self.set_pixel(x, y + h - 1, (255, 255, 255))
        self.set_pixel(x + w - 1, y + h - 1, (255, 255, 255))
        if title:
            self.draw_rect(x + 4, y - 4, len(title) * 6 + 4, 8, bg_color, fill=True)
            self.draw_text(x + 6, y - 3, title, border_color, scale=1)

    def draw_meter_bar(self, x: int, y: int, w: int, h: int, value: float,
                       color: Union[Tuple[int, int, int], int] = (247, 37, 133),
                       border_color: Union[Tuple[int, int, int], int] = (0, 180, 216)):
        """Barra de telemetría de energía/fuerza tipo arcade."""
        self.draw_rect(x, y, w, h, (10, 15, 30), fill=True)
        self.draw_rect(x, y, w, h, border_color, fill=False)
        fill_w = int(max(0.0, min(1.0, value)) * (w - 2))
        if fill_w > 0:
            self.draw_rect(x + 1, y + 1, fill_w, h - 2, color, fill=True)

    def get_upscaled_frame(self, scale: int = 4, scanlines: bool = True,
                           scanline_intensity: float = 0.22) -> np.ndarray:
        """
        Escala la imagen por vecino más cercano a alta resolución (ej. 320x180 x 4 = 1280x720)
        y aplica el shader de scanlines CRT.
        """
        out_w = self.width * scale
        out_h = self.height * scale
        upscaled = cv2.resize(self.buffer, (out_w, out_h), interpolation=cv2.INTER_NEAREST)

        if scanlines and scale >= 2:
            # Atenuar filas alternas simulando el haz de electrones CRT
            mask = np.ones((out_h, 1, 1), dtype=np.float32)
            # Para cada ciclo de 'scale' píxeles, oscurecer la línea divisoria
            mask[::scale] = 1.0 - scanline_intensity
            upscaled = np.clip(upscaled.astype(np.float32) * mask, 0, 255).astype(np.uint8)

        return upscaled


# =============================================================================
# 4. MODELOS GENERATIVOS DE FÓRMULAS MATEMÁTICAS EN PIXEL ART
# =============================================================================

class BasePixelMathSystem:
    """Clase base para sistemas matemáticos renderizados en pixel art."""

    def __init__(self, canvas: PixelCanvas):
        self.canvas = canvas
        self.w = canvas.width
        self.h = canvas.height

    def reset(self):
        pass

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        raise NotImplementedError


# -----------------------------------------------------------------------------
# 4.1 FÓRMULA 1: FLUIDO MICROPOLAR CÓSMICO REYSEK-OCAMPO
# -----------------------------------------------------------------------------
class ReysekOcampoMicropolarSystem(BasePixelMathSystem):
    r"""
    Simulación y visualización Pixel Art del Fluido Micropolar Reysek-Ocampo:
      \rho(\partial_t u + u \cdot \nabla u) = -\nabla p + (\mu + \mu_r)\Delta u + 2\mu_r(\nabla \times \omega) + f_{R-O}
      f_{R-O} = 2\nu_r(\nabla \times \omega_{vib}) + (\nabla h_{topo}) \times u - \beta\nabla u + k(d_0/d)^2 \hat{r}
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)
        self.n_particles = 140
        np.random.seed(42)
        self.px = np.random.uniform(20, self.w - 20, self.n_particles)
        self.py = np.random.uniform(20, self.h - 20, self.n_particles)

        # Precalcular rejilla de coordenadas espaciales centradas
        gx = np.linspace(-3.0, 3.0, self.w)
        gy = np.linspace(-1.7, 1.7, self.h)
        self.X, self.Y = np.meshgrid(gx, gy)
        self.R = np.sqrt(self.X**2 + self.Y**2) + 0.15

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        self.canvas.decay_persistence(decay_rate=0.75)

        # 1. Campo de vorticidad Cosserat y potencial topológico
        vort_phase = t * 2.2
        omega = (np.sin(self.X * 1.5 + vort_phase) * np.cos(self.Y * 1.5 - vort_phase * 0.7)) / (self.R**0.6)
        # Fuerza topológica f_RO
        f_ro = 0.5 * np.cos(self.X * self.Y + t * 1.8) / (self.R**0.8)
        scalar_energy = (omega * 0.6 + f_ro * 0.4)
        norm_field = np.clip((scalar_energy - scalar_energy.min()) / (scalar_energy.max() - scalar_energy.min() + 1e-6), 0.0, 1.0)

        # Blit del campo escalar de fondo con dithering Bayer
        self.canvas.blit_scalar_field(norm_field, dither=True, dither_strength=0.38)

        # 2. Vórtices centrales y flujo u(x,y,t)
        u_x = -self.Y / (self.R**1.3) * (1.2 + 0.3 * np.sin(3 * t))
        u_y =  self.X / (self.R**1.3) * (1.2 + 0.3 * np.cos(3 * t))

        # 3. Actualizar partículas trazadoras con estelas de fósforo
        cx, cy = self.w // 2, self.h // 2
        for i in range(self.n_particles):
            # Muestrear velocidades del campo en la posición de la partícula
            grid_x = int(np.clip(self.px[i], 0, self.w - 1))
            grid_y = int(np.clip(self.py[i], 0, self.h - 1))

            vx = u_x[grid_y, grid_x] * 12.0
            vy = u_y[grid_y, grid_x] * 12.0

            # Fuerza de atracción a la singularidad central
            dx = cx - self.px[i]
            dy = cy - self.py[i]
            dist = math.sqrt(dx**2 + dy**2) + 1.0
            vx += (dx / dist) * 1.2
            vy += (dy / dist) * 1.2

            self.px[i] += vx * 0.12
            self.py[i] += vy * 0.12

            # Regenerar si colapsa al centro o sale de pantalla
            if dist < 4 or self.px[i] < 4 or self.px[i] > self.w - 4 or self.py[i] < 4 or self.py[i] > self.h - 4:
                angle = np.random.uniform(0, 2 * math.pi)
                rad = np.random.uniform(50, 110)
                self.px[i] = cx + rad * math.cos(angle)
                self.py[i] = cy + rad * math.sin(angle)

            # Pintar partícula con color neón
            p_color = (0, 245, 212) if i % 2 == 0 else (247, 37, 133)
            self.canvas.set_pixel(int(self.px[i]), int(self.py[i]), p_color, persistent=True)

        # 4. Singularidad Macro Central (v > c)
        sing_radius = int(5 + 2 * math.sin(t * 8))
        self.canvas.draw_circle(cx, cy, sing_radius, (255, 0, 85), fill=True)
        self.canvas.draw_circle(cx, cy, sing_radius + 3, (255, 183, 3), fill=False)
        self.canvas.set_pixel(cx, cy, (255, 255, 255))

        # 5. Interfaz HUD Arcade / Cockpit TARDIS
        self.canvas.draw_hud_box(4, 4, 180, 42, title="REYSEK-OCAMPO COSMIC FLUID")
        self.canvas.draw_text(8, 10, "FLUIDO MICROPOLAR COSSERAT", (0, 245, 212), scale=1)
        self.canvas.draw_text(8, 20, "\\rho(\\partial t u+u\\cdot\\nabla u)=-\\nabla P+fRO", (255, 255, 255), scale=1)
        self.canvas.draw_text(8, 30, f"VORTICIDAD: {abs(math.sin(t*2)*3.14):.2f} RAD/S", (255, 183, 3), scale=1)

        # Telemetría de fuerza topológica
        self.canvas.draw_hud_box(self.w - 96, 4, 92, 38, title="||f_RO||")
        energy_val = 0.5 + 0.45 * math.sin(t * 3.5)
        self.canvas.draw_meter_bar(self.w - 90, 14, 80, 8, energy_val, color=(255, 0, 85))
        self.canvas.draw_text(self.w - 90, 26, f"F_RO: {energy_val * 14.8:.1f} kN", (144, 224, 239), scale=1)

        # Estado del núcleo
        self.canvas.draw_hud_box(4, self.h - 18, 140, 14)
        self.canvas.draw_text(8, self.h - 14, "SINGULARIDAD: v > c [SUPERLUM.]", (57, 255, 20), scale=1)


# -----------------------------------------------------------------------------
# 4.2 FÓRMULA 2: ONDAS CUÁNTICAS RETROCAUSALES WHEELER-FEYNMAN & SINTROPÍA
# -----------------------------------------------------------------------------
class RetrocausalSyntropySystem(BasePixelMathSystem):
    r"""
    Visualización de la Ecuación Retrocausal Wheeler-Feynman & Sintropía ECCA V2.0:
      \Psi_{Retro}(t_0) = \Lambda_{Aegis} \int_{\mathcal{H}} \mathcal{D}[\gamma] \Phi_{adv}(t_f, t_0) \exp((i/\hbar)S_{geom} - \eta \int \nabla S_{ent} d\tau)
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)
        self.x_vals = np.linspace(-6.0, 6.0, self.w)
        self.history_entropy = []

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        self.canvas.clear(bg_color=(2, 6, 18))

        # Rejilla cuántica de fondo (espaciotiempo discretizado)
        for gy in range(0, self.h, 12):
            for gx in range(0, self.w, 12):
                self.canvas.set_pixel(gx, gy, (20, 35, 65))

        mid_y = self.h // 2 - 8
        v = 2.0
        k = 4.5
        omega = 5.0

        # Paquete Retardado (avanza hacia el futuro, de izquierda a derecha)
        center_ret = -4.0 + (v * t) % 8.0
        env_ret = np.exp(-((self.x_vals - center_ret) ** 2) / 1.5)
        wave_ret = env_ret * np.cos(k * self.x_vals - omega * t)

        # Paquete Avanzado (retrocausal, avanza hacia el pasado, de derecha a izquierda)
        center_adv = 4.0 - (v * t) % 8.0
        env_adv = np.exp(-((self.x_vals - center_adv) ** 2) / 1.5)
        wave_adv = env_adv * np.cos(k * self.x_vals + omega * t)

        # Superposición cuántica e interferencia sintrópica
        psi_total = wave_ret + wave_adv
        prob_density = psi_total**2

        # 1. Dibujar Pozo de Resonancia Central \Lambda_{Aegis}
        well_cx = self.w // 2
        self.canvas.draw_line(well_cx - 24, mid_y - 35, well_cx - 24, mid_y + 35, (58, 12, 163))
        self.canvas.draw_line(well_cx + 24, mid_y - 35, well_cx + 24, mid_y + 35, (58, 12, 163))

        # Barras de densidad de probabilidad |Psi|^2 con efecto neón
        scale_amp = 30.0
        for ix in range(0, self.w, 2):
            dens = prob_density[ix]
            bar_h = int(dens * scale_amp)
            if bar_h > 0:
                col = (0, 245, 212) if abs(self.x_vals[ix]) < 1.5 else (114, 9, 183)
                self.canvas.draw_line(ix, mid_y - bar_h // 2, ix, mid_y + bar_h // 2, col)

        # 2. Dibujar curvas de onda individuales
        for ix in range(self.w - 1):
            y_ret_0 = int(mid_y - wave_ret[ix] * 18.0)
            y_ret_1 = int(mid_y - wave_ret[ix + 1] * 18.0)
            self.canvas.draw_line(ix, y_ret_0, ix + 1, y_ret_1, (0, 180, 216))

            y_adv_0 = int(mid_y - wave_adv[ix] * 18.0)
            y_adv_1 = int(mid_y - wave_adv[ix + 1] * 18.0)
            self.canvas.draw_line(ix, y_adv_0, ix + 1, y_adv_1, (247, 37, 133))

        # Eje temporal central
        self.canvas.draw_line(0, mid_y, self.w, mid_y, (30, 45, 80))

        # 3. Osciloscopio de Sintropía vs Entropía (Parte inferior)
        osc_y = self.h - 38
        self.canvas.draw_rect(4, osc_y, self.w - 8, 34, (5, 10, 25), fill=True)
        self.canvas.draw_rect(4, osc_y, self.w - 8, 34, (0, 180, 216), fill=False)

        # Curva de disipación de entropía exp(-\eta \tau) y aumento de sintropía
        cur_entropy = math.exp(-0.45 * (t % 6.0))
        cur_syntropy = 1.0 - cur_entropy
        self.history_entropy.append((cur_entropy, cur_syntropy))
        if len(self.history_entropy) > self.w - 40:
            self.history_entropy.pop(0)

        for hist_i in range(len(self.history_entropy) - 1):
            e0, s0 = self.history_entropy[hist_i]
            e1, s1 = self.history_entropy[hist_i + 1]
            px0 = 20 + hist_i
            px1 = 20 + hist_i + 1
            # Entropía en rojo-fucsia
            self.canvas.draw_line(px0, int(osc_y + 30 - e0 * 24), px1, int(osc_y + 30 - e1 * 24), (255, 0, 85))
            # Sintropía en verde neón
            self.canvas.draw_line(px0, int(osc_y + 30 - s0 * 24), px1, int(osc_y + 30 - s1 * 24), (57, 255, 20))

        self.canvas.draw_text(self.w - 110, osc_y + 4, "SINTROPÍA: +99.4%", (57, 255, 20), scale=1)
        self.canvas.draw_text(self.w - 110, osc_y + 14, "ENTROPÍA: \\nabla S -> 0", (255, 0, 85), scale=1)

        # 4. HUD Superior
        self.canvas.draw_hud_box(4, 4, 210, 42, title="WHEELER-FEYNMAN & ECCA V2.0")
        self.canvas.draw_text(8, 10, "INTERFERENCIA RETROCAUSAL", (247, 37, 133), scale=1)
        self.canvas.draw_text(8, 20, "\\psi RETRO=\\Lambda AEGIS \\int D[\\gamma]\\Phi ADV exp(i/h S)", (255, 255, 255), scale=1)
        self.canvas.draw_text(8, 30, "ONDA AVANZADA (t<0) + RETARDADA (t>0)", (0, 245, 212), scale=1)

        # Blindaje Aegis
        self.canvas.draw_hud_box(self.w - 96, 4, 92, 38, title="AEGIS SHIELD")
        self.canvas.draw_text(self.w - 90, 14, "ESTADO: BLOQUEADO", (57, 255, 20), scale=1)
        self.canvas.draw_text(self.w - 90, 26, "FREC: 432 Hz SINT", (255, 183, 3), scale=1)


# -----------------------------------------------------------------------------
# 4.3 FÓRMULA 3: ATRACTOR CAÓTICO NO LINEAL DE LORENZ (RK4 3D)
# -----------------------------------------------------------------------------
class LorenzAttractorSystem(BasePixelMathSystem):
    r"""
    Simulación numérica RK4 del sistema dinámico no lineal de Lorenz:
      \dot{x} = \sigma (y - x)
      \dot{y} = x (\rho - z) - y
      \dot{z} = x y - \beta z
    Renderizado con proyección 3D rotatoria y persistencia de fósforo CRT.
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)
        self.sigma = 10.0
        self.rho = 28.0
        self.beta = 8.0 / 3.0

        # Semillas de partículas con perturbaciones mínimas (\delta x = 10^-5)
        self.particles = [
            np.array([1.0, 1.0, 20.0]),
            np.array([1.0001, 1.0, 20.0]),
            np.array([1.0, 1.0001, 20.0]),
            np.array([-1.0, -1.0, 20.0])
        ]
        self.colors = [
            (0, 245, 212),    # Cyan
            (247, 37, 133),   # Magenta
            (255, 183, 3),    # Gold
            (57, 255, 20)     # Lime
        ]
        self.step_size = 0.008

    def derivatives(self, state: np.ndarray) -> np.ndarray:
        x, y, z = state
        dx = self.sigma * (y - x)
        dy = x * (self.rho - z) - y
        dz = x * y - self.beta * z
        return np.array([dx, dy, dz])

    def rk4_step(self, state: np.ndarray, dt: float) -> np.ndarray:
        k1 = self.derivatives(state)
        k2 = self.derivatives(state + 0.5 * dt * k1)
        k3 = self.derivatives(state + 0.5 * dt * k2)
        k4 = self.derivatives(state + dt * k3)
        return state + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    def project_3d(self, x: float, y: float, z: float, angle: float) -> Tuple[int, int]:
        # Rotación alrededor del eje Z y elevación Y
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        rz = z - 25.0

        # Proyección isométrica/perspectiva a la pantalla de píxeles
        screen_x = int(self.w // 2 + rx * 5.2 - ry * 1.5)
        screen_y = int(self.h // 2 + 10 - rz * 3.8 + ry * 1.2)
        return screen_x, screen_y

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        self.canvas.decay_persistence(decay_rate=0.88)

        rot_angle = t * 0.45

        # Avanzar varios pasos RK4 por frame para dibujar trazos continuos
        sub_steps = 14
        for _ in range(sub_steps):
            for p_idx in range(len(self.particles)):
                old_state = self.particles[p_idx].copy()
                new_state = self.rk4_step(old_state, self.step_size)
                self.particles[p_idx] = new_state

                x0, y0 = self.project_3d(old_state[0], old_state[1], old_state[2], rot_angle)
                x1, y1 = self.project_3d(new_state[0], new_state[1], new_state[2], rot_angle)

                self.canvas.draw_line(x0, y0, x1, y1, self.colors[p_idx])
                # Registrar en buffer de persistencia
                self.canvas.set_pixel(x1, y1, self.colors[p_idx], persistent=True)

        # Proyección de Espacio de Fases 2D en recuadros secundarios (HUD)
        # 1. Proyección (x, z)
        box_w, box_h = 60, 48
        bx, by = 6, self.h - box_h - 6
        self.canvas.draw_hud_box(bx, by, box_w, box_h, title="X-Z PHASE")
        p0 = self.particles[0]
        f_px = int(bx + box_w // 2 + p0[0] * 1.1)
        f_pz = int(by + box_h - 4 - p0[2] * 0.8)
        self.canvas.set_pixel(f_px, f_pz, (0, 245, 212), persistent=True)

        # 2. Proyección (x, y)
        bx2 = bx + box_w + 4
        self.canvas.draw_hud_box(bx2, by, box_w, box_h, title="X-Y PHASE")
        f_py = int(by + box_h // 2 + p0[1] * 1.1)
        self.canvas.set_pixel(f_px, f_py, (247, 37, 133), persistent=True)

        # HUD Superior
        self.canvas.draw_hud_box(4, 4, 185, 42, title="LORENZ CHAOTIC ATTRACTOR")
        self.canvas.draw_text(8, 10, "SISTEMA DINAMICO NO LINEAL", (255, 183, 3), scale=1)
        self.canvas.draw_text(8, 20, "dx/dt=\\sigma(y-x) dy/dt=x(\\rho-z)-y", (255, 255, 255), scale=1)
        self.canvas.draw_text(8, 30, f"X:{p0[0]:+06.2f} Y:{p0[1]:+06.2f} Z:{p0[2]:+06.2f}", (0, 245, 212), scale=1)

        # Indicador de régimen caótico
        self.canvas.draw_hud_box(self.w - 100, 4, 96, 38, title="LYAPUNOV")
        self.canvas.draw_text(self.w - 94, 14, "\\lambda 1 = +0.9056", (57, 255, 20), scale=1)
        self.canvas.draw_text(self.w - 94, 26, "CAOS DETERMINISTA", (255, 0, 85), scale=1)


# -----------------------------------------------------------------------------
# 4.4 FÓRMULA 4: EPICICLOS DE FOURIER Y SÍNTESIS DE ONDAS
# -----------------------------------------------------------------------------
class FourierEpicyclesSystem(BasePixelMathSystem):
    r"""
    Visualización de Epiciclos de Fourier y síntesis armónica de onda cuadrada:
      f(t) = \sum_{k=1}^N \frac{4}{\pi (2k - 1)} \sin((2k - 1)\omega t)
    Epiciclos rotatorios conectados por radios vectores trazando la onda en osciloscopio continuo.
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)
        self.wave_history: List[int] = []
        self.max_harmonics = 5

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        self.canvas.clear(bg_color=(3, 8, 20))

        # Rejilla de osciloscopio
        for gx in range(130, self.w - 6, 16):
            self.canvas.draw_line(gx, 44, gx, self.h - 10, (12, 22, 45))
        for gy in range(44, self.h - 10, 16):
            self.canvas.draw_line(130, gy, self.w - 6, gy, (12, 22, 45))

        # Centro de los epiciclos
        cx = 64
        cy = self.h // 2 + 15
        cur_x = cx
        cur_y = cy

        omega = 2.4
        base_radius = 42.0

        # Dibujar cada epiciclo armónico (armónicos impares k = 1, 3, 5, 7, 9)
        for n in range(self.max_harmonics):
            k = 2 * n + 1
            radius = int(base_radius * (4.0 / (math.pi * k)))
            prev_x, prev_y = cur_x, cur_y

            angle = k * omega * t
            cur_x += int(radius * math.cos(angle))
            cur_y += int(radius * math.sin(angle))

            # Círculo del epiciclo en píxeles
            self.canvas.draw_circle(prev_x, prev_y, radius, (28, 55, 95), fill=False)
            # Radio vector
            vec_color = (0, 245, 212) if n == 0 else (114, 9, 183)
            self.canvas.draw_line(prev_x, prev_y, cur_x, cur_y, vec_color)
            self.canvas.set_pixel(cur_x, cur_y, (255, 255, 255))

        # Registrar la posición vertical trazada en el osciloscopio
        self.wave_history.insert(0, cur_y)
        max_history = self.w - 140
        if len(self.wave_history) > max_history:
            self.wave_history.pop()

        # Línea guía conectora desde el epiciclo final hasta la onda
        wave_start_x = 135
        self.canvas.draw_line(cur_x, cur_y, wave_start_x, self.wave_history[0], (255, 183, 3))

        # Trazar la onda generada en el osciloscopio
        for i in range(len(self.wave_history) - 1):
            px0 = wave_start_x + i
            py0 = self.wave_history[i]
            px1 = wave_start_x + i + 1
            py1 = self.wave_history[i + 1]
            self.canvas.draw_line(px0, py0, px1, py1, (0, 245, 212))

        # HUD Superior
        self.canvas.draw_hud_box(4, 4, 205, 36, title="FOURIER SERIES & EPICYCLES")
        self.canvas.draw_text(8, 10, "SINTESIS ARMONICA DE ONDA", (0, 245, 212), scale=1)
        self.canvas.draw_text(8, 20, "f(t)=\\sum [4/(\\pi k)] \\sin(k \\omega t)", (255, 255, 255), scale=1)

        # Barras de espectro de Fourier
        bx = self.w - 105
        self.canvas.draw_hud_box(bx, 4, 100, 36, title="FFT SPECTRUM")
        for bar_idx in range(self.max_harmonics):
            k = 2 * bar_idx + 1
            amp = 1.0 / k
            bh = int(amp * 16)
            self.canvas.draw_rect(bx + 8 + bar_idx * 18, 34 - bh, 10, bh, (247, 37, 133), fill=True)


# -----------------------------------------------------------------------------
# 4.5 FÓRMULA 5: GEOMETRÍA SAGRADA Y ARMONICOS LISSAJOUS
# -----------------------------------------------------------------------------
class SacredLissajousSystem(BasePixelMathSystem):
    r"""
    Visualización de curvas paramétricas de Lissajous y Rosas Polares armónicas:
      x(\theta) = A \sin(a \theta + \delta(t)), \quad y(\theta) = B \cos(b \theta)
      r(\theta, t) = R \cos(k(t) \theta)
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        self.canvas.decay_persistence(decay_rate=0.82)

        # Modulación armónica de frecuencias y desfase
        a = 3.0
        b = 4.0
        delta = t * 1.8
        cx = self.w // 2
        cy = self.h // 2 + 8
        scale_r = 52.0

        n_pts = 220
        thetas = np.linspace(0, 2 * math.pi, n_pts)

        # 1. Curva de Lissajous
        lx = cx + (scale_r * np.sin(a * thetas + delta)).astype(int)
        ly = cy + (scale_r * np.cos(b * thetas)).astype(int)

        for i in range(n_pts - 1):
            col_idx = int((i / n_pts) * (len(self.canvas.palette) - 1))
            self.canvas.draw_line(lx[i], ly[i], lx[i + 1], ly[i + 1], col_idx)
            self.canvas.set_pixel(lx[i], ly[i], col_idx, persistent=True)

        # 2. Rosa Polar centrada en el interior
        k_rose = 3.0 + math.sin(t * 0.8) * 1.5
        r_polar = (scale_r * 0.45 * np.cos(k_rose * thetas))
        rx = cx + (r_polar * np.cos(thetas + t * 0.5)).astype(int)
        ry = cy + (r_polar * np.sin(thetas + t * 0.5)).astype(int)

        for i in range(n_pts - 1):
            self.canvas.draw_line(rx[i], ry[i], rx[i + 1], ry[i + 1], (255, 183, 3))

        # HUD Superior
        self.canvas.draw_hud_box(4, 4, 195, 36, title="LISSAJOUS & SACRED GEOMETRY")
        self.canvas.draw_text(8, 10, f"RATIO ARMONICO a:b = {int(a)}:{int(b)}", (0, 245, 212), scale=1)
        self.canvas.draw_text(8, 20, f"DESFASE \\delta(t)={delta % (2*math.pi):.2f} RAD", (247, 37, 133), scale=1)

        # Información Polar
        self.canvas.draw_hud_box(self.w - 100, 4, 96, 36, title="ROSA POLAR")
        self.canvas.draw_text(self.w - 94, 10, f"r=R \\cos({k_rose:.1f} \\theta)", (255, 255, 255), scale=1)
        self.canvas.draw_text(self.w - 94, 20, "SIMETRIA N-PETALOS", (57, 255, 20), scale=1)


# -----------------------------------------------------------------------------
# 4.6 FÓRMULA 6: FRACTAL DINÁMICO DE JULIA EN EL PLANO COMPLEJO
# -----------------------------------------------------------------------------
class DynamicJuliaFractalSystem(BasePixelMathSystem):
    r"""
    Simulación fractal del conjunto de Julia morphing dinámico:
      z_{n+1} = z_n^2 + c(t), \quad c(t) = R e^{i \omega t}
    Renderizado con difuminado Bayer sobre la cuadrícula del plano complejo.
    """

    def __init__(self, canvas: PixelCanvas):
        super().__init__(canvas)
        # Rejilla compleja optimizada
        self.gx = np.linspace(-1.6, 1.6, self.w).astype(np.float32)
        self.gy = np.linspace(-0.95, 0.95, self.h).astype(np.float32)
        self.ZX, self.ZY = np.meshgrid(self.gx, self.gy)

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        # Parámetro complejo que orbita en el plano de Mandelbrot
        c_real = -0.7 + 0.12 * math.cos(t * 1.4)
        c_imag = 0.27015 + 0.08 * math.sin(t * 1.4)

        zx = self.ZX.copy()
        zy = self.ZY.copy()
        escape_iter = np.zeros(zx.shape, dtype=np.float32)
        max_iter = 24

        mask = np.ones(zx.shape, dtype=bool)

        for n in range(max_iter):
            if not np.any(mask):
                break
            # z = z^2 + c
            zx2 = zx[mask] ** 2
            zy2 = zy[mask] ** 2
            zy[mask] = 2.0 * zx[mask] * zy[mask] + c_imag
            zx[mask] = zx2 - zy2 + c_real

            escaped = (zx2 + zy2) > 4.0
            escaped_indices = np.where(mask)
            sub_escaped = escaped_indices[0][escaped], escaped_indices[1][escaped]
            escape_iter[sub_escaped] = n
            mask[sub_escaped] = False

        # Los que no escaparon quedan al máximo
        escape_iter[mask] = max_iter
        norm_fractal = escape_iter / float(max_iter)

        # Mapear a través del shader Bayer 4x4
        self.canvas.blit_scalar_field(norm_fractal, dither=True, dither_strength=0.35)

        # HUD Superior e información del plano complejo
        self.canvas.draw_hud_box(4, 4, 180, 36, title="JULIA SET DYNAMICS")
        self.canvas.draw_text(8, 10, "FRACTAL EN EL PLANO COMPLEJO", (0, 245, 212), scale=1)
        self.canvas.draw_text(8, 20, f"c = {c_real:+.3f} {c_imag:+.3f} i", (255, 183, 3), scale=1)

        self.canvas.draw_hud_box(self.w - 100, 4, 96, 36, title="ESCAPE DEPTH")
        self.canvas.draw_text(self.w - 94, 10, f"MAX ITER: {max_iter}", (255, 255, 255), scale=1)
        self.canvas.draw_text(self.w - 94, 20, "DITHER: BAYER 4x4", (247, 37, 133), scale=1)


# -----------------------------------------------------------------------------
# 4.7 FÓRMULA 7: EVALUADOR DE ECUACIONES ARBITRARIAS DEL USUARIO
# -----------------------------------------------------------------------------
class CustomFormulaSystem(BasePixelMathSystem):
    """
    Compilador dinámico y graficador de fórmulas arbitrarias 2D: z = f(x, y, t).
    """

    def __init__(self, canvas: PixelCanvas, formula_expr: str):
        super().__init__(canvas)
        self.formula_expr = formula_expr
        self.gx = np.linspace(-3.0, 3.0, self.w).astype(np.float32)
        self.gy = np.linspace(-1.7, 1.7, self.h).astype(np.float32)
        self.X, self.Y = np.meshgrid(self.gx, self.gy)
        self.R = np.sqrt(self.X**2 + self.Y**2) + 1e-4

        # Espacio de nombres seguro para evaluación numérica
        self.safe_globals = {
            "np": np,
            "sin": np.sin,
            "cos": np.cos,
            "tan": np.tan,
            "exp": np.exp,
            "sqrt": np.sqrt,
            "abs": np.abs,
            "arctan2": np.arctan2,
            "pi": math.pi,
            "e": math.e
        }

    def update_frame(self, t: float, frame_idx: int, total_frames: int):
        local_scope = {"x": self.X, "y": self.Y, "r": self.R, "t": t}
        try:
            raw_field = eval(self.formula_expr, self.safe_globals, local_scope)
            if not isinstance(raw_field, np.ndarray):
                raw_field = np.full_like(self.X, float(raw_field))
        except Exception:
            # Fallback a onda sinusoidal armónica
            raw_field = np.sin(self.R * 4.0 - t * 3.0)

        # Normalizar a [0, 1]
        f_min, f_max = np.min(raw_field), np.max(raw_field)
        if abs(f_max - f_min) < 1e-6:
            norm_f = np.zeros_like(raw_field)
        else:
            norm_f = (raw_field - f_min) / (f_max - f_min)

        self.canvas.blit_scalar_field(norm_f, dither=True, dither_strength=0.40)

        # HUD
        self.canvas.draw_hud_box(4, 4, 210, 36, title="CUSTOM MATHEMATICAL FORMULA")
        self.canvas.draw_text(8, 10, f"EXPR: {self.formula_expr[:28]}", (0, 245, 212), scale=1)
        self.canvas.draw_text(8, 20, f"TIEMPO: t = {t:.2f} s", (255, 183, 3), scale=1)


# =============================================================================
# 5. ORQUESTADOR Y MOTOR DE SÍNTESIS DE VIDEO PIXEL ART (TardisPixelArtEngine)
# =============================================================================

class TardisPixelArtEngine:
    """Orquestador Soberano de Generación Cinemática Pixel Art para TARDIS."""

    def __init__(self,
                 native_res: Tuple[int, int] = (320, 180),
                 scale: int = 4,
                 palette: str = "cyber_neon",
                 fps: int = 30):
        self.native_w, self.native_h = native_res
        self.scale = scale
        self.palette = palette
        self.fps = fps
        self.out_w = self.native_w * scale
        self.out_h = self.native_h * scale

    def create_system(self, formula_key: str, custom_expr: str = "") -> BasePixelMathSystem:
        canvas = PixelCanvas(self.native_w, self.native_h, palette_name=self.palette)
        key = formula_key.lower().strip()

        if key in ["reysek_ocampo", "cosmic_fluid", "micropolar", "fluido"]:
            return ReysekOcampoMicropolarSystem(canvas)
        elif key in ["retrocausal", "wheeler_feynman", "syntropy", "sintropia"]:
            return RetrocausalSyntropySystem(canvas)
        elif key in ["lorenz", "chaos", "caos", "atractor"]:
            return LorenzAttractorSystem(canvas)
        elif key in ["fourier", "epicycles", "epiciclos", "ondas"]:
            return FourierEpicyclesSystem(canvas)
        elif key in ["lissajous", "sacred_geometry", "geometria_sagrada"]:
            return SacredLissajousSystem(canvas)
        elif key in ["julia", "fractal", "mandelbrot"]:
            return DynamicJuliaFractalSystem(canvas)
        elif key in ["custom", "formula"]:
            expr = custom_expr if custom_expr else "sin(r*4.0 - t*3.0)"
            return CustomFormulaSystem(canvas, expr)
        else:
            # Por defecto, Fluido Micropolar Reysek-Ocampo
            return ReysekOcampoMicropolarSystem(canvas)

    def render_video(self,
                     formula_key: str,
                     duration_sec: int = 5,
                     output_name: str = "",
                     custom_expr: str = "",
                     scanlines: bool = True) -> Tuple[Path, Path]:
        """
        Sintetiza de forma autónoma el video MP4 acelerado y el GIF en bucle.
        Inyecta automáticamente la pista de audio sintrópico TARDIS.
        """
        if not output_name:
            output_name = f"tardis_pixelart_{formula_key}"

        mp4_path = OUTPUT_VIDEOS_DIR / f"{output_name}.mp4"
        gif_path = OUTPUT_VIDEOS_DIR / f"{output_name}.gif"

        system = self.create_system(formula_key, custom_expr)
        total_frames = self.fps * duration_sec
        dt = 1.0 / self.fps

        print(f"[PIXELART-ENGINE] Sintetizando Video '{output_name}':")
        print(f"  • Resolución Nativa: {self.native_w}x{self.native_h} | Escalado: {self.scale}x -> {self.out_w}x{self.out_h}")
        print(f"  • Paleta: {self.palette} | FPS: {self.fps} | Duración: {duration_sec} s ({total_frames} cuadros)")

        # Preparar grabador de video temporal con OpenCV
        temp_mp4 = OUTPUT_VIDEOS_DIR / f"temp_{output_name}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(temp_mp4), fourcc, self.fps, (self.out_w, self.out_h))

        gif_frames: List[Image.Image] = []
        gif_stride = max(1, self.fps // 15)  # Muestrear a ~15 FPS para el GIF animado

        t0 = time.time()
        for frame_idx in range(total_frames):
            t = frame_idx * dt
            system.update_frame(t, frame_idx, total_frames)
            frame_rgb = system.canvas.get_upscaled_frame(scale=self.scale, scanlines=scanlines)

            # Escribir frame BGR a OpenCV VideoWriter
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            writer.write(frame_bgr)

            # Acumular frames para GIF animado
            if frame_idx % gif_stride == 0:
                # Reducir ligeramente para GIF liviano
                gif_img = Image.fromarray(frame_rgb).resize((self.native_w * 2, self.native_h * 2), Image.Resampling.NEAREST)
                gif_frames.append(gif_img.convert("P", palette=Image.Palette.ADAPTIVE, colors=64))

        writer.release()
        elapsed = time.time() - t0
        print(f"[PIXELART-ENGINE] Renderizado visual completado en {elapsed:.2f} s ({total_frames/elapsed:.1f} fps).")

        # 1. Re-codificar a H.264 definitivo con ffmpeg para máxima compatibilidad y compresión
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_mp4),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-crf", "18",
            str(mp4_path)
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if temp_mp4.exists():
                temp_mp4.unlink()
        except Exception:
            # Fallback si ffmpeg falla: renombrar temporal
            if temp_mp4.exists():
                shutil.move(temp_mp4, mp4_path)

        # 2. Guardar GIF animado
        if gif_frames:
            gif_frames[0].save(
                str(gif_path),
                save_all=True,
                append_images=gif_frames[1:],
                duration=int(1000 / 15),
                loop=0,
                optimize=True
            )

        # 3. DIRECTIVA SOBERANA: Inyección y Enforzamiento de Sonificación Acústica
        if AUDIO_SYNTH_AVAILABLE and mp4_path.exists():
            formula_desc = {
                "reysek_ocampo": r"\rho(\partial_t u + u\cdot\nabla u) = -\nabla p + (\mu+\mu_r)\Delta u + 2\mu_r(\nabla\times\omega) + f_{R-O}",
                "retrocausal": r"\Psi_{Retro} = \Lambda_{Aegis}\int D[\gamma]\Phi_{adv} \exp((i/\hbar)S_{geom} - \eta\int \nabla S_{ent})",
                "lorenz": r"\dot{x}=\sigma(y-x), \dot{y}=x(\rho-z)-y, \dot{z}=xy-\beta z",
                "fourier": r"f(t)=\sum \frac{4}{\pi(2k-1)}\sin((2k-1)\omega t)",
                "lissajous": r"x=A\sin(a\theta+\delta), y=B\cos(b\theta)",
                "julia": r"z_{n+1} = z_n^2 + c(t)",
                "custom": custom_expr
            }.get(formula_key, "Ecuaciones Dinamicas en Pixel Art")

            try:
                ensure_video_has_audio(
                    video_path=mp4_path,
                    title=f"Pixel Art TARDIS: {formula_key.upper()}",
                    formula=formula_desc,
                    domain="Matemáticas Avanzadas, Física Cuántica y Dinámica Retrocausal"
                )
                print(f"[PIXELART-ENGINE] Pista de audio procedural 432Hz/528Hz inyectada en {mp4_path.name}")
            except Exception as e_audio:
                print(f"[PIXELART-ENGINE-WARN] Excepción al inyectar audio: {e_audio}")

        # 4. Sincronización multi-directorio (GODWORKS videos y Directorio de Artefactos)
        for dest_dir in [GODWORKS_VIDEOS_DIR, ARTIFACT_DIR]:
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(mp4_path, dest_dir / mp4_path.name)
                shutil.copy2(gif_path, dest_dir / gif_path.name)
            except Exception as e_copy:
                print(f"[PIXELART-SYNC-WARN] No se pudo copiar a {dest_dir}: {e_copy}")

        print(f"[PIXELART-ENGINE] Archivos generados exitosamente:")
        print(f"  • Video MP4: {mp4_path} ({os.path.getsize(mp4_path)/1024:.1f} KB)")
        print(f"  • GIF Loop:  {gif_path} ({os.path.getsize(gif_path)/1024:.1f} KB)")
        return mp4_path, gif_path


# =============================================================================
# 6. PUNTO DE ENTRADA CLI Y MODO LOTE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TARDIS Pixel Art Mathematical Video Generator · GODWORKS SYSTEM v26.4"
    )
    parser.add_argument(
        "--formula", "-f",
        default="all",
        choices=["all", "reysek_ocampo", "retrocausal", "lorenz", "fourier", "lissajous", "julia", "custom"],
        help="Fórmula matemática o sistema a renderizar en Pixel Art"
    )
    parser.add_argument(
        "--expr",
        default="sin(r*4.0 - t*3.0)",
        help="Expresión matemática personalizada para --formula custom (ej. 'sin(x*2-t)*cos(y*2+t)')"
    )
    parser.add_argument(
        "--palette", "-p",
        default="cyber_neon",
        choices=list(PALETTES.keys()),
        help="Paleta de color retro pixel art"
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=5,
        help="Duración del video en segundos"
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Cuadros por segundo"
    )
    parser.add_argument(
        "--scale", "-s",
        type=int,
        default=4,
        help="Factor de escalado entero (ej. 4x -> 1280x720)"
    )
    parser.add_argument(
        "--no-scanlines",
        action="store_true",
        help="Desactiva las líneas de escaneo CRT en el post-procesado"
    )

    args = parser.parse_args()

    engine = TardisPixelArtEngine(
        native_res=(320, 180),
        scale=args.scale,
        palette=args.palette,
        fps=args.fps
    )

    if args.formula == "all":
        formulas_to_run = ["reysek_ocampo", "retrocausal", "lorenz", "fourier", "lissajous", "julia"]
        print(f"\n⚡ [TARDIS-PIXELART] Generando suite completa de {len(formulas_to_run)} videos matemáticos...")
        results = []
        for f in formulas_to_run:
            mp4, gif = engine.render_video(
                formula_key=f,
                duration_sec=args.duration,
                scanlines=not args.no_scanlines
            )
            results.append((f, mp4, gif))
        print("\n✨ [TARDIS-PIXELART] Suite completa generada con éxito.")
    else:
        engine.render_video(
            formula_key=args.formula,
            duration_sec=args.duration,
            custom_expr=args.expr,
            scanlines=not args.no_scanlines
        )


if __name__ == "__main__":
    main()
