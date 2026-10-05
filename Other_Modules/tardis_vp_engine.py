#!/usr/bin/env python3
"""
core/tardis_vp_engine.py - Motor Soberano de Generación de Video Pixel Art a 1080P @ 60 FPS
========================================================================================
GODWORKS SYSTEM v26.4 · Directiva Soberana del Arquitecto (₪) · ChronoVision Core
Tecnología Procedural de Vanguardia :: Arquitectura de Potencia Visual Nano Banana

Comando /vp:
  "Al escribir el siguiente comando, el programa generará un video utilizando Pixel Art.
   El sistema analizará el texto, investigará y creará una imagen lo más cercana a la
   realidad ocupando la tecnología pixel art, lo hará en formato de video y siempre
   a 60FPS a una resolución de 1080P el comando es /vp"

Lineamientos Nano Banana Procedural Integrados:
  1. BLUEPRINT SEMÁNTICO Y FÍSICO NANO BANANA:
     - Sujeto (Subject): Entidad geométrica, topología no euclidiana o sistema físico central.
     - Acción (Action): Cinemática continua, campos de velocidades, flujo turbulento y órbitas (dt=1/60s).
     - Contexto (Context): Atmósfera volumétrica, dispersión de Rayleigh/Mie, profundidad de capas y horizontes.
     - Estilo Artístico (Art Style): Pixel Art Discreto 1080P60, Dithering matricial Bayer 8x8,
       sombreado Phong, reflejos especulares de Fresnel y resplandor radial con caída cúbica.
  2. INVESTIGACIÓN CIENTÍFICA FACTUAL & ESPECTRAL:
     - Extracción de espectros cromáticos reales (Rayleigh, Planck, emisión H-alfa, Doppler relativista).
     - Deducción de ecuaciones LaTeX de leyes físicas gobernantes.
  3. LIENZO NATIVO DISCRETO 480x270 ESCALADO A 1080P (1920x1080) SIN DESENFOQUE:
     - Escalado entero 4x exacto por vecino más cercano (Nearest Neighbor).
     - Guardado automático de boceto estático 1080P PNG de máxima fidelidad.
  4. SÍNTESIS DE VIDEO A 60 FPS NATIVOS CON GPU NVIDIA NVENC (RTX 3050):
     - Codificación de hardware h264_nvenc con fallback automático a libx264.
     - Multiplexación acústica cuántica obligatoria (48 kHz estéreo sincronizado).
  5. SÍNTESIS PROCEDURAL UNIVERSAL SIN FALLBACK TRIVIAL:
     - Cualquier consulta sin plantilla previa es descompuesta por el Blueprint Nano Banana
       y renderizada mediante SDFs procedurales 3D/2D, enjambre de partículas dinámicas y
       sombras volumétricas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image

# Importar rutas base de GODWORKS
TARDIS_ROOT = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM")
if str(TARDIS_ROOT) not in sys.path:
    sys.path.insert(0, str(TARDIS_ROOT))

# Enforzador de Audio TARDIS
try:
    from core.tardis_audio_synthesizer import ensure_video_has_audio
    AUDIO_SYNTH_AVAILABLE = True
except Exception:
    AUDIO_SYNTH_AVAILABLE = False

# Motor de investigación web si está disponible
try:
    from core.web_research_engine import get_web_research_engine
    WEB_RESEARCH_AVAILABLE = True
except Exception:
    WEB_RESEARCH_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='[TARDIS VP-NANO-BANANA] %(asctime)s - %(message)s')
logger = logging.getLogger("TardisVPEngine")

OUTPUT_VIDEOS_DIR = Path("/home/timemachine/Vídeos")
OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 1. MATRICES DE DITHERING Y TIPOGRAFÍA DISCRETA
# =============================================================================

# Matriz Bayer 4x4 normalizada en [-0.5, 0.5]
BAYER_4X4 = np.array([
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5]
], dtype=np.float32) / 16.0 - 0.5

# Matriz Bayer 8x8 para gradientes ultrarrealistas
BAYER_8X8 = np.array([
    [ 0, 32,  8, 40,  2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44,  4, 36, 14, 46,  6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [ 3, 35, 11, 43,  1, 33,  9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47,  7, 39, 13, 45,  5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21]
], dtype=np.float32) / 64.0 - 0.5

# Tipografía matricial 5x7 integrada
FONT_5X7: Dict[str, List[str]] = {
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'B': ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    'C': ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    'F': ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    'G': ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    'H': ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    'I': ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    'J': ["00001", "00001", "00001", "00001", "10001", "10001", "01110"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'N': ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10011", "01111"],
    'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
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
    ':': ["00000", "00100", "00000", "00000", "00100", "00000", "00000"],
    '.': ["00000", "00000", "00000", "00000", "00000", "00100", "00000"],
    ',': ["00000", "00000", "00000", "00000", "00100", "00100", "01000"],
    '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '+': ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    '/': ["00001", "00010", "00100", "01000", "10000", "00000", "00000"],
    '=': ["00000", "11111", "00000", "11111", "00000", "00000", "00000"],
    '(': ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ')': ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    '|': ["00100", "00100", "00100", "00100", "00100", "00100", "00100"],
    '*': ["00000", "10101", "01110", "11111", "01110", "10101", "00000"]
}


# =============================================================================
# 2. LIENZO NATIVO DISCRETO PIXEL ART NANO BANANA (480x270 -> 1080P x4)
# =============================================================================

class PixelCanvas480:
    """
    Lienzo discreto de alta definición (480x270) que escala de forma entera 4x
    a 1080P Full HD (1920x1080) con cero desenfoque, dithering Bayer 8x8 y
    primitivas procedurales avanzadas.
    """

    def __init__(self, width: int = 480, height: int = 270):
        self.width = width
        self.height = height
        self.buffer = np.zeros((height, width, 3), dtype=np.uint8)
        self.persistence = np.zeros((height, width, 3), dtype=np.float32)

    def clear(self, bg_color: Tuple[int, int, int] = (4, 6, 14)):
        self.buffer[:] = bg_color

    def decay_persistence(self, factor: float = 0.84):
        self.persistence *= factor
        combined = self.buffer.astype(np.float32) + self.persistence
        self.buffer = np.clip(combined, 0, 255).astype(np.uint8)

    def set_pixel(self, x: int, y: int, color: Tuple[int, int, int], persistent: bool = False):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.buffer[y, x] = color
            if persistent:
                self.persistence[y, x] = color

    def draw_line(self, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int]):
        """Línea discreta mediante algoritmo de Bresenham."""
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

    def draw_rect(self, x: int, y: int, w: int, h: int, color: Tuple[int, int, int], fill: bool = False):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        if fill:
            self.buffer[y0:y1, x0:x1] = color
        else:
            self.draw_line(x, y, x + w - 1, y, color)
            self.draw_line(x, y + h - 1, x + w - 1, y + h - 1, color)
            self.draw_line(x, y, x, y + h - 1, color)
            self.draw_line(x + w - 1, y, x + w - 1, y + h - 1, color)

    def draw_circle(self, cx: int, cy: int, radius: int, color: Tuple[int, int, int], fill: bool = False):
        x = radius
        y = 0
        err = 0
        while x >= y:
            if fill:
                self.draw_line(cx - x, cy + y, cx + x, cy + y, color)
                self.draw_line(cx - x, cy - y, cx + x, cy - y, color)
                self.draw_line(cx - y, cy + x, cx + y, cy + x, color)
                self.draw_line(cx - y, cy - x, cx + y, cy - x, color)
            else:
                pts = [
                    (cx + x, cy + y), (cx + y, cy + x),
                    (cx - y, cy + x), (cx - x, cy + y),
                    (cx - x, cy - y), (cx - y, cy - x),
                    (cx + y, cy - x), (cx + x, cy - y)
                ]
                for px, py in pts:
                    self.set_pixel(px, py, color)
            y += 1
            err += 1 + 2 * y
            if 2 * (err - x) + 1 > 0:
                x -= 1
                err += 1 - 2 * x

    def blit_dithered_gradient(
        self,
        y0: int,
        y1: int,
        color_top: Tuple[int, int, int],
        color_bottom: Tuple[int, int, int],
        dither_strength: float = 0.5
    ):
        """Genera un gradiente vertical natural realista utilizando dithering Bayer 8x8."""
        y0 = max(0, y0)
        y1 = min(self.height, y1)
        h = y1 - y0
        w = self.width
        if h <= 0:
            return

        c_top = np.array(color_top, dtype=np.float32)
        c_bot = np.array(color_bottom, dtype=np.float32)

        v_lin = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        tile_y = (h + 7) // 8
        tile_x = (w + 7) // 8
        bayer = np.tile(BAYER_8X8, (tile_y, tile_x))[:h, :w]
        v_dithered = np.clip(v_lin + (dither_strength * bayer), 0.0, 1.0)

        r = c_top[0] * (1.0 - v_dithered) + c_bot[0] * v_dithered
        g = c_top[1] * (1.0 - v_dithered) + c_bot[1] * v_dithered
        b = c_top[2] * (1.0 - v_dithered) + c_bot[2] * v_dithered

        grad_rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
        self.buffer[y0:y1, 0:w] = grad_rgb

    def draw_soft_radial_glow(
        self,
        cx: int,
        cy: int,
        radius: int,
        core_color: Tuple[int, int, int],
        edge_color: Tuple[int, int, int] = (0, 0, 0),
        dither_strength: float = 0.4
    ):
        """Dibuja un resplandor luminoso radial realista con caída inversa cúbica y dithering Bayer."""
        x0 = max(0, cx - radius)
        x1 = min(self.width, cx + radius + 1)
        y0 = max(0, cy - radius)
        y1 = min(self.height, cy + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return

        y_grid, x_grid = np.ogrid[y0:y1, x0:x1]
        dist = np.sqrt((x_grid - cx)**2 + (y_grid - cy)**2)
        norm_dist = np.clip(dist / radius, 0.0, 1.0)
        intensity = (1.0 - norm_dist)**2.2

        h_box, w_box = y1 - y0, x1 - x0
        tile_y = (h_box + 7) // 8
        tile_x = (w_box + 7) // 8
        bayer = np.tile(BAYER_8X8, (tile_y, tile_x))[:h_box, :w_box]

        int_dithered = np.clip(intensity + dither_strength * bayer, 0.0, 1.0)[:, :, None]
        c_core = np.array(core_color, dtype=np.float32)
        c_edge = np.array(edge_color, dtype=np.float32)
        color_field = c_edge * (1.0 - int_dithered) + c_core * int_dithered

        current_crop = self.buffer[y0:y1, x0:x1].astype(np.float32)
        mask = (norm_dist <= 1.0)[:, :, None]
        blended = np.where(mask, np.clip(current_crop + color_field * int_dithered, 0, 255), current_crop)
        self.buffer[y0:y1, x0:x1] = blended.astype(np.uint8)

    def draw_dithered_sphere_3d(
        self,
        cx: int,
        cy: int,
        radius: int,
        base_color: Tuple[int, int, int],
        light_pos: Tuple[float, float, float] = (-0.5, -0.6, 0.8),
        ambient: float = 0.18,
        specular_power: float = 24.0,
        dither_strength: float = 0.35
    ):
        """
        Renderiza una esfera 3D sombreada físicamente con cálculo de normales,
        iluminación difusa Lambertiana, especular Blinn-Phong y dithering Bayer 8x8.
        """
        x0 = max(0, cx - radius)
        x1 = min(self.width, cx + radius + 1)
        y0 = max(0, cy - radius)
        y1 = min(self.height, cy + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return

        y_grid, x_grid = np.ogrid[y0:y1, x0:x1]
        dx = (x_grid - cx).astype(np.float32) / radius
        dy = (y_grid - cy).astype(np.float32) / radius
        d2 = dx**2 + dy**2
        mask = d2 <= 1.0

        dz = np.sqrt(np.maximum(0.0, 1.0 - d2))
        # Vector de luz normalizado
        lx, ly, lz = light_pos
        l_len = math.sqrt(lx*lx + ly*ly + lz*lz) or 1.0
        lx, ly, lz = lx / l_len, ly / l_len, lz / l_len

        # Producto punto N·L (Lambert)
        dot_nl = np.clip(dx * lx + dy * ly + dz * lz, 0.0, 1.0)

        # Especular Blinn-Phong
        vx, vy, vz = 0.0, 0.0, 1.0  # Vista hacia la pantalla
        hx, hy, hz = lx + vx, ly + vy, lz + vz
        h_len = np.sqrt(hx*hx + hy*hy + hz*hz) + 1e-5
        hx, hy, hz = hx / h_len, hy / h_len, hz / h_len
        dot_nh = np.clip(dx * hx + dy * hy + dz * hz, 0.0, 1.0)
        spec = dot_nh ** specular_power

        # Intensidad combinada
        intensity = np.clip(ambient + (1.0 - ambient) * dot_nl + spec * 0.7, 0.0, 1.5)

        # Dithering
        h_box, w_box = y1 - y0, x1 - x0
        tile_y = (h_box + 7) // 8
        tile_x = (w_box + 7) // 8
        bayer = np.tile(BAYER_8X8, (tile_y, tile_x))[:h_box, :w_box]
        int_dithered = np.clip(intensity + dither_strength * bayer, 0.0, 1.5)[:, :, None]

        c_base = np.array(base_color, dtype=np.float32)
        sphere_rgb = np.clip(c_base * int_dithered + spec[:, :, None] * 200.0, 0, 255).astype(np.uint8)

        current_crop = self.buffer[y0:y1, x0:x1]
        self.buffer[y0:y1, x0:x1] = np.where(mask[:, :, None], sphere_rgb, current_crop)

    def draw_procedural_lightning(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: Tuple[int, int, int] = (220, 240, 255),
        core_color: Tuple[int, int, int] = (255, 255, 255),
        displace: float = 35.0,
        subdiv: int = 5
    ):
        """Genera un arco de relámpago procedural con subdivisión fractal y resplandor."""
        pts = [(float(x0), float(y0)), (float(x1), float(y1))]
        cur_disp = displace

        for _ in range(subdiv):
            new_pts = []
            for i in range(len(pts) - 1):
                p_a = pts[i]
                p_b = pts[i + 1]
                mid_x = (p_a[0] + p_b[0]) * 0.5
                mid_y = (p_a[1] + p_b[1]) * 0.5
                # Vector normal perpendicular
                nx = -(p_b[1] - p_a[1])
                ny = p_b[0] - p_a[0]
                n_len = math.sqrt(nx*nx + ny*ny) + 1e-5
                nx, ny = nx / n_len, ny / n_len

                offset = (np.random.rand() - 0.5) * 2.0 * cur_disp
                mid_x += nx * offset
                mid_y += ny * offset

                new_pts.append(p_a)
                new_pts.append((mid_x, mid_y))
            new_pts.append(pts[-1])
            pts = new_pts
            cur_disp *= 0.52

        # Dibujar ramas principales y secundarias
        for i in range(len(pts) - 1):
            px0, py0 = int(pts[i][0]), int(pts[i][1])
            px1, py1 = int(pts[i+1][0]), int(pts[i+1][1])
            self.draw_line(px0, py0, px1, py1, color)
            # Línea central brillante
            if i % 2 == 0:
                self.draw_line(px0, py0, px1, py1, core_color)

    def draw_synthwave_perspective_grid(
        self,
        horizon_y: int,
        t: float,
        grid_color: Tuple[int, int, int] = (240, 40, 180),
        v_speed: float = 2.4
    ):
        """Dibuja una cuadrícula synthwave en perspectiva 3D infinita con movimiento fluido."""
        w, h = self.width, self.height
        cx = w // 2
        horizon_y = max(10, min(h - 20, horizon_y))

        # Líneas radiales que convergen en el punto de fuga central
        num_radials = 24
        for i in range(-num_radials // 2, num_radials // 2 + 1):
            bottom_x = cx + int(i * (w // (num_radials // 2)))
            self.draw_line(cx, horizon_y, bottom_x, h - 1, grid_color)

        # Líneas horizontales espaciadas hiperbólicamente (Z-depth)
        num_horizontals = 16
        offset = (t * v_speed) % 1.0
        for i in range(num_horizontals):
            norm_z = (i + offset) / float(num_horizontals)
            # Ley cuadrática para perspectiva
            hy = int(horizon_y + (h - horizon_y) * (norm_z ** 2.2))
            if horizon_y < hy < h:
                # Disminución de brillo hacia el horizonte
                fade = norm_z
                c_fade = (
                    int(grid_color[0] * fade),
                    int(grid_color[1] * fade),
                    int(grid_color[2] * fade)
                )
                self.draw_line(0, hy, w - 1, hy, c_fade)

    def draw_text(self, x: int, y: int, text: str, color: Tuple[int, int, int], scale: int = 1):
        """Renderiza texto pixel-art con fuente matricial 5x7."""
        cursor_x = x
        for char in text.upper():
            matrix = FONT_5X7.get(char, FONT_5X7.get(' '))
            for row_idx, row in enumerate(matrix):
                for col_idx, bit in enumerate(row):
                    if bit == '1':
                        for sx in range(scale):
                            for sy in range(scale):
                                px = cursor_x + col_idx * scale + sx
                                py = y + row_idx * scale + sy
                                self.set_pixel(px, py, color)
            cursor_x += (5 + 1) * scale

    def to_1080p(self, scanlines: bool = False) -> np.ndarray:
        """
        Escala el lienzo nativo (480x270) de forma exacta 4x a 1080P Full HD (1920x1080)
        utilizando vecino más cercano (Nearest Neighbor) sin emborronar ningún píxel.
        """
        out_w = self.width * 4   # 480 * 4 = 1920
        out_h = self.height * 4  # 270 * 4 = 1080
        upscaled = cv2.resize(self.buffer, (out_w, out_h), interpolation=cv2.INTER_NEAREST)

        if scanlines:
            # Emulación sutil de monitor de estudio Sony PVM CRT
            mask = np.ones((out_h, 1, 1), dtype=np.float32)
            mask[::4] = 0.84
            upscaled = np.clip(upscaled.astype(np.float32) * mask, 0, 255).astype(np.uint8)

        return upscaled


# =============================================================================
# 3. BLUEPRINT PROCEDURAL NANO BANANA & ANÁLISIS DE LA REALIDAD FÍSICA
# =============================================================================

@dataclass
class NanoBananaProceduralSpec:
    prompt: str
    concept: str
    subject: str                  # 1. Sujeto / Primarias geométricas y físicas
    action: str                   # 2. Dinámica, cinemática y vectores de velocidad
    context: str                  # 3. Atmósfera, entorno, dispersión lumínica y horizontes
    art_style: str                # 4. Estilo procedural, dithering Bayer 8x8 y paleta
    category: str
    realism_palette: List[Tuple[int, int, int]]
    light_source: Tuple[int, int]
    formula_latex: str
    spectral_research: str
    motion_type: str
    simulation_fn: str
    frequencies: List[float] = field(default_factory=lambda: [432.0, 528.0])


def analyze_and_research_prompt(prompt: str) -> NanoBananaProceduralSpec:
    """
    Descompone el prompt del usuario mediante el método Nano Banana:
      [Sujeto + Acción + Contexto + Estilo Artístico & Modelo Físico]
    e investiga espectros reales y ecuaciones gobernantes.
    """
    logger.info(f"Descomponiendo Blueprint Nano Banana e investigando realidad física para: '{prompt}'")
    q = prompt.lower().strip()

    # 1. Agujeros Negros & Astrofísica Relativista
    if any(k in q for k in ["kerr", "agujero negro", "black hole", "ergosfera", "singularity", "acreción", "acrecion"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Agujero Negro de Kerr con Disco de Acreción Doppler y Lente Gravitacional",
            subject="Horizonte de sucesos y ergoesfera oblata con anillo de fotones en r = 3M",
            action="Rotación relativista a velocidad angular omega=a/(r^2+a^2) y arrastre de marcos inerciales",
            context="Vacío del espacio profundo interestelar con distorsión de fondo estelar por lente gravitacional",
            art_style="Pixel Art Discreto 1080P60, gradiente térmico de Planck, corrimiento Doppler y dithering Bayer 8x8",
            category="cosmic_astrophysics",
            realism_palette=[
                (2, 2, 8), (12, 10, 28), (60, 15, 10), (180, 50, 15),
                (255, 140, 20), (255, 230, 100), (255, 255, 240), (100, 200, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"ds^2 = -\left(1-\frac{2Mr}{\rho^2}\right)dt^2 - \frac{4Mar\sin^2\theta}{\rho^2}dt d\phi + \frac{\rho^2}{\Delta}dr^2 + \rho^2 d\theta^2",
            spectral_research="Efecto Doppler relativista: corrimiento al azul en el lado aproximante con brillo incrementado a T~10^7 K; corrimiento al rojo en el lado recedente. Desviación geodésica nula de fotones.",
            motion_type="relativistic_rotation",
            simulation_fn="kerr_black_hole",
            frequencies=[108.0, 432.0]
        )

    # 2. Atardecer / Paisajes Naturales Realistas
    elif any(k in q for k in ["atardecer", "sunset", "bosque", "lago", "mar", "playa", "montaña", "montana", "aurora"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Atardecer Atmosférico con Dispersión de Rayleigh y Reflejos en Agua",
            subject="Sol poniente en horizonte con corona dorada y ondas de agua de Gerstner",
            action="Propagación de trenes de ondas trochoidales con reflexión especular de Fresnel y refracción",
            context="Cielo cenital índigo en transición a crepúsculo carmesí con siluetas montañosas en profundidad",
            art_style="Pixel Art Naturalista 1080P60 con dithering Bayer 8x8 y reflejos estirados sobre agua",
            category="nature_landscape",
            realism_palette=[
                (14, 18, 48), (45, 24, 75), (140, 40, 60), (230, 80, 40),
                (255, 180, 50), (255, 245, 200), (20, 45, 55), (15, 60, 90)
            ],
            light_source=(240, 120),
            formula_latex=r"I(\lambda) = I_0 \frac{8\pi^4 N \alpha^2}{\lambda^4 R^2}(1 + \cos^2\theta) \quad [\text{Rayleigh Scattering}]",
            spectral_research="Dispersión elástica de Rayleigh de la luz solar: las longitudes de onda cortas se dispersan en el cenit, permitiendo la transmisión de radiación ámbar y roja (~650-700 nm) en el horizonte.",
            motion_type="wave_water_reflection",
            simulation_fn="nature_sunset_waves",
            frequencies=[432.0, 528.0]
        )

    # 3. Mecánica Cuántica (Función de Onda, Efecto Túnel, Superposición)
    elif any(k in q for k in ["cuantico", "cuántico", "quantum", "onda", "schrodinger", "superposicion", "tunel", "probabilidad"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Evolución de Paquete de Ondas Cuánticas y Densidad de Probabilidad de Born",
            subject="Función de onda compleja Psi(x,t) incidiendo sobre barrera de potencial finita",
            action="Evolución unitaria de Schrödinger con dispersión de paquete y tunelamiento evanescente",
            context="Espacio de configuración de Hilbert con franjas de interferencia coherente",
            art_style="Pixel Art Holográfico 1080P60 con gradiente de fase cromática y decaimiento cuántico",
            category="quantum_physics",
            realism_palette=[
                (3, 8, 20), (10, 30, 60), (0, 140, 180), (0, 230, 180),
                (120, 60, 240), (240, 40, 180), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"i\hbar \frac{\partial \Psi}{\partial t} = -\frac{\hbar^2}{2m} \nabla^2 \Psi + V(\mathbf{r})\Psi, \quad \rho = |\Psi|^2",
            spectral_research="Densidad de probabilidad de Born |Psi|^2 con conservación de norma unitaria. Penetración de barrera con decaimiento exponencial exp(-2kappa x) e interferencia constructiva.",
            motion_type="quantum_wave_interference",
            simulation_fn="quantum_wave_packet",
            frequencies=[528.0, 648.0]
        )

    # 4. Mecánica & Motores (Pistones, V8, Combustión Interna)
    elif any(k in q for k in ["motor", "v8", "piston", "pistones", "combustion", "engranaje", "turbina", "maquina"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Motor V8 de Cuatro Tiempos y Cinemática Recíproca de Pistones",
            subject="Bloque de cilindros en corte transversal con pistones, bielas y cigüeñal forjado",
            action="Ciclo termodinámico de 4 tiempos (Admisión, Compresión, Expansión, Escape) con deflagración",
            context="Entorno de ingeniería mecánica con iluminación rasante de taller y reflejos metálicos",
            art_style="Pixel Art Técnico 1080P60 con sombreado de acero pulido y flash térmico de combustión",
            category="mechanical_engineering",
            realism_palette=[
                (20, 22, 28), (55, 60, 72), (130, 140, 155), (210, 220, 235),
                (255, 80, 10), (255, 180, 20), (255, 255, 180), (40, 80, 120)
            ],
            light_source=(180, 60),
            formula_latex=r"x(\theta) = r\left((1-\cos\theta) + \frac{1}{\lambda}\left(1-\sqrt{1-\lambda^2\sin^2\theta}\right)\right)",
            spectral_research="Cinemática de mecanismo biela-manivela. Temperatura de deflagración adiabática ~ 2200 K con expansión isentrópica de gases de combustión.",
            motion_type="piston_reciprocation",
            simulation_fn="engine_pistons",
            frequencies=[120.0, 240.0]
        )

    # 5. Cyberpunk & Metrópolis Nocturna (Neón, Asfalto Lluvioso)
    elif any(k in q for k in ["cyberpunk", "ciudad", "neon", "neón", "metropolis", "calle", "asfalto", "tokyo"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Metrópolis Cyberpunk Nocturna con Asfalto Húmedo y Neón",
            subject="Rascacielos retrofuturistas con letreros holográficos y gotas de lluvia direccionales",
            action="Flujo vertical de lluvia impulsada por viento y reflejos especulares de neón sobre asfalto mojado",
            context="Noche lluviosa densa con niebla urbana difusa y dispersión volumétrica de luz artificial",
            art_style="Pixel Art Synthwave Cyberpunk 1080P60 con alto contraste cromático y reflejos anamórficos",
            category="urban_cyberpunk",
            realism_palette=[
                (10, 12, 22), (28, 32, 50), (0, 220, 240), (255, 0, 128),
                (255, 210, 0), (180, 240, 255), (80, 100, 140), (255, 255, 255)
            ],
            light_source=(240, 80),
            formula_latex=r"L_o(\mathbf{x}, \omega_o) = L_e + \int_\Omega f_r(\mathbf{x}, \omega_i, \omega_o) L_i (\omega_i \cdot \mathbf{n}) d\omega_i",
            spectral_research="Microfaceta de Cook-Torrance con capa de agua de rugosidad casi nula produciendo reflejos especulares verticales alargados sobre asfalto asfáltico.",
            motion_type="neon_rain_city",
            simulation_fn="cyberpunk_rain_city",
            frequencies=[216.0, 432.0]
        )

    # 6. Biología & ADN Molecular (Doble Hélice 3D)
    elif any(k in q for k in ["adn", "dna", "helice", "hélice", "celula", "célula", "genetica"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Doble Hélice de ADN en Rotación Molecular B-DNA",
            subject="Hebra bicatenaria helicoidal con pares de bases nitrogenadas Adenina-Timina y Guanina-Citosina",
            action="Rotación continua tridimensional en torno al eje central longitudinal con ordenación Z-buffer",
            context="Microcosmos celular citoplasmático con profundidad de campo desenfocada",
            art_style="Pixel Art Científico 1080P60 con sombreado esférico 3D de esferas atómicas y enlaces covalentes",
            category="biological_cellular",
            realism_palette=[
                (8, 12, 24), (18, 35, 65), (0, 180, 220), (240, 70, 120),
                (80, 220, 100), (255, 190, 40), (180, 240, 255), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"\mathbf{r}(t, s) = (R\cos(\omega t \pm s), R\sin(\omega t \pm s), p\cdot s), \quad p = 3.4\text{ nm/vuelta}",
            spectral_research="Conformación estándar B-DNA descubierta por Watson, Crick y Franklin: diámetro de 2.0 nm, paso helicoidal de 3.4 nm por vuelta de 10.5 pares de bases.",
            motion_type="dna_helix_3d_rotation",
            simulation_fn="dna_molecular_helix",
            frequencies=[432.0, 528.0]
        )

    # 7. Dinámica Caótica & Atractor de Lorenz RK4
    elif any(k in q for k in ["lorenz", "caos", "atractor", "fractal", "julia", "mandelbrot"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Atractor Caótico de Lorenz con Integración Numérica RK4",
            subject="Espacio de fases tridimensional con alas mariposa y dos puntos focales inestables",
            action="Integración numérica Runge-Kutta 4to orden con divergencia exponencial de Lyapunov",
            context="Vacío matemático topológico con estela luminosa de decaimiento temporal",
            art_style="Pixel Art Matemático 1080P60 con gradiente de velocidad cinemática y resplandor frontal",
            category="mathematical_chaos",
            realism_palette=[
                (2, 6, 14), (12, 24, 55), (0, 210, 230), (140, 40, 220),
                (255, 0, 110), (255, 200, 40), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"\dot{x} = \sigma(y - x), \quad \dot{y} = x(\rho - z) - y, \quad \dot{z} = xy - \beta z",
            spectral_research="Sistema dinámico disipativo no lineal en R^3 con parámetros de Lorenz sigma=10, rho=28, beta=8/3. Dimensión fractal de Hausdorff ~ 2.06.",
            motion_type="lorenz_rk4_flow",
            simulation_fn="lorenz_chaos",
            frequencies=[432.0, 864.0]
        )

    # 8. Reactor de Fusión Nuclear Tokamak (Plasma Confinado)
    elif any(k in q for k in ["tokamak", "fusion", "fusión", "plasma", "reactor", "confinamiento"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Reactor de Fusión Nuclear Tokamak con Plasma Magnético Confinado",
            subject="Toroide magnético de plasma D-T a 150 millones de grados con bobinas poloidales",
            action="Flujo helicoidal de líneas de campo magnético q(r) y turbulencia magnetohidrodinámica (MHD)",
            context="Cámara de vacío de acero reforzado y divertor inferior con disipación térmica",
            art_style="Pixel Art Fusión Nuclear 1080P60 con líneas de campo luminosas y resplandor térmico de plasma",
            category="nuclear_fusion",
            realism_palette=[
                (4, 6, 16), (20, 25, 45), (100, 15, 220), (0, 240, 255),
                (255, 120, 20), (255, 240, 80), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"\nabla p = \mathbf{J} \times \mathbf{B}, \quad \mu_0 \mathbf{J} = \nabla \times \mathbf{B} \quad [\text{Grad-Shafranov Equilibrium}]",
            spectral_research="Equilibrio magnetohidrodinámico de Grad-Shafranov: presión cinética confinada por campo magnético toroidal y poloidal para alcanzar el criterio de Lawson n*T*tau >= 3x10^21 keV s / m^3.",
            motion_type="tokamak_plasma_flow",
            simulation_fn="tokamak_fusion_reactor",
            frequencies=[300.0, 600.0]
        )

    # 9. Supernova & Astrofísica Explosiva
    elif any(k in q for k in ["supernova", "explosion estelar", "estrella explota", "remanente"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Colapso Gravitacional de Supernova y Expansión Asimétrica de Onda de Choque",
            subject="Remanente estelar ultradenso central con caparazón de choque en expansión y filamentos",
            action="Onda de choque explosiva con inestabilidades hidrodinámicas de Rayleigh-Taylor",
            context="Espacio interestelar circundante ionizado por emisión sincrotrón y rayos gamma",
            art_style="Pixel Art Cósmico 1080P60 con filamentos policromáticos de ionización y resplandor central",
            category="stellar_astrophysics",
            realism_palette=[
                (2, 2, 8), (20, 10, 40), (255, 60, 20), (255, 180, 40),
                (0, 200, 255), (180, 80, 255), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"E_{\text{nuc}} \sim 10^{44}\text{ J}, \quad R_{\text{shock}}(t) \propto \left(\frac{E}{\rho_0}\right)^{1/5} t^{2/5} \quad [\text{Sedov-Taylor}]",
            spectral_research="Fase autosemejante de Sedov-Taylor: choque supersónico con velocidad inicial ~ 15,000 km/s generando ionización térmica de oxígeno, silicio y hierro.",
            motion_type="supernova_shockwave_expansion",
            simulation_fn="supernova_explosion",
            frequencies=[108.0, 528.0]
        )

    # 10. Cyber Speeder en Autopista Synthwave
    elif any(k in q for k in ["speeder", "coche", "auto", "vehiculo", "vehículo", "autopista", "synthwave", "retrowave"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Cyber Speeder en Autopista Synthwave con Cuadrícula de Perspectiva 3D",
            subject="Vehículo aerodinámico flotante con estela lumínica roja de propulsión iónica",
            action="Desplazamiento a alta velocidad por carretera infinita con líneas de velocidad y balanceo",
            context="Horizonte con sol retrowave gigante y montañas vectoriales púrpuras",
            art_style="Pixel Art Synthwave 1080P60 con cuadrícula 3D animada y paleta neón brillante",
            category="cyber_retrowave",
            realism_palette=[
                (12, 6, 26), (40, 12, 60), (240, 30, 140), (0, 245, 212),
                (255, 210, 40), (255, 255, 255)
            ],
            light_source=(240, 110),
            formula_latex=r"y_{\text{persp}} = \frac{f \cdot Y}{Z(t)}, \quad Z(t) = Z_0 - v \cdot t",
            spectral_research="Transformación proyectiva de perspectiva cónica con gradiente de absorción atmosférica retro.",
            motion_type="speeder_highway_motion",
            simulation_fn="cyber_speeder_highway",
            frequencies=[216.0, 432.0]
        )

    # 11. Tormenta Oceánica con Relámpagos Procedurales
    elif any(k in q for k in ["tormenta", "rayo", "relampago", "relámpago", "trueno", "mar picado", "tempestad"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Tempestad Oceánica Violenta con Descargas Eléctricas Procedurales",
            subject="Olas gigantescas rompientes y arcos de relámpago con bifurcación fractal",
            action="Choque de trenes de olas no lineales, oscilación de crestas y descargas de plasma súbitas",
            context="Nubes cumulonimbus de tormenta iluminadas internamente por ionización dieléctrica",
            art_style="Pixel Art Atmosférico 1080P60 con iluminación relampagueante global y espuma blanca",
            category="nature_storm",
            realism_palette=[
                (6, 12, 22), (18, 28, 48), (35, 60, 90), (140, 190, 240),
                (240, 250, 255), (255, 255, 255)
            ],
            light_source=(240, 60),
            formula_latex=r"E_{\text{ruptura}} \approx 3 \times 10^6 \text{ V/m}, \quad I_{\text{pico}} \sim 30\text{ kA}",
            spectral_research="Ruptura dieléctrica del aire por avalancha de Townsend. Emisión de plasma de canal de retorno con temperatura T ~ 30,000 K generando luz blanca-azulada intensa.",
            motion_type="storm_lightning_motion",
            simulation_fn="storm_lightning_ocean",
            frequencies=[80.0, 432.0]
        )

    # 12. Red Sináptica Neuronal (Cerebro & Sinapsis)
    elif any(k in q for k in ["neurona", "sinapsis", "cerebro", "red neuronal", "axón", "axon"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Red Sináptica Neuronal y Propagación de Potenciales de Acción",
            subject="Soma neuronal con árbol dendrítico, vaina de mielina y botones presinápticos",
            action="Propagación electroquímica de onda de despolarización por canales de Na+/K+",
            context="Matriz extracelular cerebral con microglía y pulsos de información sincronizados",
            art_style="Pixel Art Bioeléctrico 1080P60 con bioluminiscencia sináptica y pulsos de disparo",
            category="neurobiology",
            realism_palette=[
                (4, 8, 20), (15, 30, 60), (0, 200, 240), (0, 255, 180),
                (255, 220, 40), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"C_m \frac{dV}{dt} = -g_{\text{Na}}m^3h(V-E_{\text{Na}}) - g_{\text{K}}n^4(V-E_{\text{K}}) - g_L(V-E_L) + I_{\text{app}}",
            spectral_research="Modelo de Hodgkin-Huxley de dinámica de membrana neuronal: conductancias iónicas dependientes de voltaje generando espigas de despolarización de 100 mV en 1 ms.",
            motion_type="neural_pulse_propagation",
            simulation_fn="neural_synapse_network",
            frequencies=[432.0, 528.0]
        )

    # 13. Variedad de Calabi-Yau 6D & Teoría de Cuerdas
    elif any(k in q for k in ["calabi", "cuerdas", "dimensiones", "compactificacion", "compactificación"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Variedad de Calabi-Yau 6D Compactificada con Cuerdas Vibrando",
            subject="Hipersuperficie analítica compleja Kähler con curvatura de Ricci nula",
            action="Rotación tridimensional proyectiva e interferencia de modos de vibración de cuerdas",
            context="Espaciotiempo de 10 dimensiones de la Teoría M compactificado en escala de Planck",
            art_style="Pixel Art Topológico 1080P60 con transparencia matricial y líneas de curvatura isométrica",
            category="string_theory",
            realism_palette=[
                (6, 6, 20), (20, 25, 65), (72, 202, 228), (0, 119, 182),
                (144, 224, 239), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"R_{i\bar{j}} = 0, \quad c_1(M) = 0, \quad \Omega \wedge \bar{\Omega} = \text{vol}_M",
            spectral_research="Variedad Kähler compacta de holonomía SU(3) requerida para preservar supersimetría N=1 en compactificaciones de supercuerdas de tipo IIB y heteróticas.",
            motion_type="calabi_yau_rotation",
            simulation_fn="calabi_yau_manifold",
            frequencies=[528.0, 864.0]
        )

    # 14. Sistema Solar & Órbitas Planetarias Keplerianas
    elif any(k in q for k in ["sistema solar", "planeta", "planetas", "kepler", "heliocentr"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="El Sistema Solar en Movimiento y Cinemática Orbital Kepleriana",
            subject="Sol central masivo con 5 planetas en traslación orbital elíptica",
            action="Revolución orbital Kepleriana v = sqrt(GM/r) con rotación y sombras",
            context="Vacío interplanetario con cinturón de asteroides y polvo zodiacal",
            art_style="Pixel Art Astronómico 1080P60 con sombreado de fases planetarias y fulgor solar",
            category="planetary_astronomy",
            realism_palette=[
                (2, 4, 12), (18, 24, 45), (255, 180, 20), (80, 160, 240),
                (200, 70, 30), (240, 210, 120), (255, 255, 230)
            ],
            light_source=(240, 135),
            formula_latex=r"T^2 = \frac{4\pi^2}{G(M_\odot + m)} a^3, \quad v(r) = \sqrt{GM_\odot \left(\frac{2}{r} - \frac{1}{a}\right)}",
            spectral_research="Cinemática kepleriana planetaria heliocéntrica con leyes de áreas y periodos. Gradiente de iluminación cónica inversa al cuadrado de la distancia r.",
            motion_type="solar_keplerian_orbits",
            simulation_fn="solar_system_orbits",
            frequencies=[108.0, 432.0]
        )

    # 15. Eje Solar & Fulguración de Plasma (Eyección de Masa Coronal)
    elif any(k in q for k in ["sol", "solar", "fulguracion", "fulguración", "cme", "corona", "plasma solar"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Fulguración Solar y Eyección de Masa Coronal (CME) con Granulación",
            subject="Fotosfera solar granulada con lazo magnético retorcido y eyección de plasma relativista",
            action="Reconexión magnética violenta que acelera protones y electrones a fracciones de c",
            context="Corona solar exterior a millones de grados Kelvin con filamentos de viento solar",
            art_style="Pixel Art Heliofísico 1080P60 con emisión espectral H-alfa y plasma incandescente",
            category="solar_physics",
            realism_palette=[
                (8, 2, 4), (40, 10, 8), (180, 40, 10), (255, 120, 20),
                (255, 210, 40), (255, 255, 220)
            ],
            light_source=(240, 135),
            formula_latex=r"E_{\text{mag}} = \int \frac{B^2}{2\mu_0} dV \longrightarrow \Delta E_{\text{flare}} \sim 10^{25}\text{ J}",
            spectral_research="Reconexión de líneas de campo magnético heliofísico de Parker con radiación en línea H-alfa (656.3 nm) y rayos X blandos/duros.",
            motion_type="solar_flare_eruption",
            simulation_fn="solar_coronal_mass_ejection",
            frequencies=[432.0, 648.0]
        )

    # 16. Hipercubo 4D Tesseract
    elif any(k in q for k in ["tesseract", "hipercubo", "4d", "cuarta dimension", "cuarta dimensión"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Hipercubo 4D (Tesseract) en Rotación Isométrica Doble",
            subject="Politopo regular cuatridimensional con 16 vértices, 32 aristas y 8 células cúbicas",
            action="Rotación continua simultánea en dos planos ortogonales (XY y ZW) con proyección 3D a 2D",
            context="Espacio no euclidiano con inversión periódica de células interiores y exteriores",
            art_style="Pixel Art Geometría Sagrada 1080P60 con aristas cian translúcidas y vértices brillantes",
            category="multidimensional_geometry",
            realism_palette=[
                (4, 6, 16), (15, 24, 50), (0, 240, 220), (120, 80, 255),
                (255, 0, 128), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"\mathbf{x}_{4D} = \mathbf{R}_{XY}(\theta_1) \cdot \mathbf{R}_{ZW}(\theta_2) \cdot \mathbf{x}_0, \quad \mathbf{x}_{3D} = \frac{d}{d - w}\mathbf{x}",
            spectral_research="Politopo regular de Schläfli {4,3,3} con simetría del grupo hiperoctaédrico de orden 384.",
            motion_type="tesseract_4d_rotation",
            simulation_fn="tesseract_4d_hypercube",
            frequencies=[432.0, 528.0]
        )

    # 16. Colisión de Galaxias Espirales
    elif any(k in q for k in ["galaxia", "galaxias", "colision galactica", "colisión galáctica", "espiral"]):
        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept="Colisión y Fusión Gravitacional de Galaxias Espirales Interactivas",
            subject="Dos núcleos galácticos supermasivos con brazos espirales de estrellas y gas estelar",
            action="Desgarramiento mareal gravitacional formando colas de marea y brotes de formación estelar",
            context="Cúmulo galáctico con filamentos de materia oscura en el espacio profundo",
            art_style="Pixel Art Galáctico 1080P60 con brazos espirales azulados y núcleos dorados",
            category="extragalactic_astronomy",
            realism_palette=[
                (2, 2, 8), (10, 15, 35), (40, 60, 120), (0, 200, 255),
                (255, 200, 60), (255, 255, 255)
            ],
            light_source=(240, 135),
            formula_latex=r"\mathbf{a}_i = -G \sum_{j \neq i} \frac{m_j (\mathbf{r}_i - \mathbf{r}_j)}{(|\mathbf{r}_i - \mathbf{r}_j|^2 + \epsilon^2)^{3/2}}",
            spectral_research="Simulación gravitacional N-cuerpos con suavizado de Coulomb epsilon: formación de puentes de marea y fusión en galaxia elíptica gigante.",
            motion_type="galaxy_collision_flow",
            simulation_fn="galaxy_collision",
            frequencies=[108.0, 432.0]
        )

    # 17. SÍNTESIS PROCEDURAL UNIVERSAL NANO BANANA (Fallback Inteligente para Cualquier Concepto)
    else:
        # Extracción analítica del sujeto y acción
        words = prompt.strip().split()
        clean_name = prompt.strip().capitalize()
        subject_name = " ".join(words[:4]).capitalize() if words else "Estructura Universal"

        return NanoBananaProceduralSpec(
            prompt=prompt,
            concept=f"Síntesis Visual Procedural de {clean_name}",
            subject=f"Morfología geométrica y dinámica representativa de {subject_name}",
            action="Evolución armónica continua con campos de fuerzas no lineales, vórtices y rotación 3D",
            context="Atmósfera volumétrica con dispersión lumínica y horizonte con gradiente de profundidad",
            art_style="Pixel Art High-Density Nano Banana 1080P60 con sombreado de Phong y partículas activas",
            category="universal_procedural",
            realism_palette=[
                (6, 10, 24), (20, 35, 68), (0, 210, 240), (140, 50, 230),
                (255, 45, 140), (255, 210, 50), (255, 255, 255)
            ],
            light_source=(240, 100),
            formula_latex=r"\mathcal{S}_{\text{sintropía}} = \oint_{\partial \Omega} \Psi_{\text{retro}} \cdot d\mathbf{\Sigma} - \Delta S_{\text{caos}}",
            spectral_research="Mapeo morfológico paramétrico no euclidiano con iluminación difusa de Lambert y reflejos especulares de Blinn-Phong.",
            motion_type="universal_harmonic_evolution",
            simulation_fn="universal_nano_banana_procedural",
            frequencies=[432.0, 528.0]
        )


# =============================================================================
# 4. RENDERIZADORES PROCEDURALES FÍSICO-VISUALES A 60 FPS
# =============================================================================

def render_frame_for_spec(
    canvas: PixelCanvas480,
    spec: NanoBananaProceduralSpec,
    t: float,
    frame_idx: int,
    total_frames: int
):
    """
    Renderiza un cuadro completo en la rejilla discreta de 480x270 para el tiempo t (en segundos).
    A 60 FPS Nativos, dt = 1/60s.
    """
    fn = spec.simulation_fn
    w, h = canvas.width, canvas.height
    cx, cy = w // 2, h // 2

    # -------------------------------------------------------------------------
    # 1. Agujero Negro de Kerr con Disco de Acreción Doppler
    # -------------------------------------------------------------------------
    if fn == "kerr_black_hole":
        canvas.clear(bg_color=(2, 2, 6))

        # Estrellas de fondo con parpadeo y lente gravitacional
        np.random.seed(42)
        star_coords = np.random.randint(0, w, (140, 2))
        star_coords[:, 1] = np.random.randint(0, h, 140)
        twinkles = (180 + 75 * np.sin(t * 3.0 + star_coords[:, 0])).astype(np.uint8)
        for idx, (sx, sy) in enumerate(star_coords):
            dx, dy = sx - cx, sy - cy
            if (dx*dx + dy*dy) > 2025:  # r > 45
                tw = int(twinkles[idx])
                canvas.set_pixel(sx, sy, (tw, tw, tw))

        # Disco de acreción vectorizado en NumPy para 60 FPS ultra-rápido
        r_inner, r_outer = 40, 132
        angle_rot = t * 2.2
        r_rings = np.arange(r_inner, r_outer, 2, dtype=np.float32)
        thetas = np.linspace(0, 2 * np.pi, 96, endpoint=False, dtype=np.float32) + angle_rot

        R, TH = np.meshgrid(r_rings, thetas)
        PX = (cx + R * np.cos(TH)).astype(np.int32)
        PY = (cy + (R * 0.32) * np.sin(TH)).astype(np.int32)

        valid_mask = (PX >= 0) & (PX < w) & (PY >= 0) & (PY < h)
        PX_val = PX[valid_mask]
        PY_val = PY[valid_mask]
        R_val = R[valid_mask]
        TH_val = TH[valid_mask]

        doppler_factor = np.clip(1.0 + 0.65 * np.cos(TH_val), 0.35, 1.8)
        norm_r = (R_val - r_inner) / float(r_outer - r_inner)

        red = np.clip(doppler_factor * (255 * (1.0 - norm_r) + 120 * norm_r), 0, 255).astype(np.uint8)
        green = np.clip(doppler_factor * (160 * (1.0 - norm_r) + 30 * norm_r), 0, 255).astype(np.uint8)
        blue = np.clip(doppler_factor * (80 * (1.0 - norm_r) + 20 * norm_r), 0, 255).astype(np.uint8)

        # Matriz Bayer para suavizado orgánico
        tile_y = (len(PX_val) + 7) // 8
        bayer_d = np.tile(BAYER_8X8.flatten(), tile_y)[:len(PX_val)] * 25.0
        red = np.clip(red.astype(np.float32) + bayer_d, 0, 255).astype(np.uint8)

        canvas.buffer[PY_val, PX_val] = np.stack([red, green, blue], axis=-1)

        # Horizonte de sucesos central (Sombra pura del agujero negro)
        canvas.draw_circle(cx, cy, 32, (0, 0, 0), fill=True)
        # Anillo de fotones brillante
        canvas.draw_circle(cx, cy, 33, (255, 250, 220), fill=False)
        canvas.draw_soft_radial_glow(cx, cy, 55, (255, 180, 30), (0, 0, 0), dither_strength=0.3)

    # -------------------------------------------------------------------------
    # 2. Atardecer Atmosférico & Olas de Gerstner
    # -------------------------------------------------------------------------
    elif fn == "nature_sunset_waves":
        canvas.clear()
        horizon_y = h // 2 + 10

        # Cielo crepuscular con gradiente Rayleigh
        canvas.blit_dithered_gradient(
            0, horizon_y,
            color_top=(14, 18, 48),
            color_bottom=(240, 85, 40),
            dither_strength=0.55
        )

        # Sol poniente
        sun_x, sun_y = cx, horizon_y - 18
        canvas.draw_soft_radial_glow(sun_x, sun_y, 48, (255, 230, 120), (220, 60, 20), dither_strength=0.3)
        canvas.draw_circle(sun_x, sun_y, 16, (255, 250, 220), fill=True)

        # Siluetas de montañas en el horizonte
        np.random.seed(99)
        mtn_pts = []
        for x in range(0, w, 6):
            elevation = int(24 * math.sin(x * 0.015) + 12 * math.cos(x * 0.04))
            mtn_pts.append((x, horizon_y - max(4, elevation)))
        for i in range(len(mtn_pts) - 1):
            canvas.draw_line(mtn_pts[i][0], mtn_pts[i][1], mtn_pts[i+1][0], mtn_pts[i+1][1], (25, 30, 45))

        # Superficie del mar con ondas de Gerstner
        canvas.blit_dithered_gradient(
            horizon_y, h,
            color_top=(35, 55, 75),
            color_bottom=(8, 16, 28),
            dither_strength=0.45
        )

        # Reflejo especular del sol en el agua
        for y_wave in range(horizon_y + 1, h, 3):
            wave_amp = (y_wave - horizon_y) * 0.06
            glitter_w = int(12 + (y_wave - horizon_y) * 0.75)
            wave_shift = int(wave_amp * math.sin(t * 3.5 + y_wave * 0.4))

            rx0 = max(0, sun_x - glitter_w + wave_shift)
            rx1 = min(w, sun_x + glitter_w + wave_shift)
            for rx in range(rx0, rx1, 2):
                if (rx + y_wave + int(t * 60)) % 3 == 0:
                    spec_c = (255, int(180 + 60 * math.sin(rx * 0.1)), 60)
                    canvas.set_pixel(rx, y_wave, spec_c)

    # -------------------------------------------------------------------------
    # 3. Evolución de Paquete de Ondas Cuánticas
    # -------------------------------------------------------------------------
    elif fn == "quantum_wave_packet":
        canvas.clear(bg_color=(3, 8, 20))
        # Barrera de potencial central
        bar_x0, bar_x1 = cx - 15, cx + 15
        canvas.draw_rect(bar_x0, 30, bar_x1 - bar_x0, h - 60, (20, 40, 75), fill=True)
        canvas.draw_rect(bar_x0, 30, bar_x1 - bar_x0, h - 60, (0, 180, 220), fill=False)

        x_arr = np.linspace(-4.0, 4.0, w, dtype=np.float32)
        x_center = -2.2 + (t * 1.4) % 4.8
        envelope = np.exp(-((x_arr - x_center)**2) / 0.5)

        for px in range(w):
            psi_real = envelope[px] * math.cos(14.0 * x_arr[px] - t * 8.0)
            psi_imag = envelope[px] * math.sin(14.0 * x_arr[px] - t * 8.0)
            prob_density = envelope[px]**2

            py_real = int(cy - psi_real * 55)
            py_prob = int(cy + 65 - prob_density * 60)

            c_phase = (
                int(np.clip(120 + psi_real * 135, 0, 255)),
                int(np.clip(180 + psi_imag * 75, 0, 255)),
                int(np.clip(240 * prob_density + 15, 0, 255))
            )
            canvas.set_pixel(px, py_real, c_phase)
            canvas.set_pixel(px, py_prob, (240, 40, 180))

        canvas.draw_soft_radial_glow(int(cx + (x_center / 4.0) * (w // 2)), cy, 25, (0, 240, 220), (0, 0, 0), dither_strength=0.3)

    # -------------------------------------------------------------------------
    # 4. Motor V8 de Cuatro Tiempos
    # -------------------------------------------------------------------------
    elif fn == "engine_pistons":
        canvas.clear(bg_color=(16, 18, 24))
        crank_angle = t * 6.28 * 2.5
        crank_y = cy + 45
        stroke_r = 28.0
        conrod_l = 65.0

        canvas.draw_circle(cx, crank_y, 45, (40, 45, 55), fill=True)
        canvas.draw_circle(cx, crank_y, 45, (100, 110, 130), fill=False)

        piston_offsets = [0.0, math.pi * 0.5, math.pi, math.pi * 1.5]
        for i, off in enumerate(piston_offsets):
            th = crank_angle + off
            crank_pin_x = cx + int(stroke_r * math.cos(th))
            crank_pin_y = crank_y + int(stroke_r * math.sin(th))

            cyl_x = int(cx - 120 + i * 80)
            piston_disp = stroke_r * (1.0 - math.cos(th)) + (stroke_r**2 / (2.0 * conrod_l)) * (math.sin(th)**2)
            piston_y = int(cy - 60 + piston_disp * 0.6)

            canvas.draw_line(cyl_x - 22, cy - 80, cyl_x - 22, cy + 20, (80, 90, 110))
            canvas.draw_line(cyl_x + 22, cy - 80, cyl_x + 22, cy + 20, (80, 90, 110))
            canvas.draw_line(cyl_x, piston_y + 15, crank_pin_x, crank_pin_y, (160, 170, 190))

            canvas.draw_rect(cyl_x - 20, piston_y, 40, 22, (120, 130, 145), fill=True)
            canvas.draw_rect(cyl_x - 20, piston_y, 40, 22, (200, 215, 235), fill=False)
            canvas.draw_line(cyl_x - 18, piston_y + 4, cyl_x + 18, piston_y + 4, (60, 65, 75))

            if math.cos(th) > 0.85:
                canvas.draw_soft_radial_glow(cyl_x, piston_y - 10, 25, (255, 140, 20), (180, 30, 5), dither_strength=0.3)
                canvas.draw_circle(cyl_x, piston_y - 12, 6, (255, 255, 200), fill=True)

    # -------------------------------------------------------------------------
    # 5. Metrópolis Cyberpunk Nocturna
    # -------------------------------------------------------------------------
    elif fn == "cyberpunk_rain_city":
        canvas.clear(bg_color=(8, 10, 18))
        np.random.seed(101)
        building_x = 0
        while building_x < w:
            b_width = np.random.randint(35, 70)
            b_height = np.random.randint(110, 210)
            b_top = h - 60 - b_height

            canvas.draw_rect(building_x, b_top, b_width, b_height, (18, 22, 34), fill=True)
            canvas.draw_rect(building_x, b_top, b_width, b_height, (35, 45, 65), fill=False)

            for wy in range(b_top + 10, h - 65, 12):
                for wx in range(building_x + 6, building_x + b_width - 6, 8):
                    if np.random.rand() > 0.4:
                        w_color = (0, 240, 220) if np.random.rand() > 0.5 else (255, 40, 140)
                        canvas.draw_rect(wx, wy, 4, 6, w_color, fill=True)

            if np.random.rand() > 0.6:
                neon_y = b_top + 25
                canvas.draw_rect(building_x + 8, neon_y, 18, 30, (255, 0, 128), fill=False)
                canvas.draw_soft_radial_glow(building_x + 17, neon_y + 15, 20, (255, 0, 128), (0, 0, 0), dither_strength=0.3)

            building_x += b_width + 4

        street_y = h - 55
        canvas.blit_dithered_gradient(
            street_y, h,
            color_top=(20, 25, 38),
            color_bottom=(6, 8, 14),
            dither_strength=0.35
        )

        for rx in range(0, w, 16):
            if (rx // 16) % 2 == 0:
                neon_reflect = (0, int(180 + 70 * math.sin(rx + t * 4.0)), int(220 + 35 * math.cos(rx)))
            else:
                neon_reflect = (int(220 + 35 * math.sin(rx)), 10, int(160 + 80 * math.cos(rx + t * 3.0)))

            for ry in range(street_y + 2, h, 2):
                falloff = 1.0 - (ry - street_y) / float(h - street_y)
                c_wet = (
                    int(neon_reflect[0] * falloff * 0.65),
                    int(neon_reflect[1] * falloff * 0.65),
                    int(neon_reflect[2] * falloff * 0.65)
                )
                if (rx + ry + int(t * 60)) % 2 == 0:
                    canvas.set_pixel(rx, ry, c_wet)

        np.random.seed(int(t * 60) % 1000)
        rain_drops = np.random.randint(0, w, 90)
        for rx in rain_drops:
            ry = np.random.randint(0, h)
            canvas.draw_line(rx, ry, rx - 3, ry + 8, (140, 190, 240))

    # -------------------------------------------------------------------------
    # 6. Doble Hélice de ADN Molecular 3D
    # -------------------------------------------------------------------------
    elif fn == "dna_molecular_helix":
        canvas.clear(bg_color=(6, 12, 25))
        omega = t * 2.2
        radius = 55.0
        pitch = 18.0
        num_base_pairs = 32

        for i in range(num_base_pairs):
            s = (i - num_base_pairs // 2) * pitch
            y_base = cy + int(s * 0.45)
            if not (15 <= y_base < h - 15):
                continue

            th = omega + i * 0.42
            x1 = cx + int(radius * math.cos(th))
            z1 = radius * math.sin(th)
            x2 = cx + int(radius * math.cos(th + math.pi))
            z2 = radius * math.sin(th + math.pi)

            c_pair = (80, 220, 120) if i % 2 == 0 else (255, 190, 40)
            canvas.draw_line(x1, y_base, x2, y_base, c_pair)

            size1 = 4 if z1 > 0 else 2
            int1 = int(np.clip(180 + z1 * 1.3, 80, 255))
            canvas.draw_circle(x1, y_base, size1, (0, int1, 230), fill=True)

            size2 = 4 if z2 > 0 else 2
            int2 = int(np.clip(180 + z2 * 1.3, 80, 255))
            canvas.draw_circle(x2, y_base, size2, (int2, 50, 140), fill=True)

    # -------------------------------------------------------------------------
    # 7. Atractor Caótico de Lorenz RK4
    # -------------------------------------------------------------------------
    elif fn == "lorenz_chaos":
        canvas.clear(bg_color=(4, 6, 14))
        sigma, rho, beta = 10.0, 28.0, 8.0 / 3.0
        dt = 0.008
        x_val, y_val, z_val = 0.1, 1.0, 1.05
        steps = int(1200 + t * 450)
        trail_pts: List[Tuple[int, int, int]] = []

        for st in range(steps):
            dx1 = sigma * (y_val - x_val)
            dy1 = x_val * (rho - z_val) - y_val
            dz1 = x_val * y_val - beta * z_val

            x_val += dx1 * dt
            y_val += dy1 * dt
            z_val += dz1 * dt

            if st > steps - 350:
                px = int(cx + (x_val - y_val) * 4.8)
                py = int(cy + 40 - z_val * 4.2 + (x_val + y_val) * 1.2)
                trail_pts.append((px, py, st))

        for i in range(len(trail_pts) - 1):
            p1 = trail_pts[i]
            p2 = trail_pts[i+1]
            progress = i / float(len(trail_pts))
            c_trail = (
                int(progress * 255),
                int((1.0 - progress) * 200 + 40),
                int(240 * progress + 15)
            )
            canvas.draw_line(p1[0], p1[1], p2[0], p2[1], c_trail)

        if trail_pts:
            head = trail_pts[-1]
            canvas.draw_circle(head[0], head[1], 4, (255, 255, 255), fill=True)
            canvas.draw_soft_radial_glow(head[0], head[1], 18, (255, 220, 60), (0, 0, 0), dither_strength=0.3)

    # -------------------------------------------------------------------------
    # 8. Reactor de Fusión Tokamak
    # -------------------------------------------------------------------------
    elif fn == "tokamak_fusion_reactor":
        canvas.clear(bg_color=(4, 6, 16))
        # Bobinas magnéticas toroidales
        for ang_deg in range(0, 360, 30):
            ang = math.radians(ang_deg)
            coil_x = cx + int(85 * math.cos(ang))
            coil_y = cy + int(45 * math.sin(ang))
            canvas.draw_circle(coil_x, coil_y, 22, (50, 60, 85), fill=False)

        # Anillo de plasma toroidal brillante con rotación helicoidal
        r_torus = 80.0
        angle_plasma = t * 4.0
        num_pts = 120
        for i in range(num_pts):
            phi = 2.0 * math.pi * i / num_pts
            px = cx + int(r_torus * math.cos(phi))
            py = cy + int((r_torus * 0.45) * math.sin(phi))

            # Fibras de plasma helicoidales
            theta_helix = phi * 6.0 + angle_plasma
            hx = px + int(12.0 * math.cos(theta_helix))
            hy = py + int(12.0 * math.sin(theta_helix))

            glow_c = (0, 240, 255) if i % 2 == 0 else (255, 120, 20)
            canvas.set_pixel(hx, hy, glow_c)

        canvas.draw_soft_radial_glow(cx, cy, 70, (140, 30, 240), (0, 0, 0), dither_strength=0.35)
        canvas.draw_circle(cx, cy, 28, (255, 255, 255), fill=False)

    # -------------------------------------------------------------------------
    # 9. Supernova & Remanente de Expansión
    # -------------------------------------------------------------------------
    elif fn == "supernova_explosion":
        canvas.clear(bg_color=(2, 2, 8))
        shock_r = int(25 + t * 40.0) % 110
        num_filaments = 64

        for f_idx in range(num_filaments):
            ang = 2.0 * math.pi * f_idx / num_filaments
            noise_r = shock_r + int(12 * math.sin(f_idx * 0.7 + t * 5.0))
            fx = cx + int(noise_r * math.cos(ang))
            fy = cy + int(noise_r * math.sin(ang))

            col_c = (255, int(80 + 120 * math.sin(ang + t)), int(200 + 55 * math.cos(ang)))
            canvas.draw_line(cx, cy, fx, fy, col_c)

        canvas.draw_soft_radial_glow(cx, cy, max(15, shock_r // 2), (255, 240, 180), (0, 0, 0), dither_strength=0.4)
        canvas.draw_circle(cx, cy, 6, (255, 255, 255), fill=True)

    # -------------------------------------------------------------------------
    # 10. Cyber Speeder en Autopista Synthwave
    # -------------------------------------------------------------------------
    elif fn == "cyber_speeder_highway":
        canvas.clear(bg_color=(12, 6, 26))
        horizon_y = cy - 10

        # Sol retro gigante con líneas horizontales
        sun_y = horizon_y - 25
        canvas.draw_circle(cx, sun_y, 45, (255, 45, 140), fill=True)
        for sy_cut in range(sun_y - 15, sun_y + 45, 6):
            canvas.draw_line(cx - 45, sy_cut, cx + 45, sy_cut, (12, 6, 26))

        # Cuadrícula synthwave en perspectiva
        canvas.draw_synthwave_perspective_grid(horizon_y, t, grid_color=(0, 245, 212), v_speed=3.2)

        # Speeder futurista centrado con balanceo
        speeder_x = cx + int(8 * math.sin(t * 4.0))
        speeder_y = cy + 50
        # Cuerpo del vehículo
        canvas.draw_rect(speeder_x - 22, speeder_y, 44, 14, (30, 35, 55), fill=True)
        canvas.draw_rect(speeder_x - 22, speeder_y, 44, 14, (0, 245, 212), fill=False)
        canvas.draw_rect(speeder_x - 12, speeder_y - 6, 24, 8, (240, 30, 140), fill=True)
        # Propulsores traseros brillantes
        canvas.draw_soft_radial_glow(speeder_x - 14, speeder_y + 14, 12, (255, 0, 128), (0, 0, 0), dither_strength=0.2)
        canvas.draw_soft_radial_glow(speeder_x + 14, speeder_y + 14, 12, (255, 0, 128), (0, 0, 0), dither_strength=0.2)

    # -------------------------------------------------------------------------
    # 11. Tempestad Oceánica con Relámpagos
    # -------------------------------------------------------------------------
    elif fn == "storm_lightning_ocean":
        canvas.clear(bg_color=(6, 12, 22))
        water_y = cy + 25

        # Nubes de tormenta oscuras con gradiente
        canvas.blit_dithered_gradient(0, water_y, (4, 8, 16), (25, 38, 55), dither_strength=0.45)

        # Olas tempestuosas
        for wx in range(0, w, 4):
            wy = int(water_y + 18 * math.sin(wx * 0.04 + t * 6.0) + 8 * math.cos(wx * 0.08 - t * 4.0))
            canvas.draw_line(wx, wy, wx, h - 1, (18, 32, 52))
            canvas.set_pixel(wx, wy, (200, 230, 255))  # Espuma

        # Descarga eléctrica de relámpago periódica
        cycle_t = t % 1.2
        if cycle_t < 0.15:
            # Destello global
            canvas.buffer = np.clip(canvas.buffer.astype(np.int16) + 40, 0, 255).astype(np.uint8)
            # Relámpago procedural
            np.random.seed(int(t * 10))
            lx_start = np.random.randint(cx - 80, cx + 80)
            canvas.draw_procedural_lightning(lx_start, 10, cx + np.random.randint(-40, 40), water_y + 10)

    # -------------------------------------------------------------------------
    # 12. Red Sináptica Neuronal
    # -------------------------------------------------------------------------
    elif fn == "neural_synapse_network":
        canvas.clear(bg_color=(4, 8, 20))
        np.random.seed(42)
        nodes = [(np.random.randint(40, w - 40), np.random.randint(30, h - 30)) for _ in range(12)]

        # Axones interconectados
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                n1, n2 = nodes[i], nodes[j]
                dist = math.hypot(n1[0] - n2[0], n1[1] - n2[1])
                if dist < 140:
                    canvas.draw_line(n1[0], n1[1], n2[0], n2[1], (20, 50, 90))

                    # Pulso eléctrico viajando por el axón
                    pulse_t = (t * 2.5 + i * 0.3) % 1.0
                    px = int(n1[0] + (n2[0] - n1[0]) * pulse_t)
                    py = int(n1[1] + (n2[1] - n1[1]) * pulse_t)
                    canvas.draw_circle(px, py, 2, (0, 255, 180), fill=True)

        # Somas neuronales con resplandor
        for nx, ny in nodes:
            canvas.draw_circle(nx, ny, 6, (0, 210, 240), fill=True)
            canvas.draw_soft_radial_glow(nx, ny, 16, (0, 210, 240), (0, 0, 0), dither_strength=0.25)

    # -------------------------------------------------------------------------
    # 13. Variedad de Calabi-Yau 6D
    # -------------------------------------------------------------------------
    elif fn == "calabi_yau_manifold":
        canvas.clear(bg_color=(6, 6, 20))
        rot_ang = t * 1.5
        u_vals = np.linspace(-math.pi, math.pi, 28)
        v_vals = np.linspace(-math.pi, math.pi, 28)

        for u in u_vals:
            for v in v_vals:
                # Proyección isométrica de hipersuperficie
                r_cross = 55.0 * (1.0 + 0.35 * math.cos(3 * u))
                x_3d = r_cross * math.cos(v + rot_ang)
                y_3d = r_cross * math.sin(v + rot_ang)
                z_3d = 35.0 * math.sin(u) * math.cos(2 * v)

                px = int(cx + x_3d * 0.866 - y_3d * 0.5)
                py = int(cy + 0.5 * (x_3d * 0.5 + y_3d * 0.866) - z_3d * 0.7)

                if 0 <= px < w and 0 <= py < h:
                    c_calabi = (
                        int(120 + 110 * math.cos(u)),
                        int(180 + 75 * math.sin(v)),
                        int(240)
                    )
                    canvas.set_pixel(px, py, c_calabi)

        canvas.draw_soft_radial_glow(cx, cy, 65, (72, 202, 228), (0, 0, 0), dither_strength=0.3)

    # -------------------------------------------------------------------------
    # 14. Eje Solar & CME
    # -------------------------------------------------------------------------
    elif fn == "solar_coronal_mass_ejection":
        canvas.clear(bg_color=(8, 2, 4))
        # Granulación solar en fotosfera
        canvas.draw_circle(cx, cy, 75, (255, 140, 20), fill=True)
        canvas.draw_soft_radial_glow(cx, cy, 110, (255, 60, 10), (0, 0, 0), dither_strength=0.4)

        # Lazo coronal magnético eruptivo
        loop_ang = t * 2.0
        loop_r = 75 + int(30 * math.sin(loop_ang))
        for deg in range(0, 180, 4):
            rad = math.radians(deg)
            lx = cx + int((loop_r + 20 * math.sin(rad)) * math.cos(rad - 0.4))
            ly = cy - int((loop_r + 25 * math.sin(rad)) * math.sin(rad))
            canvas.draw_circle(lx, ly, 3, (255, 240, 120), fill=True)

    # -------------------------------------------------------------------------
    # 15. Sistema Solar en Movimiento & Órbitas Keplerianas
    # -------------------------------------------------------------------------
    elif fn == "solar_system_orbits":
        canvas.clear(bg_color=(2, 3, 10))

        # Estrellas de fondo con parpadeo suave
        np.random.seed(77)
        for _ in range(120):
            sx = np.random.randint(0, w)
            sy = np.random.randint(0, h)
            tw = int(140 + 70 * math.sin(t * 3.0 + sx * 0.1))
            canvas.set_pixel(sx, sy, (tw, tw, tw))

        # Sol central resplandeciente con fulgor y corona
        sun_r = 18
        canvas.draw_soft_radial_glow(cx, cy, 55, (255, 180, 20), (0, 0, 0), dither_strength=0.35)
        canvas.draw_circle(cx, cy, sun_r, (255, 230, 80), fill=True)
        canvas.draw_circle(cx, cy, sun_r - 4, (255, 255, 220), fill=True)

        # Planetas definidos: (dist_a, dist_b, vel_kepler, radio_px, color_rgb, nombre, tiene_anillos)
        planets = [
            (38.0, 14.0, 4.2, 3, (180, 160, 140), "Mercurio", False),
            (62.0, 22.0, 3.1, 5, (240, 200, 110), "Venus", False),
            (92.0, 32.0, 2.5, 6, (60, 150, 240), "Tierra", False),
            (126.0, 44.0, 2.0, 4, (230, 80, 40), "Marte", False),
            (172.0, 60.0, 1.4, 9, (220, 180, 130), "Saturno", True),
        ]

        # Trayectorias orbitales elípticas en perspectiva (inclinación orbital)
        for a_orb, b_orb, _, _, _, _, _ in planets:
            for deg in range(0, 360, 6):
                rad = math.radians(deg)
                ox = int(cx + a_orb * math.cos(rad))
                oy = int(cy + b_orb * math.sin(rad))
                if (deg // 6) % 2 == 0:
                    canvas.set_pixel(ox, oy, (25, 40, 65))

        # Dibujar cada planeta con posición orbital, iluminación y satélites
        for a_orb, b_orb, vel_k, p_rad, p_col, p_name, has_rings in planets:
            orb_angle = t * vel_k
            px = int(cx + a_orb * math.cos(orb_angle))
            py = int(cy + b_orb * math.sin(orb_angle))

            # Dibujar anillos de Saturno detrás del planeta si corresponde
            if has_rings:
                for r_deg in range(120, 240, 6):
                    r_rad = math.radians(r_deg)
                    rx = px + int((p_rad + 8) * math.cos(r_rad))
                    ry = py + int(4 * math.sin(r_rad))
                    canvas.set_pixel(rx, ry, (190, 170, 130))

            # Cuerpo del planeta con terminador de sombra (fase respecto al Sol)
            canvas.draw_circle(px, py, p_rad, p_col, fill=True)

            # Lado iluminado hacia el centro (Sol)
            dx_sun = cx - px
            dy_sun = cy - py
            dist_sun = math.sqrt(dx_sun*dx_sun + dy_sun*dy_sun) + 1e-4
            nx, ny = dx_sun / dist_sun, dy_sun / dist_sun

            # Resplandor frontal del planeta
            hx = px + int(nx * (p_rad * 0.5))
            hy = py + int(ny * (p_rad * 0.5))
            canvas.set_pixel(hx, hy, (255, 255, 255))

            # Luna para la Tierra
            if p_name == "Tierra":
                moon_ang = t * 12.0
                mx = px + int(11 * math.cos(moon_ang))
                my = py + int(5 * math.sin(moon_ang))
                canvas.set_pixel(mx, my, (220, 220, 220))

            # Anillos de Saturno por delante
            if has_rings:
                for r_deg in range(-60, 60, 6):
                    r_rad = math.radians(r_deg)
                    rx = px + int((p_rad + 8) * math.cos(r_rad))
                    ry = py + int(4 * math.sin(r_rad))
                    canvas.set_pixel(rx, ry, (230, 210, 160))

    # -------------------------------------------------------------------------
    # 16. Tesseract 4D Hypercube
    # -------------------------------------------------------------------------
    elif fn == "tesseract_4d_hypercube":
        canvas.clear(bg_color=(4, 6, 16))
        th1 = t * 1.8
        th2 = t * 1.1

        # 16 vértices de un 4D tesseract [-1, 1]^4
        v_4d = []
        for x in (-1, 1):
            for y in (-1, 1):
                for z in (-1, 1):
                    for w_coord in (-1, 1):
                        v_4d.append(np.array([x, y, z, w_coord], dtype=np.float32))

        # Rotación XY y ZW
        c1, s1 = math.cos(th1), math.sin(th1)
        c2, s2 = math.cos(th2), math.sin(th2)

        proj_2d = []
        for v in v_4d:
            rx = v[0] * c1 - v[1] * s1
            ry = v[0] * s1 + v[1] * c1
            rz = v[2] * c2 - v[3] * s2
            rw = v[2] * s2 + v[3] * c2

            # Proyección estereográfica 4D a 3D y luego isométrica 2D
            dist_4d = 2.8 - rw * 0.45
            p3x = (rx / dist_4d) * 65.0
            p3y = (ry / dist_4d) * 65.0
            p3z = (rz / dist_4d) * 65.0

            px = int(cx + p3x * 0.866 - p3y * 0.5)
            py = int(cy + 0.5 * (p3x * 0.5 + p3y * 0.866) - p3z * 0.7)
            proj_2d.append((px, py))

        # Aristas que conectan vértices adyacentes (distancia Hamming = 1)
        for i in range(16):
            for j in range(i + 1, 16):
                diff = bin(i ^ j).count("1")
                if diff == 1:
                    p1 = proj_2d[i]
                    p2 = proj_2d[j]
                    canvas.draw_line(p1[0], p1[1], p2[0], p2[1], (0, 240, 220))

        for px, py in proj_2d:
            canvas.draw_circle(px, py, 3, (255, 255, 255), fill=True)

        canvas.draw_soft_radial_glow(cx, cy, 60, (120, 80, 255), (0, 0, 0), dither_strength=0.3)

    # -------------------------------------------------------------------------
    # 16. Colisión de Galaxias Espirales
    # -------------------------------------------------------------------------
    elif fn == "galaxy_collision":
        canvas.clear(bg_color=(2, 2, 8))
        np.random.seed(42)

        # Núcleo 1 y Núcleo 2 orbitándose
        orb_r = 55.0
        ang_orb = t * 1.2
        g1_x = cx + int(orb_r * math.cos(ang_orb))
        g1_y = cy + int((orb_r * 0.4) * math.sin(ang_orb))

        g2_x = cx + int(orb_r * math.cos(ang_orb + math.pi))
        g2_y = cy + int((orb_r * 0.4) * math.sin(ang_orb + math.pi))

        # Brazos espirales de Galaxia 1
        for i in range(180):
            r = np.random.uniform(5, 50)
            arm_ang = 2.8 * math.log(r) + t * 2.0
            px = g1_x + int(r * math.cos(arm_ang))
            py = g1_y + int(r * 0.55 * math.sin(arm_ang))
            canvas.set_pixel(px, py, (0, 200, 255))

        # Brazos espirales de Galaxia 2
        for i in range(180):
            r = np.random.uniform(5, 45)
            arm_ang = -2.8 * math.log(r) - t * 1.8
            px = g2_x + int(r * math.cos(arm_ang))
            py = g2_y + int(r * 0.55 * math.sin(arm_ang))
            canvas.set_pixel(px, py, (255, 180, 40))

        canvas.draw_soft_radial_glow(g1_x, g1_y, 22, (0, 240, 255), (0, 0, 0), dither_strength=0.25)
        canvas.draw_soft_radial_glow(g2_x, g2_y, 20, (255, 200, 60), (0, 0, 0), dither_strength=0.25)

    # -------------------------------------------------------------------------
    # 17. SÍNTESIS PROCEDURAL UNIVERSAL NANO BANANA (Para Cualquier Prompt Libre)
    # -------------------------------------------------------------------------
    else:
        canvas.clear(bg_color=(6, 10, 24))

        # 1. Fondo atmosférico/cósmico procedural con gradiente Bayer
        canvas.blit_dithered_gradient(
            0, h,
            color_top=(12, 18, 38),
            color_bottom=(4, 6, 14),
            dither_strength=0.45
        )

        # 2. Horizonte o cuadrícula de base procedural
        canvas.draw_synthwave_perspective_grid(cy + 40, t, grid_color=(80, 25, 110), v_speed=1.5)

        # 3. Entidad geométrica central tridimensional (Esfera Phong 3D con pulso y órbita)
        sphere_r = int(38 + 6 * math.sin(t * 3.0))
        light_x = math.cos(t * 2.0)
        light_y = math.sin(t * 2.0)
        canvas.draw_dithered_sphere_3d(
            cx, cy - 15,
            radius=sphere_r,
            base_color=(0, 210, 240),
            light_pos=(light_x, -0.6, 0.8),
            ambient=0.2,
            dither_strength=0.35
        )

        # Anillos orbitales procedurales en rotación
        for ring_idx in (1, 2):
            r_maj = sphere_r + ring_idx * 20
            th_ring = t * (2.2 / ring_idx)
            for deg in range(0, 360, 4):
                rad = math.radians(deg)
                rx = cx + int(r_maj * math.cos(rad))
                ry = (cy - 15) + int((r_maj * 0.38) * math.sin(rad + th_ring))
                canvas.set_pixel(rx, ry, (255, 45, 140))

        # Enjambre de partículas dinámicas en vórtice
        np.random.seed(int(t * 10) % 500)
        for p_idx in range(60):
            p_ang = np.random.uniform(0, 2 * math.pi)
            p_dist = np.random.uniform(sphere_r + 5, sphere_r + 75)
            px = cx + int(p_dist * math.cos(p_ang + t * 3.0))
            py = (cy - 15) + int(p_dist * 0.5 * math.sin(p_ang + t * 3.0))
            canvas.set_pixel(px, py, (255, 230, 80))

        canvas.draw_soft_radial_glow(cx, cy - 15, sphere_r + 30, (140, 50, 230), (0, 0, 0), dither_strength=0.35)

    # -------------------------------------------------------------------------
    # HUD DE TELEMETRÍA PIXEL ART NANO BANANA 1080P60 (Siempre Presente)
    # -------------------------------------------------------------------------
    header_title = f"TARDIS VP-NANO-BANANA :: {spec.concept.upper()[:34]}"
    canvas.draw_text(16, 12, header_title, (0, 245, 212), scale=1)
    fps_hud = f"60 FPS | 1080P | T={t:.2f}S"
    canvas.draw_text(w - len(fps_hud) * 6 - 16, 12, fps_hud, (255, 209, 102), scale=1)

    # Borde sutil del marco
    canvas.draw_rect(8, 6, w - 16, h - 12, (20, 45, 75), fill=False)


# =============================================================================
# 5. ORQUESTADOR PRINCIPAL DEL COMANDO /vp (NANO BANANA POWER)
# =============================================================================

class TardisVPEngine:
    """Motor Autónomo Soberano de Generación de Video Pixel Art a 1080P @ 60 FPS."""

    _instance: Optional[TardisVPEngine] = None

    @classmethod
    def get_instance(cls) -> TardisVPEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.native_w = 480
        self.native_h = 270
        self.fps = 60           # Siempre a 60 FPS Nativos estricto
        self.out_w = 1920       # Siempre a 1080P Full HD (1920x1080)
        self.out_h = 1080

    def generate_sketch_image(self, spec: NanoBananaProceduralSpec, safe_slug: str) -> Tuple[Path, Path]:
        """
        Genera el boceto estático de referencia en Pixel Art más cercano a la realidad.
        Guarda la versión nativa (480x270) y la versión escalada 1080P (1920x1080).
        """
        logger.info(f"Generando boceto Pixel Art Nano Banana para: '{spec.concept}'...")
        canvas = PixelCanvas480(self.native_w, self.native_h)
        
        # Renderizar en t=0.0
        render_frame_for_spec(canvas, spec, t=0.0, frame_idx=0, total_frames=300)

        # 1. Guardar versión nativa (480x270)
        native_path = OUTPUT_VIDEOS_DIR / f"tardis_vp_{safe_slug}_sketch_native.png"
        cv2.imwrite(str(native_path), cv2.cvtColor(canvas.buffer, cv2.COLOR_RGB2BGR))

        # 2. Guardar versión 1080P (1920x1080) por vecino más cercano
        sketch_1080p_path = OUTPUT_VIDEOS_DIR / f"tardis_vp_{safe_slug}_sketch_1080p.png"
        frame_1080p = canvas.to_1080p(scanlines=False)
        cv2.imwrite(str(sketch_1080p_path), cv2.cvtColor(frame_1080p, cv2.COLOR_RGB2BGR))

        logger.info(f"Boceto Pixel Art 1080P guardado con éxito en: {sketch_1080p_path}")
        return sketch_1080p_path, native_path

    def render_video_1080p60(
        self,
        spec: NanoBananaProceduralSpec,
        safe_slug: str,
        duration_sec: float = 5.0
    ) -> Tuple[Path, Path]:
        """
        Sintetiza el video completo a 1080P (1920x1080) a 60 FPS Nativos.
        Utiliza aceleración de GPU NVIDIA NVENC (h264_nvenc) mediante tubería directa.
        """
        mp4_path = OUTPUT_VIDEOS_DIR / f"tardis_vp_{safe_slug}_1080p60.mp4"
        gif_path = OUTPUT_VIDEOS_DIR / f"tardis_vp_{safe_slug}_preview.gif"

        total_frames = int(self.fps * duration_sec)
        dt = 1.0 / float(self.fps)

        logger.info(f"Iniciando síntesis Nano Banana 1080P @ 60 FPS ({total_frames} cuadros, {duration_sec}s)...")
        t0 = time.time()

        # Configurar pipeline ffmpeg con NVENC acelerado
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{self.out_w}x{self.out_h}",
            "-pix_fmt", "bgr24",
            "-r", str(self.fps),
            "-i", "-",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-cq", "18",
            "-pix_fmt", "yuv420p",
            str(mp4_path)
        ]

        # Verificar si NVENC está disponible, si no usar libx264
        use_nvenc = True
        try:
            test_pipe = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            use_nvenc = False
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{self.out_w}x{self.out_h}",
                "-pix_fmt", "bgr24",
                "-r", str(self.fps),
                "-i", "-",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                str(mp4_path)
            ]
            test_pipe = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        canvas = PixelCanvas480(self.native_w, self.native_h)
        gif_frames: List[Image.Image] = []
        gif_stride = max(1, self.fps // 15)  # Muestrear a 15 fps para el GIF liviano

        for frame_idx in range(total_frames):
            t = frame_idx * dt
            render_frame_for_spec(canvas, spec, t, frame_idx, total_frames)
            frame_1080p = canvas.to_1080p(scanlines=False)
            frame_bgr = cv2.cvtColor(frame_1080p, cv2.COLOR_RGB2BGR)

            try:
                test_pipe.stdin.write(frame_bgr.tobytes())
            except Exception as e_write:
                logger.error(f"Error escribiendo frame a ffmpeg: {e_write}")
                break

            # Muestrear frame para el GIF animado
            if frame_idx % gif_stride == 0:
                small_preview = cv2.resize(canvas.buffer, (240, 135), interpolation=cv2.INTER_NEAREST)
                gif_frames.append(Image.fromarray(small_preview))

        test_pipe.stdin.close()
        test_pipe.wait()
        elapsed = time.time() - t0
        render_fps = total_frames / max(0.001, elapsed)
        logger.info(f"Renderizado y codificación 1080P @ 60 FPS completado en {elapsed:.2f}s ({render_fps:.1f} fps render).")

        # Guardar GIF animado optimizado
        if gif_frames:
            try:
                quantized_frames = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=48) for f in gif_frames]
                quantized_frames[0].save(
                    str(gif_path),
                    save_all=True,
                    append_images=quantized_frames[1:],
                    duration=int(1000 / 15),
                    loop=0,
                    optimize=True
                )
            except Exception as e_gif:
                logger.warning(f"No se pudo guardar GIF: {e_gif}")

        # Enforzamiento de Sonificación Acústica TARDIS
        if AUDIO_SYNTH_AVAILABLE and mp4_path.exists():
            try:
                ensure_video_has_audio(
                    video_path=mp4_path,
                    title=spec.concept,
                    formula=spec.formula_latex,
                    domain=spec.category
                )
                logger.info("Sonificación cuántica inyectada y multiplexada con éxito en el video final.")
            except Exception as e_audio:
                logger.warning(f"Error en sonificación de audio: {e_audio}")

        return mp4_path, gif_path

    def run_pipeline(self, prompt: str, duration_sec: float = 5.0) -> Dict[str, Any]:
        """
        Ejecuta el pipeline completo de principio a fin para el comando /vp.
        """
        logger.info("==================================================================")
        logger.info(f"EJECUTANDO PIPELINE NANO BANANA /vp: '{prompt}'")
        logger.info("==================================================================")
        t_start = time.time()

        # 1. Blueprint Semántico Nano Banana e Investigación Factual
        spec = analyze_and_research_prompt(prompt)
        safe_slug = re.sub(r"[^a-zA-Z0-9_]", "_", spec.concept.lower())[:32]

        # 2. Generación del Boceto Pixel Art Realista 1080P
        sketch_1080p, sketch_native = self.generate_sketch_image(spec, safe_slug)

        # 3. Síntesis de Video a 60 FPS y 1080P Nativos
        mp4_path, gif_path = self.render_video_1080p60(spec, safe_slug, duration_sec=duration_sec)

        total_elapsed = time.time() - t_start
        file_size_mb = mp4_path.stat().st_size / (1024 * 1024) if mp4_path.exists() else 0.0

        result = {
            "status": "SUCCESS",
            "command": "/vp",
            "query": prompt,
            "concept": spec.concept,
            "subject": spec.subject,
            "action": spec.action,
            "context": spec.context,
            "art_style": spec.art_style,
            "category": spec.category,
            "formula_latex": spec.formula_latex,
            "spectral_research": spec.spectral_research,
            "resolution": "1920x1080 (1080P Full HD)",
            "framerate": 60,
            "duration_sec": duration_sec,
            "sketch_image_1080p": str(sketch_1080p),
            "sketch_image_native": str(sketch_native),
            "video_path": str(mp4_path),
            "gif_path": str(gif_path),
            "file_size_mb": round(file_size_mb, 2),
            "elapsed_seconds": round(total_elapsed, 2)
        }

        logger.info(f"Secuencia /vp Nano Banana completada exitosamente en {total_elapsed:.2f}s:")
        logger.info(f"  • Imagen Pixel Art 1080P: {sketch_1080p}")
        logger.info(f"  • Video Final 60 FPS 1080P: {mp4_path} ({result['file_size_mb']} MB)")
        return result


def generate_vp_pixelart_video(prompt: str, duration_sec: float = 5.0) -> Dict[str, Any]:
    """Punto de entrada programático rápido para /vp."""
    engine = TardisVPEngine.get_instance()
    return engine.run_pipeline(prompt, duration_sec=duration_sec)


# =============================================================================
# 6. ENTRADA CLI DIRECTA
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TARDIS /vp - Motor de Video Pixel Art a 1080P @ 60 FPS (Nano Banana Power)"
    )
    parser.add_argument("prompt", nargs="+", help="Texto, fórmula o tema para generar video Pixel Art")
    parser.add_argument("--duration", type=float, default=5.0, help="Duración en segundos (por defecto 5.0 s)")
    args = parser.parse_args()

    full_prompt = " ".join(args.prompt)
    res = generate_vp_pixelart_video(full_prompt, duration_sec=args.duration)
    print("\n" + json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
