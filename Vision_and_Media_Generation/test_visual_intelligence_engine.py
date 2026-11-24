"""
tests/test_visual_intelligence_engine.py
========================================
Pruebas unitarias para el enrutamiento VLM al carril GPU (:11435), alineación de
contexto (`num_ctx=3072`, `num_gpu=22`) y descarga inmediata (`keep_alive=0`) en
respaldo frío CPU (:11434) de `core/visual_intelligence_engine.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_resolve_vlm_url_keeps_gpu_lane_when_tcp_busy():
    from core import visual_intelligence_engine as vie

    with (
        patch.object(vie.requests, "get", side_effect=TimeoutError("busy")),
        patch.object(vie, "_is_tcp_reachable", return_value=True),
        patch.object(vie.time, "sleep", return_value=None),
    ):
        assert vie._resolve_vlm_ollama_url() == vie.OLLAMA_GPU_LANE_URL


def test_resolve_vlm_url_falls_back_only_when_gpu_lane_down():
    from core import visual_intelligence_engine as vie

    ok_resp = MagicMock(status_code=200)

    def fake_get(url, timeout=None):
        if ":11435" in url:
            raise ConnectionRefusedError("11435 down")
        return ok_resp

    with (
        patch.object(vie.requests, "get", side_effect=fake_get),
        patch.object(vie, "_is_tcp_reachable", return_value=False),
        patch.object(vie.time, "sleep", return_value=None),
    ):
        assert vie._resolve_vlm_ollama_url() == vie.OLLAMA_URL


def test_ollama_vision_call_aligns_gpu_options_and_evicts_cpu_fallback():
    from core import visual_intelligence_engine as vie

    eng = vie.VisualIntelligenceEngine.__new__(vie.VisualIntelligenceEngine)
    captured = []

    def fake_post(url, json=None, timeout=None):
        captured.append((url, json))
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"response": "Escritorio con monitor encendido."}
        return resp

    # 1. Carril GPU :11435 -> num_ctx <= 3072, num_gpu=22, keep_alive=-1
    with (
        patch.object(vie, "_resolve_vlm_ollama_url", return_value=vie.OLLAMA_GPU_LANE_URL),
        patch.object(vie.requests, "post", side_effect=fake_post),
    ):
        res = eng._ollama_vision_call("ZmFrZQ==", "Describe", "qwen3-vl:2b-instruct", num_ctx=4096)
        assert res["ok"] is True
        assert res["endpoint"] == vie.OLLAMA_GPU_LANE_URL
        url, payload = captured[-1]
        assert url == f"{vie.OLLAMA_GPU_LANE_URL}/api/generate"
        assert payload["keep_alive"] == -1
        assert payload["options"]["num_ctx"] == vie.OLLAMA_GPU_LANE_NUM_CTX
        assert payload["options"]["num_gpu"] == vie.OLLAMA_GPU_LANE_NUM_GPU

    # 2. Respaldo frío CPU :11434 -> keep_alive=0, sin num_gpu
    with (
        patch.object(vie, "_resolve_vlm_ollama_url", return_value=vie.OLLAMA_URL),
        patch.object(vie.requests, "post", side_effect=fake_post),
    ):
        res = eng._ollama_vision_call("ZmFrZQ==", "Describe", "qwen3-vl:2b-instruct", num_ctx=3072)
        assert res["ok"] is True
        assert res["endpoint"] == vie.OLLAMA_URL
        url, payload = captured[-1]
        assert url == f"{vie.OLLAMA_URL}/api/generate"
        assert payload["keep_alive"] == 0
        assert "num_gpu" not in payload["options"]
