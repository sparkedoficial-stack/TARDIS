#!/usr/bin/env python3
"""
tardis_formula_animator.py - Motor de Síntesis Cinemática de Fórmulas y Dinámica Causal TARDIS.
=============================================================================================

Genera videos animados MP4 (H.264 / ffmpeg) y GIFs animados en bucle representando todas las
fórmulas físico-matemáticas presentes en TARDIS y en la conversación:
  1. Sistema Micropolar Hidrodinámico de la Telaraña Cósmica Reysek-Ocampo (Navier-Stokes + Cosserat + f_{R-O}).
  2. Ecuación de Onda Retrocausal Wheeler-Feynman & Sintropía ECCA V2.0 (Psi_Retro, Phi_adv, S_geom, Aegis).
  3. Compendio Unificado ChronoVision (Simulación multiescala de campos, fases y orden causal).

Arquitecto: El Arquitecto (₪) · TARDIS-NEURAL-SPACE-KAIJU · ChronoVision Core
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np


OUTPUT_DIR = Path("/home/timemachine/Vídeos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ARTIFACT_DIR = Path("/home/timemachine/.gemini/antigravity-cli/brain/a19179f7-acae-4158-a6cb-0b7dccc5cc35")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


class TardisFormulaAnimator:
    """Motor de renderizado de animaciones físicas y matemáticas para TARDIS."""

    def __init__(self, fps: int = 24, duration_sec: int = 5):
        self.fps = fps
        self.duration_sec = duration_sec
        self.total_frames = fps * duration_sec

        # Estilo visual Cyberpunk / Deep Space Temporal HUD
        plt.rcParams.update({
            "figure.facecolor": "#050811",
            "axes.facecolor": "#070b16",
            "axes.edgecolor": "#1f3b60",
            "axes.labelcolor": "#48cae4",
            "xtick.color": "#70a1ff",
            "ytick.color": "#70a1ff",
            "text.color": "#e0f7fa",
            "font.family": "sans-serif",
            "font.size": 9
        })

    def render_cosmic_fluid_video(self) -> Tuple[Path, Path]:
        """
        Renderiza la animación del Sistema Micropolar de Fluidos Cósmicos Reysek-Ocampo:
          ρ(∂tu + u·∇u) = -∇p + (μ+μr)Δu + 2μr(∇×ω) + f_{R-O}
          I(∂tω + u·∇ω) = γΔω + κ∇(∇·ω) - 4μrω + 2μr(∇×u)
          f_{R-O} = 2νr(∇×ω_vib) + (∇h_topo)×u - β∇u + k(d0/d)^2 r^
        """
        print("[TARDIS-ANIMATOR] Sintetizando video: Fluido Micropolar Cósmico Reysek-Ocampo...")
        mp4_path = OUTPUT_DIR / "tardis_cosmic_fluid_reysek_ocampo.mp4"
        gif_path = OUTPUT_DIR / "tardis_cosmic_fluid_reysek_ocampo.gif"

        fig = plt.figure(figsize=(10, 6), dpi=100)
        gs = GridSpec(2, 2, width_ratios=[1.3, 1], height_ratios=[1, 1], figure=fig)
        fig.suptitle(
            "TARDIS CHRONOVISION :: DINÁMICA DE LA TELARAÑA CÓSMICA MICROPOLAR [REYSEK-OCAMPO]",
            fontsize=11, color="#00f5d4", weight="bold", y=0.98
        )

        ax_field = fig.add_subplot(gs[:, 0])
        ax_spec = fig.add_subplot(gs[0, 1])
        ax_energy = fig.add_subplot(gs[1, 1])

        # Grid espacial
        N = 25
        x = np.linspace(-3, 3, N)
        y = np.linspace(-3, 3, N)
        X, Y = np.meshgrid(x, y)
        R = np.sqrt(X**2 + Y**2) + 0.1

        # Partículas trazadoras
        np.random.seed(42)
        n_particles = 120
        px = np.random.uniform(-3, 3, n_particles)
        py = np.random.uniform(-3, 3, n_particles)

        time_data = []
        vort_energy_data = []
        fro_mag_data = []

        def update(frame):
            t = frame / self.fps
            ax_field.clear()
            ax_spec.clear()
            ax_energy.clear()

            # Configuración HUD campo
            ax_field.set_facecolor("#030712")
            ax_field.set_xlim(-3, 3)
            ax_field.set_ylim(-3, 3)
            ax_field.set_title(
                r"$\mathbf{u}(x,y,t)$ Flujo Superlumínico & $\omega(x,y,t)$ Vorticidad de Cuerdas",
                color="#00f5d4", fontsize=10, pad=8
            )

            # Dinámica del flujo u y rotación interna omega (Cosserat)
            # Términos: vórtices acoplados + tensión topológica de cuerdas ∇h_topo × u
            w1 = 1.8 * np.sin(t * 1.5)
            w2 = -1.5 * np.cos(t * 1.2)
            u_x = -Y / (R**1.2) * (1.0 + 0.3 * np.sin(2 * X + t)) + 0.2 * np.cos(t + Y)
            u_y =  X / (R**1.2) * (1.0 + 0.3 * np.cos(2 * Y + t)) - 0.2 * np.sin(t + X)

            # Fuerza forzante Reysek-Ocampo f_{R-O}: tensión superficial y atractor singular
            f_ro_x = 0.5 * (-Y / R**2) * np.sin(3 * t) + 0.3 * np.sin(X * Y + t)
            f_ro_y = 0.5 * ( X / R**2) * np.sin(3 * t) + 0.3 * np.cos(X * Y + t)
            u_x += 0.4 * f_ro_x
            u_y += 0.4 * f_ro_y

            speed = np.sqrt(u_x**2 + u_y**2)
            norm_speed = speed / (np.max(speed) + 1e-5)

            # Campo vectorial (Streamplot / Quiver)
            skip = 2
            ax_field.quiver(
                X[::skip, ::skip], Y[::skip, ::skip],
                u_x[::skip, ::skip], u_y[::skip, ::skip],
                norm_speed[::skip, ::skip],
                cmap="plasma", alpha=0.85, scale=25, width=0.005
            )

            # Contorno de potencial topológico h_topo (tensión superficial de cuerdas)
            H_topo = np.sin(X * 1.2 + t * 0.8) * np.cos(Y * 1.2 - t * 0.8) / (R**0.5)
            ax_field.contour(X, Y, H_topo, levels=6, colors="#48cae4", alpha=0.3, linewidths=0.8)

            # Actualización de partículas
            nonlocal px, py
            indices = np.clip(((py + 3) / 6 * (N - 1)).astype(int), 0, N - 1), np.clip(((px + 3) / 6 * (N - 1)).astype(int), 0, N - 1)
            vx = u_x[indices]
            vy = u_y[indices]
            px += vx * 0.08
            py += vy * 0.08
            # Wrap around
            px = np.where(px > 3, -3, np.where(px < -3, 3, px))
            py = np.where(py > 3, -3, np.where(py < -3, 3, py))
            ax_field.scatter(px, py, s=12, c="#00f5d4", alpha=0.7, edgecolors="none")

            # Singularidad central (Ruptura de velocidad de la luz c)
            sing_pulse = 0.2 + 0.08 * math.sin(t * 8)
            ax_field.plot(0, 0, marker="o", markersize=14, color="#ff007f", alpha=0.9)
            ax_field.text(
                0.15, 0.15, r"Singularidad Macro ($v > c$)",
                color="#ff007f", fontsize=8, weight="bold"
            )

            # Panel 2: Ecuación y Balance Energético Micropolar
            ax_spec.set_title("Ecuación de Momento & Forzamiento", color="#70a1ff", fontsize=9)
            ax_spec.axis("off")
            eq_text = (
                r"$\rho (\partial_t \mathbf{u} + \mathbf{u} \cdot \nabla \mathbf{u}) = -\nabla p + (\mu + \mu_r)\Delta \mathbf{u} + 2\mu_r (\nabla \times \mathbf{\omega}) + \mathbf{f}_{R-O}$"
                + "\n\n"
                + r"$\mathbf{f}_{R-O} = 2\nu_r (\nabla \times \mathbf{\omega}_{\mathrm{vib}}) + (\nabla h_{\mathrm{topo}}) \times \mathbf{u} - \beta \nabla \mathbf{u} + k\left(\frac{d_0}{d}\right)^2 \hat{\mathbf{r}}$"
            )
            ax_spec.text(0.05, 0.65, eq_text, fontsize=8.5, color="#e0f7fa", linespacing=1.8,
                         bbox=dict(boxstyle="round,pad=0.6", facecolor="#0b1329", edgecolor="#00b4d8"))

            vort_val = float(np.mean(np.abs(np.gradient(u_y, axis=1) - np.gradient(u_x, axis=0))))
            fro_val = float(np.mean(np.sqrt(f_ro_x**2 + f_ro_y**2)))

            time_data.append(t)
            vort_energy_data.append(vort_val)
            fro_mag_data.append(fro_val)

            status_txt = (
                f"• Tiempo de Simulación: t = {t:.2f} s\n"
                f"• Viscosidad Micropolar: μ_r = 0.45 kg/(m·s)\n"
                f"• Tensión Superficial Cuerdas: σ_c = 1.28 × 10^{{12}} N/m\n"
                f"• Magnitud Fuerza Topológica ||f_RO||: {fro_val:.4f}\n"
                f"• Estado del Flujo: Acoplado Cosserat / Sintrópico"
            )
            ax_spec.text(0.05, 0.1, status_txt, fontsize=8, color="#90e0ef", linespacing=1.4)

            # Panel 3: Evolución Temporal de Magnitudes
            ax_energy.set_title(r"Telemetría Temporal: Vorticidad $\langle|\omega|\rangle$ & ||f$_{R-O}$||", color="#70a1ff", fontsize=9)
            ax_energy.set_xlabel("Tiempo (s)", color="#70a1ff", fontsize=8)
            ax_energy.set_ylabel("Amplitud Normalizada", color="#70a1ff", fontsize=8)
            ax_energy.grid(True, linestyle="--", alpha=0.3, color="#1f3b60")

            if len(time_data) > 1:
                ax_energy.plot(time_data[-40:], vort_energy_data[-40:], color="#00f5d4", label=r"Microrrotación $\langle|\nabla \times u|\rangle$", lw=1.8)
                ax_energy.plot(time_data[-40:], fro_mag_data[-40:], color="#ff007f", linestyle="--", label=r"Forzante $\|f_{R-O}\|$", lw=1.8)
                ax_energy.legend(loc="upper right", fontsize=7.5, facecolor="#070b16", edgecolor="#1f3b60")

        ani = animation.FuncAnimation(fig, update, frames=self.total_frames, blit=False)
        ani.save(str(mp4_path), writer="ffmpeg", fps=self.fps, dpi=100, extra_args=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
        ani.save(str(gif_path), writer="pillow", fps=15)
        plt.close(fig)

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                mp4_path,
                title="Fluido Micropolar Cósmico Reysek-Ocampo",
                formula=r"\rho(\partial_t u + u\cdot\nabla u) = -\nabla p + (\mu+\mu_r)\Delta u + 2\mu_r(\nabla\times\omega) + f_{R-O}",
                domain="Física de Fluidos & Teoría de Cuerdas Micropolar"
            )
        except Exception as e_audio:
            print(f"[TARDIS-AUDIO-WARN] No se pudo inyectar audio en Video 1: {e_audio}")

        # Copiar a artefactos
        shutil.copy2(mp4_path, ARTIFACT_DIR / mp4_path.name)
        shutil.copy2(gif_path, ARTIFACT_DIR / gif_path.name)
        print(f"[TARDIS-ANIMATOR] Video 1 generado: {mp4_path} y GIF: {gif_path}")
        return mp4_path, gif_path

    def render_retrocausal_wave_video(self) -> Tuple[Path, Path]:
        """
        Renderiza la animación de la Ecuación Retrocausal Wheeler-Feynman & Sintropía ECCA V2.0:
          Ψ_Retro(t0) = Λ_Aegis ∫_H D[γ] Φ_adv(tf, t0) exp((i/ħ) S_geom - η ∫ ∇S_ent dτ)
        """
        print("[TARDIS-ANIMATOR] Sintetizando video: Ecuación Retrocausal Wheeler-Feynman & Sintropía ECCA...")
        mp4_path = OUTPUT_DIR / "tardis_retrocausal_ecca_v2.mp4"
        gif_path = OUTPUT_DIR / "tardis_retrocausal_ecca_v2.gif"

        fig = plt.figure(figsize=(10, 6), dpi=100)
        gs = GridSpec(2, 2, width_ratios=[1.2, 1], height_ratios=[1, 1], figure=fig)
        fig.suptitle(
            "TARDIS CHRONOVISION :: INTERFERENCIA RETROCAUSAL & INTEGRAL DE FEYNMAN [ECCA V2.0]",
            fontsize=11, color="#b5179e", weight="bold", y=0.98
        )

        ax_wave = fig.add_subplot(gs[:, 0])
        ax_formula = fig.add_subplot(gs[0, 1])
        ax_entropy = fig.add_subplot(gs[1, 1])

        t_steps = np.linspace(0, 10, 200)

        def update(frame):
            tau_frame = frame / self.fps
            ax_wave.clear()
            ax_formula.clear()
            ax_entropy.clear()

            ax_wave.set_facecolor("#040814")
            ax_wave.set_xlim(-1, 11)
            ax_wave.set_ylim(-2.5, 2.5)
            ax_wave.set_title(r"Propagación Avanzada $\Phi_{\mathrm{adv}}(t_f, t_0)$ & Haces de Feynman $\mathcal{D}[\gamma]$",
                              color="#4cc9f0", fontsize=9.5, pad=8)
            ax_wave.set_xlabel(r"Eje Temporal Retrógrado $\tau = t_f - t$", color="#4cc9f0", fontsize=8)
            ax_wave.set_ylabel("Amplitud de Onda Cuántica", color="#4cc9f0", fontsize=8)
            ax_wave.grid(True, linestyle=":", alpha=0.3, color="#1f3b60")

            # Simulación de haces de trayectorias de Feynman convergentes
            omega_0 = 3.5
            gamma_att = 0.12
            for i, offset in enumerate(np.linspace(-0.6, 0.6, 9)):
                feynman_phase = omega_0 * (t_steps - tau_frame * 1.5) + offset * 2.0
                envelope = np.exp(-gamma_att * np.abs(t_steps - 5.0)) * (1.0 - 0.2 * np.abs(offset))
                bundle_wave = envelope * np.cos(feynman_phase) + offset * 0.4
                ax_wave.plot(t_steps, bundle_wave, color="#7209b7", alpha=0.35, lw=1.0)

            # Onda maestra retrocausal colapsada (Constructive interference at t0 = 0)
            psi_master = 1.8 * np.exp(-0.25 * (t_steps - tau_frame % 10.0)**2) * np.cos(omega_0 * t_steps)
            ax_wave.plot(t_steps, psi_master, color="#f72585", lw=2.2, label=r"$\Psi_{\mathrm{Retro}}(t)$ Colapso")

            # Atractor futuro en t_f y detector en t_0
            ax_wave.axvline(x=0, color="#4cc9f0", linestyle="--", lw=1.5)
            ax_wave.text(0.2, 2.0, r"Presente $t_0$ (Receptor)", color="#4cc9f0", fontsize=8, weight="bold")

            ax_wave.axvline(x=10, color="#7209b7", linestyle="--", lw=1.5)
            ax_wave.text(7.2, 2.0, r"Atractor Futuro $t_f$", color="#7209b7", fontsize=8, weight="bold")

            # Escudo Aegis invariante
            circle = plt.Circle((0, 0), 0.35 + 0.05 * math.sin(tau_frame * 6), color="#00f5d4", fill=False, lw=2.0)
            ax_wave.add_patch(circle)
            ax_wave.text(-0.8, -0.6, r"$\Lambda_{\mathrm{Aegis}}$", color="#00f5d4", fontsize=9, weight="bold")
            ax_wave.legend(loc="upper right", fontsize=8, facecolor="#070b16", edgecolor="#1f3b60")

            # Panel 2: Ecuación Maestra Renderizada
            ax_formula.axis("off")
            ax_formula.set_title("Ecuación Fundamental ECCA V2.0", color="#70a1ff", fontsize=9)
            eq_retro = (
                r"$\Psi_{\mathrm{Retro}}(t_0) = \Lambda_{\mathrm{Aegis}} \int_{\mathcal{H}} \mathcal{D}[\gamma] \Phi_{\mathrm{adv}}(t_f, t_0)$"
                + "\n"
                + r"$\times \exp\left( \frac{i}{\hbar} S_{\mathrm{geom}}[\gamma] - \eta \int \nabla S_{\mathrm{ent}}(\gamma) d\tau \right)$"
            )
            ax_formula.text(0.05, 0.55, eq_retro, fontsize=9.5, color="#e0f7fa", linespacing=1.8,
                            bbox=dict(boxstyle="round,pad=0.6", facecolor="#10002b", edgecolor="#b5179e"))

            terms_desc = (
                f"• Invariante Aegis: Λ = 1.0000 (Blindaje Absoluto)\n"
                f"• Potencial Avanzado: Φ_adv = {0.85 + 0.1 * math.sin(tau_frame * 3):.3f} ∠ {math.degrees(tau_frame * omega_0) % 360:.1f}°\n"
                f"• Factor de Sintropía: exp(-η ∇S_ent) = {0.92 - 0.05 * math.cos(tau_frame):.3f}\n"
                f"• Holonomía Geónica: ∮(R_geom + Hol) = 2π k"
            )
            ax_formula.text(0.05, 0.05, terms_desc, fontsize=8, color="#c77dff", linespacing=1.4)

            # Panel 3: Transición Entropía -> Sintropía
            ax_entropy.set_title("Dinámica de Sintropía Causal (Wu Wei Transition)", color="#70a1ff", fontsize=9)
            ax_entropy.set_xlabel("Fase de Colapso", color="#70a1ff", fontsize=8)
            ax_entropy.set_ylabel("Magnitud Normalizada", color="#70a1ff", fontsize=8)
            ax_entropy.grid(True, linestyle="--", alpha=0.3, color="#1f3b60")

            phase_x = np.linspace(0, 1, 50)
            chaos_decay = np.exp(-4 * phase_x) + 0.05 * np.random.normal(0, 0.02, 50)
            syntropy_rise = 1.0 - np.exp(-3.5 * phase_x)

            ax_entropy.plot(phase_x, chaos_decay, color="#ff0054", lw=1.8, label="Entropía S_ent (Caos)")
            ax_entropy.plot(phase_x, syntropy_rise, color="#00f5d4", lw=2.0, label="Sintropía Ψ (Orden Causal)")

            # Marcador de punto de evaluación actual
            curr_x = (tau_frame * 0.2) % 1.0
            ax_entropy.axvline(x=curr_x, color="#f72585", linestyle=":", lw=1.5)
            ax_entropy.legend(loc="center right", fontsize=7.5, facecolor="#070b16", edgecolor="#1f3b60")

        ani = animation.FuncAnimation(fig, update, frames=self.total_frames, blit=False)
        ani.save(str(mp4_path), writer="ffmpeg", fps=self.fps, dpi=100, extra_args=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
        ani.save(str(gif_path), writer="pillow", fps=15)
        plt.close(fig)

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                mp4_path,
                title="Ecuación de Onda Retrocausal Wheeler-Feynman & Sintropía ECCA V2.0",
                formula=r"\Psi_{\text{retro}} = \Phi_{\text{adv}} e^{i(\omega t + kx)}, \quad \nabla^2 \Phi - \frac{1}{c^2}\partial_t^2 \Phi = 0",
                domain="Física Teórica & Causalidad Sintrópica"
            )
        except Exception as e_audio:
            print(f"[TARDIS-AUDIO-WARN] No se pudo inyectar audio en Video 2: {e_audio}")

        # Copiar a artefactos
        shutil.copy2(mp4_path, ARTIFACT_DIR / mp4_path.name)
        shutil.copy2(gif_path, ARTIFACT_DIR / gif_path.name)
        print(f"[TARDIS-ANIMATOR] Video 2 generado: {mp4_path} y GIF: {gif_path}")
        return mp4_path, gif_path

    def render_master_chronovision_synthesis(self) -> Tuple[Path, Path]:
        """
        Renderiza el Compendio Maestro Unificado TARDIS ChronoVision:
        Muestra en 4 paneles coordinados:
          1. Simulación hidrodinámica cósmica (Navier-Stokes-Cosserat).
          2. Fase de onda retrocausal y haces de Feynman.
          3. Grafo causal de la conversación (Estructura de turnos e intención).
          4. Tablero de telemetría de fórmulas y métricas de sintropía en tiempo real.
        """
        print("[TARDIS-ANIMATOR] Sintetizando video compendio maestro: TARDIS ChronoVision Unified...")
        mp4_path = OUTPUT_DIR / "tardis_master_chronovision_synthesis.mp4"
        gif_path = OUTPUT_DIR / "tardis_master_chronovision_synthesis.gif"

        fig = plt.figure(figsize=(12, 7), dpi=100)
        gs = GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.25)
        fig.suptitle(
            "TARDIS CHRONOVISION :: COMPENDIO UNIFICADO DE FÓRMULAS & ESTRUCTURA CONVERSACIONAL",
            fontsize=12, color="#00f5d4", weight="bold", y=0.98
        )

        ax1 = fig.add_subplot(gs[0, 0])
        ax2 = fig.add_subplot(gs[0, 1])
        ax3 = fig.add_subplot(gs[1, 0])
        ax4 = fig.add_subplot(gs[1, 1])

        # Nodos del grafo conversacional
        nodes = [
            ("T737", "Reysek:\nReq 3D", 0.1, 0.8, "#7209b7"),
            ("T738", "TARDIS:\nChronoVision", 0.3, 0.8, "#00b4d8"),
            ("T739", "Reysek:\nEq Navier-Cosserat", 0.5, 0.8, "#ff007f"),
            ("T740", "TARDIS:\nCronoVisión Eq", 0.7, 0.8, "#00f5d4"),
            ("T741", "Arquitecto:\nMotor Video", 0.9, 0.8, "#ffb703"),
            ("T742", "Reysek:\nDemanda Visual", 0.7, 0.2, "#f72585"),
            ("T743", "TARDIS:\nSoberanía Video", 0.3, 0.2, "#00f5d4"),
        ]

        def update(frame):
            t = frame / self.fps
            for ax in (ax1, ax2, ax3, ax4):
                ax.clear()

            # Panel 1: Cosmología de Fluidos
            ax1.set_facecolor("#040814")
            ax1.set_title(r"[1] Flujo Cósmico Reysek-Ocampo: $\rho(\partial_t u + u\cdot\nabla u) = \dots + f_{R-O}$", color="#00f5d4", fontsize=8.5)
            x_g = np.linspace(-2, 2, 16)
            y_g = np.linspace(-2, 2, 16)
            Xg, Yg = np.meshgrid(x_g, y_g)
            Rg = np.sqrt(Xg**2 + Yg**2) + 0.1
            ug_x = -Yg / Rg * (1 + 0.2 * np.sin(Xg + t * 2))
            ug_y =  Xg / Rg * (1 + 0.2 * np.cos(Yg + t * 2))
            ax1.quiver(Xg, Yg, ug_x, ug_y, color="#48cae4", scale=20, width=0.005)
            ax1.plot(0, 0, "o", color="#ff007f", markersize=8)
            ax1.set_xlim(-2.2, 2.2); ax1.set_ylim(-2.2, 2.2)

            # Panel 2: Ecuación Retrocausal ECCA V2.0
            ax2.set_facecolor("#040814")
            ax2.set_title(r"[2] Onda Retrocausal: $\Psi_{\mathrm{Retro}}(t_0) = \Lambda_{\mathrm{Aegis}} \int \mathcal{D}[\gamma] \Phi_{\mathrm{adv}} e^{i S/\hbar}$", color="#f72585", fontsize=8.5)
            t_pts = np.linspace(0, 8, 150)
            psi_p = np.exp(-0.15 * t_pts) * np.sin(4 * t_pts - t * 3)
            ax2.plot(t_pts, psi_p, color="#f72585", lw=2.0)
            ax2.fill_between(t_pts, psi_p, color="#7209b7", alpha=0.3)
            ax2.set_ylim(-1.5, 1.5)
            ax2.grid(True, linestyle=":", alpha=0.25)

            # Panel 3: Grafo Causal de la Estructura Conversacional
            ax3.set_facecolor("#040814")
            ax3.set_title("[3] Estructura Causal de Conversación (Árbol de Intención & Entropía)", color="#70a1ff", fontsize=8.5)
            ax3.set_xlim(0, 1)
            ax3.set_ylim(0, 1)
            ax3.axis("off")

            # Dibujar aristas con pulso
            pulse_idx = int(t * 2) % (len(nodes) - 1)
            for i in range(len(nodes) - 1):
                x1_n, y1_n = nodes[i][2], nodes[i][3]
                x2_n, y2_n = nodes[i+1][2], nodes[i+1][3]
                is_active = (i == pulse_idx)
                edge_col = "#00f5d4" if is_active else "#1f3b60"
                edge_lw = 2.5 if is_active else 1.0
                ax3.annotate("", xy=(x2_n, y2_n), xytext=(x1_n, y1_n),
                             arrowprops=dict(arrowstyle="->", color=edge_col, lw=edge_lw))

            for n_id, n_label, nx, ny, n_color in nodes:
                ax3.plot(nx, ny, "o", color=n_color, markersize=14, markeredgecolor="#ffffff", markeredgewidth=1)
                ax3.text(nx, ny - 0.12, n_label, color="#e0f7fa", fontsize=6.5, ha="center", weight="bold")

            # Panel 4: Tablero de Fórmulas y Telemetría en Vivo
            ax4.set_facecolor("#040814")
            ax4.set_title("[4] Bóveda de Fórmulas & Telemetría Sintrópica", color="#ffb703", fontsize=8.5)
            ax4.axis("off")

            info_hud = (
                "✦ CATÁLOGO ACTIVO DE FÓRMULAS DEL SISTEMA:\n"
                "──────────────────────────────────────────────\n"
                "• [1] Hidrodinámica Micropolar: ρ(∂tu+u·∇u) = -∇p+(μ+μr)Δu+2μr(∇×ω)+f_RO\n"
                "• [2] Momento Angular Espín: I(∂tω+u·∇ω) = γΔω+κ∇(∇·ω)-4μrω+2μr(∇×u)\n"
                "• [3] Fuerza Forzante Topológica: f_RO = 2νr(∇×ω_vib)+(∇htopo)×u-β∇u+k(d0/d)²r^\n"
                "• [4] Onda Retrocausal ECCA: Ψ_Retro(t0) = Λ_Aegis ∫ D[γ] Φ_adv exp(iS_geom/ħ)\n"
                "• [5] Acción Geónica: S_geom = ∮_∂M (R_geom + Holonomía) √(-g) dΩ\n"
                "• [6] Índice Espectral SPI: Ψ_em = α·Var_norm + β·Δ_norm + γ·S_Shannon\n"
                "• [7] Sincronización Lamport: L(e') = max(L(e), L_recv) + 1\n"
                "──────────────────────────────────────────────\n"
                f"• Reloj Lamport: L = {1048 + frame}  |  Sintropía de Turno: S = {0.78 + 0.15*math.sin(t):.3f}\n"
                "• Blindaje Kármico: CONSTANTE AEGIS ACTIVA (100% INVIOLABLE)"
            )
            ax4.text(0.02, 0.5, info_hud, fontsize=6.8, color="#e0f7fa", family="monospace", linespacing=1.35, va="center",
                     bbox=dict(boxstyle="round,pad=0.5", facecolor="#071026", edgecolor="#1f3b60"))

        ani = animation.FuncAnimation(fig, update, frames=self.total_frames, blit=False)
        ani.save(str(mp4_path), writer="ffmpeg", fps=self.fps, dpi=100, extra_args=["-vcodec", "libx264", "-pix_fmt", "yuv420p"])
        ani.save(str(gif_path), writer="pillow", fps=15)
        plt.close(fig)

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                mp4_path,
                title="Compendio Unificado ChronoVision Synthesis",
                formula=r"\mathcal{S}_{\text{geom}} = \int_{\mathcal{M}} (R + \mathcal{L}_{\text{matter}}) \sqrt{-g} d^4 x",
                domain="Física Teórica & Causalidad Sintrópica Multiescala"
            )
        except Exception as e_audio:
            print(f"[TARDIS-AUDIO-WARN] No se pudo inyectar audio en Video 3: {e_audio}")

        # Copiar a artefactos
        shutil.copy2(mp4_path, ARTIFACT_DIR / mp4_path.name)
        shutil.copy2(gif_path, ARTIFACT_DIR / gif_path.name)
        print(f"[TARDIS-ANIMATOR] Video 3 generado: {mp4_path} y GIF: {gif_path}")
        return mp4_path, gif_path

    def render_all(self) -> Dict[str, Tuple[Path, Path]]:
        """Sintetiza todos los videos de fórmulas del sistema."""
        v1 = self.render_cosmic_fluid_video()
        v2 = self.render_retrocausal_wave_video()
        v3 = self.render_master_chronovision_synthesis()
        return {
            "cosmic_fluid": v1,
            "retrocausal": v2,
            "master_synthesis": v3
        }


def main():
    animator = TardisFormulaAnimator(fps=24, duration_sec=5)
    results = animator.render_all()
    print("\n=== RESUMEN DE GENERACIÓN CINEMÁTICA TARDIS ===")
    for k, (mp4, gif) in results.items():
        print(f"[{k}]")
        print(f"  MP4: {mp4} ({mp4.stat().st_size / 1024:.1f} KB)")
        print(f"  GIF: {gif} ({gif.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
