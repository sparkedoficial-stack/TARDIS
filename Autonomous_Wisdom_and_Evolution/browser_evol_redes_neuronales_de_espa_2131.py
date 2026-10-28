"""
browser_evol_redes_neuronales_de_espa_2131.py - Neuroevolución ligera en CPU
===========================================================================
Módulo auto-sintetizado (stub vacío reparado el 2026-10-27 por TARDIS).
Implementa búsqueda evolutiva (1+lambda) sobre los pesos de una red neuronal
MLP mínima, sin dependencias externas más allá de NumPy.

Uso como librería:
    from browser_evol_redes_neuronales_de_espa_2131 import BrowserEvolRedesNeuronales
    print(BrowserEvolRedesNeuronales().run(generations=40))

Uso como CLI:
    python3 browser_evol_redes_neuronales_de_espa_2131.py --generations 40
"""

import argparse
import time

import numpy as np


class BrowserEvolRedesNeuronales:
    """Evoluciona los pesos de un MLP (2-6-1) para aproximar una función objetivo."""

    name = "browser_evol_redes_neuronales"
    description = "Neuroevolución (1+lambda) de un MLP mínimo sobre CPU."

    def __init__(self, seed: int = 42, hidden: int = 6, population: int = 24, sigma: float = 0.35):
        self.seed = seed
        self.hidden = hidden
        self.population = population
        self.sigma = sigma
        self.rng = np.random.default_rng(seed)
        # Dominio y objetivo: y = sin(2x) * cos(x/2) en [-3, 3]
        raw = np.linspace(-3.0, 3.0, 96).reshape(-1, 1)
        # Dos entradas: x normalizada y su armónico (base de Fourier mínima)
        self.x = np.hstack([raw / 3.0, np.sin(raw)])
        self.y = np.sin(2 * raw) * np.cos(raw / 2)
        self.shape = (2, hidden, hidden, 1)

    def _unpack(self, flat: np.ndarray):
        i = 0
        w1 = flat[i:i + 2 * self.hidden].reshape(2, self.hidden); i += 2 * self.hidden
        b1 = flat[i:i + self.hidden]; i += self.hidden
        w2 = flat[i:i + self.hidden * self.hidden].reshape(self.hidden, self.hidden); i += self.hidden ** 2
        b2 = flat[i:i + self.hidden]; i += self.hidden
        w3 = flat[i:i + self.hidden].reshape(self.hidden, 1); i += self.hidden
        b3 = flat[i:i + 1]
        return w1, b1, w2, b2, w3, b3

    def _forward(self, flat: np.ndarray) -> np.ndarray:
        w1, b1, w2, b2, w3, b3 = self._unpack(flat)
        h1 = np.tanh(self.x @ w1 + b1)
        h2 = np.tanh(h1 @ w2 + b2)
        return h2 @ w3 + b3

    def fitness(self, flat: np.ndarray) -> float:
        """Error cuadrático medio invertido (mayor es mejor)."""
        pred = self._forward(flat)
        return float(-np.mean((pred - self.y) ** 2))

    def run(self, generations: int = 60, patience: int = 15, target: float = -1e-3):
        """Ejecuta la neuroevolución y devuelve métricas del mejor individuo."""
        t0 = time.time()
        dim = 2 * self.hidden + self.hidden + self.hidden ** 2 + self.hidden + self.hidden + 1
        best = self.rng.normal(0, 0.5, dim)
        best_fit = self.fitness(best)
        history = [best_fit]
        stale = 0
        generation = 0

        for generation in range(1, generations + 1):
            candidates = best + self.rng.normal(0, self.sigma, (self.population, dim))
            fits = np.array([self.fitness(c) for c in candidates])
            idx = int(np.argmax(fits))
            if fits[idx] > best_fit:
                best, best_fit = candidates[idx], float(fits[idx])
                stale = 0
            else:
                stale += 1
                self.sigma *= 0.97  # enfriamiento adaptativo
            history.append(best_fit)
            if best_fit >= target or stale >= patience:
                break

        return {
            "status": "ok",
            "generaciones": generation,
            "fitness": round(best_fit, 8),
            "mse": round(-best_fit, 8),
            "sigma_final": round(self.sigma, 5),
            "elapsed_s": round(time.time() - t0, 3),
            "historial": [round(h, 6) for h in history[-8:]],
            "pesos": best.tolist(),
        }

    def execute(self, **kwargs):
        return self.run(**kwargs)


def main():
    parser = argparse.ArgumentParser(description="Neuroevolución ligera (MLP 2-6-1) en CPU")
    parser.add_argument("--generations", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--population", type=int, default=24)
    args = parser.parse_args()
    out = BrowserEvolRedesNeuronales(seed=args.seed, population=args.population).run(
        generations=args.generations
    )
    out.pop("pesos", None)
    print(f"[NEUROEVOLUCION] {out}")


if __name__ == "__main__":
    main()
