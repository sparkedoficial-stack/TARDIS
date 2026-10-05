#!/usr/bin/env python3
"""
==============================================================================
TARDIS POCKET - GENERADOR MAESTRO DE BOOTANIMATION (60 FPS / FULL-HD 1080x1920)
==============================================================================
Genera la animación de arranque a 60 FPS con el personaje oficial de TARDIS
(astrolabio rúnico, anillo dimensional, ondas cuánticas y cabina holográfica)
junto a la leyenda ciberespacial "(Cargando vinculo cuántico)".
==============================================================================
"""

import math
import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE_DIR = Path(__file__).resolve().parent
PART0_DIR = BASE_DIR / "part0"
PART1_DIR = BASE_DIR / "part1"
ZIP_OUTPUT = BASE_DIR / "bootanimation.zip"

WIDTH = 1080
HEIGHT = 1920
FPS = 60

# Paleta oficial TARDIS
COL_BG = (3, 8, 16)
COL_PRIMARY = (0, 212, 200)      # Neon Teal
COL_SECONDARY = (232, 182, 74)   # Solar Gold
COL_HULL = (4, 16, 28)           # Dark Cyan Glass
COL_PULSE = (14, 165, 233)       # Cyan Wave
COL_TEXT = (0, 255, 235)         # Bright Neon Cyan

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def get_font(size: int) -> ImageFont.ImageFont:
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def render_frame(t_sec: float, intro_progress: float = 1.0) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), COL_BG)
    draw = ImageDraw.Draw(img)

    cx = WIDTH // 2
    cy = int(HEIGHT * 0.44)
    intro_progress = max(0.08, intro_progress)
    base_size = max(30.0, 280.0 * intro_progress)

    # 1. Fondo con gradiente radial cinemático
    max_r = int(WIDTH * 0.75)
    for r in range(max_r, 0, -40):
        intensity = int(32 * (1.0 - r / float(max_r)) * intro_progress)
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=(3 + intensity, 8 + intensity * 2, 16 + intensity * 3)
        )

    # 2. Ondas Cuánticas Expansivas
    wave_count = 4
    for w in range(wave_count):
        wave_phase = (t_sec * 1.5 + w / float(wave_count)) % 1.0
        r_min = base_size * 0.5
        r_max = base_size * 1.3
        wr = r_min + wave_phase * (r_max - r_min)
        alpha = int((1.0 - wave_phase) * 160 * intro_progress)
        if alpha > 10:
            draw.ellipse(
                [(cx - wr, cy - wr), (cx + wr, cy + wr)],
                outline=COL_PRIMARY,
                width=max(1, int(3 * (1.0 - wave_phase)))
            )

    # 3. Dinámica del personaje (levitación armónica y respiración)
    float_y = math.sin(t_sec * 2.0) * (base_size * 0.035)
    breath = 1.0 + math.sin(t_sec * 3.0) * 0.018
    char_cy = cy + float_y
    size = base_size * breath

    # 4. Astrolabio Rúnico Rotatorio
    r_astrolabe = size * 0.82
    angle = t_sec * 0.45
    for i in range(12):
        a = angle + i * (2 * math.pi / 12)
        px1 = cx + math.cos(a) * (r_astrolabe * 0.9)
        py1 = char_cy + math.sin(a) * (r_astrolabe * 0.9)
        px2 = cx + math.cos(a) * (r_astrolabe * 1.05)
        py2 = char_cy + math.sin(a) * (r_astrolabe * 1.05)
        draw.line([(px1, py1), (px2, py2)], fill=COL_SECONDARY, width=2)

    draw.ellipse(
        [(cx - r_astrolabe, char_cy - r_astrolabe), (cx + r_astrolabe, char_cy + r_astrolabe)],
        outline=COL_SECONDARY,
        width=2
    )

    # 5. Cabina Central Holográfica TARDIS
    cab_w = size * 0.52
    cab_h = size * 0.72
    cab_x0 = cx - cab_w / 2
    cab_y0 = char_cy - cab_h / 2
    cab_x1 = cx + cab_w / 2
    cab_y1 = char_cy + cab_h / 2

    # Cuerpo exterior de la cabina
    draw.rounded_rectangle(
        [(cab_x0, cab_y0), (cab_x1, cab_y1)],
        radius=int(14 * intro_progress),
        fill=COL_HULL,
        outline=COL_PRIMARY,
        width=3
    )

    # Linterna superior
    lamp_w, lamp_h = cab_w * 0.22, cab_h * 0.12
    draw.rounded_rectangle(
        [(cx - lamp_w / 2, cab_y0 - lamp_h), (cx + lamp_w / 2, cab_y0)],
        radius=4,
        fill=(255, 255, 255),
        outline=COL_PRIMARY,
        width=2
    )

    # Paneles de ventana holográfica
    pan_margin = max(2.0, cab_w * 0.08)
    pan_w = (cab_w - pan_margin * 3) / 2
    pan_h = (cab_h * 0.35)
    if pan_w > 1 and pan_h > 1:
        for col in range(2):
            px = cab_x0 + pan_margin + col * (pan_w + pan_margin)
            py = cab_y0 + cab_h * 0.18
            draw.rectangle(
                [(px, py), (px + pan_w, py + pan_h)],
                fill=(10, 30, 48),
                outline=COL_PRIMARY,
                width=max(1, int(2 * intro_progress))
            )

    # Ojo / Núcleo de Inferencia Cuántica Central
    core_r = size * 0.14
    draw.ellipse(
        [(cx - core_r, char_cy + cab_h * 0.15 - core_r),
         (cx + core_r, char_cy + cab_h * 0.15 + core_r)],
        fill=(0, 212, 200),
        outline=(255, 255, 255),
        width=2
    )

    # 6. Leyenda Inferior: (Cargando vinculo cuántico)
    text = "(Cargando vinculo cuántico)"
    font = get_font(34)
    
    # Efecto de pulso en el texto
    text_alpha = 0.75 + 0.25 * math.sin(t_sec * 4.0)
    col_text_pulsed = (
        int(COL_TEXT[0] * text_alpha),
        int(COL_TEXT[1] * text_alpha),
        int(COL_TEXT[2] * text_alpha)
    )

    # Medir y centrar el texto
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw // 2
    ty = int(HEIGHT * 0.78)

    # Resplandor sutil (Glow) detrás del texto
    for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)]:
        draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 80, 80))
    draw.text((tx, ty), text, font=font, fill=col_text_pulsed)

    # 7. Barra de energía cuántica sutil bajo el texto
    bar_w = int(tw * 1.1)
    bar_h = 3
    bar_x = cx - bar_w // 2
    bar_y = ty + th + 18
    draw.line([(bar_x, bar_y), (bar_x + bar_w, bar_y)], fill=(0, 60, 80), width=bar_h)
    
    # Segmento móvil de energía en la barra
    seg_w = bar_w * 0.35
    seg_pos = (t_sec * 0.8) % 1.0
    seg_x1 = bar_x + seg_pos * (bar_w - seg_w)
    draw.line([(seg_x1, bar_y), (seg_x1 + seg_w, bar_y)], fill=COL_PRIMARY, width=bar_h)

    return img

def generate_bootanimation():
    print("===============================================================")
    print(" GENERANDO BOOTANIMATION 60 FPS PARA TARDIS POCKET (1080x1920)")
    print("===============================================================")

    # Limpiar directorios
    if PART0_DIR.exists():
        shutil.rmtree(PART0_DIR)
    if PART1_DIR.exists():
        shutil.rmtree(PART1_DIR)
    PART0_DIR.mkdir(parents=True, exist_ok=True)
    PART1_DIR.mkdir(parents=True, exist_ok=True)

    # 1. part0: Intro (30 cuadros = 0.5s a 60fps)
    print("Rendering part0 (Intro)...")
    for i in range(30):
        t = i / float(FPS)
        progress = math.sin((i / 30.0) * (math.pi / 2))
        frame = render_frame(t, intro_progress=progress)
        frame.save(PART0_DIR / f"{i:04d}.jpg", quality=92)

    # 2. part1: Loop continuo (120 cuadros = 2.0s a 60fps)
    print("Rendering part1 (Loop continuo 60 FPS)...")
    for i in range(120):
        t = 0.5 + (i / float(FPS))
        frame = render_frame(t, intro_progress=1.0)
        frame.save(PART1_DIR / f"{i:04d}.jpg", quality=92)

    # 3. desc.txt
    desc_path = BASE_DIR / "desc.txt"
    desc_content = f"{WIDTH} {HEIGHT} {FPS}\np 1 0 part0\np 0 0 part1\n"
    desc_path.write_text(desc_content, encoding="ascii")
    print(f"desc.txt creado:\n{desc_content.strip()}")

    # 4. Empaquetar bootanimation.zip (STORE ONLY - 0 compresión)
    if ZIP_OUTPUT.exists():
        ZIP_OUTPUT.unlink()

    # Android requiere que el zip no tenga compresión (zip -0)
    print("Empaquetando bootanimation.zip sin compresión...")
    subprocess.run(
        ["zip", "-0", "-r", str(ZIP_OUTPUT), "desc.txt", "part0", "part1"],
        cwd=str(BASE_DIR),
        check=True
    )

    size_mb = ZIP_OUTPUT.stat().st_size / (1024 * 1024)
    print(f"✓ bootanimation.zip creado exitosamente ({size_mb:.2f} MB): {ZIP_OUTPUT}")
    print("===============================================================")

if __name__ == "__main__":
    generate_bootanimation()
