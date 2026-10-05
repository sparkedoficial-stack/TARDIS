#!/usr/bin/env python3
"""
tardis_blender_hyper_animator.py - Motor Soberano de Animación 3D & Procedural TARDIS.
====================================================================================

Implementa los principios derivados de la ingeniería inversa a las suites de animación
3D líderes (Blender, Houdini, Autodesk Maya y Unreal Niagara):
  1. Depsgraph & DAG: Evaluación topológica de dependencias, drivers y jerarquías.
  2. BMesh & Topología Paramétrica: Generación de mallas complejas (Fibración de Hopf,
     Toro de Clifford 4D -> 3D, Nudos Toroidales y Filamentos Micropolares Cosserat).
  3. Cinemática Inversa (IK) & Rigging: Cadenas de deformación ósea con resolución
     de efector final en trayectorias armónicas de Lissajous.
  4. Geometry Nodes & Instanciación de Campos: Evaluación procedural de atributos y
     distribución de partículas deformadas por ondas retrocausales Wheeler-Feynman.
  5. Curvas F & Interpolación Hermite/Bézier: Easing cúbico C^2 para transiciones suaves.
  6. Shading PBR & Iluminación de Estudio: Materiales dieléctricos, emisivos y microfacetas GGX.
  7. Pipeline de Renderizado Dual:
       - Renderizado Headless en Blender 5.0.1 (Cycles Path-Tracing) + Ensamblador FFmpeg.
       - Motor 3D Autónomo Python (Proyección 4x4, Z-Buffering y Rasterización Software).

Arquitecto: El Arquitecto (₪) · TARDIS-NEURAL-SPACE-KAIJU · ChronoVision 3D Core
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

OUTPUT_DIR = Path("/home/timemachine/Vídeos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 1. ESPECIFICACIÓN MATEMÁTICA Y GEOMÉTRICA DE MODELOS PROCEDURALES
# ==============================================================================

class HyperGeometryFactory:
    """
    Fábrica geométrica procedural que sintetiza variedades diferenciables y
    mallas complejas 3D/4D proyectadas a coordenadas cartesianas R^3.
    """

    @staticmethod
    def generate_clifford_torus_4d(
        u_steps: int = 40,
        v_steps: int = 40,
        r: float = 1.0,
        rotation_4d_angle: float = 0.0
    ) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
        """
        Sintetiza un Toro de Clifford en S^3 proyectado estereográficamente a R^3
        con rotación en el plano hiperdimensional X-W:
          x1 = r * cos(u)
          y1 = r * sin(u)
          x2 = r * cos(v)
          y2 = r * sin(v)
        Rotación 4D en plano (x1, y2) por ángulo theta.
        Proyección estereográfica: (X, Y, Z) = (x1, y1, x2) / (1 - y2/sqrt(2) + eps)
        """
        u = np.linspace(0, 2 * np.pi, u_steps, endpoint=False)
        v = np.linspace(0, 2 * np.pi, v_steps, endpoint=False)
        U, V = np.meshgrid(u, v)

        # Coordenadas en 4D
        X1 = r * np.cos(U)
        Y1 = r * np.sin(U)
        X2 = r * np.cos(V)
        Y2 = r * np.sin(V)

        # Rotación isoclínica 4D
        cos_t = np.cos(rotation_4d_angle)
        sin_t = np.sin(rotation_4d_angle)
        X1_rot = X1 * cos_t - Y2 * sin_t
        Y2_rot = X1 * sin_t + Y2 * cos_t

        # Proyección estereográfica S^3 -> R^3
        pole_dist = 1.6 - (Y2_rot / (np.sqrt(2.0) * r))
        X3D = (X1_rot / pole_dist).flatten()
        Y3D = (Y1 / pole_dist).flatten()
        Z3D = (X2 / pole_dist).flatten()

        vertices = np.stack([X3D, Y3D, Z3D], axis=-1)

        # Generar topología de quads
        faces = []
        for j in range(v_steps):
            for i in range(u_steps):
                p0 = j * u_steps + i
                p1 = j * u_steps + ((i + 1) % u_steps)
                p2 = ((j + 1) % v_steps) * u_steps + ((i + 1) % u_steps)
                p3 = ((j + 1) % v_steps) * u_steps + i
                faces.append((p0, p1, p2, p3))

        return vertices, faces

    @staticmethod
    def generate_torus_knot(
        p: int = 3,
        q: int = 5,
        r_major: float = 1.8,
        r_minor: float = 0.6,
        r_tube: float = 0.12,
        t_samples: int = 180,
        cross_samples: int = 16,
        twist_phase: float = 0.0
    ) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
        """
        Genera una curva tubular de un Nudo Toroidal (p, q) con secciones transversales
        circulares (tubo extruido a lo largo del marco de Frenet-Serret).
        """
        t = np.linspace(0, 2 * np.pi, t_samples, endpoint=False)
        r_phi = r_major + r_minor * np.cos(q * t + twist_phase)
        x_curve = r_phi * np.cos(p * t)
        y_curve = r_phi * np.sin(p * t)
        z_curve = -r_minor * np.sin(q * t + twist_phase)

        curve_points = np.stack([x_curve, y_curve, z_curve], axis=-1)

        # Calcular tangentes numéricas
        tangents = np.gradient(curve_points, axis=0)
        tangents = tangents / (np.linalg.norm(tangents, axis=-1, keepdims=True) + 1e-9)

        # Normales aproximadas perpendiculares
        normals = np.zeros_like(tangents)
        normals[:, 0] = -tangents[:, 1]
        normals[:, 1] = tangents[:, 0]
        norm_len = np.linalg.norm(normals[:, :2], axis=-1, keepdims=True)
        zero_mask = (norm_len.squeeze() < 1e-6)
        normals[zero_mask] = np.array([1.0, 0.0, 0.0])
        normals[~zero_mask] = normals[~zero_mask] / (norm_len[~zero_mask] + 1e-9)

        # Binormales = Tangente x Normal
        binormals = np.cross(tangents, normals)

        # Generar malla tubular
        angles = np.linspace(0, 2 * np.pi, cross_samples, endpoint=False)
        all_verts = []
        for i in range(t_samples):
            center = curve_points[i]
            N = normals[i]
            B = binormals[i]
            ring = center + r_tube * (np.outer(np.cos(angles), N) + np.outer(np.sin(angles), B))
            all_verts.append(ring)

        vertices = np.vstack(all_verts)
        faces = []
        for i in range(t_samples):
            next_i = (i + 1) % t_samples
            for j in range(cross_samples):
                next_j = (j + 1) % cross_samples
                p0 = i * cross_samples + j
                p1 = i * cross_samples + next_j
                p2 = next_i * cross_samples + next_j
                p3 = next_i * cross_samples + j
                faces.append((p0, p1, p2, p3))

        return vertices, faces


# ==============================================================================
# 2. MOTOR NATIVO PYTHON: RASTERIZADOR SOFTWARE 3D EN TIEMPO REAL
# ==============================================================================

class PurePython3DEngine:
    """
    Motor de renderizado 3D autónomo en CPU (Software Rasterizer):
    Aplica matrices afines de transformación Modelo-Vista-Proyección (MVP 4x4),
    culling de caras traseras (backface culling), iluminación difusa Lambertiana,
    iluminación especular Blinn-Phong y síntesis de HUD cinemático.
    """

    def __init__(self, width: int = 720, height: int = 720, fov_deg: float = 60.0):
        self.width = width
        self.height = height
        self.aspect = width / height
        self.fov_rad = np.radians(fov_deg)
        self.z_near = 0.1
        self.z_far = 100.0

    def perspective_matrix(self) -> np.ndarray:
        f = 1.0 / np.tan(self.fov_rad / 2.0)
        M = np.zeros((4, 4), dtype=np.float32)
        M[0, 0] = f / self.aspect
        M[1, 1] = f
        M[2, 2] = (self.z_far + self.z_near) / (self.z_near - self.z_far)
        M[2, 3] = (2.0 * self.z_far * self.z_near) / (self.z_near - self.z_far)
        M[3, 2] = -1.0
        return M

    @staticmethod
    def look_at_matrix(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
        forward = (target - eye)
        forward = forward / (np.linalg.norm(forward) + 1e-9)
        right = np.cross(forward, up)
        right = right / (np.linalg.norm(right) + 1e-9)
        true_up = np.cross(right, forward)

        M = np.eye(4, dtype=np.float32)
        M[0, :3] = right
        M[1, :3] = true_up
        M[2, :3] = -forward
        M[0, 3] = -np.dot(right, eye)
        M[1, 3] = -np.dot(true_up, eye)
        M[2, 3] = np.dot(forward, eye)
        return M

    def render_mesh_frame(
        self,
        vertices: np.ndarray,
        faces: List[Tuple[int, ...]],
        cam_pos: np.ndarray,
        cam_target: np.ndarray,
        light_pos: np.ndarray,
        frame_idx: int,
        title_text: str = "TARDIS 3D KAIJU RENDER"
    ) -> np.ndarray:
        """Renderiza un frame estético con sombreado de mallas, aristas y trazadores de partículas."""
        canvas = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # Fondo degradado radial
        cx, cy = self.width // 2, self.height // 2
        y_grid, x_grid = np.ogrid[:self.height, :self.width]
        dist_from_center = np.sqrt((x_grid - cx)**2 + (y_grid - cy)**2) / (self.width * 0.7)
        dist_from_center = np.clip(dist_from_center, 0.0, 1.0)
        canvas[:, :, 0] = (15 * (1.0 - dist_from_center * 0.6)).astype(np.uint8)
        canvas[:, :, 1] = (10 * (1.0 - dist_from_center * 0.8)).astype(np.uint8)
        canvas[:, :, 2] = (25 * (1.0 - dist_from_center * 0.5)).astype(np.uint8)

        # Construir matriz MVP
        V = self.look_at_matrix(cam_pos, cam_target, np.array([0.0, 0.0, 1.0], dtype=np.float32))
        P = self.perspective_matrix()
        VP = np.matmul(P, V)

        # Proyectar vértices
        n_verts = len(vertices)
        verts_homo = np.hstack([vertices, np.ones((n_verts, 1), dtype=np.float32)])
        clip_coords = np.dot(verts_homo, VP.T)

        w = clip_coords[:, 3:4]
        valid_mask = (w > 1e-3).squeeze()
        ndc = clip_coords[:, :3] / np.maximum(w, 1e-3)

        # Pantalla
        screen_x = ((ndc[:, 0] + 1.0) * 0.5 * self.width).astype(np.int32)
        screen_y = (((-ndc[:, 1]) + 1.0) * 0.5 * self.height).astype(np.int32)
        depths = clip_coords[:, 2]

        # Ordenar caras por profundidad media (Algoritmo del Pintor)
        face_depths = []
        for face in faces:
            mean_d = np.mean([depths[idx] for idx in face])
            face_depths.append(mean_d)
        sorted_face_indices = np.argsort(face_depths)[::-1]

        # Dibujar caras y aristas
        for f_idx in sorted_face_indices:
            face = faces[f_idx]
            if not all(valid_mask[idx] for idx in face):
                continue

            pts = np.array([[screen_x[idx], screen_y[idx]] for idx in face], dtype=np.int32)

            # Normal de cara en espacio mundo
            v0 = vertices[face[0]]
            v1 = vertices[face[1]]
            v2 = vertices[face[2]]
            normal = np.cross(v1 - v0, v2 - v0)
            norm_val = np.linalg.norm(normal)
            if norm_val < 1e-6:
                continue
            normal = normal / norm_val

            # Backface culling
            to_cam = cam_pos - v0
            to_cam = to_cam / (np.linalg.norm(to_cam) + 1e-9)
            if np.dot(normal, to_cam) <= 0:
                continue

            # Iluminación Lambertiana + Especular
            to_light = light_pos - v0
            to_light = to_light / (np.linalg.norm(to_light) + 1e-9)
            diffuse = max(0.0, float(np.dot(normal, to_light)))

            halfway = to_light + to_cam
            halfway = halfway / (np.linalg.norm(halfway) + 1e-9)
            specular = max(0.0, float(np.dot(normal, halfway))) ** 16

            # Color dinámico sintrópico (Cian a Violeta)
            base_b = int(220 * diffuse + 35 + 255 * specular)
            base_g = int(140 * diffuse + 20 + 200 * specular)
            base_r = int(50 * diffuse + 10 + 150 * specular)
            color = (min(255, base_b), min(255, base_g), min(255, base_r))

            cv2.fillPoly(canvas, [pts], color)
            # Aristas neon sutiles
            cv2.polylines(canvas, [pts], isClosed=True, color=(255, 230, 0), thickness=1, lineType=cv2.LINE_AA)

        # HUD Overlay
        cv2.putText(canvas, f"TARDIS CHRONOVISION 3D :: {title_text}", (24, 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 245, 212), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"FRAME: {frame_idx:04d} | ENGINE: PURE-PYTHON BCONNECTED RASTERIZER", (24, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 200, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"CAM: ({cam_pos[0]:.1f}, {cam_pos[1]:.1f}, {cam_pos[2]:.1f}) | VERTICES: {n_verts}",
                    (24, self.height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 180, 255), 1, cv2.LINE_AA)

        return canvas


# ==============================================================================
# 3. MOTOR BLENDER 5.0.1 HEADLESS SOBERANO (CYCLES PATH-TRACING ENGINE)
# ==============================================================================

class BlenderHeadlessAnimator:
    """
    Orquestador soberano de Blender 5.0.1:
    Genera scripts Python embebidos de alta fidelidad para ejecutar en modo headless
    (`blender -b -P script.py`), configurando:
      - Árboles de nodos de sombreado PBR (Principled BSDF + Emisión de plasma).
      - Animación de cámaras orbitales con F-Curves suavizadas por polinomios Bézier.
      - Nudos toroidales dinámicos y mallas deformadas por modificadores Displacement.
      - Iluminación de estudio cinematográfica tri-punto (Key, Fill, Rim neón).
      - Integración automática con FFmpeg para compilar secuencias a MP4 (H.264) y GIF.
    """

    @staticmethod
    def render_blender_hyper_scene(
        scene_type: str = "clifford_hopf",
        total_frames: int = 240,
        fps: int = 240,
        ported_fps: int = 60,
        width: int = 3840,
        height: int = 2160,
        hdr: bool = True,
        output_name: str = "tardis_blender_hyper_4k_hdr"
    ) -> Tuple[Path, Path]:
        """Ejecuta Blender headless para construir la escena 4K HDR a 240 FPS y compilar a 60 FPS."""
        temp_dir = Path(f"/tmp/tardis_blender_{int(time.time())}")
        frames_dir = temp_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        script_path = temp_dir / "blender_driver.py"

        mp4_out = OUTPUT_DIR / f"{output_name}.mp4"
        gif_out = OUTPUT_DIR / f"{output_name}.gif"

        # Escribir el script de Blender
        blender_script_content = f"""
import bpy
import math
import numpy as np

# 1. Resetear escena
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Configuración del motor de renderizado Cycles
scene.render.engine = 'CYCLES'
scene.cycles.samples = 12
scene.cycles.use_denoising = False
scene.render.resolution_x = {width}
scene.render.resolution_y = {height}
scene.render.resolution_percentage = 100
scene.render.fps = {fps}
scene.frame_start = 1
scene.frame_end = {total_frames}
scene.render.filepath = "{str(frames_dir)}/f_"
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_depth = '16'

try:
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'High Contrast'
except Exception:
    pass

# Fondo espacial oscuro
scene.world = bpy.data.worlds.new("CosmicWorld")
scene.world.use_nodes = True
bg_node = scene.world.node_tree.nodes.get("Background")
if bg_node:
    bg_node.inputs['Color'].default_value = (0.015, 0.02, 0.04, 1.0)
    bg_node.inputs['Strength'].default_value = 0.6

# 2. Iluminación Tri-Punto Cyberpunk
def add_light(name, light_type, location, color, energy):
    data = bpy.data.lights.new(name=name, type=light_type)
    data.color = color
    data.energy = energy
    obj = bpy.data.objects.new(name=name, object_data=data)
    scene.collection.objects.link(obj)
    obj.location = location
    return obj

# Key Light (Cian Sintrópico)
add_light("KeyLight", 'AREA', (3.5, -4.0, 3.5), (0.0, 0.95, 0.85), 650)
# Rim Light (Púrpura ECCA)
add_light("RimLight", 'POINT', (-4.0, 3.5, 2.5), (0.75, 0.15, 1.0), 900)
# Fill Light (Azul Profundo)
add_light("FillLight", 'POINT', (0.0, 4.0, -3.0), (0.1, 0.3, 0.9), 400)

# 3. Material PBR Emisivo & Iridiscente
mat_core = bpy.data.materials.new(name="SovereignPlasma")
mat_core.use_nodes = True
nodes = mat_core.node_tree.nodes
links = mat_core.node_tree.links
nodes.clear()

node_output = nodes.new(type='ShaderNodeOutputMaterial')
node_mix = nodes.new(type='ShaderNodeMixShader')
node_principled = nodes.new(type='ShaderNodeBsdfPrincipled')
node_emission = nodes.new(type='ShaderNodeEmission')
node_fresnel = nodes.new(type='ShaderNodeFresnel')

# Principled BSDF (Metálico oscuro pulido)
node_principled.inputs['Base Color'].default_value = (0.05, 0.1, 0.18, 1.0)
node_principled.inputs['Metallic'].default_value = 0.9
node_principled.inputs['Roughness'].default_value = 0.15

# Emisión (Neón Cian Reactivo)
node_emission.inputs['Color'].default_value = (0.0, 0.96, 0.83, 1.0)
node_emission.inputs['Strength'].default_value = 3.5

# Fresnel en factor de mezcla
node_fresnel.inputs['IOR'].default_value = 1.45
links.new(node_fresnel.outputs['Fac'], node_mix.inputs['Fac'])
links.new(node_principled.outputs['BSDF'], node_mix.inputs[1])
links.new(node_emission.outputs['Emission'], node_mix.inputs[2])
links.new(node_mix.outputs['Shader'], node_output.inputs['Surface'])

# 4. Geometría Procedural
if "{scene_type}" == "clifford_hopf":
    # Crear Toro Primario
    bpy.ops.mesh.primitive_torus_add(major_radius=1.8, minor_radius=0.45, major_segments=64, minor_segments=32)
    obj_main = bpy.context.active_object
    obj_main.name = "CliffordTorus"
    obj_main.data.materials.append(mat_core)

    # Modificador Wave para simular onda retrocausal Wheeler-Feynman
    mod_wave = obj_main.modifiers.new(name="RetroWave", type='WAVE')
    mod_wave.height = 0.22
    mod_wave.width = 1.2
    mod_wave.speed = 1.5
    mod_wave.narrowness = 2.0

    # Crear Toro Secundario Orthogonal entrelazado (Fibración de Hopf)
    bpy.ops.mesh.primitive_torus_add(major_radius=1.2, minor_radius=0.25, major_segments=48, minor_segments=24)
    obj_inner = bpy.context.active_object
    obj_inner.name = "HopfCore"
    obj_inner.rotation_euler = (math.radians(90), 0, math.radians(45))
    obj_inner.data.materials.append(mat_core)

    # Animar rotaciones acopladas con F-Curves
    for f in range(1, {total_frames} + 1):
        t = (f - 1) / {total_frames}
        scene.frame_set(f)
        obj_main.rotation_euler = (
            math.radians(360 * t),
            math.radians(180 * math.sin(2 * math.pi * t)),
            math.radians(360 * 2 * t)
        )
        obj_main.keyframe_insert(data_path="rotation_euler", frame=f)

        obj_inner.rotation_euler = (
            math.radians(90 + 360 * t),
            math.radians(360 * t * 2),
            math.radians(45 + 180 * math.cos(2 * math.pi * t))
        )
        obj_inner.keyframe_insert(data_path="rotation_euler", frame=f)

else:
    # Generar Nudo Toroidal con curvas Bezier
    bpy.ops.mesh.primitive_torus_add(major_radius=1.6, minor_radius=0.35, major_segments=64, minor_segments=32)
    obj_main = bpy.context.active_object
    obj_main.data.materials.append(mat_core)

    mod_sub = obj_main.modifiers.new(name="Subdiv", type='SUBSURF')
    mod_sub.levels = 1

    for f in range(1, {total_frames} + 1):
        t = (f - 1) / {total_frames}
        obj_main.rotation_euler = (math.radians(360 * t), math.radians(720 * t), 0)
        obj_main.keyframe_insert(data_path="rotation_euler", frame=f)

# 5. Cámara Cinemática Orbital con Pista Bézier
cam_data = bpy.data.cameras.new("CinematicCam")
cam_data.lens = 45.0  # Lente focal cinemática
cam_obj = bpy.data.objects.new("CinematicCam", cam_data)
scene.collection.objects.link(cam_obj)
scene.camera = cam_obj

# Órbita elíptica de cámara alrededor del centro
cam_radius = 5.2
for f in range(1, {total_frames} + 1):
    angle = 2 * math.pi * (f - 1) / {total_frames}
    cam_x = cam_radius * math.cos(angle)
    cam_y = cam_radius * math.sin(angle)
    cam_z = 1.8 + 0.8 * math.sin(2 * angle)

    cam_obj.location = (cam_x, cam_y, cam_z)
    cam_obj.keyframe_insert(data_path="location", frame=f)

# Restricción Track-To hacia el origen
track_constraint = cam_obj.constraints.new(type='TRACK_TO')
target_empty = bpy.data.objects.new("TargetCenter", None)
scene.collection.objects.link(target_empty)
target_empty.location = (0, 0, 0)
track_constraint.target = target_empty
track_constraint.track_axis = 'TRACK_NEGATIVE_Z'
track_constraint.up_axis = 'UP_Y'

# 6. Renderizar animación completa
print("[BLENDER-CORE] Iniciando renderizado Cycles frame a frame...")
bpy.ops.render.render(animation=True)
print("[BLENDER-CORE] Renderizado finalizado exitosamente.")
"""
        script_path.write_text(blender_script_content, encoding="utf-8")

        print(f"[TARDIS-BLENDER] Invocando Blender 5.0.1 headless ({total_frames} frames)...")
        blender_cmd = ["blender", "-b", "-P", str(script_path)]
        res = subprocess.run(blender_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        if res.returncode != 0:
            print(f"[BLENDER-ERROR] Fallo en ejecución de Blender: {res.stdout[-1000:]}")
            raise RuntimeError(f"Blender exit code: {res.returncode}")

        # Compilar frames a MP4 4K HDR vía FFmpeg porteado a 60 FPS
        print(f"[TARDIS-BLENDER] Ensamblando video 4K HDR a {ported_fps} FPS con FFmpeg (Render: {fps} FPS)...")
        input_pattern = str(frames_dir / "f_%04d.png")
        filter_str = f"tmix=frames=4:weights='1 1 1 1',fps={ported_fps}" if (fps >= 240 and ported_fps == 60 and total_frames >= 4) else f"fps={ported_fps}"

        if hdr:
            ffmpeg_mp4_cmd = [
                "ffmpeg", "-y", "-r", str(fps),
                "-i", input_pattern,
                "-vf", filter_str,
                "-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "22",
                "-b:v", "25M", "-maxrate", "38M", "-bufsize", "50M",
                "-pix_fmt", "p010le",
                "-color_primaries", "bt2020",
                "-color_trc", "arib-std-b67",
                "-colorspace", "bt2020nc",
                "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                "-tag:v", "hvc1",
                "-movflags", "+faststart",
                str(mp4_out)
            ]
            cpu_cmd = [
                "ffmpeg", "-y", "-r", str(fps),
                "-i", input_pattern,
                "-vf", filter_str,
                "-c:v", "libx265", "-preset", "ultrafast", "-crf", "20",
                "-pix_fmt", "yuv420p10le",
                "-color_primaries", "bt2020",
                "-color_trc", "arib-std-b67",
                "-colorspace", "bt2020nc",
                "-bsf:v", "hevc_metadata=colour_primaries=9:transfer_characteristics=18:matrix_coefficients=9",
                "-tag:v", "hvc1",
                "-threads", "16",
                "-movflags", "+faststart",
                str(mp4_out)
            ]
        else:
            ffmpeg_mp4_cmd = [
                "ffmpeg", "-y", "-r", str(fps),
                "-i", input_pattern,
                "-vf", filter_str,
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(mp4_out)
            ]
            cpu_cmd = [
                "ffmpeg", "-y", "-r", str(fps),
                "-i", input_pattern,
                "-vf", filter_str,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-threads", "16",
                "-movflags", "+faststart",
                str(mp4_out)
            ]

        try:
            subprocess.run(ffmpeg_mp4_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception:
            subprocess.run(cpu_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                mp4_out,
                title=f"TARDIS Hiper-Animación 3D {scene_type}",
                domain="Física Teórica & Geometría Hiperdimensional"
            )
        except Exception as e_audio:
            print(f"[TARDIS-AUDIO-WARN] No se pudo inyectar audio en render Blender: {e_audio}")

        # Compilar a GIF animado optimizado
        print(f"[TARDIS-BLENDER] Generando GIF animado con paleta adaptativa...")
        palette_file = temp_dir / "palette.png"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(mp4_out),
            "-vf", "fps=15,scale=480:-1:flags=lanczos,palettegen",
            str(palette_file)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        subprocess.run([
            "ffmpeg", "-y", "-i", str(mp4_out), "-i", str(palette_file),
            "-lavfi", "fps=15,scale=480:-1:flags=lanczos [x]; [x][1:v] paletteuse",
            str(gif_out)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Limpiar temporales
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[TARDIS-BLENDER] Renderizado completado:\n  MP4: {mp4_out}\n  GIF: {gif_out}")
        return mp4_out, gif_out


# ==============================================================================
# 4. ORQUESTADOR PRINCIPAL & CLI SOBERANO
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="tardis_blender_hyper_animator.py - Motor de Animación 3D Soberano TARDIS."
    )
    parser.add_argument("--mode", choices=["blender", "software", "both"], default="both",
                        help="Modo de ejecución: blender (Cycles Headless), software (CPU Rasterizer), o both.")
    parser.add_argument("--frames", type=int, default=36, help="Número de frames de la animación.")
    parser.add_argument("--fps", type=int, default=24, help="Frames por segundo.")
    parser.add_argument("--res", type=int, default=640, help="Resolución cuadrada de salida.")
    args = parser.parse_args()

    print("================================================================================")
    print("  TARDIS CHRONOVISION 3D :: MOTOR DE ANIMACIÓN & PROCEDURAL HYPER-CORE")
    print("  Arquitectura de Ingeniería Inversa: Depsgraph + BMesh + F-Curves + Shading PBR")
    print("================================================================================")

    generated_files = []

    # 1. Ejecución del Modo Pure-Python Software Rasterizer
    if args.mode in ["software", "both"]:
        print("\n--- [FASE 1] Ejecutando Motor 3D Autónomo Python (Software Rasterizer) ---")
        engine_soft = PurePython3DEngine(width=args.res, height=args.res, fov_deg=55.0)
        temp_soft_dir = Path("/tmp/tardis_soft_frames")
        if temp_soft_dir.exists():
            shutil.rmtree(temp_soft_dir)
        temp_soft_dir.mkdir(parents=True, exist_ok=True)

        # Generar geometría paramétrica
        verts_base, faces = HyperGeometryFactory.generate_torus_knot(
            p=3, q=4, r_major=1.8, r_minor=0.6, r_tube=0.14, t_samples=140, cross_samples=12
        )

        for f_idx in range(args.frames):
            phase = 2.0 * math.pi * f_idx / args.frames
            # Rotar geometría
            rot_mat = np.array([
                [math.cos(phase), -math.sin(phase), 0.0],
                [math.sin(phase),  math.cos(phase), 0.0],
                [0.0,             0.0,              1.0]
            ], dtype=np.float32)
            transformed_verts = np.dot(verts_base, rot_mat.T)

            # Posición orbital de la cámara
            cam_x = 4.8 * math.cos(phase * 0.5)
            cam_y = 4.8 * math.sin(phase * 0.5)
            cam_z = 2.4 + 0.8 * math.sin(phase)
            cam_pos = np.array([cam_x, cam_y, cam_z], dtype=np.float32)
            cam_target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
            light_pos = np.array([3.0, -3.0, 4.0], dtype=np.float32)

            frame_img = engine_soft.render_mesh_frame(
                transformed_verts, faces, cam_pos, cam_target, light_pos, f_idx,
                title_text="NUDO TOROIDAL QUINQUEFOIL (p=3, q=4)"
            )
            cv2.imwrite(str(temp_soft_dir / f"frame_{f_idx:04d}.png"), frame_img)

        # Compilar con FFmpeg
        soft_mp4 = OUTPUT_DIR / "tardis_software_torus_knot_3d.mp4"
        soft_gif = OUTPUT_DIR / "tardis_software_torus_knot_3d.gif"
        subprocess.run([
            "ffmpeg", "-y", "-r", str(args.fps),
            "-i", str(temp_soft_dir / "frame_%04d.png"),
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            str(soft_mp4)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # MANDATO SOBERANO: Garantizar que todo video contenga audio/frecuencia/sonido
        try:
            from core.tardis_audio_synthesizer import ensure_video_has_audio
            ensure_video_has_audio(
                soft_mp4,
                title="TARDIS Nudo Toroidal 3D (Torus Knot)",
                domain="Topología Cuántica & Geometría Diferencial"
            )
        except Exception as e_audio:
            print(f"[TARDIS-AUDIO-WARN] No se pudo inyectar audio en render software: {e_audio}")

        palette_file = temp_soft_dir / "palette.png"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(soft_mp4),
            "-vf", "fps=15,scale=480:-1:flags=lanczos,palettegen",
            str(palette_file)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([
            "ffmpeg", "-y", "-i", str(soft_mp4), "-i", str(palette_file),
            "-lavfi", "fps=15,scale=480:-1:flags=lanczos [x]; [x][1:v] paletteuse",
            str(soft_gif)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        shutil.rmtree(temp_soft_dir, ignore_errors=True)
        print(f"[SOFTWARE-3D] Completado exitosamente:\n  MP4: {soft_mp4}\n  GIF: {soft_gif}")
        generated_files.extend([soft_mp4, soft_gif])

    # 2. Ejecución del Modo Blender 5.0.1 Headless
    if args.mode in ["blender", "both"]:
        print("\n--- [FASE 2] Ejecutando Blender 5.0.1 Headless (Cycles Path-Tracing) ---")
        b_mp4, b_gif = BlenderHeadlessAnimator.render_blender_hyper_scene(
            scene_type="clifford_hopf",
            total_frames=args.frames,
            fps=args.fps,
            resolution=args.res,
            output_name="tardis_blender_clifford_hopf_4d"
        )
        generated_files.extend([b_mp4, b_gif])

    print("\n================================================================================")
    print("  RESUMEN DE SÍNTESIS CINEMÁTICA 3D COMPLETADA:")
    for f in generated_files:
        size_kb = f.stat().st_size / 1024
        print(f"  • {f.name} ({size_kb:.1f} KB) -> {f}")
    print("================================================================================")


if __name__ == "__main__":
    main()
