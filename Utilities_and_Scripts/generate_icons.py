#!/usr/bin/env python3
"""
generate_icons.py - Generador de iconos nativos para iPad Pro M2 (TARDIS)
"""

import base64
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("/home/timemachine/Escritorio/GODWORKS SYSTEM/tardis_ipad_native/assets")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_icon(size=512):
    img = Image.new("RGBA", (size, size), (8, 12, 22, 255))
    draw = ImageDraw.Draw(img)

    # Gradient rings / glow
    center = size // 2
    for r in range(size // 2 - 10, size // 2 - 40, -4):
        alpha = int(120 * (1 - (size // 2 - r) / 30))
        draw.ellipse([center - r, center - r, center + r, center + r], outline=(0, 229, 255, alpha), width=3)

    # Inner hexagon/rings
    inner_r = size // 3
    draw.ellipse([center - inner_r, center - inner_r, center + inner_r, center + inner_r], outline=(0, 150, 255, 180), width=4)

    # Central TARDIS symbol (Stylized Greek Omega / Shekel ₪ / Quantum Rotor)
    # Draw central stylized Police Box / Quantum Obelisk
    box_w = size // 4
    box_h = int(size * 0.42)
    x0 = center - box_w // 2
    y0 = center - box_h // 2 + 10
    x1 = center + box_w // 2
    y1 = y0 + box_h

    # Main box body
    draw.rectangle([x0, y0, x1, y1], fill=(12, 24, 48, 240), outline=(0, 229, 255, 255), width=4)

    # Roof & Light
    draw.polygon([(x0 - 8, y0), (x1 + 8, y0), (center + 12, y0 - 18), (center - 12, y0 - 18)], fill=(16, 36, 70, 255), outline=(0, 229, 255, 255))
    draw.rectangle([center - 6, y0 - 28, center + 6, y0 - 18], fill=(0, 255, 255, 255))

    # Windows / panels (2x3 grid)
    p_w = (box_w - 18) // 2
    p_h = (box_h - 40) // 4
    for row in range(4):
        for col in range(2):
            px0 = x0 + 6 + col * (p_w + 6)
            py0 = y0 + 16 + row * (p_h + 5)
            px1 = px0 + p_w
            py1 = py0 + p_h
            if row == 0:
                # White glowing window
                draw.rectangle([px0, py0, px1, py1], fill=(220, 245, 255, 230), outline=(0, 180, 230, 255), width=1)
            else:
                # Cyan neon panel
                draw.rectangle([px0, py0, px1, py1], fill=(18, 38, 68, 200), outline=(0, 140, 200, 200), width=1)

    # Accent badge: M2
    badge_w = int(size * 0.35)
    badge_h = int(size * 0.1)
    bx0 = center - badge_w // 2
    by0 = y1 - badge_h // 2
    bx1 = center + badge_w // 2
    by1 = by0 + badge_h
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=10, fill=(0, 229, 255, 255))
    
    return img

if __name__ == "__main__":
    icon_512 = generate_icon(512)
    icon_512.save(str(OUT_DIR / "icon_512.png"))

    icon_180 = icon_512.resize((180, 180), Image.Resampling.LANCZOS)
    icon_180.save(str(OUT_DIR / "icon_180.png"))

    icon_192 = icon_512.resize((192, 192), Image.Resampling.LANCZOS)
    icon_192.save(str(OUT_DIR / "icon_192.png"))

    # Base64 string for mobileconfig
    with open(OUT_DIR / "icon_180.png", "rb") as fp:
        b64 = base64.b64encode(fp.read()).decode("ascii")
        with open(OUT_DIR / "icon_base64.txt", "w") as b64_fp:
            b64_fp.write(b64)

    print("Icons generated successfully in", OUT_DIR)
