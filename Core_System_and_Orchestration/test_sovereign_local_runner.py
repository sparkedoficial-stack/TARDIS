"""
tests/test_sovereign_local_runner.py - Pruebas del Ejecutor Soberano Local Serverless
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.sovereign_local_runner import (
    OllamaModelInspector,
    SovereignLocalRunner,
    get_local_runner,
    get_sovereign_local_runner,
)


class TestSovereignLocalRunner(unittest.TestCase):

    def test_singleton_accessor(self):
        r1 = get_local_runner()
        r2 = get_sovereign_local_runner()
        self.assertIs(r1, r2)

    def test_ollama_model_inspector_list_models(self):
        models = OllamaModelInspector.list_models()
        self.assertIsInstance(models, list)
        if models:
            first = models[0]
            self.assertIn("name", first)
            self.assertIn("gguf_path", first)
            self.assertIn("size_gb", first)

    def test_ollama_model_inspector_inspect_kaiju(self):
        info = OllamaModelInspector.inspect_model("TARDIS-NEURAL-SPACE-KAIJU")
        if info:
            self.assertEqual(info["model_name"], "TARDIS-NEURAL-SPACE-KAIJU")
            self.assertTrue(Path(info["gguf_path"]).exists())
            self.assertGreater(info["size_bytes"], 1024 * 1024)

    def test_cuda_environment_resolution(self):
        runner = SovereignLocalRunner(model_name="TARDIS-NEURAL-SPACE-KAIJU")
        env, cuda_backend = runner._get_cuda_environment()
        self.assertIn("LD_LIBRARY_PATH", env)
        if cuda_backend:
            self.assertIn("GGML_BACKEND_PATH", env)
            self.assertEqual(env.get("CUDA_VISIBLE_DEVICES"), "0")

    def test_is_serverless_ready(self):
        runner = SovereignLocalRunner(model_name="TARDIS-NEURAL-SPACE-KAIJU")
        ready = runner.is_serverless_ready()
        self.assertIsInstance(ready, bool)

    @patch("httpx.Client")
    def test_chat_mocked_success(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Soberano listo."}}],
            "usage": {"completion_tokens": 5, "prompt_tokens": 10}
        }
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        runner = SovereignLocalRunner(model_name="TARDIS-NEURAL-SPACE-KAIJU")
        with patch.object(runner, "is_running", return_value=True):
            res = runner.chat([{"role": "user", "content": "Hola"}])
            self.assertTrue(res["ok"])
            self.assertEqual(res["reply"], "Soberano listo.")
            self.assertEqual(res["engine"], "sovereign_direct_ipc")

    @patch("httpx.Client")
    def test_chat_stream_mocked(self, mock_client_cls):
        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "Hola "}}]}',
            'data: {"choices": [{"delta": {"content": "Soberano"}}]}',
            'data: [DONE]'
        ]
        mock_client.stream.return_value.__enter__.return_value = mock_stream_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        runner = SovereignLocalRunner(model_name="TARDIS-NEURAL-SPACE-KAIJU")
        with patch.object(runner, "is_running", return_value=True):
            gen = runner.chat_stream([{"role": "user", "content": "Hola"}])
            chunks = list(gen)
            self.assertEqual(chunks, ["Hola ", "Soberano"])


if __name__ == "__main__":
    unittest.main()
