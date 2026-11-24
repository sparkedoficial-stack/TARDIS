"""
tests/test_gia_sovereign_engine.py
==================================
Pruebas unitarias deterministas para el enrutamiento GPU-lane (:11435) y guardia
anti-duplicación CPU (:11434) en `gia_sovereign_engine.py` (COEV-20261123-D0A4DE).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _FakeHTTPResp:
    def __init__(self, lines: list[bytes], status: int = 200):
        self._lines = lines
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return b"".join(self._lines)

    def close(self):
        pass


def test_gia_logger_and_model_classifiers():
    import gia_sovereign_engine as gse

    assert hasattr(gse, "logger")
    assert gse._is_vlm_model("qwen3-vl:2b-instruct") is True
    assert gse._is_vlm_model("minicpm-v:latest") is True
    assert gse._is_vlm_model("TARDIS-NEURAL-SPACE-KAIJU") is False
    assert gse._is_kaiju_model("TARDIS-NEURAL-SPACE-KAIJU:latest") is True
    assert gse._is_gpu_lane_endpoint("http://127.0.0.1:11435") is True
    assert gse._is_local_cpu_ollama_endpoint("http://127.0.0.1:11434") is True


def test_find_working_endpoint_prefers_gpu_lane_for_vlm_even_under_load():
    import gia_sovereign_engine as gse

    eng = gse.SovereignInferenceEngine.__new__(gse.SovereignInferenceEngine)
    eng.preferred_endpoint = "http://127.0.0.1:11434"
    eng.active_endpoint = None

    with (
        patch.object(eng, "_probe_endpoint", return_value=False),
        patch.object(eng, "_is_tcp_reachable", side_effect=lambda ep, timeout=0.8: ep.endswith(":11435")),
        patch("gia_sovereign_engine.time.sleep", return_value=None),
    ):
        ep = eng.find_working_endpoint(model="qwen3-vl:2b-instruct")
        assert ep == gse.OLLAMA_GPU_LANE_URL


def test_http_chat_stream_aligns_gpu_lane_and_evicts_cpu_fallback(monkeypatch):
    import gia_sovereign_engine as gse

    eng = gse.SovereignInferenceEngine.__new__(gse.SovereignInferenceEngine)
    eng.preferred_endpoint = "http://127.0.0.1:11434"
    eng.active_endpoint = None

    captured = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        captured.append((req.full_url, body))
        line = json.dumps({"message": {"content": "ok"}}).encode("utf-8") + b"\n"
        return _FakeHTTPResp([line])

    monkeypatch.delenv("GIA_OLLAMA_FALLBACK_KEEP_ALIVE", raising=False)

    # Caso 1: Carril GPU (:11435) -> keep_alive=-1, num_ctx=3072, num_gpu=22
    with (
        patch.object(eng, "find_working_endpoint", return_value="http://127.0.0.1:11435"),
        patch("gia_sovereign_engine.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        chunks = list(eng._http_chat_stream([{"role": "user", "content": "hola"}], model="qwen3-vl:2b-instruct", num_ctx=4096))
        assert chunks == ["ok"]
        url, payload = captured[-1]
        assert url == "http://127.0.0.1:11435/api/chat"
        assert payload["keep_alive"] == -1
        assert payload["options"]["num_ctx"] == gse.OLLAMA_GPU_LANE_NUM_CTX
        assert payload["options"]["num_gpu"] == gse.OLLAMA_GPU_LANE_NUM_GPU

    # Caso 2: Respaldo frío CPU (:11434) -> keep_alive=0 (sin retención duplicada)
    with (
        patch.object(eng, "find_working_endpoint", return_value="http://127.0.0.1:11434"),
        patch("gia_sovereign_engine.urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        chunks = list(eng._http_chat_stream([{"role": "user", "content": "hola"}], model="qwen3-vl:2b-instruct", num_ctx=4096))
        assert chunks == ["ok"]
        url, payload = captured[-1]
        assert url == "http://127.0.0.1:11434/api/chat"
        assert payload["keep_alive"] == 0
        assert "num_gpu" not in payload["options"]
