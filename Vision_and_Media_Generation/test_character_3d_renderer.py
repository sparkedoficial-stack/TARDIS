"""Pruebas unitarias aisladas para core/character_3d_renderer.py (COEV-20261123-ADB934)."""
from __future__ import annotations

import numpy as np
import pytest

from core import character_3d_renderer as c3d


def test_color_and_geometry_primitives_integrity():
    fb = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    vec = c3d._hex_to_vec("#00ffff", fb)
    assert vec.shape == (3,)
    assert np.allclose(vec, [0.0, 255.0, 255.0], atol=1e-3)

    fallback = c3d._hex_to_vec("not-a-color", fb)
    assert np.allclose(fallback, [10.0, 20.0, 30.0], atol=1e-3)

    tc_lo = c3d._thermal_color(0.0)
    tc_hi = c3d._thermal_color(1.0)
    assert tc_lo.shape == (3,) and tc_hi.shape == (3,)
    assert not np.allclose(tc_lo, tc_hi)

    pts = np.array([[3.0, 4.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float32)
    normed = c3d._normalize_rows(pts)
    assert np.isclose(np.linalg.norm(normed[0]), 1.0, atol=1e-5)

    for mesh_fn, kwargs in (
        (c3d.icosphere, {"subdivisions": 1, "radius": 1.0}),
        (c3d.torus, {"R": 1.0, "r": 0.25, "seg_u": 12, "seg_v": 8}),
        (c3d.cylinder, {"radius": 0.5, "height": 1.0, "segments": 10}),
        (c3d.rounded_box, {"sx": 1.0, "sy": 0.8, "sz": 0.6, "subdiv": 1}),
    ):
        verts, faces = mesh_fn(**kwargs)
        assert verts.ndim == 2 and verts.shape[1] == 3 and len(verts) > 0
        assert faces.ndim == 2 and faces.shape[1] == 3 and len(faces) > 0
        assert int(faces.max()) < len(verts)

    for sub_mesh in c3d.build_beveled_triangle_hull():
        verts, faces = sub_mesh
        assert verts.ndim == 2 and verts.shape[1] == 3 and len(verts) > 0
        assert faces.ndim == 2 and faces.shape[1] == 3 and len(faces) > 0
        assert int(faces.max()) < len(verts)


def test_matrix_transforms_and_render_frame_small():
    pts = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    m = c3d.mat_translate(2.0, 3.0, -1.0) @ c3d.mat_scale(2.0, 1.0, 1.0)
    out = c3d.transform_points(m, pts)
    assert np.allclose(out[0], [4.0, 3.0, -1.0], atol=1e-4)

    renderer = c3d.Character3DRenderer(quality="low")
    frame = renderer.render_frame(t=0.25, width=96, height=96, state={"energy": 0.4, "speaking": 0.2})
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (96, 96, 3)
    assert frame.dtype == np.uint8
    assert int(frame.max()) > 0

    post = c3d.Character3DRenderer.post_process(frame, bloom=0.2, vignette=0.15, grain=0.02, chroma=0.0, seed=42)
    assert post.shape == frame.shape and post.dtype == np.uint8
