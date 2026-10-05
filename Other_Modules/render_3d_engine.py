"""
core/render_3d_engine.py - Motor Soberano de Mallas y Renderizado 3D
===================================================================
GODWORKS SYSTEM v26.4 - Suite de Geometría Procedural y Proyección Holográfica

Permite al sistema generar, modelar, enseñar y renderizar objetos tridimensionales
complejos (biología, física cuántica, topología, geometría sagrada y superficies matemáticas)
tanto para la interfaz web interactiva (JSON/Canvas) como para canales remotos (renderizado
fotográfico PNG para Telegram y API REST).
"""

from __future__ import annotations

import io
import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Mesh3D:
    name: str
    title: str
    category: str
    description: str
    formula: str = ""
    fun_fact: str = ""
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    faces: List[List[int]] = field(default_factory=list)
    edges: List[Tuple[int, int]] = field(default_factory=list)
    colors: Optional[List[Tuple[int, int, int]]] = None
    node_labels: Optional[Dict[int, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializa la malla para consumo por WebGL / Canvas en el frontend."""
        return {
            "name": self.name,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "formula": self.formula,
            "fun_fact": self.fun_fact,
            "vertex_count": len(self.vertices),
            "face_count": len(self.faces),
            "edge_count": len(self.edges),
            "vertices": self.vertices,
            "faces": self.faces,
            "edges": self.edges,
            "node_labels": self.node_labels or {},
        }


class Render3DEngine:
    """Motor central de generación matemática procedural y renderizado 3D."""

    _instance: Optional[Render3DEngine] = None

    @classmethod
    def get_instance(cls) -> Render3DEngine:
        if cls._instance is None:
            cls._instance = Render3DEngine()
        return cls._instance

    def __init__(self):
        self._catalog_cache: Dict[str, Mesh3D] = {}
        self._init_catalog()

    # --------------------------------------------------------------------------
    # GENERADORES PROCEDURALES DE MODELOS 3D
    # --------------------------------------------------------------------------

    def create_dna_helix(self, turns: int = 3, base_pairs: int = 36, radius: float = 1.2, height: float = 4.0, phase: float = 0.0) -> Mesh3D:
        """Genera una doble hélice de ADN con pares de bases complementarios."""
        vertices: List[Tuple[float, float, float]] = []
        edges: List[Tuple[int, int]] = []
        faces: List[List[int]] = []
        labels: Dict[int, str] = {}

        total_nodes = base_pairs
        dz = height / total_nodes
        dtheta = (turns * 2 * math.pi) / total_nodes

        # Hélices principales (hebra 1 y hebra 2 desfasada 180°)
        for i in range(total_nodes):
            z = (i - total_nodes / 2) * dz
            theta = i * dtheta + phase * 2 * math.pi

            # Hebra 1 (Azúcar-Fosfato)
            x1 = radius * math.cos(theta)
            y1 = radius * math.sin(theta)
            idx1 = len(vertices)
            vertices.append((round(x1, 3), round(y1, 3), round(z, 3)))
            labels[idx1] = "Fosfato-5'"

            # Hebra 2 (Complementaria antiparalela)
            x2 = radius * math.cos(theta + math.pi)
            y2 = radius * math.sin(theta + math.pi)
            idx2 = len(vertices)
            vertices.append((round(x2, 3), round(y2, 3), round(z, 3)))
            labels[idx2] = "Fosfato-3'"

            # Rung / Par de bases central (Adenina-Timina / Guanina-Citosina)
            edges.append((idx1, idx2))

            # Conexión longitudinal de cada hebra
            if i > 0:
                edges.append((idx1 - 2, idx1))
                edges.append((idx2 - 2, idx2))
                # Cara cuadrilateral ligera para relleno sombreado
                faces.append([idx1 - 2, idx1, idx2, idx2 - 2])

        return Mesh3D(
            name="dna_helix",
            title="Doble Hélice de ADN",
            category="Biología & Genética Molecular",
            description="Estructura helicoidal dextrógira del ácido desoxirribonucleico, base de la herencia biológica.",
            formula="x(t) = r\\cos(t), \\; y(t) = r\\sin(t), \\; z(t) = c \\cdot t",
            fun_fact="Si desenrollaras el ADN de todas las células de tu cuerpo, alcanzaría para ir y volver a Plutón.",
            vertices=vertices,
            faces=faces,
            edges=edges,
            node_labels=labels
        )

    def create_bohr_atom(self, electrons: int = 6, rings: int = 3, core_radius: float = 0.45, orbit_radius: float = 1.6, phase: float = 0.0) -> Mesh3D:
        """Genera un átomo de Bohr con núcleo cuántico y electrones en orbitales inclinados."""
        vertices: List[Tuple[float, float, float]] = []
        edges: List[Tuple[int, int]] = []
        faces: List[List[int]] = []
        labels: Dict[int, str] = {}

        # 1. Núcleo central (Protones y Neutrones densos)
        phi = (1 + math.sqrt(5)) / 2
        core_scale = core_radius * 0.7
        core_raw = [
            (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
            (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
            (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1)
        ]
        for idx, (x, y, z) in enumerate(core_raw):
            vertices.append((round(x * core_scale, 3), round(y * core_scale, 3), round(z * core_scale, 3)))
            labels[idx] = "Protón/Neutrón"

        core_faces = [
            [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
            [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
            [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
            [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
        ]
        faces.extend(core_faces)
        for f in core_faces:
            edges.append((f[0], f[1]))
            edges.append((f[1], f[2]))
            edges.append((f[2], f[0]))

        # 2. Orbitales elípticos inclinados con electrones
        pts_per_ring = 24
        ring_rotations = [0.0, math.pi / 3, 2 * math.pi / 3]
        for r_idx, tilt_yaw in enumerate(ring_rotations):
            tilt_pitch = math.pi / 4 * (1 if r_idx % 2 == 0 else -1)
            ring_start = len(vertices)

            for p in range(pts_per_ring):
                ang = (p / pts_per_ring) * 2 * math.pi
                lx = orbit_radius * math.cos(ang)
                ly = orbit_radius * math.sin(ang)
                lz = 0.0

                # Rotación en 3D del plano orbital
                # Rotación pitch
                y1 = ly * math.cos(tilt_pitch) - lz * math.sin(tilt_pitch)
                z1 = ly * math.sin(tilt_pitch) + lz * math.cos(tilt_pitch)
                # Rotación yaw
                x2 = lx * math.cos(tilt_yaw) + z1 * math.sin(tilt_yaw)
                z2 = -lx * math.sin(tilt_yaw) + z1 * math.cos(tilt_yaw)

                v_idx = len(vertices)
                vertices.append((round(x2, 3), round(y1, 3), round(z2, 3)))
                if p > 0:
                    edges.append((v_idx - 1, v_idx))

            edges.append((len(vertices) - 1, ring_start))

            # Añadir electrón en el orbital con velocidad angular diferenciada
            speed_mult = (r_idx + 1) * 1.5
            e_ang = (r_idx * 1.8 + phase * speed_mult * 2 * math.pi) % (2 * math.pi)
            elx = (orbit_radius * 1.02) * math.cos(e_ang)
            ely = (orbit_radius * 1.02) * math.sin(e_ang)
            ey1 = ely * math.cos(tilt_pitch)
            ez1 = ely * math.sin(tilt_pitch)
            ex2 = elx * math.cos(tilt_yaw) + ez1 * math.sin(tilt_yaw)
            ez2 = -elx * math.sin(tilt_yaw) + ez1 * math.cos(tilt_yaw)
            e_idx = len(vertices)
            vertices.append((round(ex2, 3), round(ey1, 3), round(ez2, 3)))
            labels[e_idx] = f"Electrón e⁻ ({r_idx+1})"

        return Mesh3D(
            name="bohr_atom",
            title="Átomo de Bohr & Orbitales Cuánticos",
            category="Física Cuántica & Atómica",
            description="Representación del modelo atómico con orbitales cuantizados e interacción electrodinámica.",
            formula="E_n = -\\frac{13.6 \\text{ eV}}{n^2}, \\; L = n \\hbar",
            fun_fact="El 99.9999999% de un átomo es espacio completamente vacío.",
            vertices=vertices,
            faces=faces,
            edges=list(set(edges)),
            node_labels=labels
        )

    def create_torus(self, R: float = 1.3, r: float = 0.45, seg_u: int = 24, seg_v: int = 14) -> Mesh3D:
        """Genera un toroide cuántico Wheeler-Feynman (Geón Causal)."""
        vertices: List[Tuple[float, float, float]] = []
        faces: List[List[int]] = []
        edges: List[Tuple[int, int]] = []

        for i in range(seg_u):
            u = (i / seg_u) * 2 * math.pi
            cos_u, sin_u = math.cos(u), math.sin(u)
            for j in range(seg_v):
                v = (j / seg_v) * 2 * math.pi
                cos_v, sin_v = math.cos(v), math.sin(v)

                x = (R + r * cos_v) * cos_u
                y = (R + r * cos_v) * sin_u
                z = r * sin_v
                vertices.append((round(x, 3), round(y, 3), round(z, 3)))

        for i in range(seg_u):
            next_i = (i + 1) % seg_u
            for j in range(seg_v):
                next_j = (j + 1) % seg_v
                p1 = i * seg_v + j
                p2 = next_i * seg_v + j
                p3 = next_i * seg_v + next_j
                p4 = i * seg_v + next_j

                faces.append([p1, p2, p3, p4])
                edges.append((p1, p2))
                edges.append((p2, p3))
                edges.append((p3, p4))
                edges.append((p4, p1))

        return Mesh3D(
            name="torus_geon",
            title="Toroide Cuántico Wheeler-Feynman",
            category="Física Teórica & Confinamiento Geón",
            description="Geometría toroidal de auto-confinamiento electromagnético e intercambio simétrico temporal.",
            formula="x(u,v) = (R + r\\cos v)\\cos u, \\; z(u,v) = r\\sin v",
            fun_fact="John Wheeler propuso que la materia y la masa podían ser simplemente ondas electromagnéticas atrapadas en su propio vórtice gravitacional (geones).",
            vertices=vertices,
            faces=faces,
            edges=list(set(edges))
        )

    def create_tesseract_projection(self, angle_4d: float = 0.6) -> Mesh3D:
        """Genera un Tesseract (hipercubo 4D) proyectado en el espacio 3D."""
        # 16 vértices en 4D: (±1, ±1, ±1, ±1)
        raw_4d = []
        for x in (-1, 1):
            for y in (-1, 1):
                for z in (-1, 1):
                    for w in (-1, 1):
                        raw_4d.append([x, y, z, w])

        # Rotación en 4D alrededor del plano XW
        cos_a = math.cos(angle_4d)
        sin_a = math.sin(angle_4d)
        rotated_4d = []
        for x, y, z, w in raw_4d:
            x_rot = x * cos_a - w * sin_a
            w_rot = x * sin_a + w * cos_a
            rotated_4d.append((x_rot, y, z, w_rot))

        # Proyección perspectiva 4D -> 3D
        d = 2.4
        vertices: List[Tuple[float, float, float]] = []
        for x, y, z, w in rotated_4d:
            factor = d / (d - w * 0.45)
            vertices.append((round(x * factor * 0.75, 3), round(y * factor * 0.75, 3), round(z * factor * 0.75, 3)))

        # 32 aristas en 4D: conectar nodos que difieren en solo 1 coordenada
        edges: List[Tuple[int, int]] = []
        for i in range(16):
            for j in range(i + 1, 16):
                diff = sum(1 for c1, c2 in zip(raw_4d[i], raw_4d[j]) if c1 != c2)
                if diff == 1:
                    edges.append((i, j))

        # Caras del hipercubo
        faces = [
            # Cubo exterior
            [0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5],
            # Cubo interior
            [8, 9, 11, 10], [12, 13, 15, 14], [8, 9, 13, 12], [10, 11, 15, 14], [8, 10, 14, 12], [9, 11, 15, 13],
            # Conexiones 4D
            [0, 1, 9, 8], [2, 3, 11, 10], [4, 5, 13, 12], [6, 7, 15, 14]
        ]

        return Mesh3D(
            name="tesseract_4d",
            title="Tesseract (Hipercubo 4D)",
            category="Topología & Geometría Hiperdimensional",
            description="Proyección tridimensional isométrica de un cubo tetradimensional con rotación en el eje XW.",
            formula="V_4 = a^4, \\; \\text{Proyección: } (x,y,z)_{3D} = \\frac{(x,y,z)_{4D}}{d - w}",
            fun_fact="Un hipercubo tiene 16 vértices, 32 aristas, 24 caras cuadradas y 8 células cúbicas.",
            vertices=vertices,
            faces=faces,
            edges=edges
        )

    def create_mobius_strip(self, segs: int = 40, width: float = 0.55, radius: float = 1.3) -> Mesh3D:
        """Genera una cinta de Möbius, superficie no orientable con un solo lado."""
        vertices: List[Tuple[float, float, float]] = []
        faces: List[List[int]] = []
        edges: List[Tuple[int, int]] = []

        for i in range(segs):
            u = (i / segs) * 2 * math.pi
            for v_ratio in (-1.0, 1.0):
                v = v_ratio * (width / 2)
                x = (radius + v * math.cos(u / 2)) * math.cos(u)
                y = (radius + v * math.cos(u / 2)) * math.sin(u)
                z = v * math.sin(u / 2)
                vertices.append((round(x, 3), round(y, 3), round(z, 3)))

        for i in range(segs):
            next_i = (i + 1) % segs
            if i == segs - 1:
                # El giro de 180° invierte los índices en el cierre
                p1 = i * 2
                p2 = i * 2 + 1
                p3 = 0
                p4 = 1
                faces.append([p1, p2, p3, p4])
                edges.extend([(p1, p2), (p2, p3), (p3, p4), (p4, p1)])
            else:
                p1 = i * 2
                p2 = i * 2 + 1
                p3 = next_i * 2 + 1
                p4 = next_i * 2
                faces.append([p1, p2, p3, p4])
                edges.extend([(p1, p2), (p2, p3), (p3, p4), (p4, p1)])

        return Mesh3D(
            name="mobius_strip",
            title="Cinta de Möbius",
            category="Topología Matemática",
            description="Superficie de una sola cara y un solo borde, obtenida al unir los extremos de una tira con una torsión de 180°.",
            formula="x(u,v) = [r + v\\cos(u/2)]\\cos u, \\; z(u,v) = v\\sin(u/2)",
            fun_fact="Si cortas una cinta de Möbius por la mitad a lo largo, no obtienes dos cintas, sino una sola cinta más larga con dos vueltas completas.",
            vertices=vertices,
            faces=faces,
            edges=list(set(edges))
        )

    def create_platonic_solid(self, kind: str = "icosahedron") -> Mesh3D:
        """Genera los sólidos platónicos fundamentales de la geometría clásica y sagrada."""
        kind_l = kind.lower().strip()
        phi = (1 + math.sqrt(5)) / 2

        if kind_l in ("icosahedron", "icosaedro"):
            raw_v = [
                (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
                (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
                (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1)
            ]
            scale = 0.9
            vertices = [(round(x * scale, 3), round(y * scale, 3), round(z * scale, 3)) for x, y, z in raw_v]
            faces = [
                [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
                [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
                [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
                [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
            ]
            title = "Icosaedro Regular (20 Caras)"
            formula = "\\text{Vérts: } 12, \\; \\text{Caras: } 20, \\; \\text{Aristas: } 30"
            fact = "Asociado por Platón al elemento Agua; es la estructura fundamental de la cápside de la mayoría de los virus biológicos."

        elif kind_l in ("octahedron", "octaedro"):
            vertices = [(1.5, 0, 0), (-1.5, 0, 0), (0, 1.5, 0), (0, -1.5, 0), (0, 0, 1.5), (0, 0, -1.5)]
            faces = [
                [0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
                [0, 2, 5], [2, 1, 5], [1, 3, 5], [3, 0, 5]
            ]
            title = "Octaedro Regular (8 Caras)"
            formula = "\\text{Vérts: } 6, \\; \\text{Caras: } 8, \\; \\text{Aristas: } 12"
            fact = "Asociado al elemento Aire; es la base geométrica de la estructura cristalina del diamante y la fluorita."

        elif kind_l in ("dodecahedron", "dodecaedro"):
            raw_v = [
                (-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
                (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1),
                (0, -1/phi, -phi), (0, -1/phi, phi), (0, 1/phi, -phi), (0, 1/phi, phi),
                (-1/phi, -phi, 0), (-1/phi, phi, 0), (1/phi, -phi, 0), (1/phi, phi, 0),
                (-phi, 0, -1/phi), (-phi, 0, 1/phi), (phi, 0, -1/phi), (phi, 0, 1/phi)
            ]
            scale = 0.65
            vertices = [(round(x * scale, 3), round(y * scale, 3), round(z * scale, 3)) for x, y, z in raw_v]
            faces = [
                [0, 8, 10, 2, 16], [0, 16, 17, 1, 12], [0, 12, 14, 4, 8],
                [1, 9, 5, 14, 12], [1, 17, 3, 11, 9], [2, 10, 6, 15, 13],
                [2, 13, 3, 17, 16], [3, 13, 15, 7, 11], [4, 14, 5, 19, 18],
                [4, 18, 6, 10, 8], [5, 9, 11, 7, 19], [6, 18, 19, 7, 15]
            ]
            title = "Dodecaedro Regular (12 Caras Pentagonales)"
            formula = "\\text{Vérts: } 20, \\; \\text{Caras: } 12, \\; \\text{Aristas: } 30"
            fact = "Platón lo asoció al Éter y a la forma del Universo entero; sus proporciones están gobernadas por el número áureo."

        else:  # Cube
            vertices = [
                (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)
            ]
            faces = [
                [0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
                [2, 3, 7, 6], [0, 3, 7, 4], [1, 2, 6, 5]
            ]
            title = "Cubo Regular (Hexaedro)"
            formula = "V = a^3, \\; A = 6a^2"
            fact = "Asociado a la Tierra por su máxima estabilidad y simetría ortogonal."

        edges: List[Tuple[int, int]] = []
        for face in faces:
            n = len(face)
            for i in range(n):
                e = tuple(sorted((face[i], face[(i + 1) % n])))
                edges.append(e)

        return Mesh3D(
            name=f"platonic_{kind_l}",
            title=title,
            category="Geometría Sagrada & Sólidos Platónicos",
            description=f"Poliedro regular convexo con congruencia y simetría espacial absoluta.",
            formula=formula,
            fun_fact=fact,
            vertices=vertices,
            faces=faces,
            edges=list(set(edges))
        )

    def create_parametric_surface(self, surface_type: str = "saddle", resolution: int = 18, phase: float = 0.0) -> Mesh3D:
        """Genera superficies matemáticas parametrizadas (silla de montar, ondas cuánticas, etc.)."""
        surface_type_l = surface_type.lower()
        vertices: List[Tuple[float, float, float]] = []
        faces: List[List[int]] = []
        edges: List[Tuple[int, int]] = []

        xs = np.linspace(-1.5, 1.5, resolution)
        ys = np.linspace(-1.5, 1.5, resolution)

        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                if surface_type_l in ("saddle", "silla"):
                    z = (x**2 - y**2) * 0.4 * math.cos(phase * 0.5)
                    title = "Paraboloide Hiperbólico (Silla de Montar)"
                    desc = "Superficie reglada con curvatura gaussiana negativa en cada punto."
                    formula = "z = \\frac{x^2}{a^2} - \\frac{y^2}{b^2}"
                    fact = "Es una de las formas de mayor resistencia estructural en arquitectura moderna (usada en techos tensores)."
                elif surface_type_l in ("wave", "onda", "sintropia"):
                    r = math.sqrt(x**2 + y**2)
                    z = math.sin(r * 3.2 - phase) * 0.45
                    title = "Onda de Dispersión Cuántica Ψ(r)"
                    desc = "Superficie de colapso de onda y probabilidad de interferencia sintrópica."
                    formula = "z = A \\cdot \\sin(k \\sqrt{x^2 + y^2} - \\omega t)"
                    fact = "Describe la propagación de paquetes de ondas en física ondulatoria y acústica."
                else:
                    z = math.cos(x * 2 - phase) * math.sin(y * 2 - phase) * 0.4
                    title = "Superficie Modular Trigonométrica"
                    desc = "Patrón periódico de resonancia bidimensional de Chladni."
                    formula = "z = \\cos(2x - \\omega t)\\sin(2y - \\omega t)"
                    fact = "Representa los modos armónicos de vibración de una membrana tensa."

                vertices.append((round(float(x), 3), round(float(y), 3), round(float(z), 3)))

        for i in range(resolution - 1):
            for j in range(resolution - 1):
                p1 = i * resolution + j
                p2 = (i + 1) * resolution + j
                p3 = (i + 1) * resolution + (j + 1)
                p4 = i * resolution + (j + 1)
                faces.append([p1, p2, p3, p4])
                edges.extend([(p1, p2), (p2, p3), (p3, p4), (p4, p1)])

        return Mesh3D(
            name=f"surface_{surface_type_l}",
            title=title,
            category="Superficies Matemáticas Paramétricas",
            description=desc,
            formula=formula,
            fun_fact=fact,
            vertices=vertices,
            faces=faces,
            edges=list(set(edges))
        )

    def create_custom_mesh(self, spec: Dict[str, Any]) -> Mesh3D:
        """Crea una malla 3D arbitraria a partir de especificaciones de vértices y caras."""
        raw_v = spec.get("vertices", [])
        vertices = [(float(v[0]), float(v[1]), float(v[2])) for v in raw_v]
        faces = [list(map(int, f)) for f in spec.get("faces", [])]
        edges = spec.get("edges", [])
        if not edges and faces:
            calc_edges = []
            for face in faces:
                n = len(face)
                for i in range(n):
                    calc_edges.append(tuple(sorted((face[i], face[(i + 1) % n]))))
            edges = list(set(calc_edges))

        return Mesh3D(
            name=spec.get("name", "custom_object"),
            title=spec.get("title", "Objeto 3D Personalizado"),
            category=spec.get("category", "Creación Autónoma"),
            description=spec.get("description", "Malla tridimensional sintetizada bajo demanda."),
            formula=spec.get("formula", "M = \\{V, F, E\\}"),
            fun_fact=spec.get("fun_fact", "Generado por el Núcleo Soberano de GODWORKS SYSTEM v26.4."),
            vertices=vertices,
            faces=faces,
            edges=edges,
            node_labels=spec.get("node_labels")
        )

    # --------------------------------------------------------------------------
    # CATÁLOGO DE MODELOS DISPONIBLES
    # --------------------------------------------------------------------------

    def _init_catalog(self):
        """Inicializa los presets principales en caché."""
        self._catalog_cache["dna"] = self.create_dna_helix()
        self._catalog_cache["atom"] = self.create_bohr_atom()
        self._catalog_cache["torus"] = self.create_torus()
        self._catalog_cache["tesseract"] = self.create_tesseract_projection()
        self._catalog_cache["mobius"] = self.create_mobius_strip()
        self._catalog_cache["icosahedron"] = self.create_platonic_solid("icosahedron")
        self._catalog_cache["dodecahedron"] = self.create_platonic_solid("dodecahedron")
        self._catalog_cache["octahedron"] = self.create_platonic_solid("octahedron")
        self._catalog_cache["cube"] = self.create_platonic_solid("cube")
        self._catalog_cache["saddle"] = self.create_parametric_surface("saddle")
        self._catalog_cache["wave"] = self.create_parametric_surface("wave")
        try:
            import rf_presence_radar
            self._catalog_cache["rf_room"] = rf_presence_radar.get_rf_3d_mesh()
        except Exception:
            pass

    def get_mesh(self, identifier: str) -> Optional[Mesh3D]:
        """Obtiene una malla por nombre o genera variantes dinámicas."""
        id_clean = identifier.lower().strip()
        alias_map = {
            "adn": "dna",
            "dna": "dna",
            "atomo": "atom",
            "átomo": "atom",
            "atom": "atom",
            "toroide": "torus",
            "torus": "torus",
            "geon": "torus",
            "tesseract": "tesseract",
            "hipercubo": "tesseract",
            "mobius": "mobius",
            "möbius": "mobius",
            "cinta": "mobius",
            "icosaedro": "icosahedron",
            "icosahedron": "icosahedron",
            "dodecaedro": "dodecahedron",
            "dodecahedron": "dodecahedron",
            "octaedro": "octahedron",
            "octahedron": "octahedron",
            "cubo": "cube",
            "cube": "cube",
            "silla": "saddle",
            "saddle": "saddle",
            "onda": "wave",
            "wave": "wave",
            "rf": "rf_room",
            "rf_room": "rf_room",
            "radar": "rf_room",
            "entorno_rf": "rf_room",
            "tomografia": "rf_room",
            "wifi_radar": "rf_room",
            "presencia_rf": "rf_room",
            "individuos": "rf_room",
            "habitacion": "rf_room"
        }
        target_key = alias_map.get(id_clean, id_clean)

        if target_key == "rf_room":
            try:
                import rf_presence_radar
                live_mesh = rf_presence_radar.get_rf_3d_mesh()
                self._catalog_cache["rf_room"] = live_mesh
                return live_mesh
            except Exception:
                pass

        return self._catalog_cache.get(target_key)

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Retorna catálogo de modelos con metadatos completos."""
        return self.get_catalog_summary()

    def get_catalog_summary(self) -> List[Dict[str, Any]]:
        """Retorna lista de modelos disponibles para el selector de la UI y el bot."""
        summary = []
        for key, mesh in self._catalog_cache.items():
            summary.append({
                "id": key,
                "name": mesh.name,
                "title": mesh.title,
                "category": mesh.category,
                "description": mesh.description,
                "formula": mesh.formula,
                "fun_fact": mesh.fun_fact,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.faces),
                "edges": len(mesh.edges),
            })
        return summary

    # --------------------------------------------------------------------------
    # MOTOR DE RENDERIZADO SOFTWARE 3D -> IMAGEN PNG
    # --------------------------------------------------------------------------

    def render_mesh_to_image(
        self,
        mesh: Mesh3D,
        width: int = 720,
        height: int = 540,
        pitch_deg: float = 24.0,
        yaw_deg: float = 42.0,
        roll_deg: float = 0.0,
        style: str = "hologram",  # 'hologram', 'wireframe', 'solid', 'points'
        show_hud: bool = True,
        rot_x: Optional[float] = None,
        rot_y: Optional[float] = None,
        rot_z: Optional[float] = None,
    ) -> Image.Image:
        """
        Renderiza una malla 3D completa a una imagen PIL con iluminación,
        profundidad Z-buffer (Painter's algorithm) y estilo cibernético/holográfico.
        """
        if rot_x is not None:
            pitch_deg = rot_x
        if rot_y is not None:
            yaw_deg = rot_y
        if rot_z is not None:
            roll_deg = rot_z

        img = Image.new("RGBA", (width, height), (6, 10, 16, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # 1. Matriz de Rotación 3D
        pitch = math.radians(pitch_deg)
        yaw = math.radians(yaw_deg)
        roll = math.radians(roll_deg)

        cos_p, sin_p = math.cos(pitch), math.sin(pitch)
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        cos_r, sin_r = math.cos(roll), math.sin(roll)

        # Matriz de rotación R = Rz(roll) * Rx(pitch) * Ry(yaw)
        # Vector de luz direccional en el espacio de la cámara
        light_dir = np.array([0.4, 0.7, 0.9])
        light_dir /= np.linalg.norm(light_dir)

        # 2. Transformar vértices al espacio de cámara
        verts_3d: List[Tuple[float, float, float]] = []
        for x, y, z in mesh.vertices:
            # Rotación Yaw (eje Y)
            x1 = x * cos_y + z * sin_y
            y1 = y
            z1 = -x * sin_y + z * cos_y

            # Rotación Pitch (eje X)
            x2 = x1
            y2 = y1 * cos_p - z1 * sin_p
            z2 = y1 * sin_p + z1 * cos_p

            # Rotación Roll (eje Z)
            x3 = x2 * cos_r - y2 * sin_r
            y3 = x2 * sin_r + y2 * cos_r
            z3 = z2

            verts_3d.append((x3, y3, z3))

        # 3. Proyección perspectiva 3D -> 2D
        # Encontrar escala del objeto para ajustarlo al canvas
        all_x = [v[0] for v in verts_3d]
        all_y = [v[1] for v in verts_3d]
        all_z = [v[2] for v in verts_3d]
        max_dim = max(
            max(all_x) - min(all_x) if all_x else 1.0,
            max(all_y) - min(all_y) if all_y else 1.0,
            max(all_z) - min(all_z) if all_z else 1.0,
            0.01
        )
        scale = (min(width, height) * 0.42) / (max_dim * 0.55)
        camera_dist = 5.0
        cx = width / 2
        cy = height / 2

        verts_2d: List[Tuple[float, float, float]] = []
        for x, y, z in verts_3d:
            factor = camera_dist / (camera_dist + z * 0.4)
            px = cx + x * scale * factor
            py = cy - y * scale * factor
            verts_2d.append((px, py, z))

        # Factor de escala dinámica para resoluciones estándar (720x540), Full HD (1920x1080) y Ultra HD (1920x1440 o 4K)
        ui_scale = max(1.0, min(width, height) / 540.0)

        # 4. Dibujar fondo de cuadrícula de perspectiva holográfica
        grid_color = (0, 212, 200, 18)
        gy_step = int(40 * ui_scale)
        gx_step = int(50 * ui_scale)
        for gy in range(int(height * 0.2), int(height * 0.8), max(20, gy_step)):
            draw.line([(width * 0.15, gy), (width * 0.85, gy)], fill=grid_color, width=max(1, int(1 * ui_scale)))
        for gx in range(int(width * 0.2), int(width * 0.8), max(25, gx_step)):
            draw.line([(gx, height * 0.2), (gx, height * 0.8)], fill=grid_color, width=max(1, int(1 * ui_scale)))

        # 5. Ordenamiento de caras por profundidad Z (Painter's Algorithm)
        faces_with_depth = []
        for f_idx, face in enumerate(mesh.faces):
            if len(face) < 3:
                continue
            # Calcular profundidad Z media de la cara
            avg_z = sum(verts_3d[v_i][2] for v_i in face) / len(face)

            # Vector normal para iluminación
            v0 = np.array(verts_3d[face[0]])
            v1 = np.array(verts_3d[face[1]])
            v2 = np.array(verts_3d[face[2]])
            normal = np.cross(v1 - v0, v2 - v0)
            norm_len = np.linalg.norm(normal)
            if norm_len > 1e-6:
                normal /= norm_len
            else:
                normal = np.array([0.0, 0.0, 1.0])

            diffuse = max(0.12, float(np.dot(normal, light_dir)))
            faces_with_depth.append((avg_z, face, diffuse, normal[2]))

        # Ordenar caras de atrás hacia adelante (Z decreciente)
        faces_with_depth.sort(key=lambda x: x[0])

        # 6. Renderizar Caras Sólidas / Holográficas
        primary_teal = (0, 212, 200)
        gold_accent = (232, 182, 74)

        if style in ("hologram", "solid"):
            for _, face, diffuse, nz in faces_with_depth:
                poly = [(verts_2d[v_i][0], verts_2d[v_i][1]) for v_i in face]

                if style == "hologram":
                    # Tono traslúcido con resplandor cian según la incidencia de la luz
                    alpha = int(35 + diffuse * 85)
                    r_c = int(primary_teal[0] * diffuse * 0.4)
                    g_c = int(primary_teal[1] * diffuse * 0.6)
                    b_c = int(primary_teal[2] * diffuse * 0.8)
                    draw.polygon(poly, fill=(r_c, g_c, b_c, alpha))
                else:  # Solid
                    r_c = int(primary_teal[0] * diffuse)
                    g_c = int(primary_teal[1] * diffuse)
                    b_c = int(primary_teal[2] * diffuse)
                    draw.polygon(poly, fill=(r_c, g_c, b_c, 210))

        # 7. Renderizar Aristas (Wireframe Neon)
        if style in ("hologram", "wireframe", "solid"):
            edge_color = (0, 212, 200, 200 if style == "wireframe" else 150)
            line_w = max(2, int(2.5 * ui_scale)) if style == "wireframe" else max(1, int(1.4 * ui_scale))
            for v1_i, v2_i in mesh.edges:
                if v1_i < len(verts_2d) and v2_i < len(verts_2d):
                    p1 = (verts_2d[v1_i][0], verts_2d[v1_i][1])
                    p2 = (verts_2d[v2_i][0], verts_2d[v2_i][1])
                    draw.line([p1, p2], fill=edge_color, width=line_w)

        # 8. Renderizar Vértices como Nodos de Resplandor
        base_r = 2.5 if len(mesh.vertices) < 80 else 1.8
        node_radius = max(2.0, base_r * ui_scale)
        for idx, (px, py, z) in enumerate(verts_2d):
            is_labeled = bool(mesh.node_labels and idx in mesh.node_labels)
            color = (255, 230, 140, 240) if is_labeled else (0, 255, 220, 210)
            r = node_radius + ((1.5 * ui_scale) if is_labeled else 0.0)

            # Brillo circular
            draw.ellipse([px - r, py - r, px + r, py + r], fill=color)

        # 9. Superposición de HUD Holográfico con Datos Científicos
        if show_hud:
            # Fuentes TrueType para renderizado nítido y caracteres Unicode / acentos
            font_title = None
            font_body = None
            font_small = None
            for p_bold in [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
            ]:
                if os.path.exists(p_bold):
                    try:
                        font_title = ImageFont.truetype(p_bold, max(14, int(15 * ui_scale)))
                        break
                    except Exception:
                        pass

            for p_reg in [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
            ]:
                if os.path.exists(p_reg):
                    try:
                        font_body = ImageFont.truetype(p_reg, max(11, int(12 * ui_scale)))
                        font_small = ImageFont.truetype(p_reg, max(10, int(11 * ui_scale)))
                        break
                    except Exception:
                        pass

            # Marco exterior estilo HUD táctico escalado
            border_color = (0, 212, 200, 90)
            pad = int(10 * ui_scale)
            corner_len = int(18 * ui_scale)
            corner_w = max(2, int(2.5 * ui_scale))
            border_w = max(1, int(1.2 * ui_scale))

            draw.rectangle([pad, pad, width - pad, height - pad], outline=border_color, width=border_w)
            # Esquinas acentuadas
            draw.line([(pad, pad + corner_len), (pad, pad), (pad + corner_len, pad)], fill=(0, 212, 200, 255), width=corner_w)
            draw.line([(width - pad - corner_len, pad), (width - pad, pad), (width - pad, pad + corner_len)], fill=(0, 212, 200, 255), width=corner_w)
            draw.line([(pad, height - pad - corner_len), (pad, height - pad), (pad + corner_len, height - pad)], fill=(0, 212, 200, 255), width=corner_w)
            draw.line([(width - pad - corner_len, height - pad), (width - pad, height - pad), (width - pad, height - pad - corner_len)], fill=(0, 212, 200, 255), width=corner_w)

            # Título y metadatos con fuentes nítidas
            x_text = int(22 * ui_scale)
            y_title = int(18 * ui_scale)
            y_meta = int(18 * ui_scale + 22 * ui_scale)
            y_formula = int(18 * ui_scale + 42 * ui_scale)
            y_footer = height - int(32 * ui_scale)

            draw.text((x_text, y_title), f"// {mesh.title.upper()} · ESTUDIO 3D SOBERANO (HD)", fill=(0, 212, 200, 255), font=font_title)
            draw.text((x_text, y_meta), f"Categoría: {mesh.category} | V: {len(mesh.vertices)} | F: {len(mesh.faces)} | E: {len(mesh.edges)}", fill=(160, 190, 210, 230), font=font_body)
            if mesh.formula:
                draw.text((x_text, y_formula), f"Fórmula: {mesh.formula}", fill=(240, 195, 85, 240), font=font_body)

            # Pie de imagen
            draw.text((x_text, y_footer), f"TARDIS · Sistema de Vigilancia y Control Temporal · Inferencia 3D Render Engine · {width}x{height} HD", fill=(0, 212, 200, 180), font=font_small)
            angle_str = f"Ángulo: P:{pitch_deg:.0f}° Y:{yaw_deg:.0f}°"
            angle_x = max(x_text + int(300 * ui_scale), width - int(240 * ui_scale))
            draw.text((angle_x, y_footer), angle_str, fill=(160, 190, 210, 190), font=font_small)

        return img

    def render_to_png_bytes(
        self,
        mesh: Mesh3D,
        width: int = 720,
        height: int = 540,
        pitch_deg: float = 24.0,
        yaw_deg: float = 42.0,
        style: str = "hologram",
        show_hud: bool = True,
        rot_x: Optional[float] = None,
        rot_y: Optional[float] = None,
        rot_z: Optional[float] = None
    ) -> bytes:
        """Renderiza a bytes PNG listos para enviar por red o guardar en disco."""
        img = self.render_mesh_to_image(
            mesh,
            width=width,
            height=height,
            pitch_deg=pitch_deg,
            yaw_deg=yaw_deg,
            style=style,
            show_hud=show_hud,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z
        )
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def render_mesh_animation(
        self,
        mesh_or_name: Union[Mesh3D, str],
        duration_sec: float = 4.0,
        fps: int = 240,
        ported_fps: int = 60,
        width: int = 3840,
        height: int = 2160,
        hdr: bool = True,
        style: str = "hologram",
        show_hud: bool = True,
        output_path: Optional[Path] = None,
        camera_orbit_yaw: float = 360.0,
        frames: Optional[int] = None,
        pitch_deg: Optional[float] = None,
        return_bytes: bool = False
    ) -> Union[Dict[str, Any], bytes]:
        """
        Sintetiza una animación 3D cinemática fluida (360° orbital) acelerada por hardware (NVENC)
        renderizada a 240 FPS y porteada a 60 FPS en resolución 4K HDR (BT.2020 10-bit).
        Devuelve un diccionario con bytes MP4, metadata, duración y ruta del archivo, o bytes directos.
        """
        if isinstance(mesh_or_name, str):
            mesh = self.get_mesh(mesh_or_name)
            if not mesh:
                for it in self.get_catalog_summary():
                    if mesh_or_name.lower() in it["id"] or mesh_or_name.lower() in it["title"].lower():
                        mesh = self.get_mesh(it["id"])
                        break
            if not mesh:
                mesh = self.get_mesh("atom")
        else:
            mesh = mesh_or_name

        if not mesh:
            if return_bytes:
                return b""
            return {"ok": False, "error": f"No se pudo resolver el modelo 3D para animación."}

        output_dir = BASE_DIR / "data" / "render3d_animations"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        out_file = output_path or (output_dir / f"anim3d_{mesh.name}_{timestamp}.mp4")

        if frames is not None and frames > 0:
            total_frames = int(frames)
            duration_sec = total_frames / max(1, fps)
        else:
            total_frames = max(1, int(duration_sec * fps))

        # Filtro de conversión temporal: 240 FPS -> 60 FPS con mezcla temporal de fotogramas (motion blur puro)
        if fps >= 240 and ported_fps == 60 and total_frames >= 4:
            filter_str = f"tmix=frames=4:weights='1 1 1 1',fps={ported_fps}"
        elif fps != ported_fps:
            filter_str = f"fps=fps={ported_fps}"
        else:
            filter_str = f"fps=fps={fps}"

        if hdr:
            # 4K HDR10 / HLG BT.2020 10-bit NVENC Hardware Encoder
            cmd_nvenc = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-pix_fmt", "rgb24",
                "-r", str(fps),
                "-i", "-",
                "-vf", filter_str,
                "-c:v", "hevc_nvenc",
                "-preset", "p4",
                "-cq", "22",
                "-b:v", "25M",
                "-maxrate", "38M",
                "-bufsize", "50M",
                "-pix_fmt", "p010le",
                "-color_primaries", "bt2020",
                "-color_trc", "arib-std-b67",
                "-colorspace", "bt2020nc",
                "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                "-tag:v", "hvc1",
                "-movflags", "+faststart",
                str(out_file)
            ]
            # Respaldo CPU multihilo libx265 10-bit
            cmd_cpu = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-pix_fmt", "rgb24",
                "-r", str(fps),
                "-i", "-",
                "-vf", filter_str,
                "-c:v", "libx265",
                "-preset", "ultrafast",
                "-crf", "20",
                "-pix_fmt", "yuv420p10le",
                "-color_primaries", "bt2020",
                "-color_trc", "arib-std-b67",
                "-colorspace", "bt2020nc",
                "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                "-tag:v", "hvc1",
                "-threads", "16",
                "-movflags", "+faststart",
                str(out_file)
            ]
        else:
            cmd_nvenc = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-pix_fmt", "rgb24",
                "-r", str(fps),
                "-i", "-",
                "-vf", filter_str,
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-cq", "23",
                "-b:v", "15M",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(out_file)
            ]
            cmd_cpu = [
                "ffmpeg", "-y",
                "-f", "rawvideo",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-pix_fmt", "rgb24",
                "-r", str(fps),
                "-i", "-",
                "-vf", filter_str,
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-pix_fmt", "yuv420p",
                "-threads", "16",
                "-movflags", "+faststart",
                str(out_file)
            ]

        proc = None
        try:
            proc = subprocess.Popen(cmd_nvenc, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception:
            proc = subprocess.Popen(cmd_cpu, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        base_pitch = pitch_deg if pitch_deg is not None else 22.0
        try:
            for f_idx in range(total_frames):
                progress = f_idx / total_frames
                phase = progress * 2.0 * math.pi
                yaw_deg = (progress * camera_orbit_yaw) % 360.0
                curr_pitch_deg = base_pitch + 8.0 * math.sin(phase)

                # Generar variante dinámica según el tipo de modelo
                curr_mesh = mesh
                if mesh.name in ("bohr_atom", "atom"):
                    curr_mesh = self.create_bohr_atom(phase=progress)
                elif mesh.name in ("wave", "saddle") or "wave" in mesh.name:
                    curr_mesh = self.create_parametric_surface("wave", phase=phase)
                elif "tesseract" in mesh.name:
                    curr_mesh = self.create_tesseract_projection(angle_4d=phase)
                elif "dna" in mesh.name:
                    curr_mesh = self.create_dna_helix(phase=progress)

                img = self.render_mesh_to_image(
                    curr_mesh,
                    width=width,
                    height=height,
                    pitch_deg=curr_pitch_deg,
                    yaw_deg=yaw_deg,
                    style=style,
                    show_hud=show_hud
                )
                raw_rgb = img.convert("RGB").tobytes()
                proc.stdin.write(raw_rgb)

            proc.stdin.close()
            proc.wait(timeout=30.0)
        except Exception as e:
            if proc and proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if return_bytes:
                return b""
            return {"ok": False, "error": f"Fallo durante el renderizado 3D: {e}"}
        finally:
            if proc and proc.stderr:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

        if not out_file.exists() or out_file.stat().st_size == 0:
            if return_bytes:
                return b""
            return {"ok": False, "error": f"El archivo de animación 3D no se generó correctamente ({out_file})."}

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                out_file,
                title=mesh.title,
                formula=mesh.formula,
                domain=mesh.category,
                keywords=[mesh.name]
            )
        except Exception as e_audio:
            logger.warning(f"No se pudo asegurar audio en animación 3D: {e_audio}")

        mp4_bytes = out_file.read_bytes()
        if return_bytes:
            return mp4_bytes
        is_4k = (width >= 3840 or height >= 2160 or (width >= 2160 and height >= 2160))
        res_str = f"{width}x{height} (4K HDR)" if (is_4k and hdr) else (f"{width}x{height} HDR" if hdr else f"{width}x{height}")
        hdr_info = " • BT.2020 10-bit HDR (HLG)" if hdr else ""
        caption = (
            f"🌀 **[ANIMACIÓN 3D ORBITAL · TARDIS HOLODECK 4K HDR]**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **Modelo:** {mesh.title}\n"
            f"• **Categoría:** {mesh.category}\n"
            f"• **Dinámica:** Órbita cinemática 360° ({res_str} @ {fps} FPS Render · Porteadas a {ported_fps} FPS · {duration_sec:.1f}s)\n"
            f"• **Espacio de Color:** BT.2020 10-bit High Dynamic Range (HLG/PQ){hdr_info}\n"
            f"• **Topología:** `{len(mesh.vertices)}` vértices | `{len(mesh.faces)}` caras | `{len(mesh.edges)}` aristas\n"
            f"• **Fórmula:** `{mesh.formula}`\n"
            f"• **Explicación Científica:** {mesh.description}\n"
            f"💡 *Dato Curioso:* {mesh.fun_fact}"
        )

        return {
            "ok": True,
            "media_type": "animation",
            "file_path": out_file,
            "bytes_data": mp4_bytes,
            "width": width,
            "height": height,
            "fps": fps,
            "ported_fps": ported_fps,
            "hdr": hdr,
            "resolution": res_str,
            "duration": duration_sec,
            "caption": caption,
            "title": mesh.title,
            "name": mesh.name
        }

    def animate_model(self, model_name: str, **kwargs) -> Dict[str, Any]:
        """Helper para animar un modelo por identificador."""
        return self.render_mesh_animation(model_name, **kwargs)


# Instancia Global
def get_render_3d_engine() -> Render3DEngine:
    return Render3DEngine.get_instance()
