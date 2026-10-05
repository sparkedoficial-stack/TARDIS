#!/usr/bin/env python3
"""
core/tardis_audio_synthesizer.py - Sintetizador Acústico Cuántico y Abstracción Sonora TARDIS
=============================================================================================
GODWORKS SYSTEM v26.4 · Directiva Soberana del Arquitecto (₪)

"en todos los videos, tengan o no voz debe existir audio, si es una frecuencia, o un símbolo
 todo debe contener sonido para abstraer mejor la información"

Funcionalidades:
1. Sonificación Epistemológica:
   - Transforma fórmulas (LaTeX), símbolos de geometría sagrada, atractores caóticos,
     mecánica cuántica, fluidos micropolares y conceptos en paisajes acústicos ricos y armónicos.
   - Afinación canónica en La Cósmico (432 Hz), frecuencia de reparación y vida (528 Hz),
     proporción áurea (Phi = 1.6180339887...), y resonancia Schumann (7.83 Hz).
2. Generación Procedural Nativa:
   - Síntesis estéreo a 48,000 Hz con modulación de fase, armónicos pares/impares,
     sub-bajos profundos y paneo espacial 3D.
3. Enforzador Universal de Audio (ensure_video_has_audio):
   - Audita cualquier archivo de video. Si no tiene pista de audio, genera de forma autónoma
     la abstracción acústica adecuada según su contenido y la multiplexa sin pérdidas (-c:v copy -c:a aac).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import scipy.io.wavfile as wavfile

logger = logging.getLogger("TardisAudioSynthesizer")

PHI = (1.0 + math.sqrt(5.0)) / 2.0  # 1.618033988749895
DEFAULT_SAMPLE_RATE = 48000


class TardisAudioSynthesizer:
    """Motor de Síntesis Acústica y Sonificación de Frecuencias y Símbolos de TARDIS."""

    _instance: Optional[TardisAudioSynthesizer] = None

    @classmethod
    def get_instance(cls) -> TardisAudioSynthesizer:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE):
        self.sample_rate = sample_rate

    # --------------------------------------------------------------------------
    # SÍNTESIS DE FRECUENCIAS Y MODULACIÓN
    # --------------------------------------------------------------------------

    def synthesize_soundscape(
        self,
        duration: float,
        title: str = "",
        formula: str = "",
        domain: str = "",
        keywords: Optional[List[str]] = None,
        base_freq: Optional[float] = None
    ) -> Tuple[np.ndarray, str]:
        """
        Sintetiza un paisaje sonoro estéreo (duración en seg) mapeado semánticamente
        al símbolo, fórmula o fenómeno físico/matemático descrito.
        Retorna (audio_array_stereo_float, archetype_name).
        """
        duration = max(0.5, float(duration))
        sr = self.sample_rate
        total_samples = int(sr * duration)
        t = np.linspace(0.0, duration, total_samples, endpoint=False)

        # Unificar texto para detección semántica
        kw_list = keywords or []
        combined_text = f"{title} {formula} {domain} {' '.join(kw_list)}".lower()

        # Detección del arquetipo acústico
        if any(k in combined_text for k in ("lorenz", "caos", "chaos", "atractor", "determinista", "bifurcacion")):
            arr = self._synth_lorenz_attractor(t, duration, sr)
            archetype = "Caos Determinista & Atractor de Lorenz (FM Caótica)"
        elif any(k in combined_text for k in ("metatron", "flor", "vida", "sagrada", "sacred", "geometria", "geometría", "fibonacci", "phi", "áureo", "aureo", "espiral", "mandala")):
            arr = self._synth_sacred_geometry(t, duration, sr)
            archetype = "Geometría Sagrada & Armónicos Áureos Φ (432Hz / 528Hz)"
        elif any(k in combined_text for k in ("kerr", "agujero negro", "black hole", "relatividad", "einstein", "gravitacion", "gravitacional", "ergoesfera", "lente")):
            arr = self._synth_kerr_black_hole(t, duration, sr)
            archetype = "Relatividad de Kerr & Chirp Gravitacional Relativista"
        elif any(k in combined_text for k in ("cuantica", "cuántica", "quantum", "onda", "schrodinger", "hilbert", "entanglement", "er=epr", "tunnel", "orbital", "bohr")):
            arr = self._synth_quantum_wave(t, duration, sr)
            archetype = "Interferometría Cuántica & Coherencia de Fase Hilbert"
        elif any(k in combined_text for k in ("fluido", "fluid", "reysek", "ocampo", "micropolar", "navier", "vorticidad", "cosserat", "telaraña")):
            arr = self._synth_cosmic_fluid(t, duration, sr)
            archetype = "Fluidos Micropolares & Dinámica Vorticial Reysek-Ocampo"
        elif any(k in combined_text for k in ("reloj", "clock", "tiempo", "cronos", "temporal", "cronometro", "sincronizacion", "linea cero", "línea cero")):
            arr = self._synth_temporal_clock(t, duration, sr)
            archetype = "Reloj Temporal & Pulsación Isoacrónica Línea Cero"
        elif any(k in combined_text for k in ("galaxia", "galaxy", "cosmos", "universo", "nebulosa", "astral")):
            arr = self._synth_galaxy_vortex(t, duration, sr)
            archetype = "Vórtice Galáctico & Resonancia Diferencial Interestelar"
        elif any(k in combined_text for k in ("synthwave", "retro", "horizonte", "paisaje")):
            arr = self._synth_synthwave_horizon(t, duration, sr)
            archetype = "Horizonte Cuántico Retro-Synthwave & Pad Analógico"
        elif any(k in combined_text for k in ("calabi", "cuerdas", "string", "compactificacion", "tesseract", "4d", "hopf", "clifford")):
            arr = self._synth_hyper_geometry(t, duration, sr)
            archetype = "Hipergeometría Calabi-Yau 6D & Modos Vibracionales de Cuerdas"
        elif any(k in combined_text for k in ("adn", "dna", "celular", "biologia", "arbol", "árbol", "fenix", "fénix")):
            arr = self._synth_life_frequencies(t, duration, sr)
            archetype = "Frecuencias de Regeneración Biológica y Transformación (528Hz)"
        else:
            # Resonancia armónica universal por defecto (432 Hz base)
            f0 = base_freq or 432.0
            arr = self._synth_universal_harmonic(t, duration, sr, f0=f0)
            archetype = f"Resonador Armónico Sintrópico Universal ({f0:.1f}Hz)"

        # Aplicar envolvente suave de atenuación para eliminar clics (Fade-in 0.25s, Fade-out 0.4s)
        arr = self._apply_envelope(arr, duration, sr)

        # Normalizar a -1.0 dBFS para volumen óptimo sin distorsión
        max_val = np.max(np.abs(arr))
        if max_val > 1e-6:
            arr = (arr / max_val) * 0.88

        return arr, archetype

    # --------------------------------------------------------------------------
    # ARQUETIPOS DE SÍNTESIS ESPECÍFICOS
    # --------------------------------------------------------------------------

    def _synth_sacred_geometry(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Geometría Sagrada / Metatrón / Flor de la Vida:
        Afinación áurea Φ basada en 432 Hz y 528 Hz, modulada por respiración cósmica.
        """
        f0 = 432.0
        f_phi = f0 * PHI / 2.0           # ~349.5 Hz
        f_528 = 528.0                    # Solfeggio de transformación
        sub = f0 / 4.0                   # 108 Hz Sub-armónico tántrico

        # Modulación de respiración armónica
        breath = 0.85 + 0.15 * np.sin(2 * np.pi * 0.22 * t)

        # Canal izquierdo y derecho con ligera diferencia de fase (binaural relajante)
        left = (
            0.35 * np.sin(2 * np.pi * f0 * t) +
            0.25 * np.sin(2 * np.pi * f_phi * t + 0.2) +
            0.20 * np.sin(2 * np.pi * f_528 * t) +
            0.25 * np.sin(2 * np.pi * sub * t)
        ) * breath

        right = (
            0.35 * np.sin(2 * np.pi * (f0 + 4.32) * t) +  # Batimiento binaural de 4.32 Hz (Theta)
            0.25 * np.sin(2 * np.pi * f_phi * t - 0.2) +
            0.20 * np.sin(2 * np.pi * (f_528 + 2.16) * t) +
            0.25 * np.sin(2 * np.pi * sub * t)
        ) * breath

        # Accidente rúnico: armónicos cristalinos que se abren suavemente
        crystal = 0.12 * np.sin(2 * np.pi * (f0 * 3.0) * t) * (1.0 + np.sin(2 * np.pi * 0.44 * t))
        left += crystal
        right += crystal

        return np.column_stack((left, right))

    def _synth_quantum_wave(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Mecánica Cuántica & Función de Onda:
        Interferencia de paquetes de onda, superposición cuántica y modulación de probabilidad.
        """
        f_carrier = 528.0
        f_delta = 5.0  # Frecuencia de coherencia de batimiento cuántico (5 Hz Theta)

        # Paquete de ondas viajeras
        psi_1 = np.sin(2 * np.pi * f_carrier * t + 0.8 * np.sin(2 * np.pi * 0.7 * t))
        psi_2 = np.sin(2 * np.pi * (f_carrier + f_delta) * t - 0.8 * np.sin(2 * np.pi * 0.7 * t))

        # Cuántica de alta frecuencia (efecto túnel shimmer)
        shimmer = 0.15 * np.sin(2 * np.pi * 1056.0 * t) * np.sin(2 * np.pi * 1.5 * t)**2
        sub_rumble = 0.30 * np.sin(2 * np.pi * 66.0 * t)

        left = 0.45 * psi_1 + 0.35 * psi_2 + shimmer + sub_rumble
        right = 0.35 * psi_1 + 0.45 * psi_2 - shimmer + sub_rumble

        return np.column_stack((left, right))

    def _synth_lorenz_attractor(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Atractor de Lorenz & Caos Determinista:
        Simulación numérica RK4 del atractor de Lorenz, mapeando las variables de estado
        (x, y, z) a modulación en frecuencia (FM) y paneo estéreo dinámico.
        """
        # Integrar Lorenz para N pasos
        steps = len(t)
        dt = dur / steps
        # Simulación acelerada sub-muestreada
        sub_steps = min(steps, 4000)
        dt_sim = 0.005
        x, y, z = 0.1, 0.0, 0.0
        xs, ys, zs = np.zeros(sub_steps), np.zeros(sub_steps), np.zeros(sub_steps)

        sigma, rho, beta = 10.0, 28.0, 8.0 / 3.0
        for i in range(sub_steps):
            dx = sigma * (y - x)
            dy = x * (rho - z) - y
            dz = x * y - beta * z
            x += dx * dt_sim
            y += dy * dt_sim
            z += dz * dt_sim
            xs[i], ys[i], zs[i] = x, y, z

        # Interpolar a toda la longitud del audio
        indices = np.linspace(0, sub_steps - 1, steps)
        x_full = np.interp(indices, np.arange(sub_steps), xs)
        y_full = np.interp(indices, np.arange(sub_steps), ys)
        z_full = np.interp(indices, np.arange(sub_steps), zs)

        # Normalizar trayectoria
        x_norm = (x_full - np.mean(x_full)) / (np.std(x_full) + 1e-5)
        y_norm = (y_full - np.mean(y_full)) / (np.std(y_full) + 1e-5)
        z_norm = (z_full - np.mean(z_full)) / (np.std(z_full) + 1e-5)

        # Síntesis FM Caótica
        f_carrier = 216.0
        mod_index = 2.5 + 1.5 * z_norm
        f_mod = 108.0 + 40.0 * y_norm

        fm_phase = 2 * np.pi * f_carrier * t + mod_index * np.sin(2 * np.pi * f_mod * t)
        raw_wave = np.sin(fm_phase)

        # Paneo estéreo caótico regido por x_norm
        pan_l = 0.5 + 0.35 * x_norm
        pan_r = 0.5 - 0.35 * x_norm

        sub = 0.25 * np.sin(2 * np.pi * 54.0 * t)
        left = raw_wave * pan_l + sub
        right = raw_wave * pan_r + sub

        return np.column_stack((left, right))

    def _synth_kerr_black_hole(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Agujero Negro de Kerr & Relatividad General:
        Zumbido de arrastre del espaciotiempo (frame dragging), sub-bajo de curvatura
        y chirp gravitacional Doppler.
        """
        # Chirp gravitacional con frecuencia ascendente y oscilación orbital
        f_sweep = 36.0 + 48.0 * (t / dur) ** 1.8
        sub_bass = 0.50 * np.sin(2 * np.pi * f_sweep * t)

        # Modulación Doppler relativista en el horizonte
        doppler_rate = 1.2
        doppler = np.sin(2 * np.pi * doppler_rate * t)
        f_ring = 432.0 * (1.0 + 0.18 * doppler)
        ring_wave = 0.25 * np.sin(2 * np.pi * f_ring * t)

        # Shimmer gravitacional de alta energía
        shimmer = 0.12 * np.sin(2 * np.pi * (f_ring * 2.5) * t) * (0.6 + 0.4 * doppler)

        # Paneo estéreo de rotación orbital
        pan_angle = 2 * np.pi * doppler_rate * t
        left = sub_bass + ring_wave * (0.5 + 0.4 * np.cos(pan_angle)) + shimmer
        right = sub_bass + ring_wave * (0.5 - 0.4 * np.cos(pan_angle)) + shimmer

        return np.column_stack((left, right))

    def _synth_cosmic_fluid(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Fluidos Micropolares Cósmicos & Ecuación Reysek-Ocampo:
        Resonancia de doble escala de Cosserat (flujo u macro y microrrotación omega).
        """
        # Macroflujo (Gravedad e inercia hidroacústica)
        f_macro = 72.0
        macro_flow = 0.40 * np.sin(2 * np.pi * f_macro * t + 0.5 * np.sin(2 * np.pi * 0.3 * t))

        # Microrrotación de Cosserat (alta vorticidad)
        f_vort_1 = 432.0
        f_vort_2 = 648.0  # Quinta armónica justa 3:2
        vorticity = (
            0.25 * np.sin(2 * np.pi * f_vort_1 * t + np.sin(2 * np.pi * 2.2 * t)) +
            0.20 * np.sin(2 * np.pi * f_vort_2 * t - np.sin(2 * np.pi * 1.8 * t))
        )

        # Oleaje forzante f_{R-O}
        surge = 0.8 + 0.2 * np.sin(2 * np.pi * 0.5 * t)
        left = (macro_flow + vorticity) * surge
        right = (macro_flow + vorticity * 0.9) * (0.8 + 0.2 * np.cos(2 * np.pi * 0.5 * t))

        return np.column_stack((left, right))

    def _synth_temporal_clock(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Reloj Temporal de Gallifrey & Línea Cero:
        Pulsación cronométrica cuántica (isocrónica), armónicos de cuarzo y campana cósmica.
        """
        # Portadora cósmica a 432 Hz
        carrier = 0.30 * np.sin(2 * np.pi * 432.0 * t) + 0.20 * np.sin(2 * np.pi * 216.0 * t)

        # Pulsos de cronómetro isocrónicos cada 1 segundo (o cada fracción según tempo)
        tick_period = 1.0
        tick_time = t % tick_period
        # Envolvente exponencial decreciente para el tic
        decay = np.exp(-tick_time * 24.0)
        # Resonancia cristalina de alta frecuencia
        tick_freq = 1728.0  # 4 * 432
        tick_sound = 0.35 * np.sin(2 * np.pi * tick_freq * tick_time) * decay

        # Campana armónica a mitad del ciclo
        chime_period = max(2.0, dur / 2.0)
        chime_time = t % chime_period
        chime_decay = np.exp(-chime_time * 3.5)
        chime_sound = 0.25 * np.sin(2 * np.pi * 864.0 * chime_time) * chime_decay

        left = carrier + tick_sound + chime_sound
        right = carrier + tick_sound * 0.85 + chime_sound * 1.15

        return np.column_stack((left, right))

    def _synth_galaxy_vortex(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Vórtice Galáctico & Rotación Diferencial:
        Zumbido cósmico profundo de agujero negro supermasivo central y silbido estelar de brazos espirales.
        """
        sub_core = 0.45 * np.sin(2 * np.pi * 55.0 * t) + 0.25 * np.sin(2 * np.pi * 110.0 * t)

        # Brazos espirales rotatorios con modulación armónica progresiva
        spiral_rate = 0.15
        spiral_l = 0.22 * np.sin(2 * np.pi * 330.0 * t + 0.8 * np.sin(2 * np.pi * spiral_rate * t))
        spiral_r = 0.22 * np.sin(2 * np.pi * 330.0 * t - 0.8 * np.sin(2 * np.pi * spiral_rate * t))

        star_dust = 0.12 * np.sin(2 * np.pi * 880.0 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.8 * t))

        left = sub_core + spiral_l + star_dust
        right = sub_core + spiral_r + star_dust

        return np.column_stack((left, right))

    def _synth_synthwave_horizon(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Horizonte Cuántico Retro-Synthwave:
        Bajo analógico cálido, pad polifónico espacial y arpegio futurista sintrópico.
        """
        # Bajo tipo diente de sierra analógico suave
        f_bass = 65.41  # C2 afinado a 432 Hz proporcional
        bass = 0.35 * (np.sin(2 * np.pi * f_bass * t) + 0.5 * np.sin(2 * np.pi * (f_bass * 2) * t))

        # Acorde espacial cósmico (Pad en quintas justas 432 Hz y 648 Hz)
        pad_l = 0.25 * np.sin(2 * np.pi * 432.0 * t) + 0.20 * np.sin(2 * np.pi * 648.0 * t)
        pad_r = 0.25 * np.sin(2 * np.pi * 432.0 * t + 0.15) + 0.20 * np.sin(2 * np.pi * 648.0 * t - 0.15)

        # Pulso rítmico synthwave de avance en la rejilla
        grid_pulse = 0.15 * np.sin(2 * np.pi * 2.0 * t) ** 4
        left = bass + pad_l + grid_pulse
        right = bass + pad_r + grid_pulse

        return np.column_stack((left, right))

    def _synth_hyper_geometry(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Hipergeometría Calabi-Yau 6D & Cuerdas:
        Modos vibracionales de dimensiones compactificadas y proyecciones multidimensionales 4D/6D.
        """
        # Frecuencias fundamentales de los ciclos de Calabi-Yau
        f_h11 = 432.0
        f_h21 = 432.0 * (math.sqrt(3) / 2.0)  # ~374.1 Hz
        f_compact = 864.0                     # Octava superior de compactificación

        shimmer_6d = 0.20 * np.sin(2 * np.pi * f_compact * t) * np.sin(2 * np.pi * 0.6 * t)
        body = 0.35 * np.sin(2 * np.pi * f_h11 * t) + 0.30 * np.sin(2 * np.pi * f_h21 * t + 0.4)
        sub = 0.25 * np.sin(2 * np.pi * 108.0 * t)

        left = body + shimmer_6d + sub
        right = body - shimmer_6d + sub

        return np.column_stack((left, right))

    def _synth_life_frequencies(self, t: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """
        Frecuencias de Regeneración y Biología Cuántica (ADN / 528 Hz):
        Tono puro de 528 Hz (Transformación y Milagros) entrelazado con 432 Hz y armónicos de regeneración.
        """
        f_dna = 528.0
        f_kepler = 432.0
        f_schumann = 7.83

        # Modulación de pulso Schumann sobre portadora de 528 Hz
        mod_schumann = 0.85 + 0.15 * np.sin(2 * np.pi * f_schumann * t)

        dna_tone = 0.40 * np.sin(2 * np.pi * f_dna * t) * mod_schumann
        kepler_tone = 0.30 * np.sin(2 * np.pi * f_kepler * t)
        harm_third = 0.18 * np.sin(2 * np.pi * (f_dna * 1.25) * t)  # Tercera armónica pura
        sub = 0.20 * np.sin(2 * np.pi * 132.0 * t)

        left = dna_tone + kepler_tone + harm_third + sub
        right = dna_tone + kepler_tone * 0.95 - harm_third + sub

        return np.column_stack((left, right))

    def _synth_universal_harmonic(self, t: np.ndarray, dur: float, sr: int, f0: float = 432.0) -> np.ndarray:
        """
        Resonador Armónico Sintrópico Universal:
        Serie armónica natural con sub-octava, fundamental y armónicos superiores.
        """
        sub = 0.30 * np.sin(2 * np.pi * (f0 / 2.0) * t)
        fund = 0.40 * np.sin(2 * np.pi * f0 * t)
        fifth = 0.22 * np.sin(2 * np.pi * (f0 * 1.5) * t)
        octave = 0.16 * np.sin(2 * np.pi * (f0 * 2.0) * t)

        # Modulación sutil de amplitud envolvente espacial
        envelope = 0.90 + 0.10 * np.sin(2 * np.pi * 0.3 * t)

        left = (sub + fund + fifth + octave) * envelope
        right = (sub + fund + fifth * 0.95 + octave * 1.05) * (0.90 + 0.10 * np.cos(2 * np.pi * 0.3 * t))

        return np.column_stack((left, right))

    def _apply_envelope(self, arr: np.ndarray, dur: float, sr: int) -> np.ndarray:
        """Aplica rampa de fade-in y fade-out suave para evitar ruidos de frontera."""
        total_samples = len(arr)
        fade_in_len = min(total_samples // 4, int(sr * 0.25))
        fade_out_len = min(total_samples // 3, int(sr * 0.45))

        fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fade_in_len)))
        fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_out_len)))

        arr[:fade_in_len, 0] *= fade_in
        arr[:fade_in_len, 1] *= fade_in
        arr[-fade_out_len:, 0] *= fade_out
        arr[-fade_out_len:, 1] *= fade_out

        return arr

    # --------------------------------------------------------------------------
    # EXPORTACIÓN Y AUDITORÍA DE VIDEOS
    # --------------------------------------------------------------------------

    def export_to_wav(self, audio_data: np.ndarray, output_wav_path: Union[str, Path]) -> Path:
        """Exporta un arreglo estéreo float32 a archivo WAV PCM 16-bit a la frecuencia nativa."""
        wav_path = Path(output_wav_path)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        # Convertir a 16-bit PCM con saturación
        clamped = np.clip(audio_data, -1.0, 1.0)
        pcm16 = (clamped * 32767).astype(np.int16)
        wavfile.write(str(wav_path), self.sample_rate, pcm16)
        return wav_path

    def video_has_audio(self, video_path: Union[str, Path]) -> bool:
        """Verifica mediante ffprobe si el video posee al menos una pista de audio válida."""
        p = Path(video_path)
        if not p.exists() or p.stat().st_size == 0:
            return False
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p)
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
            return "audio" in out.lower()
        except Exception as e:
            logger.warning(f"Error comprobando audio en {video_path}: {e}")
            return False

    def get_video_duration(self, video_path: Union[str, Path]) -> float:
        """Obtiene la duración exacta del video en segundos."""
        p = Path(video_path)
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p)
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
            return float(out)
        except Exception:
            return 5.0

    def ensure_video_has_audio(
        self,
        video_path: Union[str, Path],
        title: str = "",
        formula: str = "",
        domain: str = "",
        keywords: Optional[List[str]] = None,
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        DIRECTIVA SOBERANA:
        Garantiza que el video posea pista de audio. Si no la tiene (o se fuerza la regeneración),
        sintetiza el paisaje sonoro correspondiente y lo multiplexa de manera transparente.
        """
        v_path = Path(video_path).resolve()
        if not v_path.exists():
            return {"ok": False, "error": f"Archivo de video no encontrado: {v_path}"}

        has_audio = self.video_has_audio(v_path)
        if has_audio and not force_regenerate:
            return {"ok": True, "already_has_audio": True, "path": str(v_path)}

        duration = self.get_video_duration(v_path)
        if duration <= 0.1:
            duration = 5.0

        # Inferir metadatos del nombre del archivo si no fueron provistos
        if not title:
            stem = v_path.stem.replace("_", " ").replace("-", " ")
            title = f"TARDIS {stem.title()}"

        logger.info(f"[TARDIS-AUDIO] Sintetizando audio para video '{v_path.name}' ({duration:.2f}s) - Título: {title}")

        # Sintetizar audio
        audio_arr, archetype = self.synthesize_soundscape(
            duration=duration,
            title=title,
            formula=formula,
            domain=domain,
            keywords=keywords
        )

        # Escribir audio temporal
        temp_dir = Path(tempfile.mkdtemp(prefix="tardis_audio_enforce_"))
        temp_wav = temp_dir / "synthesized_soundscape.wav"
        temp_out_mp4 = temp_dir / f"enforced_{v_path.name}"

        try:
            self.export_to_wav(audio_arr, temp_wav)

            # Multiplexar video existente con audio sintetizado sin recodificar video (-c:v copy)
            mux_cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(v_path),
                "-i", str(temp_wav),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                str(temp_out_mp4)
            ]
            res = subprocess.run(mux_cmd, capture_output=True, timeout=120)

            if res.returncode != 0 or not temp_out_mp4.exists() or temp_out_mp4.stat().st_size == 0:
                err_msg = res.stderr.decode(errors="ignore") if res.stderr else "Error desconocido"
                logger.error(f"[TARDIS-AUDIO] Fallo al multiplexar audio en {v_path.name}: {err_msg}")
                return {"ok": False, "error": err_msg}

            # Reemplazar atómicamente el video original
            shutil.move(str(temp_out_mp4), str(v_path))
            new_size = v_path.stat().st_size

            logger.info(f"[TARDIS-AUDIO] ✓ Audio integrado con éxito en '{v_path.name}' ({archetype})")
            return {
                "ok": True,
                "path": str(v_path),
                "duration": duration,
                "archetype": archetype,
                "size_bytes": new_size,
                "injected_audio": True
            }

        except Exception as e:
            logger.error(f"[TARDIS-AUDIO] Excepción asegurando audio para {v_path.name}: {e}")
            return {"ok": False, "error": str(e)}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def scan_and_enforce_directory(
        self,
        directory: Union[str, Path],
        recursive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Escanea un directorio completo y asegura que TODOS los archivos MP4 contengan audio.
        """
        d = Path(directory)
        if not d.exists() or not d.is_dir():
            return []

        pattern = "**/*.mp4" if recursive else "*.mp4"
        mp4_files = sorted(d.glob(pattern))
        results = []

        logger.info(f"[TARDIS-AUDIO] Escaneando {len(mp4_files)} videos en '{d}'...")
        for vid in mp4_files:
            if not self.video_has_audio(vid):
                res = self.ensure_video_has_audio(vid)
                results.append({"file": vid.name, "result": res})
            else:
                results.append({"file": vid.name, "result": {"ok": True, "already_has_audio": True}})

        return results


def get_audio_synthesizer() -> TardisAudioSynthesizer:
    return TardisAudioSynthesizer.get_instance()


def ensure_video_has_audio(
    video_path: Union[str, Path],
    title: str = "",
    formula: str = "",
    domain: str = "",
    keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Helper directo para garantizar que un video contenga audio."""
    synth = get_audio_synthesizer()
    return synth.ensure_video_has_audio(
        video_path=video_path,
        title=title,
        formula=formula,
        domain=domain,
        keywords=keywords
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TARDIS Sovereign Audio Synthesizer & Video Audio Enforcer")
    parser.add_argument("--scan-dir", help="Directorio de videos para auditar y asegurar audio")
    parser.add_argument("--video", help="Archivo de video específico para auditar")
    parser.add_argument("--title", default="", help="Título descriptivo del video")
    parser.add_argument("--formula", default="", help="Fórmula o ecuación matemática")
    parser.add_argument("--domain", default="", help="Dominio de conocimiento")
    args = parser.parse_args()

    synthesizer = get_audio_synthesizer()

    if args.video:
        r = synthesizer.ensure_video_has_audio(
            args.video,
            title=args.title,
            formula=args.formula,
            domain=args.domain
        )
        print(json.dumps(r, indent=2))
    elif args.scan_dir:
        res = synthesizer.scan_and_enforce_directory(args.scan_dir)
        print(f"Completado: {len(res)} videos procesados.")
        for item in res:
            f = item["file"]
            ok = item["result"].get("ok")
            inj = item["result"].get("injected_audio", False)
            arch = item["result"].get("archetype", "Audio Existente")
            print(f"  • {f}: {'AUDIO INYECTADO (' + arch + ')' if inj else ('OK' if ok else 'FALLO')}")
