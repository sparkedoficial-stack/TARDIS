"""Pruebas unitarias aisladas para core/chronovision_engine.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

from core import chronovision_engine as cve


def test_chrono_grapher_plot_2d_and_attractor():
    grapher = cve.ChronoGrapher()
    res_2d = grapher.plot_2d_function("sin(x) * cos(x)", x_min=-6.28, x_max=6.28, title="Test 2D", points=120)
    assert res_2d.ok is True
    assert res_2d.bytes_data and len(res_2d.bytes_data) > 500
    assert res_2d.media_type == "photo"

    res_attr = grapher.plot_attractor("lorenz", steps=300, title="Lorenz Test")
    assert res_attr.ok is True
    assert res_attr.bytes_data and len(res_attr.bytes_data) > 500


def test_chrono_painter_sacred_geometry_and_temporal_clock():
    painter = cve.ChronoPainter(width=320, height=240)
    res_geo = painter.draw_sacred_geometry("metatron", recipient="Arquitecto")
    assert res_geo.ok is True and res_geo.bytes_data
    img = Image.open(__import__("io").BytesIO(res_geo.bytes_data))
    assert img.size == (320, 240)

    res_clk = painter.draw_temporal_clock(topic="Reloj Cuántico", recipient="Arquitecto")
    assert res_clk.ok is True and res_clk.bytes_data


def test_chronovision_engine_process_request_isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cve, "DATA_DIR", tmp_path)
    engine = cve.ChronoVisionEngine()
    res = engine.process_request("dibuja geometria sagrada metatron", recipient="Arquitecto", prefer_animation=False)
    assert isinstance(res, cve.ChronoVisionResult)
    assert res.ok is True
    assert res.bytes_data and len(res.bytes_data) > 500
