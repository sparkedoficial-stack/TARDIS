"""
cognitivo_artes_visuales_generativas_y_atractores_caoticos_1791929323.py - Generador Autónomo de Arte Computacional Sintrópico
=====================================================================
Módulo auto-sintetizado para el estudio de 'artes visuales generativas y atractores caoticos'.
Produce obras de arte generativo de alta resolución basadas en atractores caóticos
y campos de potencial escalar.
"""

import os
import sys
import argparse
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

OUTPUT_DIR = Path.home() / "Escritorio" / "TARDIS_ARTE_GENERATIVO"

def generate_chaotic_art_canvas(width: int = 1920, height: int = 1080, steps: int = 250000, seed: int = 42):
    """Genera una pieza de arte procedural basada en dinámica caótica no lineal."""
    np.random.seed(seed)
    
    # Parámetros del atractor tipo Clifford / de Jong
    a, b, c, d = -1.4, 1.6, 1.0, 0.7
    
    x = np.zeros(steps, dtype=np.float64)
    y = np.zeros(steps, dtype=np.float64)
    
    x[0], y[0] = 0.1, 0.1
    for i in range(1, steps):
        x[i] = np.sin(a * y[i-1]) + c * np.cos(a * x[i-1])
        y[i] = np.cos(b * x[i-1]) + d * np.sin(b * y[i-1])
        
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    fig.patch.set_facecolor('#040711')
    ax.set_facecolor('#040711')
    
    # Mapeo de color basado en densidad y distancia radial
    r = np.sqrt(x**2 + y**2)
    colors = plt.cm.magma(r / (r.max() + 1e-6))
    
    ax.scatter(x, y, c=colors, s=0.08, alpha=0.35, edgecolors='none')
    ax.axis('off')
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    
    output_filename = f"obra_arte_{int(time.time())}.png"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / output_filename
    plt.savefig(output_path, facecolor=fig.get_facecolor(), edgecolor='none', bbox_inches='tight', pad_inches=0)
    plt.close()
    
    return str(output_path)


class CognitivoArtesVisuales:
    """Interfaz Master Hub: arte generativo sintrópico bajo demanda."""

    name = "cognitivo_artes_visuales"
    description = "Genera obras de arte computacional con atractores caóticos (Clifford/de Jong)."

    def run(self, steps: int = 150000, seed: int = 42):
        t0 = time.time()
        out = generate_chaotic_art_canvas(steps=steps, seed=seed)
        return {
            "status": "ok",
            "obra": out,
            "pasos": steps,
            "semilla": seed,
            "elapsed_s": round(time.time() - t0, 3),
        }

    def execute(self, **kwargs):
        return self.run(**kwargs)

def main():
    parser = argparse.ArgumentParser(description="Generador de Arte y Simulación artes visuales generativas y atractores caoticos")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demo y guardar obra de arte")
    parser.add_argument("--steps", type=int, default=150000, help="Pasos de simulación")
    args = parser.parse_args()
    
    print(f"[COGNITIVO-ARTE] Generando simulación estética para: 'artes visuales generativas y atractores caoticos'")
    t0 = time.time()
    out = generate_chaotic_art_canvas(steps=args.steps)
    elapsed = round(time.time() - t0, 3)
    print(f"[EXITO] Obra de arte generada: {out} en {elapsed}s")

if __name__ == '__main__':
    main()
