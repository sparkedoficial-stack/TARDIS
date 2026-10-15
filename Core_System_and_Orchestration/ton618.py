"""
TON 618: Official Mascot & Singularity Engine of FTL
Faster-Than-Light: Unified Anthropic Claude Code & Google AGY/Gemini Engine

TON 618 is the ultramassive black hole and hyperluminous quasar (66 billion solar masses)
serving as the official mascot and celestial singularity of FTL.

This module provides:
- Procedural relativistic ray-marched ASCII/ANSI animation of TON 618
- Adaptive rendering for standard (80x24+), large (120x35+), and compact (iPad/mobile) viewports
- Relativistic physics: Keplerian differential rotation, Doppler beaming, gravitational lensing,
  photon sphere, and collimated polar energy jets
- Non-blocking/interruptible terminal playback with clean cursor management
"""

import math
import os
import shutil
import sys
import time
from typing import List, Tuple

# ANSI Escape Sequences
C_HIDE_CURSOR = "\033[?25l"
C_SHOW_CURSOR = "\033[?25h"
C_CURSOR_HOME = "\033[H"
C_CLEAR_SCREEN = "\033[2J"
C_RESET = "\033[0m"
C_BOLD = "\033[1m"


def rgb(r: int, g: int, b: int, text: str) -> str:
    """Renders text with 24-bit TrueColor foreground."""
    return f"\033[38;2;{r};{g};{b}m{text}{C_RESET}"


def rgb_bg(r: int, g: int, b: int, text: str) -> str:
    """Renders text with 24-bit TrueColor background."""
    return f"\033[48;2;{r};{g};{b}m{text}{C_RESET}"


def render_ton618_frame(t: float, width: int = 68, height: int = 13, compact: bool = False) -> List[str]:
    """
    Renders a single frame of TON 618 with relativistic physics:
    - Differential Keplerian rotation of the accretion disk
    - Relativistic Doppler boosting (approaching side = bright cyan/white, receding = redshifted amber/orange)
    - Gravitational lensing (warped upper & lower Einstein arcs)
    - Central event horizon shadow with '✦ TON 618 ✦'
    - Relativistic polar jets blasting outward with helical magnetic field
    """
    cx = width / 2.0
    cy = height // 2
    lines = []

    aspect = 2.2  # Terminal characters are ~2.2x taller than wide

    for y in range(height):
        row = []
        dy = (y - cy) * aspect
        is_center_y = (y == cy)

        for x in range(width):
            dx = (x - cx)
            r = math.sqrt(dx * dx + dy * dy)
            phi = math.atan2(dy, dx)

            # 1. Center Label inside the Event Horizon
            label = " ✦ TON 618 ✦ " if not compact else " TON 618 "
            lbl_start = int(cx) - len(label) // 2
            lbl_end = lbl_start + len(label)

            if is_center_y and lbl_start <= x < lbl_end:
                if x == lbl_start:
                    pulse = 0.8 + 0.2 * math.sin(t * 4.0)
                    cr = int(220 * pulse)
                    cg = int(255 * pulse)
                    cb = int(255 * pulse)
                    row.append(f"\033[1;38;2;{cr};{cg};{cb};48;2;6;8;15m{label}{C_RESET}")
                continue

            # 2. Relativistic Polar Jets (|dx| <= 1.2, |dy| >= 3.8)
            jet_threshold = 3.6 if not compact else 2.8
            if abs(dx) <= 1.2 and abs(dy) >= jet_threshold:
                # Helical jet phase
                jet_phase = (abs(dy) * 0.9 - t * 8.0) % 4.0
                if jet_phase < 1.0:
                    c, ch = (255, 255, 255), ("▲" if dy < 0 else "▼")
                elif jet_phase < 2.0:
                    c, ch = (0, 255, 204), "║"
                elif jet_phase < 3.0:
                    c, ch = (192, 132, 252), "│"
                else:
                    c, ch = (129, 140, 248), "✦"
                row.append(rgb(c[0], c[1], c[2], ch))
                continue

            # 3. Event Horizon Shadow (Singularity Interior)
            shadow_r = 7.8 if not compact else 5.2
            shadow_dy = 2.8 if not compact else 2.0
            if r < shadow_r and abs(dy) < shadow_dy:
                row.append(" ")
                continue

            # 4. Photon Ring (Einstein Sphere Boundary)
            ring_outer = 9.8 if not compact else 6.8
            if shadow_r <= r < ring_outer and abs(dy) < (shadow_dy + 1.2):
                if dx < 0:  # Blueshifted approaching side
                    row.append(rgb(255, 255, 255, "█"))
                else:  # Redshifted receding side
                    row.append(rgb(255, 180, 50, "▓"))
                continue

            # 5. Equatorial Accretion Disk (Crossing in front of the horizon)
            disk_radius = 32.0 if not compact else 22.0
            if is_center_y and r < disk_radius:
                dist_pct = (disk_radius - r) / disk_radius
                omega = 18.0 / (r + 2.0)
                m = math.sin(phi * 2.0 - t * omega)

                if dx < 0:  # Approaching: Blazing cyan / electric white
                    b_val = min(255, int(200 + 55 * dist_pct))
                    ch = "━" if m > 0.2 else ("═" if m > -0.2 else "─")
                    row.append(rgb(0, b_val, 255, ch))
                else:  # Receding: Redshifted amber / orange / crimson
                    r_val = min(255, int(210 + 45 * dist_pct))
                    g_val = min(200, int(130 * dist_pct))
                    ch = "─" if m > 0.2 else ("╌" if m > -0.2 else "·")
                    row.append(rgb(r_val, g_val, 40, ch))
                continue

            # 6. Gravitationally Lensed Upper & Lower Accretion Arcs
            lens_outer = 16.0 if not compact else 10.5
            lens_dy = 6.2 if not compact else 4.2
            if ring_outer <= r < lens_outer and abs(dy) < lens_dy:
                omega = 10.0 / (r + 1.0)
                m = math.sin(phi * 3.0 - t * omega)
                if dx < 0:
                    row.append(rgb(56, 189, 248, "▒" if m > 0 else "░"))
                else:
                    row.append(rgb(249, 115, 22, "░" if m > 0 else "·"))
                continue

            # 7. Outer Relativistic Swirling Matter / Interstellar Vortex
            vortex_outer = 29.0 if not compact else 20.0
            vortex_dy = 7.2 if not compact else 4.8
            if lens_outer <= r < vortex_outer and abs(dy) < vortex_dy:
                sp = math.sin(r * 0.42 + phi * 2.0 - t * 4.0)
                if sp > 0.82:
                    if dx < 0:
                        row.append(rgb(0, 255, 204, "·"))
                    else:
                        row.append(rgb(251, 191, 36, "·"))
                    continue

            # Vacuum / Deep Space
            row.append(" ")

        lines.append("".join(row))

    return lines


def get_ton618_status_bar(frame_idx: int, total_frames: int, width: int = 68) -> str:
    """Generates an epic narrative telemetry bar matching the animation phase."""
    progress = frame_idx / max(1, total_frames - 1)

    if progress < 0.25:
        msg = "COLAPSO GRAVITACIONAL DETECTADO · FORMANDO SINGULARIDAD ZERO-POINT"
        color = (129, 140, 248)
    elif progress < 0.55:
        msg = "DISCO DE ACRECIÓN RELATIVISTA ENCENDIDO · 66,000,000,000 MASAS SOLARES"
        color = (56, 189, 248)
    elif progress < 0.85:
        msg = "JETS POLARES RELATIVISTAS ACTIVOS · EL QUÁSAR MÁS BRILLANTE DEL COSMOS"
        color = (0, 255, 204)
    else:
        msg = "MASCOTA SOBERANA TON 618 EN LÍNEA · VELOCIDAD MÁS RÁPIDA QUE LA LUZ"
        color = (255, 215, 0)

    # Pad or truncate to width
    msg_str = f"✦ {msg} ✦"
    centered = msg_str.center(width)
    return rgb(color[0], color[1], color[2], f"{C_BOLD}{centered}{C_RESET}")


def get_ton618_badge_card(width: int = 68) -> str:
    """Returns the sovereign TON 618 mascot badge panel in ANSI."""
    box_w = min(width - 2, 70)
    inner_w = box_w - 4

    top = "╔" + "═" * (box_w - 2) + "╗"
    mid = "╠" + "═" * (box_w - 2) + "╣"
    bot = "╚" + "═" * (box_w - 2) + "╝"

    t1 = "🌌 MASCOTA & SINGULARIDAD SOBERANA DE FTL :: TON 618 🌌".center(inner_w)
    t2 = "Masa: 66 Mil Millones M☉  |  Luminosidad: 140 Billones L☉  |  Radio: 1,300 AU".center(inner_w)
    t3 = "Directiva: Aceleración Hiperlumínica · Inferencia Cuántica · Bypass Total".center(inner_w)

    lines = [
        rgb(0, 255, 204, top),
        rgb(0, 255, 204, "║ ") + rgb(255, 215, 0, f"{C_BOLD}{t1}{C_RESET}") + rgb(0, 255, 204, " ║"),
        rgb(0, 255, 204, mid),
        rgb(0, 255, 204, "║ ") + rgb(226, 232, 240, t2) + rgb(0, 255, 204, " ║"),
        rgb(0, 255, 204, "║ ") + rgb(148, 163, 184, t3) + rgb(0, 255, 204, " ║"),
        rgb(0, 255, 204, bot),
    ]
    return "\n".join(lines)


def play_ton618_animation(frames: int = 18, delay: float = 0.07, force: bool = False) -> None:
    """
    Plays the cinematic TON 618 animation at terminal startup.
    - Responsive to terminal size (auto-centers, fits 80x24, scales down for iPad/mobile)
    - Interruptible via Ctrl+C / Enter without errors
    - Restores terminal cursor cleanly
    """
    # Only animate in interactive TTY sessions unless forced
    if not force and not sys.stdout.isatty():
        return

    term_size = shutil.get_terminal_size((80, 24))
    cols = term_size.columns
    lines = term_size.lines

    compact = cols < 72 or lines < 20
    anim_w = min(cols - 2, 68 if not compact else 48)
    anim_h = 13 if not compact else 9

    # Clean terminal start
    sys.stdout.write(C_HIDE_CURSOR)
    sys.stdout.write(C_CLEAR_SCREEN)
    sys.stdout.write(C_CURSOR_HOME)
    sys.stdout.flush()

    try:
        for idx in range(frames):
            t = idx * 0.28
            frame_lines = render_ton618_frame(t, width=anim_w, height=anim_h, compact=compact)
            status = get_ton618_status_bar(idx, frames, width=anim_w)

            # Center horizontally if terminal is wide
            left_pad = " " * max(0, (cols - anim_w) // 2)

            buf = [C_CURSOR_HOME]
            for row in frame_lines:
                buf.append(f"{left_pad}{row}\n")

            buf.append(f"\n{left_pad}{status}\n")
            sys.stdout.write("".join(buf))
            sys.stdout.flush()

            time.sleep(delay)

        # Final hold frame
        time.sleep(0.15)

    except KeyboardInterrupt:
        # Gracefully handle skip
        pass
    except Exception:
        pass
    finally:
        sys.stdout.write(C_SHOW_CURSOR)
        sys.stdout.flush()


def get_ton618_art() -> str:
    """Returns a static, fully rendered truecolor representation of TON 618."""
    term_size = shutil.get_terminal_size((80, 24))
    cols = term_size.columns
    compact = cols < 72
    anim_w = min(cols - 2, 68 if not compact else 48)
    anim_h = 13 if not compact else 9

    lines = render_ton618_frame(2.5, width=anim_w, height=anim_h, compact=compact)
    left_pad = " " * max(0, (cols - anim_w) // 2)
    centered_lines = [f"{left_pad}{row}" for row in lines]
    badge = get_ton618_badge_card(width=anim_w)
    centered_badge = "\n".join([f"{left_pad}{b_row}" for b_row in badge.splitlines()])

    return "\n".join(centered_lines) + "\n\n" + centered_badge


if __name__ == "__main__":
    play_ton618_animation(frames=20, delay=0.06, force=True)
    print("\n" + get_ton618_badge_card())
