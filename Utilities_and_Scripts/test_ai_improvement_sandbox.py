"""
tests/test_ai_improvement_sandbox.py - Pruebas del Sandbox de Mejora y Calibración de IA
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.ai_improvement_sandbox import (
    AISandboxDatasetCompiler,
    AISandboxEvaluator,
    AISandboxQuantizationLab,
    BENCHMARK_CASES,
)


class TestAISandbox(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.history_file = Path(self.temp_dir) / "eval_history.json"
        self.dataset_file = Path(self.temp_dir) / "training_pairs.jsonl"
        self.quant_dir = Path(self.temp_dir) / "quantized"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_evaluator_scoring_logic(self):
        evaluator = AISandboxEvaluator(history_file=self.history_file)

        # Mock inference function that passes privacy Aegis, Identity, and Python checks
        def mock_infer(prompt: str, system: str = "") -> str:
            if "creador" in prompt:
                return "Mi creador es el Arquitecto del nodo local."
            if "propósito" in prompt or "quién eres" in prompt.lower():
                return "Soy TARDIS, una inteligencia artificial para descubrir las maravillas de la realidad."
            if "entropía" in prompt.lower():
                return "La entropía dispersa energía mientras que la sintropía concentra coherencia temporal en el sistema ECCA."
            if "volumen" in prompt.lower():
                return "Ajustando volumen a 30% y teclado en nivel 2."
            if "calcular_entropia_shannon" in prompt or "Python" in prompt:
                return "```python\nimport math\ndef calcular_entropia_shannon(probabilidades):\n    return -sum(p * math.log2(p) for p in probabilidades if p > 0)\n```"
            return "Respuesta simulada soberana."

        res = evaluator.run_benchmark_suite(infer_func=mock_infer)
        self.assertIsInstance(res, dict)
        self.assertGreaterEqual(res["overall_score"], 50.0)
        self.assertEqual(len(res["cases"]), 5)
        self.assertTrue(self.history_file.exists())

        # Check history retrieval
        history = evaluator.get_evaluation_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["model_name"], "TARDIS-NEURAL-SPACE-KAIJU")

    def test_dataset_compiler_add_and_stats(self):
        compiler = AISandboxDatasetCompiler(dataset_file=self.dataset_file)
        
        compiler.add_pair(
            instruction="¿Cuál es tu función?",
            response="Procesar y proteger las líneas temporales del nodo local.",
            source="test_manual",
            category="identity"
        )
        
        compiler.add_pair(
            instruction="Sintetiza hardware cuántico",
            response="Generando RTL Verilog para acelerador sistólico.",
            source="test_manual",
            category="hardware"
        )

        stats = compiler.get_dataset_stats()
        self.assertEqual(stats["total_pairs"], 2)
        self.assertEqual(stats["categories"].get("identity"), 1)
        self.assertEqual(stats["categories"].get("hardware"), 1)
        self.assertTrue(self.dataset_file.exists())

    def test_quantization_lab_supported_types(self):
        lab = AISandboxQuantizationLab(output_dir=self.quant_dir)
        types = lab.get_supported_quant_types()
        self.assertIn("Q4_K_M", types)
        self.assertIn("Q5_K_M", types)
        self.assertIn("Q8_0", types)

    def test_quantization_lab_missing_model(self):
        lab = AISandboxQuantizationLab(output_dir=self.quant_dir)
        res = lab.quantize_model("/tmp/nonexistent_model.gguf", "Q4_K_M")
        self.assertFalse(res["ok"])
        self.assertIn("no encontrado", res["error"])


if __name__ == "__main__":
    unittest.main()
