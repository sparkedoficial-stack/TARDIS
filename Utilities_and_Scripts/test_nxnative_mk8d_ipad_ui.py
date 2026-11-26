"""Pruebas unitarias aisladas para core/nxnative_mk8d_ipad_ui.py (COEV-20261123-ADB934)."""
from __future__ import annotations

from core.nxnative_mk8d_ipad_ui import get_nxnative_mk8d_html


def test_nxnative_mk8d_ipad_html_structure_and_controls():
    html = get_nxnative_mk8d_html()
    assert isinstance(html, str) and len(html) > 5000
    low = html.lower()
    assert "<!doctype html>" in low
    assert "<html" in low and "</html>" in low
    assert "<canvas" in low or "video" in low
    assert "viewport" in low
    assert "<script" in low and "</script>" in low
