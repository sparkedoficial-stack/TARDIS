"""
core/video_pipeline_4k.py - Tubería de Video 4K @ 60 FPS con Gráficos Vivos de TARDIS
=====================================================================================
Renderiza los videomensajes del personaje 3D de TARDIS en UHD (3840x2160) a 60 FPS
impulsados por la telemetría viva y el manifiesto visual del sistema:

  * Estado vocal híbrido: marcas fonéticas + envolvente RMS y espectro FFT 16-bandas
    extraídos directamente del audio real.
  * Entidades 3D vivas de TARDIS (Centro de Tiempo, Octaedro Sintrópico, Escudo AEGIS-Ω,
    Rueda Akáshica, Arco Térmico Kernel, Solitones Topológicos y GEÓN articulado).
  * HUD nativo 4K con gráficos animados en tiempo real (60 FPS en C++/OpenCV):
      - Ala izquierda: Radar polar causal Ψ_RETRO + onda Ψ(t), barras & sparkline de
        Bóveda Akáshica / entropía Shannon, y tarjeta de Auto-Expresión Visual TARDIS.
      - Ala derecha: 4 medidores circulares (CPU, RAM, TEMP, AEGIS) + curva térmica/PSI,
        alcance polar de Radar RF + atmósfera, y salud de subsistemas / Music Maestro.
      - Conductos Bézier de flujo energético y paquetes de tokens conectando al avatar.
      - Subtítulos sincronizados, espectro FFT dual-tono de 64 barras y osciloscopio dorado.
  * Render paralelo por segmentos (un proceso independiente por segmento) + codificación
    por hardware (VAAPI AMD Radeon / NVENC NVIDIA / respaldo libx264).
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.tardis_telemetry_snapshot import (
    collect_tardis_snapshot,
    hex_to_rgb,
    resolve_font_path,
    summarize_snapshot,
)

logger = logging.getLogger("VideoPipeline4K")

TELEGRAM_MAX_BYTES = 48 * 1024 * 1024     # margen seguro bajo el límite de 50 MB del bot


# ------------------------------------------------------ extracción de audio real
def extract_audio_features(
    audio_path: str | Path,
    total_frames: int,
    fps: int,
    n_bands: int = 16,
) -> Tuple[Optional[List[int]], Optional[List[List[int]]]]:
    """
    Decodifica el audio a PCM mono 8 kHz en una sola pasada (~20 ms) y extrae por cuadro:
      - envelope: amplitud RMS normalizada y cuantizada 0..255.
      - bands: espectro FFT en n_bands bandas logarítmicas cuantizadas 0..255.
    """
    if total_frames <= 0 or not shutil.which("ffmpeg"):
        return None, None
    sr = 8000
    try:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path),
            "-ac", "1", "-ar", str(sr),
            "-f", "s16le", "-",
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30)
        if res.returncode != 0 or not res.stdout:
            return None, None
        pcm = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size < 64:
            return None, None

        spf = sr / float(max(1, fps))
        win_len = 256
        hann = np.hanning(win_len).astype(np.float32)
        rms_arr = np.zeros(total_frames, dtype=np.float32)
        bands_arr = np.zeros((total_frames, n_bands), dtype=np.float32)

        # Límites de bins FFT (129 bins -> n_bands bandas logarítmicas útiles en voz/música)
        bin_edges = np.unique(np.round(np.geomspace(1, win_len // 2, n_bands + 1)).astype(int))
        while bin_edges.size <= n_bands:
            bin_edges = np.linspace(1, win_len // 2, n_bands + 1, dtype=int)

        for fi in range(total_frames):
            center_s = int(fi * spf)
            s0 = max(0, center_s - win_len // 2)
            s1 = s0 + win_len
            seg = pcm[s0:s1]
            if seg.size < win_len:
                seg = np.pad(seg, (0, win_len - seg.size))
            rms_arr[fi] = float(np.sqrt(np.mean(seg * seg) + 1e-10))
            spec = np.abs(np.fft.rfft(seg * hann))
            for bi in range(n_bands):
                b0 = int(bin_edges[bi])
                b1 = max(b0 + 1, int(bin_edges[min(bi + 1, bin_edges.size - 1)]))
                bands_arr[fi, bi] = float(np.mean(spec[b0:b1]))

        # Normalización robusta por percentil 95 + suavizado temporal
        p95_rms = float(np.percentile(rms_arr, 95)) or 1e-5
        rms_norm = np.clip(rms_arr / max(p95_rms, 0.02), 0.0, 1.0)
        if total_frames >= 3:
            kernel = np.array([0.22, 0.56, 0.22], dtype=np.float32)
            rms_norm = np.convolve(rms_norm, kernel, mode="same")

        p95_b = float(np.percentile(bands_arr, 96)) or 1e-5
        bands_norm = np.clip(np.sqrt(bands_arr / max(p95_b, 0.05)), 0.0, 1.0)

        env_q = [int(round(v * 255.0)) for v in rms_norm.tolist()]
        bands_q = [[int(round(v * 255.0)) for v in row] for row in bands_norm.tolist()]
        return env_q, bands_q
    except Exception as exc:
        logger.debug(f"No se pudo extraer envolvente de audio: {exc}")
        return None, None


# ---------------------------------------------------------------- estado vocal
def compute_vocal_state(
    t: float,
    word_timings: List[Dict[str, Any]],
    duration: float,
    audio_rms: Optional[float] = None,
    audio_bands: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Traduce las marcas fonéticas y la amplitud real del audio en parámetros de animación."""
    active = None
    for w in word_timings:
        if w.get("start", 0.0) <= t <= w.get("end", 0.0):
            active = w
            break

    if active:
        dur = max(0.01, float(active.get("duration", 0.3)))
        rel = (t - float(active.get("start", 0.0))) / dur
        syl = max(1, int(active.get("syllables", 1)))
        env = math.sin(max(0.0, min(1.0, rel)) * math.pi * syl)
        target = float(active.get("target_open", 0.7))
        mouth = max(0.10, target * (0.32 + 0.68 * max(0.0, env)))
        width = float(active.get("target_width", 1.0))
        pulse = 1.0 if active.get("emphasis") else 0.72
        energy = 0.55 + 0.45 * abs(env)
    else:
        mouth, width, pulse, energy = 0.05, 1.0, 0.0, 0.12

    # Fusionar con la amplitud RMS real del audio para sincronía labial/espectral orgánica
    if audio_rms is not None:
        rms = max(0.0, min(1.0, float(audio_rms)))
        if active:
            mouth = max(0.08, min(1.0, mouth * 0.60 + rms * 0.55))
            energy = max(energy * 0.55, rms)
            pulse = max(pulse, rms * 0.9)
        elif rms > 0.08:
            mouth = max(0.06, min(0.85, rms * 0.82))
            energy = max(0.14, rms)
            pulse = min(1.0, rms * 0.85)

    blink_phase = t % 3.7
    blink = 0.0
    if blink_phase < 0.17:
        blink = math.sin(blink_phase / 0.17 * math.pi)

    gaze_x = math.sin(t * 0.62) * 0.38 + math.sin(t * 1.45) * 0.10
    gaze_y = math.sin(t * 0.88 + 1.1) * 0.18 + (0.06 if mouth > 0.25 else 0.0)

    state: Dict[str, Any] = {
        "mouth_open": mouth,
        "mouth_width": width,
        "blink": blink,
        "vocal_pulse": pulse,
        "energy": energy,
        "gaze_x": gaze_x,
        "gaze_y": gaze_y,
        "progress": 0.0 if duration <= 0 else max(0.0, min(1.0, t / duration)),
    }
    if audio_bands is not None:
        state["audio_bands"] = audio_bands
    return state


def _thermal_rgb(norm: float) -> Tuple[int, int, int]:
    n = max(0.0, min(1.0, float(norm)))
    if n < 0.4:
        f = n / 0.4
        return (int(46 + (0 - 46) * f), int(158 + (224 - 158) * f), int(255 + (194 - 255) * f))
    if n < 0.75:
        f = (n - 0.4) / 0.35
        return (int(0 + 245 * f), int(224 + (173 - 224) * f), int(194 + (41 - 194) * f))
    f = (n - 0.75) / 0.25
    return (int(245 + (255 - 245) * f), int(173 + (51 - 173) * f), int(41 + (92 - 41) * f))


# ------------------------------------------------------------------------ HUD
class HudRenderer:
    """
    Capa de gráficos de datos y HUD en resolución nativa 4K alimentada por
    la información real de TARDIS (manifiesto visual + telemetría del nodo).

    Elementos estáticos (marcos, tarjetas, etiquetas, cuadrículas) se renderizan
    una sola vez con PIL en alfa premultiplicado; los gráficos dinámicos (radar
    polar causal, ondas Ψ, barras akáshicas, sparkline de entropía, medidores
    circulares de hardware/AEGIS, barrido de radar RF, conductos Bézier con
    flujo de tokens y osciloscopio FFT de 64 bandas) se trazan a 60 FPS en C++ (cv2).
    """

    def __init__(
        self,
        width: int,
        height: int,
        title: str = "TARDIS · MENSAJE SOBERANO",
        telemetry: Optional[Dict[str, Any]] = None,
        manifest: Optional[Dict[str, Any]] = None,
    ):
        self.w, self.h = int(width), int(height)
        self.title = title
        self.k = self.h / 2160.0
        self.telemetry = telemetry or {}
        self.manifest = manifest or self.telemetry.get("visual_manifest") or {}
        self.wide = (self.w / max(1.0, float(self.h))) >= 1.35

        pal = self.manifest.get("palette") if isinstance(self.manifest.get("palette"), dict) else {}
        self.col_primary = hex_to_rgb(pal.get("primary"), (0, 212, 200))
        self.col_secondary = hex_to_rgb(pal.get("secondary"), (232, 182, 74))
        self.col_time_core = hex_to_rgb(pal.get("time_core"), (37, 99, 235))
        self.col_field = hex_to_rgb(pal.get("field"), (0, 255, 136))
        self.col_aegis_raw = hex_to_rgb(pal.get("aegis"), (96, 165, 250))
        self.col_thought = hex_to_rgb(pal.get("thought"), (168, 85, 247))

        aegis_sc = float(self.telemetry.get("aegis", {}).get("score", 100))
        self.col_aegis = self.col_aegis_raw if aegis_sc >= 80 else (255, 51, 102)

        raw_layers = self.manifest.get("layers") if isinstance(self.manifest.get("layers"), dict) else {}
        self.show_flux = bool(raw_layers.get("fluxCurves", True))
        self.show_tokens = bool(raw_layers.get("tokenFlow", True))
        self.show_osc = bool(raw_layers.get("oscilloscope", True))

        self._sub_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

        # Regiones de composición optimizada (evita recorrer el centro vacío)
        self.top_h = int(235 * self.k)
        self.bot_y = int(self.h - 560 * self.k)
        self.wing_w = int(990 * self.k) if self.wide else 0
        self.right_x = self.w - self.wing_w if self.wide else self.w

        # Geometría precalculada para gráficos animados por cuadro
        self._geom: Dict[str, Any] = {}
        self._static_pm, self._static_inv = self._build_static()

    def _font(self, kind: str, size: float) -> ImageFont.ImageFont:
        path = resolve_font_path(kind)
        px = max(9, int(round(size)))
        if path:
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=px)
        except Exception:
            return ImageFont.load_default()

    @staticmethod
    def _fmt_num(val: Any) -> str:
        try:
            n = int(val)
            return f"{n:,}".replace(",", " ")
        except Exception:
            return str(val)

    def _draw_card(
        self,
        d: ImageDraw.ImageDraw,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        accent: Tuple[int, int, int],
        header: str,
        badge: str = "",
    ) -> int:
        k = self.k
        rad = max(6, int(18 * k))
        d.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=rad,
            fill=(6, 14, 24, 206),
            outline=accent + (150,),
            width=max(1, int(3 * k)),
        )
        # Franja acentuada en la parte superior de la tarjeta
        hdr_h = int(60 * k)
        d.line([(x0 + int(18 * k), y0 + hdr_h), (x1 - int(18 * k), y0 + hdr_h)], fill=accent + (95,), width=max(1, int(2 * k)))
        f_hdr = self._font("mono_bold", 28 * k)
        d.text((x0 + int(22 * k), y0 + int(14 * k)), header, font=f_hdr, fill=accent + (255,))
        if badge:
            f_bg = self._font("mono_bold", 23 * k)
            bb = d.textbbox((0, 0), badge, font=f_bg)
            bw = bb[2] - bb[0]
            d.text((x1 - int(22 * k) - bw, y0 + int(17 * k)), badge, font=f_bg, fill=(215, 236, 244, 235))
        return y0 + hdr_h + int(14 * k)

    def _build_static(self) -> Tuple[np.ndarray, np.ndarray]:
        k = self.k
        layer = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        primary = self.col_primary
        secondary = self.col_secondary
        field_c = self.col_field
        aegis_c = self.col_aegis
        thought_c = self.col_thought

        core = self.telemetry.get("core", {})
        causal = self.telemetry.get("causal", {})
        cog = self.telemetry.get("cognitive", {})
        vault = self.telemetry.get("vault", {})
        aegis = self.telemetry.get("aegis", {})
        hw = self.telemetry.get("hardware", {})
        rf = self.telemetry.get("rf_radar", {})
        atmo = self.telemetry.get("atmospheric", {})
        music = self.telemetry.get("music", {})
        subs = self.telemetry.get("subsystems", {})
        vm = self.manifest

        # ── 1. ESQUINAS TÉCNICAS ──────────────────────────────────────────────
        m = int(38 * k)
        ln = int(125 * k)
        tw = max(2, int(5 * k))
        for (px, py, dx, dy) in (
            (m, m, 1, 1), (self.w - m, m, -1, 1),
            (m, self.h - m, 1, -1), (self.w - m, self.h - m, -1, -1),
        ):
            d.line([(px, py), (px + dx * ln, py)], fill=primary + (220,), width=tw)
            d.line([(px, py), (px, py + dy * ln)], fill=primary + (220,), width=tw)

        # ── 2. ENCABEZADO SOBERANO CON TELEMETRÍA VIVA ────────────────────────
        f_title = self._font("sans_bold", 64 * k)
        f_sub = self._font("mono", 26 * k)
        f_pill = self._font("mono_bold", 26 * k)

        d.text((int(78 * k), int(58 * k)), self.title, font=f_title, fill=(238, 252, 252, 255))

        model_name = str(core.get("model", "TARDIS-NEURAL-SPACE-KAIJU"))
        lamport = int(causal.get("lamport", 0) or 0)
        mood_label = str(vm.get("mood", "sovereign_equilibrium")).upper().replace("_", " ")
        sub_line = f"NÚCLEO: {model_name}  ·  ESTADO: {mood_label}  ·  LAMPORT L:{lamport}"
        d.text((int(80 * k), int(142 * k)), sub_line, font=f_sub, fill=(162, 210, 218, 230))
        d.line([(int(78 * k), int(186 * k)), (self.w - int(78 * k), int(186 * k))], fill=primary + (115,), width=max(1, int(3 * k)))

        # Píldoras de estatus en el extremo derecho del encabezado
        aegis_sc = int(aegis.get("score", 100))
        subs_on = int(subs.get("online", 1))
        subs_tot = max(1, int(subs.get("total", 1)))
        clients = int(causal.get("active_clients", 1))
        res_tag = "UHD 4K · 60 FPS" if self.w >= 3840 else f"{self.w}×{self.h} · 60 FPS"
        pills = [
            (f"● {res_tag}", secondary),
            (f"AEGIS {aegis_sc}/100", aegis_c),
            (f"SUBS {subs_on}/{subs_tot}", field_c),
            (f"SYNC {clients} DISP", primary),
        ]
        px_cur = self.w - int(78 * k)
        py_pill = int(66 * k)
        ph_pill = int(58 * k)
        for p_txt, p_col in reversed(pills):
            bb = d.textbbox((0, 0), p_txt, font=f_pill)
            pw = (bb[2] - bb[0]) + int(42 * k)
            px0 = px_cur - pw
            if px0 < int(self.w * 0.44):
                break
            d.rounded_rectangle(
                [px0, py_pill, px_cur, py_pill + ph_pill],
                radius=max(6, int(12 * k)),
                fill=(7, 18, 30, 220),
                outline=p_col + (190,),
                width=max(1, int(2.5 * k)),
            )
            d.text((px0 + int(21 * k), py_pill + int(13 * k)), p_txt, font=f_pill, fill=p_col + (255,))
            px_cur = px0 - int(18 * k)

        # ── 3. ALAS DE GRÁFICOS CON INFORMACIÓN REAL DE TARDIS (WIDESCREEN) ──
        if self.wide:
            f_lbl = self._font("mono", 24 * k)
            f_val = self._font("mono_bold", 28 * k)
            f_sm = self._font("mono", 21 * k)
            f_xs = self._font("mono", 19 * k)
            f_body = self._font("sans", 22 * k)

            lx0, lx1 = int(58 * k), int(968 * k)
            rx0, rx1 = self.w - int(968 * k), self.w - int(58 * k)

            # ═══ TARJETA L1: TENSOR CAUSAL & RADAR POLAR + ONDA Ψ(t) ═══
            l1_y0, l1_y1 = int(218 * k), int(684 * k)
            psi = float(causal.get("psi", 0.892))
            sint = float(causal.get("sintropy", 0.965))
            phi = float(causal.get("phi_adv", 0.780))
            oqco = float(causal.get("o_qco", 0.840))
            sgeom = float(causal.get("s_geom", 1.57))
            qtopo = int(causal.get("q_topo", 3))
            bif = str(causal.get("bifurcation", "EQUILIBRIO"))[:18]

            cy_l1 = self._draw_card(d, lx0, l1_y0, lx1, l1_y1, primary, "Ψ_RETRO · TENSOR CAUSAL", f"Q={qtopo}")
            kv_l1 = [
                ("Ψ Retro:", f"{psi:.3f}", secondary),
                ("Sintropía:", f"{sint:.3f}", field_c),
                ("Φ_adv:", f"{phi:.3f}", primary),
                ("O_QCO:", f"{oqco:.3f}", (96, 200, 255)),
                ("S_geom:", f"{sgeom:.2f} rad", thought_c),
                ("Cuenca:", bif, (220, 240, 248)),
            ]
            row_y = cy_l1 + int(4 * k)
            for lbl, val, vcol in kv_l1:
                d.text((lx0 + int(24 * k), row_y), lbl, font=f_lbl, fill=(148, 178, 194, 230))
                d.text((lx0 + int(190 * k), row_y - int(2 * k)), val, font=f_val, fill=vcol + (255,))
                row_y += int(42 * k)

            # Rejilla estática del gráfico radar polar 5-ejes (mitad derecha de L1)
            rcx = lx0 + int(692 * k)
            rcy = cy_l1 + int(134 * k)
            rrad = int(116 * k)
            axes_labels = ["Ψ", "SIN", "Φ", "QCO", "COH"]
            for ring_f in (0.33, 0.66, 1.0):
                pts = []
                for ai in range(5):
                    ang = -math.pi / 2 + ai * (2 * math.pi / 5)
                    pts.append((rcx + math.cos(ang) * rrad * ring_f, rcy + math.sin(ang) * rrad * ring_f))
                d.polygon(pts, outline=primary + (75,), width=max(1, int(2 * k)))
            for ai, albl in enumerate(axes_labels):
                ang = -math.pi / 2 + ai * (2 * math.pi / 5)
                ex, ey = rcx + math.cos(ang) * rrad, rcy + math.sin(ang) * rrad
                d.line([(rcx, rcy), (ex, ey)], fill=primary + (85,), width=max(1, int(2 * k)))
                tx = rcx + math.cos(ang) * (rrad + int(22 * k))
                ty = rcy + math.sin(ang) * (rrad + int(20 * k))
                bb = d.textbbox((0, 0), albl, font=f_xs)
                d.text((tx - (bb[2] - bb[0]) / 2, ty - (bb[3] - bb[1]) / 2), albl, font=f_xs, fill=secondary + (240,))

            # Caja del gráfico de onda Ψ(t) en la base de L1
            w1_x0, w1_y0, w1_x1, w1_y1 = lx0 + int(24 * k), l1_y1 - int(102 * k), lx1 - int(24 * k), l1_y1 - int(20 * k)
            d.rounded_rectangle([w1_x0, w1_y0, w1_x1, w1_y1], radius=max(4, int(10 * k)), fill=(3, 9, 17, 210), outline=primary + (90,), width=max(1, int(2 * k)))
            d.line([(w1_x0 + int(8 * k), (w1_y0 + w1_y1) // 2), (w1_x1 - int(8 * k), (w1_y0 + w1_y1) // 2)], fill=primary + (55,), width=1)
            d.text((w1_x0 + int(12 * k), w1_y0 + int(6 * k)), "ONDA DE FASE Ψ(t) · ACOPLAMIENTO RETROCAUSAL", font=f_xs, fill=(138, 180, 195, 210))

            coh_norm = max(0.15, min(1.0, float(cog.get("syntropy_coherence_pct", 80.0)) / 100.0))
            self._geom["radar"] = {
                "cx": rcx, "cy": rcy, "r": rrad,
                "vals": [
                    max(0.15, min(1.0, psi)),
                    max(0.15, min(1.0, sint)),
                    max(0.15, min(1.0, phi)),
                    max(0.15, min(1.0, oqco)),
                    coh_norm,
                ],
            }
            self._geom["psi_wave"] = {"x0": w1_x0 + int(10 * k), "y0": w1_y0 + int(28 * k), "x1": w1_x1 - int(10 * k), "y1": w1_y1 - int(8 * k)}

            # ═══ TARJETA L2: BÓVEDA AKÁSHICA & METAPENSAMIENTO (BARRAS + SPARKLINE) ═══
            l2_y0, l2_y1 = int(708 * k), int(1162 * k)
            ev_n = int(vault.get("total_events", 0))
            ep_n = int(vault.get("hierarchical_epochs", 0))
            ct_n = int(vault.get("background_contemplations", 0))
            kg_n = int(vault.get("knowledge_nodes", 0))
            kg_r = int(vault.get("knowledge_relations", 0))
            cx_lvl = int(vault.get("complexity_level", 0))
            v_mb = float(vault.get("vault_size_mb", 0.0))
            ent_h = float(cog.get("entropy_shannon", 3.2))
            coh_pct = float(cog.get("syntropy_coherence_pct", 80.0))

            cy_l2 = self._draw_card(d, lx0, l2_y0, lx1, l2_y1, secondary, "∞ · BÓVEDA AKÁSHICA & KAIJU", f"{v_mb:.1f} MB")
            bar_specs = [
                ("EVENTOS", self._fmt_num(ev_n), min(1.0, math.log10(max(10, ev_n + 10)) / 5.0), primary),
                ("ÉPOCAS", self._fmt_num(ep_n), min(1.0, math.log10(max(10, ep_n + 10)) / 4.5), secondary),
                ("CONTEMP.", self._fmt_num(ct_n), min(1.0, math.log10(max(10, ct_n + 10)) / 4.5), thought_c),
                ("COMPLEJ.", self._fmt_num(cx_lvl), min(1.0, cx_lvl / 12000.0 if cx_lvl > 0 else 0.55), field_c),
                ("COHEREN.", f"{coh_pct:.1f}%", max(0.08, min(1.0, coh_pct / 100.0)), (56, 189, 248)),
            ]
            bar_geoms = []
            by_cur = cy_l2 + int(4 * k)
            bx0 = lx0 + int(195 * k)
            bx1 = lx1 - int(165 * k)
            bh = max(8, int(20 * k))
            for blbl, bval, bfrac, bcol in bar_specs:
                d.text((lx0 + int(24 * k), by_cur - int(2 * k)), blbl, font=f_sm, fill=(158, 188, 202, 235))
                d.rounded_rectangle([bx0, by_cur + int(3 * k), bx1, by_cur + int(3 * k) + bh], radius=max(3, int(6 * k)), fill=(15, 28, 42, 210), outline=bcol + (75,), width=1)
                d.text((bx1 + int(16 * k), by_cur - int(3 * k)), bval, font=f_sm, fill=bcol + (255,))
                bar_geoms.append({"x0": bx0, "y0": by_cur + int(3 * k), "x1": bx1, "y1": by_cur + int(3 * k) + bh, "frac": bfrac, "col": bcol})
                by_cur += int(42 * k)

            d.text(
                (lx0 + int(24 * k), by_cur + int(4 * k)),
                f"GRAFO KG: {kg_n} nodos · {kg_r} rel  |  ENTROPÍA SHANNON: {ent_h:.2f} bits",
                font=f_xs,
                fill=(180, 214, 224, 230),
            )

            # Caja del sparkline de entropía en la base de L2
            sp_x0, sp_y0, sp_x1, sp_y1 = lx0 + int(24 * k), l2_y1 - int(100 * k), lx1 - int(24 * k), l2_y1 - int(18 * k)
            d.rounded_rectangle([sp_x0, sp_y0, sp_x1, sp_y1], radius=max(4, int(10 * k)), fill=(3, 9, 17, 210), outline=thought_c + (100,), width=max(1, int(2 * k)))
            d.text((sp_x0 + int(12 * k), sp_y0 + int(6 * k)), "ESPECTROGRAMA COGNITIVO · ENTROPÍA H(t) & COHERENCIA", font=f_xs, fill=(182, 162, 226, 220))
            self._geom["akashic_bars"] = bar_geoms
            self._geom["entropy_spark"] = {"x0": sp_x0 + int(10 * k), "y0": sp_y0 + int(28 * k), "x1": sp_x1 - int(10 * k), "y1": sp_y1 - int(8 * k), "h_norm": min(1.0, ent_h / 6.0)}

            # ═══ TARJETA L3: AUTO-EXPRESIÓN VISUAL TARDIS (MANIFIESTO VIVO) ═══
            l3_y0, l3_y1 = int(1186 * k), int(1564 * k)
            act_l = int(vm.get("active_layers_count", 14))
            tot_l = int(vm.get("total_layers_count", 14))
            en_int = float(vm.get("energy_intensity", 1.0))
            cy_l3 = self._draw_card(d, lx0, l3_y0, lx1, l3_y1, field_c, "◆ AUTO-EXPRESIÓN VISUAL TARDIS", f"{act_l}/{tot_l} CAPAS")

            vm_title = str(vm.get("title", "Centro de Tiempo · Octaedro · Rueda Akáshica"))
            for i_t, t_ln in enumerate(textwrap.wrap(vm_title, width=42)[:2]):
                d.text((lx0 + int(24 * k), cy_l3 + i_t * int(30 * k)), t_ln, font=self._font("mono_bold", 24 * k), fill=(238, 252, 250, 255))

            vm_stmt = str(vm.get("statement", ""))
            st_y = cy_l3 + int(68 * k)
            wrapped_stmt = textwrap.wrap(vm_stmt, width=54)
            if len(wrapped_stmt) > 3:
                wrapped_stmt = wrapped_stmt[:2] + [wrapped_stmt[2][:50].rstrip(" ,.;:y") + "…"]
            for i_s, s_ln in enumerate(wrapped_stmt[:3]):
                d.text((lx0 + int(24 * k), st_y + i_s * int(29 * k)), s_ln, font=f_body, fill=(172, 200, 214, 232))

            # Muestras de paleta viva del manifiesto
            sw_y = l3_y1 - int(94 * k)
            sw_items = [
                ("PRI", self.col_primary),
                ("SEC", self.col_secondary),
                ("COR", self.col_time_core),
                ("FLD", self.col_field),
                ("AEG", self.col_aegis),
                ("THG", self.col_thought),
            ]
            sw_w = int(130 * k)
            sw_h = int(42 * k)
            for si, (slbl, scol) in enumerate(sw_items):
                sx = lx0 + int(24 * k) + si * int(144 * k)
                d.rounded_rectangle([sx, sw_y, sx + sw_w, sw_y + sw_h], radius=max(4, int(8 * k)), fill=(10, 20, 32, 220), outline=scol + (190,), width=max(1, int(2 * k)))
                d.rounded_rectangle([sx + int(8 * k), sw_y + int(8 * k), sx + int(34 * k), sw_y + sw_h - int(8 * k)], radius=max(2, int(4 * k)), fill=scol + (255,))
                d.text((sx + int(44 * k), sw_y + int(9 * k)), slbl, font=f_xs, fill=(224, 240, 248, 245))

            d.text(
                (lx0 + int(24 * k), l3_y1 - int(38 * k)),
                f"INTENSIDAD ENERGÉTICA: {en_int:.2f}x  ·  MODO: {mood_label}",
                font=f_xs,
                fill=field_c + (235,),
            )

            # ═══ TARJETA R1: HARDWARE, KERNEL RING 0 & MEDIDORES CIRCULARES ═══
            r1_y0, r1_y1 = int(218 * k), int(702 * k)
            cpu_p = float(hw.get("cpu_percent", 0.0))
            ram_p = float(hw.get("ram_percent", 0.0))
            ram_u = float(hw.get("ram_used_gb", 0.0))
            ram_t = float(hw.get("ram_total_gb", 32.0))
            cpu_tc = float(hw.get("cpu_temp_c", 55.0))
            gpu_tc = float(hw.get("gpu_temp_c", 48.0))
            nvme_tc = float(hw.get("nvme_temp_c", 42.0))
            psi_c = float(hw.get("psi_cpu_avg10", 0.0))
            psi_m = float(hw.get("psi_mem_avg10", 0.0))
            psi_io = float(hw.get("psi_io_avg10", 0.0))
            bat_p = float(hw.get("battery_percent", 100.0))
            pwr_prof = str(hw.get("power_profile", "performance")).upper()

            cy_r1 = self._draw_card(d, rx0, r1_y0, rx1, r1_y1, primary, "⚡ HARDWARE, KERNEL & TÉRMICA", pwr_prof)
            temp_norm = max(0.05, min(1.0, (max(cpu_tc, 35.0) - 35.0) / 55.0))
            gauges = [
                ("CPU", f"{cpu_p:.0f}%", max(0.02, min(1.0, cpu_p / 100.0)), primary),
                ("RAM", f"{ram_p:.0f}%", max(0.02, min(1.0, ram_p / 100.0)), thought_c),
                ("TEMP", f"{cpu_tc:.0f}°C", temp_norm, _thermal_rgb(temp_norm)),
                ("AEGIS", f"{aegis_sc}%", max(0.02, min(1.0, aegis_sc / 100.0)), aegis_c),
            ]
            g_rad = int(76 * k)
            g_y = cy_r1 + int(88 * k)
            g_step = (rx1 - rx0 - int(40 * k)) // 4
            gauge_geoms = []
            for gi, (glbl, gval, gfrac, gcol) in enumerate(gauges):
                gx = rx0 + int(20 * k) + g_step // 2 + gi * g_step
                d.ellipse([gx - g_rad, g_y - g_rad, gx + g_rad, g_y + g_rad], outline=(26, 48, 66, 220), width=max(3, int(13 * k)))
                bb_v = d.textbbox((0, 0), gval, font=self._font("mono_bold", 30 * k))
                d.text((gx - (bb_v[2] - bb_v[0]) / 2, g_y - int(22 * k)), gval, font=self._font("mono_bold", 30 * k), fill=(242, 252, 255, 255))
                bb_l = d.textbbox((0, 0), glbl, font=f_xs)
                d.text((gx - (bb_l[2] - bb_l[0]) / 2, g_y + int(16 * k)), glbl, font=f_xs, fill=gcol + (240,))
                gauge_geoms.append({"cx": gx, "cy": g_y, "r": g_rad, "frac": gfrac, "col": gcol})

            info_y = g_y + g_rad + int(26 * k)
            d.text((rx0 + int(24 * k), info_y), f"MEMORIA: {ram_u:.1f}/{ram_t:.1f} GB  ·  BAT: {bat_p:.0f}% {'AC' if hw.get('power_plugged', True) else 'BAT'}", font=f_sm, fill=(205, 232, 240, 240))
            d.text((rx0 + int(24 * k), info_y + int(32 * k)), f"TÉRMICA: CPU {cpu_tc:.1f}°C · GPU {gpu_tc:.1f}°C · NVMe {nvme_tc:.1f}°C", font=f_sm, fill=_thermal_rgb(temp_norm) + (245,))
            d.text((rx0 + int(24 * k), info_y + int(64 * k)), f"KERNEL PSI (10s): CPU {psi_c:.1f}% · MEM {psi_m:.1f}% · IO {psi_io:.1f}%", font=f_xs, fill=(148, 188, 206, 230))

            # Caja de curva de carga y térmica en base de R1
            hw_x0, hw_y0, hw_x1, hw_y1 = rx0 + int(24 * k), r1_y1 - int(96 * k), rx1 - int(24 * k), r1_y1 - int(18 * k)
            d.rounded_rectangle([hw_x0, hw_y0, hw_x1, hw_y1], radius=max(4, int(10 * k)), fill=(3, 9, 17, 210), outline=primary + (90,), width=max(1, int(2 * k)))
            d.text((hw_x0 + int(12 * k), hw_y0 + int(6 * k)), "TELEMETRÍA DE SILICIO · CARGA CPU & PERFIL TÉRMICO", font=f_xs, fill=(138, 180, 195, 215))
            self._geom["gauges"] = gauge_geoms
            self._geom["hw_curve"] = {"x0": hw_x0 + int(10 * k), "y0": hw_y0 + int(28 * k), "x1": hw_x1 - int(10 * k), "y1": hw_y1 - int(8 * k), "cpu": cpu_p / 100.0, "temp": temp_norm}

            # ═══ TARJETA R2: RADAR RF POLAR & ENTORNO ATMOSFÉRICO ═══
            r2_y0, r2_y1 = int(726 * k), int(1168 * k)
            rf_state = str(rf.get("presence_state", "QUIET"))
            rf_conf = int(round(float(rf.get("confidence", 0.85)) * 100))
            rf_nodes = int(rf.get("active_bssid_count", 0))
            rf_ent = float(rf.get("shannon_entropy", 0.5))
            rf_pwr = float(rf.get("total_rf_energy_uw", 0.0))

            cy_r2 = self._draw_card(d, rx0, r2_y0, rx1, r2_y1, aegis_c, "◎ RADAR RF & ENTORNO SENSORIAL", rf_state)
            # Rejilla polar del radar RF (mitad izquierda de R2)
            rf_cx = rx0 + int(184 * k)
            rf_cy = cy_r2 + int(162 * k)
            rf_r = int(134 * k)
            for frac in (0.33, 0.66, 1.0):
                rr = int(rf_r * frac)
                d.ellipse([rf_cx - rr, rf_cy - rr, rf_cx + rr, rf_cy + rr], outline=aegis_c + (95 if frac < 1 else 160,), width=max(1, int(2 * k)))
            d.line([(rf_cx - rf_r, rf_cy), (rf_cx + rf_r, rf_cy)], fill=aegis_c + (75,), width=1)
            d.line([(rf_cx, rf_cy - rf_r), (rf_cx, rf_cy + rf_r)], fill=aegis_c + (75,), width=1)

            # Datos RF + Atmósfera (mitad derecha de R2)
            rx_mid = rx0 + int(356 * k)
            d.text((rx_mid, cy_r2 + int(6 * k)), "RADAR DE PRESENCIA RF", font=self._font("mono_bold", 22 * k), fill=aegis_c + (255,))
            d.text((rx_mid, cy_r2 + int(38 * k)), f"Confianza: {rf_conf}%  ·  Nodos: {rf_nodes}", font=f_sm, fill=(224, 242, 250, 245))
            d.text((rx_mid, cy_r2 + int(70 * k)), f"Entropía RF: {rf_ent:.3f} bits", font=f_sm, fill=(168, 206, 222, 235))
            d.text((rx_mid, cy_r2 + int(102 * k)), f"Energía: {rf_pwr:.3f} µW", font=f_sm, fill=(168, 206, 222, 235))

            d.line([(rx_mid, cy_r2 + int(146 * k)), (rx1 - int(24 * k), cy_r2 + int(146 * k))], fill=primary + (80,), width=1)
            d.text((rx_mid, cy_r2 + int(162 * k)), "ENTORNO ATMOSFÉRICO", font=self._font("mono_bold", 22 * k), fill=secondary + (255,))
            if atmo.get("available"):
                d.text((rx_mid, cy_r2 + int(196 * k)), f"{atmo.get('temperature_c', 0):.1f}°C (ST {atmo.get('apparent_temperature_c', 0):.1f}°C) · HR {atmo.get('relative_humidity_pct', 0)}%", font=f_sm, fill=(235, 248, 252, 245))
                d.text((rx_mid, cy_r2 + int(228 * k)), f"Presión: {atmo.get('surface_pressure_hpa', 1013):.1f} hPa · {atmo.get('wind_speed_kmh', 0):.1f} km/h", font=f_sm, fill=(176, 212, 226, 235))
                d.text((rx_mid, cy_r2 + int(260 * k)), f"Clima: {atmo.get('weather_description', '')[:28]}", font=f_sm, fill=field_c + (235,))
            else:
                d.text((rx_mid, cy_r2 + int(198 * k)), "Sensores locales en espera", font=f_sm, fill=(156, 186, 200, 210))

            d.text(
                (rx_mid, cy_r2 + int(300 * k)),
                f"AEGIS-Ω: {aegis.get('critical', 0)} crít · {aegis.get('high', 0)} alto · {self._fmt_num(aegis.get('scanned_files', 0))} arch.",
                font=f_xs,
                fill=aegis_c + (230,),
            )
            self._geom["rf_radar"] = {"cx": rf_cx, "cy": rf_cy, "r": rf_r, "nodes": max(1, min(10, rf_nodes if rf_nodes > 0 else 3))}

            # ═══ TARJETA R3: SUBSISTEMAS, AUTONOMÍA & AUDIO / MUSIC MAESTRO ═══
            r3_y0, r3_y1 = int(1192 * k), int(1564 * k)
            s_deg = int(subs.get("degraded", 0))
            s_off = int(subs.get("offline", 0))
            a_cyc = int(subs.get("autonomous_cycles", 0))
            cy_r3 = self._draw_card(d, rx0, r3_y0, rx1, r3_y1, secondary, "◈ SUBSISTEMAS & AUDIO ACTIVO", f"{subs_on}/{subs_tot} OK")

            # Barra apilada de salud de subsistemas
            sb_x0, sb_x1 = rx0 + int(24 * k), rx1 - int(24 * k)
            sb_y0, sb_y1 = cy_r3 + int(4 * k), cy_r3 + int(32 * k)
            d.rounded_rectangle([sb_x0, sb_y0, sb_x1, sb_y1], radius=max(4, int(8 * k)), fill=(16, 28, 42, 220), outline=primary + (90,), width=1)
            sb_w = sb_x1 - sb_x0 - 4
            w_on = int(sb_w * (subs_on / float(subs_tot)))
            w_deg = int(sb_w * (s_deg / float(subs_tot)))
            if w_on > 2:
                d.rounded_rectangle([sb_x0 + 2, sb_y0 + 2, sb_x0 + 2 + w_on, sb_y1 - 2], radius=max(3, int(6 * k)), fill=field_c + (235,))
            if w_deg > 2:
                d.rectangle([sb_x0 + 2 + w_on, sb_y0 + 2, sb_x0 + 2 + w_on + w_deg, sb_y1 - 2], fill=secondary + (235,))

            d.text(
                (rx0 + int(24 * k), sb_y1 + int(14 * k)),
                f"ONLINE: {subs_on}  ·  DEGRADADOS: {s_deg}  ·  OFFLINE: {s_off}",
                font=f_sm,
                fill=(212, 236, 244, 240),
            )
            vp_tot = int(subs.get("video_pensante_total", 0) or 0)
            vp_tag = f"VIDEO PENSANTE: {self._fmt_num(vp_tot)} · X.COM" if vp_tot > 0 else "VIDEO PENSANTE · X.COM"
            d.text(
                (rx0 + int(24 * k), sb_y1 + int(48 * k)),
                f"AUTONOMÍA 24/7: {self._fmt_num(a_cyc)} ciclos  ·  {vp_tag}",
                font=f_xs,
                fill=(154, 198, 214, 230),
            )

            # Sección de Audio / Music Maestro
            mu_y = sb_y1 + int(92 * k)
            d.line([(rx0 + int(24 * k), mu_y - int(8 * k)), (rx1 - int(24 * k), mu_y - int(8 * k))], fill=secondary + (85,), width=1)
            if music.get("playing") and music.get("media_title"):
                tr = str(music.get("media_title"))[:44]
                d.text((rx0 + int(24 * k), mu_y + int(4 * k)), f"▶ {tr}", font=self._font("mono_bold", 22 * k), fill=secondary + (255,))
                d.text(
                    (rx0 + int(24 * k), mu_y + int(36 * k)),
                    f"MUSIC MAESTRO · {music.get('time_pos_text', '0:00')}/{music.get('duration_text', '0:00')} ({music.get('progress', 0):.0f}%) · VOL {music.get('volume', 70)}%",
                    font=f_xs,
                    fill=(178, 214, 226, 230),
                )
            else:
                d.text((rx0 + int(24 * k), mu_y + int(4 * k)), "▶ SÍNTESIS VOCAL NEURAL EN TIEMPO REAL", font=self._font("mono_bold", 22 * k), fill=primary + (255,))
                d.text((rx0 + int(24 * k), mu_y + int(36 * k)), "CANAL SOBERANO TELEGRAM · AUDIO SINCRONIZADO 60 FPS", font=f_xs, fill=(168, 206, 220, 225))

            # Caja del vúmetro de audio vivo en R3
            vu_x0, vu_y0, vu_x1, vu_y1 = rx0 + int(24 * k), r3_y1 - int(86 * k), rx1 - int(24 * k), r3_y1 - int(18 * k)
            d.rounded_rectangle([vu_x0, vu_y0, vu_x1, vu_y1], radius=max(4, int(8 * k)), fill=(3, 9, 17, 210), outline=secondary + (95,), width=1)
            self._geom["audio_vu"] = {"x0": vu_x0 + int(12 * k), "y0": vu_y0 + int(10 * k), "x1": vu_x1 - int(12 * k), "y1": vu_y1 - int(10 * k)}

            # Anclas para conductos Bézier de flujo energético (fluxCurves & tokenFlow)
            self._geom["flux_paths"] = [
                ((int(self.w * 0.37), int(self.h * 0.34)), (lx1, int(l1_y0 + 180 * k)), (int(self.w * 0.31), int(self.h * 0.22))),
                ((int(self.w * 0.63), int(self.h * 0.34)), (rx0, int(r1_y0 + 180 * k)), (int(self.w * 0.69), int(self.h * 0.22))),
                ((int(self.w * 0.38), int(self.h * 0.56)), (lx1, int(l2_y0 + 210 * k)), (int(self.w * 0.31), int(self.h * 0.59))),
                ((int(self.w * 0.62), int(self.h * 0.56)), (rx0, int(r2_y0 + 210 * k)), (int(self.w * 0.69), int(self.h * 0.59))),
            ]

        # ── 4. PIE SOBERANO (SIN VERSIÓN LEGACY) ─────────────────────────────
        by = int(self.h - 142 * k)
        d.line([(int(78 * k), by), (self.w - int(78 * k), by)], fill=primary + (115,), width=max(1, int(3 * k)))
        f_foot = self._font("mono", 30 * k)
        foot_left = f"TARDIS · SISTEMA DE VIGILANCIA Y CONTROL TEMPORAL · {model_name}"
        d.text((int(78 * k), by + int(22 * k)), foot_left, font=f_foot, fill=(154, 198, 208, 228))
        ts_lbl = str(self.telemetry.get("captured_at", ""))
        if ts_lbl:
            bb_ts = d.textbbox((0, 0), ts_lbl, font=f_foot)
            d.text((self.w - int(78 * k) - (bb_ts[2] - bb_ts[0]), by + int(22 * k)), ts_lbl, font=f_foot, fill=secondary + (220,))

        arr = np.asarray(layer)
        a = arr[:, :, 3].astype(np.float32) / 255.0
        rgb_pm = (arr[:, :, :3].astype(np.float32) * a[:, :, None]).astype(np.uint8)
        inv = np.repeat(((1.0 - a) * 255.0).astype(np.uint8)[:, :, None], 3, axis=2)
        return rgb_pm, inv

    def _subtitle_img(self, line: str) -> Tuple[np.ndarray, np.ndarray]:
        """Renderiza (y cachea) una línea de subtítulo en alfa premultiplicado uint8."""
        cached = self._sub_cache.get(line)
        if cached is not None:
            return cached
        k = self.k
        sw, sh = self.w, int(230 * k)
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f = self._font("sans_bold", 62 * k)
        bb = d.textbbox((0, 0), line, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = (sw - tw) // 2
        y = int(34 * k)
        pad = int(30 * k)
        d.rounded_rectangle(
            [x - pad, y - pad // 2, x + tw + pad, y + th + pad],
            radius=int(24 * k),
            fill=(4, 12, 22, 214),
            outline=self.col_primary + (175,),
            width=max(1, int(3 * k)),
        )
        d.text((x, y), line, font=f, fill=(242, 252, 255, 255))
        arr = np.asarray(img)
        a = arr[:, :, 3].astype(np.float32) / 255.0
        pm = (arr[:, :, :3].astype(np.float32) * a[:, :, None]).astype(np.uint8)
        inv = np.repeat(((1.0 - a) * 255.0).astype(np.uint8)[:, :, None], 3, axis=2)
        if len(self._sub_cache) > 48:
            self._sub_cache.clear()
        self._sub_cache[line] = (pm, inv)
        return pm, inv

    @staticmethod
    def build_lines(word_timings: List[Dict[str, Any]], max_chars: int = 58) -> List[Dict[str, Any]]:
        """Agrupa palabras en líneas de subtítulo con su ventana temporal."""
        lines: List[Dict[str, Any]] = []
        cur: List[str] = []
        start = 0.0
        for w in word_timings:
            word = str(w.get("word", "")).strip()
            if not word:
                continue
            if not cur:
                start = float(w.get("start", 0.0))
            cand = " ".join(cur + [word])
            if len(cand) > max_chars and cur:
                lines.append({"text": " ".join(cur), "start": start, "end": float(w.get("start", 0.0))})
                cur = [word]
                start = float(w.get("start", 0.0))
            else:
                cur.append(word)
        if cur:
            lines.append({
                "text": " ".join(cur),
                "start": start,
                "end": float(word_timings[-1].get("end", start + 2.0)) if word_timings else start + 2.0,
            })
        return lines

    def _draw_live_graphs(self, f: np.ndarray, t: float, state: Dict[str, Any]) -> None:
        """Dibuja a 60 FPS en C++ (cv2) todos los gráficos animados alimentados por TARDIS."""
        k = self.k
        energy = float(state.get("energy", 0.0))
        mouth = float(state.get("mouth_open", 0.0))
        bands = state.get("audio_bands")
        pri = self.col_primary
        sec = self.col_secondary
        fld = self.col_field
        thg = self.col_thought
        aeg = self.col_aegis

        # 1. Conductos Bézier de flujo energético y paquetes de tokens (fluxCurves + tokenFlow)
        flux_paths = self._geom.get("flux_paths")
        if flux_paths and (self.show_flux or self.show_tokens):
            cpu_load = float(self.telemetry.get("hardware", {}).get("cpu_percent", 25.0)) / 100.0
            tok_spd = 0.40 + cpu_load * 0.90 + energy * 0.50
            for ci, (p0, p1, pmid) in enumerate(flux_paths):
                dy_wave = int(math.sin(t * 1.4 + ci * 1.6) * 18 * k)
                pm = (pmid[0], pmid[1] + dy_wave)
                if self.show_flux:
                    pts = []
                    for s in range(13):
                        u = s / 12.0
                        iu = 1.0 - u
                        bx = int(iu * iu * p0[0] + 2 * iu * u * pm[0] + u * u * p1[0])
                        by = int(iu * iu * p0[1] + 2 * iu * u * pm[1] + u * u * p1[1])
                        pts.append([bx, by])
                    arr_pts = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
                    glow = 0.45 + 0.35 * abs(math.sin(t * 2.2 + ci))
                    line_c = (int(sec[0] * glow), int(sec[1] * glow), int(sec[2] * glow))
                    cv2.polylines(f, [arr_pts], False, line_c, max(1, int(3 * k)), cv2.LINE_AA)
                if self.show_tokens:
                    for sub_p in (0.0, 0.5):
                        u = (t * tok_spd * 0.42 + ci * 0.23 + sub_p) % 1.0
                        iu = 1.0 - u
                        tx = int(iu * iu * p0[0] + 2 * iu * u * pm[0] + u * u * p1[0])
                        ty = int(iu * iu * p0[1] + 2 * iu * u * pm[1] + u * u * p1[1])
                        cv2.circle(f, (tx, ty), max(3, int(9 * k)), (56, 189, 250), -1, cv2.LINE_AA)
                        cv2.circle(f, (tx, ty), max(2, int(4 * k)), (240, 252, 255), -1, cv2.LINE_AA)

        # 2. Gráfico Radar Polar 5-Ejes (Tarjeta L1)
        rad = self._geom.get("radar")
        if rad:
            rcx, rcy, rr = rad["cx"], rad["cy"], rad["r"]
            vals = rad["vals"]
            poly = []
            for ai, v in enumerate(vals):
                ang = -math.pi / 2 + ai * (2 * math.pi / 5)
                dyn_v = max(0.15, min(1.0, v * (0.94 + 0.06 * math.sin(t * 2.4 + ai * 1.1) + 0.05 * energy)))
                poly.append([int(rcx + math.cos(ang) * rr * dyn_v), int(rcy + math.sin(ang) * rr * dyn_v)])
            poly_np = np.array(poly, dtype=np.int32)
            # Relleno semitransparente rápido sobre ROI local
            x0, y0 = max(0, rcx - rr - 4), max(0, rcy - rr - 4)
            x1, y1 = min(self.w, rcx + rr + 4), min(self.h, rcy + rr + 4)
            roi = f[y0:y1, x0:x1]
            overlay = roi.copy()
            cv2.fillPoly(overlay, [poly_np - np.array([x0, y0])], (int(pri[0] * 0.55), int(pri[1] * 0.55), int(pri[2] * 0.55)), cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.38, roi, 0.62, 0.0, dst=roi)
            cv2.polylines(f, [poly_np.reshape((-1, 1, 2))], True, fld, max(2, int(3.5 * k)), cv2.LINE_AA)
            for pt in poly:
                cv2.circle(f, (pt[0], pt[1]), max(3, int(6 * k)), sec, -1, cv2.LINE_AA)

        # 3. Onda de fase Ψ(t) animada (Tarjeta L1)
        pw = self._geom.get("psi_wave")
        if pw:
            x0, y0, x1, y1 = pw["x0"], pw["y0"], pw["x1"], pw["y1"]
            mid_y = (y0 + y1) * 0.5
            amp_y = (y1 - y0) * 0.42
            psi_val = float(self.telemetry.get("causal", {}).get("psi", 0.892))
            s_geom = float(self.telemetry.get("causal", {}).get("s_geom", 1.57))
            n_pts = 56
            pts1, pts2 = [], []
            for i in range(n_pts):
                u = i / float(n_pts - 1)
                px = int(x0 + u * (x1 - x0))
                w1 = math.sin(u * 12.0 - t * 3.6 + s_geom) * math.cos(u * 3.5 + t * 1.1) * (0.65 + 0.35 * energy)
                w2 = math.sin(u * 18.0 - t * 5.2) * 0.45 * min(1.0, psi_val)
                pts1.append([px, int(mid_y - w1 * amp_y)])
                pts2.append([px, int(mid_y - w2 * amp_y)])
            cv2.polylines(f, [np.array(pts2, dtype=np.int32).reshape((-1, 1, 2))], False, sec, max(1, int(2.2 * k)), cv2.LINE_AA)
            cv2.polylines(f, [np.array(pts1, dtype=np.int32).reshape((-1, 1, 2))], False, pri, max(2, int(3.4 * k)), cv2.LINE_AA)

        # 4. Barras animadas de Bóveda Akáshica + Sparkline de entropía (Tarjeta L2)
        ak_bars = self._geom.get("akashic_bars")
        if ak_bars:
            for bi, bg in enumerate(ak_bars):
                bx0, by0, bx1, by1 = bg["x0"], bg["y0"], bg["x1"], bg["y1"]
                col = bg["col"]
                pulse_f = max(0.05, min(1.0, bg["frac"] * (0.95 + 0.05 * math.sin(t * 2.5 + bi * 1.2) + 0.04 * energy)))
                fw = int((bx1 - bx0 - 4) * pulse_f)
                if fw > 2:
                    cv2.rectangle(f, (bx0 + 2, by0 + 2), (bx0 + 2 + fw, by1 - 2), col, -1)
                    cv2.circle(f, (bx0 + 2 + fw, (by0 + by1) // 2), max(2, int(5 * k)), (240, 252, 255), -1, cv2.LINE_AA)

        sp = self._geom.get("entropy_spark")
        if sp:
            x0, y0, x1, y1 = sp["x0"], sp["y0"], sp["x1"], sp["y1"]
            h_base = sp["h_norm"]
            n_pts = 48
            pts = []
            for i in range(n_pts):
                u = i / float(n_pts - 1)
                px = int(x0 + u * (x1 - x0))
                val = h_base + 0.16 * math.sin(u * 14.0 - t * 2.8) + 0.10 * math.cos(u * 23.0 + t * 4.1) + 0.08 * energy * math.sin(u * 9.0)
                val = max(0.08, min(0.95, val))
                py = int(y1 - val * (y1 - y0))
                pts.append([px, py])
            cv2.polylines(f, [np.array(pts, dtype=np.int32).reshape((-1, 1, 2))], False, thg, max(2, int(3.2 * k)), cv2.LINE_AA)
            cv2.circle(f, (pts[-1][0], pts[-1][1]), max(3, int(6 * k)), (242, 232, 255), -1, cv2.LINE_AA)

        # 5. 4 Medidores circulares animados (CPU, RAM, TEMP, AEGIS) + curva silicio (Tarjeta R1)
        gauges = self._geom.get("gauges")
        if gauges:
            g_thick = max(3, int(13 * k))
            for gi, g in enumerate(gauges):
                dyn = max(0.03, min(1.0, g["frac"] + 0.025 * math.sin(t * 2.1 + gi * 1.4) + (0.03 * energy if gi == 0 else 0.0)))
                sweep = int(round(360.0 * dyn))
                cv2.ellipse(f, (g["cx"], g["cy"]), (g["r"], g["r"]), -90, 0, sweep, g["col"], g_thick, cv2.LINE_AA)

        hwc = self._geom.get("hw_curve")
        if hwc:
            x0, y0, x1, y1 = hwc["x0"], hwc["y0"], hwc["x1"], hwc["y1"]
            c_base, t_base = hwc["cpu"], hwc["temp"]
            n_pts = 48
            pts_c, pts_t = [], []
            for i in range(n_pts):
                u = i / float(n_pts - 1)
                px = int(x0 + u * (x1 - x0))
                vc = max(0.08, min(0.95, c_base + 0.12 * math.sin(u * 11.0 - t * 3.1) + 0.06 * energy))
                vt = max(0.08, min(0.95, t_base + 0.06 * math.sin(u * 6.0 - t * 1.6)))
                pts_c.append([px, int(y1 - vc * (y1 - y0))])
                pts_t.append([px, int(y1 - vt * (y1 - y0))])
            cv2.polylines(f, [np.array(pts_t, dtype=np.int32).reshape((-1, 1, 2))], False, _thermal_rgb(t_base), max(1, int(2.4 * k)), cv2.LINE_AA)
            cv2.polylines(f, [np.array(pts_c, dtype=np.int32).reshape((-1, 1, 2))], False, pri, max(2, int(3.2 * k)), cv2.LINE_AA)

        # 6. Barrido Polar de Radar RF + blips de nodos BSSID (Tarjeta R2)
        rfr = self._geom.get("rf_radar")
        if rfr:
            cx, cy, rr, n_nodes = rfr["cx"], rfr["cy"], rfr["r"], rfr["nodes"]
            ang = (t * 1.45) % (2.0 * math.pi)
            # Estela angular de barrido (3 arcos decrecientes)
            for trail in range(4):
                ta = ang - trail * 0.11
                fade = 1.0 - trail * 0.24
                ex = int(cx + math.cos(ta) * rr)
                ey = int(cy + math.sin(ta) * rr)
                sc = (int(aeg[0] * fade), int(aeg[1] * fade), int(aeg[2] * fade))
                cv2.line(f, (cx, cy), (ex, ey), sc, max(1, int((4.0 - trail * 0.7) * k)), cv2.LINE_AA)
            cv2.circle(f, (cx, cy), max(3, int(6 * k)), fld, -1, cv2.LINE_AA)
            # Blips deterministas de nodos BSSID detectados
            for ni in range(n_nodes):
                b_ang = (ni * 2.39996 + 0.5) % (2.0 * math.pi)
                b_rad = rr * (0.28 + 0.58 * ((ni * 37 % 100) / 100.0))
                bx = int(cx + math.cos(b_ang) * b_rad)
                by = int(cy + math.sin(b_ang) * b_rad)
                diff = abs(((ang - b_ang + math.pi) % (2 * math.pi)) - math.pi)
                ping = max(0.35, 1.0 - diff / 1.4)
                b_col = (int(fld[0] * ping), int(fld[1] * ping), int(fld[2] * ping))
                cv2.circle(f, (bx, by), max(3, int((4.5 + 3.5 * ping) * k)), b_col, -1, cv2.LINE_AA)

        # 7. Vúmetro de Audio / Music Maestro en Tarjeta R3
        vu = self._geom.get("audio_vu")
        if vu:
            x0, y0, x1, y1 = vu["x0"], vu["y0"], vu["x1"], vu["y1"]
            nb = 22
            step_x = (x1 - x0) / float(nb)
            bw = max(2, int(step_x * 0.65))
            vh = y1 - y0
            for i in range(nb):
                if bands is not None and len(bands) > 0:
                    b_idx = min(len(bands) - 1, int(i * len(bands) / nb))
                    amp = max(0.10, min(1.0, float(bands[b_idx]) * 0.85 + 0.25 * energy))
                else:
                    amp = max(0.10, min(1.0, (0.25 + 0.75 * abs(math.sin(t * 7.5 + i * 0.55))) * (0.28 + 0.72 * energy)))
                bh = max(3, int(amp * vh))
                bx = int(x0 + i * step_x)
                col = sec if amp > 0.68 else pri
                cv2.rectangle(f, (bx, y1 - bh), (bx + bw, y1), col, -1)

    def composite(self, frame: np.ndarray, t: float, lines: List[Dict[str, Any]],
                  state: Dict[str, Any]) -> np.ndarray:
        """
        Funde el HUD estático (solo franjas ocupadas) + gráficos vivos 60 FPS +
        subtítulos + espectro FFT y osciloscopio sobre el cuadro uint8 in situ.
        """
        f = frame
        k = self.k

        # 1. Capa estática solo en las 4 franjas perimetrales (el centro 3D no se toca)
        for y0, y1 in ((0, self.top_h), (self.bot_y, self.h)):
            reg = f[y0:y1]
            cv2.multiply(reg, self._static_inv[y0:y1], dst=reg, scale=1.0 / 255.0)
            cv2.add(reg, self._static_pm[y0:y1], dst=reg)

        if self.wide and self.wing_w > 0:
            my0, my1 = self.top_h, self.bot_y
            for x0, x1 in ((0, self.wing_w), (self.right_x, self.w)):
                reg = f[my0:my1, x0:x1]
                cv2.multiply(reg, self._static_inv[my0:my1, x0:x1], dst=reg, scale=1.0 / 255.0)
                cv2.add(reg, self._static_pm[my0:my1, x0:x1], dst=reg)

            # Gráficos animados en vivo (60 FPS C++/cv2)
            self._draw_live_graphs(f, t, state)

        # 2. Subtítulo activo sincronizado
        line = None
        for L in lines:
            if L["start"] <= t <= L["end"]:
                line = L["text"]
                break
        if line:
            pm, inv = self._subtitle_img(line)
            y0 = int(self.h - 468 * k)
            y1 = min(self.h, y0 + pm.shape[0])
            reg = f[y0:y1]
            cv2.multiply(reg, inv[: y1 - y0], dst=reg, scale=1.0 / 255.0)
            cv2.add(reg, pm[: y1 - y0], dst=reg)

        # 3. Espectro vocal FFT (64 barras dual-tono) + Osciloscopio dorado continuo
        if self.show_osc:
            energy = float(state.get("energy", 0.0))
            mouth = float(state.get("mouth_open", 0.0))
            bands = state.get("audio_bands")
            pri = self.col_primary
            sec = self.col_secondary
            bars, bw = 64, max(2, int(self.w * 0.0095))
            total_span = bars * bw * 1.55
            x0 = int(self.w * 0.5 - total_span / 2)
            base_y = int(self.h - 168 * k)
            osc_pts = []
            for i in range(bars):
                if bands is not None and len(bands) > 0:
                    # Espectro simétrico espejo desde las 16 bandas FFT reales
                    mirror_pos = abs((i / float(bars - 1)) * 2.0 - 1.0)
                    b_idx = min(len(bands) - 1, int(mirror_pos * (len(bands) - 1)))
                    raw_amp = float(bands[b_idx])
                    amp = max(0.08, min(1.0, raw_amp * 0.85 + 0.18 * abs(math.sin(t * 9.0 + i * 0.4)) * max(mouth, energy)))
                else:
                    ph = t * 9.0 + i * 0.41
                    amp = (0.22 + 0.78 * abs(math.sin(ph))) * (0.18 + 0.82 * max(mouth, energy * 0.6))
                bh = int(amp * 92 * k)
                x = x0 + int(i * bw * 1.55)
                if bh >= 2:
                    sh = 0.45 + 0.55 * amp
                    t_mix = max(0.0, min(1.0, (amp - 0.45) / 0.45))
                    bc = (
                        int((pri[0] * (1.0 - t_mix) + sec[0] * t_mix) * sh),
                        int((pri[1] * (1.0 - t_mix) + sec[1] * t_mix) * sh),
                        int((pri[2] * (1.0 - t_mix) + sec[2] * t_mix) * sh),
                    )
                    cv2.rectangle(f, (x, base_y - bh), (x + bw, base_y), bc, -1)
                osc_pts.append([x + bw // 2, base_y - max(4, bh + int(8 * k))])
            if len(osc_pts) >= 2:
                cv2.polylines(
                    f,
                    [np.array(osc_pts, dtype=np.int32).reshape((-1, 1, 2))],
                    False,
                    sec,
                    max(1, int(3.0 * k)),
                    cv2.LINE_AA,
                )

        # 4. Barra de progreso temporal
        prog = float(state.get("progress", 0.0))
        py = int(self.h - 42 * k)
        th = max(2, int(8 * k))
        cv2.rectangle(f, (int(78 * k), py), (self.w - int(78 * k), py + th), (14, 34, 44), -1)
        cv2.rectangle(
            f,
            (int(78 * k), py),
            (int(78 * k) + int((self.w - 156 * k) * prog), py + th),
            self.col_primary,
            -1,
        )

        return f


# --------------------------------------------------------------- codificacion
def _nvenc_available(width: int = 1920, height: int = 1080) -> bool:
    """Verifica que NVENC funcione a la resolución objetivo sin agotar la VRAM compartida."""
    if not shutil.which("ffmpeg"):
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={width}x{height}:d=0.2:r=30",
             "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            capture_output=True, timeout=40,
        )
        err = (r.stderr or b"").decode(errors="ignore").lower()
        if r.returncode != 0 or "cannot allocate memory" in err or "could not open encoder" in err:
            return False
        return True
    except Exception:
        return False


_VAAPI_CACHE: Dict[Tuple[int, int], Optional[str]] = {}


def _vaapi_device(width: int, height: int) -> Optional[str]:
    """Nodo DRI de GPU AMD/Intel capaz de codificar H.264 por VAAPI a esta resolución."""
    key = (width, height)
    if key in _VAAPI_CACHE:
        return _VAAPI_CACHE[key]
    found = None
    for node in sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").exists() else []:
        try:
            drv = Path(f"/sys/class/drm/{node.name}/device/driver").resolve().name
        except Exception:
            drv = ""
        if drv not in ("amdgpu", "i915", "xe", "radeon"):
            continue
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-vaapi_device", str(node),
                 "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=0.2:r=30",
                 "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-"],
                capture_output=True, timeout=30,
            )
            if r.returncode == 0:
                found = str(node)
                break
        except Exception:
            continue
    _VAAPI_CACHE[key] = found
    return found


def _video_encoder_args(bitrate_kbps: int, use_nvenc: bool, threads: int = 2,
                        vaapi_device: Optional[str] = None) -> List[str]:
    maxrate = int(bitrate_kbps * 1.35)
    if vaapi_device:
        return [
            "-vf", "format=nv12,hwupload",
            "-c:v", "h264_vaapi", "-profile:v", "high",
            "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{maxrate}k",
            "-bufsize", f"{maxrate * 2}k", "-g", "120",
        ]
    if use_nvenc:
        return [
            "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", "23",
            "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{maxrate}k",
            "-bufsize", f"{maxrate * 2}k",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "120",
        ]
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-maxrate", f"{maxrate}k", "-bufsize", f"{maxrate * 2}k",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "120",
        "-threads", str(threads),
    ]


# ----------------------------------------------------------- render segmentado
def _render_segment(args: Dict[str, Any]) -> Dict[str, Any]:
    """Renderiza y codifica un tramo de cuadros. Ejecutado en un proceso propio."""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from core.character_3d_renderer import get_character_3d_renderer

    w, h = args["width"], args["height"]
    fps = args["fps"]
    f0, n = args["frame_start"], args["frame_count"]
    out_path = args["out_path"]
    telemetry = args.get("telemetry")
    manifest = args.get("manifest") or (telemetry.get("visual_manifest") if isinstance(telemetry, dict) else None)
    seg_env = args.get("audio_env")
    seg_bands = args.get("audio_bands")

    try:
        os.nice(15)
    except Exception:
        pass
    renderer = get_character_3d_renderer(args["quality"], manifest=manifest, telemetry=telemetry)
    hud = HudRenderer(w, h, args["title"], telemetry=telemetry, manifest=manifest) if args["hud"] else None
    lines = args["lines"]
    wt = args["word_timings"]
    duration = args["duration"]

    cmd = (
        ["ffmpeg", "-y", "-loglevel", "error"]
        + list(args.get("pre_input", []))
        + ["-f", "rawvideo", "-vcodec", "rawvideo",
           "-s", f"{w}x{h}", "-pix_fmt", "rgb24", "-r", str(fps), "-i", "-"]
        + args["enc_args"] + ["-an", out_path]
    )

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(n):
            idx = f0 + i
            t = idx / float(fps)
            a_rms = (seg_env[i] / 255.0) if (seg_env is not None and i < len(seg_env)) else None
            a_bnd = ([v / 255.0 for v in seg_bands[i]] if (seg_bands is not None and i < len(seg_bands)) else None)
            st = compute_vocal_state(t, wt, duration, audio_rms=a_rms, audio_bands=a_bnd)
            img = renderer.render_frame(
                t, w, h, st,
                char_scale=args["char_scale"],
                center=args["center"],
            )
            frame = renderer.post_process(
                img, bloom=args["bloom"], vignette=0.0, grain=0.0, seed=idx,
            )
            if hud is not None:
                frame = hud.composite(frame, t, lines, st)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        _, err = proc.communicate(timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": (err or b"").decode(errors="ignore")[-300:], "seg": args["seg"]}
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "seg": args["seg"]}

    return {"ok": True, "seg": args["seg"], "path": out_path, "frames": n}


def render_video_4k(
    audio_path: str | Path,
    word_timings: List[Dict[str, Any]],
    duration: float,
    output_path: str | Path,
    width: int = 3840,
    height: int = 2160,
    fps: int = 60,
    title: str = "TARDIS · MENSAJE SOBERANO",
    quality: str = "high",
    hud: bool = True,
    char_scale: float = 0.70,
    center: Tuple[float, float] = (0.5, 0.44),
    bloom: float = 0.52,
    workers: Optional[int] = None,
    max_bytes: int = TELEGRAM_MAX_BYTES,
    telemetry: Optional[Dict[str, Any]] = None,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Renderiza el videomensaje completo del personaje 3D + gráficos vivos de TARDIS
    y lo multiplexa con el audio. Reparte los cuadros entre procesos independientes.
    """
    import time as _time
    t0 = _time.time()

    audio_path = str(audio_path)
    output_path = Path(output_path)
    total_frames = max(1, int(round(duration * fps)))

    # Capturar instantánea viva de TARDIS una sola vez para todos los segmentos
    snap = telemetry if isinstance(telemetry, dict) else collect_tardis_snapshot()
    eff_manifest = manifest if isinstance(manifest, dict) else snap.get("visual_manifest")

    # Extraer envolvente RMS y espectro FFT real del audio una sola vez (~20 ms)
    audio_env, audio_bands = extract_audio_features(audio_path, total_frames, fps)

    if workers is None:
        workers = max(1, min(4, (os.cpu_count() or 4) // 4))
    workers = max(1, min(workers, total_frames))

    audio_kbps = 192
    budget_kbps = int((max_bytes * 8 / 1000.0) / max(1.0, duration)) - audio_kbps
    px_kbps = min(32000, int(width * height * fps * 0.075 / 1000))
    bitrate_kbps = max(2500, min(px_kbps, budget_kbps if budget_kbps > 0 else px_kbps))

    vaapi = _vaapi_device(width, height)
    use_nvenc = (vaapi is None) and (workers == 1) and _nvenc_available(width, height)
    enc_args = _video_encoder_args(
        bitrate_kbps, use_nvenc,
        threads=max(1, 16 // max(1, workers)),
        vaapi_device=vaapi,
    )
    pre_input = ["-vaapi_device", vaapi] if vaapi else []
    if vaapi:
        bitrate_kbps = min(bitrate_kbps, 16000)
        enc_args = _video_encoder_args(bitrate_kbps, False, vaapi_device=vaapi)
    encoder_name = "h264_vaapi" if vaapi else ("h264_nvenc" if use_nvenc else "libx264")

    lines = HudRenderer.build_lines(word_timings) if hud else []

    tmpdir = Path(tempfile.mkdtemp(prefix="tardis4k_"))
    try:
        per = math.ceil(total_frames / workers)
        jobs = []
        for s in range(workers):
            f0 = s * per
            if f0 >= total_frames:
                break
            n = min(per, total_frames - f0)
            jobs.append({
                "seg": s,
                "frame_start": f0,
                "frame_count": n,
                "width": width,
                "height": height,
                "fps": fps,
                "duration": duration,
                "word_timings": word_timings,
                "lines": lines,
                "title": title,
                "quality": quality,
                "hud": hud,
                "char_scale": char_scale,
                "center": list(center),
                "bloom": bloom,
                "telemetry": snap,
                "manifest": eff_manifest,
                "audio_env": audio_env[f0:f0 + n] if audio_env is not None else None,
                "audio_bands": audio_bands[f0:f0 + n] if audio_bands is not None else None,
                "enc_args": enc_args,
                "pre_input": pre_input,
                "out_path": str(tmpdir / f"seg_{s:03d}.mp4"),
            })

        py = sys.executable or "python3"
        procs = []
        for j in jobs:
            jf = tmpdir / f"job_{j['seg']:03d}.json"
            jf.write_text(json.dumps(j), encoding="utf-8")
            procs.append((j, jf, subprocess.Popen(
                [py, str(Path(__file__).resolve()), "--job", str(jf)],
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )))

        results = []
        for j, jf, pr in procs:
            out, err = pr.communicate(timeout=1800)
            if pr.returncode != 0:
                results.append({"ok": False, "seg": j["seg"],
                                "error": (err or b"").decode(errors="ignore")[-300:]})
                continue
            try:
                results.append(json.loads((out or b"{}").decode(errors="ignore").strip().splitlines()[-1]))
            except Exception as e:
                results.append({"ok": False, "seg": j["seg"], "error": f"respuesta ilegible: {e}"})

        failed = [r for r in results if not r.get("ok")]
        if failed:
            return {"ok": False, "error": f"Fallo en segmento {failed[0].get('seg')}: {failed[0].get('error')}"}

        results.sort(key=lambda r: r["seg"])

        listfile = tmpdir / "segments.txt"
        listfile.write_text("".join(f"file '{r['path']}'\n" for r in results), encoding="utf-8")

        mux = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listfile),
            "-i", audio_path,
            "-c:v", "copy", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-shortest", "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(mux, capture_output=True, timeout=300)
        if r.returncode != 0 or not output_path.exists():
            return {"ok": False, "error": f"Multiplexado fallido: {r.stderr.decode(errors='ignore')[-300:]}"}

        size = output_path.stat().st_size
        return {
            "ok": True,
            "path": str(output_path),
            "size": size,
            "width": width,
            "height": height,
            "fps": fps,
            "duration": duration,
            "frames": total_frames,
            "workers": len(jobs),
            "encoder": encoder_name,
            "bitrate_kbps": bitrate_kbps,
            "elapsed_s": round(_time.time() - t0, 2),
            "over_limit": size > max_bytes,
            "audio_reactive": audio_env is not None,
            "telemetry_summary": summarize_snapshot(snap),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------- entrada de subproceso
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Renderizador de segmento de video 4K de TARDIS")
    ap.add_argument("--job", required=True, help="Ruta al archivo JSON con la descripcion del tramo")
    a = ap.parse_args()

    job = json.loads(Path(a.job).read_text(encoding="utf-8"))
    job["center"] = tuple(job.get("center", (0.5, 0.42)))
    print(json.dumps(_render_segment(job)))
