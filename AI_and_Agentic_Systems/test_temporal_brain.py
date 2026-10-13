"""
tests/test_temporal_brain.py - Pruebas Exhaustivas de Temporal Brain
===================================================================
Verifica:
1. Inicialización y Singleton de Temporal Brain.
2. Configuración declarativa en caliente (TemporalBrainConfig).
3. Hooks de inferencia (pre-hooks, post-hooks y stream filters).
4. Registro y ejecución de herramientas y funciones dinámicas (@tool).
5. Sistema de adaptadores modulares (TemporalBrainAdapter).
6. Adaptadores integrados (HardwareControlAdapter, SystemTelemetryAdapter).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.temporal_brain import (
    HardwareControlAdapter,
    SystemTelemetryAdapter,
    TemporalBrain,
    TemporalBrainAdapter,
    TemporalBrainConfig,
    TemporalBrainFunctionRegistry,
    get_temporal_brain,
)


class CustomTestAdapter(TemporalBrainAdapter):
    """Adaptador de prueba para validar la extensibilidad de Temporal Brain."""

    def __init__(self):
        super().__init__(name="custom_test_adapter")
        self.init_called = False

    def on_init(self, brain: TemporalBrain):
        self.init_called = True

    def pre_inference(self, messages, options):
        # Agrega un mensaje de sistema extra
        new_msgs = list(messages) + [{"role": "system", "content": "[ADAPTER-ACTIVE]"}]
        return new_msgs, options

    def post_inference(self, result):
        result["adapter_custom_tag"] = "processed_by_adapter"
        return result

    def on_stream_token(self, token: str):
        return token.upper()


class TestTemporalBrain(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "temporal_brain_config.json"
        self.config_data = {
            "system_name": "Temporal Brain Test",
            "model": "TARDIS-NEURAL-SPACE-KAIJU",
            "socket_path": "/tmp/test_temporal_brain.sock",
            "temperature": 0.2,
            "max_tokens": 1024,
            "hooks": {
                "enable_pre_hooks": True,
                "enable_post_hooks": True,
                "enable_stream_filters": True,
            },
            "adapters": {}
        }
        self.config_path.write_text(json.dumps(self.config_data, indent=2), encoding="utf-8")

    def test_config_loader_and_hot_reload(self):
        cfg = TemporalBrainConfig(self.config_path)
        self.assertEqual(cfg.get("system_name"), "Temporal Brain Test")
        self.assertEqual(cfg.get("temperature"), 0.2)

        # Modificar archivo para probar recarga en caliente
        self.config_data["temperature"] = 0.5
        # Cambiar mtime para disparar reload
        self.config_path.write_text(json.dumps(self.config_data, indent=2), encoding="utf-8")
        os.utime(self.config_path, (time_val := os.path.getmtime(self.config_path) + 2, time_val))

        cfg.check_update()
        self.assertEqual(cfg.get("temperature"), 0.5)

    def test_singleton_accessor(self):
        b1 = get_temporal_brain()
        b2 = get_temporal_brain()
        self.assertIs(b1, b2)

    def test_function_registry_and_tool_decorator(self):
        brain = TemporalBrain(config_path=self.config_path)

        @brain.tool(name="calcular_delta_temporal", description="Calcula desfase de tiempo en ms")
        def calcular_delta(t1: float, t2: float) -> float:
            return abs(t2 - t1) * 1000.0

        # Verificar catálogo
        funcs = brain.functions.list_functions()
        self.assertIn("calcular_delta_temporal", funcs)
        self.assertIn("t1", funcs["calcular_delta_temporal"]["parameters"])

        # Ejecutar función dinámicamente
        res = brain.functions.execute("calcular_delta_temporal", t1=10.0, t2=10.05)
        self.assertAlmostEqual(res, 50.0)

    @patch("httpx.Client")
    def test_pre_and_post_hooks_pipeline(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Respuesta original de inferencia."}}],
            "usage": {"completion_tokens": 10}
        }
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        brain = TemporalBrain(config_path=self.config_path)

        # Hook 1: Pre-inferencia
        def custom_pre_hook(messages, options):
            messages.append({"role": "system", "content": "[PRE_HOOK_INJECTED]"})
            options["temperature"] = 0.77
            return messages, options

        # Hook 2: Post-inferencia
        def custom_post_hook(result):
            result["reply"] += " [POST_HOOK_VERIFIED]"
            result["hook_verified"] = True
            return result

        brain.register_pre_hook(custom_pre_hook)
        brain.register_post_hook(custom_post_hook)

        with patch.object(brain, "is_running", return_value=True):
            res = brain.chat([{"role": "user", "content": "Hola Temporal Brain"}])
            self.assertTrue(res["ok"])
            self.assertIn("[POST_HOOK_VERIFIED]", res["reply"])
            self.assertTrue(res.get("hook_verified"))

    @patch("httpx.Client")
    def test_custom_adapter_lifecycle(self, mock_client_cls):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Respuesta del modelo."}}],
            "usage": {"completion_tokens": 5}
        }
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        brain = TemporalBrain(config_path=self.config_path)
        adapter = CustomTestAdapter()
        brain.register_adapter(adapter)

        self.assertTrue(adapter.init_called)
        self.assertIs(brain.get_adapter("custom_test_adapter"), adapter)

        with patch.object(brain, "is_running", return_value=True):
            res = brain.chat([{"role": "user", "content": "Test"}])
            self.assertTrue(res["ok"])
            self.assertEqual(res.get("adapter_custom_tag"), "processed_by_adapter")

    @patch("httpx.Client")
    def test_stream_filter(self, mock_client_cls):
        mock_client = MagicMock()
        mock_stream_resp = MagicMock()
        mock_stream_resp.iter_lines.return_value = [
            'data: {"choices": [{"delta": {"content": "token_a "}}]}',
            'data: {"choices": [{"delta": {"content": "token_b"}}]}',
            'data: [DONE]'
        ]
        mock_client.stream.return_value.__enter__.return_value = mock_stream_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        brain = TemporalBrain(config_path=self.config_path)

        # Filtro que añade prefijo a cada token
        def test_filter(token: str):
            return f"[{token.strip()}]"

        brain.register_stream_filter(test_filter)

        with patch.object(brain, "is_running", return_value=True):
            gen = brain.chat_stream([{"role": "user", "content": "Stream test"}])
            tokens = list(gen)
            self.assertEqual(tokens, ["[token_a]", "[token_b]"])

    def test_built_in_adapters(self):
        hw_adapter = HardwareControlAdapter()
        res_hw = hw_adapter.post_inference({"reply": "Ajustando volumen al 30% en el sistema."})
        self.assertIn("volume_directive", res_hw.get("hardware_directives", []))

        telemetry_adapter = SystemTelemetryAdapter(include_timestamp=True)
        msgs, _ = telemetry_adapter.pre_inference([{"role": "user", "content": "¿Estado del nodo?"}], {})
        self.assertIn("[Nodo Local:", msgs[-1]["content"])


if __name__ == "__main__":
    unittest.main()
