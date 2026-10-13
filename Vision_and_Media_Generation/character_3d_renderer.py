"""
core/character_3d_renderer.py - Motor de Render 3D del Personaje TARDIS
=======================================================================
GODWORKS SYSTEM v26.4

Rasterizador 3D por software (NumPy + OpenCV) que genera el avatar soberano
de TARDIS como geometria tridimensional real:

  * Mallas procedurales (icoesfera, toroide, cilindro, casquete esferico).
  * Pipeline modelo -> mundo -> vista -> proyeccion en perspectiva.
  * Descarte de caras traseras + ordenamiento por profundidad (painter).
  * Sombreado Blinn-Phong: luz clave, relleno, contraluz y emision.
  * Post-proceso: bloom, vineteado, aberracion cromatica y grano.

Disenado para 3840x2160 @ 60 FPS. El rasterizado usa cv2.fillConvexPoly
(C++) por triangulo, con transformaciones e iluminacion vectorizadas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Paleta soberana (identica a la plataforma local)
# --------------------------------------------------------------------------
COL_TEAL = np.array([0, 212, 200], dtype=np.float32)
COL_GOLD = np.array([232, 182, 74], dtype=np.float32)
COL_AMBER = np.array([245, 158, 11], dtype=np.float32)
COL_HULL = np.array([46, 74, 96], dtype=np.float32)
COL_HULL_DARK = np.array([24, 44, 60], dtype=np.float32)
COL_GLASS = np.array([10, 48, 62], dtype=np.float32)
COL_BG_TOP = np.array([2, 6, 12], dtype=np.float32)
COL_BG_BOT = np.array([1, 3, 7], dtype=np.float32)


@dataclass
class Material:
    """Propiedades de superficie para el sombreador Blinn-Phong."""
    base: np.ndarray                      # color difuso RGB 0-255
    specular: float = 0.5                 # intensidad especular
    shininess: float = 32.0               # exponente especular
    emissive: float = 0.0                 # 0-1, auto-iluminacion
    rim: float = 0.6                      # intensidad del contraluz
    metallic: float = 0.3                 # refuerza especular y oscurece difuso


@dataclass
class Part:
    """Sub-malla del personaje con su material y transformacion animable."""
    name: str
    vertices: np.ndarray                  # (N, 3) float32
    faces: np.ndarray                     # (M, 3) int32
    material: Material
    dynamic: bool = False                 # recalcula transform por cuadro
    transform: Optional[np.ndarray] = None  # (4, 4) opcional


# --------------------------------------------------------------------------
# Primitivas de malla procedural
# --------------------------------------------------------------------------
def _normalize_rows(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0.0] = 1.0
    return v / n


def icosphere(subdivisions: int = 2, radius: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
    """Icoesfera geodesica: triangulos uniformes, ideal para sombreado suave."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ], dtype=np.float32)
    faces = np.array([
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ], dtype=np.int32)

    verts = _normalize_rows(verts)
    for _ in range(max(0, subdivisions)):
        cache: Dict[Tuple[int, int], int] = {}
        vlist = [v for v in verts]
        new_faces = []

        def midpoint(a: int, b: int) -> int:
            key = (min(a, b), max(a, b))
            if key in cache:
                return cache[key]
            m = (vlist[a] + vlist[b]) * 0.5
            m = m / (np.linalg.norm(m) or 1.0)
            vlist.append(m.astype(np.float32))
            idx = len(vlist) - 1
            cache[key] = idx
            return idx

        for f in faces:
            a, b, c = int(f[0]), int(f[1]), int(f[2])
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            new_faces += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]

        verts = np.array(vlist, dtype=np.float32)
        faces = np.array(new_faces, dtype=np.int32)

    return (verts * float(radius)).astype(np.float32), faces


def torus(R: float = 1.0, r: float = 0.25, seg_u: int = 48, seg_v: int = 20) -> Tuple[np.ndarray, np.ndarray]:
    """Toroide parametrico para los anillos giroscopicos."""
    u = np.linspace(0.0, 2.0 * math.pi, seg_u, endpoint=False)
    v = np.linspace(0.0, 2.0 * math.pi, seg_v, endpoint=False)
    uu, vv = np.meshgrid(u, v, indexing="ij")
    x = (R + r * np.cos(vv)) * np.cos(uu)
    y = (R + r * np.cos(vv)) * np.sin(uu)
    z = r * np.sin(vv)
    verts = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1).astype(np.float32)

    faces = []
    for i in range(seg_u):
        i2 = (i + 1) % seg_u
        for j in range(seg_v):
            j2 = (j + 1) % seg_v
            a = i * seg_v + j
            b = i2 * seg_v + j
            c = i2 * seg_v + j2
            d = i * seg_v + j2
            faces.append([a, b, c])
            faces.append([a, c, d])
    return verts, np.array(faces, dtype=np.int32)


def cylinder(radius: float = 0.3, height: float = 1.0, segments: int = 28, caps: bool = True):
    """Cilindro sobre el eje Z, centrado en el origen."""
    ang = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    cx, cy = np.cos(ang) * radius, np.sin(ang) * radius
    top = np.stack([cx, cy, np.full(segments, height * 0.5)], axis=1)
    bot = np.stack([cx, cy, np.full(segments, -height * 0.5)], axis=1)
    verts = np.concatenate([top, bot], axis=0).astype(np.float32)

    faces = []
    for i in range(segments):
        i2 = (i + 1) % segments
        a, b = i, i2
        c, d = segments + i2, segments + i
        faces.append([a, b, c])
        faces.append([a, c, d])

    if caps:
        verts = np.concatenate([verts, np.array([[0, 0, height * 0.5], [0, 0, -height * 0.5]], dtype=np.float32)])
        ct, cb = len(verts) - 2, len(verts) - 1
        for i in range(segments):
            i2 = (i + 1) % segments
            faces.append([ct, i2, i])
            faces.append([cb, segments + i, segments + i2])

    return verts, np.array(faces, dtype=np.int32)


def spherical_cap(radius: float = 1.0, max_angle: float = 0.9, rings: int = 16, segments: int = 32):
    """Casquete esferico (visor). max_angle en radianes desde el polo +Z."""
    verts = [np.array([0.0, 0.0, radius], dtype=np.float32)]
    for i in range(1, rings + 1):
        phi = max_angle * (i / rings)
        z = radius * math.cos(phi)
        rad = radius * math.sin(phi)
        for j in range(segments):
            th = 2.0 * math.pi * j / segments
            verts.append(np.array([rad * math.cos(th), rad * math.sin(th), z], dtype=np.float32))
    V = np.array(verts, dtype=np.float32)

    faces = []
    for j in range(segments):
        j2 = (j + 1) % segments
        faces.append([0, 1 + j2, 1 + j])
    for i in range(rings - 1):
        base = 1 + i * segments
        nxt = base + segments
        for j in range(segments):
            j2 = (j + 1) % segments
            faces.append([base + j, base + j2, nxt + j2])
            faces.append([base + j, nxt + j2, nxt + j])
    return V, np.array(faces, dtype=np.int32)


def rounded_box(sx: float, sy: float, sz: float, subdiv: int = 2, roundness: float = 0.35):
    """Caja redondeada mediante deformacion de icoesfera (casco del torso)."""
    v, f = icosphere(subdiv, 1.0)
    p = v.copy()
    k = max(1e-3, roundness)
    sign = np.sign(p)
    p = sign * (np.abs(p) ** (1.0 - k * 0.85))
    p[:, 0] *= sx
    p[:, 1] *= sy
    p[:, 2] *= sz
    return p.astype(np.float32), f


def cylinder_between(p1: np.ndarray, p2: np.ndarray, radius: float = 0.03, segments: int = 12) -> Tuple[np.ndarray, np.ndarray]:
    """Crea una malla cilíndrica sólida conectando dos puntos 3D arbitrarios."""
    p1 = np.asarray(p1, dtype=np.float32)
    p2 = np.asarray(p2, dtype=np.float32)
    v = p2 - p1
    length = float(np.linalg.norm(v))
    if length < 1e-6:
        v = np.array([0, 0, 1], dtype=np.float32)
        length = 1e-6
    u = v / length

    ref = np.array([0, 0, 1], dtype=np.float32) if abs(u[2]) < 0.9 else np.array([1, 0, 0], dtype=np.float32)
    a = np.cross(u, ref)
    a /= (np.linalg.norm(a) or 1.0)
    b = np.cross(u, a)

    angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    cos_a = np.cos(angles)[:, None] * radius
    sin_a = np.sin(angles)[:, None] * radius
    ring = cos_a * a[None, :] + sin_a * b[None, :]

    bottom_verts = p1[None, :] + ring
    top_verts = p2[None, :] + ring
    center_bot = p1[None, :]
    center_top = p2[None, :]

    verts = np.concatenate([bottom_verts, top_verts, center_bot, center_top], axis=0).astype(np.float32)

    faces = []
    idx_cb = 2 * segments
    idx_ct = 2 * segments + 1

    for i in range(segments):
        i2 = (i + 1) % segments
        faces.append([i, i2, segments + i2])
        faces.append([i, segments + i2, segments + i])
        faces.append([idx_cb, i2, i])
        faces.append([idx_ct, segments + i, segments + i2])

    return verts, np.array(faces, dtype=np.int32)


def build_beveled_triangle_hull(
    side: float = 2.4,
    depth: float = 0.32,
    front_bevel: float = 0.12,
    rear_depth: float = 0.22
) -> Tuple[Tuple[np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray]]:
    """
    Construye la carcasa triangular en 3D del personaje soberano:
      - outer_chassis: Chasis biselado metálico perimetral y posterior.
      - inner_plate: Placa frontal de cristal abisal con rebaje óptico.
    """
    H = side * (math.sqrt(3.0) / 2.0)
    p_apex = np.array([0.0, H * (2.0 / 3.0), 0.0], dtype=np.float32)
    p_left = np.array([-side * 0.5, -H * (1.0 / 3.0), 0.0], dtype=np.float32)
    p_right = np.array([side * 0.5, -H * (1.0 / 3.0), 0.0], dtype=np.float32)

    scale_rim = 0.94
    scale_plate = 0.86
    scale_back = 0.92

    V_mid = [p_apex, p_right, p_left]

    zf = depth * 0.5
    V_f_rim = [p * scale_rim + np.array([0, 0, zf]) for p in V_mid]

    zp = zf + front_bevel * 0.5
    V_f_plate = [p * scale_plate + np.array([0, 0, zp]) for p in V_mid]
    V_f_center = np.array([0.0, 0.0, zp + 0.03], dtype=np.float32)

    zb = -depth * 0.5
    V_b_rim = [p * scale_back + np.array([0, 0, zb]) for p in V_mid]
    V_b_apex = np.array([0.0, 0.0, zb - rear_depth], dtype=np.float32)

    chassis_verts = []
    chassis_faces = []

    chassis_verts.extend(V_mid)
    chassis_verts.extend(V_f_rim)
    chassis_verts.extend(V_b_rim)
    chassis_verts.append(V_b_apex)

    for i in range(3):
        i2 = (i + 1) % 3
        chassis_faces.append([i, i2, 3 + i2])
        chassis_faces.append([i, 3 + i2, 3 + i])

        chassis_faces.append([i2, i, 6 + i])
        chassis_faces.append([i2, 6 + i, 6 + i2])

        chassis_faces.append([6 + i2, 6 + i, 9])

    plate_verts = []
    plate_faces = []
    plate_verts.extend(V_f_rim)
    plate_verts.extend(V_f_plate)
    plate_verts.append(V_f_center)

    for i in range(3):
        i2 = (i + 1) % 3
        plate_faces.append([i, i2, 3 + i2])
        plate_faces.append([i, 3 + i2, 3 + i])
        plate_faces.append([3 + i, 3 + i2, 6])

    v_c = np.array(chassis_verts, dtype=np.float32)
    f_c = np.array(chassis_faces, dtype=np.int32)
    v_p = np.array(plate_verts, dtype=np.float32)
    f_p = np.array(plate_faces, dtype=np.int32)

    return (v_c, f_c), (v_p, f_p)


# --------------------------------------------------------------------------
# Algebra de transformaciones
# --------------------------------------------------------------------------
def mat_identity() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def mat_translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = (x, y, z)
    return m


def mat_scale(sx: float, sy: float = None, sz: float = None) -> np.ndarray:
    sy = sx if sy is None else sy
    sz = sx if sz is None else sz
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


def mat_rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def mat_rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def mat_rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def transform_points(mat: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Aplica una matriz 4x4 a un lote de puntos (N,3) de forma vectorizada."""
    return pts @ mat[:3, :3].T + mat[:3, 3]


# --------------------------------------------------------------------------
# Motor de render del personaje
# --------------------------------------------------------------------------
class Character3DRenderer:
    """Avatar 3D Soberano de TARDIS: Personaje Triangular idéntico al nodo local."""

    _instance: Optional["Character3DRenderer"] = None

    @classmethod
    def get_instance(cls, quality: str = "high") -> "Character3DRenderer":
        if cls._instance is None or cls._instance.quality != quality:
            cls._instance = cls(quality=quality)
        return cls._instance

    def __init__(self, quality: str = "high"):
        self.quality = quality
        # Densidad de malla segun calidad
        sub = {"low": 1, "medium": 2, "high": 3, "ultra": 4}.get(quality, 2)
        self.subdiv = sub
        self.parts: List[Part] = []
        self._build_character()

        # Iluminacion de estudio (espacio de vista)
        self.light_key = _normalize_rows(np.array([[-0.45, 0.62, 0.85]], dtype=np.float32))[0]
        self.light_fill = _normalize_rows(np.array([[0.75, 0.15, 0.55]], dtype=np.float32))[0]
        self.light_back = _normalize_rows(np.array([[0.1, -0.35, -0.92]], dtype=np.float32))[0]
        self.key_color = np.array([1.0, 0.97, 0.92], dtype=np.float32)
        self.fill_color = np.array([0.30, 0.68, 0.80], dtype=np.float32)
        self.back_color = np.array([0.95, 0.72, 0.30], dtype=np.float32)

    # ---------------------------------------------------------------- malla
    def _build_character(self) -> None:
        s = self.subdiv
        P = self.parts

        mat_hull = Material(COL_HULL, specular=0.85, shininess=64.0, rim=0.85, metallic=0.72)
        mat_hull_dark = Material(COL_HULL_DARK, specular=0.60, shininess=45.0, rim=0.6, metallic=0.65)
        mat_glass = Material(COL_GLASS, specular=1.0, shininess=180.0, emissive=0.15, rim=1.0, metallic=0.9)
        mat_teal_glow = Material(COL_TEAL, specular=0.6, shininess=48.0, emissive=0.88, rim=0.4)
        mat_gold = Material(COL_GOLD, specular=0.95, shininess=110.0, emissive=0.30, rim=0.75, metallic=0.85)
        mat_amber = Material(COL_AMBER, specular=0.8, shininess=90.0, emissive=0.95, rim=0.3)
        mat_white_spark = Material(np.array([255, 255, 255], dtype=np.float32), specular=1.0, shininess=120.0, emissive=1.0)
        mat_pupil_black = Material(np.array([1, 3, 6], dtype=np.float32), specular=0.1, shininess=10.0, emissive=0.0)

        side = 2.4
        H = side * (math.sqrt(3.0) / 2.0)
        p_apex = np.array([0.0, H * (2.0 / 3.0), 0.0], dtype=np.float32)
        p_left = np.array([-side * 0.5, -H * (1.0 / 3.0), 0.0], dtype=np.float32)
        p_right = np.array([side * 0.5, -H * (1.0 / 3.0), 0.0], dtype=np.float32)

        p_mid_bot = np.array([0.0, -H * (1.0 / 3.0), 0.0], dtype=np.float32)
        p_mid_left = np.array([-side * 0.25, H * (1.0 / 6.0), 0.0], dtype=np.float32)
        p_mid_right = np.array([side * 0.25, H * (1.0 / 6.0), 0.0], dtype=np.float32)

        # 1. Chasis triangular biselado y placa frontal (idéntico al nodo local)
        (v_c, f_c), (v_p, f_p) = build_beveled_triangle_hull(side=side)
        P.append(Part("chassis", v_c, f_c, mat_hull))
        P.append(Part("face_plate", v_p, f_p, mat_glass))

        # 2. Marco exterior de neón (3 aristas tubulares principales)
        z_edge = 0.16
        p_a_e = p_apex + np.array([0, 0, z_edge])
        p_l_e = p_left + np.array([0, 0, z_edge])
        p_r_e = p_right + np.array([0, 0, z_edge])

        for idx, (p1, p2) in enumerate(((p_a_e, p_l_e), (p_l_e, p_r_e), (p_r_e, p_a_e))):
            v, f = cylinder_between(p1, p2, radius=0.034, segments=12)
            P.append(Part(f"border_neon_{idx}", v, f, mat_teal_glow))

        # 3. Enrejado interno: Triángulo fractal invertido sagrado (dorado)
        z_lattice = 0.19
        p_mb_l = p_mid_bot + np.array([0, 0, z_lattice])
        p_ml_l = p_mid_left + np.array([0, 0, z_lattice])
        p_mr_l = p_mid_right + np.array([0, 0, z_lattice])

        for idx, (p1, p2) in enumerate(((p_mb_l, p_ml_l), (p_ml_l, p_mr_l), (p_mr_l, p_mb_l))):
            v, f = cylinder_between(p1, p2, radius=0.022, segments=10)
            P.append(Part(f"inverted_tri_{idx}", v, f, mat_gold))

        # 4. Enrejado interno: Puntales centroidales radiantes (teal glow)
        p_center_l = np.array([0.0, 0.0, z_lattice - 0.01], dtype=np.float32)
        for idx, target in enumerate((p_a_e * 0.92, p_l_e * 0.92, p_r_e * 0.92, p_mb_l, p_ml_l, p_mr_l)):
            v, f = cylinder_between(p_center_l, target, radius=0.015, segments=8)
            P.append(Part(f"centroid_strut_{idx}", v, f, mat_teal_glow))

        # 5. Nodos condensadores cuánticos en los 3 vértices
        for idx, pt in enumerate((p_apex, p_left, p_right)):
            v, f = icosphere(s, 0.11)
            v = v + pt + np.array([0, 0, z_edge])
            P.append(Part(f"node_gold_{idx}", v, f, mat_gold))

            v, f = icosphere(s, 0.055)
            v = v + pt + np.array([0, 0, z_edge + 0.07])
            P.append(Part(f"node_core_{idx}", v, f, mat_amber, dynamic=True))

            v, f = torus(R=0.15, r=0.018, seg_u=32, seg_v=8)
            v = v + pt + np.array([0, 0, z_edge])
            P.append(Part(f"node_ring_{idx}", v, f, mat_teal_glow, dynamic=True))

        # 6. El Ojo Cibernético Soberano (almendrado, iris cuántico y reflejos)
        eye_y = 0.05
        eye_z = 0.21

        # Marco / Bisel almendrado del ojo
        v, f = torus(R=0.34, r=0.024, seg_u=48, seg_v=8)
        v = v * np.array([1.28, 0.58, 1.0], dtype=np.float32) + np.array([0, eye_y, eye_z], dtype=np.float32)
        P.append(Part("eye_socket", v, f, mat_gold))

        # Esclera oscura abisal
        v, f = icosphere(s, 0.30)
        v = v * np.array([1.22, 0.54, 0.22], dtype=np.float32) + np.array([0, eye_y, eye_z - 0.03], dtype=np.float32)
        P.append(Part("sclera", v, f, mat_hull_dark))

        # Iris central
        v, f = icosphere(s, 0.15)
        v = v * np.array([1.0, 1.0, 0.35], dtype=np.float32) + np.array([0, eye_y, eye_z + 0.02], dtype=np.float32)
        P.append(Part("iris_core", v, f, mat_amber, dynamic=True))

        # Anillos orbitales del iris
        for idx, (rr, tt) in enumerate(((0.21, 0.015), (0.27, 0.012))):
            v, f = torus(R=rr, r=tt, seg_u=40, seg_v=8)
            v = v + np.array([0, eye_y, eye_z + 0.015], dtype=np.float32)
            P.append(Part(f"iris_ring_{idx}", v, f, mat_gold if idx == 0 else mat_teal_glow, dynamic=True))

        # Pupila negra pura en primer plano
        v, f = icosphere(s, 0.065)
        v = v * np.array([1.0, 1.0, 0.25], dtype=np.float32) + np.array([0, eye_y, eye_z + 0.065], dtype=np.float32)
        P.append(Part("pupil", v, f, mat_pupil_black, dynamic=True))

        # Destellos / Brillo especular 3D de mirada viva (specular glints)
        v, f = icosphere(1, 0.018)
        v = v + np.array([-0.045, eye_y + 0.045, eye_z + 0.075], dtype=np.float32)
        P.append(Part("specular_1", v, f, mat_white_spark))

        v, f = icosphere(1, 0.010)
        v = v + np.array([0.038, eye_y - 0.032, eye_z + 0.075], dtype=np.float32)
        P.append(Part("specular_2", v, f, mat_white_spark))

        # Párpado superior (dinámico con blink)
        v, f = icosphere(s, 0.32)
        v = v * np.array([1.30, 0.38, 0.12], dtype=np.float32) + np.array([0, eye_y + 0.16, eye_z + 0.05], dtype=np.float32)
        P.append(Part("eyelid", v, f, mat_hull, dynamic=True))

        # 7. Boca Biomecánica Articulada y Barras del Ecualizador
        mouth_y = -0.32
        mouth_z = 0.20

        # Cavidad bucal oscura
        v, f = icosphere(max(1, s - 1), 0.28)
        v = v * np.array([1.15, 0.22, 0.18], dtype=np.float32) + np.array([0, mouth_y, mouth_z - 0.02], dtype=np.float32)
        P.append(Part("mouth_cavity", v, f, Material(np.array([2, 6, 12], dtype=np.float32), specular=0.1, shininess=10.0)))

        # Labio / Mandíbula articulada inferior
        v, f = torus(R=0.28, r=0.020, seg_u=36, seg_v=8)
        v = v * np.array([1.15, 0.40, 0.8], dtype=np.float32) + np.array([0, mouth_y, mouth_z + 0.01], dtype=np.float32)
        P.append(Part("jaw", v, f, mat_gold, dynamic=True))

        # Nodos terminales en comisuras
        for side_x, name in ((-0.32, "comm_l"), (0.32, "comm_r")):
            v, f = icosphere(1, 0.032)
            v = v + np.array([side_x, mouth_y, mouth_z + 0.02], dtype=np.float32)
            P.append(Part(name, v, f, mat_teal_glow))

        # 7 Barras vocales del ecualizador neural
        for i in range(7):
            bx = (i - 3) * 0.076
            v, f = cylinder(radius=0.014, height=0.14, segments=10)
            v = v + np.array([bx, mouth_y, mouth_z], dtype=np.float32)
            P.append(Part(f"vocal_bar_{i}", v, f, mat_teal_glow, dynamic=True))

        # 8. Astrolabio Cuántico: Anillo Rúnico Exterior y Giroscopio Interior
        v, f = torus(R=1.86, r=0.026, seg_u=80, seg_v=8)
        P.append(Part("astrolabe_outer", v, f, mat_gold, dynamic=True))

        # 12 Muescas rúnicas en el astrolabio exterior
        for n in range(12):
            ang = (n / 12.0) * math.pi * 2
            nx = math.cos(ang) * 1.86
            ny = math.sin(ang) * 1.86
            v, f = cylinder(radius=0.016, height=0.08, segments=8)
            v = transform_points(mat_rot_z(ang), v) + np.array([nx, ny, 0.0], dtype=np.float32)
            col_m = mat_gold if n % 3 == 0 else mat_teal_glow
            P.append(Part(f"astrolabe_notch_{n}", v, f, col_m, dynamic=True))

        v, f = torus(R=1.56, r=0.018, seg_u=72, seg_v=8)
        P.append(Part("astrolabe_inner", v, f, mat_teal_glow, dynamic=True))

        # 9. Enjambre Orbital de Partículas Cuánticas (8 partículas en 3D)
        for p in range(8):
            v, f = icosphere(1, 0.038)
            mat_p = mat_teal_glow if p % 2 == 0 else mat_gold
            P.append(Part(f"orbit_particle_{p}", v, f, mat_p, dynamic=True))

        # Indices por nombre para animacion
        self.index = {p.name: i for i, p in enumerate(self.parts)}

    # ----------------------------------------------------------- animacion
    def _animate(self, t: float, st: Dict[str, float]) -> Dict[str, np.ndarray]:
        """Calcula la matriz de modelo por pieza segun el estado vocal."""
        mouth = float(st.get("mouth_open", 0.0))
        m_wide = float(st.get("mouth_width", 1.0))
        blink = float(st.get("blink", 0.0))
        pulse = float(st.get("vocal_pulse", 0.0))
        energy = float(st.get("energy", 0.0))

        side = 2.4
        H = side * (math.sqrt(3.0) / 2.0)
        p_apex = np.array([0.0, H * (2.0 / 3.0), 0.16], dtype=np.float32)
        p_left = np.array([-side * 0.5, -H * (1.0 / 3.0), 0.16], dtype=np.float32)
        p_right = np.array([side * 0.5, -H * (1.0 / 3.0), 0.16], dtype=np.float32)
        vertex_pts = [p_apex, p_left, p_right]

        bob = math.sin(t * 1.6) * 0.05
        sway = math.sin(t * 0.8) * 0.02
        nod = math.sin(t * 1.2) * 0.02 + mouth * 0.02
        breath = 1.0 + math.sin(t * 2.4) * 0.012

        base_m = (mat_translate(0.0, bob, 0.0)
                  @ mat_rot_y(sway)
                  @ mat_rot_x(nod)
                  @ mat_scale(breath))

        out: Dict[str, np.ndarray] = {}
        for p in self.parts:
            out[p.name] = base_m

        # Mandíbula / Labio articulado (se abre con la fonética)
        jaw_rot = mat_rot_x(math.radians(24.0) * mouth)
        jaw_drop = mat_translate(0.0, -0.14 * mouth, 0.0)
        jaw_scale = mat_scale(0.95 + 0.12 * m_wide, 1.0, 1.0)
        out["jaw"] = base_m @ mat_translate(0.0, -0.32, 0.20) @ jaw_rot @ jaw_drop @ mat_translate(0.0, 0.32, -0.20) @ jaw_scale

        # Párpado con parpadeo procedural
        out["eyelid"] = (base_m @ mat_translate(0.0, 0.05, 0.21)
                         @ mat_scale(1.0, max(1e-3, blink), 1.0)
                         @ mat_translate(0.0, -0.05, -0.21))

        # Iris central y micro-dilatación
        iris_s = 1.0 + 0.18 * pulse + 0.06 * math.sin(t * 5.0)
        out["iris_core"] = (base_m @ mat_translate(0.0, 0.05, 0.23)
                            @ mat_scale(iris_s, iris_s, 1.0)
                            @ mat_translate(0.0, -0.05, -0.23))

        for idx in range(2):
            k = f"iris_ring_{idx}"
            rs = 1.0 + 0.12 * pulse
            spin = mat_rot_z(t * (0.8 if idx == 0 else -1.2))
            out[k] = (base_m @ mat_translate(0.0, 0.05, 0.22)
                      @ spin @ mat_scale(rs, rs, 1.0)
                      @ mat_translate(0.0, -0.05, -0.22))

        # Pupila reactiva al habla
        pupil_s = 1.0 + 0.32 * pulse
        out["pupil"] = (base_m @ mat_translate(0.0, 0.05, 0.275)
                        @ mat_scale(pupil_s, pupil_s, 1.0)
                        @ mat_translate(0.0, -0.05, -0.275))

        # Nodos de los 3 vértices (anillos pulsando en su centro)
        for idx, pt in enumerate(vertex_pts):
            k = f"node_ring_{idx}"
            ring_pulse = 1.0 + 0.22 * math.sin(t * 6.0 + idx) * max(0.4, pulse + energy)
            out[k] = (base_m @ mat_translate(pt[0], pt[1], pt[2])
                      @ mat_scale(ring_pulse, ring_pulse, 1.0)
                      @ mat_translate(-pt[0], -pt[1], -pt[2]))

        # 7 Barras vocales reactivas palabra a palabra
        for i in range(7):
            k = f"vocal_bar_{i}"
            phase = t * 12.0 + i * 0.85
            amp = (0.2 + 0.8 * abs(math.sin(phase))) * max(0.08, mouth)
            h = 0.35 + 2.8 * amp
            bx = (i - 3) * 0.076
            out[k] = (base_m @ mat_translate(bx, -0.32, 0.20)
                      @ mat_scale(1.0, h, 1.0)
                      @ mat_translate(-bx, 0.32, -0.20))

        # Astrolabio exterior giratorio con 12 muescas
        ast_spin = mat_rot_z(t * 0.26)
        out["astrolabe_outer"] = base_m @ ast_spin
        for n in range(12):
            out[f"astrolabe_notch_{n}"] = base_m @ ast_spin

        # Astrolabio interior en contragiro inclinado
        gyro_spin = mat_rot_x(math.radians(16.0)) @ mat_rot_z(-t * 0.52)
        out["astrolabe_inner"] = base_m @ gyro_spin

        # 8 Partículas orbitales cuánticas en 3D
        for p in range(8):
            p_ang = (p / 8.0) * math.pi * 2 + t * 0.85 * (1 if p % 2 == 0 else -0.7)
            rx = 1.95 + (p % 3) * 0.12
            ry = 1.30 + (p % 2) * 0.10
            px = math.cos(p_ang) * rx
            py = math.sin(p_ang) * ry
            pz = math.sin(p_ang * 2.0 + p) * 0.40
            out[f"orbit_particle_{p}"] = base_m @ mat_translate(px, py, pz)

        return out

    # ------------------------------------------------------------ fondo
    def _bg_cache(self, w: int, h: int) -> Dict[str, np.ndarray]:
        """Buffers estaticos del fondo (degradado, halo, mapa radial) cacheados por resolucion."""
        key = (w, h)
        if getattr(self, "_bgc_key", None) == key:
            return self._bgc
        # Base a resolucion completa: degradado vertical
        grad = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
        base = (COL_BG_TOP[None, None, :] * (1.0 - grad) + COL_BG_BOT[None, None, :] * grad)
        base = np.repeat(base, w, axis=1)
        # El vineteado es estatico: se hornea aqui una sola vez en vez de aplicarse
        # a cada cuadro completo (ahorra una pasada de 25 MB por cuadro).
        yv, xv = np.mgrid[0:h, 0:w].astype(np.float32)
        rv = np.sqrt(((xv - w * 0.5) / (w * 0.62)) ** 2 + ((yv - h * 0.5) / (h * 0.62)) ** 2)
        vig = np.clip(1.0 - 0.34 * np.clip(rv - 0.35, 0.0, None) ** 1.7, 0.25, 1.0)
        base = base * vig[:, :, None]
        base = np.clip(base, 0, 255).astype(np.uint8)   # el lienzo vive en uint8

        # Capas suaves a 1/4 de resolucion (son degradados: el reescalado es imperceptible)
        sw, sh = max(8, w // 4), max(8, h // 4)
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        r = np.sqrt(((xx - sw * 0.5) / (sw * 0.42)) ** 2 + ((yy - sh * 0.46) / (sh * 0.52)) ** 2)
        halo = np.clip(1.0 - r, 0.0, 1.0) ** 2.2

        self._bgc_key = key
        self._bgc = {"base": base, "r_small": r, "halo_small": halo, "sw": sw, "sh": sh}
        return self._bgc

    def _render_background(self, w: int, h: int, t: float, energy: float) -> np.ndarray:
        """Fondo: degradado vertical + halo radial reactivo + ondas acusticas."""
        c = self._bg_cache(w, h)
        r = c["r_small"]

        glow_amt = 0.16 + 0.10 * energy + 0.02 * math.sin(t * 1.7)
        glow = c["halo_small"] * glow_amt

        # Anillos concentricos de onda acustica (calculados en baja resolucion)
        for k in range(3):
            phase = (t * 0.42 + k / 3.0) % 1.0
            rad = 0.30 + phase * 0.95
            band = np.exp(-((r - rad) ** 2) / 0.0016)
            glow += band * (0.13 * (1.0 - phase) * (0.4 + energy))

        layer = np.clip(glow[:, :, None] * COL_TEAL[None, None, :], 0, 255).astype(np.uint8)

        buf = getattr(self, "_frame_buf", None)
        if buf is None or buf.shape[:2] != (h, w) or buf.dtype != np.uint8:
            buf = np.empty((h, w, 3), dtype=np.uint8)
            self._frame_buf = buf
        cv2.add(c["base"], cv2.resize(layer, (w, h), interpolation=cv2.INTER_LINEAR), dst=buf)
        return buf

    # ------------------------------------------------------- sombreado
    def _shade(self, normals: np.ndarray, centroids: np.ndarray, mat: Material,
               boost: float = 1.0) -> np.ndarray:
        """Blinn-Phong vectorizado: difuso + especular + contraluz + emision."""
        view = _normalize_rows(-centroids)
        base = mat.base.astype(np.float32) / 255.0
        diff_albedo = base * (1.0 - 0.55 * mat.metallic)

        col = diff_albedo * 0.26  # ambiente

        for ldir, lcol, inten in (
            (self.light_key, self.key_color, 1.0),
            (self.light_fill, self.fill_color, 0.42),
            (self.light_back, self.back_color, 0.30),
        ):
            ndl = np.clip(normals @ ldir, 0.0, 1.0)[:, None]
            col = col + diff_albedo * lcol[None, :] * ndl * inten

            half = _normalize_rows(ldir[None, :] + view)
            ndh = np.clip(np.sum(normals * half, axis=1), 0.0, 1.0)[:, None]
            spec_col = base if mat.metallic > 0.5 else np.ones(3, dtype=np.float32)
            col = col + spec_col * lcol[None, :] * (ndh ** mat.shininess) * mat.specular * inten

        # Contraluz (fresnel aproximado)
        ndv = np.clip(np.sum(normals * view, axis=1), 0.0, 1.0)[:, None]
        fres = (1.0 - ndv) ** 3.0
        col = col + COL_TEAL[None, :] / 255.0 * fres * mat.rim * 0.55

        # Emision
        if mat.emissive > 0.0:
            col = col + base * mat.emissive * boost

        return np.clip(col * 255.0, 0.0, 255.0)

    # ----------------------------------------------------------- render
    def render_frame(
        self,
        t: float,
        width: int = 3840,
        height: int = 2160,
        state: Optional[Dict[str, float]] = None,
        char_scale: float = 1.0,
        center: Tuple[float, float] = (0.5, 0.47),
    ) -> np.ndarray:
        """Renderiza un cuadro RGB uint8 (H,W,3) del personaje animado."""
        st = state or {}
        energy = float(st.get("energy", 0.0))
        emis_boost = 1.0 + 0.55 * float(st.get("vocal_pulse", 0.0))

        canvas = self._render_background(width, height, t, energy)

        mats = self._animate(t, st)

        # Camara: el personaje se mira desde el frente, ligeramente elevado
        cam_dist = 6.05
        view = (mat_translate(0.0, -0.10, cam_dist)
                @ mat_rot_x(math.radians(-4.0))
                @ mat_rot_y(math.pi))   # la cara (+Z del modelo) queda frente a la camara

        f_len = 3.05 * char_scale
        base_dim = min(width, height)
        cx = width * center[0]
        cy = height * center[1]

        tri_pts: List[np.ndarray] = []
        tri_depth: List[np.ndarray] = []
        tri_col: List[np.ndarray] = []

        for part in self.parts:
            M = mats.get(part.name, mat_identity())
            wv = transform_points(M, part.vertices)
            vv = transform_points(view, wv)

            tri = vv[part.faces]                       # (M,3,3)
            v0, v1, v2 = tri[:, 0], tri[:, 1], tri[:, 2]
            nrm = np.cross(v1 - v0, v2 - v0)
            nl = np.linalg.norm(nrm, axis=1, keepdims=True)
            nl[nl == 0.0] = 1.0
            nrm = nrm / nl
            cen = (v0 + v1 + v2) / 3.0

            # Descarte de caras traseras y de las que quedan tras la camara
            facing = np.sum(nrm * (-cen), axis=1) > 0.0
            in_front = np.all(tri[:, :, 2] > 0.35, axis=1)
            keep = facing & in_front
            if not np.any(keep):
                continue

            tri_k = tri[keep]
            nrm_k = nrm[keep]
            cen_k = cen[keep]

            # Proyeccion en perspectiva
            z = tri_k[:, :, 2]
            sx = cx + (tri_k[:, :, 0] * f_len / z) * base_dim * 0.5
            sy = cy - (tri_k[:, :, 1] * f_len / z) * base_dim * 0.5
            pts = np.stack([sx, sy], axis=2)

            # Descarte de triangulos fuera de pantalla
            vis = ((pts[:, :, 0].max(axis=1) >= 0) & (pts[:, :, 0].min(axis=1) < width) &
                   (pts[:, :, 1].max(axis=1) >= 0) & (pts[:, :, 1].min(axis=1) < height))
            if not np.any(vis):
                continue

            cols = self._shade(nrm_k[vis], cen_k[vis], part.material, boost=emis_boost)
            tri_pts.append(np.round(pts[vis]).astype(np.int32))
            tri_depth.append(cen_k[vis][:, 2])
            tri_col.append(cols)

        if tri_pts:
            allp = np.concatenate(tri_pts, axis=0)
            alld = np.concatenate(tri_depth, axis=0)
            allc = np.concatenate(tri_col, axis=0)

            order = np.argsort(-alld)          # painter: lejano -> cercano
            allp = allp[order]
            allc = allc[order]

            surf = canvas
            for i in range(allp.shape[0]):
                c = allc[i]
                cv2.fillConvexPoly(
                    surf, allp[i],
                    (int(c[0]), int(c[1]), int(c[2])),
                    lineType=cv2.LINE_AA
                )
            canvas = surf

        return canvas

    # ------------------------------------------------------ post-proceso
    _vig_cache: Dict[Tuple[int, int, float], np.ndarray] = {}

    @classmethod
    def _vignette_u8(cls, w: int, h: int, amount: float) -> np.ndarray:
        """Mapa de vineteado como uint8 (0-255 = factor 0.0-1.0)."""
        key = (w, h, round(amount, 3))
        m = cls._vig_cache.get(key)
        if m is None:
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            r = np.sqrt(((xx - w * 0.5) / (w * 0.62)) ** 2 + ((yy - h * 0.5) / (h * 0.62)) ** 2)
            v = np.clip(1.0 - amount * np.clip(r - 0.35, 0.0, None) ** 1.7, 0.25, 1.0)
            m = np.repeat((v * 255.0).astype(np.uint8)[:, :, None], 3, axis=2)
            cls._vig_cache.clear()
            cls._vig_cache[key] = m
        return m

    _u8_cache: Dict[Tuple[int, int], np.ndarray] = {}

    _bloom_cache: Dict[Tuple[int, int], np.ndarray] = {}

    @classmethod
    def _bloom_buf(cls, w: int, h: int) -> np.ndarray:
        buf = cls._bloom_cache.get((w, h))
        if buf is None:
            buf = np.empty((h, w, 3), dtype=np.uint8)
            cls._bloom_cache.clear()
            cls._bloom_cache[(w, h)] = buf
        return buf

    @classmethod
    def _u8_buf(cls, w: int, h: int) -> np.ndarray:
        buf = cls._u8_cache.get((w, h))
        if buf is None:
            buf = np.empty((h, w, 3), dtype=np.uint8)
            cls._u8_cache.clear()
            cls._u8_cache[(w, h)] = buf
        return buf

    @classmethod
    def post_process(cls, img: np.ndarray, bloom: float = 0.55, vignette: float = 0.0,
                     grain: float = 0.0, chroma: float = 0.0, seed: int = 0) -> np.ndarray:
        """
        Bloom + vineteado + grano sobre uint8.

        Trabajar en uint8 en lugar de float32 reduce a la cuarta parte el trafico
        de memoria: a 3840x2160 cada buffer float pesa 99 MB y el post-proceso
        estaba dominado por el ancho de banda, no por el calculo.
        """
        h, w = img.shape[:2]
        if img.dtype == np.uint8:
            out = img                      # el rasterizador ya entrega uint8: sin copia
        else:
            out = cls._u8_buf(w, h)
            cv2.convertScaleAbs(img, dst=out)

        if bloom > 0.0:
            sw, sh = max(8, w // 8), max(8, h // 8)
            small = cv2.resize(out, (sw, sh), interpolation=cv2.INTER_AREA).astype(np.float32)
            np.subtract(small, 150.0, out=small)
            np.clip(small, 0.0, None, out=small)
            cv2.GaussianBlur(small, (0, 0), sigmaX=max(1.5, sw / 26.0), dst=small)
            np.multiply(small, bloom, out=small)
            np.clip(small, 0.0, 255.0, out=small)
            bl = cls._bloom_buf(w, h)
            cv2.resize(small.astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR, dst=bl)
            cv2.add(out, bl, dst=out)          # suma saturante: bloom sin desbordes

        if vignette > 0.0:
            cv2.multiply(out, cls._vignette_u8(w, h, vignette), dst=out, scale=1.0 / 255.0)

        if grain > 0.0:
            rng = np.random.default_rng(seed)
            n = rng.normal(0.0, grain, (max(4, h // 4), max(4, w // 4), 1)).astype(np.float32)
            n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)
            nb = np.repeat(np.clip(n + 128.0, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2)
            cv2.addWeighted(out, 1.0, nb, 0.06, -0.06 * 128.0, dst=out)

        return out


def get_character_3d_renderer(quality: str = "high") -> Character3DRenderer:
    return Character3DRenderer.get_instance(quality=quality)
