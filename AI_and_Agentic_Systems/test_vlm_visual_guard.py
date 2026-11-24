"""
tests/test_vlm_visual_guard.py
==============================
Pruebas unitarias para el enrutamiento al carril GPU (:11435) y prevención de
duplicados en CPU (:11434) en `vlm_visual_guard.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_active_vlm_endpoint_prefers_gpu_lane_when_tcp_alive():
    import vlm_visual_guard as vvg

    with (
        patch.object(vvg.httpx, "get", side_effect=TimeoutError("busy")),
        patch.object(vvg, "_is_tcp_reachable", return_value=True),
        patch.object(vvg.time, "sleep", return_value=None),
    ):
        assert vvg._active_vlm_endpoint() == vvg.OLLAMA_GPU_URL


def test_inspect_image_uses_gpu_lane_params_and_zero_keepalive_on_cpu_fallback():
    import vlm_visual_guard as vvg

    captured = []

    def fake_post(url, json=None, timeout=None):
        captured.append((url, json))
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"response": "Ventana activa de terminal."}
        return resp

    # 1. Carril GPU :11435
    with (
        patch.object(vvg, "_active_vlm_endpoint", return_value=vvg.OLLAMA_GPU_URL),
        patch.object(vvg.httpx, "post", side_effect=fake_post),
    ):
        res = vvg.inspect_image(b"fake-jpeg-bytes", prompt="Describe", model="qwen3-vl:2b-instruct")
        assert res["ok"] is True
        assert res["endpoint"] == vvg.OLLAMA_GPU_URL
        url, payload = captured[-1]
        assert url == f"{vvg.OLLAMA_GPU_URL}/api/generate"
        assert payload["keep_alive"] == -1
        assert payload["think"] is False
        assert payload["options"]["num_ctx"] == vvg.OLLAMA_GPU_NUM_CTX
        assert payload["options"]["num_gpu"] == vvg.OLLAMA_GPU_NUM_GPU

    # 2. Respaldo frío CPU :11434
    with (
        patch.object(vvg, "_active_vlm_endpoint", return_value=vvg.OLLAMA_URL),
        patch.object(vvg.httpx, "post", side_effect=fake_post),
    ):
        res = vvg.inspect_image(b"fake-jpeg-bytes", prompt="Describe", model="qwen3-vl:2b-instruct")
        assert res["ok"] is True
        assert res["endpoint"] == vvg.OLLAMA_URL
        url, payload = captured[-1]
        assert url == f"{vvg.OLLAMA_URL}/api/generate"
        assert payload["keep_alive"] == 0
        assert "num_gpu" not in payload["options"]
