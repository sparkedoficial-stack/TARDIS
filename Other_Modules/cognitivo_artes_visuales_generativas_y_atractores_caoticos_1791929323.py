"""cognitivo_artes_visuales_generativas_y_atractores_caoticos_1791929323.py
-------------------------------------------------------------------------
Simulador procedural interactivo de atractores caóticos para artes visuales
generativas. Utiliza el atractor de Lorenz como ejemplo y permite exportar
imágenes en PNG y SVG de alta resolución.

Requisitos:
    - numpy
    - matplotlib (backend Agg)
    - pillow (PIL)
"""

import argparse
import os
import sys
from typing import Tuple, List

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

__all__ = ['AttractorSimulator', 'run_simulation']

class AttractorSimulator:
    """Simulador del atractor de Lorenz.

    Parámetros
    ----------
    sigma, rho, beta : float
        Parámetros clásicos del sistema de Lorenz.
    dt : float
        Paso de integración.
    steps : int
        Número de iteraciones.
    initial : Tuple[float, float, float]
        Condición inicial del sistema.
    """

    def __init__(self,
                 sigma: float = 10.0,
                 rho: float = 28.0,
                 beta: float = 8.0 / 3.0,
                 dt: float = 0.01,
                 steps: int = 50000,
                 initial: Tuple[float, float, float] = (0.0, 1.0, 1.05)):
        self.sigma = sigma
        self.rho = rho
        self.beta = beta
        self.dt = dt
        self.steps = steps
        self.initial = np.array(initial, dtype=float)

    def simulate(self) -> np.ndarray:
        """Ejecuta la integración numérica del atractor.

        Returns
        -------
        np.ndarray
            Array de forma (steps, 3) con la trayectoria.
        """
        traj = np.empty((self.steps, 3), dtype=float)
        x, y, z = self.initial
        for i in range(self.steps):
            dx = self.sigma * (y - x)
            dy = x * (self.rho - z) - y
            dz = x * y - self.beta * z
            x += dx * self.dt
            y += dy * self.dt
            z += dz * self.dt
            traj[i] = (x, y, z)
        return traj

    def render(self,
               trajectory: np.ndarray,
               output_path: str,
               dpi: int = 300,
               linewidth: float = 0.5,
               colormap: str = 'viridis',
               background: str = 'black') -> None:
        """Renderiza la trayectoria en una imagen.

        Parámetros
        ----------
        trajectory : np.ndarray
            Resultado de ``simulate``.
        output_path : str
            Ruta completa del archivo a guardar (debe terminar en .png o .svg).
        dpi : int
            Resolución en puntos por pulgada.
        linewidth : float
            Grosor de la línea.
        colormap : str
            Nombre del colormap de Matplotlib.
        background : str
            Color de fondo de la figura.
        """
        fig = plt.figure(figsize=(8, 8), facecolor=background)
        ax = fig.add_subplot(111, projection='3d')
        ax.set_axis_off()

        # Normalizamos para colorear según el tiempo
        t = np.linspace(0, 1, trajectory.shape[0])
        points = trajectory
        ax.plot(points[:, 0], points[:, 1], points[:, 2],
                lw=linewidth, c='white' if background == 'black' else 'black')

        # Aplicamos colormap mediante scatter para mayor control visual
        sc = ax.scatter(points[:, 0], points[:, 1], points[:, 2],
                        c=t, cmap=colormap, s=0.1, depthshade=False)

        plt.tight_layout(pad=0)
        fig.savefig(output_path, dpi=dpi, transparent=False, bbox_inches='tight')
        plt.close(fig)

def run_simulation(output_dir: str = '.', *,
                   steps: int = 50000,
                   dt: float = 0.01,
                   seed: int = 42,
                   fmt: str = 'png') -> str:
    """Ejecuta una simulación completa y guarda la imagen.

    Parámetros
    ----------
    output_dir : str
        Directorio donde se guardará la imagen.
    steps, dt, seed : parámetros del simulador.
    fmt : 'png' o 'svg'.

    Returns
    -------
    str
        Ruta completa del archivo generado.
    """
    np.random.seed(seed)
    sim = AttractorSimulator(steps=steps, dt=dt)
    traj = sim.simulate()
    filename = f"lorenz_attractor_{steps}_{seed}.{fmt}"
    out_path = os.path.join(output_dir, filename)
    sim.render(traj, out_path, dpi=300, linewidth=0.3, colormap='plasma')
    return out_path

def _parse_args(argv: List[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Simulador de atractor caótico y exportador visual.')
    parser.add_argument('--steps', type=int, default=50000,
                        help='Número de pasos de integración.')
    parser.add_argument('--dt', type=float, default=0.01,
                        help='Tamaño del paso de tiempo.')
    parser.add_argument('--seed', type=int, default=42,
                        help='Semilla aleatoria para reproducibilidad.')
    parser.add_argument('--fmt', choices=['png', 'svg'], default='png',
                        help='Formato de salida de la imagen.')
    parser.add_argument('--out-dir', default='.',
                        help='Directorio donde guardar la imagen.')
    parser.add_argument('--demo', action='store_true',
                        help='Ejecuta una demostración rápida y guarda la imagen.')
    return parser.parse_args(argv)

def main() -> None:
    args = _parse_args()
    if args.demo:
        try:
            out_file = run_simulation(
                output_dir=args.out_dir,
                steps=args.steps,
                dt=args.dt,
                seed=args.seed,
                fmt=args.fmt
            )
            print(f"Imagen generada: {out_file}")
        except Exception as exc:
            print(f"Error durante la generación: {exc}", file=sys.stderr)
            sys.exit(1)

if __name__ == '__main__':
    main()
